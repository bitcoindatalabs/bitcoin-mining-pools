"""
pool_facts.py
Writes dashboard/data/lookup/pool_facts.json: per canonical pool slug, the facts the dashboard's pool profile shows
(the profile text itself is bdl-064's). Built by resolve_blocks.py on every run from the attribution and the
registry; `python3 scripts/pool_facts.py` rebuilds it from the files on disk.

{"registry_version": "...", "generated_at": "...", "tip_height": 0, "pools": {
  "<slug>": {
    "name": "...",                                   display name (the current name for all history)
    "former_names": [{"name", "source", "note"}],    real renames only (registry former_names)
    "host_pools": [{"slug", "blocks", "first_height", "last_height", "first_date", "last_date"}],
                                                     for a sub-pool: the pools that built and were paid for its
                                                     blocks; empty for an ordinary pool
    "sub_pools": [{"slug", "blocks", "first_date", "last_date"}],
                                                     for a host: the sub-pools whose blocks it built
    "blocks", "first_height", "last_height", "first_date", "last_date":
                                                     blocks whose `pool` is this slug (a host's sub-pool blocks are
                                                     in its sub_pools, not here)
    "methods": {"tag", "regex", "payout", "jlopp", "cooccurrence", "generic"}: how those blocks were labelled
    "identification_note": "..." or null             registry identification_notes, the sub-pool note, and a
                                                     sentence on co-occurrence labels, when any applies
  }}}
Dates are UTC block-header dates. The "unknown" slug is not a pool and is left out.
"""

import json
import os
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
POOL_FACTS = ROOT / "dashboard" / "data" / "lookup" / "pool_facts.json"
ATTRIBUTION = ROOT / "data" / "processed" / "block_attribution.parquet"
METHOD_KEYS = ("tag", "regex", "payout", "jlopp", "cooccurrence", "generic")


def _date(ts) -> str:
    return str(pd.to_datetime(int(ts), unit="s", utc=True).date())


def _span(g: pd.DataFrame) -> dict:
    return {"first_height": int(g["height"].min()), "last_height": int(g["height"].max()),
            "first_date": _date(g["time"].min()), "last_date": _date(g["time"].max())}


def _cooc_sentence(name: str, g: pd.DataFrame, registry: dict) -> str:
    c = g[g["method"] == "cooccurrence"]
    years = sorted(pd.to_datetime(c["time"], unit="s", utc=True).dt.year.unique())
    yr = f"{years[0]}" if len(years) == 1 else f"{years[0]}-{years[-1]}"
    cfg = registry.get("cooccurrence") or {}
    n, share = int(cfg.get("min_identified_blocks", 10)), float(cfg.get("min_share", 1.0))
    share_txt = "all of them" if share >= 1.0 else f"at least {share:.0%} of them"
    return (f"{len(c):,} blocks ({yr}) carry no pool tag but pay the same first output as at least {n} blocks that "
            f"carry a pool tag or pay a listed address, {share_txt} {name}'s; Bitcoin Data Labs labels them {name} "
            f"(co-occurrence).")


def build_pool_facts(df: pd.DataFrame, registry: dict, slug_to_name: dict) -> dict:
    """df: the attribution (height, time, pool, host_pool, method)."""
    df = df[["height", "time", "pool", "host_pool", "method"]]
    sub_notes = {e["slug"]: e.get("note") for e in registry.get("sub_pools", [])}
    id_notes = registry.get("identification_notes", {})
    former = registry.get("former_names", {})
    nested = df[df["pool"] != df["host_pool"]]
    slugs = (set(df["pool"]) | set(df["host_pool"])) - {"unknown"}
    pools = {}
    for slug in sorted(slugs):
        own = df[df["pool"] == slug]
        name = slug_to_name.get(slug, slug)
        e = {"name": name, "former_names": former.get(slug, [])}
        e["host_pools"] = [{"slug": h, "blocks": int(len(g)), **_span(g)}
                           for h, g in nested[nested["pool"] == slug].groupby("host_pool", sort=True)]
        e["host_pools"].sort(key=lambda x: (-x["blocks"], x["slug"]))
        e["sub_pools"] = []
        for s, g in nested[nested["host_pool"] == slug].groupby("pool", sort=True):
            sp = _span(g)
            e["sub_pools"].append({"slug": s, "blocks": int(len(g)), "first_date": sp["first_date"],
                                   "last_date": sp["last_date"]})
        e["sub_pools"].sort(key=lambda x: (-x["blocks"], x["slug"]))
        e["blocks"] = int(len(own))
        e.update(_span(own) if len(own) else {"first_height": None, "last_height": None, "first_date": None,
                                              "last_date": None})
        vc = own["method"].value_counts()
        e["methods"] = {k: int(vc.get(k, 0)) for k in METHOD_KEYS}
        notes = [n for n in (id_notes.get(slug), sub_notes.get(slug)) if n]
        if e["methods"]["cooccurrence"]:
            notes.append(_cooc_sentence(name, own, registry))
        e["identification_note"] = " ".join(notes) or None
        pools[slug] = e
    return {"registry_version": registry["registry_version"],
            "generated_at": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"),
            "tip_height": int(df["height"].max()), "pools": pools}


def write_pool_facts(facts: dict, path: Path = POOL_FACTS):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(facts, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def main() -> int:
    lookup = ROOT / "dashboard" / "data" / "lookup"
    registry = json.loads((lookup / "pools_enriched.json").read_text(encoding="utf-8"))
    slug_to_name = json.loads((lookup / "lookup_slug_to_name.json").read_text(encoding="utf-8"))
    df = pd.read_parquet(ATTRIBUTION, columns=["height", "time", "pool", "host_pool", "method"])
    facts = build_pool_facts(df, registry, slug_to_name)
    write_pool_facts(facts)
    print(f"{POOL_FACTS.relative_to(ROOT)}: {len(facts['pools'])} pools, tip {facts['tip_height']:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
