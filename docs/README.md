# Documentation Index

Architecture and client-side rendering notes for the `bitcoin-mining-pools` static dashboard.

> **Note (`bdl-065` / `bdl-066`)**: Raw data inputs, upstream pool lists, attribution resolution, and Python
> pipeline scripts have moved to the sibling **`mining-pools-data`** repository. `bitcoin-mining-pools` serves
> the static frontend in `dashboard/` from data artifacts synced into `dashboard/data/` by
> `mining-pools-data/scripts/sync_to_site.py`.

| File | What it answers |
|---|---|
| [01-architecture.md](./01-architecture.md) | Frontend architecture, dashboard layout, tech stack |
| [02-data-flow.md](./02-data-flow.md) | Browser Parquet/JSON loading -> filters -> ECharts visuals |
| [03-logic-flow.md](./03-logic-flow.md) | Runtime execution order, state machine, filter/render cycle |
| [04-adding-features.md](./04-adding-features.md) | Step-by-step patterns for UI and chart extensions |

## Project in one sentence
A static Bitcoin mining pool dashboard hosted on GitHub Pages that reads dual-era Parquet files synced from
`mining-pools-data` in the browser via **hyparquet** and renders interactive **ECharts** visualizations — no
backend, no build step.
