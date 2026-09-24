---
name: SRA/SWA upgrade
about: Track one implementation upgrade of the SRA or SWA proxy, calibration then mainnet
title: "Upgrade to vX.Y.Z"
labels: upgrade
---

Runbook: [docs/UPGRADE.md](https://github.com/filecoin-project/solstice/blob/main/docs/UPGRADE.md). This issue tracks progress: check items off and link each run or comment under it. The durable record (tag, addresses, transaction hashes) lives in the GitHub release for the tag, not here.

Tag: `vX.Y.Z`  FIP: `<link, or why none is needed>`  Previous implementations (for rollback): SRA `0x...`, SWA `0x...`

- [ ] [Merged](https://github.com/filecoin-project/solstice/blob/main/docs/UPGRADE.md#1-merge) with version bump and changelog; pre-release created by Releaser
  - pre-release:
- [ ] [Rehearsed](https://github.com/filecoin-project/solstice/blob/main/docs/UPGRADE.md#2-rehearse) on a calibration fork
  - run:
- [ ] Calibration: [implementations deployed](https://github.com/filecoin-project/solstice/blob/main/docs/UPGRADE.md#3-deploy-the-implementation)
  - run:
  - SRA implementation:
  - SWA implementation:
- [ ] Calibration: [proposed](https://github.com/filecoin-project/solstice/blob/main/docs/UPGRADE.md#4-propose-to-the-owners) and both owners executed
  - run:
  - owner 1 tx:
  - owner 2 tx:
- [ ] Calibration: [hold elapsed](https://github.com/filecoin-project/solstice/blob/main/docs/UPGRADE.md#5-track-the-hold) and [executed](https://github.com/filecoin-project/solstice/blob/main/docs/UPGRADE.md#6-execute)
  - run:
  - execute tx:
- [ ] Calibration: [verified](https://github.com/filecoin-project/solstice/blob/main/docs/UPGRADE.md#7-verify)
  - run:
- [ ] Mainnet: implementations deployed
  - run:
  - SRA implementation:
  - SWA implementation:
- [ ] Mainnet: proposed and both owners executed
  - run:
  - owner 1 tx:
  - owner 2 tx:
- [ ] Mainnet: hold elapsed and executed
  - run:
  - execute tx:
- [ ] Mainnet: verified (the run promotes the pre-release to the final release)
  - run:
  - final release:
