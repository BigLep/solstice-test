// SPDX-License-Identifier: Apache-2.0 OR MIT
pragma solidity ^0.8.36;

import {console} from "forge-std/console.sol";

import {UUPSUpgradeable} from "@openzeppelin/contracts/proxy/utils/UUPSUpgradeable.sol";

import {Epoch} from "../src/lib/Epoch.sol";
import {DeploymentScript} from "./DeploymentScript.sol";

/// @dev Shared pieces of the upgrade scripts (Verify, Upgrade, Rehearse): the ERC-1967 slot, the target
///      selected by `TARGET=sra|swa`, the `upgradeToAndCall` calldata, and the runtime-code comparison.
abstract contract UpgradeBase is DeploymentScript {
    /// @dev ERC1967Utils.IMPLEMENTATION_SLOT
    bytes32 internal constant IMPLEMENTATION_SLOT = 0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc;

    error UnknownTarget(string target);

    struct Target {
        bool isSra;
        address proxy;
        address owner1;
        address owner2;
        Epoch hold;
    }

    function _implementationOf(address proxy) internal view returns (address) {
        return address(uint160(uint256(vm.load(proxy, IMPLEMENTATION_SLOT))));
    }

    /// @dev Reads `TARGET` and resolves the proxy, owners and hold for it. Reverts on anything but sra or swa.
    function _resolveTarget(Config memory config, address sra, address swa) internal view returns (Target memory t) {
        string memory target = vm.envString("TARGET");
        t.isSra = keccak256(bytes(target)) == keccak256("sra");
        require(t.isSra || keccak256(bytes(target)) == keccak256("swa"), UnknownTarget(target));
        t.proxy = t.isSra ? sra : swa;
        t.owner1 = t.isSra ? config.sraOwner1 : config.swaOwner1;
        t.owner2 = t.isSra ? config.sraOwner2 : config.swaOwner2;
        t.hold = config.hold;
    }

    /// @dev Builds the target's implementation from the checked-out source, in the simulation only.
    function _buildImplementation(Target memory t, Config memory config, address sra) internal returns (address) {
        return t.isSra ? _deploySraImplementation(config) : _deploySwaImplementation(config, sra);
    }

    /// @dev `upgradeToAndCall(impl, UPGRADE_CALLDATA)`; `UPGRADE_CALLDATA` defaults to empty.
    function _upgradeCall(address implementation) internal view returns (bytes memory) {
        return
            abi.encodeCall(UUPSUpgradeable.upgradeToAndCall, (implementation, vm.envOr("UPGRADE_CALLDATA", bytes(""))));
    }

    /// @dev UUPSUpgradeable stores `__self = address(this)` as an immutable, so an implementation's runtime code
    ///      embeds its own address. Both copies are compared with their own address zeroed out; every other
    ///      immutable (owners, hold, orchestrator, epoch parameters, SWA's SRA pointer) must match byte for byte.
    function _checkCode(string memory label, address live, address expected) internal view {
        require(live.code.length != 0, string.concat(label, ": no code at implementation"));
        bytes memory liveCode = live.code;
        bytes memory expectedCode = expected.code;
        _maskAddress(liveCode, live);
        _maskAddress(expectedCode, expected);
        require(liveCode.length == expectedCode.length, string.concat(label, ": runtime code length mismatch"));
        bytes32 liveHash = keccak256(liveCode);
        bytes32 expectedHash = keccak256(expectedCode);
        console.log(string.concat("[", label, "] live code hash (self masked)     "), vm.toString(liveHash));
        console.log(string.concat("[", label, "] expected code hash (self masked) "), vm.toString(expectedHash));
        require(liveHash == expectedHash, string.concat(label, ": runtime code mismatch"));
    }

    /// @dev Zeroes every 20-byte occurrence of `self` in `code`, in place.
    function _maskAddress(bytes memory code, address self) internal pure {
        bytes20 needle = bytes20(self);
        uint256 n = code.length;
        for (uint256 i = 0; i + 20 <= n; i++) {
            bytes20 window;
            assembly ("memory-safe") {
                window := mload(add(add(code, 0x20), i))
            }
            if (window == needle) {
                for (uint256 j = 0; j < 20; j++) {
                    code[i + j] = 0;
                }
                i += 19;
            }
        }
    }
}
