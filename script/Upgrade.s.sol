// SPDX-License-Identifier: Apache-2.0 OR MIT
pragma solidity ^0.8.36;

import {console} from "forge-std/console.sol";

import {IERC1822Proxiable} from "@openzeppelin/contracts/interfaces/draft-IERC1822.sol";

import {UpgradeBase} from "./UpgradeBase.sol";

/// @notice Checks that a deployed implementation was built from the checked-out source and can be upgraded to.
/// @dev Used by tools/upgrade.py before it builds the upgrade calldata; can also be run by hand:
///
///        TARGET=sra NEW_IMPLEMENTATION=0x... forge script script/Upgrade.s.sol --rpc-url $ETH_RPC_URL
///
///      Sends nothing. Rebuilds the implementation locally from source and `deployments.json`, requires the
///      on-chain runtime code to match, requires it to be UUPS-compatible and different from the implementation
///      the proxy currently points at. Reverts naming the failed check; prints `IMPLEMENTATION OK` otherwise.
contract UpgradeScript is UpgradeBase {
    function run() public {
        string memory key = _configKey();
        string memory json = vm.readFile(CONFIG_PATH);
        Config memory config = _loadConfig(json, key);
        address sra = _readAddress(json, key, "sra");
        address swa = _readAddress(json, key, "swa");
        require(sra != address(0) && swa != address(0), "deployments.json has no sra/swa address for this chain");

        Target memory t = _resolveTarget(config, sra, swa);
        require(t.proxy.code.length != 0, "proxy has no code on this chain");
        address current = _implementationOf(t.proxy);
        require(current.code.length != 0, "proxy implementation slot is empty");

        address newImplementation = vm.envAddress("NEW_IMPLEMENTATION");
        require(newImplementation.code.length != 0, "new implementation has no code");
        string memory label = t.isSra ? "SRA new implementation" : "SWA new implementation";
        _checkCode(label, newImplementation, _buildImplementation(t, config, sra));
        require(newImplementation != current, "new implementation equals current implementation");
        require(
            IERC1822Proxiable(newImplementation).proxiableUUID() == IMPLEMENTATION_SLOT,
            "new implementation is not UUPS (proxiableUUID mismatch)"
        );

        console.log(string.concat("[", label, "] IMPLEMENTATION OK: built from this source; current is"), current);
    }
}
