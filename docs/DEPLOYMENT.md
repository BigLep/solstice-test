# SRA and SWA deployment runbook

This is the operator procedure for the one-time deployment of the ServiceRewardsActor (SRA) and StreamWeightActor (SWA) proxies on a network. After deployment, code changes go through [UPGRADE.md](./UPGRADE.md); the proxy addresses never change.

Status: calibration and mainnet were first deployed on 2026-09-17 and then redeployed on 2026-09-22 (#83) after contract fixes, both times from a single deployer key at the same nonces, so the proxies share addresses on both networks (`sra` and `swa` in `deployments.json`). The 2026-09-17 contracts are abandoned. This document therefore applies to new networks only (for example butterflynet or a devnet) and otherwise serves as the record of the live deployment and how to re-verify it. Phase 4 can be run at any time against the live networks; the result as of 2026-09-24 is in the "Live deployment record" section at the end.

The proxy addresses are hardwired into the Lotus nv29 migration, so a wrong or re-deployed address after handoff is a network-level incident. Treat every step below as required, and record the evidence in the tracking issue.

## What gets deployed

`script/DeployAll.s.sol` sends four transactions in one broadcast, reading its parameters from the `deployments.json` entry for the connected chain id:

| Order | Contract | Constructor arguments (all immutable) |
|---|---|---|
| 1 | `ServiceRewardsActor` implementation | `sraOwner1`, `sraOwner2`, `initialOrchestrator`, `initialOrchestratorWallet`, `epochsPerQuarter`, `postPeriod`, `verificationWindow`, `activationEpoch`, `hold` |
| 2 | `ERC1967Proxy` for SRA | implementation 1, `initialize()` calldata |
| 3 | `StreamWeightActor` implementation | `swaOwner1`, `swaOwner2`, `hold`, SRA proxy address |
| 4 | `ERC1967Proxy` for SWA | implementation 3, `initialize()` calldata |

`initialize()` runs inside the proxy constructor. It seats the two owners in storage, seats the initial orchestrator in SRA, and sets the initial gate parameters in SWA. Everything else is an immutable on the implementation, which is why verification reduces to a bytecode comparison plus a handful of storage reads.

After a real broadcast the script writes the two proxy addresses back into `deployments.json` under `sra` and `swa`.

## Roles

| Role | Responsibility |
|---|---|
| Deployer | Holds the funded key that broadcasts. Any key works; it has no rights over the contracts afterwards. |
| Technical owner | Freezes the commit, reviews config, signs off on evidence, gives go/no-go for mainnet. |
| SRA owners, SWA owners | The two-of-two governance parties per contract. Must confirm their addresses in `deployments.json` before deployment. |
| Lotus | Consumes the proxy addresses for the nv29 migration. |

## Prerequisites

- Foundry `v1.7.1` (the version pinned in CI). Newer or older solc or optimizer settings change bytecode and will fail the verification step.
- Repo at the frozen commit with submodules initialized: `git submodule update --init --recursive`.
- A funded deployer key in the Foundry keystore (`cast wallet list`) and `ETH_KEYSTORE_ACCOUNT` exported, or `--private-key`.
- `ETH_RPC_URL` for the target network: `https://api.node.glif.io/rpc/v1` (mainnet, chain id 314) or `https://api.calibration.node.glif.io/rpc/v1` (calibration, chain id 314159).
- A tracking issue for this deployment with the evidence table from the bottom of this document pasted in.

## Phase 1: Freeze and review

1. Merge every PR that must be in the deployed code. Record the commit hash in the tracking issue and tag it (for example `deploy-calibnet-YYYYMMDD`).
2. Review the `deployments.json` entry for the target chain id line by line with the people who own each value:
   - `sraOwner1`, `sraOwner2`, `swaOwner1`, `swaOwner2`: confirmed by each owner party. These cannot be changed after deployment except through the unanimous `replaceOwner` flow.
   - `initialOrchestrator`, `initialOrchestratorWallet`: confirmed by the orchestrator party.
   - `epochsPerQuarter`, `postPeriod`, `verificationWindow`, `activationEpoch`, `hold`: confirmed against FIP-0118 by the technical owner. These are immutable; changing any of them later means a new implementation and an upgrade.
   - `sra` and `swa` must be the zero address. If they are not, a deployment already happened on this chain; stop and reconcile.
3. Confirm CI is green on the frozen commit, including the `Dry Deployment` and `Storage Layout` workflows.

## Phase 2: Dry runs

Run both dry runs from the frozen commit and paste the output summary into the tracking issue.

Offline simulation (no network; proves config parses and constructors and initializers do not revert):

```sh
forge script script/DeployAll.s.sol --chain-id 314159
git checkout deployments.json   # the dry run rewrites sra/swa with simulated addresses
```

Forked simulation (uses live chain state, still sends nothing):

```sh
forge script script/DeployAll.s.sol --rpc-url $ETH_RPC_URL
git checkout deployments.json
```

A revert inside a constructor or initializer is a stop. A failure in Foundry's anvil-backed gas simulation is not; see the note on `--skip-simulation` in Phase 3.

## Phase 3: Broadcast

The preferred path is the `Deploy Contract` GitHub Actions workflow (`.github/workflows/deploy-contract.yml`), dispatched against the frozen tag with target "Full deployment" and dry run off. It checks the RPC chain id, builds a temporary keystore from the environment's `DEPLOYER_PRIVATE_KEY`, broadcasts, uploads the `broadcast/` directory as a run artifact and prints the `deployments.json` diff in the job summary. Run the same dispatch with dry run on first and link both runs in the tracking issue.

```sh
gh workflow run deploy-contract.yml --ref <tag> -f network=Calibnet -f target="Full deployment (implementations and proxies)"
gh workflow run deploy-contract.yml --ref <tag> -f network=Calibnet -f target="Full deployment (implementations and proxies)" -f dry_run=false
```

The equivalent local command, for when the workflow is unavailable, is:

```sh
forge script script/DeployAll.s.sol --broadcast --rpc-url $ETH_RPC_URL
```

`--skip-simulation` is required on Filecoin, as the workflow and README already do. Foundry's pre-broadcast re-simulation runs in an anvil-backed EVM that cannot model FEVM gas, so it either fails or produces Ethereum gas figures. With the flag, Foundry instead broadcasts sequentially and asks the node for `eth_estimateGas` on each transaction, which is the accurate path here. The local simulation of the script logic (Phase 2) still runs; only the gas re-simulation is skipped. `--verify` defaults to Sourcify, which supports both Filecoin networks and takes constructor arguments from the broadcast, so no verifier flags are needed.

When the run completes:

1. Record the four creation transaction hashes and four addresses in the evidence table, from the workflow's broadcast artifact or `broadcast/DeployAll.s.sol/<chainid>/run-latest.json` locally. Once the contracts are verified (Phase 4c) the block explorer keeps the creation transaction and initcode permanently, which is the durable record; the public RPC does not keep transaction bodies indefinitely.
2. Apply the `deployments.json` diff from the job summary (or the local file) on a branch and open a PR titled with the network and commit hash. Do not merge it until Phase 4 passes.

If any transaction fails partway, do not retry blindly. Implementations without a proxy are harmless orphans; a proxy without a recorded address is not. Read the broadcast log, identify what landed, and either finish the sequence by hand with the same constructor arguments or start over and treat the earlier contracts as abandoned.

## Phase 4: Verify

### 4a. Scripted on-chain verification

From the frozen commit, with `deployments.json` containing the live addresses:

```sh
forge script script/Verify.s.sol --rpc-url $ETH_RPC_URL
```

The script sends nothing. It rebuilds both implementations and both proxies locally from the same source, compiler settings and config, and then checks against the live chain:

- Each proxy's ERC-1967 implementation slot points at an implementation whose runtime code matches the local build byte for byte (with only the implementation's own self-address immutable masked). Because owners, hold, orchestrator, epoch parameters and SWA's SRA pointer are immutables, this single comparison proves every constructor argument.
- Each proxy's runtime code matches an unmodified OpenZeppelin `ERC1967Proxy`.
- Each implementation reports `proxiableUUID()` equal to the ERC-1967 implementation slot (so future upgrades will be accepted).
- Each proxy's Initializable version is exactly 1 and not mid-initialization.
- Each proxy's owner set contains exactly the two configured owners and nothing else.
- SRA reports the initial orchestrator as admitted, with an admitted count of 1, and its public epoch getters match config.
- SWA's gate parameters are initialized to the FIP-0118 entry values.

It prints `ALL CHECKS PASSED` or reverts naming the failed check. Paste the full output into the tracking issue. Anyone can rerun this at any later time from the same commit; it is the reproducible record of what was verified.

### 4b. Independent spot checks

These duplicate part of 4a with plain `cast` calls so that a reviewer who does not trust the script can confirm the two most important facts by hand. `PROXY` is the SRA or SWA proxy address.

```sh
# Implementation slot (ERC-1967)
cast storage $PROXY 0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc --rpc-url $ETH_RPC_URL

# Initializable version; expect 0x...01
cast storage $PROXY 0xf0c57e16840df040f15088dc2f81fe391c3923bec73e23a9662efc9c229c6a00 --rpc-url $ETH_RPC_URL

# SRA public immutables
cast call $SRA 'EPOCHS_PER_QUARTER()(uint64)' --rpc-url $ETH_RPC_URL
cast call $SRA 'SRA_UPGRADE_HOLD()(uint64)' --rpc-url $ETH_RPC_URL
cast call $SRA 'isAdmitted(address)(bool)' $INITIAL_ORCHESTRATOR --rpc-url $ETH_RPC_URL
```

Reading current state is necessary but not sufficient on its own: a malicious initial implementation could seed storage during `initialize()` (for example a pre-approved upgrade task in a mapping that cannot be enumerated) and then hand the proxy to the genuine implementation. Ruling that out means anchoring on the creation initcode of each proxy, which pins the initial implementation address and the `initialize()` calldata, and of that implementation. Explorer verification (4c) does exactly this, because Sourcify and Blockscout match against the creation bytecode including constructor arguments, and the explorer keeps the creation transaction after the Glif RPC has pruned it (`cast tx <creation hash>` returns "tx not found" for older transactions even though `cast receipt` works). So 4a proves the present state and 4c proves it was reached honestly; both are required.

### 4c. Explorer source verification

`forge script --verify` submits all four contracts to Sourcify with constructor arguments taken from the broadcast, so after a workflow deployment this is usually already done; confirm each address shows as verified on Sourcify and on Blockscout (`filecoin.blockscout.com` for mainnet, `filecoin-testnet.blockscout.com` for calibration). To verify a contract by hand, or to add Blockscout, use `forge verify-contract`, which needs the constructor arguments supplied explicitly. Generate them from `deployments.json` (example for calibration SRA):

```sh
ARGS=$(cast abi-encode 'c(address,address,address,address,uint64,uint64,uint64,uint64,uint64)' \
  $SRA_OWNER1 $SRA_OWNER2 $INITIAL_ORCHESTRATOR $INITIAL_ORCHESTRATOR_WALLET \
  $EPOCHS_PER_QUARTER $POST_PERIOD $VERIFICATION_WINDOW $ACTIVATION_EPOCH $HOLD)

forge verify-contract $SRA_IMPL src/ServiceRewardsActor.sol:ServiceRewardsActor \
  --chain 314159 --verifier blockscout --verifier-url https://filecoin-testnet.blockscout.com/api/ \
  --constructor-args $ARGS
forge verify-contract $SRA_IMPL src/ServiceRewardsActor.sol:ServiceRewardsActor \
  --chain 314159 --verifier sourcify --constructor-args $ARGS
```

For SWA the arguments are `(address,address,uint64,address)` with the SRA proxy last. For each proxy the contract is `lib/openzeppelin-contracts/contracts/proxy/ERC1967/ERC1967Proxy.sol:ERC1967Proxy` with arguments `(address,bytes)` where the bytes are `0x8129fc1c` (the `initialize()` selector). Mainnet uses `--chain 314` and `https://filecoin.blockscout.com/api/`.

Sourcify and Blockscout are both required, since together they are the initcode anchor described in 4b. Filfox verification is best effort and has been unreliable for other FilOz contracts; do not block on it.

## Phase 5: Handoff and close out

1. Send the SRA proxy, SWA proxy and orchestrator addresses to the Lotus migration owner, and have them confirm by replying with the addresses as they appear in the Lotus PR. Cross-check both directions character by character; a checksum-cased copy from `deployments.json` is the source of truth.
2. Merge the `deployments.json` PR from Phase 3.
3. Fill in the evidence table and have the technical owner mark go/no-go in the tracking issue. Mainnet deployment does not start until the calibration table is complete.
4. Anything learned that changes this document goes into a follow-up PR against `docs/`.

## Rollback

Before Lotus ships the migration, a bad deployment is fixed by deploying a fresh pair and updating the addresses everywhere; the abandoned contracts are inert. After the migration is live, the proxy addresses are permanent and the only corrective path is an [upgrade](./UPGRADE.md).

## Evidence table

Copy this into the tracking issue, one table per network.

| Item | Value |
|---|---|
| Network / chain id | |
| Frozen commit / tag | |
| Foundry version | |
| Deployer address | |
| SRA implementation address / tx | |
| SRA proxy address / tx | |
| SWA implementation address / tx | |
| SWA proxy address / tx | |
| `Verify.s.sol` output (link to paste or CI run) | |
| Implementation slot spot check (SRA, SWA) | |
| Initializable version spot check (SRA, SWA) | |
| Blockscout verification (4 contracts) | |
| Sourcify verification (4 contracts) | |
| Filfox verification (best effort) | |
| Addresses confirmed by Lotus PR link | |
| `deployments.json` PR | |
| Technical owner go/no-go | |

## Live deployment record

Verified 2026-09-24 from `main` at commit 0006edc (the #83 redeploy commit) with `forge script script/Verify.s.sol --rpc-url ...`, plus the explorer checks below. Deployer for all eight contracts: `0x0000000090d0Fd86602e0F63DAF18371e35Cc1e6`. Addresses are identical on both networks; implementations differ in bytecode only through the per-network immutables.

| Contract | Address | Network | Creation tx | Verify.s.sol | Sourcify | Blockscout |
|---|---|---|---|---|---|---|
| SRA proxy | `0x0339f205314C8210AF7Cb075d1A96D012e7896a9` | mainnet | `0x0f9621c112e5790b659eee5551b5380bdbb5624ba1a98491b66d20c797b75a46` | pass | full match (creation and runtime) | verified, stale bytecode warning |
| SRA proxy | `0x0339f205314C8210AF7Cb075d1A96D012e7896a9` | calibration | `0x20ed9f5bba6f94c507861c38680fb331f5ad04efb96b92b6dea7a5dcdd580072` | pass | full match | verified, stale bytecode warning |
| SWA proxy | `0x66C11A9F6dfEC3c1557958cF9f575a023EB01421` | mainnet | `0xf543cbf0f865bd3ca3d47054088fa7de1ebd4309535bdad544f41d7512845cba` | pass | full match | verified, stale bytecode warning |
| SWA proxy | `0x66C11A9F6dfEC3c1557958cF9f575a023EB01421` | calibration | `0xe30d830ca20d87ae4896b33122ca6ed89d4405354020b2ba757c0960d42f4558` | pass | full match | verified, stale bytecode warning |
| SRA implementation | `0x2FBb2e00ADa8Aca24b7E0F42Df0BB9B36251106b` | mainnet | `0xb7f6bc7a7dae4cf29a1b66869fb04d5916db6ddbd19229dfacbee60576ce7ca4` | pass | full match | verified, stale bytecode warning |
| SRA implementation | `0x2FBb2e00ADa8Aca24b7E0F42Df0BB9B36251106b` | calibration | `0x18ae342b8d06a11eca3db48752298b7545c95f60aa69465d703b546e4564b182` | pass | full match | verified, stale bytecode warning |
| SWA implementation | `0x31982901ecC96D153f461cbAa6c36447af8aa9f1` | mainnet | `0x99258110970e3aaf992cd3050ded7726c1d7fdffa6628507c9a74420f2a753be` | pass | full match | verified |
| SWA implementation | `0x31982901ecC96D153f461cbAa6c36447af8aa9f1` | calibration | `0x59f422a3b14c5696876c12fd4282768e7ce9d86f410181d4210121c196c47a98` | pass | full match | verified, stale bytecode warning |

"Stale bytecode warning" is Blockscout's "contract bytecode has been changed" banner. On these contracts Blockscout's stored copy of the deployed bytecode is the single placeholder byte `0xfe` that Filecoin returns from `eth_getCode` before an EVM actor is instantiated; its indexer captured that instead of the real code and never refreshed. Live code matches the verified source (Sourcify full match and `Verify.s.sol`), so the banner is an indexer artifact. Treat Sourcify's creation and runtime match as the authoritative explorer signal.
