// SPDX-License-Identifier: Apache-2.0 OR MIT
pragma solidity ^0.8.36;

import {Epoch, currentEpoch} from "./Epoch.sol";
import {FixedU18} from "./FixedU18.sol";
import {EMPTY_SET, OwnerSet} from "./OwnerSet.sol";
import {OwnersLibrary} from "./Owners.sol";
import {PendingTaskLibrary} from "./PendingTask.sol";

FixedU18 constant VOL_TARGET_ENTRY = FixedU18.wrap(3500 ether);
FixedU18 constant VOL_TARGET_RATIO = FixedU18.wrap(2.7 ether);

struct VolumeTarget {
    FixedU18 base;
    FixedU18 stepRatio;
}

struct GateParams {
    VolumeTarget target;
    uint64 steps;
}

using GateParamsLibrary for GateParams global;

library GateParamsLibrary {
    /// @dev W2_CAP is reached after (0.50 - 0.10) / 0.05 = 8 gate steps.
    uint64 internal constant GATE_STEPS = 8;

    /// @custom:storage-location erc7201:Solstice.GateCheck
    struct GateCheckBlockers {
        Epoch pendingWeightUntil;
        bytes32 pendingGateParamsTaskId;
    }

    // keccak256(abi.encode(uint256(keccak256("Solstice.GateCheck")) - 1)) & ~bytes32(uint256(0xff));
    bytes32 private constant GATE_CHECK_SLOT = 0xf841decd8ddcb41f8d697f3767c4cb55c655b2888a4f9b80db06444434da1700;

    function getGateCheckSlot() internal pure returns (GateCheckBlockers storage slot) {
        assembly ("memory-safe") {
            slot.slot := GATE_CHECK_SLOT
        }
    }

    /// @notice A SetWeightRecords write is still unsettled in f02.
    error PendingWeightWrite(Epoch until);

    /// @notice A SetGateParams task is still outstanding.
    error PendingGateParams(bytes32 taskId);

    function gateCheck() internal view {
        GateCheckBlockers storage blockers = getGateCheckSlot();
        Epoch pendingUntil = blockers.pendingWeightUntil;
        require(currentEpoch() >= pendingUntil, PendingWeightWrite(pendingUntil));

        bytes32 gpTaskId = blockers.pendingGateParamsTaskId;
        if (gpTaskId != bytes32(0)) {
            OwnerSet gpApprovals = PendingTaskLibrary.getTasksSlot()[gpTaskId].task.approvals;
            OwnerSet allOwners = OwnersLibrary.getAllOwners();
            require(gpApprovals & allOwners != allOwners, PendingGateParams(gpTaskId));
        }
    }

    function setPendingGateParams() internal returns (bytes32 taskId) {
        taskId = keccak256(msg.data);
        GateCheckBlockers storage gateParamsInfo = getGateCheckSlot();
        bytes32 existingTaskId = gateParamsInfo.pendingGateParamsTaskId;
        if (existingTaskId != taskId) {
            require(
                PendingTaskLibrary.getTasksSlot()[existingTaskId].task.approvals == EMPTY_SET,
                PendingGateParams(existingTaskId)
            );
        }
        gateParamsInfo.pendingGateParamsTaskId = taskId;
    }

    /// @custom:storage-location erc7201:Solstice.GateParams
    struct GateParamsInfo {
        uint64 lastCheckedQuarter;
        GateParams params;
    }

    // keccak256(abi.encode(uint256(keccak256("Solstice.GateParams")) - 1)) & ~bytes32(uint256(0xff));
    bytes32 private constant GATE_PARAMS_SLOT = 0xf9abab00248d945495524c8caf6be2b837274c1becd1964fb3775f62fd6e4600;

    function getGateParamsSlot() internal pure returns (GateParamsInfo storage slot) {
        assembly ("memory-safe") {
            slot.slot := GATE_PARAMS_SLOT
        }
    }

    function nextThreshold(GateParams memory params) internal pure returns (FixedU18 fpvThreshold) {
        return params.target.base * params.target.stepRatio.exp(params.steps);
    }

    function init() internal {
        GateParamsInfo storage slot = GateParamsLibrary.getGateParamsSlot();
        slot.lastCheckedQuarter = 1;
        slot.params.target.base = VOL_TARGET_ENTRY;
        slot.params.target.stepRatio = VOL_TARGET_RATIO;
    }
}
