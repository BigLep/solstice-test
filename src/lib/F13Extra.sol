// SPDX-License-Identifier: Apache-2.0 OR MIT
pragma solidity ^0.8.36;

/// F13(g) test: a new ERC-7201 namespace with no StorageLayoutProbe variable.
library F13Extra {
    /// @custom:storage-location erc7201:Solstice.F13Extra
    struct F13ExtraStorage {
        uint256 value;
    }
}
