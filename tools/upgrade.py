#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["safe-eth-py>=7.0,<8"]
# ///
# The `<8` cap keeps us on the safe-eth-py major version this was written and tested against; the exact
# versions actually installed are pinned by tools/upgrade.py.lock (run with `uv run --locked`).
"""Every step of an SRA/SWA implementation upgrade, as one command each. See docs/UPGRADE.md.

  uv run tools/upgrade.py rehearse [--sra 0x.. --swa 0x..]          dry-run both upgrades in a local fork
  uv run tools/upgrade.py propose --sra 0x.. --swa 0x..              verify both implementations, queue the upgrade
                                                                     on every owner Safe (DRY_RUN=1 to stop short)
  uv run tools/upgrade.py status --sra 0x.. --swa 0x.. [--previous-sra 0x.. --previous-swa 0x..]
                                                                     approvals, hold end, prepared-rollback state
  uv run tools/upgrade.py execute --sra 0x.. --swa 0x..              send both upgrades once the holds have elapsed
  uv run tools/upgrade.py verify [--record-release]                  script/Verify.s.sol against the live chain;
                                                                     optionally append the result to the GitHub release

Environment:
  ETH_RPC_URL               required; selects the network (chain id 314 or 314159)
  PROPOSER_PRIVATE_KEY      the operations key for propose (an owner of each Safe registers its address as a
                            proposer once, in the Safe app: https://help.safe.global/articles/1671337645-proposers);
                            any funded key for execute
  UPGRADE_CALLDATA          optional `data` for upgradeToAndCall (a reinitializer call); default empty
  DRY_RUN=1                 for propose: print the Safe transactions instead of submitting them
  NETWORK_NAME              for --record-release: the label to write into the release ("Calibnet" or "Mainnet")

`propose` first runs script/Upgrade.s.sol for each contract, which rebuilds the implementation from the checked-out
source and deployments.json and refuses to continue unless the on-chain runtime code matches, so the calldata
always refers to code built from this commit. It then builds the same Safe transaction for each owner Safe, signs
it with the proposer key and posts it to the Filecoin Safe Transaction Service. The proposer then tells the owner
groups; each confirms and executes in the Safe app. The hold starts when the second owner's transaction lands.
"""

import argparse
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
TARGETS = ("sra", "swa")

# ERC-1967 implementation slot: keccak256("eip1967.proxy.implementation") - 1. Same constant as
# lib/openzeppelin-contracts/contracts/proxy/ERC1967/ERC1967Utils.sol.
IMPLEMENTATION_SLOT = bytes.fromhex("360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc")
# ERC-7201 slot of the pending-task mapping: keccak256(abi.encode(uint256(keccak256("Solstice.PendingTasks")) - 1))
# & ~0xff. Same constant as src/lib/PendingTask.sol; test/StorageSlots.t.sol pins it.
PENDING_TASKS_SLOT = bytes.fromhex("635f64a8ec66823e68578973f5bc466fd4e0eadd655f760cfc91e860524aa300")
UPGRADE_SELECTOR = keccak(text="upgradeToAndCall(address,bytes)")[:4]
VETO_SELECTOR = keccak(text="veto(bytes32)")[:4]
SAFE_SERVICES = {
    314: "https://transaction.safe.filecoin.io",
    314159: "https://transaction-testnet.safe.filecoin.io",
}
ZERO_ADDRESS = "0x" + "00" * 20


def die(msg):
    print(msg, file=sys.stderr)
    sys.exit(1)


def parse_hex(value, name):
    """Hex bytes with or without a 0x prefix; anything else is an error rather than silently truncated."""
    raw = value[2:] if value.lower().startswith("0x") else value
    try:
        return bytes.fromhex(raw)
    except ValueError:
        die(f"{name} must be hex (got {value!r})")


def forge_script(script, env=None, quiet=False):
    """Run a forge script against ETH_RPC_URL (no broadcast); return stdout, exit on failure."""
    r = subprocess.run(
        ["forge", "script", script, "--rpc-url", os.environ["ETH_RPC_URL"]],
        cwd=ROOT, env={**os.environ, **(env or {})}, capture_output=True, text=True,
    )
    if r.returncode != 0:
        tail = [l for l in (r.stdout + r.stderr).splitlines() if "Error" in l or "Revert" in l] or r.stdout.splitlines()[-15:]
        print("\n".join(tail), file=sys.stderr)
        die(f"{script} failed")
    if not quiet:
        for line in r.stdout.splitlines():
            if line.startswith("  ") and not line.startswith("  ["):
                print(line.strip())
    return r.stdout


class Chain:
    def __init__(self):
        rpc = os.environ.get("ETH_RPC_URL") or die("ETH_RPC_URL is required")
        self.client = EthereumClient(rpc)
        self.w3 = self.client.w3
        self.chain_id = self.w3.eth.chain_id
        self.cfg = json.loads((ROOT / "deployments.json").read_text())[str(self.chain_id)]
        self.hold = int(self.cfg["hold"])

    def proxy(self, target):
        return to_checksum_address(self.cfg[target])

    def owners(self, target):
        return [to_checksum_address(self.cfg[f"{target}Owner1"]), to_checksum_address(self.cfg[f"{target}Owner2"])]

    def current_impl(self, target):
        word = self.w3.eth.get_storage_at(self.proxy(target), IMPLEMENTATION_SLOT)
        return to_checksum_address(word[-20:])


class Task:
    """One upgradeToAndCall task on one proxy: its calldata, id, and on-chain approval state."""

    def __init__(self, chain, target, implementation):
        self.chain, self.target = chain, target
        self.proxy = chain.proxy(target)
        self.impl = to_checksum_address(implementation)
        data = parse_hex(os.environ.get("UPGRADE_CALLDATA", "0x"), "UPGRADE_CALLDATA")
        self.calldata = UPGRADE_SELECTOR + encode(["address", "bytes"], [self.impl, data])
        self.task_id = keccak(self.calldata)
        self.slot = keccak(encode(["bytes32", "bytes32"], [self.task_id, PENDING_TASKS_SLOT]))

    def state(self):
        word = int.from_bytes(self.chain.w3.eth.get_storage_at(self.proxy, self.slot), "big")
        modified = word & ((1 << 64) - 1)
        approvals = bin((word >> 64) & ((1 << 160) - 1)).count("1")
        return modified, approvals

    def verify_code(self):
        print(f"== {self.target.upper()}: verifying {self.impl} against a local build (script/Upgrade.s.sol) ==")
        out = forge_script("script/Upgrade.s.sol", {"TARGET": self.target, "NEW_IMPLEMENTATION": self.impl}, quiet=True)
        lines = out.splitlines()
        marker = [i for i, l in enumerate(lines) if "send this exact calldata" in l]
        if not marker or lines[marker[0] + 1].strip() != "0x" + self.calldata.hex():
            die("calldata mismatch between script/Upgrade.s.sol and this tool")
        print("implementation runtime code matches the local build")

    def summary(self):
        print()
        print(f"== {self.target.upper()} upgrade on chain {self.chain.chain_id} ==")
        print(f"proxy                   {self.proxy}")
        print(f"current implementation  {self.chain.current_impl(self.target)}")
        print(f"new implementation      {self.impl}")
        print(f"owner Safes             {'  '.join(self.chain.owners(self.target))}")
        print(f"hold (epochs)           {self.chain.hold}")
        print(f"task id                 0x{self.task_id.hex()}")
        print("calldata (to proxy, value 0):")
        print("0x" + self.calldata.hex())
        print("veto calldata (either owner, to proxy):")
        print("0x" + (VETO_SELECTOR + self.task_id).hex())

    def status(self, label="upgrade"):
        modified, approvals = self.state()
        block = self.chain.w3.eth.block_number
        print(f"[{self.target.upper()} {label} task 0x{self.task_id.hex()[:10]}...] ", end="")
        if label == "upgrade" and self.chain.current_impl(self.target) == self.impl:
            print("executed: implementation slot points at the new implementation")
        elif modified == 0:
            print("no pending task (not submitted, or already executed or vetoed)")
        else:
            end = modified + self.chain.hold
            left = end - block
            if approvals >= 2:
                print(f"approved by both owners at epoch {modified}; " + (f"hold ends at epoch {end} ({left} epochs, about {left * 30 // 3600}h)" if left > 0 else "executable now by anyone"))
            else:
                print(f"{approvals} approval(s), last at epoch {modified}; the hold starts on the second approval")


def tasks(chain, args):
    return [Task(chain, t, getattr(args, t)) for t in TARGETS]


def cmd_rehearse(args):
    for t in TARGETS:
        impl = getattr(args, t)
        print(f"== Rehearsing {t.upper()} in a local fork (script/Rehearse.s.sol) ==")
        forge_script("script/Rehearse.s.sol", {"TARGET": t, **({"NEW_IMPLEMENTATION": impl} if impl else {})})
        print()


def cmd_propose(args):
    chain = Chain()
    key = os.environ.get("PROPOSER_PRIVATE_KEY") or die("PROPOSER_PRIVATE_KEY is required for propose")
    proposer = Account.from_key(key).address
    base_url = SAFE_SERVICES.get(chain.chain_id) or die(f"no Safe Transaction Service known for chain {chain.chain_id}")
    api = TransactionServiceApi(EthereumNetwork(chain.chain_id), ethereum_client=chain.client, base_url=base_url)
    for task in tasks(chain, args):
        task.verify_code()
        task.summary()
        print()
        print(f"== Queuing the {task.target.upper()} upgrade on its owner Safes as {proposer} via {base_url} ==")
        for owner in chain.owners(task.target):
            safe = Safe(owner, chain.client)
            # Next free nonce: after every queued (unexecuted) transaction, but never below the on-chain nonce,
            # since the service may still list stale proposals whose nonce has already been consumed.
            on_chain = safe.retrieve_nonce()
            pending = [int(t["nonce"]) for t in api.get_transactions(owner, executed="false", limit=100)]
            nonce = max([on_chain] + [n + 1 for n in pending if n >= on_chain])
            safe_tx = safe.build_multisig_tx(to=task.proxy, value=0, data=task.calldata, safe_nonce=nonce)
            safe_tx.sign(key)
            print(f"Safe {owner}: nonce {nonce}, safeTxHash 0x{safe_tx.safe_tx_hash.hex()}")
            if os.environ.get("DRY_RUN") == "1":
                print(f"  dry run: would post to {base_url}/api/v2/safes/{owner}/multisig-transactions/")
                continue
            try:
                api.post_transaction(safe_tx)
            except Exception as e:  # SafeAPIException carries the service's reason
                die(f"  proposal rejected: {e}\n  Is {proposer} registered as a proposer on {owner}? See docs/UPGRADE.md.")
            print(f"  queued; the owners of {owner} confirm and execute it at https://safe.filecoin.io")
    print()
    print("Next: tell each owner group their Safe has the upgrade queued. Owner 1's execution submits it; owner 2's approves it and starts the hold.")


def cmd_status(args):
    chain = Chain()
    print(f"== Task status on chain {chain.chain_id}, epoch {chain.w3.eth.block_number} ==")
    for task in tasks(chain, args):
        task.status()
        previous = getattr(args, f"previous_{task.target}")
        if previous:
            Task(chain, task.target, previous).status("prepared rollback")
    print()
    for task in tasks(chain, args):
        task.summary()


def cmd_execute(args):
    chain = Chain()
    key = os.environ.get("PROPOSER_PRIVATE_KEY") or die("PROPOSER_PRIVATE_KEY is required for execute")
    account = Account.from_key(key)
    for task in tasks(chain, args):
        task.status()
        if chain.current_impl(task.target) == task.impl:
            continue
        print(f"== Executing the {task.target.upper()} upgrade from {account.address} ==")
        tx = {
            "from": account.address, "to": task.proxy, "data": task.calldata, "value": 0,
            "chainId": chain.chain_id, "nonce": chain.w3.eth.get_transaction_count(account.address),
        }
        try:
            tx["gas"] = chain.w3.eth.estimate_gas(tx)
        except Exception as e:
            die(f"execution would revert: {e}")
        fees = chain.w3.eth.fee_history(1, "latest", [50])
        tx["maxPriorityFeePerGas"] = int(fees["reward"][0][0]) if fees.get("reward") else chain.w3.eth.max_priority_fee
        tx["maxFeePerGas"] = int(fees["baseFeePerGas"][-1]) * 2 + tx["maxPriorityFeePerGas"]
        tx_hash = chain.w3.eth.send_raw_transaction(account.sign_transaction(tx).raw_transaction)
        receipt = chain.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=600)
        print(f"tx 0x{tx_hash.hex()} status {receipt['status']} block {receipt['blockNumber']}")
        if receipt["status"] != 1:
            die("execution transaction reverted")
        if chain.current_impl(task.target) != task.impl:
            die(f"implementation slot is {chain.current_impl(task.target)}, not {task.impl}")
        print(f"implementation slot now {task.impl}")
    print()
    for task in tasks(chain, args):
        task.status()


def cmd_verify(args):
    print("== script/Verify.s.sol against the live chain ==")
    out = forge_script("script/Verify.s.sol")
    if "ALL CHECKS PASSED" not in out:
        die("verification did not pass")
    if args.record_release:
        record_release()


def sh(*cmd, check=True, **kw):
    return subprocess.run(cmd, cwd=ROOT, check=check, capture_output=True, text=True, **kw).stdout.strip()


def record_release():
    """Append the verified implementations to the GitHub release for the tag this commit is at; on mainnet
    promote the pre-release to the final release. Only for commits on main, since this runs without reviewers."""
    network = os.environ.get("NETWORK_NAME") or die("NETWORK_NAME is required with --record-release")
    sh("git", "fetch", "--quiet", "--tags", "origin", "main")
    head = sh("git", "rev-parse", "HEAD")
    if subprocess.run(["git", "merge-base", "--is-ancestor", head, "origin/main"], cwd=ROOT).returncode != 0:
        die(f"{head[:8]} is not on main; not touching the release")
    tag = sh("git", "describe", "--tags", "--exact-match", "--match", "v[0-9]*.[0-9]*.[0-9]*", check=False)
    if not tag:
        print(f"{head[:8]} is not at a v* tag; nothing to record")
        return
    if subprocess.run(["gh", "release", "view", tag], cwd=ROOT, capture_output=True).returncode != 0:
        print(f"no release {tag}; nothing to record")
        return
    chain = Chain()
    epoch = chain.w3.eth.block_number
    run_url = os.environ.get("RUN_URL", "")
    note = (f"\n\n**Verified on {network}** at epoch {epoch} from `{head[:8]}`"
            + (f" ([run]({run_url}))" if run_url else "")
            + f": SRA implementation `{chain.current_impl('sra')}`, SWA implementation `{chain.current_impl('swa')}`.\n")
    body = sh("gh", "release", "view", tag, "--json", "body", "-q", ".body") + note
    notes = ROOT / "release-notes.tmp.md"
    notes.write_text(body)
    try:
        if network == "Mainnet":
            sh("gh", "release", "edit", tag, "--notes-file", str(notes), "--prerelease=false", "--latest")
            print(f"recorded and promoted {tag} to the final release")
        else:
            sh("gh", "release", "edit", tag, "--notes-file", str(notes))
            print(f"recorded verification in pre-release {tag}")
    finally:
        notes.unlink(missing_ok=True)


def address(value):
    try:
        return to_checksum_address(value)
    except Exception:
        raise argparse.ArgumentTypeError(f"not an address: {value}")


def main(argv):
    p = argparse.ArgumentParser(prog="tools/upgrade.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="operation", required=True)

    def impls(sp, required):
        sp.add_argument("--sra", type=address, required=required, help="new SRA implementation address")
        sp.add_argument("--swa", type=address, required=required, help="new SWA implementation address")

    impls(sub.add_parser("rehearse", help="dry-run both upgrades in a local fork"), required=False)
    impls(sub.add_parser("propose", help="verify and queue both upgrades on the owner Safes"), required=True)
    s = sub.add_parser("status", help="approvals, hold end and prepared-rollback state")
    impls(s, required=True)
    s.add_argument("--previous-sra", type=address, help="previous SRA implementation, to report its prepared rollback")
    s.add_argument("--previous-swa", type=address, help="previous SWA implementation, to report its prepared rollback")
    impls(sub.add_parser("execute", help="send both upgrades after the holds"), required=True)
    v = sub.add_parser("verify", help="run script/Verify.s.sol against the live chain")
    v.add_argument("--record-release", action="store_true", help="append the result to the GitHub release; promote on mainnet")

    args = p.parse_args(argv)
    {
        "rehearse": cmd_rehearse, "propose": cmd_propose, "status": cmd_status, "execute": cmd_execute,
        "verify": cmd_verify,
    }[args.operation](args)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
