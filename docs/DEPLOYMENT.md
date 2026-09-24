# Deployment

The SRA and SWA proxies were deployed once for nv29 and will not be deployed again on calibration or mainnet: code changes are [upgrades](./UPGRADE.md) behind the same proxies, and moving a proxy would itself be a network upgrade. This page records what is live and how to bring up a new network.

## nv29 addresses

Identical on calibration and mainnet, set in Lotus by [lotus#13809](https://github.com/filecoin-project/lotus/pull/13809) and recorded in [`deployments.json`](../deployments.json). Deployed 2026-09-22 ([#83](https://github.com/filecoin-project/solstice/pull/83)) by `0x0000000090d0Fd86602e0F63DAF18371e35Cc1e6`, a key with no further role.

| Contract | Address | Mainnet | Calibration |
|---|---|---|---|
| SRA proxy | `0x0339f205314C8210AF7Cb075d1A96D012e7896a9` | [Blockscout](https://filecoin.blockscout.com/address/0x0339f205314C8210AF7Cb075d1A96D012e7896a9?tab=contract), [Sourcify](https://repo.sourcify.dev/314/0x0339f205314C8210AF7Cb075d1A96D012e7896a9) | [Blockscout](https://filecoin-testnet.blockscout.com/address/0x0339f205314C8210AF7Cb075d1A96D012e7896a9?tab=contract), [Sourcify](https://repo.sourcify.dev/314159/0x0339f205314C8210AF7Cb075d1A96D012e7896a9) |
| SWA proxy | `0x66C11A9F6dfEC3c1557958cF9f575a023EB01421` | [Blockscout](https://filecoin.blockscout.com/address/0x66C11A9F6dfEC3c1557958cF9f575a023EB01421?tab=contract), [Sourcify](https://repo.sourcify.dev/314/0x66C11A9F6dfEC3c1557958cF9f575a023EB01421) | [Blockscout](https://filecoin-testnet.blockscout.com/address/0x66C11A9F6dfEC3c1557958cF9f575a023EB01421?tab=contract), [Sourcify](https://repo.sourcify.dev/314159/0x66C11A9F6dfEC3c1557958cF9f575a023EB01421) |
| SRA implementation (v1) | `0x2FBb2e00ADa8Aca24b7E0F42Df0BB9B36251106b` | [Blockscout](https://filecoin.blockscout.com/address/0x2FBb2e00ADa8Aca24b7E0F42Df0BB9B36251106b?tab=contract) | [Blockscout](https://filecoin-testnet.blockscout.com/address/0x2FBb2e00ADa8Aca24b7E0F42Df0BB9B36251106b?tab=contract) |
| SWA implementation (v1) | `0x31982901ecC96D153f461cbAa6c36447af8aa9f1` | [Blockscout](https://filecoin.blockscout.com/address/0x31982901ecC96D153f461cbAa6c36447af8aa9f1?tab=contract) | [Blockscout](https://filecoin-testnet.blockscout.com/address/0x31982901ecC96D153f461cbAa6c36447af8aa9f1?tab=contract) |

Verified 2026-09-24 from `main` at `0006edc`: [`script/Verify.s.sol`](../script/Verify.s.sol) passes on both networks, and Sourcify reports a full match on creation and runtime bytecode for all eight contracts. Blockscout shows a "bytecode has been changed" banner on most of them; that is an indexer artifact (its stored copy is the `0xfe` placeholder Filecoin returns before an EVM actor exists), not a real mismatch. Treat Sourcify's match as the explorer signal.

The current implementation behind each proxy changes with upgrades; read the ERC-1967 slot or run `Verify.s.sol` rather than trusting this table for it.

## Deploying on a new network

1. Add a `deployments.json` entry for the chain id (owners, orchestrator, epoch parameters, `hold`; `sra` and `swa` zero) and merge it.
2. Dispatch the `Deploy Contract` workflow (from [#73](https://github.com/filecoin-project/solstice/pull/73)) with target "Full deployment" and dry run off. It needs `DEPLOYER_PRIVATE_KEY` set on the network's GitHub environment. Any funded key works; it has no power over the contracts afterwards and does not need to be a multisig. Reusing the nv29 deployer at the same nonces is the only way to get the same addresses, and that is not required.
3. Commit the `deployments.json` diff from the job summary, then verify from the same commit:

```sh
forge script script/Verify.s.sol --rpc-url $ETH_RPC_URL
```

It ends with `ALL CHECKS PASSED` or names the failed check. Explorer verification (Sourcify) happens in the workflow via `--verify`.

`--skip-simulation` in the deploy commands is deliberate: Foundry's anvil-backed gas re-simulation cannot model FEVM gas, so the flag makes it broadcast sequentially with the node's own `eth_estimateGas`.
