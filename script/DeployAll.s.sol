// SPDX-License-Identifier: Apache-2.0 OR MIT
pragma solidity ^0.8.36;

import {VmSafe} from "forge-std/Vm.sol";

import {DeploymentScript} from "./DeploymentScript.sol";

/// @dev Deploys both actors, each behind a freshly initialized proxy, and records the proxies in deployments.json.
contract DeployAllScript is DeploymentScript {
    function _writeDeployedAddresses(string memory key, address sra, address swa) internal {
        vm.writeJson(vm.toString(sra), CONFIG_PATH, string.concat(key, ".sra"));
        vm.writeJson(vm.toString(swa), CONFIG_PATH, string.concat(key, ".swa"));
    }

    function run() public returns (address sra, address swa) {
        string memory key = _configKey();
        Config memory config = _loadConfig(vm.readFile(CONFIG_PATH), key);

        vm.startBroadcast();

        address sraImplementation = _deploySraImplementation(config);
        sra = initializeProxy(sraImplementation);

        address swaImplementation = _deploySwaImplementation(config, sra);
        swa = initializeProxy(swaImplementation);

        vm.stopBroadcast();

        if (vm.isContext(VmSafe.ForgeContext.ScriptBroadcast)) {
            _writeDeployedAddresses(key, sra, swa);
        }
    }
}
