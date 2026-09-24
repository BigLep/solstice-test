// SPDX-License-Identifier: Apache-2.0 OR MIT
pragma solidity ^0.8.36;

import {GateParamsLibrary} from "../../src/lib/GateParams.sol";
import {OwnersLibrary} from "../../src/lib/Owners.sol";
import {PendingTaskLibrary} from "../../src/lib/PendingTask.sol";
import {SraStorage} from "../../src/lib/SraStorage.sol";

/// @dev Compile-only probe so the compiler reports the layout of every ERC-7201 namespaced struct the SRA and
///      SWA keep behind their proxies. `forge inspect` sees only state variables, and the real contracts have
///      none (each namespace is reached through a fixed slot), so this contract declares one variable per
///      namespace. tools/storage_layout.py snapshots its layout and fails CI on non-append-only changes.
///      Never deployed. Add a variable here whenever a new namespaced struct is introduced.
contract StorageLayoutProbe {
    OwnersLibrary.Owners internal owners;
    PendingTaskLibrary.PendingTasks internal pendingTasks;
    GateParamsLibrary.GateParamsInfo internal gateParams;
    GateParamsLibrary.GateCheckBlockers internal gateCheck;
    SraStorage.SraStorageRegistry internal sraRegistry;
    SraStorage.SraStorageQuarter internal sraQuarter;
}
