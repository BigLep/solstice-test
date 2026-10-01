# Changelog

Each version is one tag and one GitHub release covering both SRA and SWA. The release is created automatically as a pre-release when `version.json` changes on `main` (see `.github/workflows/releaser.yml`) and is promoted to a release when the mainnet upgrade is verified. Put the notes for the next version under its heading before merging the bump.

## v1.0.5

- Rerun for filecoin-project/solstice#86 with the at_block fix (df8f5f1); contract code unchanged from v1.0.4.

## v1.0.4

- Rerun for filecoin-project/solstice#86 with the #84 fixes (fbfa52e): same contract code as v1.0.1 plus the F13(h) test struct array; exercises the fixed `execute`, `propose` and `verify`.

## v1.0.2

- F11 test for filecoin-project/solstice#86: version bump whose tag was already pushed on an unrelated commit.

## v1.0.1

- Test-only upgrade for filecoin-project/solstice#86: a governance modifier reverts with `NoOwners()` instead of `NotOwner` when no owners are configured (unreachable on the deployed contracts). No storage change.

## v1.0.0

- Initial nv29 deployment of ServiceRewardsActor and StreamWeightActor behind ERC-1967 proxies on calibration and mainnet ([#83](https://github.com/filecoin-project/solstice/pull/83)).
