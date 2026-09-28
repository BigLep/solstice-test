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

### Upgrades
Versions are bumped in [`version.json`](version.json) with notes in [`CHANGELOG.md`](CHANGELOG.md); the [Releaser workflow](.github/workflows/releaser.yml) tags and pre-releases them. Implementation upgrades run through the [Upgrade workflow](.github/workflows/upgrade.yml), a thin wrapper around [`tools/upgrade.py`](tools/upgrade.py): rehearse, propose to the owner Safes, track the hold, execute, verify (which records into the release). The runbook is [docs/UPGRADE.md](docs/UPGRADE.md); [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) covers new networks. Under the hood, in the order they are used:
* [`script/Rehearse.s.sol`](script/Rehearse.s.sol): full upgrade dry run in a local fork (impersonated owners, hold, execute, verify).
* [`script/Upgrade.s.sol`](script/Upgrade.s.sol): checks a deployed implementation against a local build and prints the `upgradeToAndCall` calldata and task id. [`script/UpgradeBase.sol`](script/UpgradeBase.sol) holds what the three scripts share.
* [`tools/upgrade.py`](tools/upgrade.py), run with `uv run`: every upgrade operation as one command, using safe-eth-py for the Safe proposals.
* [`script/Verify.s.sol`](script/Verify.s.sol): read-only check that the live proxies and implementations match the checked-out source and [`deployments.json`](deployments.json).
* [`tools/storage_layout.py`](tools/storage_layout.py) with [`test/layout/StorageLayoutProbe.sol`](test/layout/StorageLayoutProbe.sol) and [`test/StorageSlots.t.sol`](test/StorageSlots.t.sol): CI gate for ERC-7201 namespaced storage; fails non-append-only changes and pins slot constants.

## Deploy Contract workflow
`.github/workflows/deploy-contract.yml` runs either script from GitHub Actions.
It never runs on push or pull request; trigger it manually from the Actions tab (Run workflow) or with the GitHub CLI:
```sh
# Dry run (the default): simulates against the network without sending transactions
gh workflow run deploy-contract.yml -f network=Calibnet -f target="Implementations only"
# Live deployment
gh workflow run deploy-contract.yml -f network=Mainnet -f target="Implementations only" -f dry_run=false
```
Live runs use the `calibnet` or `mainnet` [environment](https://github.com/filecoin-project/solstice/settings/environments), which holds the operations key `DEPLOYER_PRIVATE_KEY` and whose required reviewers gate live runs (see [docs/UPGRADE.md](docs/UPGRADE.md)).
Select the branch or tag to deploy with `--ref`; the commit is recorded in the run summary.
