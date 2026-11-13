# Data sources

Where every input in `data/raw/` comes from, which version we use, and how it may be used. Machine-readable pins for
the two upstream pool lists are in `pool_sources.lock.json`. The registry built from them
(`dashboard/data/lookup/pools_enriched.json`) records the same pins and a `registry_version`.

## Pool lists (refreshed)

| File | Upstream | Branch | Commit (pinned) | Commit date | Licence |
|---|---|---|---|---|---|
| `pools.json` | [bitcoin-data/mining-pools](https://github.com/bitcoin-data/mining-pools) (0xB10C and contributors) | `generated` | `0158b59ac47ac1b6f1df2704c98f2576f6d5391d` | 2026-06-30 | MIT |
| `mempool-pools-v2.json` | [mempool/mining-pools](https://github.com/mempool/mining-pools) (the list behind mempool.space) | `master` | `d2ddbfa37da1d260225b74db04f939871f78e17b` | 2026-11-12 | MIT |

Both files are the exact upstream bytes at the pinned commit (`md5` in the lock file), first fetched 2026-11-12 and
since then refreshed daily by `scripts/refresh_pool_sources.py`: it pins the newest commit that changed the file,
validates the file, and keeps the last good snapshot if the new one is refused or the fetch fails. The table below
records the pins of 2026-11-12; the lock file always holds the current ones, and git history holds every earlier
snapshot. Label changes caused by a new pin are logged in `data/status/relabel_log.json`.

- **bitcoin-data `pools.json`**: `coinbase_tags` (matched as exact, case-sensitive substrings of the coinbase
  scriptSig) and `payout_addresses`; 174 tags and 201 addresses at this commit. The generated branch is rebuilt from
  `master` (last change 2026-04-21, "add: GDPool").
- **mempool `pools-v2.json`**: a list of pools (`id`, `name`, `addresses`, `tags`, `link`); 172 pools, 207 tags,
  220 addresses at this commit. mempool's backend uses each tag as a JavaScript regex with the `i` flag on the
  scriptSig read byte by byte (`backend/src/api/pools-parser.ts` `matchBlockMiner`, mempool/mempool `04c299c`), and
  derives the slug from the name (`name.replace(/[^a-z0-9]/gi, '').toLowerCase()`). We match its tags the same way.
- Both licences are MIT. bitcoin-data: "Copyright (c) 2019-2021 btc.com; Copyright (c) 2021- 0xB10C and
  contributors". mempool: "Copyright (c) 2019 btc.com". Both lists descend from btc.com's original `known-pools`
  list and share its git history up to 2021.
- How the two lists differed on 2026-11-12: 157 tags and 175 addresses are in both. mempool alone has 50 tags and
  45 addresses (most of them pools that `pools_supplement.json` had already added by hand). bitcoin-data alone has
  17 tags and 26 addresses. Eight entries give a tag or an address to different pools; they are listed in
  `dashboard/data/lookup/pool_conflicts.json`, where the higher-precedence source wins.

## Our curated additions

`pools_supplement.json`: tags, regexes and payout addresses that neither upstream list has, slug aliases for
renamed pools, `generic_tags` (pool *software* names such as `ckpool`), `payout_to_miners_slugs` (pools whose
coinbase pays miners directly), and pool types. Every entry added since bdl-060 (2026-11-12) has a `source` field
that cites where it comes from. Precedence when building the registry: supplement > mempool > bitcoin-data.

## Historical block labels (frozen)

| File | Upstream | Heights | Rows | Status |
|---|---|---|---|---|
| `blocks.csv` | [jlopp/bitcoin-blocks-by-mining-pool](https://github.com/jlopp/bitcoin-blocks-by-mining-pool) | 0 – 869,305 | 869,316 (10 duplicated rows at 860,579–860,588) | **Frozen. Not refreshed.** |

- jlopp's dataset stopped at height 869,305 (2024-11-07). It is not maintained any more, and it is never
  re-downloaded (owner decision 2026-11-12).
- We use it only as a fallback label (rule 3 in `scripts/pool_resolver.py`), after the coinbase tag and the payout
  address.
- Its labels match mempool.space's own block labels in every block we sampled. On 2026-11-12 our resolver agreed
  with it on 99.94% of the 649,115 blocks it labels. The disagreements are explained in the bdl-060 report.

## Chain data (local, not in git)

- `coinbase_blocks.parquet` (gitignored) holds every block's coinbase scriptSig and coinbase output scripts.
  `scripts/extract_coinbase.py` writes it from a local chain lake: on datalabs, `/data/bitcoin/data/chain/parts`,
  written from our own Bitcoin Core node.
- `bitcoin_blocks_pool.parquet` (gitignored) holds per-block size, weight and transaction count for
  `process_forensics.py`. It is written by `python/automation/miner_data_updater.py`.
- `bitcoin_miners_myrp.parquet` holds legacy labels for 869,306–942,459. No script reads it any more; it is kept
  only for reference.
