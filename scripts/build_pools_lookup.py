"""
build_pools_lookup.py
Merges the pinned upstream pool lists with our curated supplement into one versioned registry, and writes:
  - dashboard/data/lookup/pools_enriched.json      the registry pool_resolver.PoolResolver reads
  - dashboard/data/lookup/pool_conflicts.json      tags / addresses that two sources give to different pools
  - dashboard/data/lookup/lookup_slug_to_name.json slug -> display name
  - dashboard/data/lookup/pool_types.json          slug -> "solo" | "pool"

Sources (pinned in data/raw/pool_sources.lock.json; see data/raw/SOURCES.md):
  bitcoin-data   data/raw/pools.json             0xB10C's bitcoin-data/mining-pools, generated branch
                                                 (coinbase_tags: case-sensitive substrings; payout_addresses)
  mempool        data/raw/mempool-pools-v2.json  mempool/mining-pools master (per pool: tags = JS regexes run
                                                 case-insensitively by mempool, addresses)
  supplement     data/raw/pools_supplement.json  our curated additions; every new entry cites a source
                                                 (coinbase_tags, regexes, payout_addresses, slug_aliases,
                                                 generic_tags, payout_to_miners_slugs, pool_types)

Precedence: supplement > mempool > bitcoin-data. When two sources give the same tag text or the same address to
different pools (after slug aliases), the higher source wins, the lower entry is dropped, and the case is written
to pool_conflicts.json. A pool renamed upstream (BTC.com -> CloverPool, Slush Pool -> Braiins Pool) is mapped with
slug_aliases in the supplement, never by relabelling blocks.

registry_version = first 16 hex chars of sha256(pool_resolver.RESOLVER_VERSION, lock sources' sha + md5,
supplement md5). Every dataset built from
the registry records it.
"""

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
LOOKUP_DIR = ROOT / "dashboard" / "data" / "lookup"
LOCK = RAW / "pool_sources.lock.json"
SUPPLEMENT = RAW / "pools_supplement.json"
SOURCE_RANK = {"supplement": 0, "mempool": 1, "bitcoin-data": 2}

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pool_resolver import RESOLVER_VERSION, to_slug, apply_alias, addr_to_script, regex_problem  # noqa: E402


def _clean(d: dict) -> dict:
    return {k: v for k, v in (d or {}).items() if not k.startswith("_comment")}


def registry_version(lock: dict, supplement_bytes: bytes) -> str:
    h = hashlib.sha256(f"resolver:{RESOLVER_VERSION};".encode())
    for name in sorted(lock["sources"]):
        s = lock["sources"][name]
        h.update(f"{name}:{s['sha']}:{s['md5']};".encode())
    h.update(hashlib.md5(supplement_bytes).hexdigest().encode())
    return h.hexdigest()[:16]


def build(write: bool = True, lock: dict | None = None, quiet: bool = False):
    """Merge the sources into the registry. `lock` defaults to data/raw/pool_sources.lock.json; refresh_pool_sources.py
    passes a candidate lock whose `local` paths point at freshly fetched files (absolute paths are fine) to build
    and diff a candidate registry with write=False before anything in the repo changes."""
    lock = lock if lock is not None else json.loads(LOCK.read_text())
    sup_bytes = SUPPLEMENT.read_bytes()
    supplement = json.loads(sup_bytes)
    aliases = _clean(supplement.get("slug_aliases"))

    def slug_of(name: str) -> str:
        return apply_alias(to_slug(name), aliases)

    # ---- 1. collect candidate entries from every source --------------------------------------------------------
    tag_cands, addr_cands, names = [], [], {}

    # Display names: supplement > bitcoin-data > mempool (the dashboard's pools_info.json and earlier releases use
    # bitcoin-data's names; matching precedence above is unaffected). supplement.display_names overrides all.
    name_rank = {"supplement": 0, "bitcoin-data": 1, "mempool": 2}

    def note_name(slug, name, source):
        cur = names.get(slug)
        if cur is None or name_rank[source] < cur[1]:
            names[slug] = (name, name_rank[source])

    bd = json.loads((ROOT / lock["sources"]["bitcoin-data"]["local"]).read_text())
    rejected_tags = []
    for tag, info in bd.get("coinbase_tags", {}).items():
        s = slug_of(info["name"])
        if not tag.strip():             # an empty tag is a substring of every coinbase
            rejected_tags.append({"tag": tag, "slug": s, "source": "bitcoin-data", "error": "empty tag"})
            continue
        tag_cands.append({"text": tag, "kind": "tag", "slug": s, "name": info["name"], "link": info.get("link", ""),
                          "source": "bitcoin-data"})
        note_name(s, info["name"], "bitcoin-data")
    for addr, info in bd.get("payout_addresses", {}).items():
        s = slug_of(info["name"])
        addr_cands.append({"addr": addr, "slug": s, "name": info["name"], "link": info.get("link", ""),
                           "source": "bitcoin-data"})
        note_name(s, info["name"], "bitcoin-data")

    mp = json.loads((ROOT / lock["sources"]["mempool"]["local"]).read_text(encoding="utf-8"))
    for pool in mp:
        s = slug_of(pool["name"])
        note_name(s, pool["name"], "mempool")
        for pat in pool.get("tags", pool.get("regexes", [])):
            tag_cands.append({"text": pat, "kind": "regex", "slug": s, "name": pool["name"],
                              "link": pool.get("link", ""), "source": "mempool", "mempool_id": pool.get("id")})
        for addr in pool.get("addresses", []):
            addr_cands.append({"addr": addr, "slug": s, "name": pool["name"], "link": pool.get("link", ""),
                               "source": "mempool"})

    for tag, info in _clean(supplement.get("coinbase_tags")).items():
        s = slug_of(info["name"])
        tag_cands.append({"text": tag, "kind": "tag", "slug": s, "name": info["name"], "link": info.get("link", ""),
                          "source": "supplement", "cite": info.get("source", "")})
        note_name(s, info["name"], "supplement")
    for r in supplement.get("regexes", []):
        s = slug_of(r["name"])
        tag_cands.append({"text": r["pattern"], "kind": "regex", "slug": s, "name": r["name"],
                          "link": r.get("link", ""), "source": "supplement", "cite": r.get("source", "")})
        note_name(s, r["name"], "supplement")
    for addr, info in _clean(supplement.get("payout_addresses")).items():
        s = slug_of(info["name"])
        addr_cands.append({"addr": addr, "slug": s, "name": info["name"], "link": info.get("link", ""),
                           "source": "supplement", "cite": info.get("source", "")})
        note_name(s, info["name"], "supplement")
    for slug, name in _clean(supplement.get("display_names")).items():
        names[slug] = (name, -1)

    # ---- 2. resolve conflicts by precedence --------------------------------------------------------------------
    conflicts = []
    by_text: dict = {}
    for c in tag_cands:
        by_text.setdefault(c["text"], []).append(c)
    kept_tags = []
    for text, cs in by_text.items():
        winner = min(cs, key=lambda c: SOURCE_RANK[c["source"]])
        if len({c["slug"] for c in cs}) > 1:
            conflicts.append({"kind": "tag", "key": text, "winner": winner["slug"], "winner_source": winner["source"],
                              "candidates": [{"source": c["source"], "slug": c["slug"], "name": c["name"]}
                                             for c in cs]})
            cs = [c for c in cs if c["slug"] == winner["slug"]]
        kept_tags.extend(cs)            # same text, same slug: keep both (a regex is case-insensitive, a tag not)

    addrs, by_addr = {}, {}
    for c in addr_cands:
        by_addr.setdefault(c["addr"], []).append(c)
    for addr, cs in by_addr.items():
        winner = min(cs, key=lambda c: SOURCE_RANK[c["source"]])
        if len({c["slug"] for c in cs}) > 1:
            conflicts.append({"kind": "address", "key": addr, "winner": winner["slug"],
                              "winner_source": winner["source"],
                              "candidates": [{"source": c["source"], "slug": c["slug"], "name": c["name"]}
                                             for c in cs]})
        addrs[addr] = winner

    # ---- 3. validate: addresses decode, regexes compile ---------------------------------------------------------
    undecoded, rejected, regexes = [], [], []
    for addr, c in addrs.items():
        try:
            addr_to_script(addr)
        except (ValueError, IndexError):
            undecoded.append({"address": addr, "slug": c["slug"], "source": c["source"]})
    for c in kept_tags:
        if c["kind"] != "regex":
            continue
        problem = regex_problem(c["text"])
        if problem:
            rejected.append({"pattern": c["text"], "slug": c["slug"], "source": c["source"], "error": problem})
        else:
            regexes.append(c)

    # ---- 4. assemble the registry -------------------------------------------------------------------------------
    def entry(c):
        e = {"name": names.get(c["slug"], (c["name"],))[0], "slug": c["slug"], "link": c["link"],
             "source": c["source"]}
        if c.get("cite"):
            e["cite"] = c["cite"]
        return e

    coinbase_tags = {}
    for c in sorted((c for c in kept_tags if c["kind"] == "tag"), key=lambda c: SOURCE_RANK[c["source"]]):
        coinbase_tags.setdefault(c["text"], entry(c))
    supplement_overrides = _clean(supplement.get("supplement_overrides"))
    pool_types = {}
    for _tag, info in _clean(supplement.get("coinbase_tags")).items():
        if info.get("type"):
            pool_types[slug_of(info["name"])] = info["type"]
    pool_types.update(_clean(supplement.get("pool_types")))

    version = registry_version(lock, sup_bytes)
    enriched = {
        "registry_version": version,
        "sources": {k: {f: v[f] for f in ("repo", "branch", "sha", "commit_date", "md5")}
                    for k, v in lock["sources"].items()} | {
            "supplement": {"file": "data/raw/pools_supplement.json", "md5": hashlib.md5(sup_bytes).hexdigest()}},
        "resolver_version": RESOLVER_VERSION,
        "source_rank": SOURCE_RANK,
        "coinbase_tags": dict(sorted(coinbase_tags.items())),
        "regexes": [entry(c) | {"pattern": c["text"], "mempool_id": c.get("mempool_id")}
                    for c in sorted(regexes, key=lambda c: (c.get("mempool_id") or 0, c["text"]))],
        "payout_addresses": {a: entry(c) for a, c in sorted(addrs.items())},
        "slug_aliases": aliases,
        "generic_tags": supplement.get("generic_tags", []),
        "generic_slugs": supplement.get("generic_slugs", []),
        "payout_to_miners_slugs": sorted(set(supplement.get("payout_to_miners_slugs", []))
                                         | {s for s, t in pool_types.items() if t == "solo"}),
        "validation": {"undecoded_addresses": undecoded, "rejected_regexes": rejected,
                       "rejected_tags": rejected_tags},
    }

    slug_to_name = {s: n for s, (n, _r) in names.items()}
    for src, tgt in aliases.items():
        if tgt not in slug_to_name and src in slug_to_name:
            slug_to_name[tgt] = slug_to_name[src]
    for src in aliases:                 # aliased slugs never appear in outputs
        slug_to_name.pop(src, None)
    slug_to_name["unknown"] = "Unknown"
    slug_to_name = dict(sorted(slug_to_name.items()))

    if write:
        LOOKUP_DIR.mkdir(parents=True, exist_ok=True)

        def dump(name, obj):
            (LOOKUP_DIR / name).write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        dump("pools_enriched.json", enriched)
        dump("pool_conflicts.json", {"registry_version": version, "conflicts": conflicts})
        dump("lookup_slug_to_name.json", slug_to_name)
        dump("pool_types.json", dict(sorted(pool_types.items())))
    if not quiet:
        print(f"registry {version}: {len(coinbase_tags)} substring tags, {len(regexes)} regexes, "
              f"{len(addrs)} payout addresses ({len(undecoded)} not mainnet-decodable), "
              f"{len(rejected)} rejected regexes, {len(conflicts)} conflicts, {len(slug_to_name)} slugs")

    return enriched, slug_to_name, aliases, supplement_overrides, pool_types, conflicts


if __name__ == "__main__":
    build()
