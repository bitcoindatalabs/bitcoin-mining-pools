import sys
import pandas as pd
import numpy as np
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent
RAW = ROOT / "data" / "raw"
DASHBOARD_DATA = ROOT / "dashboard" / "data"

def registry_provenance() -> dict:
    """registry_version and source pins of the pool list behind the labels (bdl-062)."""
    try:
        reg = json.loads((DASHBOARD_DATA / "lookup" / "pools_enriched.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {"registry_version": reg.get("registry_version"),
            "pool_sources": {k: v.get("sha") or v.get("md5") for k, v in reg.get("sources", {}).items()}}


def main():
    print("Loading datasets for synchronization...")
    # 1. Load Main Dashboard Data (The "Identity" Source)
    df_main = pd.read_parquet(DASHBOARD_DATA / "blocks_post_2021.parquet")
    
    # 2. Load Raw Forensics Data (The "Metric" Source)
    raw_bp_file = RAW / "bitcoin_blocks_pool.parquet"
    if raw_bp_file.exists():
        df_raw = pd.read_parquet(raw_bp_file)
    else:
        print("Loading metrics from bitcoin_blocks_metadata and chain lake parts ...")
        meta_path = Path("/data/Lightning/Data/parquet/bitcoin_blocks_metadata.parquet")
        df_meta = pd.read_parquet(meta_path)
        df_meta = df_meta[df_meta["block_height"] >= 664063].copy()
        df_meta = df_meta.rename(columns={
            "size": "bytes_total",
            "weight": "block_weight",
            "transaction_count": "tx_count",
            "stripped_size": "bytes_stripped"
        })
        df_meta["block_time"] = pd.to_datetime(df_meta["timestamp"]).astype("int64") // 10**6

        import glob, os, re
        chain_parts = "/data/bitcoin/data/chain/parts"
        b_files = sorted(
            glob.glob(os.path.join(chain_parts, "blocks_*.parquet")),
            key=lambda f: [int(x) for x in re.findall(r"\d+", os.path.basename(f))]
        )
        target_files = [f for f in b_files if [int(x) for x in re.findall(r"\d+", os.path.basename(f))][1] >= 664063]
        dfs = [pd.read_parquet(f, columns=["height", "version"]) for f in target_files]
        df_ver = pd.concat(dfs, ignore_index=True)
        df_ver = df_ver[df_ver["height"] >= 664063]

        df_raw = pd.merge(df_meta, df_ver, left_on="block_height", right_on="height", how="left")
        df_raw["protocol_version"] = df_raw["version"].fillna(0x20000000).astype("int64")

    # Check if df_main has heights beyond df_raw
    missing_h = set(df_main["height"]) - set(df_raw["block_height"])
    if missing_h:
        print(f"Resolving {len(missing_h)} missing blocks locally from bitcoin_blocks_metadata.parquet ...")
        meta_path = Path("/data/Lightning/Data/parquet/bitcoin_blocks_metadata.parquet")
        if meta_path.exists():
            df_meta = pd.read_parquet(meta_path)
            df_m = df_meta[df_meta["block_height"].isin(missing_h)].copy()
            if not df_m.empty:
                df_m = df_m.rename(columns={
                    "size": "bytes_total",
                    "weight": "block_weight",
                    "transaction_count": "tx_count",
                    "stripped_size": "bytes_stripped"
                })
                df_m["block_time"] = pd.to_datetime(df_m["timestamp"]).astype("int64") // 10**6
                df_m["protocol_version"] = 0x20000000
                df_raw = pd.concat([df_raw, df_m], ignore_index=True)
                missing_h = set(df_main["height"]) - set(df_raw["block_height"])

        if missing_h:
            print(f"Fetching remaining {len(missing_h)} tip blocks metadata via RPC fallback ...")
            import sys
            sys.path.insert(0, "/home/sorukumar/dev/python/automation")
            from closed_channel_engine import load_env_credentials
            import requests
            _rpc = load_env_credentials()
            url = f"http://{_rpc["BITCOIN_RPC_HOST"]}:{_rpc["BITCOIN_RPC_PORT"]}/"
            auth = (_rpc["BITCOIN_RPC_USER"], _rpc["BITCOIN_RPC_PASSWORD"])
            rpc_rows = []
            for h in sorted(missing_h):
                res_hash = requests.post(url, auth=auth, json={"method": "getblockhash", "params": [h], "id": h}).json()["result"]
                res_blk = requests.post(url, auth=auth, json={"method": "getblock", "params": [res_hash, 1], "id": h}).json()["result"]
                rpc_rows.append({
                    "block_height": h,
                    "bytes_total": res_blk.get("size", 0),
                    "block_weight": res_blk.get("weight", 0),
                    "tx_count": res_blk.get("nTx", 0),
                    "block_time": res_blk.get("time", 0),
                    "protocol_version": res_blk.get("version", 0x20000000),
                    "bytes_stripped": res_blk.get("strippedsize", 0)
                })
            df_raw = pd.concat([df_raw, pd.DataFrame(rpc_rows)], ignore_index=True)
    
    # 3. Join on Height to ensure 100% consistency with main dashboard
    print("Joining datasets on block height ...")
    df = pd.merge(
        df_main, 
        df_raw[['block_height', 'bytes_total', 'block_weight', 'tx_count', 'block_time', 'protocol_version', 'bytes_stripped']], 
        left_on='height', 
        right_on='block_height', 
        how='inner'
    )
    
    # Use pool_slug as the primary pool identifier
    df['pool_name'] = df['pool_slug']
    
    # 2. Add Datetime
    df['timestamp'] = pd.to_datetime(df['block_time'], unit='s')
    
    # Filter to start from January 2021 as requested
    df = df[df['timestamp'] >= '2021-01-01'].copy()
    
    # KPI 1: Consecutive Strikes
    print("KPI 1: Consecutive Strikes Analysis...")
    df['prev_pool'] = df['pool_name'].shift(1)
    df['strike_id'] = (df['pool_name'] != df['prev_pool']).cumsum()
    
    # Calculate Pool Shares for the entire period baseline
    pool_counts = df['pool_name'].value_counts()
    total_blocks = len(df)
    pool_shares = (pool_counts / total_blocks).to_dict()

    # Build monthly share lookup for block-weighted per-event analysis
    print("  Building monthly share lookup (block-weighted baselines)...")
    df['month'] = df['timestamp'].dt.to_period('M')
    df['quarter'] = df['timestamp'].dt.to_period('Q')
    _monthly_counts = df.groupby(['month', 'pool_name']).size().reset_index(name='_pool_blocks')
    _monthly_totals = df.groupby('month').size().reset_index(name='_total_blocks_month')
    _monthly_merged = _monthly_counts.merge(_monthly_totals, on='month')
    _monthly_merged['_share'] = _monthly_merged['_pool_blocks'] / _monthly_merged['_total_blocks_month']
    monthly_share_lookup = {
        (row['month'], row['pool_name']): row['_share']
        for _, row in _monthly_merged.iterrows()
    }

    strikes = df.groupby('strike_id').agg({
        'pool_name': 'first',
        'block_height': ['min', 'max', 'count'],
        'timestamp': ['min', 'max']
    })
    strikes.columns = ['pool', 'start_height', 'end_height', 'count', 'start_time', 'end_time']
    strikes['duration_sec'] = (strikes['end_time'] - strikes['start_time']).dt.total_seconds()
    
    # Filter for streaks >= 7
    strikes_filtered = strikes[strikes['count'] >= 7].sort_values(['count', 'start_time'], ascending=[False, False])
    
    def get_propensity_score(pool, length):
        p = pool_shares.get(pool, 0)
        if p <= 0 or p >= 1: return 0
        expected_n = total_blocks * (p**length) * (1-p)
        actual_n = strikes[(strikes['pool'] == pool) & (strikes['count'] >= length)].shape[0]
        return round(actual_n / expected_n, 2) if expected_n > 0 else 0

    # Group by Pool to get Pool-Level metrics
    pool_summaries = []
    top_pools_by_hashrate = list(pool_shares.keys())[:15] # Analyze top 15 pools

    for pool in top_pools_by_hashrate:
        p_strikes = strikes_filtered[strikes_filtered['pool'] == pool]
        if len(p_strikes) == 0: continue
        
        counts_dist = {str(k): int(v) for k, v in p_strikes['count'].value_counts().sort_index(ascending=False).to_dict().items()}
        max_n = int(p_strikes['count'].max())
        
        # Era block-weighted share: pool's share from its first streak month onward
        _era_start_month = p_strikes['start_time'].min().to_period('M')
        _era_months = _monthly_merged[
            (_monthly_merged['pool_name'] == pool) &
            (_monthly_merged['month'] >= _era_start_month)
        ]
        if len(_era_months) > 0:
            era_bw_share = _era_months['_pool_blocks'].sum() / _era_months['_total_blocks_month'].sum()
            era_total_blocks = int(_era_months['_total_blocks_month'].sum())
        else:
            era_bw_share = pool_shares.get(pool, 0)
            era_total_blocks = total_blocks
        expected_7plus = era_total_blocks * (era_bw_share**7) * (1 - era_bw_share)
        actual_7plus = len(p_strikes)
        propensity_base = round(actual_7plus / expected_7plus, 2) if expected_7plus > 0 else 1.0

        # Streak events for this pool, converted for JSON
        events = p_strikes.sort_values(['count', 'start_time'], ascending=[False, False]).to_dict(orient='records')
        for ev in events:
            ev['pool'] = str(ev['pool'])
            ev['start_time'] = ev['start_time'].isoformat()
            ev['end_time'] = ev['end_time'].isoformat()
            ev['start_height'] = int(ev['start_height'])
            ev['end_height'] = int(ev['end_height'])
            ev['count'] = int(ev['count'])
            ev['duration_sec'] = float(ev['duration_sec']) if not pd.isna(ev['duration_sec']) else 0

            # Use monthly share at time of event for correct per-event expected values
            _ev_month = pd.Timestamp(ev['start_time']).to_period('M')
            p = monthly_share_lookup.get((_ev_month, pool), pool_shares.get(pool, 0))
            n = int(ev['count'])
            ev['pool_share'] = round(p * 100, 2)
            if p > 0 and p < 1:
                prob_start = (p**n) * (1 - p)
                years = round(1 / (prob_start * 144 * 365.25), 2)
                ev['expected_1_in_years'] = min(years, 999.0)
                # Propensity: era block-weighted baseline for this streak length
                expected_this_n = era_total_blocks * (era_bw_share**n) * (1 - era_bw_share)
                actual_this_n = strikes[(strikes['pool'] == pool) & (strikes['count'] >= n)].shape[0]
                ev['propensity_score'] = round(actual_this_n / expected_this_n, 2) if expected_this_n > 0 else 1.0
            else:
                ev['expected_1_in_years'] = 0
                ev['propensity_score'] = 1.0

        pool_summaries.append({
            "pool": str(pool),
            "total_events": int(len(p_strikes)),
            "max_streak": max_n,
            "pool_share": round(era_bw_share * 100, 2),  # era block-weighted share
            "propensity": propensity_base,
            "distribution": counts_dist,
            "events": events
        })

    # Sort pools by total events
    pool_summaries = sorted(pool_summaries, key=lambda x: x['total_events'], reverse=True)
    leaderboard_json = pool_summaries

    # KPI 2: Z-Score Funnel (Hidden Hashrate)
    # Observed: counts in last 144 blocks
    # Expected: share in last 2016 blocks
    print("KPI 2: Z-Score Funnel Analysis...")
    
    # We'll slide every 144 blocks to get a series of snapshots
    funnel_data = []
    
    # Only analyze pools with significant share in the last 2016 blocks (> 1%)
    # Let's take the most recent 20,000 blocks and slide markers
    window_baseline = 2016
    window_observed = 144
    
    # We calculate state at the tip and a few historical points for the dashboard
    # Let's just do it for the most recent 10 checkpoints (every 144 blocks)
    for i in range(0, 144 * 10, 144):
        tip_idx = len(df) - 1 - i
        # Need room for both the observed window AND the non-overlapping baseline before it
        if tip_idx < window_baseline + window_observed: break
        
        obs_start = tip_idx - window_observed + 1
        base_start = obs_start - window_baseline  # baseline ends where observed begins
        
        obs_df = df.iloc[obs_start:tip_idx+1]
        base_df = df.iloc[base_start:obs_start]  # non-overlapping with observed window
        
        base_counts = base_df['pool_name'].value_counts()
        base_shares = base_counts / len(base_df)  # use actual length, not hardcoded constant
        
        obs_counts = obs_df['pool_name'].value_counts()
        
        timestamp = df.iloc[tip_idx]['timestamp'].isoformat()
        
        for pool, share in base_shares.items():
            if pool == "Unknown" or share < 0.01: continue
            
            O = obs_counts.get(pool, 0)
            E = window_observed * share
            Z = (O - E) / np.sqrt(E) if E > 0 else 0
            
            # Luck % = (Observed / Expected) * 100
            luck = (O / E * 100) if E > 0 else 0
            
            funnel_data.append({
                "pool": pool,
                "share": round(share * 100, 2),
                "luck": round(luck, 2),
                "z": round(Z, 2),
                "blocks": int(O),
                "timestamp": timestamp
            })

    # KPI 3: Hashrate Entropy Heatmap (CV)
    print("KPI 3: Hashrate Entropy Heatmap...")
    df['time_delta'] = df['timestamp'].diff().dt.total_seconds()
    
    # Group by Pool and Week (7-day windows)
    # We use resample on timestamp
    entropy_data = []
    
    # Filter for pools with > 1% hashrate OVERALL to keep heatmap/charts clean
    top_pools = df['pool_name'].value_counts(normalize=True)
    top_pools = top_pools[top_pools > 0.01].index.tolist()
    if "Unknown" in top_pools: top_pools.remove("Unknown")

    # For lookup-table metrics (kpi5 empty blocks & kpi6 density) we include every
    # identified pool — no hashrate threshold. The table already controls which pools
    # are visible based on the active time range, and the loop's own `< 50 blocks`
    # guard filters out truly tiny/noisy pools. "Unknown" is excluded as it doesn't
    # map to a real entity.
    extended_pools = [p for p in df['pool_name'].unique().tolist() if p != "Unknown"]
    
    weekly_stats = df[df['pool_name'].isin(top_pools)].copy()
    weekly_stats.set_index('timestamp', inplace=True)
    
    for pool in top_pools:
        p_df = weekly_stats[weekly_stats['pool_name'] == pool]['time_delta']
        # 7-day rolling statistics
        resampled = p_df.resample('7D').agg(['std', 'mean', 'count'])
        resampled['cv'] = resampled['std'] / resampled['mean']
        
        for date, row in resampled.iterrows():
            if pd.isna(row['cv']) or row['count'] < 10: continue
            entropy_data.append({
                "date": date.strftime('%Y-%m-%d'),
                "pool": pool,
                "cv": round(row['cv'], 3),
                "blocks": int(row['count'])
            })

    # KPI 4: Mempool Synchronization Index
    print("KPI 4: Mempool Synchronization Analysis...")
    
    # Define Empty Blocks: Primary forensic indicator of Header-First mining
    df['is_empty'] = df['tx_count'] == 1
    
    # Blocks where prev_pool == pool (Consecutive blocks)
    df['is_strike'] = df['pool_name'] == df['prev_pool']
    sync_df = df[df['is_strike']].copy()
    
    sync_stats = []
    for pool in top_pools:
        p_df_full = df[df['pool_name'] == pool]
        # Exclude negative time_delta values: Bitcoin timestamps allow slight backward drift
        # which produces spurious sub-30s hits unrelated to spy-mining behaviour
        p_sync_pool = sync_df[(sync_df['pool_name'] == pool) & (sync_df['time_delta'] >= 0)]
        p_deltas = p_sync_pool['time_delta']
        if len(p_deltas) < 50: continue
        
        buckets = {
            "sub_30s": int((p_deltas < 30).sum()),
            "sub_60s": int(((p_deltas >= 30) & (p_deltas < 60)).sum()),
            "sub_2m": int(((p_deltas >= 60) & (p_deltas < 120)).sum()),
            "sub_5m": int(((p_deltas >= 120) & (p_deltas < 300)).sum()),
            "slow": int((p_deltas >= 300).sum())
        }

        # Count empty consecutive blocks in those same time-frames
        buckets_empty = {
            "sub_30s": int(((p_deltas < 30) & p_sync_pool['is_empty']).sum()),
            "sub_60s": int(((p_deltas >= 30) & (p_deltas < 60) & p_sync_pool['is_empty']).sum()),
            "sub_2m": int(((p_deltas >= 60) & (p_deltas < 120) & p_sync_pool['is_empty']).sum()),
            "sub_5m": int(((p_deltas >= 120) & (p_deltas < 300) & p_sync_pool['is_empty']).sum()),
            "slow": int(((p_deltas >= 300) & p_sync_pool['is_empty']).sum())
        }
        
        # Block-weighted expected consecutive pairs = sum_m(pool_blocks_m * monthly_share_m)
        _pool_monthly = _monthly_merged[_monthly_merged['pool_name'] == pool].copy()
        _expected_consec = float((_pool_monthly['_pool_blocks'] * _pool_monthly['_share']).sum())

        # Per-month lift data for temporal analysis
        _monthly_lift_rows = []
        for _, _mrow in _pool_monthly.iterrows():
            _m_pool_blk = int(_mrow['_pool_blocks'])
            if _m_pool_blk < 10:
                continue
            _m_share = float(_mrow['_share'])
            _m_consec = int(sync_df[
                (sync_df['pool_name'] == pool) &
                (sync_df['month'] == _mrow['month']) &
                (sync_df['time_delta'] >= 0)
            ].shape[0])
            _m_expected = _m_pool_blk * _m_share
            _m_lift = round(_m_consec / _m_expected, 3) if _m_expected > 0 else None
            _monthly_lift_rows.append({
                "month": str(_mrow['month']),
                "pool_blocks": _m_pool_blk,
                "monthly_share": round(_m_share * 100, 2),
                "consec_pairs": _m_consec,
                "expected_consec": round(_m_expected, 2),
                "lift": _m_lift
            })

        # Task 1: consec_timing — median inter-block time for consecutive same-pool pairs
        total_pairs = len(p_deltas)
        _median_delta = float(p_deltas.median())
        _pct_sub30 = round(float((p_deltas < 30).sum() / total_pairs * 100), 2) if total_pairs > 0 else 0.0
        _pct_sub60 = round(float((p_deltas < 60).sum() / total_pairs * 100), 2) if total_pairs > 0 else 0.0
        consec_timing = {
            "median_delta_sec": round(_median_delta, 2),
            "pct_sub30s": _pct_sub30,
            "pct_sub60s": _pct_sub60,
            # expected median from Exp(1/600) is 600*ln(2) ≈ 416 s; flag if meaningfully fast
            "fast_flag": bool(_median_delta < 380)
        }

        # Task 3: quarterly_lift — split history into non-overlapping 3-month windows
        _quarterly_lift_rows = []
        _pool_quarters = df[df['pool_name'] == pool]
        for _q in sorted(_pool_quarters['quarter'].unique()):
            _q_all = df[df['quarter'] == _q]
            _q_total = len(_q_all)
            _q_pool_blocks = int((_pool_quarters['quarter'] == _q).sum())
            if _q_pool_blocks < 10:
                continue
            _w_share = _q_pool_blocks / _q_total if _q_total > 0 else 0.0
            _q_consec = int(sync_df[
                (sync_df['pool_name'] == pool) &
                (sync_df['quarter'] == _q) &
                (sync_df['time_delta'] >= 0)
            ].shape[0])
            _q_expected = _q_pool_blocks * _w_share
            _q_lift = round(_q_consec / _q_expected, 3) if _q_expected > 0 else None
            _quarterly_lift_rows.append({
                "quarter": str(_q),
                "pool_blocks": _q_pool_blocks,
                "pool_consecutive": _q_consec,
                "window_share": round(_w_share, 4),
                "expected_consec": round(_q_expected, 2),
                "lift": _q_lift
            })

        sync_stats.append({
            "pool": pool,
            "avg_strike_delta": round(p_deltas.mean(), 2),
            "median_strike_delta": round(p_deltas.median(), 2),
            "buckets": buckets,
            "buckets_empty": buckets_empty,
            "total_consecutive": len(p_deltas),
            "total_blocks": len(p_df_full),
            "expected_consecutive": round(_expected_consec, 2),
            "monthly_lift": _monthly_lift_rows,
            "consec_timing": consec_timing,
            "quarterly_lift": _quarterly_lift_rows
        })

    # KPI 8: Cross-pool Transition Matrix
    print("KPI 8: Cross-pool Transition Matrix...")
    # Only pools with >= 5000 blocks to keep matrix readable (~8-10 pools)
    _pool_block_counts = df['pool_name'].value_counts()
    _matrix_pools = [
        p for p in _pool_block_counts[_pool_block_counts >= 5000].index
        if p != 'Unknown'
    ]
    # Sort descending by block count
    _matrix_pools = sorted(_matrix_pools, key=lambda p: _pool_block_counts[p], reverse=True)

    # Build consecutive pairs: each row i pairs pool at row i with pool at row i+1
    _df_sorted = df.sort_values('height').copy()
    _df_sorted['_next_pool'] = _df_sorted['pool_name'].shift(-1)
    # Filter both sides to matrix pools
    _pairs_df = _df_sorted[
        _df_sorted['pool_name'].isin(_matrix_pools) &
        _df_sorted['_next_pool'].isin(_matrix_pools)
    ].copy()

    # Block-weighted expected transitions — mirrors the kpi4_sync methodology:
    # For each block N mined by pool_A in month M, the expected probability that
    # pool_B mines block N+1 = pool_B's actual share in month M (not an all-time flat).
    # This correctly handles pools whose hashrate grew or shrank over the period.
    #
    # gateway_month_counts[pool_A][month] = # of blocks where pool_A was block N
    # and the next block (N+1) was mined by any matrix pool.
    _gateway_month_counts = (
        _pairs_df.groupby(['pool_name', 'month'])
        .size()
        .reset_index(name='gateway_count')
    )

    # Pre-compute block-weighted expected transitions for every (A, B) pair.
    # expected_AB = sum_m( gateway_count_A_m * monthly_share_B_m )
    _expected_matrix = {}
    for _pa in _matrix_pools:
        _expected_matrix[_pa] = {}
        _pa_gateways = _gateway_month_counts[_gateway_month_counts['pool_name'] == _pa]
        for _pb in _matrix_pools:
            _exp = 0.0
            for _, _grow in _pa_gateways.iterrows():
                _b_share = monthly_share_lookup.get((_grow['month'], _pb), 0.0)
                _exp += _grow['gateway_count'] * _b_share
            _expected_matrix[_pa][_pb] = _exp

    # Count transitions using groupby
    _trans_counts = (
        _pairs_df.groupby(['pool_name', '_next_pool'])
        .size()
        .reset_index(name='n')
    )
    # Pivot to get easy lookup
    _trans_pivot = _trans_counts.pivot(index='pool_name', columns='_next_pool', values='n').fillna(0)
    # Row totals (number of times pool_A was block N and pool_B was ANY matrix pool)
    _row_totals = _pairs_df.groupby('pool_name').size()

    _matrix_data = []
    _anomalies = []
    _notable_low_n = []  # High lift pairs that just miss the n>200 threshold
    for _pa in _matrix_pools:
        _row_total = int(_row_totals.get(_pa, 0))
        for _pb in _matrix_pools:
            _n = int(_trans_pivot.loc[_pa, _pb]) if (_pa in _trans_pivot.index and _pb in _trans_pivot.columns) else 0
            _obs_rate = _n / _row_total if _row_total > 0 else 0.0
            _exp_bw = _expected_matrix[_pa].get(_pb, 0.0)  # block-weighted expected count
            _exp_rate = _exp_bw / _row_total if _row_total > 0 else 0.0
            _lift = round(_n / _exp_bw, 3) if _exp_bw > 0 else None
            _matrix_data.append({"from": _pa, "to": _pb, "n": _n, "lift": _lift})
            if _lift is not None and _lift > 1.15 and _n > 200:
                _anomalies.append({
                    "from": _pa,
                    "to": _pb,
                    "n": _n,
                    "observed_rate": round(_obs_rate, 4),
                    "expected_rate": round(_exp_rate, 4),
                    "lift": _lift
                })
            elif _lift is not None and _lift > 1.3 and 30 <= _n <= 200:
                # Notable pair: high signal but small sample — surface separately
                _notable_low_n.append({
                    "from": _pa,
                    "to": _pb,
                    "n": _n,
                    "observed_rate": round(_obs_rate, 4),
                    "expected_rate": round(_exp_rate, 4),
                    "lift": _lift
                })

    _anomalies = sorted(_anomalies, key=lambda x: x['lift'], reverse=True)
    _notable_low_n = sorted(_notable_low_n, key=lambda x: x['lift'], reverse=True)

    # Build pool_countries lookup from pools_info.json
    with open(DASHBOARD_DATA / "lookup" / "pools_info.json") as _f:
        _pools_info_raw = json.load(_f)
    _name_to_country = {p['name'].lower(): p.get('country', 'Unknown') for p in _pools_info_raw}
    # Slug-to-display-name map for the matrix pools
    _slug_display = {
        'foundryusa': 'Foundry USA', 'antpool': 'AntPool', 'f2pool': 'F2Pool',
        'viabtc': 'ViaBTC', 'binancepool': 'Binance Pool', 'poolin': 'Poolin',
        'btccom': 'BTC.com', 'marapool': 'MARA Pool', 'braiinspool': 'Braiins Pool',
        'luxor': 'Luxor', 'spiderpool': 'SpiderPool'
    }
    _pool_countries = {}
    for _slug in _matrix_pools:
        _display = _slug_display.get(_slug, _slug)
        _pool_countries[_slug] = _name_to_country.get(_display.lower(), 'Unknown')

    kpi8_data = {
        "pools": _matrix_pools,
        "pool_countries": _pool_countries,
        "matrix": _matrix_data,
        "anomalies": _anomalies[:20],
        "notable_low_n": _notable_low_n[:10]
    }

    # KPI 5: Empty Block Auditor (Multi-Horizon)
    print("KPI 5: Empty Block Auditor Analysis...")
    
    # 1. Snapshots (All-time vs 30-day)
    thirty_days_ago = df['timestamp'].max() - pd.Timedelta(days=30)
    df_30d = df[df['timestamp'] >= thirty_days_ago]
    
    empty_stats = []
    for pool in extended_pools:
        # All-time
        p_df = df[df['pool_name'] == pool]
        if len(p_df) < 50: continue
        
        total_all = len(p_df)
        empty_all = int(p_df['is_empty'].sum())
        
        # 30-day
        p_df_30 = df_30d[df_30d['pool_name'] == pool]
        total_30 = len(p_df_30)
        empty_30 = int(p_df_30['is_empty'].sum()) if total_30 > 0 else 0
        
        empty_stats.append({
            "pool": pool,
            "total_all": total_all,
            "empty_all": empty_all,
            "ratio_all": round(empty_all / total_all * 100, 2),
            "total_30d": total_30,
            "empty_30d": empty_30,
            "ratio_30d": round(empty_30 / total_30 * 100, 2) if total_30 > 0 else 0
        })
    
    empty_stats = sorted(empty_stats, key=lambda x: x['ratio_all'], reverse=True)

    # 2. Monthly Trend (for the Top 10 pools by empty ratio)
    print("  Calculating monthly empty block trends...")
    df['month'] = df['timestamp'].dt.to_period('M').astype(str)
    
    # We only take pools that actually have a significant presence
    top_empty_offenders = [s['pool'] for s in empty_stats[:10]]
    trend_df = df[df['pool_name'].isin(top_empty_offenders)].groupby(['month', 'pool_name']).agg(
        total=('is_empty', 'count'),
        empty=('is_empty', 'sum')
    ).reset_index()
    trend_df['ratio'] = (trend_df['empty'] / trend_df['total'] * 100).round(2)
    
    monthly_empty_trend = trend_df.to_dict(orient='records')

    # KPI 6: Block Density Index
    print("KPI 6: Block Density Index...")
    # Space efficiency = bytes_total / block_weight
    # Max block_weight is 4,000,000
    df['density'] = df['bytes_total'] / df['block_weight']
    
    density_stats = []
    for pool in extended_pools:
        p_df = df[df['pool_name'] == pool]
        if len(p_df) < 100: continue
        
        density_stats.append({
            "pool": pool,
            "avg_density": round(float(p_df['density'].mean()), 4),
            "avg_tx_count": round(float(p_df['tx_count'].mean()), 2),
            "avg_bytes": round(float(p_df['bytes_total'].mean()), 2)
        })
    
    density_stats = sorted(density_stats, key=lambda x: x['avg_density'], reverse=True)

    # KPI 7: BIP 110 Battleground
    print("KPI 7: BIP 110 Battleground Analysis...")
    # 1. Signaling Logic
    df['is_bip110'] = (df['protocol_version'] & 16) != 0
    
    # Get 2016-block rolling average of signaling
    # We'll do this globally and also per-pool if we want the stacked area
    # For a stacked area chart, we need the contribution of each pool to the total signaling
    # Or rather, the share of signaling blocks mined by each pool in the window.
    df['signaling_val'] = df['is_bip110'].astype(int)
    
    # Calculate global signaling % over last 2016 blocks
    df['global_signaling_2016'] = df['signaling_val'].rolling(window=2016, min_periods=1).mean() * 100
    
    # For the stacked area chart: we group by Day and Pool
    df['day'] = df['timestamp'].dt.to_period('D').astype(str)
    
    # 2. Signaling Trend (Daily)
    # We want: Day, Pool, SignalingBlocksCount
    # And also TotalBlocksCount in that day to get the % context
    bip110_daily = df.groupby(['day', 'pool_name']).agg(
        total_blocks=('block_height', 'count'),
        signaling_blocks=('is_bip110', 'sum')
    ).reset_index()
    
    # 3. Efficiency Ratio (Scatter Sample)
    # Take last 30 days for the efficiency scatter plot
    efficiency_sample = df_30d[['block_height', 'tx_count', 'bytes_total', 'pool_name']].to_dict(orient='records')
    
    # 4. "Over-Limit" Blocks (83-Byte Rule Proxy)
    # Calculation: (bytes_total - bytes_stripped) / tx_count
    df['data_overhead'] = (df['bytes_total'] - df['bytes_stripped']) / df['tx_count'].replace(0, 1) # Avoid div by zero
    
    # Re-filter 30d to pick up the new column
    df_30d_new = df[df['timestamp'] >= thirty_days_ago]
    
    overhead_stats = []
    for pool in top_pools:
        # Last 30 days only for overhead
        p_df_30 = df_30d_new[df_30d_new['pool_name'] == pool]
        if len(p_df_30) < 50: continue
        
        overhead_stats.append({
            "pool": pool,
            "avg_overhead": round(float(p_df_30['data_overhead'].mean()), 2),
            "max_overhead": round(float(p_df_30['data_overhead'].max()), 2)
        })
    overhead_stats = sorted(overhead_stats, key=lambda x: x['avg_overhead'], reverse=True)

    # Final Signaling Trend Data Formatting
    days = sorted(bip110_daily['day'].unique())
    # Pre-calculate global rolling at the end of each day efficiently
    daily_rolling = df.groupby('day')['global_signaling_2016'].last().to_dict()
    
    signaling_trend = []
    for d in days:
        day_data = bip110_daily[bip110_daily['day'] == d]
        pool_signaling = {}
        pool_total = {}
        day_total_blocks = 0
        
        for _, row in day_data.iterrows():
            pname = row['pool_name']
            sig_count = int(row['signaling_blocks'])
            tot_count = int(row['total_blocks'])
            day_total_blocks += tot_count
            
            if sig_count > 0:
                pool_signaling[pname] = sig_count
            pool_total[pname] = tot_count
        
        signaling_trend.append({
            "day": str(d),
            "total_blocks": day_total_blocks,
            "pools_signaling": pool_signaling,
            "pools_total": pool_total,
            "global_rolling": round(float(daily_rolling.get(d, 0)), 2)
        })

    # Combine all into one JSON
    output = {
        "kpi1_strikes": leaderboard_json,
        "kpi2_funnel": funnel_data,
        "kpi3_entropy": entropy_data,
        "kpi4_sync": sync_stats,
        "kpi5_empty_blocks": {
            "leaderboard": empty_stats,
            "monthly_trend": monthly_empty_trend
        },
        "kpi6_density": density_stats,
        "kpi7_bip110": {
            "signaling_trend": signaling_trend[-180:], # Last 180 days
            "efficiency_scatter": efficiency_sample,
            "overhead_bar": overhead_stats
        },
        "kpi8_transitions": kpi8_data,
        "last_updated": pd.Timestamp.now().isoformat(),
        **registry_provenance(),
    }
    
    out_path = DASHBOARD_DATA / "forensics_data.json"
    with open(out_path, 'w') as f:
        json.dump(output, f, indent=2)
    
    print(f"Forensics data written to {out_path}")

if __name__ == "__main__":
    main()
