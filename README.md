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

We stand on the shoulders of the community. Our historical and real-time data is synthesized from:

1.  **Historical Blocks (0–869k)**: Sourced from [jlopp/bitcoin-blocks-by-mining-pool](https://github.com/jlopp/bitcoin-blocks-by-mining-pool). This incredible dataset provides the foundation of the historical records.
2.  **Pool Metadata**: Sourced from the [bitcoin-data/mining-pools](https://github.com/bitcoin-data/mining-pools/tree/generated) repository (generated branch), providing the mapping between coinbase tags, payout addresses, and pool identities.
3.  **Modern Tip (Post-2024)**: Continuously updated directly from a **self-hosted Bitcoin full node**, providing the most accurate, real-time insights into the current mining landscape.

---

## 🚀 Getting Started

- **View Live Dashboard**: [Visit the GitHub Pages site](https://bitcoindatalabs.github.io/bitcoin-mining-pools/) (or your repo's URL).

### 🔄 Data Update Loop
To refresh the dashboard with new block data from a node or pool-lookup registry, run the following sequence:

1. **`python scripts/merge_myrp.py`**: Merges new blocks from your local node (`data/raw/bitcoin_miners_myrp.parquet`) into the dashboard dataset.
2. **`python scripts/update_metrics.py`**: Recalculates all pool KPIs, ecosystem growth, and generates the master slug-to-name lookup.
3. **`python scripts/process_forensics.py`**: Calibrates the advanced forensics models (Z-Scores, Entropy, Streaks).

> [!NOTE]
> `scripts/prepare_data.py` is now a **Legacy Importer** and should only be run if you are resetting the entire historical dataset from the original `blocks.csv`. Regular updates should skip this to avoid overwriting node data.

- **Read the Docs**: Start with [docs/01-architecture.md](./docs/01-architecture.md) for a deep dive into how we handle 860k blocks in a browser.
