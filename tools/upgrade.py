#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["safe-eth-py>=7.0,<8"]
# ///
# The `<8` cap keeps us on the safe-eth-py major version this was written and tested against; the exact
# versions actually installed are pinned by tools/upgrade.py.lock (run with `uv run --locked`).
"""Every step of an SRA/SWA implementation upgrade, as one command each. See docs/UPGRADE.md.

Both contracts are always upgraded together, so every operation acts on both.

Environment:
  ETH_RPC_URL           required; selects the network (chain id 314 or 314159)
  DEPLOYER_PRIVATE_KEY  the operations key: registered once by an owner of each Safe as a proposer
                        (https://help.safe.global/articles/1671337645-proposers) for `propose`; any funded key
                        for `execute`
  DRY_RUN=1             for propose: build and sign the Safe transactions but do not post them
  NETWORK_NAME          for `verify --record-release`: the label written into the release ("Calibnet" or "Mainnet")

`propose` runs script/Verify.s.sol with the new addresses as candidates, which rebuilds both implementations from
the checked-out source and refuses unless the on-chain runtime code matches, so the queued transactions always
refer to code built from this commit. See docs/UPGRADE.md step 4 for what happens after the proposals are queued.
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


def die(msg):
    print(msg, file=sys.stderr)
    sys.exit(1)


def forge_script(script, env=None, quiet=False):
    """Run a forge script against ETH_RPC_URL (no broadcast); print its log lines; exit on failure."""
    r = subprocess.run(
        ["forge", "script", script, "--rpc-url", os.environ["ETH_RPC_URL"]],
        cwd=ROOT, env={**os.environ, **(env or {})}, capture_output=True, text=True,
    )
    if r.returncode != 0:
        tail = [l for l in (r.stdout + r.stderr).splitlines() if "Error" in l or "Revert" in l] or r.stdout.splitlines()[-15:]
        print("\n".join(tail), file=sys.stderr)
        die(f"{script} failed")
    if not quiet:
        for line in script_logs(r.stdout):
            print(line)
    return r.stdout


def script_logs(stdout):
    """The console.log lines of a forge script run: everything between forge's `== Logs ==` marker and the next
    section header, stripped of indentation."""
    lines, on = [], False
    for line in stdout.splitlines():
        if line.strip() == "== Logs ==":
            on = True
            continue
        if on and (line.startswith("##") or line.startswith("== ") or line.startswith("Script ran")):
            break
        if on and line.strip():
            lines.append(line.strip())
    return lines


def key_account(purpose):
    key = os.environ.get("DEPLOYER_PRIVATE_KEY") or die(f"DEPLOYER_PRIVATE_KEY is required for {purpose}")
    return key, Account.from_key(key)


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
        return to_checksum_address(self.w3.eth.get_storage_at(self.proxy(target), IMPLEMENTATION_SLOT)[-20:])


class Task:
    """One `upgradeToAndCall(impl, "")` task on one proxy: its calldata, id, and on-chain state."""

    def __init__(self, chain, target, implementation):
        self.chain, self.target = chain, target
        self.name = target.upper()
        self.proxy = chain.proxy(target)
        self.impl = to_checksum_address(implementation)
        self.calldata = upgrade_calldata(self.impl)
        self.task_id = keccak(self.calldata)
        self.slot = keccak(encode(["bytes32", "bytes32"], [self.task_id, PENDING_TASKS_SLOT]))

    def state(self):
        """(last modified epoch, number of approvals); (0, 0) when no task is pending."""
        word = int.from_bytes(self.chain.w3.eth.get_storage_at(self.proxy, self.slot), "big")
        return word & ((1 << 64) - 1), bin((word >> 64) & ((1 << 160) - 1)).count("1")

    def executable(self, block):
        modified, approvals = self.state()
        return modified != 0 and approvals >= 2 and block >= modified + self.chain.hold

    def summary(self):
        print()
        print(f"== {self.name} upgrade on chain {self.chain.chain_id} ==")
        print(f"proxy                   {self.proxy}")
        print(f"current implementation  {self.chain.current_impl(self.target)}")
        print(f"implementation          {self.impl}")
        print(f"owner Safes             {'  '.join(self.chain.owners(self.target))}")
        print(f"hold (epochs)           {self.chain.hold}")
        print(f"task id                 0x{self.task_id.hex()}")
        print("calldata (to proxy, value 0):")
        print("0x" + self.calldata.hex())
        print("veto calldata (either owner, to proxy):")
        print("0x" + (VETO_SELECTOR + self.task_id).hex())

    def status(self):
        modified, approvals = self.state()
        block = self.chain.w3.eth.block_number
        print(f"[{self.name} task 0x{self.task_id.hex()[:10]}... -> {self.impl}] ", end="")
        if modified != 0:
            end = modified + self.chain.hold
            left = end - block
            if approvals >= 2:
                print(f"approved by both owners at epoch {modified}; "
                      + (f"hold ends at epoch {end} ({left} epochs, about {left * 30 // 3600}h)" if left > 0 else "executable now by anyone"))
            else:
                print(f"{approvals} approval(s), last at epoch {modified}; the hold starts on the second approval")
        elif self.chain.current_impl(self.target) == self.impl:
            print("live: the proxy points at this implementation")
        else:
            print("no pending task (not submitted, or already executed or vetoed)")


def next_nonce(on_chain, queued):
    """Next free Safe nonce: after every queued transaction, but never below the on-chain nonce, since the
    service may still list stale proposals whose nonce has already been consumed."""
    return max([on_chain] + [n + 1 for n in queued if n >= on_chain])


def already_queued(queued, on_chain, to, data):
    """The queued (unexecuted) Safe transaction that already carries this call, if any. Proposals whose nonce is
    below the on-chain nonce can never execute, so they do not count."""
    for t in queued:
        if (int(t["nonce"]) >= on_chain and (t.get("to") or "").lower() == to.lower()
                and (t.get("data") or "").lower() == "0x" + data.hex()):
            return t
    return None


def upgrade_calldata(implementation):
    """`upgradeToAndCall(implementation, "")`, byte-identical for every sender; its keccak is the task id."""
    return UPGRADE_SELECTOR + encode(["address", "bytes"], [to_checksum_address(implementation), b""])


def tasks(chain, args):
    return [Task(chain, t, getattr(args, t)) for t in TARGETS]


def cmd_rehearse(args):
    print("== Rehearsing the SRA and SWA upgrades in a local fork (script/Rehearse.s.sol) ==")
    forge_script("script/Rehearse.s.sol")


def cmd_propose(args):
    chain = Chain()
    key, account = key_account("propose")
    base_url = SAFE_SERVICES.get(chain.chain_id) or die(f"no Safe Transaction Service known for chain {chain.chain_id}")
    api = TransactionServiceApi(EthereumNetwork(chain.chain_id), ethereum_client=chain.client, base_url=base_url)
    todo = tasks(chain, args)
    print("== Checking both candidates against a local build of the checked-out source (script/Verify.s.sol) ==")
    forge_script("script/Verify.s.sol", {f"NEW_IMPLEMENTATION_{t.name}": t.impl for t in todo})
    for task in todo:
        task.summary()
        print()
        print(f"== Queuing the {task.name} upgrade on its owner Safes as {account.address} via {base_url} ==")
        for owner in chain.owners(task.target):
            safe = Safe(owner, chain.client)
            on_chain = safe.retrieve_nonce()
            queued = api.get_transactions(owner, executed="false", limit=100)
            same = already_queued(queued, on_chain, task.proxy, task.calldata)
            if same:
                print(f"Safe {owner}: already queued at nonce {same['nonce']} (safeTxHash {same['safeTxHash']}); skipping")
                continue
            nonce = next_nonce(on_chain, [int(t["nonce"]) for t in queued])
            safe_tx = safe.build_multisig_tx(to=task.proxy, value=0, data=task.calldata, safe_nonce=nonce)
            safe_tx.sign(key)
            print(f"Safe {owner}: nonce {nonce}, safeTxHash 0x{safe_tx.safe_tx_hash.hex()}")
            if os.environ.get("DRY_RUN") == "1":
                print(f"  dry run: would post to {base_url}/api/v2/safes/{owner}/multisig-transactions/")
                continue
            try:
                api.post_transaction(safe_tx)
            except Exception as e:  # SafeAPIException carries the service's reason
                die(f"  proposal rejected: {e}\n  Is {account.address} registered as a proposer on {owner}? See docs/UPGRADE.md.")
            print(f"  queued; the owners of {owner} confirm and execute it at https://safe.filecoin.io")
    print()
    print("Next: tell each owner group their Safe has the upgrade queued. The first owner's execution submits it; "
          "the second's approves it and starts the hold.")


def cmd_status(args):
    chain = Chain()
    print(f"== Task status on chain {chain.chain_id}, epoch {chain.w3.eth.block_number} ==")
    for task in tasks(chain, args):
        task.status()
    for task in tasks(chain, args):
        task.summary()


def cmd_execute(args):
    chain = Chain()
    key, account = key_account("execute")
    todo = [t for t in tasks(chain, args) if chain.current_impl(t.target) != t.impl]
    block = chain.w3.eth.block_number
    for task in todo:
        task.status()
    not_ready = [t.name for t in todo if not t.executable(block)]
    if not_ready:
        die(f"not executing anything: {', '.join(not_ready)} not yet executable (both contracts must be ready)")
    for task in todo:
        print(f"== Executing the {task.name} upgrade from {account.address} ==")
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
    if "ALL CHECKS PASSED" not in forge_script("script/Verify.s.sol"):
        die("verification did not pass")
    if args.record_release:
        record_release()


def sh(*cmd, check=True):
    return subprocess.run(cmd, cwd=ROOT, check=check, capture_output=True, text=True).stdout.strip()


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
    facts = f"SRA implementation `{chain.current_impl('sra')}`, SWA implementation `{chain.current_impl('swa')}`"
    body = sh("gh", "release", "view", tag, "--json", "body", "-q", ".body")
    if any(line.startswith(f"**Verified on {network}**") and facts in line for line in body.splitlines()):
        print(f"release {tag} already records this verification on {network}; not appending again")
    else:
        run_url = os.environ.get("RUN_URL", "")
        body += (f"\n\n**Verified on {network}** at epoch {chain.w3.eth.block_number} from `{head[:8]}`"
                 + (f" ([run]({run_url}))" if run_url else "") + f": {facts}.\n")
    notes = ROOT / "release-notes.tmp.md"
    notes.write_text(body)
    try:
        if network == "Mainnet":
            sh("gh", "release", "edit", tag, "--notes-file", str(notes), "--prerelease=false", "--latest")
            print(f"recorded verification and promoted {tag} to the final release")
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
    sub = p.add_subparsers(dest="operation", required=True, metavar="operation")

    def impls(sp, required, what="new"):
        sp.add_argument("--sra", type=address, required=required, help=f"{what} SRA implementation address")
        sp.add_argument("--swa", type=address, required=required, help=f"{what} SWA implementation address")

    sub.add_parser("rehearse", help="dry-run both upgrades in a local fork, built from the checked-out source")
    impls(sub.add_parser("propose", help="check both implementations and queue the upgrades on the owner Safes"), True)
    impls(sub.add_parser("status", help="approvals and hold end for both tasks (pass previous addresses to see a prepared rollback)"), True, what="upgrade-target")
    impls(sub.add_parser("execute", help="send both upgrades once both holds have elapsed"), True)
    v = sub.add_parser("verify", help="run script/Verify.s.sol against the live chain")
    v.add_argument("--record-release", action="store_true", help="append the result to the GitHub release; promote on mainnet")

    args = p.parse_args(argv)
    {"rehearse": cmd_rehearse, "propose": cmd_propose, "status": cmd_status, "execute": cmd_execute, "verify": cmd_verify}[args.operation](args)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
