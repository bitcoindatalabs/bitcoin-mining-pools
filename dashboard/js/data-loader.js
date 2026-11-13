/**
 * data-loader.js
 * Loads blocks.parquet via hyparquet and pool_metrics.json
 * Returns a structured dataset ready for aggregation.
 */

const POOL_META_URL = './data/pool_metrics.json?v=29';
const POOLS_INFO_URL = './data/lookup/pools_info.json';
const TIMELINES_URL = './data/lookup/timelines.json';
const LOOKUP_SLUG_URL = './data/lookup/lookup_slug_to_name.json';

/**
 * @typedef {Object} Block
 * @property {number} height
 * @property {string} pool_slug
 * @property {string} host_pool_slug
 * @property {string} pool_name
 * @property {string} host_pool_name
 * @property {Date}   date
 */

/**
 * @typedef {Object} Dataset
 * @property {Block[]}  blocks
 * @property {Object}   poolMeta   – { [poolName]: { link } }
 * @property {Object}   poolsInfo
 * @property {Object}   timelines
 * @property {Date}     minDate
 * @property {Date}     maxDate
 */

/** Fetch and parse the parquet file using hyparquet */
async function loadParquet(parquetUrl) {
  const { parquetRead } = window.__hyparquet;

  const res = await fetch(parquetUrl);
  if (!res.ok) throw new Error(`Failed to fetch parquet: ${res.status}`);
  const file = await res.arrayBuffer();

  return new Promise((resolve, reject) => {
    parquetRead({
      file,
      rowFormat: 'object',       // each row → plain JS object
      onComplete: (rows) => resolve(rows),
    }).catch(reject);
  });
}

/** Fetch pool metadata JSON */
async function loadPoolMeta() {
  const res = await fetch(POOL_META_URL);
  if (!res.ok) throw new Error(`Failed to fetch pool_meta: ${res.status}`);
  return res.json();
}

/** Fetch pools info JSON */
async function loadPoolsInfo() {
  const res = await fetch(POOLS_INFO_URL);
  if (!res.ok) throw new Error(`Failed to fetch pools_info: ${res.status}`);
  return res.json();
}

/** Fetch timelines JSON */
async function loadTimelines() {
  const res = await fetch(TIMELINES_URL);
  if (!res.ok) throw new Error(`Failed to fetch timelines: ${res.status}`);
  return res.json();
}

/** Fetch slug-to-name lookup JSON */
async function loadLookupSlugToName() {
  const res = await fetch(LOOKUP_SLUG_URL);
  if (!res.ok) throw new Error(`Failed to fetch lookup_slug_to_name: ${res.status}`);
  return res.json();
}

/** Fetch Global Ecosystem Growth JSON */
async function loadEcosystem() {
  const res = await fetch('./data/pool_growth.json?v=29');
  if (!res.ok) throw new Error(`Failed to fetch ecosystem: ${res.status}`);
  return res.json();
}

/** Fetch Forensics Data JSON */
export async function loadForensics() {
  const res = await fetch('./data/forensics_data.json?v=29');
  if (!res.ok) throw new Error(`Failed to fetch forensics: ${res.status}`);
  return res.json();
}

function slugToDisplayName(slug, lookup) {
  const name = lookup[slug];
  if (name) return name;
  if (slug && slug.toLowerCase() !== 'unknown' && slug.toString().trim() !== '') {
    return slug.toString()
      .replace(/[_-]/g, ' ')
      .replace(/\w\S*/g, txt => txt.charAt(0).toUpperCase() + txt.substring(1).toLowerCase());
  }
  return 'Unknown';
}

function normalizeBlock(b, lookup) {
  b.height = Number(b.height);
  const poolSlug = b.pool ?? b.pool_slug;
  const hostSlug = b.host_pool ?? b.pool_slug;
  b.pool_slug = poolSlug;
  b.host_pool_slug = hostSlug;
  b.pool_name = slugToDisplayName(poolSlug, lookup);
  b.host_pool_name = slugToDisplayName(hostSlug, lookup);
  if (!(b.date instanceof Date)) {
    b.date = new Date(
      typeof b.date === 'bigint'
        ? Number(b.date) / 1000   // parquet timestamps are in µs
        : b.date
    );
  }
}

/** Main entry – returns a Dataset */
export async function loadData(period = 'post') {
  const isFullHistory = (period === 'pre');
  const parquetUrls = isFullHistory 
    ? ['./data/blocks_pre_2021.parquet?v=29', './data/blocks_post_2021.parquet?v=29']
    : ['./data/blocks_post_2021.parquet?v=29'];

  const [blocksData, poolMeta, poolsInfo, timelines, ecosystem, lookup] = await Promise.all([
    Promise.all(parquetUrls.map(url => loadParquet(url))),
    loadPoolMeta(),
    loadPoolsInfo(),
    loadTimelines(),
    loadEcosystem(),
    loadLookupSlugToName()
  ]);

  let blocks = blocksData.flat();
  
  // If post-2021 is requested, filter out 2020 data
  if (period === 'post') {
    const start2021 = new Date('2021-01-01T00:00:00Z');
    blocks = blocks.filter(b => {
      // Sometimes b.date is µs timestamp from parquet at this stage
      const d = (b.date instanceof Date) ? b.date : new Date(Number(b.date) / 1000);
      return d >= start2021;
    });
  }

  for (const b of blocks) {
    normalizeBlock(b, lookup);
  }

  // Sort ascending by height (should already be, but guarantee it)
  blocks.sort((a, b) => a.height - b.height);

  const minDate = blocks[0].date;
  const maxDate = blocks[blocks.length - 1].date;

  return { blocks, poolMeta, poolsInfo, timelines, ecosystem, minDate, maxDate, slugToName: lookup };
}

/** Helper for background loading – just blocks, normalized and sorted */
export async function loadParquetOnly(url, lookup) {
  const blocks = await loadParquet(url);
  for (const b of blocks) {
    normalizeBlock(b, lookup);
  }
  blocks.sort((a, b) => a.height - b.height);
  return blocks;
}

/**
 * Filter blocks by a time range string: '1M','3M','6M','1Y','2Y','ALL'
 *
 */
export function filterBlocks(blocks, { range = 'ALL' } = {}) {
  if (range === 'ALL') return blocks;

  const now   = blocks[blocks.length - 1].date;
  const daysMap = { '1M': 30, '3M': 90, '6M': 180, '1Y': 365, '2Y': 730, '3Y': 1095, '5Y': 1825 };
  const cutoff = new Date(now);
  
  if (daysMap[range]) {
    cutoff.setUTCDate(cutoff.getUTCDate() - daysMap[range]);
  }
  return blocks.filter(b => b.date >= cutoff);
}

/**
 * Aggregate filtered blocks into pool counts.
 * Returns array sorted by count desc: [{ name, slug, count, pct }]
 */
export function aggregateByPool(blocks, field = 'pool_name') {
  const total = blocks.length;
  const counts = new Map();
  for (const b of blocks) {
    const key = b[field] || 'Unknown';
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return Array.from(counts.entries())
    .map(([name, count]) => ({ name, count, pct: count / total * 100 }))
    .sort((a, b) => b.count - a.count);
}

/**
 * Aggregate pool data into country shares.
 * Returns array sorted by count desc: [{ country, count }]
 */
export function aggregateByCountry(poolAgg, poolsInfo) {
  const counts = new Map();
  for (const p of poolAgg) {
    if (p.name === 'Unknown' || p.name === 'Other') continue;
    const info = poolsInfo.find(i => i.name === p.name);
    let c = info && info.country ? info.country : 'Unknown';
    // Count blocks by country
    counts.set(c, (counts.get(c) ?? 0) + p.count);
  }
  return Array.from(counts.entries())
    .map(([country, count]) => ({ country, count }))
    .sort((a, b) => b.count - a.count);
}

/**
 * Aggregate blocks into monthly time series per pool.
 * Returns { months: string[], pools: { [name]: number[] } }
 * Only includes top N pools by total blocks; rest merged into "Other".
 */
export function aggregateMonthly(blocks, topN = 12, field = 'pool_name') {
  // First find top N pool names (excluding 'Other' bucket)
  const totals = new Map();
  for (const b of blocks) {
    const name = b[field] || 'Unknown';
    totals.set(name, (totals.get(name) ?? 0) + 1);
  }
  
  const topPools = Array.from(totals.entries())
    .filter(([name]) => name !== 'Other') // Exclude generic 'Other' from top N selection
    .sort((a, b) => b[1] - a[1])
    .slice(0, topN)
    .map(([name]) => name);
  const topSet = new Set(topPools);

  // Build month → pool → count
  const monthMap = new Map();
  for (const b of blocks) {
    const d = b.date;
    const key = `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`;
    if (!monthMap.has(key)) monthMap.set(key, new Map());
    const rawName = b[field] || 'Unknown';
    const poolName = topSet.has(rawName) ? rawName : 'Other';
    const m = monthMap.get(key);
    m.set(poolName, (m.get(poolName) ?? 0) + 1);
  }

  const allMonths = Array.from(monthMap.keys()).sort();
  // Filter out partial months at the edges (threshold: ~1 week of blocks)
  const months = allMonths.filter(m => {
    const monthData = monthMap.get(m);
    const total = Array.from(monthData.values()).reduce((s, v) => s + v, 0);
    return total >= 500;
  });

  const poolNames = [...topPools, 'Other'];
  const series = {};
  for (const p of poolNames) {
    series[p] = months.map(m => monthMap.get(m)?.get(p) ?? 0);
  }

  // Compute HHI per month
  const hhi = months.map(m => {
    const monthData = monthMap.get(m);
    const total = Array.from(monthData.values()).reduce((s, v) => s + v, 0);
    if (total === 0) return 0;
    const shares = Array.from(monthData.values()).map(v => v / total);
    return shares.reduce((sum, s) => sum + s * s, 0) * 10000; // Scaled HHI
  });

  return { months, series, poolNames, hhi };
}


