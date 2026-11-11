import { loadData, loadParquetOnly, loadForensics, filterBlocks, aggregateByPool, aggregateByCountry, aggregateMonthly } from './data-loader.js?v=26';
import { 
  renderDonut, renderPoolTable, renderCountryShareChart, renderAreaChart, renderEcosystemGrowthChart, renderHhiChart, renderConcentrationChart, renderTopMinersTable, 
  renderStreaksLeaderboard, renderZScoreFunnel, renderEntropyHeatmap, renderSyncHistogram, renderConsecutiveAdvantage, renderEmptyBlockChart, renderEmptyTrendChart,
  renderBip110Signaling, renderBip110Efficiency, renderBip110Overhead,
  renderQuarterlyLift, renderTransitionMatrix,
  resizeAllCharts, donutChart, growthChart 
} from './charts.js?v=26';

let allBlocks   = [];
let poolMeta    = {};
let poolsInfo   = [];
let timelines   = [];
let lookupTable = {}; // Cached for background load
let slugToName  = {}; // slug → display name, used for forensics lookups
let ecosystem   = null;
let forensics   = null;

let post2021Blocks = null;
let fullHistoryBlocks = null;

let activeRange = '1Y';
let activeCountryRange = '1Y';
let activeTopPoolsRange = '1M';
let activePeriod = 'post'; // 'pre' or 'post'
let barMetric   = 'blocks';

const profileHandler = (e) => showProfileCard(e.detail);

function showProfileCard(poolName) {
  if (!poolName || poolName === 'Other') return;
  
  if (poolName === 'Unknown') {
     const input = document.getElementById('pool-search-input');
     if (input) input.value = 'Unknown';
     
     document.getElementById('profile-link').style.display = 'none';
     document.getElementById('profile-scoop').textContent = "Unknown blocks represent mining activity where the block's coinbase transaction does not contain a recognized pool identifier. This typically includes solo miners, newly emerging private pools, or legacy miners who have not yet identified themselves to the network.";
     
     const meta = poolMeta['Unknown'] || {};
     const snapshotBlocks = post2021Blocks || allBlocks;
     const last30Blocks = filterBlocks(snapshotBlocks, { range: '1M' });
     const last30Agg = aggregateByPool(last30Blocks);
     const poolEntry = last30Agg.find(p => p.name === 'Unknown');
     const sharePct = poolEntry ? poolEntry.pct : 0;
     
     document.getElementById('profile-first-block').innerHTML = `2009-01-09<br><span style="font-size: 0.8rem; color: var(--text-secondary); font-weight: normal;">Network Genesis</span>`;
     document.getElementById('profile-blocks').textContent = (meta.lifetime_blocks || 0).toLocaleString();
     document.getElementById('profile-share').textContent = sharePct.toFixed(2) + '%';
     
     document.getElementById('pool-profile-card').style.display = 'block';
     return;
  }
  const meta = poolMeta[poolName] || {};
  const info = poolsInfo.find(i => i.name === poolName) || {};
  
  const input = document.getElementById('pool-search-input');
  if (input) input.value = poolName; // Sync search input text
  
  const linkEl = document.getElementById('profile-link');
  if (meta.link) {
    linkEl.href = meta.link;
    linkEl.innerHTML = `${meta.link.replace(/^https?:\/\//, '')} <i class="fa-solid fa-external-link-alt" style="font-size: 0.75rem; margin-left: 2px;"></i>`;
    linkEl.style.display = 'inline-block';
  } else {
    linkEl.style.display = 'none';
    linkEl.href = '#';
  }
  
  document.getElementById('profile-scoop').textContent = info.the_scoop || 'No description available for this pool.';
  
  // Calculate dynamic share for the last 30 days based on the primary dataset
  // Use post2020Blocks if available to stay consistent with the modern dashboard focus
  const snapshotBlocks = post2021Blocks || allBlocks;
  const last30Blocks = filterBlocks(snapshotBlocks, { range: '1M' });
  const last30Agg = aggregateByPool(last30Blocks);
  const poolEntry = last30Agg.find(p => p.name === poolName);
  const sharePct = poolEntry ? poolEntry.pct : 0;
  
  // Use the static metadata generated from all blocks
  if (meta.first_block_mined) {
    document.getElementById('profile-first-block').innerHTML = `${meta.first_block_mined.toLocaleString()}<br><span style="font-size: 0.8rem; color: var(--text-secondary); font-weight: normal;">${meta.first_seen_date}</span>`;
    document.getElementById('profile-blocks').textContent = meta.lifetime_blocks.toLocaleString();
    document.getElementById('profile-share').textContent = sharePct.toFixed(2) + '%';
  } else {
    document.getElementById('profile-first-block').textContent = 'Unknown';
    document.getElementById('profile-blocks').textContent = '-';
    document.getElementById('profile-share').textContent = sharePct.toFixed(2) + '%';
  }
  
  document.getElementById('pool-profile-card').style.display = 'block';
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function fmt(n)    { return n.toLocaleString(); }
function fmtPct(n) { return n.toFixed(1) + '%'; }
function fmtDate(d) {
  return d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', timeZone: 'UTC' });
}
function fmtDay(d) {
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' });
}

function hideOverlay() {
  const el = document.getElementById('loading-overlay');
  el.classList.add('hidden');
  setTimeout(() => el.remove(), 500);
}

function showError(msg) {
  const el = document.getElementById('loading-overlay');
  el.innerHTML = `<p style="color:#f85149;font-size:.95rem;">⚠ ${msg}</p>`;
}


// ── Summary cards (Last 30 Days) ─────────────────────────────────────────────
function updateKPICards() {
  if (!allBlocks || allBlocks.length === 0) return;
  
  // Use post2020Blocks if available for KPIs to ensure they reflect the modern network
  const snapshotBlocks = post2021Blocks || allBlocks;
  const last30Blocks = filterBlocks(snapshotBlocks, { range: '1M' });
  const startD = last30Blocks[0].date;
  const endD   = last30Blocks[last30Blocks.length - 1].date;

  const poolNames = new Set();
  for (const b of last30Blocks) {
    if (b.pool_name !== 'Unknown') poolNames.add(b.pool_name);
  }
  
  const poolAgg = aggregateByPool(last30Blocks);
  const top     = poolAgg.find(p => p.name !== 'Unknown');

  // Share of top 3 known pools relative to ALL blocks in the slice
  const top3Pct = poolAgg.filter(p => p.name !== 'Unknown').slice(0, 3).reduce((s, p) => s + p.pct, 0);
  const hhi = poolAgg.reduce((sum, p) => sum + (p.pct / 100) ** 2, 0) * 10000;

  let hhiLevel = 'Healthy';
  if (hhi > 2500) hhiLevel = 'At Risk';
  else if (hhi > 1500) hhiLevel = 'Moderate';

  const rangeStr = `${fmtDay(startD)} — ${fmtDay(endD)}, ${endD.getUTCFullYear()}`;
  document.getElementById('val-latest-month').textContent = rangeStr;
  
  document.getElementById('val-unique-pools').textContent  = poolNames.size;
  document.getElementById('val-top-pool').textContent      = top?.name ?? '—';
  document.getElementById('val-top-pool-pct').textContent  = top ? fmtPct(top.pct) + ' of blocks' : '';
  document.getElementById('val-concentration').textContent = fmtPct(top3Pct);
  document.getElementById('val-hhi').textContent          = hhi.toFixed(0);
  document.getElementById('val-hhi-sub').innerHTML      = `${hhiLevel} Centralization Index <a href="https://en.wikipedia.org/wiki/Herfindahl%E2%80%93Hirschman_index" target="_blank">(About HHI)</a>`;
}

// ── Static Macro Charts (Unfiltered) ──────────────────────────────────────────
function initStaticMacroCharts() {
  // 1. Dominance Area chart reflects the active toggled period (all-time or post-2020)
  const monthlyArea = aggregateMonthly(allBlocks, 12);
  renderAreaChart({ ...monthlyArea, timelines });

  // 2. HHI and Concentration macro trends should ALWAYs remain focused on the modern era (Post-2020)
  // regardless of how far back the historical dominance area chart expands.
  const modernBlocks = post2021Blocks || allBlocks;
  const monthlyModern = aggregateMonthly(modernBlocks, 12);
  
  const { months, series, poolNames, hhi } = monthlyModern;
  const top3 = [];
  const top5 = [];
  
  for (let i = 0; i < months.length; i++) {
    let total = 0;
    let counts = [];
    for (const name of poolNames) {
      const v = series[name][i] || 0;
      total += v;
      if (name !== 'Unknown') counts.push(v);
    }
    counts.sort((a,b) => b - a);
    const t3Sum = counts.slice(0, 3).reduce((a,b) => a + b, 0);
    const t5Sum = counts.slice(0, 5).reduce((a,b) => a + b, 0);
    
    top3.push(total > 0 ? (t3Sum / total * 100) : 0);
    top5.push(total > 0 ? (t5Sum / total * 100) : 0);
  }

  // Render the static macro trend charts using modern data
  renderHhiChart({ months, hhi });
  renderConcentrationChart({ months, top3, top5 });
}

// ── Profile Dropdown / Search setup ──────────────────────────────────────────
let profileRegistry = { detailed: [], standard: [] };

function initProfileSelector() {
  const poolNamesSet = new Set();
  allBlocks.forEach(b => {
      if (b.pool_name && b.pool_name !== 'Other') poolNamesSet.add(b.pool_name);
  });
  
  const infoNames = new Set(poolsInfo.map(i => i.name));
  const detailed = [];
  const standard = [];
  
  poolNamesSet.forEach(name => {
    if (infoNames.has(name)) detailed.push(name);
    else standard.push(name);
  });

  detailed.sort((a,b) => a.localeCompare(b));
  standard.sort((a,b) => a.localeCompare(b));
  profileRegistry = { detailed, standard };

  renderProfileSearchList(''); // Init with empty filter
  
  const input = document.getElementById('pool-search-input');
  const list = document.getElementById('pool-results-list');

  input.addEventListener('focus', () => {
    renderProfileSearchList(input.value);
    list.classList.add('show');
  });

  input.addEventListener('input', (e) => {
    renderProfileSearchList(e.target.value);
  });

  // Close on click outside
  document.addEventListener('click', (e) => {
    if (!e.target.closest('.pool-search-container')) {
      list.classList.remove('show');
    }
  });
}

function renderProfileSearchList(query = '') {
  const list = document.getElementById('pool-results-list');
  const q = query.toLowerCase();
  
  const matchesDetailed = profileRegistry.detailed.filter(n => n.toLowerCase().includes(q));
  const matchesStandard = profileRegistry.standard.filter(n => n.toLowerCase().includes(q));
  
  if (matchesDetailed.length === 0 && matchesStandard.length === 0) {
    list.innerHTML = '<li class="pool-result-no-match">No results found</li>';
    return;
  }

  let html = '';
  if (matchesDetailed.length > 0) {
    html += '<li class="pool-result-group">Detailed Profiles</li>';
    html += matchesDetailed.map(n => `<li class="pool-result-item" data-value="${n}">${n}</li>`).join('');
  }
  if (matchesStandard.length > 0) {
    html += '<li class="pool-result-group">Other Pools</li>';
    html += matchesStandard.map(n => `<li class="pool-result-item" data-value="${n}">${n}</li>`).join('');
  }
  
  list.innerHTML = html;
  
  // Attach listeners to new items
  list.querySelectorAll('.pool-result-item').forEach(item => {
    item.addEventListener('click', () => {
      const val = item.getAttribute('data-value');
      document.dispatchEvent(new CustomEvent('request-profile', { detail: val }));
      list.classList.remove('show');
    });
  });
}

// ── Header date range ────────────────────────────────────────────────────────
// function updateHeader(filtered) {
//   // blocks are sorted ascending by height, so first/last = min/max date
//   const minD = filtered[0].date;
//   const maxD = filtered[filtered.length - 1].date;
//   document.getElementById('data-range-label').textContent =
//     `${fmtDate(minD)} – ${fmtDate(maxD)} · ${fmt(filtered.length)} blocks`;
// }

function renderAll() {
  // Snapshot charts (Donut, Table, Country) respect the active timeframe scope (1M, 3M, etc.)
  // We use post2020Blocks (the modern dataset) to ensure these stay relevant to current mining
  // regardless of whether the historical macro chart is showing the full 2009+ history.
  const snapshotBlocks = post2021Blocks || allBlocks;
  const filtered = filterBlocks(snapshotBlocks, { range: activeRange });
  
  const poolAgg = aggregateByPool(filtered);
  renderDonut(poolAgg, poolMeta, poolsInfo);
  renderPoolTable(poolAgg, poolMeta);

  // Snapshot for Country Share independently respects its active timeframe
  const filteredCountry = filterBlocks(snapshotBlocks, { range: activeCountryRange });
  const countryPoolAgg = aggregateByPool(filteredCountry);
  const countryAgg = aggregateByCountry(countryPoolAgg, poolsInfo);
  renderCountryShareChart(countryAgg);

  // 3. Top Mining Pools Table (Independent range filter)
  const topPoolsFiltered = filterBlocks(snapshotBlocks, { range: activeTopPoolsRange });
  const topPoolsAgg = aggregateByPool(topPoolsFiltered);
  renderTopMinersTable(topPoolsAgg, poolsInfo, forensics, slugToName, activeTopPoolsRange);

  // 4. Ecosystem chart uses entirely global data (spanning from genesis to present)
  renderEcosystemGrowthChart(ecosystem, poolMeta);

  // 5. Forensics
  if (forensics) {
    renderStreaksLeaderboard(forensics.kpi1_strikes);
    renderZScoreFunnel(forensics.kpi2_funnel);
    renderEntropyHeatmap(forensics.kpi3_entropy);
    renderSyncHistogram(forensics.kpi4_sync);
    renderConsecutiveAdvantage(forensics.kpi4_sync);
    renderQuarterlyLift(forensics.kpi4_sync);
    renderEmptyBlockChart(forensics.kpi5_empty_blocks);
    renderEmptyTrendChart(forensics.kpi5_empty_blocks.monthly_trend);
    
    // KPI 8: Cross-pool Transition Matrix
    if (forensics.kpi8_transitions) {
      renderTransitionMatrix(forensics.kpi8_transitions);
    }
    
    // BIP 110 Battleground
    if (forensics.kpi7_bip110) {
      renderBip110Signaling(forensics.kpi7_bip110.signaling_trend);
      renderBip110Efficiency(forensics.kpi7_bip110.efficiency_scatter);
      renderBip110Overhead(forensics.kpi7_bip110.overhead_bar);
    }
  }

  // Handle custom request-profile events from the new search UI
  document.removeEventListener('request-profile', profileHandler);
  document.addEventListener('request-profile', profileHandler);

  if (growthChart) {
    growthChart.off('click');
    growthChart.on('click', (params) => {
      if (params.seriesType === 'scatter') {
        showProfileCard(params.name);
        // Safely scroll to the manually positioned profile card container smoothly
        document.getElementById('pool-profile-card').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }
    });
  }

  // Update donut subtitle
  const label = `Last ${activeRange} · Market share (blocks)`;
  document.getElementById('donut-subtitle').textContent = label;

  const countryLabel = `Last ${activeCountryRange} · Geographic footprint`;
  document.getElementById('country-subtitle').textContent = countryLabel;
}

// ── Filter button wiring ──────────────────────────────────────────────────────
function wireFilters() {
  // Period buttons
  document.getElementById('period-buttons').addEventListener('click', async (e) => {
    const btn = e.target.closest('.filter-btn');
    if (!btn || btn.classList.contains('active')) return; 
    
    const period = btn.dataset.period;
    const container = document.getElementById('period-buttons');
    container.style.pointerEvents = 'none';
    container.style.opacity = '0.7';

    try {
      // Instant switch if data is already cached
      if (period === 'pre' && fullHistoryBlocks) {
        allBlocks = fullHistoryBlocks;
      } else if (period === 'post' && post2021Blocks) {
        allBlocks = post2021Blocks;
      } else {
        // Fallback to loading
        await loadAndRender(period);
      }
      
      // Update state and active classes
      activePeriod = period;
      document.querySelectorAll('#period-buttons .filter-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');

      // Note: We no longer sync activeRange to 'ALL' when period changes.
      // This allows the historical trend to expand without hijacking the snapshot charts.
      
      // Full re-render with new dataset; snapshot charts remain on their chosen ranges
      updateKPICards();
      initStaticMacroCharts();
      renderAll();
      
    } finally {
      container.style.pointerEvents = 'auto';
      container.style.opacity = '1';
    }
  });

  // Time range buttons (Pool Share)
  document.getElementById('range-buttons').addEventListener('click', (e) => {
    const btn = e.target.closest('.filter-btn');
    if (!btn) return;
    activeRange = btn.dataset.range;
    document.querySelectorAll('#range-buttons .filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    renderAll();
  });

  // Time range buttons (Country Share)
  document.getElementById('country-range-buttons').addEventListener('click', (e) => {
    const btn = e.target.closest('.filter-btn');
    if (!btn) return;
    activeCountryRange = btn.dataset.range;
    document.querySelectorAll('#country-range-buttons .filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    renderAll();
  });

  // Time range buttons (Top Mining Pools Table - Independent)
  const topPoolsContainer = document.getElementById('top-pools-range-buttons');
  if (topPoolsContainer) {
    topPoolsContainer.addEventListener('click', (e) => {
      const btn = e.target.closest('.segmented-btn');
      if (!btn || btn.classList.contains('active')) return;
      activeTopPoolsRange = btn.dataset.range;
      topPoolsContainer.querySelectorAll('.segmented-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      renderAll();
    });
  }
}

function wireInfoToggles() {
  document.querySelectorAll('.info-toggle').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      const targetId = btn.getAttribute('data-target');
      const card = document.getElementById(targetId);
      if (card) {
        const isShowing = card.classList.contains('show');
        // Close others if desired, or allow multiple to be open. Let's allow multiple.
        card.classList.toggle('show', !isShowing);
        btn.classList.toggle('active', !isShowing);
      }
    });
  });
}

// ── Load and render ───────────────────────────────────────────────────────────
async function loadAndRender(period) {
  try {
    // Show loading
    document.getElementById('loading-overlay').classList.remove('hidden');
    document.getElementById('loading-overlay').innerHTML = `
      <div class="spinner"></div>
      <p>Loading ${period === 'pre' ? 'full historical' : 'post-2021'} data…</p>
    `;

    let results;
    try {
      results = await Promise.all([
        loadData(period),
        loadForensics().catch(e => {
          console.warn("Forensics data not found or failed to load. Forensics tab will be empty.", e);
          return null; // Return null so the app continues
        })
      ]);
    } catch (e) {
      throw new Error(`Core data failed to load: ${e.message}`);
    }

    const dataset = results[0];
    forensics = results[1];

    allBlocks = dataset.blocks;
    poolMeta  = dataset.poolMeta;
    poolsInfo = dataset.poolsInfo;
    timelines = dataset.timelines;
    ecosystem = dataset.ecosystem;
    if (dataset.slugToName) slugToName = dataset.slugToName;
    
    // Cache the lookup table and blocks for background loading
      if (period === 'post') {
        post2021Blocks = allBlocks;
      } else {
        fullHistoryBlocks = allBlocks;
        // Guarantee post2021Blocks is set even if we somehow skipped the 'post' load
        if (!post2021Blocks) {
          const pivotDate = new Date('2021-01-01T00:00:00Z');
          post2021Blocks = allBlocks.filter(b => b.date >= pivotDate);
        }
      }

    updateKPICards();
    initStaticMacroCharts();
    initProfileSelector();
    initTabs();

    renderAll();
    
    // Default the profile card to the top pool
    const topPool = Object.keys(poolMeta).sort((a,b) => poolMeta[b].lifetime_blocks - poolMeta[a].lifetime_blocks)[0];
    if (topPool) showProfileCard(topPool);

  } catch (err) {
    console.error("Initialization Failed:", err);
    showError(`Failed to load data: ${err.message}`);
  } finally {
    hideOverlay();
  }
}

// ── Background Loading ───────────────────────────────────────────────────────
async function lazyLoadHistory() {
  try {
    // Only need pre-2020 blocks to combine with already loaded post-2020
    const res = await fetch('./data/lookup/lookup_slug_to_name.json');
    const lookup = await res.json();
    
    const preBlocks = await loadParquetOnly('./data/blocks_pre_2021.parquet?v=26', lookup);
    fullHistoryBlocks = [...preBlocks, ...post2021Blocks];
    console.log("Historical data loaded in background.");
  } catch (err) {
    console.warn("Background load failed:", err);
  }
}

// ── Entry point ───────────────────────────────────────────────────────────────
export async function initApp() {
  await loadAndRender('post');
  wireFilters();
  wireInfoToggles();
  
  // Start lazy loading once the dashboard is interactive
  setTimeout(lazyLoadHistory, 1000);
}
// ── Tab Management (Sync with Header Nav) ────────────────────────────────────
function initTabs() {
  const switchTab = (tabId) => {
    const slug = tabId.replace('#', '') || 'overview';
    const contents = document.querySelectorAll('.tab-content');
    let found = false;
    
    contents.forEach(content => {
      const isActive = content.id === `tab-${slug}`;
      content.classList.toggle('active', isActive);
      if (isActive) found = true;
    });

    // Update Header Nav active state
    // Use a small delay to ensure the shared app shell has finished rendering
    setTimeout(() => {
      document.querySelectorAll('.app-nav a, .nav-links a').forEach(a => {
        const href = a.getAttribute('href') || '';
        a.classList.toggle('active', href.endsWith(`#${slug}`));
      });
    }, 100);

    if (found) {
      setTimeout(resizeAllCharts, 150);
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
  };

  window.addEventListener('hashchange', () => switchTab(window.location.hash));
  
  // Handle initial hash on load
  if (window.location.hash) {
    switchTab(window.location.hash);
  }

  // Debounced global resize: guarantees all ECharts canvases reflow after
  // the CSS grid has finished re-calculating column widths.
  let _resizeTimer = null;
  window.addEventListener('resize', () => {
    clearTimeout(_resizeTimer);
    _resizeTimer = setTimeout(resizeAllCharts, 120);
  });
}
