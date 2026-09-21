// SPDX-License-Identifier: Apache-2.0 OR MIT
pragma solidity ^0.8.36;

import {Script} from "forge-std/Script.sol";
import {console} from "forge-std/console.sol";

/// @dev Shared helper for comparing a live implementation's runtime code against a locally constructed one.
abstract contract BytecodeCheck is Script {
    /// @dev UUPSUpgradeable stores `__self = address(this)` as an immutable, so an implementation's runtime code
    ///      embeds its own address. Both copies are compared with their own address zeroed out; every other
    ///      immutable (owners, hold, orchestrator, epoch parameters, SWA's SRA pointer) must match byte for byte.
    function _checkCode(string memory label, address live, address expected) internal view {
        require(live.code.length != 0, string.concat(label, ": no code at implementation"));
        bytes memory liveCode = _maskAddress(live.code, live);
        bytes memory expectedCode = _maskAddress(expected.code, expected);
        require(liveCode.length == expectedCode.length, string.concat(label, ": runtime code length mismatch"));
        bytes32 liveHash = keccak256(liveCode);
        bytes32 expectedHash = keccak256(expectedCode);
        console.log(string.concat("[", label, "] live code hash (self masked)     "), vm.toString(liveHash));
        console.log(string.concat("[", label, "] expected code hash (self masked) "), vm.toString(expectedHash));
        require(liveHash == expectedHash, string.concat(label, ": runtime code mismatch"));
    }

    /// @dev Returns a copy of `code` with every 20-byte occurrence of `self` replaced by zeros.
    function _maskAddress(bytes memory code, address self) internal pure returns (bytes memory out) {
        out = code;
        bytes20 needle = bytes20(self);
        uint256 n = out.length;
        for (uint256 i = 0; i + 20 <= n; i++) {
            bytes20 window;
            assembly ("memory-safe") {
                window := mload(add(add(out, 0x20), i))
            }
            if (window == needle) {
                for (uint256 j = 0; j < 20; j++) {
                    out[i + j] = 0;
                }
                i += 19;
            }
        }
    }
}
