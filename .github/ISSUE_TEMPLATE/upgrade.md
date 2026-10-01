---
name: SRA/SWA upgrade

about: Track one implementation upgrade of the SRA and SWA proxies, calibration then mainnet
title: "Upgrade to vX.Y.Z"
labels: upgrade
---

Runbook: [docs/UPGRADE.md](https://github.com/filecoin-project/solstice/blob/main/docs/UPGRADE.md). This issue tracks progress: check items off and put each GitHub Action run link or comment link under its item. The durable record (implementation addresses, transaction hashes) lives in the GitHub release for the tag, not here. For a rollback (an upgrade back to the previous tag), open this same template, skip the merge, rehearse and deploy items, and start at propose dispatched at the previous tag.

- Tag: `vX.Y.Z`
- FIP: `<link, or why none is needed>`
- Previous SRA implementation (for rollback): `0x...`
- Previous SWA implementation (for rollback): `0x...`

- [ ] [Merged](https://github.com/filecoin-project/solstice/blob/main/docs/UPGRADE.md#1-merge) the version bump and changelog entry; Storage Layout and Test CI green on the PR
  - version bump and changelog PR:
  - pre-release created by the Releaser:
- [ ] Calibration: [rehearsed](https://github.com/filecoin-project/solstice/blob/main/docs/UPGRADE.md#2-rehearse) (one run covers SRA and SWA)
  - GitHub Action run:
- [ ] Calibration: [implementations deployed](https://github.com/filecoin-project/solstice/blob/main/docs/UPGRADE.md#3-deploy-the-implementations)
  - GitHub Action run:
  - SRA implementation address:
  - SWA implementation address:
- [ ] Calibration: [proposed](https://github.com/filecoin-project/solstice/blob/main/docs/UPGRADE.md#4-propose-to-the-owners); owner groups notified; both owner Safes executed for each contract
  - GitHub Action run:
  - SRA owner 1 tx:
  - SRA owner 2 tx:
  - SWA owner 1 tx:
  - SWA owner 2 tx:
- [ ] Calibration: [hold tracked](https://github.com/filecoin-project/solstice/blob/main/docs/UPGRADE.md#5-track-the-hold)
  - GitHub Action run (status):
- [ ] Calibration: [executed](https://github.com/filecoin-project/solstice/blob/main/docs/UPGRADE.md#6-execute) (the run's summary has the transaction hashes)
  - GitHub Action run (execute):
- [ ] Calibration: [verified](https://github.com/filecoin-project/solstice/blob/main/docs/UPGRADE.md#7-verify); the run appends the result to the pre-release
  - GitHub Action run:
- [ ] Mainnet: [rehearsed](https://github.com/filecoin-project/solstice/blob/main/docs/UPGRADE.md#2-rehearse)
  - GitHub Action run:
- [ ] Mainnet: [implementations deployed](https://github.com/filecoin-project/solstice/blob/main/docs/UPGRADE.md#3-deploy-the-implementations)
  - GitHub Action run:
  - SRA implementation address:
  - SWA implementation address:
- [ ] Mainnet: [proposed](https://github.com/filecoin-project/solstice/blob/main/docs/UPGRADE.md#4-propose-to-the-owners); owner groups notified; both owner Safes executed for each contract
  - GitHub Action run:
  - SRA owner 1 tx:
  - SRA owner 2 tx:
  - SWA owner 1 tx:
  - SWA owner 2 tx:
- [ ] Mainnet: [hold tracked](https://github.com/filecoin-project/solstice/blob/main/docs/UPGRADE.md#5-track-the-hold)
  - GitHub Action run (status):
- [ ] Mainnet: [executed](https://github.com/filecoin-project/solstice/blob/main/docs/UPGRADE.md#6-execute) (the run's summary has the transaction hashes)
  - GitHub Action run (execute):
- [ ] Mainnet: [verified](https://github.com/filecoin-project/solstice/blob/main/docs/UPGRADE.md#7-verify); this `verify` run promotes the pre-release to the final release
  - GitHub Action run:
  - final release:
- [ ] Optional [prepared rollback](https://github.com/filecoin-project/solstice/blob/main/docs/UPGRADE.md#rollback) proposed at the previous tag after execute; first owner executed at once, second at the start of the monitoring window
  - GitHub Action run:
  - owner txs (SRA):
  - owner txs (SWA):
- [ ] Prepared rollback vetoed by an owner after the monitoring window (or executed and verified, if rolling back)
  - veto tx:
