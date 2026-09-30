#!/usr/bin/env python3
"""Storage layout gate for the upgradeable SRA and SWA contracts.

The contracts keep every piece of state in ERC-7201 namespaced structs reached through fixed slots, so
`forge inspect <Contract> storageLayout` is empty for them. test/layout/StorageLayoutProbe.sol declares one
state variable per namespace; this tool asks the compiler for that probe's layout and keeps a normalized copy
in storage-layout/layout.json. The slot constants themselves are pinned by test/StorageSlots.t.sol.

Upgrade-safe (--compat passes) means: every namespace keeps its ERC-7201 id string, and so its base slot; every
storage leaf present at <ref> (a non-struct field, reached through
any nesting of structs, mapping values and array elements) is still there at the same slot and offset within
its region, with the same type and byte width, and array elements keep their size. New fields may be added
anywhere that moves nothing: appended to a struct, in unused bytes of an existing slot, or as a new namespace.
Anything else would reinterpret live storage behind the proxy and needs a migration, which docs/UPGRADE.md
does not cover.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROBE = "StorageLayoutProbe"
OUT = ROOT / "storage-layout" / "layout.json"
NAMESPACE_RE = re.compile(r"@custom:storage-location\s+erc7201:(\S+)[^{]*?struct\s+([A-Za-z0-9_]+)\s*\{", re.S)


def compiler_layout():
    cmd = ["forge", "inspect", PROBE, "storageLayout", "--json"]
    result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if result.returncode != 0 and "storage layout missing from artifact" in result.stderr:
        # A cached artifact built without the storage layout; a clean build fixes it.
        subprocess.run(["forge", "clean"], cwd=ROOT, check=True, capture_output=True)
        result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        print("forge inspect failed (does the project compile?):", file=sys.stderr)
        print(result.stderr.strip()[-2000:], file=sys.stderr)
        sys.exit(1)
    return with_namespaces(normalize(json.loads(result.stdout)))


def normalize(layout):
    """Reduce the compiler's storageLayout to what an upgrade can break.

    The raw `.storageLayout` output is not kept verbatim because it carries values that change with every
    unrelated edit (`astId`, the `contract` path, type ids such as `t_struct(Owners)873_storage`), which would
    make the committed snapshot churn and bury real layout changes in noise. This keeps each variable and struct
    member's name, slot, offset, resolved type label and byte size, with struct members inlined, so a diff of the
    file reads as a diff of the layout. The raw output remains one `forge inspect` away for other tooling.

    Top-level slots are an artifact of the probe (its variables are laid out one after another); the real
    namespaces each live at their own ERC-7201 slot. They are kept for readability but never compared.
    """
    types = layout["types"]

    def describe(type_id):
        t = types[type_id]
        d = {"type": t["label"], "bytes": int(t["numberOfBytes"])}
        if "members" in t:
            d["members"] = [
                {"name": m["label"], "slot": int(m["slot"]), "offset": m["offset"], **describe(m["type"])}
                for m in t["members"]
            ]
        if "value" in t:
            d["value"] = describe(t["value"])
        if "base" in t:
            d["base"] = describe(t["base"])
        return d

    return [
        {"name": v["label"], "slot": int(v["slot"]), "offset": v["offset"], **describe(v["type"])}
        for v in layout["storage"]
    ]


def keccak(data: bytes) -> bytes:
    """keccak256 via cast, which is already required; the standard library has no keccak."""
    out = subprocess.run(["cast", "keccak", "0x" + data.hex()], capture_output=True, text=True, check=True).stdout
    return bytes.fromhex(out.strip()[2:])


def erc7201_slot(namespace_id):
    """keccak256(abi.encode(uint256(keccak256(id)) - 1)) & ~0xff, the ERC-7201 base slot for a namespace id."""
    inner = int.from_bytes(keccak(namespace_id.encode()), "big") - 1
    return "0x" + (int.from_bytes(keccak(inner.to_bytes(32, "big")), "big") & ~0xFF).to_bytes(32, "big").hex()


def namespaces():
    """{struct name: {"id": namespace id, "slot": derived base slot}} for every struct in src/ declared with an
    ERC-7201 @custom:storage-location tag. The id string decides where the namespace's data lives in the proxy;
    changing it relocates the whole namespace to an empty region, so it is recorded and compared like a leaf."""
    found = {}
    for path in sorted((ROOT / "src").rglob("*.sol")):
        for namespace_id, struct in NAMESPACE_RE.findall(path.read_text()):
            found[struct] = {"id": namespace_id, "slot": erc7201_slot(namespace_id)}
    return found


def with_namespaces(layout):
    """Attach each probe variable's namespace id and base slot; fail if a namespaced struct is not probed."""
    known = namespaces()
    probed = set()
    for e in layout:
        struct = e["type"].split(".")[-1]
        if struct in known:
            e["namespace"], e["namespaceSlot"] = known[struct]["id"], known[struct]["slot"]
            probed.add(struct)
    missing = sorted(set(known) - probed)
    if missing:
        print("namespaced structs missing from test/layout/StorageLayoutProbe.sol: " + ", ".join(missing), file=sys.stderr)
        sys.exit(1)
    return layout


def leaves(layout):
    """Flatten a normalized layout to {path: (slot, offset, type, bytes)} for every leaf (non-struct) entry.

    Slots are counted from the start of the region the leaf lives in: a namespace, a mapping value or an array
    element. Regions restart at 0 because their absolute position is either an ERC-7201 constant (pinned by
    test/StorageSlots.t.sol) or a hash. Array elements also get a `#stride` leaf carrying the element's byte
    size, since growing an element type moves every later element even though no member of it moves.
    """
    out = {}

    def walk(entry, path, base_slot):
        if "members" in entry:
            for m in entry["members"]:
                walk(m, f"{path}.{m['name']}", base_slot + m["slot"])
        else:
            out[path] = (base_slot, entry.get("offset", 0), entry["type"], entry["bytes"])
        if "value" in entry:
            walk(entry["value"], f"{path}[value]", 0)
        if "base" in entry:
            out[f"{path}[element]#stride"] = entry["base"]["bytes"]
            walk(entry["base"], f"{path}[element]", 0)

    for e in layout:
        walk(e, e["name"], 0)
    return out


def compare_layouts(base, new, errors):
    """Upgrade-safe means every namespace keeps its id (and so its base slot), and every leaf present at the base
    still exists with the same position, type and width. Anything new may appear anywhere: a new namespace, a
    member appended to a struct, or a field placed in bytes no existing field uses, since none of those moves or
    reinterprets existing storage."""
    new_by_name = {e["name"]: e for e in new}
    for b in base:
        n = new_by_name.get(b["name"])
        if n is None:
            errors.append(f"{b['name']}: namespace removed from the probe")
        elif b.get("namespace") and (b["namespace"], b["namespaceSlot"]) != (n.get("namespace"), n.get("namespaceSlot")):
            errors.append(f"{b['name']}: namespace id changed {b.get('namespace')!r} -> {n.get('namespace')!r} "
                          f"(base slot {b.get('namespaceSlot')} -> {n.get('namespaceSlot')}); the live data stays at the old slot")
    old_leaves, new_leaves = leaves(base), leaves(new)
    for path, was in old_leaves.items():
        if path not in new_leaves:
            errors.append(f"{path}: removed or renamed")
        elif new_leaves[path] != was:
            errors.append(f"{path}: changed {was} -> {new_leaves[path]}")


def main(argv):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = p.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true", help="fail if storage-layout/layout.json is stale")
    g.add_argument("--compat", metavar="GIT_REF", help="fail if the layout is not upgrade-safe against GIT_REF")
    args = p.parse_args(argv)

    if args.check:
        committed = json.loads(OUT.read_text())
        current = compiler_layout()
        if committed != current:
            print("storage-layout/layout.json is stale; run tools/storage_layout.py and commit the result", file=sys.stderr)
            return 1
        print("storage layout snapshot is up to date")
        return 0

    if args.compat:
        rel = OUT.relative_to(ROOT)
        result = subprocess.run(["git", "show", f"{args.compat}:{rel}"], cwd=ROOT, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"no snapshot at {args.compat}:{rel}; nothing to compare against")
            return 0
        current = compiler_layout()
        errors = []
        compare_layouts(json.loads(result.stdout), current, errors)
        if errors:
            print("storage layout is NOT upgrade-safe relative to base:")
            for e in errors:
                print("  -", e)
            return 1
        print("storage layout is upgrade-safe relative to base")
        return 0

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(compiler_layout(), indent=2) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
