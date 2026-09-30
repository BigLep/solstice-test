// SPDX-License-Identifier: Apache-2.0 OR MIT
pragma solidity ^0.8.36;

import {console} from "forge-std/console.sol";

import {DeploymentScript} from "./DeploymentScript.sol";

/// @dev Shared by Verify.s.sol and Rehearse.s.sol: the ERC-1967 slot, a from-source build of either
///      implementation, and the runtime-code comparison that proves a deployed implementation was built from the
///      checked-out source.
abstract contract UpgradeBase is DeploymentScript {
    /// @dev ERC1967Utils.IMPLEMENTATION_SLOT
    bytes32 internal constant IMPLEMENTATION_SLOT = 0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc;

    function _implementationOf(address proxy) internal view returns (address) {
        return address(uint160(uint256(vm.load(proxy, IMPLEMENTATION_SLOT))));
    }

    /// @dev Builds the SRA or SWA implementation from source, in the simulation only.
    function _buildImplementation(bool isSra, Config memory config, address sra) internal returns (address) {
        return isSra ? _deploySraImplementation(config) : _deploySwaImplementation(config, sra);
    }

    /// @dev UUPSUpgradeable stores `__self = address(this)` as an immutable, so an implementation's runtime code
    ///      embeds its own address. Both copies are compared with their own address zeroed out; every other
    ///      immutable (owners, hold, orchestrator, epoch parameters, SWA's SRA pointer) must match byte for byte.
    ///      A match also proves the implementation is UUPS-compatible, since the source is.
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
