// SPDX-License-Identifier: Apache-2.0 OR MIT
pragma solidity ^0.8.36;

import {DeploymentScript} from "./DeploymentScript.sol";

/// @dev Deploys only new implementations, for a later upgrade via the two-Safe governance flow.
///      The SWA implementation binds to the existing SRA proxy in deployments.json.
///      deployments.json is not modified: record the addresses only once the upgrade is live.
contract DeployImplementationScript is DeploymentScript {
    error NoDeployedSra(uint256 chainId);

    function run() public returns (address sraImplementation, address swaImplementation) {
        string memory key = _configKey();
        string memory json = vm.readFile(CONFIG_PATH);
        Config memory config = _loadConfig(json, key);
        address sra = _readAddress(json, key, "sra");
        require(sra != address(0), NoDeployedSra(block.chainid));

        vm.startBroadcast();

        sraImplementation = _deploySraImplementation(config);
        swaImplementation = _deploySwaImplementation(config, sra);

        vm.stopBroadcast();
    }
}
