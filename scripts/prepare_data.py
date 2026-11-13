"""
prepare_data.py (Legacy Importer: NOT part of the pipeline since bdl-060. It writes jlopp-only labels and would
overwrite the resolver's output; use resolve_blocks.py.)
Reads data/raw/blocks.csv + forref/bitcoin_blocks_metadata.parquet
Enriches blocks with real timestamp from metadata
Writes blocks_pre_2021.parquet and blocks_post_2021.parquet
"""

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path

ROOT = Path(__file__).parent.parent
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "dashboard" / "data"
PROCESSED.mkdir(parents=True, exist_ok=True)

def to_slug_canonical(s):
    if pd.isna(s) or s == "": return "unknown"
    s = str(s).lower()
    if s == "unknown": return "unknown"
    for char in [" ", "-", "_", "."]:
        s = s.replace(char, "")
    return s

def main():
    print("Loading blocks.csv ...")
    blocks = pd.read_csv(
        RAW / "blocks.csv",
        dtype={"height": "int32", "hash": "str", "pool_slug": "str"},
    )
    print(f"  {len(blocks):,} blocks loaded (heights {blocks['height'].min()} – {blocks['height'].max()})")

    print("Loading bitcoin_blocks_metadata.parquet ...")
    metadata = pd.read_parquet(ROOT / "forref" / "bitcoin_blocks_metadata.parquet", columns=["block_height", "timestamp"])
    metadata.rename(columns={"block_height": "height"}, inplace=True)

    print("Merging real timestamps ...")
    blocks = blocks.merge(metadata, on="height", how="left")
    blocks.rename(columns={"timestamp": "date"}, inplace=True)

    # Keep only necessary columns
    blocks = blocks[["height", "pool_slug", "date"]]

    print("Normalizing block slugs ...")
    blocks["pool_slug"] = blocks["pool_slug"].apply(to_slug_canonical)

    # Split blocks into pre and post 2021 based on block height (610683 was 2020, 664063 is 2021)
    pre_2021 = blocks[blocks['height'] < 664063]
    post_2021 = blocks[blocks['height'] >= 664063]

    # Write pre-2021 parquet
    pre_path = PROCESSED / "blocks_pre_2021.parquet"
    print(f"Writing {pre_path} ...")
    table_pre = pa.Table.from_pandas(pre_2021, preserve_index=False)
    pq.write_table(table_pre, pre_path, compression="snappy", use_dictionary=["pool_slug"])
    print(f"  Done — {pre_path.stat().st_size / 1_048_576:.2f} MB")

    # Write post-2021 parquet
    post_path = PROCESSED / "blocks_post_2021.parquet"
    print(f"Writing {post_path} ...")
    table_post = pa.Table.from_pandas(post_2021, preserve_index=False)
    pq.write_table(table_post, post_path, compression="snappy", use_dictionary=["pool_slug"])
    print(f"  Done — {post_path.stat().st_size / 1_048_576:.2f} MB")

    print(f"\nTotal blocks processed: {len(blocks)}")

if __name__ == "__main__":
    main()