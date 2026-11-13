"""
extract_coinbase.py
Copies the inputs that pool attribution needs out of a local chain lake into one local file:

  data/raw/coinbase_blocks.parquet   (gitignored; about 1 row per block)
    height          int32
    time            int64    block header time (unix seconds)
    scriptsig       binary   coinbase input scriptSig, raw bytes
    payout_scripts  list<binary>  coinbase output scriptPubKeys in vout order, OP_RETURN outputs dropped

The chain lake is a directory of 1,000-block parquet parts (blocks_<lo>_<hi>.parquet with coinbase_scriptsig,
outputs_<lo>_<hi>.parquet with tx_key = height << 15 | tx_index). It is produced on datalabs by
python/automation/bitcoin_chain_extractor.py; pass its location with --chain-parts or $CHAIN_PARTS_DIR.

Only complete parts are read: both files present and neither modified in the last --settle-minutes (the nightly
extractor rewrites the tip part around 21:05 America/Chicago). Existing rows are kept; only heights above the
current maximum are appended, unless --full.

Usage:
  python3 scripts/extract_coinbase.py [--chain-parts DIR] [--full] [--max-height H]
"""

import argparse
import os
import re
import sys
import time
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "raw" / "coinbase_blocks.parquet"
DEFAULT_PARTS = os.environ.get("CHAIN_PARTS_DIR", "/data/bitcoin/data/chain/parts")

SCHEMA = pa.schema([
    ("height", pa.int32()),
    ("time", pa.int64()),
    ("scriptsig", pa.binary()),
    ("payout_scripts", pa.list_(pa.binary())),
])


def complete_parts(parts_dir: Path, settle_minutes: float):
    """[(lo, hi, blocks_file, outputs_file)] sorted by lo, for parts whose two files exist and have settled."""
    now = time.time()
    out = []
    for f in parts_dir.glob("blocks_*.parquet"):
        m = re.fullmatch(r"blocks_(\d+)_(\d+)\.parquet", f.name)
        if not m:
            continue
        lo, hi = int(m.group(1)), int(m.group(2))
        of = parts_dir / f"outputs_{lo}_{hi}.parquet"
        if not of.exists():
            continue
        if now - max(f.stat().st_mtime, of.stat().st_mtime) < settle_minutes * 60:
            print(f"  skipping part {lo}-{hi}: modified in the last {settle_minutes} minutes")
            continue
        out.append((lo, hi, str(f), str(of)))
    return sorted(out)


def extract(parts, start: int, max_height: int | None, batch: int = 40) -> pa.Table:
    con = duckdb.connect()
    con.execute("SET threads=8")
    tables = []
    todo = [p for p in parts if p[1] >= start and (max_height is None or p[0] <= max_height)]
    hi_cap = max_height if max_height is not None else 2**31 - 1
    for i in range(0, len(todo), batch):
        chunk = todo[i:i + batch]
        bfiles = [p[2] for p in chunk]
        ofiles = [p[3] for p in chunk]
        t = con.sql(f"""
            WITH b AS (
                SELECT height, time, coinbase_scriptsig AS scriptsig
                FROM read_parquet({bfiles})
                WHERE height >= {start} AND height <= {hi_cap}
            ),
            o AS (
                SELECT height, list(script ORDER BY vout) AS payout_scripts
                FROM read_parquet({ofiles})
                WHERE tx_key = (CAST(height AS BIGINT) << 15)
                  AND height >= {start} AND height <= {hi_cap}
                  AND script IS NOT NULL AND octet_length(script) > 0
                  AND script_type <> 'op_return'
                GROUP BY height
            )
            SELECT b.height::INT AS height, b.time::BIGINT AS time, b.scriptsig,
                   coalesce(o.payout_scripts, []::BLOB[]) AS payout_scripts
            FROM b LEFT JOIN o USING (height)
            ORDER BY b.height
        """).to_arrow_table()
        tables.append(t.cast(SCHEMA))
        print(f"  parts {chunk[0][0]:,}-{chunk[-1][1]:,}: {t.num_rows:,} blocks")
    return pa.concat_tables(tables) if tables else SCHEMA.empty_table()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--chain-parts", default=DEFAULT_PARTS)
    ap.add_argument("--full", action="store_true", help="re-extract from height 0")
    ap.add_argument("--max-height", type=int, default=None)
    ap.add_argument("--settle-minutes", type=float, default=15)
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()

    out = Path(a.out)
    parts_dir = Path(a.chain_parts)
    if not parts_dir.is_dir():
        print(f"ERROR: chain parts directory not found: {parts_dir}", file=sys.stderr)
        return 1
    existing = None
    start = 0
    if out.exists() and not a.full:
        existing = pq.read_table(out)
        if existing.num_rows:
            start = int(pa.compute.max(existing["height"]).as_py()) + 1
    parts = complete_parts(parts_dir, a.settle_minutes)
    if not parts:
        print("ERROR: no complete chain parts found", file=sys.stderr)
        return 1
    print(f"Extracting coinbase data from height {start:,} ({len(parts)} complete parts in {parts_dir}) ...")
    t0 = time.time()
    new = extract(parts, start, a.max_height)
    if new.num_rows == 0:
        print("Nothing new to extract.")
        return 0
    table = pa.concat_tables([existing, new]) if existing is not None else new
    h = table["height"].to_numpy()
    if not (h[0] == 0 or existing is not None) or (len(h) > 1 and not (h[1:] - h[:-1] == 1).all()):
        print("ERROR: extracted heights are not contiguous; refusing to write", file=sys.stderr)
        return 1
    tmp = out.with_suffix(".tmp.parquet")
    pq.write_table(table, tmp, compression="zstd")
    os.replace(tmp, out)
    print(f"Wrote {out} : {table.num_rows:,} blocks, heights {h[0]:,}-{h[-1]:,} "
          f"({out.stat().st_size / 1e6:.1f} MB, {time.time() - t0:.0f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
