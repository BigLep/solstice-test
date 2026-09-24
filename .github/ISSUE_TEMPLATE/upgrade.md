---
name: SRA/SWA upgrade
about: Track one implementation upgrade of the SRA or SWA proxy, calibration then mainnet
title: "Upgrade <sra|swa> to vX.Y.Z"
labels: upgrade
---

Runbook: [docs/UPGRADE.md](https://github.com/filecoin-project/solstice/blob/main/docs/UPGRADE.md). This issue tracks progress: check items off and link each run or comment under it. The durable record (tag, addresses, transaction hashes) lives in the GitHub release for the tag, not here.

Target: `<sra|swa>`  Tag: `vX.Y.Z`  Previous implementation (for rollback): `0x...`

- [ ] [Merged and tagged](https://github.com/filecoin-project/solstice/blob/main/docs/UPGRADE.md#1-merge-and-tag); Storage Layout and Test CI green on the tag
- [ ] [Rehearsed](https://github.com/filecoin-project/solstice/blob/main/docs/UPGRADE.md#2-rehearse) on a calibration fork
  - run:
- [ ] Calibration: [implementation deployed, pre-release created](https://github.com/filecoin-project/solstice/blob/main/docs/UPGRADE.md#3-deploy-the-implementation-and-cut-a-pre-release)
  - run:
  - implementation:
- [ ] Calibration: [proposed](https://github.com/filecoin-project/solstice/blob/main/docs/UPGRADE.md#4-propose-to-the-owners) and both owners executed
  - run:
  - owner 1 tx:
  - owner 2 tx:
- [ ] Calibration: [hold elapsed](https://github.com/filecoin-project/solstice/blob/main/docs/UPGRADE.md#5-track-the-hold) and [executed](https://github.com/filecoin-project/solstice/blob/main/docs/UPGRADE.md#6-execute)
  - run:
  - execute tx:
- [ ] Calibration: [verified](https://github.com/filecoin-project/solstice/blob/main/docs/UPGRADE.md#7-verify-and-record)
  - run:
- [ ] Mainnet: implementation deployed
  - run:
  - implementation:
- [ ] Mainnet: proposed and both owners executed
  - run:
  - owner 1 tx:
  - owner 2 tx:
- [ ] Mainnet: hold elapsed and executed
  - run:
  - execute tx:
- [ ] Mainnet: verified, release promoted from pre-release
  - run:
  - release:
