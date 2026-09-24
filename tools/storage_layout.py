#!/usr/bin/env python3
"""Storage layout gate for the upgradeable SRA and SWA contracts.

The contracts keep every piece of state in ERC-7201 namespaced structs reached through fixed slots, so
`forge inspect <Contract> storageLayout` is empty for them. test/layout/StorageLayoutProbe.sol declares one
state variable per namespace; this tool asks the compiler for that probe's layout and keeps a normalized copy
in storage-layout/layout.json. The slot constants themselves are pinned by test/StorageSlots.t.sol.

  tools/storage_layout.py                  regenerate storage-layout/layout.json
  tools/storage_layout.py --check          fail if the committed snapshot is stale
  tools/storage_layout.py --compat <ref>   fail if the layout is not upgrade-safe against <git-ref>

Upgrade-safe means every variable and every struct member present at <ref> keeps its slot, offset and type,
and anything new is appended (a new member after the existing ones, or a new namespace). Anything else
would reinterpret live storage behind the proxy and needs a migration, which docs/UPGRADE.md does not cover.
"""

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROBE = "StorageLayoutProbe"
OUT = os.path.join(ROOT, "storage-layout", "layout.json")


def compiler_layout():
    result = subprocess.run(
        ["forge", "inspect", PROBE, "storageLayout", "--json"], cwd=ROOT, capture_output=True, text=True
    )
    if result.returncode != 0:
        print("forge inspect failed (does the project compile?):", file=sys.stderr)
        print(result.stderr.strip()[-2000:], file=sys.stderr)
        sys.exit(1)
    return normalize(json.loads(result.stdout))


def normalize(layout):
    """Strip compiler noise (astId, contract) and resolve type ids to labels, keeping struct members."""
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


def entries_by_name(items):
    return {e["name"]: e for e in items}


def compare(base, new, path, errors):
    """Every base entry must exist in new at the same slot/offset/type; new entries may only be appended."""
    base_names = [e["name"] for e in base]
    new_names = [e["name"] for e in new]
    if new_names[: len(base_names)] != base_names:
        errors.append(f"{path}: order changed or entries removed: {base_names} -> {new_names}")
        return
    new_by = entries_by_name(new)
    for b in base:
        n = new_by[b["name"]]
        here = f"{path}.{b['name']}"
        for key in ("slot", "offset", "type", "bytes"):
            if b.get(key) != n.get(key):
                errors.append(f"{here}: {key} changed {b.get(key)!r} -> {n.get(key)!r}")
        for key in ("members", "value", "base"):
            if key in b:
                if key not in n:
                    errors.append(f"{here}: lost {key}")
                elif key == "members":
                    compare(b["members"], n["members"], here, errors)
                else:
                    compare([dict(b[key], name=key)], [dict(n[key], name=key)], here, errors)


def main(argv):
    mode = argv[1] if len(argv) > 1 else ""
    if mode == "":
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        with open(OUT, "w") as f:
            json.dump(compiler_layout(), f, indent=2)
            f.write("\n")
        print(f"wrote {os.path.relpath(OUT, ROOT)}")
        return 0
    if mode == "--check":
        with open(OUT) as f:
            committed = json.load(f)
        if committed != compiler_layout():
            print("storage-layout/layout.json is stale; run tools/storage_layout.py and commit the result", file=sys.stderr)
            return 1
        print("storage layout snapshot is up to date")
        return 0
    if mode == "--compat":
        ref = argv[2]
        rel = os.path.relpath(OUT, ROOT)
        try:
            base_text = subprocess.run(
                ["git", "show", f"{ref}:{rel}"], cwd=ROOT, check=True, capture_output=True, text=True
            ).stdout
        except subprocess.CalledProcessError:
            print(f"no snapshot at {ref}:{rel}; nothing to compare against")
            return 0
        errors = []
        compare(json.loads(base_text), compiler_layout(), "layout", errors)
        if errors:
            print("storage layout is NOT upgrade-safe relative to base:")
            for e in errors:
                print("  -", e)
            return 1
        print("storage layout is upgrade-safe relative to base")
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
