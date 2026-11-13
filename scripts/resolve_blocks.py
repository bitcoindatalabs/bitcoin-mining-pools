"""
resolve_blocks.py
Labels every block with its mining pool using the one resolver (pool_resolver.py) and writes:

  data/processed/block_attribution.parquet   every height in data/raw/coinbase_blocks.parquet
      height, time, pool_slug, method, coinbase_tag, jlopp_slug, tag_slug, payout_slug, generic_slug
      (schema metadata: registry_version, sources)
  dashboard/data/blocks_pre_2021.parquet     height < 664,063   (height, pool_slug, date)
  dashboard/data/blocks_post_2021.parquet    height >= 664,063  (height, pool_slug, date)

Inputs:
  data/raw/coinbase_blocks.parquet  from extract_coinbase.py (coinbase scriptSig + payout scripts per block)
  dashboard/data/lookup/pools_enriched.json  the registry, rebuilt here by build_pools_lookup.py
  data/raw/blocks.csv               jlopp/bitcoin-blocks-by-mining-pool labels, heights 0-869,305. FROZEN: never
                                    refreshed (owner decision 2026-11-12); used only as precedence rule 3.

method: tag | regex | payout | jlopp | unknown (see pool_resolver.py for the precedence).

By default only heights above the existing attribution file are resolved, unless the registry_version changed
(then every block is re-resolved, ~1 minute) or --full is passed.

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
POST_2021_HEIGHT = 664_063

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_pools_lookup import build as build_registry  # noqa: E402
from pool_resolver import PoolResolver  # noqa: E402

COLUMNS = ["height", "time", "pool_slug", "method", "coinbase_tag", "jlopp_slug", "tag_slug", "payout_slug",
           "generic_slug"]

_RESOLVER = None


def _init(registry):
    global _RESOLVER
    _RESOLVER = PoolResolver(registry)


def _resolve_chunk(args):
    heights, times, sigs, payouts, jlopp = args
    out = []
    for h, t, sig, pay, jl in zip(heights, times, sigs, payouts, jlopp):
        a = _RESOLVER.resolve(sig, pay, jl)
        out.append((h, t, a.slug, a.method, a.tag, _RESOLVER.slug(jl) if jl else None, a.tag_slug, a.payout_slug,
                    a.generic_slug))
    return out


def load_jlopp() -> pd.Series:
    jl = pd.read_csv(JLOPP, usecols=["height", "pool_slug"], dtype={"height": "int64", "pool_slug": "str"})
    jl = jl[jl["height"] <= JLOPP_MAX_HEIGHT]
    # blocks.csv repeats 10 rows (860,579-860,588) verbatim; keep one per height
    jl = jl.drop_duplicates(subset=["height", "pool_slug"])
    if jl["height"].duplicated().any():
        raise ValueError("blocks.csv has conflicting labels for one height")
    return jl.set_index("height")["pool_slug"].fillna("unknown")


def resolve(cb: pd.DataFrame, registry: dict, workers: int) -> pd.DataFrame:
    jl = load_jlopp()
    jlopp = cb["height"].map(jl).where(lambda s: s.notna(), None).tolist()
    n = len(cb)
    step = max(1, -(-n // (workers * 8)))
    chunks = [(cb["height"].iloc[i:i + step].tolist(), cb["time"].iloc[i:i + step].tolist(),
               cb["scriptsig"].iloc[i:i + step].tolist(), cb["payout_scripts"].iloc[i:i + step].tolist(),
               jlopp[i:i + step]) for i in range(0, n, step)]
    rows = []
    if workers > 1 and n > 5000:
        with get_context("fork").Pool(workers, initializer=_init, initargs=(registry,)) as pool:
            for part in pool.imap(_resolve_chunk, chunks):
                rows.extend(part)
    else:
        _init(registry)
        for c in chunks:
            rows.extend(_resolve_chunk(c))
    return pd.DataFrame(rows, columns=COLUMNS)


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
                                   "generic_slug"])
    os.replace(tmp, ATTRIBUTION)


def write_dashboard(df: pd.DataFrame, registry: dict):
    d = pd.DataFrame({"height": df["height"].astype("int64"), "pool_slug": df["pool_slug"],
                      "date": pd.to_datetime(df["time"], unit="s", utc=True).dt.as_unit("us")})
    # height dtypes as the dashboard has always read them: int32 in the pre-2021 file, int64 in the post-2021 file
    for name, part in (("blocks_pre_2021.parquet", d[d["height"] < POST_2021_HEIGHT].astype({"height": "int32"})),
                       ("blocks_post_2021.parquet", d[d["height"] >= POST_2021_HEIGHT])):
        path = DASHBOARD_DATA / name
        tmp = path.with_suffix(".tmp.parquet")
        t = pa.Table.from_pandas(part.reset_index(drop=True), preserve_index=False)
        t = t.replace_schema_metadata({**(t.schema.metadata or {}),
                                       b"registry_version": registry["registry_version"].encode()})
        pq.write_table(t, tmp, compression="snappy", use_dictionary=["pool_slug"], write_statistics=True)
        os.replace(tmp, path)
        print(f"  {name}: {len(part):,} blocks, {(part['pool_slug'] == 'unknown').sum():,} unknown, "
              f"{path.stat().st_size / 1e6:.2f} MB")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="re-resolve every block")
    ap.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 1))
    a = ap.parse_args()

    if not COINBASE.exists():
        print(f"ERROR: {COINBASE} missing; run scripts/extract_coinbase.py first", file=sys.stderr)
        return 1
    registry, *_ = build_registry()
    version = registry["registry_version"]
    cb = pd.read_parquet(COINBASE)
    if cb.empty:
        print("ERROR: coinbase_blocks.parquet is empty", file=sys.stderr)
        return 1

    old = None
    if ATTRIBUTION.exists() and not a.full:
        old_meta = pq.read_schema(ATTRIBUTION).metadata or {}
        if old_meta.get(b"registry_version", b"").decode() == version:
            old = pd.read_parquet(ATTRIBUTION)
        else:
            print(f"registry_version changed ({old_meta.get(b'registry_version', b'-').decode()} -> {version}); "
                  f"re-resolving every block")
    todo = cb if old is None else cb[cb["height"] > old["height"].max()]
    t0 = time.time()
    print(f"Resolving {len(todo):,} blocks (registry {version}) ...")
    new = resolve(todo, registry, a.workers) if len(todo) else pd.DataFrame(columns=COLUMNS)
    df = new if old is None else pd.concat([old, new], ignore_index=True)
    df = df.sort_values("height").reset_index(drop=True)
    h = df["height"].to_numpy()
    if h[0] != 0 or not (h[1:] - h[:-1] == 1).all():
        print("ERROR: attribution heights are not contiguous from 0; refusing to write", file=sys.stderr)
        return 1
    write_attribution(df, registry)
    print(f"  {ATTRIBUTION.relative_to(ROOT)}: {len(df):,} blocks (0-{h[-1]:,}) in {time.time() - t0:.0f}s; "
          f"methods {df['method'].value_counts().to_dict()}")
    write_dashboard(df, registry)
    return 0


if __name__ == "__main__":
    sys.exit(main())
