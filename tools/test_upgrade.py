"""Unit tests for the pure parts of tools/upgrade.py (calldata, task id, Safe nonce and duplicate handling,
forge log extraction).

They need the tool's dependencies, so run them through uv from the tools directory, against the tool's lock:

    cd tools && uv export --script upgrade.py --frozen --no-hashes -o /tmp/req.txt \\
        && uv run --with-requirements /tmp/req.txt python -m unittest -q test_upgrade
"""

import unittest

from eth_utils import keccak

from upgrade import VETO_SELECTOR, already_queued, approval_set, epochs_to_text, next_nonce, script_logs, upgrade_calldata


class Calldata(unittest.TestCase):
    def test_known_answer(self):
        # Matches abi.encodeCall(UUPSUpgradeable.upgradeToAndCall, (impl, "")) as built in script/Rehearse.s.sol.
        cd = upgrade_calldata("0x64fff87D5679faE19201c628e6A5B0591961038e")
        self.assertEqual(
            cd.hex(),
            "4f1ef286"
            "00000000000000000000000064fff87d5679fae19201c628e6a5b0591961038e"
            "0000000000000000000000000000000000000000000000000000000000000040"
            "0000000000000000000000000000000000000000000000000000000000000000",
        )
        self.assertEqual(keccak(cd).hex(), "0d58da671ecb18ebd3d37357cd9a8d54006ca10807f90cb956fb367da596b459")

    def test_selectors(self):
        self.assertEqual(upgrade_calldata("0x" + "00" * 20)[:4].hex(), "4f1ef286")
        self.assertEqual(VETO_SELECTOR.hex(), "fb6f93f9")

    def test_checksum_insensitive(self):
        a = "0x64fff87D5679faE19201c628e6A5B0591961038e"
        self.assertEqual(upgrade_calldata(a), upgrade_calldata(a.lower()))


class NextNonce(unittest.TestCase):
    def test_nothing_queued(self):
        self.assertEqual(next_nonce(3, []), 3)

    def test_after_queued(self):
        self.assertEqual(next_nonce(8, [8, 9]), 10)

    def test_stale_queued_below_on_chain_is_ignored(self):
        # Seen on a real calibnet Safe: a stale proposal at nonce 0 while the on-chain nonce was 3.
        self.assertEqual(next_nonce(3, [0]), 3)

    def test_gap_in_queue(self):
        self.assertEqual(next_nonce(5, [5, 7]), 8)


class AlreadyQueued(unittest.TestCase):
    TO = "0x66C11A9F6dfEC3c1557958cF9f575a023EB01421"
    DATA = bytes.fromhex("4f1ef286" + "00" * 92)

    def queued(self, nonce, to=None, data=None):
        return {"nonce": nonce, "to": to or self.TO, "data": data or ("0x" + self.DATA.hex()), "safeTxHash": "0xabc"}

    def test_live_duplicate_is_found(self):
        self.assertIsNotNone(already_queued([self.queued(5)], 5, self.TO, self.DATA))

    def test_case_insensitive(self):
        t = self.queued(5, to=self.TO.lower(), data=("0x" + self.DATA.hex()).upper())
        self.assertIsNotNone(already_queued([t], 5, self.TO, self.DATA))

    def test_stale_duplicate_below_on_chain_nonce_does_not_count(self):
        self.assertIsNone(already_queued([self.queued(0)], 3, self.TO, self.DATA))

    def test_different_call_does_not_count(self):
        self.assertIsNone(already_queued([self.queued(5, data="0xdeadbeef")], 5, self.TO, self.DATA))

    def test_delegatecall_with_same_data_does_not_count(self):
        self.assertIsNone(already_queued([dict(self.queued(5), operation=1)], 5, self.TO, self.DATA))

    def test_value_carrying_call_does_not_count(self):
        self.assertIsNone(already_queued([dict(self.queued(5), value="1")], 5, self.TO, self.DATA))

    def test_service_fields_may_be_strings_or_absent(self):
        self.assertIsNotNone(already_queued([dict(self.queued(5), operation="0", value="0")], 5, self.TO, self.DATA))
        t = self.queued(5)
        t.pop("value", None)
        self.assertIsNotNone(already_queued([t], 5, self.TO, self.DATA))


class ApprovalSet(unittest.TestCase):
    def test_bits(self):
        word = (0b101 << 64) | 4110000  # owners with bit ids 1 and 3 approved, last modified at epoch 4110000
        self.assertTrue(approval_set(word, 1))
        self.assertFalse(approval_set(word, 2))
        self.assertTrue(approval_set(word, 3))
        self.assertFalse(approval_set(word, 0))  # not an owner

    def test_no_task(self):
        self.assertFalse(approval_set(0, 1))


class EpochsToText(unittest.TestCase):
    def test_units(self):
        self.assertEqual(epochs_to_text(17), "8 min")
        self.assertEqual(epochs_to_text(720), "6.0 h")
        self.assertEqual(epochs_to_text(20160), "7.0 days")


class ScriptLogs(unittest.TestCase):
    def test_extracts_logs_between_markers(self):
        out = "Compiling...\n\n== Logs ==\n  [SRA] owners match config\n  ALL CHECKS PASSED\n\n## Setting up 1 EVM.\n  ignored\n"
        self.assertEqual(script_logs(out), ["[SRA] owners match config", "ALL CHECKS PASSED"])

    def test_no_logs(self):
        self.assertEqual(script_logs("Script ran successfully.\n"), [])


if __name__ == "__main__":
    unittest.main()
