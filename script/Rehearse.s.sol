// SPDX-License-Identifier: Apache-2.0 OR MIT
pragma solidity ^0.8.36;

import {console} from "forge-std/console.sol";

import {UUPSUpgradeable} from "@openzeppelin/contracts/proxy/utils/UUPSUpgradeable.sol";

import {Epoch} from "../src/lib/Epoch.sol";
import {UnanimousGovernance} from "../src/lib/UnanimousGovernance.sol";
import {UpgradeBase} from "./UpgradeBase.sol";

/// @notice Rehearses the SRA and SWA upgrade in a local fork of the target network. Sends nothing.
/// @dev Usage:
///
///        forge script script/Rehearse.s.sol --rpc-url $ETH_RPC_URL
///
///      Both implementations are built from the checked-out source inside the fork (the rehearsal runs before any
///      implementation is deployed). For each contract, both owner Safes are impersonated to submit and approve,
///      early execution is shown to revert with HoldUntil, the hold is rolled past, and the upgrade executes; the
///      proxy's implementation slot is then required to point at the new implementation.
contract RehearseScript is UpgradeBase {
    function run() public returns (address sra, address swa) {
        string memory key = _configKey();
        string memory json = vm.readFile(CONFIG_PATH);
        Config memory config = _loadConfig(json, key);
        sra = _readAddress(json, key, "sra");
        swa = _readAddress(json, key, "swa");

        _rehearse("SRA", sra, config.sraOwner1, config.sraOwner2, config.hold, _buildImplementation(true, config, sra));
        _rehearse("SWA", swa, config.swaOwner1, config.swaOwner2, config.hold, _buildImplementation(false, config, sra));

        console.log("");
        console.log("REHEARSAL COMPLETE");
    }

    function _rehearse(string memory name, address proxy, address owner1, address owner2, Epoch hold, address impl)
        internal
    {
        console.log(string.concat("[", name, "] built implementation in the fork"), impl);
        bytes memory upgradeCall = abi.encodeCall(UUPSUpgradeable.upgradeToAndCall, (impl, ""));
        console.log(string.concat("[", name, "] task id"), vm.toString(keccak256(upgradeCall)));

        vm.prank(owner1);
        _call(proxy, upgradeCall, string.concat("[", name, "] owner 1 submit"));
        vm.prank(owner2);
        _call(proxy, upgradeCall, string.concat("[", name, "] owner 2 approve"));

        (bool ok, bytes memory ret) = proxy.call(upgradeCall);
        require(
            !ok && bytes4(ret) == UnanimousGovernance.HoldUntil.selector,
            string.concat(name, ": early execution did not revert with HoldUntil")
        );
        console.log(string.concat("[", name, "] early execution reverted with HoldUntil, as required"));

        vm.roll(block.number + Epoch.unwrap(hold));
        _call(proxy, upgradeCall, string.concat("[", name, "] execute after hold"));
        require(_implementationOf(proxy) == impl, string.concat(name, ": implementation slot did not change"));
        console.log(string.concat("[", name, "] implementation slot now"), impl);
    }

    function _call(address target, bytes memory callData, string memory label) internal {
        (bool ok, bytes memory ret) = target.call(callData);
        require(ok, string.concat(label, " failed: ", vm.toString(ret)));
        console.log(string.concat(label, ": ok"));
    }
}
