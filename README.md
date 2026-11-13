# Bitcoin Mining Pools: Data & Dashboard

An open-source, full-stack data pipeline and interactive visualization suite for tracking the evolution of Bitcoin mining from Genesis to the present day. This repository serves two distinct products: a high-fidelity **Processed Dataset** and a zero-latency **Static Dashboard**.

---

## 🏗️ Two Products, One Repository

### 1. The Dashboard (Interactive Visualization)
A "no-build-step," fully static web application hosted on GitHub Pages. It leverages **hyparquet** to read multi-megabyte Parquet files directly in the browser, providing a buttery-smooth experience without a server.
- **8 Interactive Charts**: From market share donuts to geographic footprint (country share).
- **Miner Profiles**: Searchable, deep-dive profiles for over 150+ mining pools.
- **Decentralization Lab**: Real-time HHI (Herfindahl-Hirschman Index) tracking and Top-3/Top-5 pool concentration benches.
- **Ecosystem Growth**: A historical scatter-line visualization of every pool discovered since 2011.
- **Mining Forensics & Reorg Risks**: Analyzes pool luck via Z-scores, propagation latency histograms, and timing entropy heatmaps to profile systemic network threats.

### 2. The Data Pipeline (Processed Insights)
A robust Python pipeline that transforms raw block-level data into high-performance, dictionary-encoded **Parquet** files.
- **Dual-Era Storage**: Data is split into `blocks_pre_2021.parquet` and `blocks_post_2021.parquet`. This enables users to fetch only the modern industrial era (~3MB) for recent analysis without downloading the entire 17-year history.
- **HHI Metrics**: Pre-calculated decentralization indices to track network health trends.

### 📊 Data Schema
Both parquet files use the following schema, optimized for size and speed:
| Column | Type | Description |
|---|---|---|
| `height` | `int32` | Block height (0 to tip) |
| `pool_slug`| `str (dict)` | Normalized pool ID (e.g. "foundryusa", "antpool") |
| `date` | `timestamp` | Block creation time (µs precision) |

### 🔄 Automated Updates
This is a **living dataset**. The reports and data files are updated:
- **Monthly**: A GitHub Action scheduled refresh ensures all monthly trend lines are finalized.
- **Node-Synced**: block data is pushed monthly directly from our self-hosted Bitcoin node to keep the modern era current.

---

## 📈 Data Insights: Beyond the Hashrate
This project isn't just about who is winning today; it’s about the **narrative of Bitcoin’s centralisation**. 
- Witness the **"Rise of the Industrial Era"** post-2020.
- Track the **"Great Migration"** as hash power shifted across geographic borders.
- Observe how the **network tip** reacts to halving events and the emergence of institutional-grade pools like Foundry and AntPool.
- Experience the **"Long Tail"** of Bitcoin history by exploring extinct pools from the 2011–2014 era.

---

## 📂 Project Structure

```bash
├── dashboard/      # The web application (HTML/JS/CSS)
│   └── data/       # Deploy artifacts (Parquet/JSON)
├── data/           # The local data lake
│   ├── raw/        # Source CSVs and Metadata
│   └── processed/  # Output of the Python pipeline
├── scripts/        # Python pipeline (Pandas/PyArrow)
└── docs/           # Technical architecture & logic flow
```

---

## 🔌 Data Sources

We stand on the shoulders of the community. Every block's pool comes from one resolver
(`scripts/pool_resolver.py`), fed by these sources (pinned commits, licences and counts in
[data/raw/SOURCES.md](./data/raw/SOURCES.md)):

1.  **Chain data**: each block's coinbase scriptSig and coinbase outputs, read from our own **self-hosted Bitcoin node**
    (a local chain lake), for every block from Genesis to the tip.
2.  **Pool lists** (refreshed, pinned in `data/raw/pool_sources.lock.json`): [mempool/mining-pools](https://github.com/mempool/mining-pools)
    (the list behind mempool.space) and [bitcoin-data/mining-pools](https://github.com/bitcoin-data/mining-pools/tree/generated)
    (0xB10C, generated branch), plus our cited additions in `data/raw/pools_supplement.json`. Both lists are MIT-licensed.
3.  **Historical labels (0–869,305, frozen)**: [jlopp/bitcoin-blocks-by-mining-pool](https://github.com/jlopp/bitcoin-blocks-by-mining-pool),
    used only as a fallback when a block has neither a known coinbase tag nor a known payout address. It is no longer
    maintained and is not refreshed.

**How a block is labelled** (`method` in `data/processed/block_attribution.parquet`):
`tag` / `regex` (a known coinbase tag; the longest match wins), `payout` (a known payout address; it wins over a
conflicting tag, because such a tag is a sub-account or worker name inside another pool's coinbase, except for pools
that pay their miners in the coinbase, such as OCEAN or Eligius), `jlopp` (the frozen historical label), `unknown`.
Tags that name pool *software* (`ckpool`, `BTCPool`) are used only as a last resort.

---

## 🚀 Getting Started

- **View Live Dashboard**: [Visit the GitHub Pages site](https://bitcoindatalabs.github.io/bitcoin-mining-pools/) (or your repo's URL).

### 🔄 Data Update Loop
To refresh the dashboard with new blocks or a new pool list, run in order (on datalabs,
`python/automation/miner_data_updater.py` runs this sequence):

1. **`python scripts/extract_coinbase.py`**: appends new blocks' coinbase data from the local chain lake
   (`--chain-parts DIR`, default `/data/bitcoin/data/chain/parts`) to `data/raw/coinbase_blocks.parquet`.
2. **`python scripts/resolve_blocks.py`**: rebuilds the pool registry (`build_pools_lookup.py`), labels every block,
   and writes `data/processed/block_attribution.parquet` plus `blocks_pre_2021.parquet` and
   `blocks_post_2021.parquet`. When the registry changes, every block is re-resolved; otherwise only new ones.
3. **`python scripts/update_metrics.py`**: Recalculates all pool KPIs and ecosystem growth.
4. **`python scripts/process_forensics.py`**: Calibrates the advanced forensics models (Z-Scores, Entropy, Streaks).

> [!NOTE]
> `scripts/merge_myrp.py` is deprecated and now just runs `resolve_blocks.py`. `scripts/prepare_data.py` is a legacy
> importer from the original `blocks.csv` and is no longer part of the pipeline.

- **Read the Docs**: Start with [docs/01-architecture.md](./docs/01-architecture.md) for a deep dive into how we handle 860k blocks in a browser.
