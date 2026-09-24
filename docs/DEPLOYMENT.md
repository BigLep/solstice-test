# Deployment

The SRA and SWA proxies were deployed once for nv29 and will not be deployed again on calibration or mainnet. Code changes are [upgrades](./UPGRADE.md) behind the same proxies, and moving a proxy would itself be a network upgrade.

The live addresses are in [`deployments.json`](../deployments.json) (`sra` and `swa`; the implementation behind each is whatever the proxy points at, recorded in the GitHub release of the tag that deployed it) and are hardwired into Lotus by [lotus#13809](https://github.com/filecoin-project/lotus/pull/13809). The verification record for that deployment, with explorer links, is in [#84](https://github.com/filecoin-project/solstice/pull/84).

## Deploying on a new network

1. Add a [`deployments.json`](../deployments.json) entry for the chain id (owners, orchestrator, epoch parameters, `hold`; `sra` and `swa` zero) and merge it.
2. Dispatch the [Deploy Contract workflow](https://github.com/filecoin-project/solstice/actions/workflows/deploy-contract.yml) ([source](https://github.com/filecoin-project/solstice/blob/main/.github/workflows/deploy-contract.yml)) with target "Full deployment" and dry run off. It needs `DEPLOYER_PRIVATE_KEY` on the network's GitHub environment. Any funded key works: it pays gas and has no power over the contracts afterwards, so it does not need to be a multisig.
3. Commit the `deployments.json` diff from the job summary, then dispatch the [Upgrade workflow](https://github.com/filecoin-project/solstice/actions/workflows/upgrade.yml) with action `verify`, or run [`script/Verify.s.sol`](../script/Verify.s.sol) locally. It ends with `ALL CHECKS PASSED` or names the failed check.
