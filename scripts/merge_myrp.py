"""
merge_myrp.py
Step 2 of the data pipeline. Feeds recent block identity data into
blocks_post_2021.parquet from two sources, in priority order:

  1. bitcoin_miners_myrp.parquet  — pre-resolved pool slugs, high accuracy
                                    but only covers up to its last update date
  2. bitcoin_blocks_pool.parquet  — has today's data; pool resolved via
                                    coinbase_tag matching against the enriched
                                    pools lookup (pools.json + pools_supplement.json)

For any block height that appears in both myrp and bp, myrp wins (it uses
off-chain attribution that can identify pools whose coinbase tags are absent or
ambiguous). Blocks beyond myrp's max height are resolved from bp only.

Delegates lookup generation to build_pools_lookup.py so pool/slug logic
lives in one place.
"""

import sys
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path

ROOT = Path(__file__).parent.parent
RAW = ROOT / "data" / "raw"
DASHBOARD_DATA = ROOT / "dashboard" / "data"

# Make build_pools_lookup importable from the same scripts/ directory
sys.path.insert(0, str(Path(__file__).parent))
from build_pools_lookup import build as build_lookup, to_slug


# ---------------------------------------------------------------------------
# Pool resolver: coinbase_tag string → canonical slug
# Uses the merged coinbase_tags from pools_enriched.json.
# ---------------------------------------------------------------------------
def make_resolver(enriched: dict):
    """Return a function (coinbase_tag: str) -> slug|'unknown'."""
    tags = enriched.get("coinbase_tags", {})
    sorted_tags = sorted(tags.items(), key=lambda x: len(x[0]), reverse=True)

    def resolve(coinbase_tag) -> str:
        if not coinbase_tag or (isinstance(coinbase_tag, float)):
            return "unknown"
        tag_str = str(coinbase_tag)
        for tag_key, info in sorted_tags:
            if tag_key in tag_str:
                return to_slug(info["name"])
        return "unknown"

    return resolve


POST_2021_HEIGHT = 664_063  # first block of 2021


def main():
    rebuild = "--rebuild" in sys.argv

    # -------------------------------------------------------------------------
    # 0. Build enriched lookup — single source of truth for pool/slug mapping
    # -------------------------------------------------------------------------
    print("Building enriched pools lookup ...")
    enriched, _slug_to_name, slug_aliases, supplement_overrides, _pool_types = build_lookup()

    resolve_from_tag = make_resolver(enriched)

    # -------------------------------------------------------------------------
    # 1. Base: existing blocks_post_2021.parquet (from prepare_data.py)
    #    Skipped when --rebuild is passed; the full bp.parquet becomes the base.
    # -------------------------------------------------------------------------
    post_path = DASHBOARD_DATA / "blocks_post_2021.parquet"
    if rebuild or not post_path.exists():
        if rebuild:
            print("\n--rebuild: skipping existing blocks_post_2021.parquet; "
                  "will re-resolve all blocks from source")
        else:
            print("\nblocks_post_2021.parquet not found; will build from scratch")
        df_post = pd.DataFrame(columns=["height", "pool_slug", "date"])
    else:
        print("\nLoading existing blocks_post_2021.parquet ...")
        df_post = pd.read_parquet(post_path)
        df_post["pool_slug"] = df_post["pool_slug"].apply(to_slug)
        # Apply aliases retroactively to fix slugs written by older pipeline runs
        df_post["pool_slug"] = df_post["pool_slug"].replace(slug_aliases)
        print(f"  {len(df_post):,} blocks  "
              f"(heights {df_post['height'].min()} – {df_post['height'].max()})")

    # -------------------------------------------------------------------------
    # 2. bitcoin_miners_myrp.parquet — high-accuracy, up to myrp's last date
    # -------------------------------------------------------------------------
    print("\nLoading bitcoin_miners_myrp.parquet ...")
    miners_p = Path("/data/bitcoin/data/bitcoin_miners.parquet")
    if not miners_p.exists(): miners_p = RAW / "bitcoin_miners_myrp.parquet"
    df_myrp = pd.read_parquet(miners_p)
    df_myrp = df_myrp.rename(columns={
        "block_height": "height",
        "mining_pool":  "pool_slug",
        "timestamp":    "date",
    })[["height", "pool_slug", "date"]]

    # Normalize myrp slugs and apply aliases (e.g. slushpool → braiinspool)
    df_myrp["pool_slug"] = df_myrp["pool_slug"].apply(to_slug)
    df_myrp["pool_slug"] = df_myrp["pool_slug"].replace(slug_aliases)

    myrp_max_height = int(df_myrp["height"].max())
    print(f"  {len(df_myrp):,} blocks  "
          f"(heights {df_myrp['height'].min()} – {myrp_max_height})")

    # -------------------------------------------------------------------------
    # 3. bitcoin_blocks_pool.parquet — has data through today
    #    Normal mode:  append only blocks beyond the current frontier.
    #    Rebuild mode: re-resolve ALL post-2021 blocks from coinbase_tag.
    # -------------------------------------------------------------------------
    post_max_height = int(df_post["height"].max()) if len(df_post) else 0
    bp_cutoff = max(post_max_height, myrp_max_height) if not rebuild else (POST_2021_HEIGHT - 1)

    bp_path = RAW / "bitcoin_blocks_pool.parquet"
    if bp_path.exists():
        print("\nLoading bitcoin_blocks_pool.parquet ...")
        df_bp = pd.read_parquet(bp_path, columns=["block_height", "coinbase_tag", "block_time"])
        df_bp = df_bp.rename(columns={"block_height": "height", "block_time": "date"})
    else:
        df_bp = pd.DataFrame(columns=["height", "coinbase_tag", "date"])
    df_bp["pool_slug"] = df_bp["coinbase_tag"].apply(resolve_from_tag)
    df_bp = df_bp[["height", "pool_slug", "date"]]

    # Slice bp to only the blocks we need
    df_bp_new = df_bp[df_bp["height"] > bp_cutoff].copy()
    if len(df_bp_new):
        resolved_new = (df_bp_new["pool_slug"] != "unknown").sum()
        print(f"  {'Blocks to process' if rebuild else 'New blocks to append'} "
              f"(height > {bp_cutoff}): {len(df_bp_new):,} "
              f"({df_bp_new['height'].min()} – {df_bp_new['height'].max()})")
        print(f"  Resolved pool in these blocks: {resolved_new:,} / {len(df_bp_new):,} "
              f"({resolved_new / len(df_bp_new) * 100:.1f}%)")
    else:
        print(f"  blocks_post_2021 is already up to date (max height {post_max_height})")

    # -------------------------------------------------------------------------
    # 4. Also check if myrp has new blocks beyond blocks_post_2021's current max
    # -------------------------------------------------------------------------
    df_myrp_new = df_myrp[df_myrp["height"] > post_max_height].copy() if not rebuild else df_myrp.copy()
    if len(df_myrp_new):
        print(f"\n  myrp has {len(df_myrp_new):,} blocks {'(full range, rebuild)' if rebuild else f'beyond post_max ({post_max_height})'}: "
              f"heights {df_myrp_new['height'].min()} – {df_myrp_new['height'].max()}")

    # -------------------------------------------------------------------------
    # 5. Merge — concat in priority order (last wins on dedup):
    #      df_post (current state)
    #      < df_bp_new (coinbase-tag resolved, beyond both myrp and post frontiers)
    #      < df_myrp_new (high-accuracy off-chain attribution, beyond post frontier)
    #    myrp_new beats bp_new for any overlap since it's added last.
    #    Exceptions:
    #      a) myrp "unknown" blocks: bp wins (any attribution > no attribution)
    #      b) supplement_overrides: a specific supplement slug (e.g. braiinssolo)
    #         beats a more generic myrp slug (e.g. ckpool) — defined in
    #         data/raw/pools_supplement.json under "supplement_overrides".
    # -------------------------------------------------------------------------

    # Build reverse lookup: myrp_slug -> set of bp slugs that beat it
    # e.g. {"ckpool": {"braiinssolo", "noderunners"}, "unknown": {"publicpool", ...}}
    myrp_overrideable: dict[str, set] = {}
    for bp_slug, myrp_slugs in supplement_overrides.items():
        for ms in myrp_slugs:
            myrp_overrideable.setdefault(ms, set()).add(bp_slug)

    # Remove myrp rows that can be overridden by bp's more specific resolution:
    #   a) myrp_slug == "unknown" → bp always wins
    #   b) myrp_slug in overrideable AND the corresponding bp block resolves to
    #      one of the override slugs
    if len(myrp_overrideable) and len(df_bp_new) and len(df_myrp_new):
        bp_slug_map = df_bp_new.set_index("height")["pool_slug"]
        def should_bp_win(row):
            ms = row["pool_slug"]
            if ms == "unknown":
                return True
            overrides = myrp_overrideable.get(ms, set())
            if overrides:
                bp_s = bp_slug_map.get(row["height"])
                return bp_s in overrides
            return False
        mask_bp_wins = df_myrp_new.apply(should_bp_win, axis=1)
        n_overridden = mask_bp_wins.sum()
        if n_overridden:
            print(f"  Supplement overrides: bp resolution wins for {n_overridden} myrp blocks")
        df_myrp_new = df_myrp_new[~mask_bp_wins]

    print("\nMerging all sources ...")
    df_merged = pd.concat([df_post, df_bp_new, df_myrp_new], ignore_index=True)
    df_merged = (
        df_merged
        .drop_duplicates(subset=["height"], keep="last")
        .sort_values("height")
        .reset_index(drop=True)
    )
    print(f"  Final blocks_post_2021: {len(df_merged):,}  "
          f"(heights {df_merged['height'].min()} – {df_merged['height'].max()})")

    # -------------------------------------------------------------------------
    # 5. Write blocks_post_2021.parquet
    # -------------------------------------------------------------------------
    out_path = DASHBOARD_DATA / "blocks_post_2021.parquet"
    print(f"\nWriting {out_path} ...")
    table = pa.Table.from_pandas(df_merged, preserve_index=False)
    pq.write_table(
        table,
        out_path,
        compression="snappy",
        use_dictionary=["pool_slug"],
        write_statistics=True,
    )
    print(f"  Done — {out_path.stat().st_size / 1_048_576:.2f} MB")


if __name__ == "__main__":
    main()