# Architecture

## System Overview

This is a **fully static, no-build-step** dashboard. There is no server, no API,
no framework, no bundler. Everything runs in the browser from flat files served
by GitHub Pages.

```
┌─────────────────────────────────────────────────────────┐
│                    GitHub Pages                          │
│                                                          │
│   dashboard/          ← static file root                │
│   ├── index.html      ← single page, loads all JS/CSS   │
│   ├── css/style.css   ← all styles, no preprocessor     │
│   ├── data/           ← pre-built data files (Updated: 2026-03-29)   │
│   │   ├── blocks_post_2021.parquet (3.3 MB, Snappy)     │
│   │   ├── blocks_pre_2021.parquet  (7.6 MB, Snappy)     │
│   │   ├── pool_metrics.json   (30 KB)                   │
│   │   ├── pool_growth.json   (2.7 KB)                   │
│   │   ├── forensics_data.json (15 KB)                   │
│   │   └── lookup/                                       │
│   │       ├── lookup_slug_to_name.json                  │
│   │       ├── pools_info.json                           │
│   │       └── timelines.json                            │
│   └── js/                                               │
│       ├── main.js          ← app bootstrap + lazy loading│
│       ├── data-loader.js   ← parquet parsing + aggs     │
│       └── charts.js        ← all ECharts renderers      │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│              Python Data Pipeline (local only)           │
│                                                          │
│   data/raw/            (provenance: data/raw/SOURCES.md) │
│   ├── coinbase_blocks.parquet ← chain lake (gitignored)  │
│   ├── pools.json       ← bitcoin-data list (pinned)      │
│   ├── mempool-pools-v2.json ← mempool list (pinned)      │
│   ├── pool_sources.lock.json ← upstream SHAs + md5       │
│   ├── pools_supplement.json ← our cited additions        │
│   ├── blocks.csv       ← jlopp labels 0-869,305 (FROZEN) │
│   └── bitcoin_blocks_pool.parquet ← forensics metrics    │
│                                                          │
│   scripts/                                               │
│   ├── extract_coinbase.py ← (Step 1) chain lake -> raw   │
│   ├── resolve_blocks.py ← (Step 2) registry + resolver   │
│   │   ├── build_pools_lookup.py  (merged registry)       │
│   │   └── pool_resolver.py       (the one resolver)      │
│   ├── update_metrics.py ← (Step 3) JSONs                 │
│   ├── process_forensics.py ← (Step 4) Forensics          │
│   ├── merge_myrp.py    ← [DEPRECATED] runs resolve_blocks│
│   └── prepare_data.py  ← [LEGACY] One-time CSV Import    │
│                                                          │
│   dashboard/data/      ← (Generated Artifacts)           │
│   ├── blocks_post_2021.parquet                           │
│   ├── pool_metrics.json                                  │
│   ├── pool_growth.json                                   │
│   └── forensics_data.json                                │
└─────────────────────────────────────────────────────────┘
```

The pipeline runs **locally** (or via future GitHub Actions). Its outputs are
committed into `dashboard/data/` so GitHub Pages can serve them statically.

---

## Folder Structure (annotated)

```
bitcoin-mining-pools/
│
├── blocks.csv                  ← original download from jlopp (kept at root,
│                                 also copied to data/raw/). Do not delete.
│
├── data/
│   ├── raw/
│   │   ├── blocks.csv          ← canonical raw input for the pipeline
│   │   ├── pools.json          ← pool name/link lookup from bitcoin-data/mining-pools
│   │   └── bitcoin_blocks_pool.parquet ← modern blocks and mempool data
│   ├── processed/
│   │   ├── blocks.parquet      ← master processed parquet (source of truth)
│   │   ├── pool_metrics.json   ← master pool metadata/metrics JSON
│   │   ├── pool_growth.json    ← master ecosystem growth JSON
│   │   └── forensics_data.json ← master forensics export
│   └── geo/                    ← RESERVED: future geolocation data (empty now)
│       └── .gitkeep
│
├── scripts/
│   ├── prepare_data.py         ← [LEGACY] processes CSV once and exits
│   ├── merge_myrp.py           ← (Step 1) merges additional MYRP blocks
│   ├── update_metrics.py       ← (Step 2) calculates final metrics and Slug Lookup
│   └── process_forensics.py    ← (Step 3) generates reorg risks, entropy, Z-scores
│
├── dashboard/                  ← GitHub Pages root (everything here is public)
│   ├── index.html
│   ├── css/style.css
│   ├── data/
│   │   ├── blocks_post_2021.parquet ← (2021 — 2026)
│   │   ├── blocks_pre_2021.parquet  ← (Genesis — 2020)
│   │   ├── pool_metrics.json   ← COPY of data/processed/pool_metrics.json
│   │   ├── pool_growth.json    ← COPY of data/processed/pool_growth.json
│   │   ├── forensics_data.json ← COPY of data/processed/forensics_data.json
│   │   └── lookup/
│   │       ├── lookup_slug_to_name.json
│   │       ├── pools_info.json
│   │       └── timelines.json
│   ├── js/
│   │   ├── main.js             ← entry point, app state, filter wiring
│   │   ├── data-loader.js      ← data fetching, parsing, all aggregation functions
│   │   └── charts.js           ← all ECharts chart renderers
│   └── assets/
│       └── icons/              ← RESERVED: future pool/country icons
│
├── docs/                       ← you are here
│
└── .github/
    └── workflows/              ← RESERVED: future scheduled data refresh Action
```

> **Standard Data Refresh Pipeline (Regular Use):**
> 1. `python scripts/merge_myrp.py` (Appends 2025/2026 node data)
> 2. `python scripts/update_metrics.py` (Refreshes lifetime KPIs and Slug Lookup)
> 3. `python scripts/process_forensics.py` (Refreshes reorg & latency data)
>
> **Legacy Setup Only (Don't run by mistake):**
> *   `python scripts/prepare_data.py` (Only for one-time CSV-to-Parquet migration)

---

## Tech Stack

### Python Pipeline
| Component | Choice | Why |
|---|---|---|
| Data processing | `pandas` | Fast CSV read, clean column ops |
| Parquet write | `pyarrow` | Best-in-class parquet support |
| Compression | **Snappy** | Only codec hyparquet supports natively in-browser |
| Dictionary encoding | `use_dictionary=["pool_slug"]` | Slugs repeat ~143 unique values across 942k rows → massive size saving |

### Browser / Dashboard
| Component | Choice | Version | Why |
|---|---|---|---|
| Parquet reader | `hyparquet` | **1.17.1** | Pure JS, no WASM, CDN-ready, supports Snappy. Pin to this version — API changed in later releases |
| Charts | `echarts` | 5.5.1 | Built-in `dataZoom`, stacked area, treemap; used by mempool.space |
| Styling | Vanilla CSS | — | No framework needed; dark Bitcoin-orange theme |
| JS | Vanilla ESM modules | — | No bundler; `type="module"` in index.html |

### CDN imports (in index.html)
```js
import { parquetRead, parquetMetadata }
  from 'https://cdn.jsdelivr.net/npm/hyparquet@1.17.1/+esm';

import * as echarts
  from 'https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.esm.min.js';
```
Both are assigned to `window.__hyparquet` and `window.__echarts` so the
ES module files (`data-loader.js`, `charts.js`) can access them without
circular import issues.

---

## Data Sources

| Source | URL | Used for |
|---|---|---|
| jlopp/bitcoin-blocks-by-mining-pool | [GitHub Repo](https://github.com/jlopp/bitcoin-blocks-by-mining-pool) | `blocks.csv` — Historical (heights 0–869305) |
| bitcoin-data/mining-pools | [GitHub Repo (generated branch)](https://github.com/bitcoin-data/mining-pools/tree/generated) | `pools.json` — Mapping addresses/tags to pool names |
| Bitcoin Node (self-hosted) | Local RPC | **Post-2024 Data** — March 2026 blocks ($H \approx 942,459$) |

---

## Key Constraints — Read Before Changing Anything

1. **Snappy compression only.** hyparquet 1.17.1 has no ZSTD support.
   Never change `compression="snappy"` in `prepare_data.py`.

2. **No `Math.min/max(...largeArray)`.** Spreading 869k items as function
   arguments overflows the JS call stack. Always use loops or index access.

3. **Blocks are sorted ascending by height** after `loadData()` returns.
   Code that needs min/max date relies on `filtered[0]` and `filtered[at(-1)]`.

4. **`window.__hyparquet` and `window.__echarts`** are the only globals.
   All JS files are ESM modules; they read libs from these globals rather
   than importing directly (avoids re-fetching the CDN bundle).

5. **No build step.** Do not introduce npm, webpack, vite, or any bundler.
   The dashboard must remain deployable as raw files to GitHub Pages.

6. **`dashboard/data/` is a deploy artifact.** It is committed to git so
   GitHub Pages can serve it. It is NOT the source of truth — `data/processed/`
   is. Always regenerate from the pipeline, never hand-edit parquet.

---

## Planned Phases

| Phase | Status | Description |
|---|---|---|
| **V0** | ✅ Done | Static dashboard from jlopp CSV; 5 ECharts; HHI trend, pool concentration, pool share (donut), pool dominance (area), ecosystem growth (line), plus interactive miner profile |
| **V1** | ✅ Done | **Dual-Parquet & Lazy Loading**: Split data at 2020 for fast TTI; background load full history; Live 30-day KPI cards; Geographic distribution (Country Share); Searchable Miner Lookup |
| **V2** | 🔜 Next | Fetch gap (869k → tip) from mempool API; add real timestamps, fees, difficulty |
| **V3** | 🔮 Planned | Bitcoin node as data source; full block metadata; GitHub Actions scheduled refresh |
| **V4** | 🔮 Planned | Richer Geolocation layer; hash rate concentration by country; `data/geo/` populated |
