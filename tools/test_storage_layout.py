"""Unit tests for the storage layout gate's rules. Run: python3 -m unittest tools/test_storage_layout.py"""

import copy
import unittest

from storage_layout import compare_layouts, normalize


def leaf(name, slot, offset, type_, nbytes):
    return {"name": name, "slot": slot, "offset": offset, "type": type_, "bytes": nbytes}


def struct(name, slot, type_, members, nbytes):
    return {"name": name, "slot": slot, "offset": 0, "type": type_, "bytes": nbytes, "members": members}


def base_layout():
    owners = struct("owners", 0, "struct OwnersLibrary.Owners", [
        {"name": "ownerInfo", "slot": 0, "offset": 0, "type": "mapping(address => struct OwnersLibrary.OwnerInfo)", "bytes": 32,
         "value": {"type": "struct OwnersLibrary.OwnerInfo", "bytes": 32, "members": [leaf("bitId", 0, 0, "uint8", 1)]}},
        leaf("nextBitCursor", 1, 0, "uint8", 1),
        leaf("allOwners", 1, 1, "OwnerSet", 20),
    ], 64)
    gate = struct("gateParams", 2, "struct GateParamsLibrary.GateParamsInfo", [
        leaf("lastCheckedQuarter", 0, 0, "uint64", 8),
        struct("params", 1, "struct GateParams", [
            struct("target", 0, "struct VolumeTarget", [leaf("base", 0, 0, "FixedU18", 32), leaf("stepRatio", 1, 0, "FixedU18", 32)], 64),
            leaf("steps", 2, 0, "uint64", 8),
        ], 96),
    ], 128)
    registry = struct("sraRegistry", 6, "struct SraStorage.SraStorageRegistry", [
        leaf("allocatedIds", 0, 0, "uint64", 8),
        {"name": "admittedIds", "slot": 1, "offset": 0, "type": "uint64[]", "bytes": 32, "base": {"type": "uint64", "bytes": 8}},
    ], 64)
    return [owners, gate, registry]


def errors_for(new):
    errors = []
    compare_layouts(base_layout(), new, errors)
    return errors


class CompatRules(unittest.TestCase):
    def test_identical_is_safe(self):
        self.assertEqual(errors_for(base_layout()), [])

    def test_append_member_is_safe_even_when_struct_grows(self):
        new = base_layout()
        new[0]["members"].append(leaf("added", 2, 0, "uint256", 32))
        new[0]["bytes"] = 96
        self.assertEqual(errors_for(new), [])

    def test_append_to_nested_struct_that_is_last_member_is_safe(self):
        new = base_layout()
        params = new[1]["members"][1]  # GateParams is the last member of GateParamsInfo
        params["members"].append(leaf("extra", 3, 0, "uint256", 32))
        params["bytes"] = 128
        new[1]["bytes"] = 160
        self.assertEqual(errors_for(new), [])

    def test_growing_nested_struct_that_shifts_a_sibling_fails(self):
        new = base_layout()
        target = new[1]["members"][1]["members"][0]  # VolumeTarget, followed by `steps`
        target["members"].append(leaf("extra", 2, 0, "uint256", 32))
        target["bytes"] = 96
        new[1]["members"][1]["members"][1]["slot"] = 3  # steps moves: a real break
        self.assertTrue(any("steps: slot changed" in e for e in errors_for(new)))

    def test_insert_member_in_middle_fails(self):
        new = base_layout()
        new[0]["members"].insert(1, leaf("inserted", 1, 0, "uint256", 32))
        self.assertTrue(any("reordered, removed or inserted" in e for e in errors_for(new)))

    def test_reorder_members_fails(self):
        new = base_layout()
        m = new[0]["members"]
        m[1], m[2] = m[2], m[1]
        self.assertTrue(any("reordered" in e for e in errors_for(new)))

    def test_remove_member_fails(self):
        new = base_layout()
        del new[0]["members"][2]
        self.assertTrue(any("reordered, removed or inserted" in e for e in errors_for(new)))

    def test_retype_leaf_fails(self):
        new = base_layout()
        new[0]["members"][1]["type"] = "uint16"
        new[0]["members"][1]["bytes"] = 2
        self.assertTrue(any("nextBitCursor: type changed" in e for e in errors_for(new)))

    def test_udvt_width_change_with_same_label_fails(self):
        new = base_layout()
        new[0]["members"][2]["bytes"] = 32  # OwnerSet widened, label unchanged, still the last member of its slot
        self.assertTrue(any("allOwners: bytes changed 20 -> 32" in e for e in errors_for(new)))

    def test_member_slot_or_offset_change_fails(self):
        new = base_layout()
        new[0]["members"][2]["offset"] = 2
        self.assertTrue(any("allOwners: offset changed" in e for e in errors_for(new)))

    def test_mapping_value_may_grow(self):
        new = base_layout()
        value = new[0]["members"][0]["value"]
        value["members"].append(leaf("flag", 0, 1, "bool", 1))
        self.assertEqual(errors_for(new), [])

    def test_mapping_value_member_retype_fails(self):
        new = base_layout()
        new[0]["members"][0]["value"]["members"][0]["type"] = "uint16"
        new[0]["members"][0]["value"]["members"][0]["bytes"] = 2
        self.assertTrue(any("ownerInfo.value.bitId: type changed" in e for e in errors_for(new)))

    def test_array_element_width_change_fails(self):
        new = base_layout()
        new[2]["members"][1]["base"] = {"type": "uint128", "bytes": 16}
        errs = errors_for(new)
        self.assertTrue(any("admittedIds.base: type changed" in e for e in errs))
        self.assertTrue(any("admittedIds.base: bytes changed 8 -> 16" in e for e in errs))

    def test_new_namespace_anywhere_is_safe(self):
        new = base_layout()
        new.insert(0, struct("extra", 0, "struct Extra", [leaf("x", 0, 0, "uint256", 32)], 32))
        for i, e in enumerate(new):
            e["slot"] = i * 4  # probe reshuffles top-level slots; they must not matter
        self.assertEqual(errors_for(new), [])

    def test_removed_namespace_fails(self):
        new = base_layout()[1:]
        self.assertTrue(any("namespace variable owners was removed" in e for e in errors_for(new)))

    def test_top_level_type_change_fails(self):
        new = base_layout()
        new[0]["type"] = "struct Other"
        self.assertTrue(any("layout.owners: type changed" in e for e in errors_for(new)))


class Normalize(unittest.TestCase):
    def test_drops_volatile_fields_and_inlines_members(self):
        raw = {
            "storage": [{"astId": 12, "contract": "x.sol:P", "label": "owners", "offset": 0, "slot": "0", "type": "t_struct(Owners)873_storage"}],
            "types": {
                "t_struct(Owners)873_storage": {"label": "struct OwnersLibrary.Owners", "numberOfBytes": "64", "encoding": "inplace",
                    "members": [{"astId": 3, "contract": "x", "label": "allOwners", "offset": 1, "slot": "1", "type": "t_userDefinedValueType(OwnerSet)9"}]},
                "t_userDefinedValueType(OwnerSet)9": {"label": "OwnerSet", "numberOfBytes": "20", "encoding": "inplace"},
            },
        }
        self.assertEqual(normalize(raw), [
            {"name": "owners", "slot": 0, "offset": 0, "type": "struct OwnersLibrary.Owners", "bytes": 64,
             "members": [{"name": "allOwners", "slot": 1, "offset": 1, "type": "OwnerSet", "bytes": 20}]},
        ])
        self.assertNotIn("astId", str(normalize(raw)))


if __name__ == "__main__":
    unittest.main()
