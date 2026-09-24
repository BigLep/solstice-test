# Upgrading SRA and SWA

How a merged code change becomes the live implementation behind the ServiceRewardsActor (SRA) or StreamWeightActor (SWA) proxy on calibration and mainnet. The proxies are permanent: their addresses are in [`deployments.json`](../deployments.json) and hardwired into Lotus for nv29 ([lotus#13809](https://github.com/filecoin-project/lotus/pull/13809)). Deploying new proxies is a one-off that already happened; see [DEPLOYMENT.md](./DEPLOYMENT.md) only if you are bringing up a new network.

## How an upgrade works

| Piece | Where | What it does |
|---|---|---|
| Proxy | OpenZeppelin [`ERC1967Proxy`](../lib/openzeppelin-contracts/contracts/proxy/ERC1967/ERC1967Proxy.sol) | Holds state and delegates to the implementation. No admin; nothing outside the implementation can change it. |
| Implementation | [`ServiceRewardsActor`](../src/ServiceRewardsActor.sol), [`StreamWeightActor`](../src/StreamWeightActor.sol) | Inherit [`UnanimousProxied`](../src/lib/UnanimousProxied.sol), whose `_authorizeUpgrade` is gated by the `unanimous` modifier in [`UnanimousGovernance`](../src/lib/UnanimousGovernance.sol) with the hold fixed at deployment. |
| Owners | Two [Safe](https://safe.filecoin.io) multisigs per contract, `sraOwner1/2` and `swaOwner1/2` in `deployments.json`, same addresses on both networks | The only parties that can approve an upgrade. |
| Deployer / proposer key | Any funded key | Pays gas and proposes. No power over the contracts; not an owner key. |

The upgrade call is the standard `upgradeToAndCall(newImplementation, data)` on the proxy. Its task id is `keccak256(calldata)`, so both owners must send byte-identical calldata with zero value.

| Step | Who | Effect |
|---|---|---|
| Submit | Owner Safe 1 | `Submitted` and `Approved` events. Nothing changes yet. |
| Approve | Owner Safe 2 | Second `Approved`. The hold starts at this block. |
| Hold | Anyone | Execution reverts with `HoldUntil(epoch)` until the hold elapses. Either owner can `veto(taskId)`. |
| Execute | Anyone | Implementation slot changes, `data` (if any) runs, task is deleted. |

Hold (`hold` in `deployments.json`): 20160 epochs (about 7 days) on mainnet, 720 (about 6 hours) on calibration.

## Steps

Calibration first, then mainnet, from the same tag. Each step is one command; record its output in the tracking issue.

**0. Open a tracking issue** from the [upgrade template](../.github/ISSUE_TEMPLATE/upgrade.md). Addresses and transaction hashes go in its table; everything else goes in comments.

**1. Merge the change and tag it.** CI does the safety checks: the `Storage Layout` workflow ([`tools/storage-layout-snapshot.sh`](../tools/storage-layout-snapshot.sh)) fails any PR whose namespaced structs or slot constants change in a way that is not append-only, and the test suite covers the upgrade paths in [`test/UnanimousProxied.t.sol`](../test/UnanimousProxied.t.sol). If the layout check fails, the change needs a storage migration, which this runbook does not cover; stop and design that first.

**2. Rehearse in a fork.** From the tag:

```sh
TARGET=sra forge script script/Rehearse.s.sol --rpc-url https://api.calibration.node.glif.io/rpc/v1
```

[`script/Rehearse.s.sol`](../script/Rehearse.s.sol) forks the network in the local EVM, builds the implementation, impersonates both owner Safes to submit and approve, proves early execution reverts, rolls past the hold, executes, and runs every verifier check. It prints `REHEARSAL COMPLETE` or reverts naming the step. Nothing is sent. Paste the tail into the issue.

**3. Deploy the implementation.** Dispatch the `Deploy Contract` workflow (`.github/workflows/deploy-contract.yml`, from [#73](https://github.com/filecoin-project/solstice/pull/73)) against the tag with target "Implementations only" and dry run off. It needs `DEPLOYER_PRIVATE_KEY` on the `calibnet` or `mainnet` GitHub environment; any funded key. It deploys both implementations and verifies them on Sourcify; use the one you are upgrading and ignore the other. Record the address from the job summary.

**4. Propose to the owners.**

```sh
PROPOSER_PRIVATE_KEY=... tools/upgrade.sh sra 0x<new-implementation> propose
```

[`tools/upgrade.sh`](../tools/upgrade.sh) first rebuilds the implementation from the checked-out source and refuses to continue unless the on-chain runtime code matches ([`script/Upgrade.s.sol`](../script/Upgrade.s.sol)), then queues the same transaction on both owner Safes through the [Filecoin Safe Transaction Service](https://transaction.safe.filecoin.io/). Each owner group opens the Safe app, sees it queued, confirms and executes. Owner 1's execution is the submit; owner 2's is the approve, and the hold starts when it lands. Record both `safeTxHash` values and the two transaction hashes.

If the proposer is not registered yet (see setup below), run the `calldata` mode instead and give the owners the proxy address and calldata to enter in the Safe app's transaction builder. It is the same transaction.

**5. Track the hold.**

```sh
tools/upgrade.sh sra 0x<new-implementation> status
```

Prints how many owners have approved and the epoch the hold ends. If something is wrong, either owner cancels with the `veto` calldata the tool prints.

**6. Execute.** After the hold, from any funded key:

```sh
PROPOSER_PRIVATE_KEY=... tools/upgrade.sh sra 0x<new-implementation> execute
```

**7. Verify.** From the tag:

```sh
forge script script/Verify.s.sol --rpc-url $ETH_RPC_URL
```

[`script/Verify.s.sol`](../script/Verify.s.sol) rebuilds both implementations and proxies from source and `deployments.json`, compares runtime code with the live contracts, and checks the implementation slot, initialization, owner sets and initializer state. It ends with `ALL CHECKS PASSED` or names the failed check. Record it, then repeat from step 3 on mainnet.

## One-time setup: proposer on the owner Safes

Step 4 relies on Safe proposers (delegates): an address that can queue transactions for a Safe but cannot sign them. One owner of each of the four Safes registers the engineering proposer address at [safe.filecoin.io](https://safe.filecoin.io) under Settings, Setup, Proposers, once per network. The proposer must be a plain key, not a Safe, because it signs proposals off chain; hold it like the deployer key, a funded engineering-held key with no other role. Until this is done, step 4 falls back to handing the owners calldata.

## Out of scope until needed

- Rollback: a new upgrade back to the previous implementation, subject to the same hold, so keep the previous implementation address in the issue. Before execution, rollback is a veto.
- Migrations and reinitializers: `tools/upgrade.sh` and the scripts accept `UPGRADE_CALLDATA` for a reinitializer call, but the process around a storage migration has not been designed.
- Owner replacement: `replaceOwner` on `UnanimousProxied` is a separate unanimous flow with no hold. Veto pending tasks before replacing an owner.
