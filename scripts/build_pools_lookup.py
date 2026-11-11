"""
build_pools_lookup.py
Merges data/raw/pools.json (upstream bitcoin-data/mining-pools) with
data/raw/pools_supplement.json (our local additions) and writes:
  - dashboard/data/lookup/lookup_slug_to_name.json   (slug -> display name)
  - dashboard/data/lookup/pools_enriched.json        (merged coinbase_tags + payout_addresses)
  - dashboard/data/lookup/pool_types.json            (slug -> type: "solo" | "pool")
The enriched JSON is used by merge_myrp.py and process_forensics.py for
coinbase_tag resolution so there is one canonical place to add new pools.
"""

import json
from pathlib import Path

ROOT = Path(__file__).parent.parent
RAW = ROOT / "data" / "raw"
LOOKUP_DIR = ROOT / "dashboard" / "data" / "lookup"
LOOKUP_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Canonical slug: lowercase, strip spaces / hyphens / underscores / dots
# ---------------------------------------------------------------------------
def to_slug(name: str) -> str:
    if not name:
        return "unknown"
    s = name.lower()
    if s == "unknown":
        return "unknown"
    for ch in (" ", "-", "_", "."):
        s = s.replace(ch, "")
    return s or "unknown"


def build():
    # --- 1. Load upstream pools.json -----------------------------------------
    with open(RAW / "pools.json") as f:
        upstream = json.load(f)

    # --- 2. Load supplemental file -------------------------------------------
    with open(RAW / "pools_supplement.json") as f:
        supplement = json.load(f)

    # --- 3. Merge coinbase_tags (supplement adds to / overrides upstream) ----
    merged_tags = dict(upstream.get("coinbase_tags", {}))
    for tag, info in supplement.get("coinbase_tags", {}).items():
        if tag.startswith("_comment"):
            continue
        merged_tags[tag] = info

    # --- 4. Merge payout_addresses (supplement adds to upstream) -------------
    merged_addrs = dict(upstream.get("payout_addresses", {}))
    for addr, info in supplement.get("payout_addresses", {}).items():
        if addr.startswith("_comment"):
            continue
        merged_addrs[addr] = info

    # --- 5. Build slug -> canonical name lookup ------------------------------
    slug_to_name: dict[str, str] = {}

    # coinbase_tags first (majority of active pools)
    for _tag, info in merged_tags.items():
        name = info.get("name", "")
        if name:
            slug_to_name[to_slug(name)] = name

    # payout_addresses fill in anything coinbase_tags missed
    for _addr, info in merged_addrs.items():
        name = info.get("name", "")
        if name:
            slug = to_slug(name)
            if slug not in slug_to_name:
                slug_to_name[slug] = name

    slug_to_name["unknown"] = "Unknown"

    # --- 6. Apply slug aliases (e.g. legacy myrp slugs -> canonical slugs) --
    slug_aliases: dict[str, str] = {
        k: v
        for k, v in supplement.get("slug_aliases", {}).items()
        if not k.startswith("_comment")
    }
    # Ensure every alias target is in the lookup
    for src, tgt in slug_aliases.items():
        if tgt not in slug_to_name and src in slug_to_name:
            slug_to_name[tgt] = slug_to_name[src]

    # --- 6b. Supplement overrides: bp-resolved slug -> myrp slugs it beats --
    supplement_overrides: dict[str, list[str]] = {
        k: v
        for k, v in supplement.get("supplement_overrides", {}).items()
        if not k.startswith("_comment")
    }

    # --- 6c. Build slug -> type ("solo" | "pool") ----------------------------
    # Priority: pool_types section (explicit overrides) > type field on coinbase_tags
    # Anything not classified defaults to "pool".
    pool_types: dict[str, str] = {}

    # Collect types declared inline on coinbase_tag entries (supplement only;
    # upstream pools.json has no type field)
    for _tag, info in supplement.get("coinbase_tags", {}).items():
        if _tag.startswith("_comment"):
            continue
        t = info.get("type")
        name = info.get("name", "")
        if t and name:
            pool_types[to_slug(name)] = t

    # Explicit pool_types section overrides anything derived above
    for slug, t in supplement.get("pool_types", {}).items():
        if not slug.startswith("_comment"):
            pool_types[slug] = t

    slug_to_name = dict(sorted(slug_to_name.items()))

    # --- 7. Write lookup_slug_to_name.json -----------------------------------
    lookup_path = LOOKUP_DIR / "lookup_slug_to_name.json"
    with open(lookup_path, "w") as f:
        json.dump(slug_to_name, f, indent=2, ensure_ascii=False)
    print(f"lookup_slug_to_name.json  → {len(slug_to_name)} entries  ({lookup_path})")

    # --- 8. Write pools_enriched.json (for coinbase_tag resolution) ----------
    enriched = {
        "coinbase_tags": merged_tags,
        "payout_addresses": merged_addrs,
        "slug_aliases": slug_aliases,
    }
    enriched_path = LOOKUP_DIR / "pools_enriched.json"
    with open(enriched_path, "w") as f:
        json.dump(enriched, f, indent=2, ensure_ascii=False)
    print(f"pools_enriched.json       → {len(merged_tags)} coinbase_tags, "
          f"{len(merged_addrs)} payout_addresses  ({enriched_path})")

    # --- 9. Write pool_types.json --------------------------------------------
    types_path = LOOKUP_DIR / "pool_types.json"
    with open(types_path, "w") as f:
        json.dump(dict(sorted(pool_types.items())), f, indent=2, ensure_ascii=False)
    solo_count = sum(1 for t in pool_types.values() if t == "solo")
    print(f"pool_types.json           → {len(pool_types)} classified slugs "
          f"({solo_count} solo)  ({types_path})")

    return enriched, slug_to_name, slug_aliases, supplement_overrides, pool_types


if __name__ == "__main__":
    build()
