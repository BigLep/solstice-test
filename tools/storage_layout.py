#!/usr/bin/env python3
"""Storage layout gate for the upgradeable SRA and SWA contracts.

The contracts keep every piece of state in ERC-7201 namespaced structs reached through fixed slots, so
`forge inspect <Contract> storageLayout` is empty for them. test/layout/StorageLayoutProbe.sol declares one
state variable per namespace; this tool asks the compiler for that probe's layout and keeps a normalized copy
in storage-layout/layout.json. The slot constants themselves are pinned by test/StorageSlots.t.sol.

Upgrade-safe (--compat passes) means: every namespace present at <ref> is still there with the same type; every
struct member present at <ref> is still there, in the same order, at the same slot and offset within its struct,
with the same type; every non-struct type keeps its byte width; and anything new is appended (a new member after
the existing ones, or a new namespace). Anything else would reinterpret live storage behind the proxy and needs
a migration, which docs/UPGRADE.md does not cover.
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
NAMESPACE_RE = re.compile(r"@custom:storage-location\s+erc7201:\S+[^{]*?struct\s+([A-Za-z0-9_]+)\s*\{", re.S)


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
    return normalize(json.loads(result.stdout))


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


def namespaced_structs():
    """Names of every struct in src/ declared with an ERC-7201 @custom:storage-location tag."""
    names = set()
    for path in (ROOT / "src").rglob("*.sol"):
        names.update(NAMESPACE_RE.findall(path.read_text()))
    return names


def check_probe_covers_namespaces(layout):
    """Fail if a namespaced struct has no variable in StorageLayoutProbe (its layout would go unchecked)."""
    probed = {e["type"].split(".")[-1] for e in layout}
    missing = sorted(namespaced_structs() - probed)
    if missing:
        print("namespaced structs missing from test/layout/StorageLayoutProbe.sol: " + ", ".join(missing), file=sys.stderr)
        sys.exit(1)


def compare_entry(b, n, here, errors, position):
    """One base entry against its counterpart: type always; slot and offset for struct members (`position`);
    byte width for everything except structs, which may legitimately grow by appending members."""
    keys = ["type"] + (["slot", "offset"] if position else []) + ([] if "members" in b else ["bytes"])
    for key in keys:
        if b.get(key) != n.get(key):
            errors.append(f"{here}: {key} changed {b.get(key)!r} -> {n.get(key)!r}")
    if "members" in b:
        if "members" not in n:
            errors.append(f"{here}: lost members")
        else:
            compare_members(b["members"], n["members"], here, errors)
    for key in ("value", "base"):  # mapping value, array element: not positioned, but width still matters
        if key in b:
            if key not in n:
                errors.append(f"{here}: lost {key}")
            else:
                compare_entry(b[key], n[key], f"{here}.{key}", errors, position=False)


def compare_members(base, new, path, errors):
    """Struct members: same names in the same order (new ones only at the end), each at its old position."""
    base_names = [e["name"] for e in base]
    new_names = [e["name"] for e in new]
    if new_names[: len(base_names)] != base_names:
        errors.append(f"{path}: members reordered, removed or inserted: {base_names} -> {new_names}")
        return
    new_by = {e["name"]: e for e in new}
    for b in base:
        compare_entry(b, new_by[b["name"]], f"{path}.{b['name']}", errors, position=True)


def compare_layouts(base, new, errors):
    """Top level: the set of namespaces. Order and slot carry no meaning (each namespace has its own ERC-7201
    slot), so a namespace may be added anywhere; removing one is an error."""
    new_by = {e["name"]: e for e in new}
    for b in base:
        if b["name"] not in new_by:
            errors.append(f"layout: namespace variable {b['name']} was removed from the probe")
            continue
        compare_entry(b, new_by[b["name"]], f"layout.{b['name']}", errors, position=False)


def main(argv):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = p.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true", help="fail if storage-layout/layout.json is stale")
    g.add_argument("--compat", metavar="GIT_REF", help="fail if the layout is not upgrade-safe against GIT_REF")
    args = p.parse_args(argv)

    if args.check:
        committed = json.loads(OUT.read_text())
        current = compiler_layout()
        check_probe_covers_namespaces(current)
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
        check_probe_covers_namespaces(current)
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
