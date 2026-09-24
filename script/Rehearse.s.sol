// SPDX-License-Identifier: Apache-2.0 OR MIT
pragma solidity ^0.8.36;

import {console} from "forge-std/console.sol";

import {Epoch} from "../src/lib/Epoch.sol";
import {UnanimousGovernance} from "../src/lib/UnanimousGovernance.sol";
import {VerifyScript} from "./Verify.s.sol";

/// @notice Rehearses a full SRA or SWA upgrade in a local fork of the target network. Sends nothing.
/// @dev Usage:
///
///        TARGET=sra forge script script/Rehearse.s.sol --rpc-url $ETH_RPC_URL
///        TARGET=swa NEW_IMPLEMENTATION=0x... forge script script/Rehearse.s.sol --rpc-url $ETH_RPC_URL
///
///      Without NEW_IMPLEMENTATION the implementation is built from the checked-out source inside the fork.
///      The script then impersonates both owner Safes to submit and approve, proves that executing early
///      reverts with HoldUntil, rolls past the hold, executes, and runs every VerifyScript check on the
///      result. Optional UPGRADE_CALLDATA is passed as the `data` argument.
contract RehearseScript is VerifyScript {
    function run() public override returns (address sra, address swa) {
        string memory key = _configKey();
        string memory json = vm.readFile(CONFIG_PATH);
        Config memory config = _loadConfig(json, key);
        sra = _readAddress(json, key, "sra");
        swa = _readAddress(json, key, "swa");

        Target memory t = _resolveTarget(config, sra, swa);
        address expected = _buildImplementation(t, config, sra);
        address impl = vm.envOr("NEW_IMPLEMENTATION", address(0));
        if (impl == address(0)) {
            impl = expected;
            console.log("built implementation in the fork", impl);
        } else {
            _checkCode("rehearsal implementation", impl, expected);
        }
        bytes memory upgradeCall = _upgradeCall(impl);
        console.log("task id", vm.toString(keccak256(upgradeCall)));

        _governanceFlow(t, impl, upgradeCall);

        console.log("");
        console.log("running VerifyScript checks on the upgraded fork");
        _verifySra(config, sra);
        _verifySwa(config, sra, swa);
        console.log("");
        console.log("REHEARSAL COMPLETE");
    }

    function _governanceFlow(Target memory t, address impl, bytes memory upgradeCall) internal {
        vm.prank(t.owner1);
        _call(t.proxy, upgradeCall, "owner 1 submit");
        vm.prank(t.owner2);
        _call(t.proxy, upgradeCall, "owner 2 approve");

        (bool ok, bytes memory ret) = t.proxy.call(upgradeCall);
        require(
            !ok && bytes4(ret) == UnanimousGovernance.HoldUntil.selector,
            "early execution did not revert with HoldUntil"
        );
        console.log("early execution reverted with HoldUntil, as required");

        vm.roll(block.number + Epoch.unwrap(t.hold));
        _call(t.proxy, upgradeCall, "execute after hold");
        require(_implementationOf(t.proxy) == impl, "implementation slot did not change");
        console.log("implementation slot now", impl);
    }

    function _call(address target, bytes memory callData, string memory label) internal {
        (bool ok, bytes memory ret) = target.call(callData);
        require(ok, string.concat(label, " failed: ", vm.toString(ret)));
        console.log(string.concat(label, ": ok"));
    }
}
