# Upgrading SRA and SWA

How a merged code change becomes the live implementation behind the ServiceRewardsActor (SRA) and StreamWeightActor (SWA) proxies on calibration and mainnet. The two proxies are permanent: their addresses are `sra` and `swa` in [`deployments.json`](../deployments.json) and are hardwired into Lotus ([lotus#13809](https://github.com/filecoin-project/lotus/pull/13809)). An upgrade replaces the implementation behind each proxy; it never moves a proxy. See [DEPLOYMENT.md](./DEPLOYMENT.md) only if you are bringing up a new network.

## How an upgrade works

| Piece | Where | What it does |
|---|---|---|
| Proxies | Two OpenZeppelin [`ERC1967Proxy`](../lib/openzeppelin-contracts/contracts/proxy/ERC1967/ERC1967Proxy.sol) contracts; addresses `sra` and `swa` in [`deployments.json`](../deployments.json) | Hold all state and delegate every call to their implementation. No admin; only the implementation's own logic can change which implementation a proxy points at. |
| Implementations | [`ServiceRewardsActor`](../src/ServiceRewardsActor.sol) and [`StreamWeightActor`](../src/StreamWeightActor.sol), one deployment each per version; the live one is whatever each proxy's ERC-1967 slot points at, recorded in the [release](https://github.com/filecoin-project/solstice/releases) for the version | Inherit [`UnanimousProxied`](../src/lib/UnanimousProxied.sol), whose `_authorizeUpgrade` is gated by the `unanimous` modifier in [`UnanimousGovernance`](../src/lib/UnanimousGovernance.sol). SRA and SWA are always upgraded together. |
| Version | [`version.json`](../version.json) and [`CHANGELOG.md`](../CHANGELOG.md) | One version covers both contracts. Bumping it on `main` makes the [Releaser workflow](https://github.com/filecoin-project/solstice/actions/workflows/releaser.yml) ([source](../.github/workflows/releaser.yml)) tag the commit and open a pre-release with the changelog section. |
| Owners | Two [Safe](https://safe.filecoin.io) multisigs per contract: `sraOwner1`, `sraOwner2`, `swaOwner1`, `swaOwner2` in [`deployments.json`](../deployments.json) | The only parties that can approve an upgrade. |
| Hold | `hold` in [`deployments.json`](../deployments.json), fixed at deployment as an immutable and the same for every task | Epochs that must pass after the second owner's approval before a task can execute. |
| Operations key (`DEPLOYER_PRIVATE_KEY`) | Secret on the [`calibnet`](https://github.com/filecoin-project/solstice/settings/environments/22478295461/edit) and [`mainnet`](https://github.com/filecoin-project/solstice/settings/environments/22478417501/edit) [environments](https://github.com/filecoin-project/solstice/settings/environments) | Deploys implementations, queues proposals on the owner Safes (it is registered there as a [proposer](https://help.safe.global/articles/1671337645-proposers)), executes, pays gas. A plain key with no power over the contracts; not an owner key. |

The upgrade call is [`upgradeToAndCall(newImplementation, data)`](../lib/openzeppelin-contracts/contracts/proxy/utils/UUPSUpgradeable.sol) on the proxy. Its task id is `keccak256(calldata)`, so both owners must send byte-identical calldata with zero value.

| Step | Who | Effect |
|---|---|---|
| Submit | Whichever owner Safe executes first | `Submitted` and `Approved` events. Nothing changes yet. |
| Approve | The other owner Safe | Second `Approved`. The hold starts at this block. |
| Hold | Anyone | Execution reverts with `HoldUntil(epoch)` until the hold elapses. Either owner can `veto(taskId)`. |
| Execute | Anyone | The proxy's implementation slot changes, `data` (if any) runs, the task is deleted. |

## Steps

Calibration first, then mainnet, from the same tag. Steps 2 to 7 are dispatches of the [Upgrade workflow](https://github.com/filecoin-project/solstice/actions/workflows/upgrade.yml) or the [Deploy Contract workflow](https://github.com/filecoin-project/solstice/actions/workflows/deploy-contract.yml), always with the version tag as the ref. Each workflow run is a thin wrapper around [`tools/upgrade.py`](../tools/upgrade.py), which can also be run locally with the same arguments. Each GitHub Action run's summary is the record; link it from the [tracking issue](#0-open-a-tracking-issue).

### 0. Open a tracking issue

Use the [upgrade issue template](https://github.com/filecoin-project/solstice/issues/new?template=upgrade.md). Progress and decisions go in issue comments; the durable record (implementation addresses, transaction hashes) accumulates in the GitHub release automatically.

Every SRA or SWA code upgrade needs an accepted [FIP](https://github.com/filecoin-project/FIPs) first: [FIP-0118 section 4.2](https://github.com/filecoin-project/FIPs/blob/master/FIPS/fip-0118.md#42-governance-tiers-and-powers) lists "upgrade the SWA's code" among the SWA writes that each require a FIP, and "upgrade the SRA's code" as the one registry change that does, and the [section 4.4](https://github.com/filecoin-project/FIPs/blob/master/FIPS/fip-0118.md#44-the-fip--governance-repository-boundary) table gives the process for SWA or SRA code as "FIP, both multisigs, on-chain hold; no network upgrade". The owner Safes approve on the strength of that FIP. Link it in the issue before step 1.

### 1. Merge

The PR carries the code change, the next version in [`version.json`](../version.json), and its notes under that version's heading in [`CHANGELOG.md`](../CHANGELOG.md). CI does the safety checks: the [Storage Layout workflow](https://github.com/filecoin-project/solstice/actions/workflows/storage-layout.yml) fails any change to the namespaced structs that is not append-only, using the compiler's layout of [`StorageLayoutProbe`](../test/layout/StorageLayoutProbe.sol) via [`tools/storage_layout.py`](../tools/storage_layout.py); [`StorageSlots.t.sol`](../test/StorageSlots.t.sol) pins every slot constant to its ERC-7201 derivation; and [`UnanimousProxied.t.sol`](../test/UnanimousProxied.t.sol) covers the governance paths. If the layout check fails, the change needs a storage migration, which this runbook does not cover; stop and design that first. On merge, the [Releaser workflow](https://github.com/filecoin-project/solstice/actions/workflows/releaser.yml) tags the commit and creates the GitHub pre-release. Link the PR and the GitHub pre-release from the issue.

### 2. Rehearse

Dispatch [Upgrade](https://github.com/filecoin-project/solstice/actions/workflows/upgrade.yml) with operation `rehearse`, the network, ref the tag. It runs [`script/Rehearse.s.sol`](../script/Rehearse.s.sol): one local fork in which both implementations are built from source, and for each contract both owner Safes are impersonated to submit and approve, early execution is shown to revert, the hold is rolled past, and the upgrade executes. The summary ends with `REHEARSAL COMPLETE` or the failing step. Nothing is sent. Rehearse on each network before its step 3, since the two networks have different holds and parameters.

### 3. Deploy the implementations

Dispatch [Deploy Contract](https://github.com/filecoin-project/solstice/actions/workflows/deploy-contract.yml) with target "Implementations only", dry run off, ref the tag. It deploys both implementations from the tag and verifies their source on Sourcify. Both contracts are upgraded every time, even if only one changed: shared code (governance, epoch and gate libraries) means either bytecode can change when the other does, and the verifier rebuilds both from the tag. Take the SRA and SWA implementation addresses from the run summary; every later step needs both.

### 4. Propose to the owners

Dispatch [Upgrade](https://github.com/filecoin-project/solstice/actions/workflows/upgrade.yml) with operation `propose`, the network, and both implementation addresses. This runs in the network's [environment](https://github.com/filecoin-project/solstice/settings/environments), so it waits for a required reviewer other than the dispatcher: two humans sign off on every proposal. The reviewer's job is to confirm the run's ref is a `v*` tag whose commit is on `main` before approving. The run then runs the full verifier ([`script/Verify.s.sol`](../script/Verify.s.sol)) with the new addresses as candidates: it rebuilds both implementations from the tag and compares the runtime code against the candidates instead of the live implementations, refuses a candidate equal to the current implementation, and still checks the live proxies' code, owners and seeded state. Only then does it queue the upgrade transaction on all four owner Safes through the [Filecoin Safe Transaction Service](https://transaction.safe.filecoin.io/). Rerunning `propose` is safe; it skips Safes where the transaction is already queued.

The proposer then tells each owner group that their Safe has a transaction queued, and each owner group confirms and executes it in the [Safe app](https://safe.filecoin.io); the Submit/Approve table under "How an upgrade works" says what the first and second executions do.

> [!NOTE]
> If there is an issue with [Safe's proposer functionality](https://help.safe.global/articles/1671337645-proposers), the same run summary prints each proxy address and calldata; the owners can enter those in the Safe app's transaction builder instead. It is the same transaction.

### 5. Track the hold

Dispatch [Upgrade](https://github.com/filecoin-project/solstice/actions/workflows/upgrade.yml) with operation `status` and both implementation addresses. The summary shows, for SRA and SWA, how many owners have approved and the epoch the hold ends. There is no need to poll: run it once after each owner group reports that it has executed, to confirm the approval landed and (after the second) to read the epoch the hold ends, and once more before step 6. If something is wrong, either owner cancels with the veto calldata printed in the same summary. `status` reports whatever task the given addresses name, so running it with the previous implementation addresses shows a prepared rollback.

### 6. Execute

After the holds, dispatch [Upgrade](https://github.com/filecoin-project/solstice/actions/workflows/upgrade.yml) with operation `execute` and both implementation addresses. Anyone may execute, but running it through the workflow keeps the record in one place. The two holds end at different epochs because each contract has its own owner Safes; the run sends nothing until both are executable, and fails if either transaction reverts or a proxy's implementation slot does not change.

### 7. Verify

Dispatch [Upgrade](https://github.com/filecoin-project/solstice/actions/workflows/upgrade.yml) with operation `verify`. It runs [`script/Verify.s.sol`](../script/Verify.s.sol), which rebuilds both implementations and both proxies from the tag and checks them against the live contracts, ending with `ALL CHECKS PASSED` or the failed check. On success the run appends the live implementation addresses and epoch to the release; on mainnet it also promotes the pre-release to the final release. [`deployments.json`](../deployments.json) does not change: the two proxy addresses are all it records for the live contracts, and the chain is the source of truth for the implementation behind each.

### 8. Repeat for mainnet

Repeat steps 2 to 7 on mainnet.

## Rollback

- Before execution, rollback is a veto: either owner sends the veto calldata printed by `status`, and the task is gone. Nothing has changed on chain, so this is always safe.
- After execution, rollback is a new upgrade back to the previous implementations, subject to the full hold. It is safe when the new version only appended storage (which is all the [layout gate](#1-merge) in [`tools/storage_layout.py`](../tools/storage_layout.py) allows), because the previous code simply ignores the new fields. It is not safe if the new version ran a reinitializer or migration that reinterpreted existing storage; that case needs its own design before it is attempted. The [tracking issue](#0-open-a-tracking-issue) template asks for the previous implementation addresses up front so the rollback proposal can be built from them.
- Optional, for a change risky enough to want a fast rollback: once the upgrade has executed (step 6), dispatch `propose` with the previous implementation addresses and ref the previous version's tag. This only works after execution: the code check rebuilds from the checked-out ref, and the verifier refuses a candidate equal to the implementation a proxy already points at, since such a proposal would be a no-op that still consumes a hold and, in practice, means someone pasted the live address instead of the new one. Have the first owner execute it at once and the second owner execute it at the start of the monitoring window you want; the rollback becomes executable one hold after that second execution. From then until an owner vetoes it, anyone can execute it, so the final step is that veto; the [issue template](../.github/ISSUE_TEMPLATE/upgrade.md) has a checkbox for it, and `status` with the previous addresses shows the rollback task.

## Related

- [#26](https://github.com/filecoin-project/solstice/issues/26): the issue that asked for this process.
- [#84](https://github.com/filecoin-project/solstice/pull/84): the PR that added it, including the one-time setup (environments, operations key, proposer registration on the owner Safes) and what is deliberately out of scope.
