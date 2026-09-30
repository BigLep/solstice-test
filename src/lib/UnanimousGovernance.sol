// SPDX-License-Identifier: Apache-2.0 OR MIT
pragma solidity ^0.8.36;

import {Epoch, currentEpoch} from "./Epoch.sol";
import {EMPTY_SET, OwnerSet} from "./OwnerSet.sol";
import {PendingTask, PendingTaskInfo, PendingTaskLibrary} from "./PendingTask.sol";
import {OwnersLibrary} from "./Owners.sol";

contract UnanimousGovernance {
    using OwnersLibrary for address;

    Epoch constant NO_HOLD = Epoch.wrap(0);
    Epoch constant UNSUBMITTED = Epoch.wrap(0);

    event Submitted(bytes32 indexed taskId);
    event Approved(bytes32 indexed taskId, address indexed owner);
    event Rejected(bytes32 indexed taskId, address indexed owner);

    error HoldUntil(Epoch until);
    error AlreadyApproved();
    error TaskNotFound(bytes32 taskId);
    error NoOwners();

    modifier anyOwner() {
        require(msg.sender.isOwner(), OwnersLibrary.NotOwner(msg.sender));
        _;
    }

    /// @notice Executes the wrapped function once every current owner has approved `taskId`.
    /// @dev If `hold` is zero, execution happens on the approval that reaches unanimity.
    /// @dev Otherwise, once unanimous, execution becomes permissionless after `hold` epochs elapse.
    /// @param taskId The identifier of the task being approved, usually keccak256(msg.data)
    /// @param hold The number of epochs to wait after unanimity before execution becomes permissionless
    modifier unanimous(bytes32 taskId, Epoch hold) {
        // load
        PendingTaskInfo storage taskInfo = PendingTaskLibrary.getTasksSlot()[taskId];
        PendingTask memory loaded = taskInfo.task;
        OwnerSet allOwners = OwnersLibrary.getAllOwners();

        require(allOwners != EMPTY_SET, NoOwners());

        // modify
        if (loaded.approvals & allOwners == allOwners) {
            // already approved: permissionless completion
            Epoch until = loaded.modified + hold;
            require(currentEpoch() >= until, HoldUntil(until));
            // execute
            delete taskInfo.task;
            _;
        } else {
            // approve
            require(msg.sender.isOwner(), OwnersLibrary.NotOwner(msg.sender));
            OwnerSet ownerBit = msg.sender.asOwnerSet();
            if (loaded.modified == UNSUBMITTED) {
                emit Submitted(taskId);
            } else {
                require(loaded.approvals & ownerBit == EMPTY_SET, AlreadyApproved());
            }
            loaded.modified = currentEpoch();
            loaded.approvals = loaded.approvals | ownerBit;

            // store result
            emit Approved(taskId, msg.sender);
            if (hold == NO_HOLD && loaded.approvals & allOwners == allOwners) {
                delete taskInfo.task;
                // execute now
                _;
            } else {
                // wait
                taskInfo.task = loaded;
                assembly ("memory-safe") {
                    // exit successfully returning no data
                    // works even for internal functions
                    stop()
                }
            }
        }
    }

    /// @notice Executes the wrapped function once every current owner has approved `taskId`.
    /// @dev Equivalent to `unanimous(taskId, NO_HOLD)`: no permissionless completion path.
    /// @param taskId Identifier of the task being approved, usually keccak256(msg.data)
    modifier unanimousNoHold(bytes32 taskId) {
        PendingTaskInfo storage taskInfo = PendingTaskLibrary.getTasksSlot()[taskId];
        PendingTask memory loaded = taskInfo.task;
        OwnerSet allOwners = OwnersLibrary.getAllOwners();

        // approve
        require(msg.sender.isOwner(), OwnersLibrary.NotOwner(msg.sender));
        OwnerSet ownerBit = msg.sender.asOwnerSet();
        if (loaded.modified == UNSUBMITTED) {
            emit Submitted(taskId);
        } else {
            require(loaded.approvals & ownerBit == EMPTY_SET, AlreadyApproved());
        }
        loaded.modified = currentEpoch();
        loaded.approvals = loaded.approvals | ownerBit;

        // store result
        emit Approved(taskId, msg.sender);
        if (loaded.approvals & allOwners == allOwners) {
            delete taskInfo.task;
            // execute now
            _;
        } else {
            // wait
            taskInfo.task = loaded;
            assembly ("memory-safe") {
                // exit successfully returning no data
                // works even for internal functions
                stop()
            }
        }
    }

    /// @param taskId The identifier of the pending task to reject
    function _veto(bytes32 taskId) internal anyOwner {
        // load
        PendingTaskInfo storage taskInfo = PendingTaskLibrary.getTasksSlot()[taskId];

        // modify
        if (taskInfo.task.modified == UNSUBMITTED) revert TaskNotFound(taskId);
        delete taskInfo.task;

        emit Rejected(taskId, msg.sender);
    }
}
