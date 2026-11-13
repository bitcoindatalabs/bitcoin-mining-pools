# Bitcoin Mining Pools Dashboard (`bitcoin-mining-pools`)

Static interactive dashboard hosted on GitHub Pages for tracking Bitcoin mining pool dominance,
decentralization metrics (HHI, Top-N concentration), sourced pool profiles (182 pools), and post-2021
mining forensics.

- **Dashboard UI**: `dashboard/` (`index.html`, `css/`, `js/`), deployed to GitHub Pages via `.github/workflows/static.yml` (`path: './dashboard'`). Zero build step; reads `dashboard/data/` directly in the browser via **hyparquet** and renders with **ECharts**.
- **Dataset & Pipeline**: Moved to the dedicated [**`mining-pools-data`**](https://github.com/bitcoindatalabs/mining-pools-data) repository (CC BY 4.0 data + MIT scripts). This repository receives synced dashboard artifacts (`dashboard/data/*.parquet`, `*.json`) via `mining-pools-data/scripts/sync_to_site.py`.

---

## Repository Layout

```
├── .github/workflows/static.yml   GitHub Pages deploy (`./dashboard`)
├── dashboard/                     Static web application
│   ├── index.html                 Dashboard layout
│   ├── css/                       Stylesheets
│   ├── js/                        Data loader & ECharts visualizations
│   ├── robots.txt                 Search crawler rules
│   ├── sitemap.xml                Site map
│   └── data/                      Synced dashboard payloads + static `lookup/timelines.json`
│       ├── blocks_pre_2021.parquet   height < 664,063 (height, pool, host_pool, date)
│       ├── blocks_post_2021.parquet  height >= 664,063 (height, pool, host_pool, date)
│       ├── pool_metrics.json
│       ├── pool_growth.json
│       ├── forensics_data.json
│       └── lookup/                pools_enriched, pool_profiles, pool_facts, pool_conflicts, ...
├── docs/                          Dashboard & browser architecture documentation
├── llms.txt                       LLM summary
└── README.md
```

---

## Data Refresh & Attribution

Block attribution, upstream list pinning (`bitcoin-data/mining-pools`, `mempool/mining-pools`, curated
`pools_supplement.json`), co-occurrence inference, 182 sourced pool profiles, and pipeline scripts live in
[`mining-pools-data`](https://github.com/bitcoindatalabs/mining-pools-data). Daily automation refreshes that
dataset first and runs `sync_to_site.py` to publish updated static assets into `dashboard/data/`.

## Local Preview

Serve `dashboard/` over HTTP (required for Parquet range/fetch requests):

```bash
python3 -m http.server 8000 --directory dashboard
```

Then open `http://localhost:8000`.
