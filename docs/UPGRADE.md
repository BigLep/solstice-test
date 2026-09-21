# SRA and SWA upgrade runbook

This is the operator procedure for replacing the implementation behind a live ServiceRewardsActor (SRA) or StreamWeightActor (SWA) proxy. It applies to both calibration and mainnet. Calibration always goes first, and mainnet does not start until the calibration evidence table is complete and the technical owner has signed off.

Read [DEPLOYMENT.md](./DEPLOYMENT.md) first if you have not; it defines the roles, the config file and the verification script that this document reuses.

## How the mechanism works

Each proxy is an OpenZeppelin `ERC1967Proxy` whose implementation inherits `UUPSUpgradeable` through `src/lib/UnanimousProxied.sol`. There is no admin contract, no timelock contract and no Safe module. The upgrade entry point is the standard `upgradeToAndCall(address newImplementation, bytes data)` on the proxy, and it is gated by the `unanimous` modifier with the hold that was fixed at deployment (`SRA_UPGRADE_HOLD()` for SRA, the `hold` config value for both).

A task is identified by `keccak256(msg.data)`, so the task id is determined by the new implementation address and the `data` argument. The lifecycle is:

| Step | Who | What happens on chain |
|---|---|---|
| Submit | Owner 1 | Sends `upgradeToAndCall(newImpl, data)`. Emits `Submitted(taskId)` and `Approved(taskId, owner1)`. Nothing else changes. |
| Approve | Owner 2 | Sends byte-identical calldata. Emits `Approved(taskId, owner2)`. The task is now unanimous and the hold clock starts at this block. |
| Hold | Anyone watching | Execution reverts with `HoldUntil(epoch)` until `approvalBlock + hold`. Either owner may `veto(taskId)` at any time before execution. |
| Execute | Anyone | Sends the same calldata again after the hold. The implementation slot changes, `data` (if any) is delegatecalled, and the task is deleted. |

Consequences that matter operationally:

- Owner 2 must send exactly the calldata owner 1 sent. A different `data`, a different checksum of the address does not matter, but a single differing byte creates a new task rather than an approval.
- The call must carry zero value. `nonpayablePayable` rejects anything else.
- `data` is normally empty. `initialize()` cannot be called again (it is guarded by `initializer` and the proxy is at version 1). If a new implementation needs a migration, it must expose a `reinitializer(2)` function and `data` must encode that call.
- The hold is measured in epochs (blocks) from owner 2's approval block, not from owner 1's submission.
- Rollback before execution is a veto. Rollback after execution is a brand-new upgrade back to the previous implementation, with its own full hold.
- Owner replacement (`replaceOwner`) is a separate unanimous flow with no hold. Veto any pending tasks before replacing an owner, otherwise the freed approval bit can be recycled to the new owner with a stale approval attached.

The owners are expected to be multisigs. This document therefore never assumes an owner can run a Foundry script; each owner action is "send this exact calldata to this address with zero value" through whatever interface the multisig uses.

## Prerequisites

- Same as deployment: Foundry `v1.7.1`, submodules initialized, `ETH_RPC_URL`, a funded deployer key for the implementation deployment, and a tracking issue with the evidence table below.
- `deployments.json` on the release commit must contain the live proxy addresses for the target chain and the constructor parameters those proxies were deployed with. `script/Upgrade.s.sol` reuses them for the new implementation, so a parameter change is a deliberate edit to `deployments.json` in the release PR.

## Phase 1: Prepare the release

1. Merge the code change. Open a tracking issue for the upgrade with: target (SRA, SWA or both), networks, the reason, the frozen commit, the current implementation address per network, and the rollback disposition (see Phase 6).
2. Storage safety. The proxies keep all state in ERC-7201 namespaced structs, so `forge inspect ... storageLayout` is empty and cannot catch a layout break. CI enforces `tools/storage-layout-snapshot.sh --check` instead, which diffs every namespaced struct and slot constant against `storage-layout/namespaced.txt`. On an upgrade PR, review that diff against these rules:
   - Allowed: appending a field at the end of an existing struct; adding a whole new namespace with a new slot constant.
   - Breaking: removing, reordering, retyping or inserting a field; changing a slot constant; changing a nested struct that an existing struct embeds. A breaking change cannot ship behind a live proxy without an explicit migration in `data` and a written argument for why the old state is safe to reinterpret.
   - Also check any change to `Initializable` or `UUPSUpgradeable` in the OpenZeppelin submodule bump, since those share the proxy's storage.
3. Tests. `forge test` must pass with `FOUNDRY_PROFILE=ci`, including `test/UnanimousProxied.t.sol`, which exercises the submit, approve, hold, execute and veto paths.
4. Fork rehearsal. Run the whole flow against a local anvil fork of the target network before touching the real one. The following sequence is what this runbook was validated with and takes a few minutes:

```sh
anvil --fork-url $ETH_RPC_URL --port 8545 &
RPC=http://127.0.0.1:8545
TARGET=sra forge script script/Upgrade.s.sol --rpc-url $RPC --broadcast --private-key $ANY_FUNDED_ANVIL_KEY
# copy PROXY, NEW and the calldata (CALL) from the script output, then impersonate the owners
for O in $OWNER1 $OWNER2; do
  cast rpc anvil_impersonateAccount $O --rpc-url $RPC
  cast rpc anvil_setBalance $O 0x3635c9adc5dea00000 --rpc-url $RPC
done
cast send $PROXY $CALL --from $OWNER1 --unlocked --rpc-url $RPC
cast send $PROXY $CALL --from $OWNER2 --unlocked --rpc-url $RPC
cast send $PROXY $CALL --private-key $ANY_FUNDED_ANVIL_KEY --rpc-url $RPC   # expect revert HoldUntil (0xbb1f322f)
cast rpc anvil_mine $(cast to-hex $HOLD) --rpc-url $RPC
cast send $PROXY $CALL --private-key $ANY_FUNDED_ANVIL_KEY --rpc-url $RPC   # executes
cast storage $PROXY 0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc --rpc-url $RPC  # expect NEW
forge script script/Verify.s.sol --rpc-url $RPC   # expect ALL CHECKS PASSED
```

   Paste the rehearsal output into the tracking issue. If the change needs a reinitializer, rehearse with `UPGRADE_CALLDATA=<encoded call>` set for the `Upgrade.s.sol` run and confirm the post-state.

5. Tag the frozen commit (for example `upgrade-sra-calibnet-YYYYMMDD`) and get the technical owner's go for calibration.

## Phase 2: Deploy the new implementation

Either dispatch the `Deploy Contract` workflow against the frozen tag with target "Implementations only" (it deploys both SRA and SWA implementations, verifies them on Sourcify, and uploads the broadcast artifact), then stage the one you need:

```sh
TARGET=sra NEW_IMPLEMENTATION=0x... forge script script/Upgrade.s.sol --rpc-url $ETH_RPC_URL
```

or deploy and stage in one local step from the frozen commit:

```sh
TARGET=sra forge script script/Upgrade.s.sol --rpc-url $ETH_RPC_URL --broadcast
```

`TARGET` is `sra` or `swa`. The script deploys one implementation (unless `NEW_IMPLEMENTATION` is given) with the constructor arguments from `deployments.json`, proves its runtime code matches a local build, refuses to continue if it is not UUPS-compatible or equals the current one, and prints a block like:

```
==== UPGRADE STAGED ====
target                  sra
proxy                   0x...
current implementation  0x...
new implementation      0x...
hold (epochs)           20160
task id                 0x...
Owner 1, then owner 2, then (after the hold) anyone, send this exact calldata to the proxy:
0x4f1ef286...
Either owner can cancel during the hold by sending this calldata to the proxy:
0xfb6f93f9...
```

Record the implementation address, its creation transaction, the calldata and the task id in the tracking issue. If you need the same output again later without deploying, rerun with `NEW_IMPLEMENTATION=0x...` and no `--broadcast`.

Then verify the implementation before any owner signs anything:

1. Bytecode. `Upgrade.s.sol` always rebuilds the implementation locally from the checked-out source and config and compares runtime code against the on-chain address (masking only the implementation's own self-address immutable), so the staged output above already proves the deployed code matches the frozen commit. A second person should repeat it independently from a clean checkout of the tag, without `--broadcast`:

   ```sh
   TARGET=sra NEW_IMPLEMENTATION=0x... forge script script/Upgrade.s.sol --rpc-url $ETH_RPC_URL
   ```

   Do not run `Verify.s.sol` yet; it checks the proxy's current implementation and will correctly report a mismatch until Phase 6.
2. Explorer verification on Blockscout and Sourcify, with constructor arguments, exactly as in DEPLOYMENT.md Phase 4c. Owners should be able to open the new implementation on the explorer and read verified source before approving.

## Phase 3: Owner 1 submits

Owner 1 sends the printed `upgradeToAndCall` calldata to the proxy with zero value.

Confirm on chain:

```sh
cast receipt $TX --rpc-url $ETH_RPC_URL    # status 1, two logs: Submitted(taskId), Approved(taskId, owner1)
```

Read the task record. The task's slot is `keccak256(abi.encode(taskId, PENDING_TASKS_SLOT))`, where the low 8 bytes are the last-modified epoch and the next 20 bytes are the approval bitmask:

```sh
TASK_SLOT=$(cast keccak $(cast abi-encode 'f(bytes32,bytes32)' $TASK_ID 0x635f64a8ec66823e68578973f5bc466fd4e0eadd655f760cfc91e860524aa300))
cast storage $PROXY $TASK_SLOT --rpc-url $ETH_RPC_URL
```

After owner 1 the word ends in the submission epoch with a single approval bit set (for example `...0001` `<epoch>`). Record the transaction and epoch.

## Phase 4: Owner 2 approves, hold begins

Owner 2 sends byte-identical calldata to the proxy with zero value. Before they sign, have them compare the calldata against the tracking issue, not against a message from owner 1.

Confirm on chain:

```sh
cast receipt $TX --rpc-url $ETH_RPC_URL    # status 1, one log: Approved(taskId, owner2)
cast storage $PROXY $TASK_SLOT --rpc-url $ETH_RPC_URL   # approvals now 0b11, epoch = this block
```

The hold ends at `approvalEpoch + hold`. Compute it from the storage read, not from the intended schedule, and record it in the tracking issue as the earliest execution epoch. Post the schedule wherever consumers of SRA and SWA expect notice.

If owner 2's receipt shows `Submitted` as well as `Approved`, the calldata differed and a second task was created. Veto both and start Phase 3 again.

## Phase 5: During the hold

The hold exists so that anyone can review what will execute. During it:

- Re-run the Phase 2 bytecode and explorer checks against the new implementation address, from a clean checkout of the frozen tag, ideally by someone other than the deployer.
- Confirm the task record is unchanged and no other task exists for the proxy (watch `Submitted` events).
- If anything is wrong, either owner sends the printed `veto` calldata. Confirm `Rejected(taskId, owner)` in the receipt and that the task slot reads zero. A vetoed task can be resubmitted later with the same calldata; it starts from scratch.

## Phase 6: Execute and validate

After the hold epoch, anyone sends the same calldata to the proxy. This does not have to be an owner; the deployer key is fine.

```sh
cast send $PROXY $CALLDATA --rpc-url $ETH_RPC_URL
```

A revert with selector `0xbb1f322f` (`HoldUntil`) means the hold has not elapsed; the encoded argument is the earliest epoch.

Validate:

```sh
cast storage $PROXY 0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc --rpc-url $ETH_RPC_URL   # new implementation
cast storage $PROXY $TASK_SLOT --rpc-url $ETH_RPC_URL   # zero
cast storage $PROXY 0xf0c57e16840df040f15088dc2f81fe391c3923bec73e23a9662efc9c229c6a00 --rpc-url $ETH_RPC_URL   # Initializable version: 1, or n if a reinitializer(n) ran
forge script script/Verify.s.sol --rpc-url $ETH_RPC_URL   # from the frozen commit: ALL CHECKS PASSED
```

`Verify.s.sol` rebuilds the implementation from the checked-out source, so it passes only when the live implementation matches the frozen commit exactly. It also re-checks owners, initialization and the initializer effects, which is the regression check that the upgrade did not disturb existing state. Note that its SRA orchestrator checks assume the state of a fresh deployment; once orchestrators have been added on mainnet those two assertions will need to become tolerant, which is a known follow-up.

Then run whatever functional smoke test the change calls for (for example a read of the new getter, or a `quarterlyGateCheck` dry call on a fork). Record everything in the evidence table, then repeat from Phase 2 on mainnet.

## Rollback

Decide the rollback disposition in Phase 1 and write it in the tracking issue before owner 1 submits:

- Safe: the new implementation makes no storage changes that the old one cannot read. Rollback is a new upgrade task pointing at the previous implementation address, subject to the full hold. Keep the previous implementation address in the issue; it is still deployed and verified.
- Unsafe: the upgrade migrated or reinterpreted storage. Rolling back would corrupt state. The only fix is a further forward upgrade.

Before execution, rollback is always a veto and is immediate.

## Evidence table

Copy this into the tracking issue, one table per network and target.

| Item | Value |
|---|---|
| Network / chain id / target | |
| Frozen commit / tag | |
| Storage snapshot diff reviewed (link) | |
| Fork rehearsal output (link) | |
| Previous implementation | |
| New implementation address / tx | |
| Blockscout / Sourcify verification | |
| `upgradeToAndCall` calldata | |
| Task id | |
| Owner 1 submit tx / epoch | |
| Owner 2 approve tx / epoch | |
| Earliest execution epoch (from storage) | |
| Hold-period review by (name, link) | |
| Execute tx / epoch | |
| Post-execute implementation slot | |
| `Verify.s.sol` output (link) | |
| Smoke test | |
| Rollback disposition | |
| Technical owner sign-off | |
