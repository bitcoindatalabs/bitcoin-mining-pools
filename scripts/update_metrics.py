import json
import sys
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).parent.parent
DASHBOARD_DATA = ROOT / "dashboard" / "data"

sys.path.insert(0, str(Path(__file__).parent))
from build_pools_lookup import to_slug

def main():
    RAW = ROOT / "data" / "raw"
    print("Loading blocks_pre_2021.parquet and blocks_post_2021.parquet ...")
    df_pre = pd.read_parquet(DASHBOARD_DATA / "blocks_pre_2021.parquet")
    df_post = pd.read_parquet(DASHBOARD_DATA / "blocks_post_2021.parquet")
    df = pd.concat([df_pre, df_post], ignore_index=True)
    print(f"  {len(df):,} blocks loaded")

    # Convert date column to datetime
    df["date"] = pd.to_datetime(df["date"])

    # Load enriched pools lookup (built by build_pools_lookup.py)
    print("Loading enriched pools lookup ...")
    lookup_path = DASHBOARD_DATA / "lookup" / "lookup_slug_to_name.json"
    with open(lookup_path) as f:
        slug_to_name = json.load(f)

    enriched_path = DASHBOARD_DATA / "lookup" / "pools_enriched.json"
    with open(enriched_path) as f:
        enriched = json.load(f)

    name_to_link: dict[str, str] = {}
    for section in ("payout_addresses", "coinbase_tags"):
        for entry in enriched.get(section, {}).values():
            name = entry.get("name", "")
            link = entry.get("link", "")
            if name:
                name_to_link[name] = link

    pool_meta = {name: {"link": link} for name, link in name_to_link.items()}

    # bdl-063: the per-pool metrics and the ecosystem count use `pool`, the most specific operator (TrustPool apart
    # from ViaBTC), like the dashboard's pool charts. Concentration figures use host_pool (dashboard JS, forensics).
    print("Calculating pool metrics ...")
    # Calculate metrics
    known = df[df["pool"] != "unknown"]
    
    grouped = known.groupby("pool").agg(
        first_block_mined=('height', 'min'),
        first_seen_date=('date', 'min'),
        last_block_mined=('height', 'max'),
        last_seen_date=('date', 'max'),
        lifetime_blocks=('height', 'count')
    )
    
    # Last 30 days share
    max_date = df["date"].max()
    last_month_start = max_date - pd.DateOffset(days=30)
    last_month_blocks = df[df["date"] >= last_month_start]
    last_month_total = len(last_month_blocks)
    
    last_month_counts = last_month_blocks[last_month_blocks["pool"] != "unknown"].groupby("pool").size()
    last_month_share = (last_month_counts / last_month_total * 100).round(2)
    
    # Format dates
    grouped['first_seen_date'] = grouped['first_seen_date'].dt.strftime('%Y-%m-%d')
    grouped['last_seen_date'] = grouped['last_seen_date'].dt.strftime('%Y-%m-%d')
    
    # Update pool_metrics.json
    for slug, row in grouped.iterrows():
        name = slug_to_name.get(slug, slug)
        if name not in pool_meta:
            pool_meta[name] = {"link": ""}
            
        pool_meta[name]["first_block_mined"] = int(row["first_block_mined"])
        pool_meta[name]["first_seen_date"] = row["first_seen_date"]
        pool_meta[name]["last_block_mined"] = int(row["last_block_mined"])
        pool_meta[name]["last_seen_date"] = row["last_seen_date"]
        pool_meta[name]["lifetime_blocks"] = int(row["lifetime_blocks"])
        
        share = last_month_share.get(slug, 0.0)
        pool_meta[name]["last_month_share_pct"] = float(share)

    with open(DASHBOARD_DATA / "pool_metrics.json", "w") as f:
        json.dump(pool_meta, f, separators=(",", ":"))
    print(f"  Wrote pool_metrics.json with metrics for {len(grouped)} pools")

    # Ecosystem Growth
    print("Calculating global ecosystem growth ...")
    # Get YYYY-MM
    df["month_key"] = df["date"].dt.strftime('%Y-%m')
    months = sorted(df["month_key"].unique())
    
    cumulative_counts = []
    seen = set()
    month_to_pools = df.groupby('month_key')['pool'].unique()
    
    for m in months:
        if m in month_to_pools:
            for p in month_to_pools[m]:
                if p != "unknown":
                    seen.add(p)
        cumulative_counts.append(len(seen))
        
    ecosystem = {
        "months": months,
        "cumulativePools": cumulative_counts,
        # provenance: the pool list these labels come from (bdl-062)
        "registry_version": enriched.get("registry_version"),
        "pool_sources": {k: v.get("sha") or v.get("md5") for k, v in enriched.get("sources", {}).items()},
    }
    with open(DASHBOARD_DATA / "pool_growth.json", "w") as f:
        json.dump(ecosystem, f, separators=(",", ":"))
    print(f"  Wrote pool_growth.json with {len(months)} months")

    print("Metrics update completed!")

if __name__ == "__main__":
    main()