---
name: SRA/SWA upgrade
about: Track one implementation upgrade of the SRA or SWA proxy, calibration then mainnet
title: "Upgrade <sra|swa> to <tag>"
labels: upgrade
---

Instructions are in [docs/UPGRADE.md](../../docs/UPGRADE.md). Keep this table current; put everything else (command output, decisions) in comments and link them from the checklist.

| | Calibration | Mainnet |
|---|---|---|
| Tag / commit | | |
| New implementation | | |
| Safe proposals (safeTxHash, owner 1 / owner 2) | | |
| Owner 1 submit tx / owner 2 approve tx | | |
| Hold ends (epoch) | | |
| Execute tx | | |
| `Verify.s.sol` result (link to comment) | | |
| Previous implementation (for rollback) | | |

## Checklist

- [ ] Change merged; `Storage Layout` and `Test` CI green on the tagged commit (step 1)
- [ ] Rehearsal passed on a calibration fork (step 2, link comment)
- [ ] Calibration: implementation deployed via `Deploy Contract` workflow (step 3, link run)
- [ ] Calibration: proposed to both owner Safes, both executed (step 4)
- [ ] Calibration: hold elapsed, executed (steps 5 and 6)
- [ ] Calibration: `Verify.s.sol` passed (step 7, link comment)
- [ ] Mainnet: implementation deployed (step 3)
- [ ] Mainnet: proposed and approved (step 4)
- [ ] Mainnet: hold elapsed, executed (steps 5 and 6)
- [ ] Mainnet: `Verify.s.sol` passed (step 7)
- [ ] `deployments.json` unchanged (proxies do not move); close issue
