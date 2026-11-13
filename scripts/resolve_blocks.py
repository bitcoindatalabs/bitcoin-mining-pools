"""
resolve_blocks.py
Labels every block with its mining pool using the one resolver (pool_resolver.py) and writes:

  data/processed/block_attribution.parquet   every height in data/raw/coinbase_blocks.parquet
      height, time, pool_slug, method, coinbase_tag, jlopp_slug, tag_slug, payout_slug, generic_slug, pool, host_pool
      (schema metadata: registry_version, sources)
      pool       the most specific operator (TrustPool); host_pool the pool that built the block and was paid
      (ViaBTC). pool_slug is an alias of host_pool, kept for older readers.
  dashboard/data/blocks_pre_2021.parquet     height < 664,063   (height, pool, host_pool, date)
  dashboard/data/blocks_post_2021.parquet    height >= 664,063  (height, pool, host_pool, date)
  dashboard/data/lookup/pool_facts.json      per pool: name, former names, hosts / sub-pools, block counts by
                                             method, identification note (pool_facts.py)
  data/status/cooccurrence_scripts.json      the evidence for every co-occurrence label
  data/status/tag_payout_pairs.json          every tag != payout pair, with its decision (or 'undecided')

Inputs:
  data/raw/coinbase_blocks.parquet  from extract_coinbase.py (coinbase scriptSig + payout scripts per block)
  dashboard/data/lookup/pools_enriched.json  the registry, rebuilt here by build_pools_lookup.py
  data/raw/blocks.csv               jlopp/bitcoin-blocks-by-mining-pool labels, heights 0-869,305. FROZEN: never
                                    refreshed (owner decision 2026-11-12); used only as precedence rule 3.

method: tag | regex | payout | jlopp | cooccurrence | generic | unknown (see pool_resolver.py for the precedence).

Co-occurrence (bdl-063) is recomputed on every run, from the whole attribution: a script that is the first payout
script of >= registry.cooccurrence.min_identified_blocks blocks identified by tag, regex or payout, >= min_share of
them one host pool P (P not a payout-to-miners pool), labels the generic or unknown blocks whose first payout script
it is. jlopp, generic and co-occurrence labels are never evidence, so the result does not depend on earlier runs.

By default only heights above the existing attribution file are resolved, unless the registry_version changed
(then every block is re-resolved, ~1 minute) or --full is passed. Every block is re-resolved, not only those
labelled by tag, payout or unknown: under the resolver's precedence a new tag or payout entry also outranks the
jlopp fallback (rule 3), so jlopp-labelled blocks are re-checked too.

When labels change on existing heights (a registry change, or co-occurrence evidence that moved), the changes
are appended to data/status/relabel_log.json: per run, the old and new registry_version and source SHAs and, per
(from, to) host_pool pair ("transitions") and per (from, to) pool pair ("pool_transitions"), the number of blocks,
the new methods and the heights (as [lo, hi] ranges).

Usage: python3 scripts/resolve_blocks.py [--full] [--workers N]
"""

import argparse
import json
import os
import sys
import time
from multiprocessing import get_context
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
DASHBOARD_DATA = ROOT / "dashboard" / "data"
COINBASE = RAW / "coinbase_blocks.parquet"
JLOPP = RAW / "blocks.csv"
JLOPP_MAX_HEIGHT = 869_305
ATTRIBUTION = PROCESSED / "block_attribution.parquet"
RELABEL_LOG = ROOT / "data" / "status" / "relabel_log.json"
RELABEL_LOG_KEEP = 200          # runs kept in the log
MAX_RANGES = 5000               # height ranges kept per transition
POST_2021_HEIGHT = 664_063

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_pools_lookup import build as build_registry  # noqa: E402
from pool_facts import build_pool_facts, write_pool_facts  # noqa: E402
from pool_resolver import PoolResolver, script_to_addr  # noqa: E402

COOC_EVIDENCE = ROOT / "data" / "status" / "cooccurrence_scripts.json"
PAIRS_STATUS = ROOT / "data" / "status" / "tag_payout_pairs.json"

COLUMNS = ["height", "time", "pool_slug", "method", "coinbase_tag", "jlopp_slug", "tag_slug", "payout_slug",
           "generic_slug", "pool", "host_pool"]
IDENTIFIED = ("tag", "regex", "payout")          # methods whose blocks count as co-occurrence evidence

_RESOLVER = None


def _init(registry, cooccurrence=None):
    global _RESOLVER
    _RESOLVER = PoolResolver(registry, cooccurrence)


def _resolve_chunk(args):
    heights, times, sigs, payouts, jlopp = args
    out = []
    for h, t, sig, pay, jl in zip(heights, times, sigs, payouts, jlopp):
        a = _RESOLVER.resolve(sig, pay, jl)
        out.append((h, t, a.slug, a.method, a.tag, _RESOLVER.slug(jl) if jl else None, a.tag_slug, a.payout_slug,
                    a.generic_slug, a.pool, a.slug))
    return out


def load_jlopp() -> pd.Series:
    jl = pd.read_csv(JLOPP, usecols=["height", "pool_slug"], dtype={"height": "int64", "pool_slug": "str"})
    jl = jl[jl["height"] <= JLOPP_MAX_HEIGHT]
    # blocks.csv repeats 10 rows (860,579-860,588) verbatim; keep one per height
    jl = jl.drop_duplicates(subset=["height", "pool_slug"])
    if jl["height"].duplicated().any():
        raise ValueError("blocks.csv has conflicting labels for one height")
    return jl.set_index("height")["pool_slug"].fillna("unknown")


def resolve(cb: pd.DataFrame, registry: dict, workers: int, cooccurrence=None, jlopp=None) -> pd.DataFrame:
    """Resolve the blocks in cb (height, time, scriptsig, payout_scripts). Without `cooccurrence` this is the base
    labelling; label_blocks() adds co-occurrence. `jlopp`: per-row jlopp slugs (default: read blocks.csv)."""
    if jlopp is None:
        jl = load_jlopp()
        jlopp = cb["height"].map(jl).where(lambda s: s.notna(), None).tolist()
    n = len(cb)
    step = max(1, -(-n // (workers * 8)))
    chunks = [(cb["height"].iloc[i:i + step].tolist(), cb["time"].iloc[i:i + step].tolist(),
               cb["scriptsig"].iloc[i:i + step].tolist(), cb["payout_scripts"].iloc[i:i + step].tolist(),
               jlopp[i:i + step]) for i in range(0, n, step)]
    rows = []
    if workers > 1 and n > 5000:
        with get_context("fork").Pool(workers, initializer=_init, initargs=(registry, cooccurrence)) as pool:
            for part in pool.imap(_resolve_chunk, chunks):
                rows.extend(part)
    else:
        _init(registry, cooccurrence)
        for c in chunks:
            rows.extend(_resolve_chunk(c))
    return pd.DataFrame(rows, columns=COLUMNS)


def first_scripts(cb: pd.DataFrame) -> pd.Series:
    """height -> hex of the block's first payout script (first non-OP_RETURN coinbase output), or None."""
    return pd.Series([bytes(x[0]).hex() if x is not None and len(x) else None for x in cb["payout_scripts"]],
                     index=cb["height"].to_numpy())


def cooccurrence_table(df: pd.DataFrame, s0: pd.Series, registry: dict):
    """The co-occurrence rule on a base attribution. Returns ({script_hex: host slug}, evidence rows, near misses).
    Evidence = blocks whose method is tag, regex or payout, counted by host_pool. A script qualifies when it is the
    first payout script of >= min_identified_blocks such blocks and >= min_share of them belong to one host pool P,
    and none of them belongs to a pool that pays its miners in the coinbase."""
    cfg = registry.get("cooccurrence") or {}
    min_n, min_share = int(cfg.get("min_identified_blocks", 10)), float(cfg.get("min_share", 1.0))
    p2m = set(registry.get("payout_to_miners_slugs", []))
    d = pd.DataFrame({"height": df["height"].to_numpy(), "host": df["host_pool"].to_numpy(),
                      "method": df["method"].to_numpy(), "s0": s0.reindex(df["height"].to_numpy()).to_numpy()})
    d = d[d["s0"].notna()]
    ident = d[d["method"].isin(IDENTIFIED)]
    cand = d[d["method"].isin(("cooccurrence", "generic", "unknown"))]
    cand_scripts = set(cand["s0"])
    ident = ident[ident["s0"].isin(cand_scripts)]          # only scripts that could label something matter
    table, evidence, near = {}, [], []
    for s, g in ident.groupby("s0", sort=True):
        n = len(g)
        vc = g["host"].value_counts()
        top, share = vc.index[0], float(vc.iloc[0] / n)
        if n < min_n:
            continue
        unl = cand[cand["s0"] == s]
        if share < min_share or set(vc.index) & p2m:
            if share >= 0.9:
                near.append({"script": s, "address": script_to_addr(bytes.fromhex(s)), "top_pool": top,
                             "share": round(share, 4), "identified_blocks": int(n),
                             "hosts": {k: int(v) for k, v in vc.items()},
                             "would_label_blocks": int(len(unl)),
                             "why_not": "payout-to-miners pool" if set(vc.index) & p2m else "share below min_share"})
            continue
        table[s] = top
        evidence.append({"script": s, "address": script_to_addr(bytes.fromhex(s)), "pool": top,
                         "identified_blocks": int(n),
                         "identified_methods": {k: int(v) for k, v in g["method"].value_counts().items()},
                         "identified_heights": [int(g["height"].min()), int(g["height"].max())],
                         "labelled_blocks": int(len(unl)),
                         "labelled_heights": [int(unl["height"].min()), int(unl["height"].max())]})
    evidence.sort(key=lambda e: (-e["labelled_blocks"], e["script"]))
    near.sort(key=lambda e: (-e["would_label_blocks"], e["script"]))
    return table, evidence, near


def label_blocks(base: pd.DataFrame, cb: pd.DataFrame, registry: dict, workers: int):
    """Add co-occurrence labels to a base attribution covering every height in cb. Blocks whose method is
    cooccurrence (from an earlier run), generic or unknown and whose first payout script is in the table, or that
    were co-occurrence-labelled before, are re-resolved with the table, so they end up exactly as a fresh run would
    label them. Returns (attribution, evidence dict)."""
    s0 = first_scripts(cb)
    reverted = base["method"] == "cooccurrence"
    if reverted.any():                                     # back to the base label before computing the table
        base = base.copy()
        gen = base["generic_slug"].notna() & reverted
        base.loc[reverted, ["method", "coinbase_tag"]] = ["unknown", None]
        base.loc[reverted, ["pool", "host_pool", "pool_slug"]] = "unknown"
        base.loc[gen, "method"] = "generic"
        for c in ("pool", "host_pool", "pool_slug"):
            base.loc[gen, c] = base.loc[gen, "generic_slug"]
    table, evidence, near = cooccurrence_table(base, s0, registry)
    s0_rows = s0.reindex(base["height"].to_numpy()).to_numpy()
    redo = (base["method"].isin(("generic", "unknown")) & pd.Series(s0_rows, index=base.index).isin(table)) | reverted
    if redo.any():
        sub = cb.set_index("height").loc[base.loc[redo, "height"].to_numpy()].reset_index()
        jl = base.loc[redo, "jlopp_slug"].where(lambda s: s.notna(), None).tolist()
        new = resolve(sub, registry, 1, cooccurrence=table, jlopp=jl)
        new.index = base.index[redo]
        base = base.copy()
        base.loc[redo, COLUMNS] = new[COLUMNS]
    cfg = registry.get("cooccurrence") or {}
    lab = base[base["method"] == "cooccurrence"]
    era = pd.cut(lab["height"], [-1, 299_999, 419_999, 799_999, 10**9],
                 labels=["0-299,999", "300,000-419,999", "420,000-799,999", "800,000+"])
    ev = {"registry_version": registry["registry_version"],
          "rule": {"min_identified_blocks": int(cfg.get("min_identified_blocks", 10)),
                   "min_share": float(cfg.get("min_share", 1.0)),
                   "evidence_methods": list(IDENTIFIED),
                   "excluded": "scripts with identified blocks from payout_to_miners_slugs pools"},
          "tip_height": int(base["height"].max()),
          "labelled_blocks": int(len(lab)),
          "labelled_by_pool": {k: int(v) for k, v in lab["pool"].value_counts().items()},
          "labelled_by_range": {str(k): int(v) for k, v in era.value_counts(sort=False).items()},
          "scripts": evidence, "near_misses": near}
    return base, ev


def pairs_status(df: pd.DataFrame, registry: dict) -> dict:
    """Every (specific tag slug, payout slug) pair that disagrees, with its decision and the labels it produced."""
    r = PoolResolver(registry)
    x = df[df["tag_slug"].notna() & df["payout_slug"].notna() & (df["tag_slug"] != df["payout_slug"])]
    rows = []
    for (a, b), g in x.groupby(["tag_slug", "payout_slug"], sort=True):
        dec = r.pair_decision(a, b)
        if dec is None and a in r.payout_to_miners:
            dec = "tag (payout_to_miners, undecided)"
        rows.append({"tag_slug": a, "payout_slug": b, "decision": dec or "undecided", "blocks": int(len(g)),
                     "heights": [int(g["height"].min()), int(g["height"].max())],
                     "dates": [str(pd.to_datetime(g["time"].min(), unit="s").date()),
                               str(pd.to_datetime(g["time"].max(), unit="s").date())],
                     "labels": {f"{p}@{h}": int(n) for (p, h), n in g.groupby(["pool", "host_pool"]).size().items()}})
    rows.sort(key=lambda e: (-e["blocks"], e["tag_slug"], e["payout_slug"]))
    return {"registry_version": registry["registry_version"], "tip_height": int(df["height"].max()),
            "undecided": [f"{e['tag_slug']}->{e['payout_slug']}" for e in rows if e["decision"] == "undecided"],
            "pairs": rows}


def write_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def height_ranges(heights) -> list:
    """Sorted heights -> [h, [lo, hi], ...]: single heights as ints, runs as [lo, hi]."""
    out = []
    for h in sorted(int(x) for x in heights):
        if out and isinstance(out[-1], list) and out[-1][1] == h - 1:
            out[-1][1] = h
        elif out and isinstance(out[-1], int) and out[-1] == h - 1:
            out[-1] = [out[-1], h]
        else:
            out.append(h)
    return out


def _transitions(m: pd.DataFrame, col: str) -> list:
    ch = m[m[f"{col}_old"] != m[f"{col}_new"]]
    out = []
    for (a, b), g in ch.groupby([f"{col}_old", f"{col}_new"]):
        r = height_ranges(g["height"])
        t = {"from": a, "to": b, "blocks": int(len(g)), "methods": g["method"].value_counts().to_dict(),
             "heights": r[:MAX_RANGES]}
        if len(r) > MAX_RANGES:
            t["heights_truncated"] = True
        out.append(t)
    out.sort(key=lambda t: (-t["blocks"], t["from"], t["to"]))
    return out


def _labels(df: pd.DataFrame) -> pd.DataFrame:
    """height, host_pool, pool from any attribution version (before bdl-063 only pool_slug existed)."""
    host = df["host_pool"] if "host_pool" in df else df["pool_slug"]
    pool = df["pool"] if "pool" in df else host
    out = pd.DataFrame({"height": df["height"].to_numpy(), "host_pool": host.to_numpy(), "pool": pool.to_numpy()})
    if "method" in df:
        out["method"] = df["method"].to_numpy()
    return out


def summarise_relabels(prev: pd.DataFrame, new: pd.DataFrame) -> dict:
    """Label changes between two attributions on their common heights: host_pool changes ("transitions", the
    concentration label, as in bdl-062) and pool changes ("pool_transitions")."""
    m = _labels(prev).drop(columns=["method"], errors="ignore").merge(_labels(new), on="height",
                                                                       suffixes=("_old", "_new"))
    # blocks_changed / transitions keep bdl-062's meaning (the concentration label, host_pool), which the ops alert
    # reads; pool_changed / pool_transitions add the sub-pool level.
    return {"blocks_compared": int(len(m)),
            "blocks_changed": int((m["host_pool_old"] != m["host_pool_new"]).sum()),
            "pool_changed": int((m["pool_old"] != m["pool_new"]).sum()),
            "unknown_before": int((m["host_pool_old"] == "unknown").sum()),
            "unknown_after": int((m["host_pool_new"] == "unknown").sum()),
            "transitions": _transitions(m, "host_pool"), "pool_transitions": _transitions(m, "pool")}


def append_relabel_log(entry: dict):
    log = {"runs": []}
    if RELABEL_LOG.exists():
        log = json.loads(RELABEL_LOG.read_text(encoding="utf-8"))
    log["runs"] = (log.get("runs", []) + [entry])[-RELABEL_LOG_KEEP:]
    RELABEL_LOG.parent.mkdir(parents=True, exist_ok=True)
    tmp = RELABEL_LOG.with_name(RELABEL_LOG.name + ".tmp")
    tmp.write_text(json.dumps(log, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, RELABEL_LOG)


def write_attribution(df: pd.DataFrame, registry: dict):
    PROCESSED.mkdir(parents=True, exist_ok=True)
    df = df.astype({"height": "int32", "time": "int64"})
    table = pa.Table.from_pandas(df, preserve_index=False)
    meta = dict(table.schema.metadata or {})
    meta[b"registry_version"] = registry["registry_version"].encode()
    meta[b"sources"] = json.dumps(registry["sources"]).encode()
    table = table.replace_schema_metadata(meta)
    tmp = ATTRIBUTION.with_suffix(".tmp.parquet")
    pq.write_table(table, tmp, compression="zstd",
                   use_dictionary=["pool_slug", "method", "coinbase_tag", "jlopp_slug", "tag_slug", "payout_slug",
                                   "generic_slug", "pool", "host_pool"])
    os.replace(tmp, ATTRIBUTION)


def write_dashboard(df: pd.DataFrame, registry: dict):
    d = pd.DataFrame({"height": df["height"].astype("int64"), "pool": df["pool"], "host_pool": df["host_pool"],
                      "date": pd.to_datetime(df["time"], unit="s", utc=True).dt.as_unit("us")})
    # height dtypes as the dashboard has always read them: int32 in the pre-2021 file, int64 in the post-2021 file
    for name, part in (("blocks_pre_2021.parquet", d[d["height"] < POST_2021_HEIGHT].astype({"height": "int32"})),
                       ("blocks_post_2021.parquet", d[d["height"] >= POST_2021_HEIGHT])):
        path = DASHBOARD_DATA / name
        tmp = path.with_suffix(".tmp.parquet")
        t = pa.Table.from_pandas(part.reset_index(drop=True), preserve_index=False)
        t = t.replace_schema_metadata({**(t.schema.metadata or {}),
                                       b"registry_version": registry["registry_version"].encode(),
                                       b"sources": json.dumps(registry["sources"]).encode()})
        pq.write_table(t, tmp, compression="snappy", use_dictionary=["pool", "host_pool"], write_statistics=True)
        os.replace(tmp, path)
        print(f"  {name}: {len(part):,} blocks, {(part['host_pool'] == 'unknown').sum():,} unknown, "
              f"{path.stat().st_size / 1e6:.2f} MB")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="re-resolve every block")
    ap.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 1))
    a = ap.parse_args()

    if not COINBASE.exists():
        print(f"ERROR: {COINBASE} missing; run scripts/extract_coinbase.py first", file=sys.stderr)
        return 1
    registry, slug_to_name, *_ = build_registry()
    version = registry["registry_version"]
    cb = pd.read_parquet(COINBASE)
    if cb.empty:
        print("ERROR: coinbase_blocks.parquet is empty", file=sys.stderr)
        return 1

    old = None
    old_meta = (pq.read_schema(ATTRIBUTION).metadata or {}) if ATTRIBUTION.exists() else {}
    old_version = old_meta.get(b"registry_version", b"").decode() or None
    prev = pd.read_parquet(ATTRIBUTION) if ATTRIBUTION.exists() else None
    if prev is not None:
        if old_version == version and not a.full and {"pool", "host_pool"} <= set(prev.columns):
            old = prev
        else:
            print(f"registry_version {old_version} -> {version}{' (--full)' if a.full else ''}; "
                  f"re-resolving every block")
    todo = cb if old is None else cb[cb["height"] > old["height"].max()]
    t0 = time.time()
    print(f"Resolving {len(todo):,} blocks (registry {version}) ...")
    new = resolve(todo, registry, a.workers) if len(todo) else pd.DataFrame(columns=COLUMNS)
    df = new if old is None else pd.concat([old[COLUMNS], new], ignore_index=True)
    df = df.sort_values("height").reset_index(drop=True)
    h = df["height"].to_numpy()
    if h[0] != 0 or not (h[1:] - h[:-1] == 1).all():
        print("ERROR: attribution heights are not contiguous from 0; refusing to write", file=sys.stderr)
        return 1
    df, cooc = label_blocks(df, cb[cb["height"] <= h[-1]], registry, a.workers)
    df["pool_slug"] = df["host_pool"]
    write_attribution(df, registry)
    write_json(COOC_EVIDENCE, cooc)
    pairs = pairs_status(df, registry)
    write_json(PAIRS_STATUS, pairs)
    print(f"  co-occurrence: {cooc['labelled_blocks']:,} blocks from {len(cooc['scripts'])} scripts "
          f"{cooc['labelled_by_range']}; tag != payout pairs: {len(pairs['pairs'])}, undecided "
          f"{pairs['undecided'] or 'none'}")
    if prev is not None:
        rel = summarise_relabels(prev, df)
        if old_version != version or rel["blocks_changed"] or rel["pool_changed"]:
            old_sources = json.loads(old_meta.get(b"sources", b"{}") or b"{}")
            append_relabel_log({
                "run_at": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"),
                "registry_version_old": old_version, "registry_version_new": version,
                "sources_old": {k: v.get("sha") or v.get("md5") for k, v in old_sources.items()},
                "sources_new": {k: v.get("sha") or v.get("md5") for k, v in registry["sources"].items()},
                **rel})
            print(f"  relabelled {rel['blocks_changed']:,} of {rel['blocks_compared']:,} blocks' host_pool and "
                  f"{rel['pool_changed']:,} blocks' pool (unknown {rel['unknown_before']:,} -> "
                  f"{rel['unknown_after']:,}); logged in {RELABEL_LOG.relative_to(ROOT)}")
            for t in rel["transitions"][:15]:
                print(f"    host {t['from']} -> {t['to']}: {t['blocks']:,}")
            for t in rel["pool_transitions"][:15]:
                print(f"    pool {t['from']} -> {t['to']}: {t['blocks']:,}")
    print(f"  {ATTRIBUTION.relative_to(ROOT)}: {len(df):,} blocks (0-{h[-1]:,}) in {time.time() - t0:.0f}s; "
          f"methods {df['method'].value_counts().to_dict()}")
    write_dashboard(df, registry)
    facts = build_pool_facts(df, registry, slug_to_name)
    write_pool_facts(facts)
    print(f"  dashboard/data/lookup/pool_facts.json: {len(facts['pools'])} pools")
    return 0


if __name__ == "__main__":
    sys.exit(main())
