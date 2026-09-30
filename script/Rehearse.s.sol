// SPDX-License-Identifier: Apache-2.0 OR MIT
pragma solidity ^0.8.36;

import {console} from "forge-std/console.sol";

import {Epoch} from "../src/lib/Epoch.sol";
import {UnanimousGovernance} from "../src/lib/UnanimousGovernance.sol";
import {VerifyScript} from "./Verify.s.sol";

/// @notice Rehearses the full SRA and SWA upgrade in a local fork of the target network. Sends nothing.
/// @dev Usage:
///
///        forge script script/Rehearse.s.sol --rpc-url $ETH_RPC_URL
///        NEW_IMPLEMENTATION_SRA=0x... NEW_IMPLEMENTATION_SWA=0x... forge script script/Rehearse.s.sol --rpc-url ...
///
///      Both contracts are upgraded in the same fork, because the verifier rebuilds both from source and shared
///      code changes both bytecodes. For each contract: the implementation is built from source in the fork
///      (or, when given, the deployed address is checked against that build), both owner Safes are impersonated
///      to submit and approve, early execution is shown to revert with HoldUntil, the hold is rolled past, and
///      the upgrade executes. Then every VerifyScript check runs on the result.
contract RehearseScript is VerifyScript {
    function run() public override returns (address sra, address swa) {
        string memory key = _configKey();
        string memory json = vm.readFile(CONFIG_PATH);
        Config memory config = _loadConfig(json, key);
        sra = _readAddress(json, key, "sra");
        swa = _readAddress(json, key, "swa");

        _rehearse(_target(true, config, sra, swa), "NEW_IMPLEMENTATION_SRA", config, sra);
        _rehearse(_target(false, config, sra, swa), "NEW_IMPLEMENTATION_SWA", config, sra);

        console.log("");
        console.log("running VerifyScript checks on the upgraded fork");
        _verifySra(config, sra);
        _verifySwa(config, sra, swa);
        console.log("");
        console.log("REHEARSAL COMPLETE");
    }

    function _rehearse(Target memory t, string memory implVar, Config memory config, address sra) internal {
        string memory name = t.isSra ? "SRA" : "SWA";
        address expected = _buildImplementation(t, config, sra);
        address impl = vm.envOr(implVar, address(0));
        if (impl == address(0)) {
            impl = expected;
            console.log(string.concat("[", name, "] built implementation in the fork"), impl);
        } else {
            _checkCode(string.concat(name, " rehearsal implementation"), impl, expected);
        }
        bytes memory upgradeCall = _upgradeCall(impl);
        console.log(string.concat("[", name, "] task id"), vm.toString(keccak256(upgradeCall)));

        vm.prank(t.owner1);
        _call(t.proxy, upgradeCall, string.concat("[", name, "] owner 1 submit"));
        vm.prank(t.owner2);
        _call(t.proxy, upgradeCall, string.concat("[", name, "] owner 2 approve"));

        (bool ok, bytes memory ret) = t.proxy.call(upgradeCall);
        require(
            !ok && bytes4(ret) == UnanimousGovernance.HoldUntil.selector,
            string.concat(name, ": early execution did not revert with HoldUntil")
        );
        console.log(string.concat("[", name, "] early execution reverted with HoldUntil, as required"));

        vm.roll(block.number + Epoch.unwrap(t.hold));
        _call(t.proxy, upgradeCall, string.concat("[", name, "] execute after hold"));
        require(_implementationOf(t.proxy) == impl, string.concat(name, ": implementation slot did not change"));
        console.log(string.concat("[", name, "] implementation slot now"), impl);
    }

    function _call(address target, bytes memory callData, string memory label) internal {
        (bool ok, bytes memory ret) = target.call(callData);
        require(ok, string.concat(label, " failed: ", vm.toString(ret)));
        console.log(string.concat(label, ": ok"));
    }
}
