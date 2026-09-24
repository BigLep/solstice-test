#!/usr/bin/env bash
# Stage, propose, track and execute a UUPS upgrade of the SRA or SWA proxy recorded in deployments.json.
#
# Usage:
#   tools/upgrade.sh <sra|swa> <new-implementation> calldata   # verify the implementation, print calldata and task id
#   tools/upgrade.sh <sra|swa> <new-implementation> propose    # ...and propose the upgrade to both owner Safes
#   tools/upgrade.sh <sra|swa> <new-implementation> status     # show approvals and when the hold ends
#   tools/upgrade.sh <sra|swa> <new-implementation> execute    # send the upgrade once the hold has elapsed
#
# Environment:
#   ETH_RPC_URL           required; selects the network (chain id 314 or 314159)
#   PROPOSER_PRIVATE_KEY  key of the address registered as a proposer (delegate) on the owner Safes, for `propose`,
#                         or any funded key for `execute`. ETH_KEYSTORE_ACCOUNT is used instead if set.
#   UPGRADE_CALLDATA      optional `data` argument for upgradeToAndCall (a reinitializer call); default empty
#   DRY_RUN=1             for `propose`: print the Safe transaction payloads instead of submitting them
#
# `calldata` and `propose` first run script/Upgrade.s.sol, which rebuilds the implementation from the checked-out
# source and deployments.json and refuses to continue unless the on-chain runtime code matches, so the calldata
# always refers to code built from this commit. `propose` then submits the same transaction to each owner Safe
# through the Filecoin Safe Transaction Service; owners confirm and execute it in the Safe app. The hold starts
# when the second owner's transaction lands; after it, `execute` can be sent from any funded key.
set -euo pipefail

cd "$(dirname "$0")/.."

TARGET=${1:?usage: tools/upgrade.sh <sra|swa> <new-implementation> <calldata|propose|status|execute>}
NEW_IMPL=${2:?missing new implementation address}
MODE=${3:?missing mode}
: "${ETH_RPC_URL:?ETH_RPC_URL is required}"

IMPLEMENTATION_SLOT=0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc
PENDING_TASKS_SLOT=0x635f64a8ec66823e68578973f5bc466fd4e0eadd655f760cfc91e860524aa300

CHAIN_ID=$(cast chain-id --rpc-url "$ETH_RPC_URL")
case "$CHAIN_ID" in
    314) SAFE_SERVICE=https://transaction.safe.filecoin.io; SAFE_APP=https://safe.filecoin.io ;;
    314159) SAFE_SERVICE=https://transaction-testnet.safe.filecoin.io; SAFE_APP=https://safe.filecoin.io ;;
    *) SAFE_SERVICE=""; SAFE_APP="" ;;
esac

read -r PROXY OWNER1 OWNER2 HOLD < <(python3 - "$CHAIN_ID" "$TARGET" <<'EOF'
import json, sys
chain, target = sys.argv[1], sys.argv[2]
c = json.load(open('deployments.json'))[chain]
print(c[target], c[f'{target}Owner1'], c[f'{target}Owner2'], c['hold'])
EOF
)

key_args() {
    if [[ -n "${PROPOSER_PRIVATE_KEY:-}" ]]; then
        echo "--private-key $PROPOSER_PRIVATE_KEY"
    elif [[ -n "${ETH_KEYSTORE_ACCOUNT:-}" ]]; then
        echo "--account $ETH_KEYSTORE_ACCOUNT"
    else
        echo "PROPOSER_PRIVATE_KEY or ETH_KEYSTORE_ACCOUNT is required for $MODE" >&2
        exit 2
    fi
}

DATA=${UPGRADE_CALLDATA:-0x}
CALLDATA=$(cast calldata 'upgradeToAndCall(address,bytes)' "$NEW_IMPL" "$DATA")
TASK_ID=$(cast keccak "$CALLDATA")
TASK_SLOT=$(cast keccak "$(cast abi-encode 'f(bytes32,bytes32)' "$TASK_ID" "$PENDING_TASKS_SLOT")")

current_impl() {
    cast storage "$PROXY" "$IMPLEMENTATION_SLOT" --rpc-url "$ETH_RPC_URL" | sed 's/^0x000000000000000000000000/0x/'
}

verify_implementation() {
    echo "== Verifying $NEW_IMPL against a local build (script/Upgrade.s.sol) =="
    local out
    if ! out=$(TARGET="$TARGET" NEW_IMPLEMENTATION="$NEW_IMPL" UPGRADE_CALLDATA="$DATA" \
            forge script script/Upgrade.s.sol --rpc-url "$ETH_RPC_URL" 2>&1); then
        echo "$out" | grep -E 'Error|Revert' || echo "$out" | tail -20
        echo "implementation did not verify; not continuing" >&2
        exit 1
    fi
    local script_calldata
    script_calldata=$(echo "$out" | grep -A1 'send this exact calldata' | tail -1 | tr -d ' ')
    if [[ "$script_calldata" != "$CALLDATA" ]]; then
        echo "calldata mismatch between script ($script_calldata) and tools ($CALLDATA)" >&2
        exit 1
    fi
    echo "implementation runtime code matches the local build"
}

print_summary() {
    echo
    echo "== Upgrade $TARGET on chain $CHAIN_ID =="
    echo "proxy                   $PROXY"
    echo "current implementation  $(current_impl)"
    echo "new implementation      $NEW_IMPL"
    echo "owner Safes             $OWNER1  $OWNER2"
    echo "hold (epochs)           $HOLD"
    echo "task id                 $TASK_ID"
    echo "calldata (to proxy, value 0):"
    echo "$CALLDATA"
    echo "veto calldata (either owner, to proxy):"
    echo "$(cast calldata 'veto(bytes32)' "$TASK_ID")"
}

status() {
    local word modified approvals block impl
    word=$(cast storage "$PROXY" "$TASK_SLOT" --rpc-url "$ETH_RPC_URL")
    block=$(cast block-number --rpc-url "$ETH_RPC_URL")
    impl=$(current_impl)
    python3 - "$word" "$block" "$HOLD" "$impl" "$NEW_IMPL" <<'EOF'
import sys
word, block, hold, impl, new = int(sys.argv[1], 16), int(sys.argv[2]), int(sys.argv[3]), sys.argv[4].lower(), sys.argv[5].lower()
modified = word & ((1 << 64) - 1)
approvals = (word >> 64) & ((1 << 160) - 1)
n = bin(approvals).count('1')
print()
print('== Task status ==')
if impl == new:
    print('implementation slot already points at the new implementation: upgrade executed')
elif modified == 0:
    print('no pending task: nothing submitted yet, or the task was executed or vetoed')
else:
    print(f'approvals: {n} owner(s), last modified at epoch {modified}, current epoch {block}')
    if n >= 2:
        end = modified + hold
        left = end - block
        print(f'hold ends at epoch {end}' + (f' ({left} epochs, about {left * 30 // 3600}h to go)' if left > 0 else ': executable now'))
    else:
        print('waiting for the second owner; the hold starts when their transaction lands')
EOF
}

propose() {
    local args sender
    args=$(key_args)
    # shellcheck disable=SC2086
    sender=$(cast wallet address $args)
    [[ -n "$SAFE_SERVICE" ]] || { echo "no Safe Transaction Service known for chain $CHAIN_ID" >&2; exit 1; }
    echo
    echo "== Proposing to owner Safes as $sender via $SAFE_SERVICE =="
    for safe in "$OWNER1" "$OWNER2"; do
        local nonce hash sig payload
        nonce=$(curl -sf "$SAFE_SERVICE/api/v1/safes/$safe/multisig-transactions/?executed=false&limit=100" \
            | python3 -c 'import sys,json; d=json.load(sys.stdin); ns=[t["nonce"] for t in d["results"]]; print(max(ns)+1 if ns else "")')
        if [[ -z "$nonce" ]]; then
            nonce=$(cast call "$safe" 'nonce()(uint256)' --rpc-url "$ETH_RPC_URL")
        fi
        hash=$(cast call "$safe" \
            'getTransactionHash(address,uint256,bytes,uint8,uint256,uint256,uint256,address,address,uint256)(bytes32)' \
            "$PROXY" 0 "$CALLDATA" 0 0 0 0 0x0000000000000000000000000000000000000000 0x0000000000000000000000000000000000000000 "$nonce" \
            --rpc-url "$ETH_RPC_URL")
        # shellcheck disable=SC2086
        sig=$(cast wallet sign --no-hash "$hash" $args)
        payload=$(python3 - "$PROXY" "$CALLDATA" "$nonce" "$hash" "$sender" "$sig" <<'EOF'
import json, sys
to, data, nonce, h, sender, sig = sys.argv[1:]
print(json.dumps({
    "to": to, "value": "0", "data": data, "operation": 0,
    "safeTxGas": "0", "baseGas": "0", "gasPrice": "0",
    "gasToken": "0x0000000000000000000000000000000000000000",
    "refundReceiver": "0x0000000000000000000000000000000000000000",
    "nonce": int(nonce), "contractTransactionHash": h,
    "sender": sender, "signature": sig, "origin": "solstice tools/upgrade.sh",
}))
EOF
)
        echo "Safe $safe: nonce $nonce, safeTxHash $hash"
        if [[ "${DRY_RUN:-}" == "1" ]]; then
            echo "$payload"
            continue
        fi
        if curl -sf -X POST -H 'Content-Type: application/json' -d "$payload" \
                "$SAFE_SERVICE/api/v1/safes/$safe/multisig-transactions/" > /dev/null; then
            echo "  proposed; owners confirm at $SAFE_APP (transactions queue for $safe)"
        else
            echo "  proposal rejected by the service. Is $sender registered as a proposer on $safe? (see docs/UPGRADE.md)" >&2
            exit 1
        fi
    done
}

execute() {
    local args
    args=$(key_args)
    echo
    echo "== Executing upgrade =="
    # shellcheck disable=SC2086
    cast send "$PROXY" "$CALLDATA" --rpc-url "$ETH_RPC_URL" $args
    echo "implementation slot now $(current_impl)"
}

case "$MODE" in
    calldata) verify_implementation; print_summary ;;
    propose) verify_implementation; print_summary; propose ;;
    status) print_summary; status ;;
    execute) status; execute; status ;;
    *) echo "unknown mode: $MODE" >&2; exit 2 ;;
esac
