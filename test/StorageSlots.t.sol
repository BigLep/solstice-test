// SPDX-License-Identifier: Apache-2.0 OR MIT
pragma solidity ^0.8.36;

import {Test} from "forge-std/Test.sol";

import {GateParamsLibrary} from "../src/lib/GateParams.sol";
import {OwnersLibrary} from "../src/lib/Owners.sol";
import {PendingTaskInfo, PendingTaskLibrary} from "../src/lib/PendingTask.sol";
import {SraStorage} from "../src/lib/SraStorage.sol";

/// @dev Every namespaced storage slot constant is hardcoded in its library. These tests pin each one to the
///      ERC-7201 derivation of its namespace id, so a typo or an accidental edit fails CI. Together with
///      test/layout/StorageLayoutProbe.sol (struct layout) this is the storage-safety gate for upgrades.
contract StorageSlotsTest is Test {
    function namespaceSlot(string memory id) internal pure returns (bytes32) {
        return keccak256(abi.encode(uint256(keccak256(bytes(id))) - 1)) & ~bytes32(uint256(0xff));
    }

    function test_ownersSlot() public pure {
        OwnersLibrary.Owners storage s = OwnersLibrary.getOwnersSlot();
        bytes32 slot;
        assembly {
            slot := s.slot
        }
        assertEq(slot, namespaceSlot("Solstice.Owners"));
    }

    function test_pendingTasksSlot() public pure {
        mapping(bytes32 => PendingTaskInfo) storage s = PendingTaskLibrary.getTasksSlot();
        bytes32 slot;
        assembly {
            slot := s.slot
        }
        assertEq(slot, namespaceSlot("Solstice.PendingTasks"));
    }

    function test_gateParamsSlot() public pure {
        GateParamsLibrary.GateParamsInfo storage s = GateParamsLibrary.getGateParamsSlot();
        bytes32 slot;
        assembly {
            slot := s.slot
        }
        assertEq(slot, namespaceSlot("Solstice.GateParams"));
    }

    function test_gateCheckSlot() public pure {
        GateParamsLibrary.GateCheckBlockers storage s = GateParamsLibrary.getGateCheckSlot();
        bytes32 slot;
        assembly {
            slot := s.slot
        }
        assertEq(slot, namespaceSlot("Solstice.GateCheck"));
    }

    function test_sraRegistrySlot() public pure {
        SraStorage.SraStorageRegistry storage s = SraStorage.registry();
        bytes32 slot;
        assembly {
            slot := s.slot
        }
        assertEq(slot, namespaceSlot("Solstice.SRA.Registry"));
    }

    function test_sraQuarterSlot() public pure {
        SraStorage.SraStorageQuarter storage s = SraStorage.quarter();
        bytes32 slot;
        assembly {
            slot := s.slot
        }
        assertEq(slot, namespaceSlot("Solstice.SRA.Quarter"));
    }
}
