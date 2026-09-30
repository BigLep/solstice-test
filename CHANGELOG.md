# Changelog

Each version is one tag and one GitHub release covering both SRA and SWA. The release is created automatically as a pre-release when `version.json` changes on `main` (see `.github/workflows/releaser.yml`) and is promoted to a release when the mainnet upgrade is verified. Put the notes for the next version under its heading before merging the bump.

## v1.0.2

- F11 test for filecoin-project/solstice#86: version bump whose tag was already pushed on an unrelated commit.

## v1.0.1

- Test-only upgrade for filecoin-project/solstice#86: a governance modifier reverts with `NoOwners()` instead of `NotOwner` when no owners are configured (unreachable on the deployed contracts). No storage change.

## v1.0.0

- Initial nv29 deployment of ServiceRewardsActor and StreamWeightActor behind ERC-1967 proxies on calibration and mainnet ([#83](https://github.com/filecoin-project/solstice/pull/83)).
