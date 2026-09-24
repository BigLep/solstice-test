#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["safe-eth-py>=7.0,<8"]
# ///
"""Stage, propose, track and execute a UUPS upgrade of the SRA or SWA proxy recorded in deployments.json.

  uv run tools/upgrade.py <sra|swa> <new-implementation> calldata   verify the implementation, print calldata
  uv run tools/upgrade.py <sra|swa> <new-implementation> propose    ...and queue it on both owner Safes
  uv run tools/upgrade.py <sra|swa> <new-implementation> status     approvals and when the hold ends
  uv run tools/upgrade.py <sra|swa> <new-implementation> execute    send the upgrade once the hold has elapsed
  uv run tools/upgrade.py register-proposer <safe> <proposer>       one-time: an owner-signer of <safe> registers
                                                                    <proposer> on the Safe Transaction Service

Environment:
  ETH_RPC_URL             required; selects the network (chain id 314 or 314159)
  PROPOSER_PRIVATE_KEY    the operations key: registered as a proposer on the owner Safes (propose), any funded
                          key (execute)
  OWNER_SIGNER_PRIVATE_KEY  for register-proposer: a signer of the owner Safe
  UPGRADE_CALLDATA        optional `data` for upgradeToAndCall (a reinitializer call); default empty
  DRY_RUN=1               for propose: print the Safe transactions instead of submitting them

`calldata` and `propose` first run script/Upgrade.s.sol, which rebuilds the implementation from the checked-out
source and deployments.json and refuses to continue unless the on-chain runtime code matches, so the calldata
always refers to code built from this commit. `propose` then builds the same Safe transaction for each owner
Safe, signs it with the proposer key and posts it to the Filecoin Safe Transaction Service; owners confirm and
execute in the Safe app. The hold starts when the second owner's transaction lands.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from eth_abi import encode
from eth_account import Account
from eth_utils import keccak, to_checksum_address
from safe_eth.eth import EthereumClient, EthereumNetwork
from safe_eth.safe import Safe
from safe_eth.safe.api import TransactionServiceApi

ROOT = Path(__file__).resolve().parent.parent
IMPLEMENTATION_SLOT = bytes.fromhex("360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc")
PENDING_TASKS_SLOT = bytes.fromhex("635f64a8ec66823e68578973f5bc466fd4e0eadd655f760cfc91e860524aa300")
UPGRADE_SELECTOR = keccak(text="upgradeToAndCall(address,bytes)")[:4]
VETO_SELECTOR = keccak(text="veto(bytes32)")[:4]
SAFE_SERVICES = {
    314: "https://transaction.safe.filecoin.io",
    314159: "https://transaction-testnet.safe.filecoin.io",
}


def die(msg):
    print(msg, file=sys.stderr)
    sys.exit(1)


class Upgrade:
    def __init__(self, target, new_impl):
        rpc = os.environ.get("ETH_RPC_URL") or die("ETH_RPC_URL is required")
        self.client = EthereumClient(rpc)
        self.w3 = self.client.w3
        self.chain_id = self.w3.eth.chain_id
        cfg = json.loads((ROOT / "deployments.json").read_text())[str(self.chain_id)]
        self.target = target
        self.proxy = to_checksum_address(cfg[target])
        self.owners = [to_checksum_address(cfg[f"{target}Owner1"]), to_checksum_address(cfg[f"{target}Owner2"])]
        self.hold = int(cfg["hold"])
        self.new_impl = to_checksum_address(new_impl)
        data = bytes.fromhex(os.environ.get("UPGRADE_CALLDATA", "0x")[2:])
        self.calldata = UPGRADE_SELECTOR + encode(["address", "bytes"], [self.new_impl, data])
        self.task_id = keccak(self.calldata)
        self.task_slot = keccak(encode(["bytes32", "bytes32"], [self.task_id, PENDING_TASKS_SLOT]))

    # ---- reads -------------------------------------------------------------------------------------------

    def current_impl(self):
        word = self.w3.eth.get_storage_at(self.proxy, IMPLEMENTATION_SLOT)
        return to_checksum_address(word[-20:])

    def task(self):
        word = int.from_bytes(self.w3.eth.get_storage_at(self.proxy, self.task_slot), "big")
        modified = word & ((1 << 64) - 1)
        approvals = (word >> 64) & ((1 << 160) - 1)
        return modified, bin(approvals).count("1")

    # ---- steps -------------------------------------------------------------------------------------------

    def verify(self):
        print(f"== Verifying {self.new_impl} against a local build (script/Upgrade.s.sol) ==")
        env = dict(os.environ, TARGET=self.target, NEW_IMPLEMENTATION=self.new_impl)
        r = subprocess.run(
            ["forge", "script", "script/Upgrade.s.sol", "--rpc-url", os.environ["ETH_RPC_URL"]],
            cwd=ROOT, env=env, capture_output=True, text=True,
        )
        if r.returncode != 0:
            tail = [l for l in (r.stdout + r.stderr).splitlines() if "Error" in l or "Revert" in l] or r.stdout.splitlines()[-15:]
            print("\n".join(tail), file=sys.stderr)
            die("implementation did not verify; not continuing")
        lines = r.stdout.splitlines()
        idx = next(i for i, l in enumerate(lines) if "send this exact calldata" in l)
        if lines[idx + 1].strip() != "0x" + self.calldata.hex():
            die("calldata mismatch between script/Upgrade.s.sol and this tool")
        print("implementation runtime code matches the local build")

    def summary(self):
        print()
        print(f"== Upgrade {self.target} on chain {self.chain_id} ==")
        print(f"proxy                   {self.proxy}")
        print(f"current implementation  {self.current_impl()}")
        print(f"new implementation      {self.new_impl}")
        print(f"owner Safes             {self.owners[0]}  {self.owners[1]}")
        print(f"hold (epochs)           {self.hold}")
        print(f"task id                 0x{self.task_id.hex()}")
        print("calldata (to proxy, value 0):")
        print("0x" + self.calldata.hex())
        print("veto calldata (either owner, to proxy):")
        print("0x" + (VETO_SELECTOR + self.task_id).hex())

    def status(self):
        modified, approvals = self.task()
        block = self.w3.eth.block_number
        print()
        print("== Task status ==")
        if self.current_impl() == self.new_impl:
            print("implementation slot already points at the new implementation: upgrade executed")
        elif modified == 0:
            print("no pending task: nothing submitted yet, or the task was executed or vetoed")
        else:
            print(f"approvals: {approvals} owner(s), last modified at epoch {modified}, current epoch {block}")
            if approvals >= 2:
                end = modified + self.hold
                left = end - block
                print(f"hold ends at epoch {end}" + (f" ({left} epochs, about {left * 30 // 3600}h to go)" if left > 0 else ": executable now"))
            else:
                print("waiting for the second owner; the hold starts when their transaction lands")

    def propose(self):
        key = os.environ.get("PROPOSER_PRIVATE_KEY") or die("PROPOSER_PRIVATE_KEY is required for propose")
        proposer = Account.from_key(key).address
        base_url = SAFE_SERVICES.get(self.chain_id) or die(f"no Safe Transaction Service known for chain {self.chain_id}")
        api = TransactionServiceApi(EthereumNetwork(self.chain_id), ethereum_client=self.client, base_url=base_url)
        print()
        print(f"== Proposing to owner Safes as {proposer} via {base_url} ==")
        for owner in self.owners:
            safe = Safe(owner, self.client)
            # Next free nonce: after every queued (unexecuted) transaction, but never below the on-chain nonce,
            # since the service may still list stale proposals whose nonce has already been consumed.
            on_chain = safe.retrieve_nonce()
            pending = [int(t["nonce"]) for t in api.get_transactions(owner, executed="false", limit=100)]
            nonce = max([on_chain] + [n + 1 for n in pending if n >= on_chain])
            safe_tx = safe.build_multisig_tx(to=self.proxy, value=0, data=self.calldata, safe_nonce=nonce)
            safe_tx.sign(key)
            print(f"Safe {owner}: nonce {nonce}, safeTxHash 0x{safe_tx.safe_tx_hash.hex()}")
            if os.environ.get("DRY_RUN") == "1":
                print(f"  dry run: would post to {base_url}/api/v2/safes/{owner}/multisig-transactions/")
                continue
            try:
                api.post_transaction(safe_tx)
            except Exception as e:  # SafeAPIException carries the service's reason
                die(f"  proposal rejected: {e}\n  Is {proposer} registered as a proposer on {owner}? See docs/UPGRADE.md.")
            print(f"  proposed; owners confirm at https://safe.filecoin.io (transactions queue for {owner})")

    def execute(self):
        key = os.environ.get("PROPOSER_PRIVATE_KEY") or die("PROPOSER_PRIVATE_KEY is required for execute")
        account = Account.from_key(key)
        print()
        print(f"== Executing upgrade from {account.address} ==")
        tx = {
            "from": account.address, "to": self.proxy, "data": self.calldata, "value": 0,
            "chainId": self.chain_id, "nonce": self.w3.eth.get_transaction_count(account.address),
        }
        try:
            tx["gas"] = self.w3.eth.estimate_gas(tx)
        except Exception as e:
            die(f"execution would revert: {e}")
        fees = self.w3.eth.fee_history(1, "latest", [50])
        tx["maxPriorityFeePerGas"] = int(fees["reward"][0][0]) if fees.get("reward") else self.w3.eth.max_priority_fee
        tx["maxFeePerGas"] = int(fees["baseFeePerGas"][-1]) * 2 + tx["maxPriorityFeePerGas"]
        signed = account.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=600)
        print(f"tx 0x{tx_hash.hex()} status {receipt['status']} block {receipt['blockNumber']}")
        print(f"implementation slot now {self.current_impl()}")


def register_proposer(safe_address, proposer):
    rpc = os.environ.get("ETH_RPC_URL") or die("ETH_RPC_URL is required")
    key = os.environ.get("OWNER_SIGNER_PRIVATE_KEY") or die("OWNER_SIGNER_PRIVATE_KEY (a signer of the Safe) is required")
    client = EthereumClient(rpc)
    chain_id = client.w3.eth.chain_id
    base_url = SAFE_SERVICES.get(chain_id) or die(f"no Safe Transaction Service known for chain {chain_id}")
    api = TransactionServiceApi(EthereumNetwork(chain_id), ethereum_client=client, base_url=base_url)
    signer = Account.from_key(key)
    safe_address, proposer = to_checksum_address(safe_address), to_checksum_address(proposer)
    message_hash = api.create_delegate_message_hash(proposer)
    signature = signer.unsafe_sign_hash(message_hash).signature
    api.add_delegate(proposer, signer.address, "solstice operations key", signature, safe_address=safe_address)
    print(f"registered {proposer} as a proposer on {safe_address} (signed by {signer.address}) via {base_url}")
    print("current proposers:", [d.delegate for d in api.get_delegates(safe_address)])


def main(argv):
    if len(argv) == 4 and argv[1] == "register-proposer":
        return register_proposer(argv[2], argv[3])
    if len(argv) != 4 or argv[1] not in ("sra", "swa") or argv[3] not in ("calldata", "propose", "status", "execute"):
        print(__doc__, file=sys.stderr)
        return 2
    u = Upgrade(argv[1], argv[2])
    mode = argv[3]
    if mode in ("calldata", "propose"):
        u.verify()
    u.summary()
    if mode == "status":
        u.status()
    elif mode == "propose":
        u.propose()
    elif mode == "execute":
        u.status()
        u.execute()
        u.status()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
