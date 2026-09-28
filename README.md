# solstice
Supporting contracts and tools for https://github.com/filecoin-project/FIPs/discussions/1249

## Deploy scripts
Run with [`forge`](https://www.getfoundry.sh/).
Both scripts extend `DeploymentScript`, which holds the shared config loading and deployment helpers.
Per-chain parameters and deployed proxy addresses live in `deployments.json`.

### Setup
```sh
# List known keystore accounts
cast wallet list
# Specify your signing wallet
export ETH_KEYSTORE_ACCOUNT=<account name>

# Mainnet
export ETH_RPC_URL=https://api.node.glif.io/rpc/v1
# Calibration
export ETH_RPC_URL=https://api.calibration.node.glif.io/rpc/v1
```

### Deploy all
`script/DeployAll.s.sol` (`DeployAllScript`) deploys both actors, each behind a new proxy, and records the proxies in `deployments.json`.
```sh
forge script script/DeployAll.s.sol --broadcast --verify --rpc-url $ETH_RPC_URL --skip-simulation
```

### Deploy implementations only
`script/DeployImplementation.s.sol` (`DeployImplementationScript`) deploys only new implementations, ready for an upgrade.
The SWA implementation binds to the existing SRA proxy recorded in `deployments.json`.
`deployments.json` is not modified; record the new addresses once the upgrade is live.
```sh
forge script script/DeployImplementation.s.sol --broadcast --verify --rpc-url $ETH_RPC_URL --skip-simulation
```

## Deploy Contract workflow
`.github/workflows/deploy-contract.yml` runs either script from GitHub Actions.
It never runs on push or pull request; trigger it manually from the Actions tab (Run workflow) or with the GitHub CLI:
```sh
# Dry run (the default): simulates against the network without sending transactions
gh workflow run deploy-contract.yml -f network=Calibnet -f target="Implementations only"
# Live deployment
gh workflow run deploy-contract.yml -f network=Mainnet -f target="Implementations only" -f dry_run=false
```
Live runs use the `calibnet` or `mainnet` [environment](https://docs.github.com/en/actions/deployment/targeting-different-environments/using-environments-for-deployment), which must define the secret `DEPLOYER_PRIVATE_KEY`.
Add required reviewers to the `mainnet` environment to gate mainnet deployments.
Select the branch or tag to deploy with `--ref`; the commit is recorded in the run summary.
