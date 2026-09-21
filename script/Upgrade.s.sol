// SPDX-License-Identifier: Apache-2.0 OR MIT
pragma solidity ^0.8.36;

import {console} from "forge-std/console.sol";
import {stdJson} from "forge-std/StdJson.sol";

import {IERC1822Proxiable} from "@openzeppelin/contracts/interfaces/draft-IERC1822.sol";
import {UUPSUpgradeable} from "@openzeppelin/contracts/proxy/utils/UUPSUpgradeable.sol";

import {Epoch} from "../src/lib/Epoch.sol";
import {UnanimousProxied} from "../src/lib/UnanimousProxied.sol";
import {BytecodeCheck} from "./BytecodeCheck.sol";
import {DeploymentScript} from "./DeploymentScript.sol";

/// @notice Stages a UUPS upgrade of the SRA or SWA proxy recorded in `deployments.json`.
/// @dev Usage (see docs/UPGRADE.md for the full runbook):
///
///        # Deploy a new implementation from the current source and config, then print the
///        # exact upgradeToAndCall calldata and task id that BOTH owners must send to the proxy.
///        TARGET=sra forge script script/Upgrade.s.sol --rpc-url $ETH_RPC_URL --broadcast
///
///        # Check and print calldata for an implementation that was already deployed (no transactions sent).
///        TARGET=swa NEW_IMPLEMENTATION=0x... forge script script/Upgrade.s.sol --rpc-url $ETH_RPC_URL
///
///      In both modes the script rebuilds the implementation locally from the checked-out source and config
///      and requires the on-chain runtime code to match, so the printed calldata always refers to code that
///      was built from this commit. The script never calls `upgradeToAndCall` itself. The two owners are
///      expected to be multisigs, so the approval, execution and veto calls are made by the owners from the
///      printed calldata. Optional `UPGRADE_CALLDATA` (hex) overrides the empty `data` argument, for example
///      to invoke a reinitializer.
contract UpgradeScript is DeploymentScript, BytecodeCheck {
    using stdJson for string;

    bytes32 internal constant IMPLEMENTATION_SLOT = 0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc;

    error UnknownTarget(string target);

    struct Target {
        bool isSra;
        address proxy;
        address currentImplementation;
        address newImplementation;
        Epoch hold;
    }

    function run() public returns (address sra, address swa) {
        string memory key = _configKey();
        string memory json = vm.readFile(CONFIG_PATH);
        Config memory config = _loadConfig(json, key);
        sra = json.readAddress(string.concat(key, ".sra"));
        swa = json.readAddress(string.concat(key, ".swa"));
        require(sra != address(0) && swa != address(0), "deployments.json has no sra/swa address for this chain");

        Target memory t = _resolveTarget(sra, swa, config.hold);

        t.newImplementation = vm.envOr("NEW_IMPLEMENTATION", address(0));
        if (t.newImplementation == address(0)) {
            vm.startBroadcast();
            t.newImplementation = _deployImplementation(t.isSra, config, sra);
            vm.stopBroadcast();
        }
        _checkNewImplementation(t, _deployImplementation(t.isSra, config, sra));

        _printStagedUpgrade(t);
    }

    function _resolveTarget(address sra, address swa, Epoch hold) internal view returns (Target memory t) {
        string memory target = vm.envString("TARGET");
        bool isSra = keccak256(bytes(target)) == keccak256("sra");
        bool isSwa = keccak256(bytes(target)) == keccak256("swa");
        require(isSra || isSwa, UnknownTarget(target));

        t.isSra = isSra;
        t.proxy = isSra ? sra : swa;
        t.hold = hold;
        require(t.proxy.code.length != 0, "proxy has no code on this chain");
        t.currentImplementation = address(uint160(uint256(vm.load(t.proxy, IMPLEMENTATION_SLOT))));
        require(t.currentImplementation.code.length != 0, "proxy implementation slot is empty");
    }

    function _deployImplementation(bool isSra, Config memory config, address sraProxy) internal returns (address) {
        return isSra ? _deploySraImplementation(config) : _deploySwaImplementation(config, sraProxy);
    }

    /// @dev Proves the on-chain implementation was built from this source and config, whoever deployed it.
    function _checkNewImplementation(Target memory t, address expected) internal view {
        require(t.newImplementation.code.length != 0, "new implementation has no code");
        _checkCode(t.isSra ? "SRA new implementation" : "SWA new implementation", t.newImplementation, expected);
        require(t.newImplementation != t.currentImplementation, "new implementation equals current implementation");
        require(
            IERC1822Proxiable(t.newImplementation).proxiableUUID() == IMPLEMENTATION_SLOT,
            "new implementation is not UUPS (proxiableUUID mismatch)"
        );
    }

    function _printStagedUpgrade(Target memory t) internal view {
        bytes memory data = vm.envOr("UPGRADE_CALLDATA", bytes(""));
        bytes memory upgradeCall = abi.encodeCall(UUPSUpgradeable.upgradeToAndCall, (t.newImplementation, data));
        bytes32 taskId = keccak256(upgradeCall);
        bytes memory vetoCall = abi.encodeCall(UnanimousProxied.veto, (taskId));

        console.log("");
        console.log("==== UPGRADE STAGED ====");
        console.log("target                 ", t.isSra ? "sra" : "swa");
        console.log("chain id               ", block.chainid);
        console.log("proxy                  ", t.proxy);
        console.log("current implementation ", t.currentImplementation);
        console.log("new implementation     ", t.newImplementation);
        console.log("hold (epochs)          ", Epoch.unwrap(t.hold));
        console.log("task id                ", vm.toString(taskId));
        console.log("");
        console.log("Owner 1, then owner 2, then (after the hold) anyone, send this exact calldata to the proxy:");
        console.log(vm.toString(upgradeCall));
        console.log("");
        console.log("Either owner can cancel during the hold by sending this calldata to the proxy:");
        console.log(vm.toString(vetoCall));
        console.log("");
        console.log("cast equivalents:");
        console.log(
            string.concat(
                "  cast send ", vm.toString(t.proxy), " ", vm.toString(upgradeCall), " --rpc-url $ETH_RPC_URL"
            )
        );
        console.log(
            string.concat("  cast send ", vm.toString(t.proxy), " ", vm.toString(vetoCall), " --rpc-url $ETH_RPC_URL")
        );
    }
}
