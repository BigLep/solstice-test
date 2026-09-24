// SPDX-License-Identifier: Apache-2.0 OR MIT
pragma solidity ^0.8.36;

import {console} from "forge-std/console.sol";

import {IERC1822Proxiable} from "@openzeppelin/contracts/interfaces/draft-IERC1822.sol";

import {Epoch} from "../src/lib/Epoch.sol";
import {UnanimousProxied} from "../src/lib/UnanimousProxied.sol";
import {UpgradeBase} from "./UpgradeBase.sol";

/// @notice Checks a deployed implementation against the checked-out source and prints the upgrade calldata.
/// @dev Usage (see docs/UPGRADE.md; the implementation itself is deployed by the Deploy Contract workflow):
///
///        TARGET=sra NEW_IMPLEMENTATION=0x... forge script script/Upgrade.s.sol --rpc-url $ETH_RPC_URL
///
///      Sends nothing. Rebuilds the implementation locally from source and `deployments.json`, requires the
///      on-chain runtime code to match, requires it to be UUPS-compatible and different from the current one,
///      then prints the exact `upgradeToAndCall` calldata, task id and veto calldata that the owner Safes must
///      send to the proxy. Optional `UPGRADE_CALLDATA` (hex) is the `data` argument, for a reinitializer.
contract UpgradeScript is UpgradeBase {
    function run() public returns (address sra, address swa) {
        string memory key = _configKey();
        string memory json = vm.readFile(CONFIG_PATH);
        Config memory config = _loadConfig(json, key);
        sra = _readAddress(json, key, "sra");
        swa = _readAddress(json, key, "swa");
        require(sra != address(0) && swa != address(0), "deployments.json has no sra/swa address for this chain");

        Target memory t = _resolveTarget(config, sra, swa);
        require(t.proxy.code.length != 0, "proxy has no code on this chain");
        address current = _implementationOf(t.proxy);
        require(current.code.length != 0, "proxy implementation slot is empty");

        address newImplementation = vm.envAddress("NEW_IMPLEMENTATION");
        require(newImplementation.code.length != 0, "new implementation has no code");
        _checkCode(
            t.isSra ? "SRA new implementation" : "SWA new implementation",
            newImplementation,
            _buildImplementation(t, config, sra)
        );
        require(newImplementation != current, "new implementation equals current implementation");
        require(
            IERC1822Proxiable(newImplementation).proxiableUUID() == IMPLEMENTATION_SLOT,
            "new implementation is not UUPS (proxiableUUID mismatch)"
        );

        bytes memory upgradeCall = _upgradeCall(newImplementation);
        bytes32 taskId = keccak256(upgradeCall);

        console.log("");
        console.log("==== UPGRADE STAGED ====");
        console.log("target                 ", t.isSra ? "sra" : "swa");
        console.log("chain id               ", block.chainid);
        console.log("proxy                  ", t.proxy);
        console.log("current implementation ", current);
        console.log("new implementation     ", newImplementation);
        console.log("hold (epochs)          ", Epoch.unwrap(t.hold));
        console.log("task id                ", vm.toString(taskId));
        console.log("");
        console.log("Owner 1, then owner 2, then (after the hold) anyone, send this exact calldata to the proxy:");
        console.log(vm.toString(upgradeCall));
        console.log("");
        console.log("Either owner can cancel during the hold by sending this calldata to the proxy:");
        console.log(vm.toString(abi.encodeCall(UnanimousProxied.veto, (taskId))));
    }
}
