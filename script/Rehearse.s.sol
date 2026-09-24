// SPDX-License-Identifier: Apache-2.0 OR MIT
pragma solidity ^0.8.36;

import {console} from "forge-std/console.sol";

import {UUPSUpgradeable} from "@openzeppelin/contracts/proxy/utils/UUPSUpgradeable.sol";

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
    struct Plan {
        bool isSra;
        address proxy;
        address owner1;
        address owner2;
        uint64 hold;
        address impl;
        bytes upgradeCall;
    }

    function run() public override returns (address sra, address swa) {
        string memory key = _configKey();
        string memory json = vm.readFile(CONFIG_PATH);
        Config memory config = _loadConfig(json, key);
        sra = _readAddress(json, key, "sra");
        swa = _readAddress(json, key, "swa");

        Plan memory plan = _plan(config, sra, swa);
        _governanceFlow(plan);

        console.log("");
        console.log("running VerifyScript checks on the upgraded fork");
        _verifySra(config, sra);
        _verifySwa(config, sra, swa);
        console.log("");
        console.log("REHEARSAL COMPLETE");
    }

    function _plan(Config memory config, address sra, address swa) internal returns (Plan memory plan) {
        plan.isSra = keccak256(bytes(vm.envString("TARGET"))) == keccak256("sra");
        plan.proxy = plan.isSra ? sra : swa;
        plan.owner1 = plan.isSra ? config.sraOwner1 : config.swaOwner1;
        plan.owner2 = plan.isSra ? config.sraOwner2 : config.swaOwner2;
        plan.hold = Epoch.unwrap(config.hold);

        plan.impl = vm.envOr("NEW_IMPLEMENTATION", address(0));
        address expected = plan.isSra ? _deploySraImplementation(config) : _deploySwaImplementation(config, sra);
        if (plan.impl == address(0)) {
            plan.impl = expected;
            console.log("built implementation in the fork", plan.impl);
        } else {
            _checkCode("rehearsal implementation", plan.impl, expected);
        }

        bytes memory data = vm.envOr("UPGRADE_CALLDATA", bytes(""));
        plan.upgradeCall = abi.encodeCall(UUPSUpgradeable.upgradeToAndCall, (plan.impl, data));
        console.log("task id", vm.toString(keccak256(plan.upgradeCall)));
    }

    function _governanceFlow(Plan memory plan) internal {
        vm.prank(plan.owner1);
        _call(plan.proxy, plan.upgradeCall, "owner 1 submit");
        vm.prank(plan.owner2);
        _call(plan.proxy, plan.upgradeCall, "owner 2 approve");

        (bool ok, bytes memory ret) = plan.proxy.call(plan.upgradeCall);
        require(
            !ok && bytes4(ret) == UnanimousGovernance.HoldUntil.selector,
            "early execution did not revert with HoldUntil"
        );
        console.log("early execution reverted with HoldUntil, as required");

        vm.roll(block.number + plan.hold);
        _call(plan.proxy, plan.upgradeCall, "execute after hold");
        require(_implementationOf(plan.proxy) == plan.impl, "implementation slot did not change");
        console.log("implementation slot now", plan.impl);
    }

    function _call(address target, bytes memory callData, string memory label) internal {
        (bool ok, bytes memory ret) = target.call(callData);
        require(ok, string.concat(label, " failed: ", vm.toString(ret)));
        console.log(string.concat(label, ": ok"));
    }
}
