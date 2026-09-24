# Upgrading SRA and SWA

How a merged code change becomes the live implementation behind the ServiceRewardsActor (SRA) or StreamWeightActor (SWA) proxy on calibration and mainnet. The proxies are permanent; their addresses are in [`deployments.json`](../deployments.json) and hardwired into Lotus ([lotus#13809](https://github.com/filecoin-project/lotus/pull/13809)). See [DEPLOYMENT.md](./DEPLOYMENT.md) only if you are bringing up a new network.

## How an upgrade works

| Piece | Where | What it does |
|---|---|---|
| Proxy | OpenZeppelin [`ERC1967Proxy`](../lib/openzeppelin-contracts/contracts/proxy/ERC1967/ERC1967Proxy.sol), addresses `sra` and `swa` in [`deployments.json`](../deployments.json) | Holds state and delegates to the implementation. No admin; only the implementation's own logic can change it. |
| Implementation | [`ServiceRewardsActor`](../src/ServiceRewardsActor.sol), [`StreamWeightActor`](../src/StreamWeightActor.sol), recorded as `sraImplementation` and `swaImplementation` in [`deployments.json`](../deployments.json) | Inherit [`UnanimousProxied`](../src/lib/UnanimousProxied.sol), whose `_authorizeUpgrade` is gated by the `unanimous` modifier in [`UnanimousGovernance`](../src/lib/UnanimousGovernance.sol). |
| Owners | Two [Safe](https://safe.filecoin.io) multisigs per contract: `sraOwner1`, `sraOwner2`, `swaOwner1`, `swaOwner2` in [`deployments.json`](../deployments.json) | The only parties that can approve an upgrade. |
| Hold | `hold` in [`deployments.json`](../deployments.json), fixed at deployment as an immutable | Epochs that must pass after the second owner's approval before the upgrade can execute. |
| Proposer key | `PROPOSER_PRIVATE_KEY` on the GitHub environments | Queues transactions on the owner Safes and pays gas. A plain key with no power over the contracts; not an owner key. |

The upgrade call is [`upgradeToAndCall(newImplementation, data)`](../lib/openzeppelin-contracts/contracts/proxy/utils/UUPSUpgradeable.sol) on the proxy. Its task id is `keccak256(calldata)`, so both owners must send byte-identical calldata with zero value.

| Step | Who | Effect |
|---|---|---|
| Submit | Owner Safe 1 | `Submitted` and `Approved` events. Nothing changes yet. |
| Approve | Owner Safe 2 | Second `Approved`. The hold starts at this block. |
| Hold | Anyone | Execution reverts with `HoldUntil(epoch)` until the hold elapses. Either owner can `veto(taskId)`. |
| Execute | Anyone | Implementation slot changes, `data` (if any) runs, task is deleted. |

## Steps

Calibration first, then mainnet, from the same tag. Every step is a dispatch of the [Upgrade workflow](https://github.com/filecoin-project/solstice/actions/workflows/upgrade.yml) ([source](../.github/workflows/upgrade.yml)) or the [Deploy Contract workflow](https://github.com/filecoin-project/solstice/actions/workflows/deploy-contract.yml) ([source](../.github/workflows/deploy-contract.yml)), always with the tag as the ref. Each run's summary is the record; link it from the tracking issue. Local equivalents are in the workflow source.

### 0. Open a tracking issue

Use the [upgrade issue template](../.github/ISSUE_TEMPLATE/upgrade.md). Progress and decisions go in issue comments; the durable record (tag, addresses, transaction hashes) goes in the GitHub release created in step 3.

### 1. Merge and tag

CI does the safety checks on the PR: the [Storage Layout workflow](../.github/workflows/storage-layout.yml) fails any change to the namespaced structs or slot constants that is not append-only, and the [tests](../test/UnanimousProxied.t.sol) cover the governance paths. If the layout check fails, the change needs a storage migration, which this runbook does not cover; stop and design that first. After merge, tag the commit with the next semantic version:

```sh
git tag vX.Y.Z <merge-commit> && git push origin vX.Y.Z
```

### 2. Rehearse

Dispatch Upgrade with action `rehearse`, network Calibnet, ref `vX.Y.Z`. It runs [`script/Rehearse.s.sol`](../script/Rehearse.s.sol): a local fork in which the implementation is built from source, both owner Safes are impersonated to submit and approve, early execution is shown to revert, the hold is rolled past, the upgrade executes, and every verifier check runs. The summary ends with `REHEARSAL COMPLETE` or the failing step. Nothing is sent.

### 3. Deploy the implementation and cut a pre-release

Dispatch Deploy Contract with target "Implementations only", dry run off, ref `vX.Y.Z`. It deploys both implementations from the tag and verifies them on Sourcify; if you are only upgrading one contract, ignore the other address. Take the address from the run summary and create a pre-release that carries it:

```sh
gh release create vX.Y.Z --prerelease --title "vX.Y.Z" --notes "<what changed>; calibnet <sra|swa> implementation 0x..."
```

### 4. Propose to the owners

Dispatch Upgrade with action `propose`, the network, target and the new implementation address. This runs in the network's environment, so it waits for a required reviewer other than the dispatcher: two humans sign off on every proposal. It then runs [`tools/upgrade.sh`](../tools/upgrade.sh), which rebuilds the implementation from the tag and refuses to continue unless the on-chain runtime code matches ([`script/Upgrade.s.sol`](../script/Upgrade.s.sol)), and queues the identical transaction on both owner Safes through the [Filecoin Safe Transaction Service](https://transaction.safe.filecoin.io/). Each owner group then confirms and executes it in the Safe app. Owner 1's execution is the submit; owner 2's is the approve, and the hold starts when it lands.

Note: if there is an issue with [Safe's proposer functionality](https://help.safe.global/articles/1671337645-proposers), the same run summary prints the proxy address and calldata; the owners can enter those in the Safe app's transaction builder instead. It is the same transaction.

### 5. Track the hold

Dispatch Upgrade with action `status`. The summary shows how many owners have approved and the epoch the hold ends. If something is wrong, either owner cancels with the veto calldata printed in the same summary.

### 6. Execute

After the hold, dispatch Upgrade with action `execute`. Anyone may execute, but running it through the workflow keeps the record in one place.

### 7. Verify and record

Dispatch Upgrade with action `verify`. It runs [`script/Verify.s.sol`](../script/Verify.s.sol), which rebuilds both implementations and proxies from the tag and checks them against the live contracts, ending with `ALL CHECKS PASSED` or the failed check. Then open a PR that sets `sraImplementation` or `swaImplementation` in [`deployments.json`](../deployments.json) to the new address; the verifier enforces that field from then on.

Repeat steps 3 to 7 on mainnet. When mainnet is verified, promote the pre-release to a release with the mainnet implementation address and the execute transaction hashes for both networks:

```sh
gh release edit vX.Y.Z --prerelease=false --notes "<notes with addresses and tx hashes>"
```

## One-time setup

- **Proposer key.** Generate a plain key, fund it lightly on both networks, and store it as `PROPOSER_PRIVATE_KEY` on the `calibnet` and `mainnet` GitHub environments. Its only ability is queuing transactions on Safes that have registered it; it cannot sign or execute anything on its own. A Safe cannot be a proposer because proposals are signed off chain.
- **Environment reviewers.** Set required reviewers on both environments and enable "prevent self-review", so a `propose` or `execute` run needs the dispatcher plus one other person.
- **Register the proposer on the owner Safes.** One owner of each of the four Safes adds the proposer address at [safe.filecoin.io](https://safe.filecoin.io) under Settings, Setup, Proposers, once per network. Until this is done, step 4 falls back to the calldata route described there.
