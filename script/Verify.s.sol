// SPDX-License-Identifier: Apache-2.0 OR MIT
pragma solidity ^0.8.36;

import {console} from "forge-std/console.sol";

import {IERC1822Proxiable} from "@openzeppelin/contracts/interfaces/draft-IERC1822.sol";
import {ERC1967Proxy} from "@openzeppelin/contracts/proxy/ERC1967/ERC1967Proxy.sol";

import {ServiceRewardsActor} from "../src/ServiceRewardsActor.sol";
import {Epoch} from "../src/lib/Epoch.sol";
import {UnanimousProxied} from "../src/lib/UnanimousProxied.sol";
import {UpgradeBase} from "./UpgradeBase.sol";

/// @notice Read-only verification of the SRA and SWA proxies recorded in `deployments.json`, valid both right
///         after deployment and after any number of upgrades.
/// @dev Run against a live chain with no `--broadcast`:
///
///        forge script script/Verify.s.sol --rpc-url $ETH_RPC_URL
///
///      The script rebuilds both implementations and both proxies locally from the same source, compiler
///      settings and `deployments.json` config, then compares the resulting runtime code against the live
///      contracts. Because immutables (owners, hold, orchestrator, epoch parameters, SWA's SRA pointer) are
///      baked into runtime code, a matching code hash proves every constructor argument. It then checks the
///      ERC-1967 slot, that the proxy is initialized, that the owner set is exactly the two configured owners,
///      and that the namespaced state each `initialize()` seeds is present (at least one admitted orchestrator,
///      gate parameters set). It does not assume deployment-time values for state that legitimately changes.
///      Any failure reverts with a message naming the check.
contract VerifyScript is UpgradeBase {
    /// @dev OpenZeppelin Initializable ERC-7201 slot: uint64 _initialized | bool _initializing (byte 8)
    bytes32 internal constant INITIALIZABLE_STORAGE =
        0xf0c57e16840df040f15088dc2f81fe391c3923bec73e23a9662efc9c229c6a00;
    /// @dev OwnersLibrary.OWNERS_SLOT (erc7201:Solstice.Owners)
    bytes32 internal constant OWNERS_SLOT = 0x7d2e7f914625694dd929b468ac404d7943373f4d24421c78ac93b57cc8efb500;
    /// @dev GateParamsLibrary.GATE_PARAMS_SLOT (erc7201:Solstice.GateParams)
    bytes32 internal constant GATE_PARAMS_SLOT = 0xf9abab00248d945495524c8caf6be2b837274c1becd1964fb3775f62fd6e4600;

    function run() public virtual returns (address sra, address swa) {
        string memory key = _configKey();
        string memory json = vm.readFile(CONFIG_PATH);
        Config memory config = _loadConfig(json, key);
        sra = _readAddress(json, key, "sra");
        swa = _readAddress(json, key, "swa");

        require(sra != address(0) && swa != address(0), "deployments.json has no sra/swa address for this chain");
        require(sra.code.length != 0, "sra proxy has no code");
        require(swa.code.length != 0, "swa proxy has no code");

        console.log("chain id      ", block.chainid);
        console.log("sra proxy     ", sra);
        console.log("swa proxy     ", swa);

        _verifySra(config, sra);
        _verifySwa(config, sra, swa);

        console.log("");
        console.log("ALL CHECKS PASSED");
    }

    function _verifySra(Config memory config, address proxy) internal {
        address implementation = _implementationOf(proxy);
        console.log("");
        console.log("[SRA] implementation", implementation);

        address expected = _deploySraImplementation(config);
        _checkCode("SRA implementation", implementation, expected);
        _checkProxy("SRA", proxy, expected);
        _checkImplementationIsUups("SRA", implementation);
        _checkInitialized("SRA", proxy);
        _checkOwners("SRA", proxy, config.sraOwner1, config.sraOwner2);

        ServiceRewardsActor actor = ServiceRewardsActor(proxy);
        require(actor.admittedCount() >= 1, "SRA: no admitted orchestrator");
        require(
            Epoch.unwrap(actor.EPOCHS_PER_QUARTER()) == Epoch.unwrap(config.epochsPerQuarter),
            "SRA: EPOCHS_PER_QUARTER mismatch"
        );
        require(Epoch.unwrap(actor.SRA_UPGRADE_HOLD()) == Epoch.unwrap(config.hold), "SRA: SRA_UPGRADE_HOLD mismatch");
        console.log("[SRA] orchestrator registry seeded, epoch params match");
    }

    function _verifySwa(Config memory config, address sraProxy, address proxy) internal {
        address implementation = _implementationOf(proxy);
        console.log("");
        console.log("[SWA] implementation", implementation);

        // The SRA pointer is an immutable, so a matching code hash proves SWA points at the live SRA proxy.
        address expected = _deploySwaImplementation(config, sraProxy);
        _checkCode("SWA implementation", implementation, expected);
        _checkProxy("SWA", proxy, expected);
        _checkImplementationIsUups("SWA", implementation);
        _checkInitialized("SWA", proxy);
        _checkOwners("SWA", proxy, config.swaOwner1, config.swaOwner2);

        // GateParamsLibrary.init() seeds lastCheckedQuarter (word 0) and params.target.base (word 1); both
        // legitimately change later (quarterly checks, setGateParams), so only require them to be set.
        uint256 lastCheckedQuarter = uint64(uint256(vm.load(proxy, GATE_PARAMS_SLOT)));
        uint256 base = uint256(vm.load(proxy, bytes32(uint256(GATE_PARAMS_SLOT) + 1)));
        require(lastCheckedQuarter >= 1, "SWA: gate params not initialized (lastCheckedQuarter == 0)");
        require(base != 0, "SWA: gate params not initialized (base == 0)");
        console.log("[SWA] gate params present");
    }

    // ------------------------------------------------------------------------
    // Checks
    // ------------------------------------------------------------------------

    /// @dev Compares the proxy's runtime code to a locally constructed ERC1967Proxy. The proxy has no
    ///      immutables, so this proves it is an unmodified OpenZeppelin ERC1967Proxy built with our settings.
    function _checkProxy(string memory label, address proxy, address expectedImplementation) internal {
        address expectedProxy =
            address(new ERC1967Proxy(expectedImplementation, abi.encodeCall(UnanimousProxied.initialize, ())));
        require(keccak256(proxy.code) == keccak256(expectedProxy.code), string.concat(label, ": proxy code mismatch"));
        console.log(string.concat("[", label, "] proxy code matches ERC1967Proxy"));
    }

    function _checkImplementationIsUups(string memory label, address implementation) internal view {
        require(
            IERC1822Proxiable(implementation).proxiableUUID() == IMPLEMENTATION_SLOT,
            string.concat(label, ": proxiableUUID mismatch")
        );
    }

    /// @dev Initialized at version 1 by deployment; a later reinitializer(n) upgrade raises it to n.
    function _checkInitialized(string memory label, address proxy) internal view {
        uint256 word = uint256(vm.load(proxy, INITIALIZABLE_STORAGE));
        uint64 initialized = uint64(word);
        bool initializing = uint8(word >> 64) != 0;
        console.log(string.concat("[", label, "] initialized version"), initialized);
        require(initialized >= 1, string.concat(label, ": not initialized"));
        require(!initializing, string.concat(label, ": still initializing"));
    }

    /// @dev Owners struct: word 0 is the ownerInfo mapping base, word 1 packs nextBitCursor (uint8, byte 0)
    ///      and allOwners (uint160, bytes 1..20).
    function _checkOwners(string memory label, address proxy, address owner1, address owner2) internal view {
        require(owner1 != owner2, string.concat(label, ": owner1 == owner2"));
        require(_ownerBit(proxy, owner1) != 0, string.concat(label, ": owner1 not an owner"));
        require(_ownerBit(proxy, owner2) != 0, string.concat(label, ": owner2 not an owner"));
        uint256 word1 = uint256(vm.load(proxy, bytes32(uint256(OWNERS_SLOT) + 1)));
        uint160 allOwners = uint160(word1 >> 8);
        require(_popcount(allOwners) == 2, string.concat(label, ": owner set is not exactly two owners"));
        console.log(string.concat("[", label, "] owners match config"));
    }

    function _ownerBit(address proxy, address owner) internal view returns (uint8) {
        bytes32 slot = keccak256(abi.encode(owner, OWNERS_SLOT));
        return uint8(uint256(vm.load(proxy, slot)));
    }

    function _popcount(uint160 x) internal pure returns (uint256 n) {
        while (x != 0) {
            x &= x - 1;
            n++;
        }
    }
}
