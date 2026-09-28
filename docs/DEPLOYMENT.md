# Deployment

The SRA and SWA proxies were deployed once for nv29 and are not expected to be deployed again on calibration or mainnet. A code change is an [upgrade](./UPGRADE.md) of the implementation behind each proxy, and moving a proxy would itself be a network upgrade. This page records where the live proxy addresses come from and how to bring up a new network.

Vocabulary: a **proxy** is the permanent contract that holds state and whose address everyone uses (`sra` and `swa` in [`deployments.json`](../deployments.json)); an **implementation** is the code a proxy currently delegates to, replaced by upgrades and recorded in the [release](https://github.com/filecoin-project/solstice/releases) for each version.

The live proxy addresses are hardwired into Lotus by [lotus#13809](https://github.com/filecoin-project/lotus/pull/13809). The verification record for that deployment, with explorer links for the proxies and the v1 implementations, is in [#84](https://github.com/filecoin-project/solstice/pull/84).

## Deploying on a new network

A new network gets new proxies and new implementations. Every step is a PR or a workflow dispatch.

1. **Config PR.** Add an entry for the chain id to [`deployments.json`](../deployments.json) with the owners, orchestrator, epoch parameters and `hold`, and with `sra` and `swa` present and set to the zero address. Add the network to the `network` choice and RPC map in [`deploy-contract.yml`](../.github/workflows/deploy-contract.yml) and [`.github/actions/setup/action.yml`](../.github/actions/setup/action.yml). Merge it.
2. **Environment.** Create a GitHub [environment](https://github.com/filecoin-project/solstice/settings/environments) named after the network with the secret `DEPLOYER_PRIVATE_KEY`, required reviewers, and the branch and tag policy of the existing ones. Any funded key works: it pays gas and has no power over the contracts afterwards, so it does not need to be a multisig.
3. **Dry run, then deploy.** Dispatch the [Deploy Contract workflow](https://github.com/filecoin-project/solstice/actions/workflows/deploy-contract.yml) ([source](../.github/workflows/deploy-contract.yml)) twice from `main`, first as a dry run, then live:

   ```sh
   gh workflow run deploy-contract.yml --ref main -f network=<Network> -f target="Full deployment (implementations and proxies)"
   gh workflow run deploy-contract.yml --ref main -f network=<Network> -f target="Full deployment (implementations and proxies)" -f dry_run=false
   ```

   The live run deploys both implementations and both proxies and verifies their source on Sourcify. Its summary shows the new proxy addresses as a `deployments.json` diff.
4. **Addresses PR.** Open a PR that applies that diff, so `sra` and `swa` for the network are the live proxy addresses. Merge it.
5. **Verify.** Dispatch the [Upgrade workflow](https://github.com/filecoin-project/solstice/actions/workflows/upgrade.yml) with operation `verify` against `main`, or run [`tools/upgrade.py verify`](../tools/upgrade.py) locally. It ends with `ALL CHECKS PASSED` or names the failed check.
