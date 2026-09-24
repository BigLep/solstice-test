# Upgrading SRA and SWA

How a merged code change becomes the live implementation behind the ServiceRewardsActor (SRA) or StreamWeightActor (SWA) proxy on calibration and mainnet. The proxies are permanent; their addresses are in [`deployments.json`](../deployments.json) and hardwired into Lotus ([lotus#13809](https://github.com/filecoin-project/lotus/pull/13809)). See [DEPLOYMENT.md](./DEPLOYMENT.md) only if you are bringing up a new network.

## How an upgrade works

| Piece | Where | What it does |
|---|---|---|
| Proxy | OpenZeppelin [`ERC1967Proxy`](../lib/openzeppelin-contracts/contracts/proxy/ERC1967/ERC1967Proxy.sol); addresses `sra` and `swa` in [`deployments.json`](../deployments.json) | Holds state and delegates to the implementation. No admin; only the implementation's own logic can change it. |
| Implementation | [`ServiceRewardsActor`](../src/ServiceRewardsActor.sol), [`StreamWeightActor`](../src/StreamWeightActor.sol); the live one is whatever the proxy's ERC-1967 slot points at, recorded in the [release](https://github.com/filecoin-project/solstice/releases) for the version | Inherit [`UnanimousProxied`](../src/lib/UnanimousProxied.sol), whose `_authorizeUpgrade` is gated by the `unanimous` modifier in [`UnanimousGovernance`](../src/lib/UnanimousGovernance.sol). |
| Version | [`version.json`](../version.json) and [`CHANGELOG.md`](../CHANGELOG.md) | One version covers both contracts. Bumping it on `main` makes the [Releaser workflow](https://github.com/filecoin-project/solstice/actions/workflows/releaser.yml) ([source](../.github/workflows/releaser.yml)) tag the commit and open a pre-release with the changelog section. |
| Owners | Two [Safe](https://safe.filecoin.io) multisigs per contract: `sraOwner1`, `sraOwner2`, `swaOwner1`, `swaOwner2` in [`deployments.json`](../deployments.json) | The only parties that can approve an upgrade. |
| Hold | `hold` in [`deployments.json`](../deployments.json), fixed at deployment as an immutable | Epochs that must pass after the second owner's approval before the upgrade can execute. |
| Operations key | `DEPLOYER_PRIVATE_KEY` on the [`calibnet`](https://github.com/filecoin-project/solstice/settings/environments/22478295461/edit) and [`mainnet`](https://github.com/filecoin-project/solstice/settings/environments/22478417501/edit) environments | Deploys implementations, proposes to the owner Safes (it is registered there as a proposer), executes, pays gas. A plain key with no power over the contracts; not an owner key. |

The upgrade call is [`upgradeToAndCall(newImplementation, data)`](../lib/openzeppelin-contracts/contracts/proxy/utils/UUPSUpgradeable.sol) on the proxy. Its task id is `keccak256(calldata)`, so both owners must send byte-identical calldata with zero value.

| Step | Who | Effect |
|---|---|---|
| Submit | Owner Safe 1 | `Submitted` and `Approved` events. Nothing changes yet. |
| Approve | Owner Safe 2 | Second `Approved`. The hold starts at this block. |
| Hold | Anyone | Execution reverts with `HoldUntil(epoch)` until the hold elapses. Either owner can `veto(taskId)`. |
| Execute | Anyone | Implementation slot changes, `data` (if any) runs, task is deleted. |

## Steps

Calibration first, then mainnet, from the same tag. Steps 2 to 7 are dispatches of the [Upgrade workflow](https://github.com/filecoin-project/solstice/actions/workflows/upgrade.yml) ([source](../.github/workflows/upgrade.yml)) or the [Deploy Contract workflow](https://github.com/filecoin-project/solstice/actions/workflows/deploy-contract.yml) ([source](../.github/workflows/deploy-contract.yml)), always with the version tag as the ref. Each run's summary is the record; link it from the tracking issue.

### 0. Open a tracking issue

Use the [upgrade issue template](https://github.com/filecoin-project/solstice/issues/new?template=upgrade.md) ([source](../.github/ISSUE_TEMPLATE/upgrade.md)). Progress and decisions go in issue comments; the durable record (addresses, transaction hashes) accumulates in the release automatically.

A change to SRA or SWA behaviour is a protocol change: it needs an accepted [FIP](https://github.com/filecoin-project/FIPs) before it ships, and the owner Safes approve on the strength of that FIP. Link the FIP in the issue before step 1; a fix with no behaviour change (for example a gas or safety fix that the FIP already permits) needs a note in the issue saying so instead.

### 1. Merge

The PR carries the code change, the next version in [`version.json`](../version.json), and its notes under that version's heading in [`CHANGELOG.md`](../CHANGELOG.md). CI does the safety checks: the [Storage Layout workflow](https://github.com/filecoin-project/solstice/actions/workflows/storage-layout.yml) ([source](../.github/workflows/storage-layout.yml)) fails any change to the namespaced structs that is not append-only, using the compiler's layout of [`StorageLayoutProbe`](../test/layout/StorageLayoutProbe.sol) via [`tools/storage_layout.py`](../tools/storage_layout.py); [`StorageSlots.t.sol`](../test/StorageSlots.t.sol) pins every slot constant to its ERC-7201 derivation; and [`UnanimousProxied.t.sol`](../test/UnanimousProxied.t.sol) covers the governance paths. If the layout check fails, the change needs a storage migration, which this runbook does not cover; stop and design that first. On merge, the [Releaser workflow](https://github.com/filecoin-project/solstice/actions/workflows/releaser.yml) tags the commit and creates the pre-release. Link it from the issue.

### 2. Rehearse

Dispatch [Upgrade](https://github.com/filecoin-project/solstice/actions/workflows/upgrade.yml) with action `rehearse`, network Calibnet, target `sra` then again with `swa`, ref the tag. It runs [`script/Rehearse.s.sol`](../script/Rehearse.s.sol): a local fork in which the implementation is built from source, both owner Safes are impersonated to submit and approve, early execution is shown to revert, the hold is rolled past, the upgrade executes, and every verifier check runs. The summary ends with `REHEARSAL COMPLETE` or the failing step. Nothing is sent.

### 3. Deploy the implementation

Dispatch [Deploy Contract](https://github.com/filecoin-project/solstice/actions/workflows/deploy-contract.yml) with target "Implementations only", dry run off, ref the tag. It deploys both implementations from the tag and verifies them on Sourcify. Upgrade both contracts every time, even if only one changed: the verifier rebuilds both from the tag, and shared code (governance, epoch and gate libraries) means either bytecode can change when the other does. Take both addresses from the run summary.

### 4. Propose to the owners

Dispatch [Upgrade](https://github.com/filecoin-project/solstice/actions/workflows/upgrade.yml) with action `propose`, the network, the target and the new implementation address. This runs in the network's [environment](https://github.com/filecoin-project/solstice/settings/environments), so it waits for a required reviewer other than the dispatcher: two humans sign off on every proposal. The reviewer's job is to confirm the run's ref is a `v*` tag whose commit is on `main` before approving. It then runs [`tools/upgrade.py`](../tools/upgrade.py), which rebuilds the implementation from the tag and refuses to continue unless the on-chain runtime code matches ([`script/Upgrade.s.sol`](../script/Upgrade.s.sol)), then queues the identical transaction on both owner Safes through the [Filecoin Safe Transaction Service](https://transaction.safe.filecoin.io/). Each owner group confirms and executes it in the Safe app. Owner 1's execution is the submit; owner 2's is the approve, and the hold starts when it lands.

Note: if there is an issue with [Safe's proposer functionality](https://help.safe.global/articles/1671337645-proposers), the same run summary prints the proxy address and calldata; the owners can enter those in the Safe app's transaction builder instead. It is the same transaction.

### 5. Track the hold

Dispatch [Upgrade](https://github.com/filecoin-project/solstice/actions/workflows/upgrade.yml) with action `status`, the target and the new implementation address. The summary shows how many owners have approved and the epoch the hold ends. If something is wrong, either owner cancels with the veto calldata printed in the same summary.

### 6. Execute

After the hold, dispatch [Upgrade](https://github.com/filecoin-project/solstice/actions/workflows/upgrade.yml) with action `execute`, the target and the new implementation address. Anyone may execute, but running it through the workflow keeps the record in one place.

### 7. Verify

Dispatch [Upgrade](https://github.com/filecoin-project/solstice/actions/workflows/upgrade.yml) with action `verify`. It runs [`script/Verify.s.sol`](../script/Verify.s.sol), which rebuilds both implementations and proxies from the tag and checks them against the live contracts, ending with `ALL CHECKS PASSED` or the failed check. On success the run appends the live implementation addresses and epoch to the release; on mainnet it also promotes the pre-release to the release. `deployments.json` does not change: proxies are the only addresses it records, and the chain is the source of truth for what is behind them.

Repeat steps 3 to 7 on mainnet.

## Rollback

- Before execution, rollback is a veto: either owner sends the veto calldata printed by `status`, and the task is gone. Nothing has changed on chain, so this is always safe.
- After execution, rollback is a new upgrade back to the previous implementation, subject to the full hold. It is safe when the new version only appended storage (which is all the layout gate allows), because the previous code simply ignores the new fields. It is not safe if the new version ran a reinitializer or migration that reinterpreted existing storage; that case needs its own design before it is attempted. Keep the previous implementation address in the tracking issue so the rollback proposal can be built from it.

## Related

- [#26](https://github.com/filecoin-project/solstice/issues/26): the issue that asked for this process.
- [#84](https://github.com/filecoin-project/solstice/pull/84): the PR that added it, including the one-time setup (environments, operations key, proposer registration on the owner Safes) and what is deliberately out of scope.
