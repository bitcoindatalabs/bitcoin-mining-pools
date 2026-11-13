/**
 * charts.js
 * All ECharts chart renderers.
 * Each function either initialises or updates a chart instance.
 */

const ec = () => window.__echarts;

// ── Shared palette (Bitcoin-themed, 15 distinct colours) ─────────────────────
export const POOL_COLORS = [
  '#E5C07B', '#7BAE7F', '#8AB4F8', '#E06C75', '#C678DD',
  '#56B6C2', '#98C379', '#F29F67', '#D19A66', '#61AFEF',
  '#ABB2BF', '#BE835D', '#A0B89C', '#879BBF', '#D4A0A4'
];

const THEME = {
  bg: '#161b22',
  bg2: '#21262d',
  border: '#30363d',
  text: '#e6edf3',
  muted: '#8b949e',
  accent: '#E2A34A',
};

const COUNTRY_FLAG = {
  'China': '🇨🇳',
  'United States': '🇺🇸',
  'Czech Republic': '🇨🇿',
  'Seychelles': '🇸🇨',
  'Japan': '🇯🇵',
  'Switzerland': '🇨🇭',
  'Global': '🌐',
  'Unknown': '?',
};

const COUNTRY_COLOR = {
  'China': 'rgba(255,100,80,0.18)',
  'United States': 'rgba(86,182,194,0.15)',
  'Czech Republic': 'rgba(152,195,121,0.15)',
  'Seychelles': 'rgba(197,120,221,0.15)',
  'Japan': 'rgba(255,180,80,0.15)',
  'Switzerland': 'rgba(189,51,64,0.15)',
  'Global': 'rgba(226,163,74,0.10)',
};

const COUNTRY_SLICE_COLOR = {
  'China': '#E63946',
  'United States': '#457B9D',
  'Czech Republic': '#2A9D8F',
  'Seychelles': '#9D4EDD',
  'Japan': '#F4A261',
  'Switzerland': '#D62828',
  'Global': '#F4A261',
  'Unknown': '#6C757D',
};

function countryBadge(country) {
  const flag = COUNTRY_FLAG[country] || '?';
  const bg = COUNTRY_COLOR[country] || 'rgba(139,148,158,0.1)';
  return `<span style="font-size:0.7rem;background:${bg};border-radius:3px;padding:1px 4px;margin-left:3px;" title="${country}">${flag}</span>`;
}

function baseTooltip(extra = {}) {
  return {
    backgroundColor: THEME.bg2,
    borderColor: THEME.border,
    borderWidth: 1,
    textStyle: { color: THEME.text, fontSize: 12 },
    ...extra,
  };
}

// ── Donut chart ───────────────────────────────────────────────────────────────
export let donutChart = null;

function buildProfileByNameMap(poolProfiles, slugToName = {}) {
  const byName = new Map();
  for (const [slug, prof] of Object.entries(poolProfiles || {})) {
    if (prof?.name) byName.set(prof.name.toLowerCase(), prof);
    if (slugToName[slug]) byName.set(slugToName[slug].toLowerCase(), prof);
  }
  return byName;
}

export function renderDonut(poolData, poolMeta, poolProfiles, slugToName = {}) {
  const el = document.getElementById('chart-donut');
  if (!donutChart) {
    donutChart = ec().init(el, null, { renderer: 'canvas' });
    window.addEventListener('resize', () => donutChart.resize());
  }

  const profileByName = buildProfileByNameMap(poolProfiles, slugToName);

  // Top 15 + aggregate rest into "Other"
  const TOP = 15;
  const top = poolData.slice(0, TOP);
  const other = poolData.slice(TOP).reduce((s, p) => s + p.count, 0);
  const total = poolData.reduce((s, p) => s + p.count, 0);

  const items = [
    ...top.map((p, i) => ({
      name: p.name,
      value: p.count,
      itemStyle: { color: POOL_COLORS[i % POOL_COLORS.length] },
    })),
    ...(other > 0 ? [{ name: 'Other', value: other, itemStyle: { color: '#444c56' } }] : []),
  ];

  donutChart.setOption({
    backgroundColor: 'transparent',
    tooltip: {
      ...baseTooltip({ confine: true }),
      trigger: 'item',
      formatter: (p) => {
        const pct = (p.value / total * 100).toFixed(2);
        const prof = profileByName.get((p.name || '').toLowerCase());
        const link = poolMeta[p.name]?.link || prof?.website;
        const nameStr = link
          ? `<a href="${link}" target="_blank" style="color:${THEME.accent}">${p.name}</a>`
          : p.name;
        let descLine = '';
        if (prof?.description) {
          const short = prof.description.length > 120
            ? prof.description.slice(0, 117) + '…'
            : prof.description;
          descLine = `<br/><span style="display:block;margin-top:4px;font-size:11px;color:${THEME.muted}">${short}</span>`;
        }
        return `${nameStr}<br/><b>${p.value.toLocaleString()}</b> blocks · <b>${pct}%</b>${descLine}`;
      },
    },
    series: [{
      type: 'pie',
      radius: ['42%', '72%'],
      center: ['50%', '50%'],
      avoidLabelOverlap: true,
      itemStyle: { borderColor: THEME.bg, borderWidth: 2 },
      label: { show: false },
      emphasis: {
        label: {
          show: true,
          fontSize: 13,
          fontWeight: 'bold',
          color: THEME.text,
          formatter: (p) => `${p.name}\n${Math.round(p.value / total * 100)}%`,
        },
        itemStyle: { shadowBlur: 16, shadowColor: 'rgba(226,163,74,0.4)' },
      },
      data: items,
    }],
  }, true);

  // Trigger profile lookup on slice click
  donutChart.off('click');
  donutChart.on('click', (p) => {
    document.dispatchEvent(new CustomEvent('request-profile', { detail: p.data.name || p.name }));
    document.getElementById('pool-profile-card').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  });
}

// ── Pool table (companion to donut) ──────────────────────────────────────────
export function renderPoolTable(poolData, poolMeta) {
  const el = document.getElementById('pool-table');
  const total = poolData.reduce((s, p) => s + p.count, 0);
  const maxPct = poolData[0]?.pct ?? 1;

  const rows = poolData.slice(0, 10).map((p, i) => {
    const nameCell = p.name;
    const barW = (p.pct / maxPct * 100).toFixed(1);
    const color = POOL_COLORS[i] ?? '#444c56';
    return `
      <tr class="pool-row" data-pool="${p.name}">
        <td class="td-rank">${i + 1}</td>
        <td class="td-name">${nameCell}</td>
        <td class="td-pct">${Math.round(p.pct)}%</td>
        <td class="td-bar">
          <div class="bar-track">
            <div class="bar-fill" style="width:${barW}%;background:${color}"></div>
          </div>
        </td>
      </tr>`;
  }).join('');

  el.innerHTML = `
    <div class="pool-table-inner">
      <table>
        <thead>
          <tr>
            <th class="td-rank">#</th>
            <th class="td-name">Pool</th>
            <th class="td-pct">Share</th>
            <th class="td-bar"></th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;

  // Add click listeners to rows to trigger profile lookup
  el.querySelectorAll('.pool-row').forEach(row => {
    row.addEventListener('click', () => {
      const pool = row.getAttribute('data-pool');
      document.dispatchEvent(new CustomEvent('request-profile', { detail: pool }));

      // Optional: scroll to the profile card smoothly
      document.getElementById('pool-profile-card').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    });
  });
}

// ── Country Share chart ──────────────────────────────────────────────────────
export let countryChart = null;

export function renderCountryShareChart(countryAgg) {
  const el = document.getElementById('chart-country');
  if (!countryChart) {
    countryChart = ec().init(el, null, { renderer: 'canvas' });
    window.addEventListener('resize', () => countryChart.resize());
  }

  const total = countryAgg.reduce((s, c) => s + c.count, 0);

  // Group top 10 countries and "Other"
  const TOP = 10;
  const top = countryAgg.slice(0, TOP);
  const other = countryAgg.slice(TOP).reduce((s, c) => s + c.count, 0);

  const items = [
    ...top.map((c, i) => ({
      name: c.country,
      value: c.count,
      itemStyle: { color: COUNTRY_SLICE_COLOR[c.country] || POOL_COLORS[(i + 3) % POOL_COLORS.length] },
    })),
    ...(other > 0 ? [{ name: 'Other', value: other, itemStyle: { color: '#444c56' } }] : []),
  ];

  countryChart.setOption({
    backgroundColor: 'transparent',
    tooltip: {
      ...baseTooltip({ confine: true }),
      trigger: 'item',
      formatter: (p) => {
        const rawPct = Number(p.value) / total * 100;
        const pctLabel = rawPct >= 2 ? Math.round(rawPct) : rawPct.toFixed(2);
        return `<b>${COUNTRY_FLAG[p.name] || ''} ${p.name}</b><br/>${Number(p.value).toLocaleString()} blocks · <b>${pctLabel}%</b>`;
      },
    },
    series: [{
      type: 'pie',
      radius: ['42%', '72%'],
      center: ['50%', '50%'],
      avoidLabelOverlap: true,
      itemStyle: { borderColor: THEME.bg, borderWidth: 2 },
      label: {
        show: true,
        position: 'outside',
        color: THEME.text,
        fontSize: 14,
        formatter: (p) => `${COUNTRY_FLAG[p.name] || ''}`,
      },
      labelLine: { show: true, length: 18, length2: 8, lineStyle: { color: 'rgba(255,255,255,0.25)' } },
      emphasis: {
        label: {
          show: true,
          fontSize: 16,
          fontWeight: 'bold',
          color: THEME.text,
          formatter: (p) => `${COUNTRY_FLAG[p.name] || ''}`,
        },
        itemStyle: { shadowBlur: 16, shadowColor: 'rgba(226,163,74,0.4)' },
      },
      data: items,
    }],
  }, true);
}

// ── Stacked area chart ────────────────────────────────────────────────────────
let areaChart = null;

export function renderAreaChart({ months, series, poolNames, timelines = [] }) {
  const el = document.getElementById('chart-area');
  if (!areaChart) {
    areaChart = ec().init(el, null, { renderer: 'canvas' });
    window.addEventListener('resize', () => areaChart.resize());
  }

  // Calculate totals to find Top 7 (excluding 'Other' bucket if present)
  const poolTotals = poolNames
    .filter(name => name !== 'Other')
    .map(name => ({
      name,
      total: series[name].reduce((sum, v) => sum + (v || 0), 0)
    })).sort((a, b) => b.total - a.total);

  const topNames = poolTotals.slice(0, 7).map(p => p.name);
  const topSet = new Set(topNames);

  const groupedSeries = {};
  topNames.forEach(name => groupedSeries[name] = [...series[name]]);
  groupedSeries['Other'] = new Array(months.length).fill(0);

  for (let i = 0; i < poolNames.length; i++) {
    const name = poolNames[i];
    if (!topSet.has(name)) {
      // This catch-all includes both the 'Other' bucket and any pools not in top 7
      for (let j = 0; j < months.length; j++) {
        groupedSeries['Other'][j] += (series[name][j] || 0);
      }
    }
  }

  const finalNames = [...topNames];
  if (groupedSeries['Other'].some(v => v > 0)) {
    finalNames.push('Other');
  }

  const seriesList = finalNames.map((name, i) => ({
    name,
    type: 'line',
    stack: 'total',
    smooth: true,
    symbol: 'none',
    areaStyle: { opacity: 0.85 },
    lineStyle: { width: 0 },
    color: name === 'Other' ? '#444c56' : POOL_COLORS[i % POOL_COLORS.length],
    emphasis: { focus: 'series' },
    data: groupedSeries[name],
  }));

  // Map timeline events to month keys
  const monthIndexByKey = new Map(months.map((m, idx) => [m, idx]));
  const parsedEvents = (timelines || []).map(t => {
    const d = new Date(t.date);
    const key = `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`;
    const idx = monthIndexByKey.get(key);
    return idx != null ? { index: idx, key, ...t } : null;
  }).filter(Boolean);

  // Build markLine entries for visible milestone markers
  const markLineData = parsedEvents.map(ev => ({
    xAxis: ev.key,
    name: ev.event,
    lineStyle: {
      color: THEME.accent,
      type: 'dashed',
      width: 2,
      opacity: 1,
    },
    label: {
      show: true,
      formatter: ev.event,
      color: THEME.text,
      rotate: 90,
      fontSize: 11,
      fontWeight: 'bold',
      padding: [4, 0, 0, 0],
    },
  }));

  // Helper series only to host markLine
  if (markLineData.length) {
    seriesList.push({
      name: 'Milestones',
      type: 'line',
      data: [],
      xAxisIndex: 0,
      yAxisIndex: 0,
      showSymbol: false,
      lineStyle: { opacity: 0 },
      markLine: {
        symbol: 'none',
        tooltip: {
          show: true,
          trigger: 'item',
          formatter: (params) => {
            const ev = parsedEvents.find(e => e.event === params.name);
            if (ev) {
              return `<b>${ev.event}</b><br/><span style="display:inline-block;max-width:250px;white-space:normal;font-size:11px;color:${THEME.muted};margin-top:4px;">${ev.description}</span>`;
            }
            return params.name;
          }
        },
        data: markLineData,
      },
    });
  }

  areaChart.setOption({
    backgroundColor: 'transparent',
    tooltip: {
      ...baseTooltip({ confine: true }),
      trigger: 'axis',
      axisPointer: { type: 'cross', label: { backgroundColor: THEME.bg2 } },
      formatter: (params) => {
        const month = params[0].axisValue;
        const total = params.reduce((s, p) => s + (p.value || 0), 0);
        const lines = params
          .filter(p => p.seriesName !== 'Milestones' && p.value > 0)
          .sort((a, b) => b.value - a.value)
          .map(p => `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${p.color};margin-right:4px"></span>${p.seriesName}: <b>${p.value}</b>`)
          .join('<br/>');
        const ev = parsedEvents.find(e => e.key === month);
        const evLine = ev
          ? `<br/><br/><span style="font-size:11px;color:${THEME.muted}"><b>${ev.event}</b><br/>${ev.description}</span>`
          : '';
        return `<b>${month}</b> · ${total} blocks<br/>${lines}${evLine}`;
      },
    },
    legend: {
      type: 'scroll',
      bottom: 36,
      textStyle: { color: THEME.muted, fontSize: 11 },
      pageTextStyle: { color: THEME.muted },
      pageIconColor: THEME.accent,
      pageIconInactiveColor: THEME.border,
      data: finalNames,
    },
    grid: { top: 16, left: 56, right: 16, bottom: 90 },
    xAxis: {
      type: 'category',
      data: months,
      axisLine: { lineStyle: { color: THEME.border } },
      axisLabel: { color: THEME.muted, fontSize: 11, rotate: 30 },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: THEME.border, type: 'dashed' } },
      axisLabel: { color: THEME.muted, fontSize: 11 },
    },
    series: seriesList,
  }, true);
}

// ── Bar chart (top pools) ─────────────────────────────────────────────────────
let barChart = null;

export function renderBarChart(poolData, metric = 'blocks') {
  const el = document.getElementById('chart-bar');
  if (!barChart) {
    barChart = ec().init(el, null, { renderer: 'canvas' });
    window.addEventListener('resize', () => barChart.resize());
  }

  const TOP = 20;
  // exclude Unknown for the bar chart to keep it meaningful
  const data = poolData
    .filter(p => p.name !== 'Unknown')
    .slice(0, TOP)
    .reverse(); // ECharts bar goes bottom→top

  const values = data.map(p => metric === 'pct' ? +p.pct.toFixed(2) : p.count);
  const labels = data.map(p => p.name);
  const colors = data.map((_, i) => POOL_COLORS[(TOP - 1 - i) % POOL_COLORS.length]);

  barChart.setOption({
    backgroundColor: 'transparent',
    tooltip: {
      ...baseTooltip(),
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params) => {
        const p = params[0];
        return metric === 'pct'
          ? `${p.name}: <b>${p.value}%</b>`
          : `${p.name}: <b>${p.value.toLocaleString()} blocks</b>`;
      },
    },
    grid: { top: 8, left: 100, right: 56, bottom: 8, containLabel: false },
    xAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: THEME.border, type: 'dashed' } },
      axisLabel: {
        color: THEME.muted, fontSize: 10,
        formatter: metric === 'pct' ? '{value}%' : (v) => v >= 1000 ? `${(v / 1000).toFixed(0)}k` : v,
      },
    },
    yAxis: {
      type: 'category',
      data: labels,
      axisLine: { lineStyle: { color: THEME.border } },
      axisLabel: { color: THEME.text, fontSize: 11 },
      axisTick: { show: false },
    },
    series: [{
      type: 'bar',
      data: values.map((v, i) => ({ value: v, itemStyle: { color: colors[i] } })),
      barMaxWidth: 18,
      label: {
        show: true,
        position: 'right',
        color: THEME.muted,
        fontSize: 10,
        formatter: metric === 'pct' ? '{c}%' : (p) => p.value >= 1000 ? `${(p.value / 1000).toFixed(1)}k` : p.value,
      },
    }],
  }, true);
}

// ── Ecosystem Growth Chart (Line + Scatter) ──────────────────────────────────────────────
export let growthChart = null;

export function renderEcosystemGrowthChart({ months, cumulativePools }, poolMeta) {
  const el = document.getElementById('chart-line');
  if (!growthChart) {
    growthChart = ec().init(el, null, { renderer: 'canvas' });
    window.addEventListener('resize', () => growthChart.resize());
  }

  // Calculate the global max timestamp to act as "today" for bucket comparisons
  let maxTime = 0;
  Object.values(poolMeta).forEach(m => {
    if (m.last_seen_date) {
      const t = new Date(m.last_seen_date).getTime();
      if (t > maxTime) maxTime = t;
    }
  });

  const MS_IN_DAY = 86400 * 1000;
  const t3M = maxTime - 90 * MS_IN_DAY;
  const t1Y = maxTime - 365 * MS_IN_DAY;

  // Categories
  const CAT_3M = 'Active (Last 3 Months)';
  const CAT_1Y = 'Active (Last 1 Year)';
  const CAT_OLD = 'Inactive (>1 Year)';

  // Map month key to the Y value of the cumulative line at that month
  const monthToY = new Map(months.map((m, i) => [m, cumulativePools[i]]));

  const scatterBuckets = {
    [CAT_3M]: [],
    [CAT_1Y]: [],
    [CAT_OLD]: []
  };

  // Find Top 20 Active pools by lifetime blocks
  const activePoolList = Object.entries(poolMeta)
    .filter(([name, meta]) => meta.last_seen_date && new Date(meta.last_seen_date).getTime() >= t1Y && name !== 'Unknown' && name !== 'Other')
    .sort((a, b) => b[1].lifetime_blocks - a[1].lifetime_blocks)
    .slice(0, 20);
  const top20ActiveNames = new Set(activePoolList.map(entry => entry[0]));

  Object.entries(poolMeta).forEach(([name, meta]) => {
    if (meta.first_seen_date && name !== 'Unknown' && name !== 'Other') {
      const monthKey = meta.first_seen_date.substring(0, 7); // e.g. "2020-10"
      if (monthToY.has(monthKey)) {
        const yVal = monthToY.get(monthKey);

        const lastTime = new Date(meta.last_seen_date).getTime();
        let category = CAT_OLD;
        if (lastTime >= t3M) category = CAT_3M;
        else if (lastTime >= t1Y) category = CAT_1Y;

        const isTop20 = top20ActiveNames.has(name);

        const point = {
          name,
          isTop20,
          value: [
            monthKey,
            yVal,
            meta.first_seen_date,
            meta.first_block_mined,
            meta.last_block_mined,
            meta.lifetime_blocks,
            meta.last_seen_date
          ],
          itemStyle: {},
        };

        // Highlight Top 20
        if (isTop20) {
          point.label = {
            show: true,
            formatter: '{b}', // Name
            position: 'top',
            distance: 5,
            color: THEME.text,
            fontSize: 10,
            textBorderColor: THEME.bg,
            textBorderWidth: 2
          };
        }

        // Fade out inactive
        if (category === CAT_OLD) {
          point.itemStyle = { color: '#555', opacity: 0.3, borderColor: 'transparent' };
        }

        scatterBuckets[category].push(point);
      }
    }
  });

  // Common scatter series template
  const createScatterSeries = (name, color, data) => {
    // Sort so smallest bubbles are on top
    data.sort((a, b) => b.value[5] - a.value[5]);
    return {
      name: name,
      type: 'scatter',
      data: data,
      z: 10,
      labelLayout: {
        moveOverlap: 'shiftY' // "Ziggle" labels up/down to strictly prevent collisions
      },
      symbolSize: function (val, params) {
        const blocks = val[5];
        let size = 4 + (Math.log10(blocks || 1) * 3);
        if (params.data.isTop20) size += 6; // Boost size
        return Math.min(Math.max(size, 4), params.data.isTop20 ? 25 : 15);
      },
      itemStyle: {
        color: color,
        opacity: 0.9,
        shadowBlur: 4,
        shadowColor: 'rgba(0, 0, 0, 0.4)',
        borderColor: THEME.bg,
        borderWidth: 1
      },
      emphasis: {
        focus: 'self',
        itemStyle: { opacity: 1, borderColor: '#fff', borderWidth: 1 }
      }
    };
  };

  growthChart.setOption({
    backgroundColor: 'transparent',
    animation: false,
    tooltip: {
      ...baseTooltip(),
      trigger: 'item',
      formatter: (params) => {
        if (params.seriesName === 'Cumulative Pools (Line)') {
          return `<b>${params.name}</b><br/>Cumulative unique pools: <b>${params.value}</b>`;
        }
        const d = params.data.value; // [monthKey, yVal, date, first_block, last_block, lifetime, last_seen]
        return `<div style="margin-bottom: 4px; border-bottom: 1px solid ${THEME.border}; padding-bottom: 4px;">
                  <b style="color:${params.color}">${params.data.name}</b>
                  <span style="margin-left: 6px; font-size: 10px; color: ${THEME.muted};">(${params.seriesName})</span>
                </div>
                First Seen: <b>${d[2]}</b> (Block ${d[3].toLocaleString()})<br/>
                Last Block : <b>${d[6]}</b> (Block ${d[4].toLocaleString()})<br/>
                Total Mined: <b>${d[5].toLocaleString()}</b> blocks`;
      },
    },
    legend: {
      data: [CAT_3M, CAT_1Y, CAT_OLD],
      top: 0,
      textStyle: { color: THEME.muted, fontSize: 11 },
      icon: 'circle'
    },
    grid: { top: 32, left: 56, right: 30, bottom: 48 },
    xAxis: {
      type: 'category',
      data: months,
      axisLine: { lineStyle: { color: THEME.border } },
      axisLabel: { color: THEME.muted, fontSize: 11, rotate: 30 },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      name: 'Cumulative Unique Pools',
      nameLocation: 'middle',
      nameGap: 40,
      nameTextStyle: { color: THEME.muted, fontSize: 11 },
      splitLine: { lineStyle: { color: THEME.border, type: 'dashed' } },
      axisLabel: { color: THEME.muted, fontSize: 11 },
    },
    series: [
      {
        name: 'Cumulative Pools (Line)',
        type: 'line',
        data: cumulativePools,
        smooth: true,
        symbol: 'none',
        lineStyle: { color: THEME.border, width: 2, type: 'dashed' },
        areaStyle: { opacity: 0.1, color: THEME.border },
        z: 2
      },
      createScatterSeries(CAT_3M, '#6db874', scatterBuckets[CAT_3M]), // Bright Green
      createScatterSeries(CAT_1Y, '#E5C07B', scatterBuckets[CAT_1Y]), // Yellowish
      createScatterSeries(CAT_OLD, '#6b7280', scatterBuckets[CAT_OLD]) // Handled by override, base color ignored 
    ],
  }, true);

  // Force a layout refresh after the chart option is applied, especially on tab-load.
  window.requestAnimationFrame(() => growthChart.resize());
}

// ── HHI Trend Chart ───────────────────────────────────────────────────────────
let hhiChart = null;

export function renderHhiChart({ months, hhi }) {
  const el = document.getElementById('chart-hhi');
  if (!hhiChart) {
    hhiChart = ec().init(el, null, { renderer: 'canvas' });
    window.addEventListener('resize', () => hhiChart.resize());
  }

  hhiChart.setOption({
    backgroundColor: 'transparent',
    tooltip: {
      ...baseTooltip(),
      trigger: 'axis',
      axisPointer: { type: 'cross', label: { backgroundColor: THEME.bg2 } },
      formatter: (params) => {
        const month = params[0].axisValue;
        const val = params[0].value;
        let hhiLevel = 'Healthy Pool Decentralization';
        if (val > 2500) hhiLevel = 'High Pool Centralization (At Risk)';
        else if (val > 1500) hhiLevel = 'Moderate Pool Centralization';
        return `<b>${month}</b><br/>HHI: <b>${val.toFixed(0)}</b><br/><span style="font-size:11px;color:${THEME.muted}">${hhiLevel}</span>`;
      },
    },
    grid: { top: 16, left: 56, right: 16, bottom: 48 },
    xAxis: {
      type: 'category',
      data: months,
      axisLine: { lineStyle: { color: THEME.border } },
      axisLabel: { color: THEME.muted, fontSize: 11, rotate: 30 },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      name: 'Mining Centralization Index (HHI)',
      nameLocation: 'middle',
      nameGap: 45,
      nameTextStyle: { color: THEME.muted, fontSize: 11 },
      min: 500,
      max: 3500,
      splitLine: { lineStyle: { color: THEME.border, type: 'dashed' } },
      axisLabel: { color: THEME.muted, fontSize: 11 },
    },
    visualMap: {
      show: false,
      pieces: [
        { gt: 0, lte: 1500, color: THEME.accent },
        { gt: 1500, lte: 2500, color: POOL_COLORS[7] },
        { gt: 2500, color: POOL_COLORS[3] }
      ],
      outOfRange: { color: '#999' }
    },
    series: [{
      type: 'line',
      data: hhi,
      smooth: true,
      symbol: 'none',
      lineStyle: { width: 3 },
      areaStyle: { opacity: 0.15 },
      markLine: {
        symbol: 'none',
        label: {
          formatter: '{b}',
          position: 'insideStartTop',
          fontSize: 10,
          color: THEME.muted
        },
        lineStyle: { opacity: 0.8 },
        data: [
          { yAxis: 1500, name: 'Moderate Threshold (1,500)', lineStyle: { color: POOL_COLORS[7], type: 'dashed' } },
          { yAxis: 2500, name: 'Concentration Risk (2,500)', lineStyle: { color: POOL_COLORS[3], type: 'dashed' } }
        ]
      }
    }],
  }, true);
}

// ── Concentration Chart ───────────────────────────────────────────────────────
let concentrationChart = null;

export function renderConcentrationChart({ months, top3, top5 }) {
  const el = document.getElementById('chart-concentration');
  if (!concentrationChart) {
    concentrationChart = ec().init(el, null, { renderer: 'canvas' });
    window.addEventListener('resize', () => concentrationChart.resize());
  }

  concentrationChart.setOption({
    backgroundColor: 'transparent',
    tooltip: {
      ...baseTooltip(),
      trigger: 'axis',
      axisPointer: { type: 'cross', label: { backgroundColor: THEME.bg2 } },
      formatter: (params) => {
        const month = params[0].axisValue;
        const lines = params
          .sort((a, b) => b.value - a.value)
          .map(p => `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${p.color};margin-right:4px"></span>${p.seriesName}: <b>${p.value.toFixed(1)}%</b>`)
          .join('<br/>');
        return `<b>${month}</b><br/>${lines}`;
      },
    },
    legend: {
      top: 0,
      right: 0,
      textStyle: { color: THEME.muted, fontSize: 11 },
      icon: 'circle'
    },
    grid: { top: 32, left: 56, right: 16, bottom: 48 },
    xAxis: {
      type: 'category',
      data: months,
      axisLine: { lineStyle: { color: THEME.border } },
      axisLabel: { color: THEME.muted, fontSize: 11, rotate: 30 },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      name: 'Combined Share of Blocks mined (%)',
      nameLocation: 'middle',
      nameGap: 40,
      nameTextStyle: { color: THEME.muted, fontSize: 11 },
      min: 20,
      max: 100,
      splitLine: { lineStyle: { color: THEME.border, type: 'dashed' } },
      axisLabel: { color: THEME.muted, fontSize: 11, formatter: '{value}%' },
    },
    series: [
      {
        name: 'Top 5 Pools',
        type: 'line',
        data: top5,
        smooth: true,
        symbol: 'none',
        lineStyle: { width: 3, color: POOL_COLORS[2] },
        areaStyle: { opacity: 0.1, color: POOL_COLORS[2] },
      },
      {
        name: 'Top 3 Pools',
        type: 'line',
        data: top3,
        smooth: true,
        symbol: 'none',
        lineStyle: { width: 3, color: POOL_COLORS[0] },
        areaStyle: { opacity: 0.2, color: POOL_COLORS[0] },
      }
    ]
  }, true);
}

// ── Top 30 Mining Pools Table ────────────────────────────────────────────────
export function renderTopMinersTable(poolAgg, poolProfiles, forensics = null, slugToName = {}, topPoolsRange = '1M') {
  const el = document.getElementById('top-miners-table-container');
  if (!el) return;

  const profileByName = buildProfileByNameMap(poolProfiles, slugToName);

  // Build maps keyed by *display name* so the lookup is a direct p.name match.
  // Resolving each forensics slug through slugToName (the same lookup used when
  // building pool_name in data-loader) avoids re-slugify mismatches like
  // Ocean.xyz → 'oceanxyz' vs forensics key 'ocean'.
  const emptyByName = {};  // display name → kpi5 entry
  const densityByName = {}; // display name → kpi6 entry

  let rangeEmptyByName = {};
  const rangeMonthsMap = { '1M': 1, '3M': 3, '1Y': 12, '3Y': 36 };
  const rangeMonths = rangeMonthsMap[topPoolsRange] || 12;

  if (forensics) {
    (forensics.kpi5_empty_blocks?.leaderboard || []).forEach(e => {
      const displayName = slugToName[e.pool] || e.pool;
      emptyByName[displayName] = e;
    });
    (forensics.kpi6_density || []).forEach(e => {
      const displayName = slugToName[e.pool] || e.pool;
      densityByName[displayName] = e;
    });

    const monthlyTrend = forensics.kpi5_empty_blocks?.monthly_trend || [];
    if (monthlyTrend.length > 0) {
      const months = Array.from(new Set(monthlyTrend.map(item => item.month))).sort();
      const selectedMonths = new Set(months.slice(-rangeMonths));
      monthlyTrend.forEach(item => {
        if (!selectedMonths.has(item.month)) return;
        const displayName = slugToName[item.pool_name] || item.pool_name;
        if (!rangeEmptyByName[displayName]) {
          rangeEmptyByName[displayName] = { total: 0, empty: 0 };
        }
        rangeEmptyByName[displayName].total += Number(item.total || 0);
        rangeEmptyByName[displayName].empty += Number(item.empty || 0);
      });
    }
  }

  const rows = poolAgg.slice(0, 30).map((p, i) => {
    const prof = profileByName.get((p.name || '').toLowerCase());

    let country = prof?.country;
    if (!country) {
      country = (p.name === 'Unknown') ? 'Unknown' : 'Unknown';
    }

    // Match forensics data by display name directly
    const emptyData   = emptyByName[p.name];
    const densityData = densityByName[p.name];
    const rangeEmpty  = rangeEmptyByName[p.name];

    // Empty block % — use the selected top-pools time range when available,
    // otherwise fall back to the existing KPI5 leaderboard value.
    let emptyCell = '<span style="color:var(--text-secondary);opacity:0.4;">—</span>';
    if (rangeEmpty && rangeEmpty.total > 0) {
      const ratio = rangeEmpty.empty / rangeEmpty.total * 100;
      let dotColor = '#98C379';  // green ≤ 0.3%
      if (ratio > 1.5)      dotColor = '#ff4d4f';    // red
      else if (ratio > 0.5) dotColor = '#ffe066';    // yellow
      emptyCell = `<span style="display:inline-flex;align-items:center;gap:5px;">
        <span style="width:7px;height:7px;border-radius:50%;background:${dotColor};flex-shrink:0;"></span>
        ${ratio.toFixed(1)}%
      </span>`;
    } else if (emptyData) {
      const ratio = emptyData.ratio_30d != null ? emptyData.ratio_30d : emptyData.ratio_all;
      let dotColor = '#98C379';
      if (ratio > 1.5)      dotColor = '#ff4d4f';
      else if (ratio > 0.5) dotColor = '#ffe066';
      emptyCell = `<span style="display:inline-flex;align-items:center;gap:5px;">
        <span style="width:7px;height:7px;border-radius:50%;background:${dotColor};flex-shrink:0;"></span>
        ${ratio.toFixed(1)}%
      </span>`;
    }

    // Avg tx count
    let txCell = '<span style="color:var(--text-secondary);opacity:0.4;">—</span>';
    if (densityData && densityData.avg_tx_count != null) {
      txCell = Math.round(densityData.avg_tx_count).toLocaleString();
    }

    return `
      <tr class="pool-row" data-pool="${p.name}">
        <td style="width: 40px; color: var(--text-secondary); font-size: 0.8rem;">${i + 1}</td>
        <td style="font-weight: 600; color: var(--text-primary); min-width: 180px;">${p.name}</td>
        <td style="color: var(--text-secondary); font-size: 0.85rem; min-width: 150px;">
          ${countryBadge(country)} ${country}
        </td>
        <td style="text-align: right; font-weight: 600; color: var(--accent); padding-right: 20px;">${p.pct.toFixed(2)}%</td>
        <td style="text-align: right; font-size: 0.85rem; padding-right: 20px;">${emptyCell}</td>
        <td style="text-align: right; font-size: 0.85rem; color: var(--text-secondary); padding-right: 20px;">${txCell}</td>
      </tr>
    `;
  }).join('');

  el.innerHTML = `
    <div class="top-miners-scroll">
      <table class="top-miners-table">
        <thead>
          <tr>
            <th style="width: 40px;">#</th>
            <th>Miner / Pool Identity</th>
            <th>Base of Operations</th>
            <th style="text-align: right; padding-right: 20px;">Block Share</th>
            <th style="text-align: right; padding-right: 20px;" title="% of blocks mined with no transactions (30-day)">Empty Blk %</th>
            <th style="text-align: right; padding-right: 20px;" title="Average transaction count per block (post-2021)">Avg Txs / Blk</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;

  // Attach listeners for profile lookup
  el.querySelectorAll('.pool-row').forEach(row => {
    row.addEventListener('click', () => {
      const pool = row.getAttribute('data-pool');
      document.dispatchEvent(new CustomEvent('request-profile', { detail: pool }));
      document.getElementById('pool-profile-card').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    });
  });
}

// ── Resize all ────────────────────────────────────────────────────────────────
export function resizeAll() {
  donutChart?.resize();
  countryChart?.resize();
  areaChart?.resize();
  barChart?.resize();
  growthChart?.resize();
  hhiChart?.resize();
  concentrationChart?.resize();
}

// ── KPI 1: Streaks Leaderboard ────────────────────────────────────────────────
export function renderStreaksLeaderboard(poolSummaries) {
  const el = document.getElementById('forensics-streaks-table');
  if (!el || !poolSummaries || poolSummaries.length === 0) return;

  // 1. Render Leaderboard Rows
  const rows = poolSummaries.map((p, i) => {
    // Determine propensity color
    let propColor = '#8ab4f8';
    let propLabel = 'Normal';
    if (p.propensity > 2.0) { propColor = '#ff4d4f'; propLabel = 'Extremely High'; }
    else if (p.propensity > 1.3) { propColor = '#ffe066'; propLabel = 'High'; }
    else if (p.propensity < 0.7) { propColor = '#98C379'; propLabel = 'Low'; }

    // Prepare Grouped View (By Length)
    // distribution: { "10": 2, "9": 5, ... }
    // events: [ {count: 10, start_time: ...}, ... ]
    const lengths = Object.keys(p.distribution).sort((a, b) => b - a);

    const drillDownRows = lengths.map(len => {
      const lenEvents = p.events.filter(e => e.count == len);
      const count = p.distribution[len];

      // Robust likelihood calculation (use event data or falls back to share-based math)
      let years;
      if (lenEvents.length > 0 && lenEvents[0].expected_1_in_years !== undefined) {
        years = lenEvents[0].expected_1_in_years;
      } else {
        const p_val = p.pool_share / 100;
        const prob_start = Math.pow(p_val, parseInt(len)) * (1 - p_val);
        const exp_blocks = prob_start > 0 ? 1 / prob_start : 10 ** 10;
        years = exp_blocks / (144 * 365.25);
      }

      let likelihoodStr = years > 50
        ? '> 50 Years'
        : (years < 0.1
          ? `${(years * 12).toFixed(1)} Mos`
          : `${years.toFixed(1)} Yrs`);

      const occurrences = lenEvents.length > 0
        ? lenEvents.map(e => {
            const d = new Date(e.start_time);
            const dateStr = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
            const heightLabel = e.end_height && e.end_height !== e.start_height
              ? `#${e.start_height.toLocaleString()} – ${e.end_height.toLocaleString()}`
              : `#${e.start_height.toLocaleString()}`;
            return `<a href="https://mempool.space/block/${e.start_height}" target="_blank" rel="noopener noreferrer"
                       style="display:inline-flex;flex-direction:column;align-items:flex-start;gap:2px;
                              background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.1);
                              border-radius:5px;padding:5px 9px;text-decoration:none;"
                       onmouseover="this.style.borderColor='var(--accent)';this.style.background='rgba(226,163,74,0.08)'"
                       onmouseout="this.style.borderColor='rgba(255,255,255,0.1)';this.style.background='rgba(255,255,255,0.04)'">
                <span style="font-size:0.78rem;color:var(--text-primary);font-weight:500;white-space:nowrap;">${dateStr}</span>
                <span style="font-size:0.68rem;color:var(--accent);font-weight:600;font-family:monospace;">${heightLabel} ↗</span>
              </a>`;
          }).join('')
        : '<span style="font-style: italic; opacity: 0.5;">Historical record (heights not in recent sample)</span>';

      return `
        <tr>
          <td style="font-weight: 700; color: var(--accent); white-space: nowrap; padding: 10px 0; vertical-align: top;">
            ${len} Blocks
            <span style="display:block; font-size: 0.65rem; color: var(--text-secondary); font-weight: 400; margin-top: 2px;">
              ${count} Occurrence${count > 1 ? 's' : ''}
            </span>
          </td>
          <td style="text-align: center; color: var(--text-primary); font-weight: 500; vertical-align: top; padding-top: 12px;">1 in ${likelihoodStr}</td>
          <td style="padding-left: 15px; vertical-align: top; padding-top: 8px;">
            <div style="display:flex;flex-wrap:wrap;gap:6px;">${occurrences}</div>
          </td>
        </tr>
      `;
    }).join('');

    return `
    <tr class="pool-streak-row" data-pool="${p.pool}">
      <td style="width: 30px; opacity: 0.5;">${i + 1}</td>
      <td style="font-weight: 700; color: var(--text-primary)">
        <i class="fa-solid fa-chevron-right" style="font-size: 0.7rem; margin-right: 8px; transition: transform 0.2s;"></i>
        ${p.pool}
        <span style="font-weight: normal; font-size: 0.75rem; color: var(--text-secondary); margin-left: 6px;" title="Block-weighted average share from this pool's first qualifying streak month through present">(${p.pool_share}% era avg)</span>
      </td>
      <td style="text-align: center;">
         <div style="display:flex; flex-direction:column; align-items:center; gap:4px;">
           <span class="streak-badge" style="background: rgba(138, 180, 248, 0.1); color: #8ab4f8; border-color: rgba(138, 180, 248, 0.3); min-width:80px;">
             ${p.total_events} ${p.total_events === 1 ? 'Event' : 'Events'}
           </span>
           <span style="font-size: 0.65rem; color: ${propColor}; font-weight:bold; opacity:0.8;">${p.propensity}x propensity</span>
         </div>
      </td>
      <td style="text-align: right;"><span class="streak-badge" style="color: #fff; background: rgba(255,255,255,0.1);">${p.max_streak} Max</span></td>
    </tr>
    <tr class="pool-streak-detail" style="display: none;">
      <td colspan="4" style="padding: 0 15px 15px 40px; border-bottom: none;">
        <div style="background: rgba(22, 27, 34, 0.5); padding: 14px; border-radius: 8px; border-left: 3px solid ${propColor};">
          <div style="display:flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
            <div style="font-size: 0.7rem; text-transform: uppercase; color: var(--text-secondary); letter-spacing: 0.05em; font-weight: 700;">Historical Streak Distribution</div>
            <div style="font-size: 0.7rem; padding: 2px 8px; border-radius: 4px; background: ${propColor}22; color: ${propColor}; border: 1px solid ${propColor}44; font-weight: bold;">
               ${propLabel} Profile
            </div>
          </div>
          <table style="width: 100%; font-size: 0.85rem; border-collapse: collapse;">
            <thead>
              <tr style="border-bottom: 1px solid rgba(255,255,255,0.05);">
                <th style="text-align: left; padding: 5px 0; color: var(--text-secondary); font-size: 0.75rem; width: 120px;">Length (Count)</th>
                <th style="text-align: center; color: var(--text-secondary); font-size: 0.75rem; width: 120px;">Likelihood</th>
                <th style="text-align: left; color: var(--text-secondary); font-size: 0.75rem; padding-left: 15px;">Occurrences — click block height to explore on mempool.space</th>
              </tr>
            </thead>
            <tbody>${drillDownRows}</tbody>
          </table>
          ${(() => {
        const name = p.pool.toLowerCase();
        if (name.includes('foundry')) {
          return `
                   <div style="margin-top: 15px; padding-top: 12px; border-top: 1px solid rgba(255,255,255,0.1); font-size: 0.75rem; color: var(--text-secondary); line-height:1.5;">
                     <strong style="color: var(--accent); text-transform: uppercase; font-size: 0.65rem; letter-spacing: 0.05em; display: block; margin-bottom: 5px;">Network Reconnaissance Brief</strong>
                     <strong>STREAK COUNT ABOVE EXPECTATION:</strong> Foundry USA's 7+ block streak count is <strong>${p.propensity}× the block-weighted Poisson expectation</strong> at their hash share (${p.pool_share}%, 2022 – present) — but the sample of qualifying events is small, and the excess falls within plausible random variance for a rapidly-growing pool. This is a streak <em>frequency</em> metric, not a second-block conversion rate. Notably, their Second Block Uplift (KPI4b) sits near baseline (~1.0×), which argues against header-first / spy-mining as the cause. The more likely explanation is <strong>hashrate variance and geographic clustering</strong> of US-based miners consolidating under one pool — producing run-length variance without the mempool-skipping fingerprint.
                   </div>
                 `;
        }
        if (name === 'f2pool') {
          const streakMonthShare = p.events?.[0]?.pool_share || null;
          return `
                   <div style="margin-top: 15px; padding-top: 12px; border-top: 1px solid rgba(255,255,255,0.1); font-size: 0.75rem; color: var(--text-secondary); line-height:1.5;">
                     <strong style="color: var(--accent); text-transform: uppercase; font-size: 0.65rem; letter-spacing: 0.05em; display: block; margin-bottom: 5px;">Network Reconnaissance Brief</strong>
                     <strong>STREAK CONTEXT:</strong> F2Pool's 7-block streak occurred when its share in the streak month was ${streakMonthShare}%, higher than its long-run average. The wider forensics do not show a sustained second-block uplift signal for F2Pool, so this appears more like a high-share variance outlier than a persistent header-first or mempool-skipping pattern.
                   </div>
                 `;
        }
        return '';
      })()}
        </div>
      </td>
    </tr>
  `;
  }).join('');

  el.innerHTML = `
    <div class="forensic-table-wrapper">
      <table class="forensic-table streak-leaderboard">
        <thead>
          <tr>
            <th>#</th>
            <th>Pool Identity</th>
            <th style="text-align: center;">Frequency (≥7)</th>
            <th style="text-align: right;">Record</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;

  // 4. Wire Toggle Interactivity
  el.querySelectorAll('.pool-streak-row').forEach(row => {
    row.addEventListener('click', () => {
      const next = row.nextElementSibling;
      const chevron = row.querySelector('.fa-chevron-right');
      const isOpen = next.style.display !== 'none';

      next.style.display = isOpen ? 'none' : 'table-row';
      chevron.style.transform = isOpen ? 'rotate(0deg)' : 'rotate(90deg)';
      row.classList.toggle('active', !isOpen);
    });
  });
}

// ── KPI 2: Z-Score Funnel (Scatter) ──────────────────────────────────────────
export let zscoreChart = null;
export function renderZScoreFunnel(funnelData) {
  const el = document.getElementById('chart-zscore-funnel');
  if (!el || !funnelData || funnelData.length === 0) return;
  if (!zscoreChart) {
    zscoreChart = ec().init(el, null, { renderer: 'canvas' });
    window.addEventListener('resize', () => zscoreChart.resize());
  }

  // Group by pool; extract date (YYYY-MM-DD) from ISO timestamp
  const toDate = ts => ts.slice(0, 10);
  const poolMap = {};
  funnelData.forEach(r => {
    if (!poolMap[r.pool]) poolMap[r.pool] = {};
    const dt = toDate(r.timestamp);
    // keep latest entry if multiple on same date
    if (!poolMap[r.pool][dt] || r.timestamp > poolMap[r.pool][dt].timestamp) {
      poolMap[r.pool][dt] = r;
    }
  });

  // Union of all dates, sorted chronologically (oldest → newest)
  const allDates = [...new Set(funnelData.map(r => toDate(r.timestamp)))].sort();
  const pools = Object.keys(poolMap);

  // Sort pools: highest |latest Z| first
  pools.sort((a, b) => {
    const latestDate = allDates[allDates.length - 1];
    const findLatest = (pm) => {
      for (let i = allDates.length - 1; i >= 0; i--) {
        if (pm[allDates[i]]) return Math.abs(pm[allDates[i]].z);
      }
      return 0;
    };
    return findLatest(poolMap[b]) - findLatest(poolMap[a]);
  });

  // Compute persistence score per pool: fraction of snapshots with |Z| ≥ 2
  const persistScore = (pool) => {
    const entries = Object.values(poolMap[pool]);
    return entries.filter(r => Math.abs(r.z) >= 2).length / entries.length;
  };

  const series = pools.map((pool, i) => {
    const color = POOL_COLORS[i % POOL_COLORS.length];
    const ps = persistScore(pool);
    const isHighPersist = ps >= 0.3; // ≥30% of windows in watch/danger zone
    const zData = allDates.map(dt => {
      const row = poolMap[pool][dt];
      return row ? +row.z.toFixed(2) : null;
    });
    // Find last non-null index for endLabel
    let lastIdx = -1;
    for (let i = zData.length - 1; i >= 0; i--) { if (zData[i] !== null) { lastIdx = i; break; } }
    const lastZ = lastIdx >= 0 ? zData[lastIdx] : null;
    return {
      name: pool,
      type: 'line',
      smooth: false,
      symbol: 'circle',
      symbolSize: 5,
      connectNulls: true,
      lineStyle: { color, width: isHighPersist ? 2.5 : 1.5, opacity: isHighPersist ? 1 : 0.55 },
      itemStyle: { color },
      endLabel: {
        show: lastZ !== null && Math.abs(lastZ) >= 1.5,
        formatter: () => `${pool} ${lastZ > 0 ? '+' : ''}${lastZ}`,
        color,
        fontSize: 11,
        fontWeight: isHighPersist ? 'bold' : 'normal',
        align: 'left',
        padding: [0, 0, 0, 4],
      },
      tooltip: {
        valueFormatter: (val) => val != null ? val.toFixed(2) : 'n/a',
      },
      data: zData,
    };
  });

  // Threshold markArea bands (attached to a silent dummy series)
  const bandSeries = {
    name: '__bands',
    type: 'line',
    silent: true,
    symbol: 'none',
    lineStyle: { opacity: 0 },
    data: allDates.map(() => null),
    tooltip: { show: false },
    legendHoverLink: false,
    markArea: {
      silent: true,
      data: [
        // Red danger zones |Z| ≥ 3
        [{ yAxis: 3 },  { yAxis: 6,  name: 'Danger |Z|≥3', itemStyle: { color: 'rgba(255,77,79,0.12)' } }],
        [{ yAxis: -6 }, { yAxis: -3, name: 'Danger |Z|≥3', itemStyle: { color: 'rgba(255,77,79,0.12)' } }],
        // Amber watch zones 2 ≤ |Z| < 3
        [{ yAxis: 2 },  { yAxis: 3,  name: 'Watch |Z|≥2', itemStyle: { color: 'rgba(226,163,74,0.09)' } }],
        [{ yAxis: -3 }, { yAxis: -2, name: 'Watch |Z|≥2', itemStyle: { color: 'rgba(226,163,74,0.09)' } }],
      ],
    },
    markLine: {
      silent: true,
      symbol: 'none',
      data: [
        { yAxis: 0,  lineStyle: { color: 'rgba(139,148,158,0.3)', type: 'dashed', width: 1 }, label: { show: false } },
        { yAxis:  3, lineStyle: { color: 'rgba(255,77,79,0.4)',   type: 'dashed', width: 1 }, label: { show: true, formatter: '|Z|=3', color: '#ff4d4f', fontSize: 10, position: 'insideStartTop' } },
        { yAxis: -3, lineStyle: { color: 'rgba(255,77,79,0.4)',   type: 'dashed', width: 1 }, label: { show: true, formatter: '|Z|=3', color: '#ff4d4f', fontSize: 10, position: 'insideStartBottom' } },
        { yAxis:  2, lineStyle: { color: 'rgba(226,163,74,0.4)',  type: 'dashed', width: 1 }, label: { show: true, formatter: '|Z|=2 watch', color: THEME.accent, fontSize: 10, position: 'insideStartTop' } },
        { yAxis: -2, lineStyle: { color: 'rgba(226,163,74,0.4)',  type: 'dashed', width: 1 }, label: { show: true, formatter: '|Z|=2 watch', color: THEME.accent, fontSize: 10, position: 'insideStartBottom' } },
      ],
    },
  };

  // Label the zones on the right side via graphic
  const dangerLabel  = { type: 'text', right: 8, top: 28,  style: { text: 'Danger',    fill: 'rgba(255,77,79,0.55)',  fontSize: 8, fontWeight: 'bold' } };
  const watchLabel   = { type: 'text', right: 8, top: 62,  style: { text: 'Watch',     fill: 'rgba(226,163,74,0.55)', fontSize: 8, fontWeight: 'bold' } };
  const normalLabel  = { type: 'text', right: 8, top: 115, style: { text: 'Normal',    fill: 'rgba(139,148,158,0.45)', fontSize: 8 } };
  const watchLabelN  = { type: 'text', right: 8, bottom: 62,  style: { text: 'Watch',  fill: 'rgba(226,163,74,0.55)', fontSize: 8, fontWeight: 'bold' } };
  const dangerLabelN = { type: 'text', right: 8, bottom: 28, style: { text: 'Danger',  fill: 'rgba(255,77,79,0.55)',  fontSize: 8, fontWeight: 'bold' } };

  // Format X labels: show only day (MM-DD) to save space
  const shortDates = allDates.map(d => d.slice(5)); // "MM-DD"

  zscoreChart.setOption({
    backgroundColor: 'transparent',
    tooltip: {
      ...baseTooltip({ confine: true }),
      trigger: 'axis',
      axisPointer: { type: 'cross', lineStyle: { color: THEME.border } },
      formatter: (params) => {
        const date = allDates[params[0].dataIndex];
        let h = `<b style="color:${THEME.accent}">${date}</b><br/>`;
        const visible = params.filter(p => p.value != null);
        visible.sort((a, b) => Math.abs(b.value) - Math.abs(a.value));
        visible.forEach(p => {
          const z = p.value;
          const zColor = Math.abs(z) >= 3 ? '#ff4d4f' : Math.abs(z) >= 2 ? THEME.accent : THEME.text;
          const row = poolMap[p.seriesName]?.[date];
          const extra = row ? ` <span style="color:${THEME.muted};font-size:10px">(luck ${row.luck}%, share ${row.share}%)</span>` : '';
          h += `${p.marker} ${p.seriesName}: <b style="color:${zColor}">${z > 0 ? '+' : ''}${z.toFixed(2)}</b>${extra}<br/>`;
        });
        return h;
      },
    },
    legend: {
      bottom: 0,
      type: 'scroll',
      textStyle: { color: THEME.muted, fontSize: 11 },
      icon: 'circle',
      itemWidth: 9,
      pageIconColor: THEME.accent,
      pageTextStyle: { color: THEME.muted },
      data: pools,
    },
    graphic: [dangerLabel, watchLabel, normalLabel, watchLabelN, dangerLabelN],
    grid: { top: 20, left: 58, right: 105, bottom: 65 },
    xAxis: {
      type: 'category',
      data: shortDates,
      axisLabel: { color: THEME.muted, fontSize: 11 },
      axisLine: { lineStyle: { color: THEME.border } },
      splitLine: { show: false },
    },
    yAxis: {
      type: 'value',
      name: 'Z-Score',
      nameTextStyle: { color: THEME.muted, fontSize: 11 },
      axisLabel: { color: THEME.muted, fontSize: 11 },
      splitLine: { lineStyle: { color: THEME.border, type: 'dashed' } },
      axisLine: { lineStyle: { color: THEME.border } },
    },
    series: [bandSeries, ...series],
  }, true);
}

// ── KPI 3: Entropy Heatmap ────────────────────────────────────────────────────
export let entropyChart = null;
export function renderEntropyHeatmap(entropyData) {
  const el = document.getElementById('chart-entropy-heatmap');
  if (!el || !entropyData || entropyData.length === 0) return;
  if (!entropyChart) {
    entropyChart = ec().init(el, null, { renderer: 'canvas' });
    window.addEventListener('resize', () => entropyChart.resize());
  }

  // Aggregate to monthly (1104 raw dates → ~63 months) for readability
  const monthAgg = {};
  entropyData.forEach(d => {
    const month = d.date.slice(0, 7);
    const key = `${month}|||${d.pool}`;
    if (!monthAgg[key]) monthAgg[key] = { month, pool: d.pool, wSum: 0, totalBlocks: 0 };
    monthAgg[key].wSum += d.cv * d.blocks;
    monthAgg[key].totalBlocks += d.blocks;
  });
  const monthlyData = Object.values(monthAgg).map(v => ({
    month: v.month,
    pool: v.pool,
    cv: v.totalBlocks > 0 ? +(v.wSum / v.totalBlocks).toFixed(3) : 0,
  }));

  const months = [...new Set(monthlyData.map(d => d.month))].sort();
  const pools  = [...new Set(monthlyData.map(d => d.pool))].sort();
  const data   = monthlyData.map(d => [months.indexOf(d.month), pools.indexOf(d.pool), d.cv]);

  // Event annotation indices
  const chinaStart = months.indexOf('2021-05');
  const chinaEnd   = months.indexOf('2021-10');
  const halvingIdx = months.indexOf('2024-04');
  const halvingEnd = months.indexOf('2024-05') >= 0 ? months.indexOf('2024-05') : halvingIdx;

  const markAreaData = [];
  if (chinaStart >= 0 && chinaEnd >= 0) {
    markAreaData.push([
      { xAxis: months[chinaStart],
        itemStyle: { color: 'rgba(255,77,79,0.1)', borderColor: 'rgba(255,77,79,0.25)', borderWidth: 1 },
        label: { show: true, formatter: '🇨🇳 China Ban', color: '#ff4d4f', fontSize: 8, fontWeight: 'bold', position: 'insideTop' } },
      { xAxis: months[chinaEnd] },
    ]);
  }
  if (halvingIdx >= 0) {
    markAreaData.push([
      { xAxis: months[halvingIdx],
        itemStyle: { color: 'rgba(226,163,74,0.12)', borderColor: 'rgba(226,163,74,0.3)', borderWidth: 1 },
        label: { show: true, formatter: '₿ Halving', color: '#E2A34A', fontSize: 8, fontWeight: 'bold', position: 'insideTop' } },
      { xAxis: months[halvingEnd] || months[halvingIdx] },
    ]);
  }

  entropyChart.setOption({
    backgroundColor: 'transparent',
    tooltip: {
      ...baseTooltip({ confine: true }),
      position: 'top',
      formatter: (p) => {
        if (!Array.isArray(p.data) || p.data[2] == null) return '';
        const cv = p.data[2];
        const status = cv < 0.75 ? '🏭 Industrial (centralized)'
                     : cv > 1.0  ? '🌐 Retail/decentralized'
                     : '🏊 Professional pool';
        const color  = cv < 0.75 ? '#ff4d4f' : cv > 1.0 ? '#74add1' : THEME.accent;
        return `<b>${pools[p.data[1]]}</b> (${months[p.data[0]]})<br/>` +
               `CV: <b style="color:${color}">${cv.toFixed(3)}</b><br/>` +
               `<span style="font-size:10px;color:${color}">${status}</span>`;
      },
    },
    grid: { top: 20, left: 120, right: 20, bottom: 80 },
    xAxis: {
      type: 'category',
      data: months,
      axisLabel: { color: THEME.muted, rotate: 35, fontSize: 11, interval: Math.floor(months.length / 12) },
      axisLine: { lineStyle: { color: THEME.border } },
    },
    yAxis: {
      type: 'category',
      data: pools,
      axisLabel: { color: THEME.text, fontSize: 12 },
      axisLine: { lineStyle: { color: THEME.border } },
    },
    // INVERTED: Low CV (suspicious = red) → High CV (normal = blue)
    visualMap: {
      min: 0.5,
      max: 1.3,
      calculable: true,
      orient: 'horizontal',
      left: 'center',
      bottom: 5,
      text: ['✅ Normal (High CV)', '🔴 Suspicious (Low CV)'],
      textStyle: { color: THEME.muted, fontSize: 11 },
      inRange: {
        color: ['#a50026', '#d73027', '#f46d43', '#fdae61', '#fee090', '#ffffbf', '#e0f3f8', '#abd9e9', '#74add1', '#4575b4', '#313695'],
      },
    },
    series: [{
      type: 'heatmap',
      data,
      label: { show: false },
      emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.5)' } },
      markArea: { silent: true, data: markAreaData },
    }],
  }, true);

  // Actor Archetypes panel (computed from last 6 months of data)
  const archetypesEl = document.getElementById('chart-entropy-archetypes');
  if (!archetypesEl) return;
  const cutoff = months.slice(-6)[0] || months[0];
  const recentMap = {};
  monthlyData.filter(d => d.month >= cutoff).forEach(d => {
    if (!recentMap[d.pool]) recentMap[d.pool] = { sum: 0, n: 0 };
    recentMap[d.pool].sum += d.cv;
    recentMap[d.pool].n  += 1;
  });
  const industrial = [], professional = [], retail = [];
  Object.entries(recentMap).forEach(([pool, v]) => {
    const avg = +(v.sum / v.n).toFixed(2);
    if (avg < 0.75) industrial.push({ pool, avg });
    else if (avg <= 1.0) professional.push({ pool, avg });
    else retail.push({ pool, avg });
  });
  industrial.sort((a, b) => a.avg - b.avg);
  professional.sort((a, b) => a.avg - b.avg);
  retail.sort((a, b) => b.avg - a.avg);

  const badge = (p, color) =>
    `<span style="background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);border-radius:3px;` +
    `padding:1px 6px;font-size:9.5px;font-weight:700;margin:2px;display:inline-block;color:${color}">${p.pool} ` +
    `<span style="opacity:0.55;font-weight:400">${p.avg}</span></span>`;

  const none = `<span style="opacity:0.4;font-size:10px">none in last 6 months</span>`;
  archetypesEl.innerHTML =
    `<div style="margin-top:14px;display:grid;grid-template-columns:repeat(3,1fr);gap:8px;">` +
      `<div style="background:rgba(255,77,79,0.07);border:1px solid rgba(255,77,79,0.25);border-radius:6px;padding:10px;">` +
        `<div style="font-size:0.68rem;font-weight:800;color:#ff4d4f;letter-spacing:0.07em;text-transform:uppercase;margin-bottom:6px;">🏭 Industrial (CV &lt; 0.75)</div>` +
        `<div style="font-size:0.76rem;color:var(--text-secondary);line-height:1.5;margin-bottom:6px;">Consistent sub-0.75 CV → owned hardware, central coordination. These are the same pools running multi-block streaks in Act I.</div>` +
        `<div>${industrial.map(p => badge(p, '#ff4d4f')).join('') || none}</div>` +
      `</div>` +
      `<div style="background:rgba(226,163,74,0.07);border:1px solid rgba(226,163,74,0.25);border-radius:6px;padding:10px;">` +
        `<div style="font-size:0.68rem;font-weight:800;color:#E2A34A;letter-spacing:0.07em;text-transform:uppercase;margin-bottom:6px;">🏊 Professional Pool (0.75–1.0)</div>` +
        `<div style="font-size:0.76rem;color:var(--text-secondary);line-height:1.5;margin-bottom:6px;">Mixed hashrate sources with stable infrastructure. Variance reflects a diverse miner base without excessive central coordination.</div>` +
        `<div>${professional.map(p => badge(p, '#E2A34A')).join('') || none}</div>` +
      `</div>` +
      `<div style="background:rgba(152,195,121,0.07);border:1px solid rgba(152,195,121,0.25);border-radius:6px;padding:10px;">` +
        `<div style="font-size:0.68rem;font-weight:800;color:#98C379;letter-spacing:0.07em;text-transform:uppercase;margin-bottom:6px;">🌐 Retail / Decentralized (CV &gt; 1.0)</div>` +
        `<div style="font-size:0.76rem;color:var(--text-secondary);line-height:1.5;margin-bottom:6px;">High timing variance → many independent contributors, no single coordinator. These pools have the lowest streak risk by design.</div>` +
        `<div>${retail.map(p => badge(p, '#98C379')).join('') || none}</div>` +
      `</div>` +
    `</div>`;
}

// ── KPI 5: Empty Block Auditor (Scatter) ──────────────────────────────────────
export let emptyChart = null;
export function renderEmptyBlockChart(emptyData) {
  const el = document.getElementById('chart-empty-blocks');
  if (!el || !emptyData || !emptyData.leaderboard) return;
  if (!emptyChart) {
    emptyChart = ec().init(el, null, { renderer: 'canvas' });
    window.addEventListener('resize', () => emptyChart.resize());
  }

  const lb = emptyData.leaderboard;

  // Weighted network average (all-time blocks as weights)
  const totalBlks = lb.reduce((s, d) => s + d.total_all, 0);
  const networkAvg = lb.reduce((s, d) => s + d.ratio_all * d.total_all, 0) / totalBlks;

  // Axis range with headroom
  const maxVal = Math.max(...lb.map(d => Math.max(d.ratio_all, d.ratio_30d)));
  const axisMax = Math.ceil(maxVal * 1.2 * 10) / 10;

  // Classify pools into 4 behavioural quadrants
  const groups = {
    persistent: { label: '🔴 Persistent Offenders', color: '#ff4d4f', items: [] },
    worsening:  { label: '🚨 Newly Suspicious',     color: '#E2A34A', items: [] },
    reformed:   { label: '📉 Reformed',             color: '#56B6C2', items: [] },
    clean:      { label: '✅ Clean',                color: '#98C379', items: [] },
  };
  lb.forEach(d => {
    const aboveAll = d.ratio_all > networkAvg;
    const above30d = d.ratio_30d > networkAvg;
    const key = aboveAll && above30d ? 'persistent'
              : !aboveAll && above30d ? 'worsening'
              : aboveAll && !above30d ? 'reformed'
              : 'clean';
    groups[key].items.push(d);
  });

  const scatterSeries = Object.entries(groups).map(([key, g]) => ({
    name: g.label,
    type: 'scatter',
    symbolSize: (val) => Math.max(7, 6 + Math.sqrt(val[2]) * 0.055),
    itemStyle: { color: g.color, opacity: 0.9, borderColor: THEME.bg, borderWidth: 1.5 },
    label: {
      show: true,
      position: 'top',
      color: g.color,
      fontSize: 9,
      fontWeight: 'bold',
      formatter: (p) => p.data[3],
    },
    // [ratio_all, ratio_30d, total_all, pool, empty_all, empty_30d, total_30d]
    data: g.items.map(d => [d.ratio_all, d.ratio_30d, d.total_all, d.pool, d.empty_all, d.empty_30d, d.total_30d]),
    ...(key === 'persistent' ? {
      markLine: {
        silent: true,
        symbol: 'none',
        data: [
          { xAxis: networkAvg, lineStyle: { color: 'rgba(255,77,79,0.35)', type: 'dashed', width: 1.5 },
            label: { show: true, formatter: `Avg ${networkAvg.toFixed(2)}%`, color: '#ff4d4f', fontSize: 10, position: 'insideStartTop' } },
          { yAxis: networkAvg, lineStyle: { color: 'rgba(255,77,79,0.35)', type: 'dashed', width: 1.5 },
            label: { show: true, formatter: `Avg ${networkAvg.toFixed(2)}%`, color: '#ff4d4f', fontSize: 10, position: 'insideEndTop' } },
        ],
      },
    } : key === 'clean' ? {
      markLine: {
        silent: true,
        symbol: 'none',
        data: [
          { xAxis: networkAvg, lineStyle: { color: 'rgba(255,77,79,0.35)', type: 'dashed', width: 1.5 }, label: { show: false } },
          { yAxis: networkAvg, lineStyle: { color: 'rgba(255,77,79,0.35)', type: 'dashed', width: 1.5 }, label: { show: false } },
        ],
      },
    } : {}),
  }));

  // Diagonal y = x "no change" reference line
  const diagSeries = {
    name: '⟵ No Change ⟶',
    type: 'line',
    silent: true,
    symbol: 'none',
    lineStyle: { color: 'rgba(139,148,158,0.28)', type: 'dotted', width: 1.5 },
    tooltip: { show: false },
    data: [[0, 0], [axisMax, axisMax]],
    legendHoverLink: false,
  };

  emptyChart.setOption({
    backgroundColor: 'transparent',
    tooltip: {
      ...baseTooltip({ confine: true }),
      trigger: 'item',
      formatter: (p) => {
        if (p.seriesType === 'line') return '';
        const [ratioAll, ratio30d, totalAll, poolName, emptyAll, empty30d, total30d] = p.data;
        const trend = ratio30d > ratioAll + 0.05 ? '↑ Worsening'
                    : ratio30d < ratioAll - 0.05  ? '↓ Improving'
                    : '→ Stable';
        const trendColor = trend.startsWith('↑') ? '#ff4d4f' : trend.startsWith('↓') ? '#98C379' : THEME.muted;
        return `<b style="color:${THEME.accent}">${poolName}</b><br/>` +
          `Since 2022: <b>${ratioAll}%</b> (${emptyAll} / ${totalAll.toLocaleString()})<br/>` +
          `Last 30d: <b>${ratio30d}%</b> (${empty30d} / ${total30d.toLocaleString()})<br/>` +
          `Trend: <b style="color:${trendColor}">${trend}</b><br/>` +
          `<span style="color:${THEME.muted};font-size:11px;">Network avg: ${networkAvg.toFixed(2)}%</span>`;
      },
    },
    legend: {
      bottom: 0,
      type: 'scroll',
      textStyle: { color: THEME.muted, fontSize: 11 },
      icon: 'circle',
      itemWidth: 10,
    },
    graphic: [
      { type: 'text', style: { text: '✅ Clean',                fill: '#98C379', fontSize: 10, fontWeight: 'bold', opacity: 0.55 }, left: 67,  bottom: 60 },
      { type: 'text', style: { text: '🚨 Newly Suspicious',     fill: '#E2A34A', fontSize: 10, fontWeight: 'bold', opacity: 0.55 }, left: 67,  top: 33   },
      { type: 'text', style: { text: '🔴 Persistent Offenders', fill: '#ff4d4f', fontSize: 10, fontWeight: 'bold', opacity: 0.55 }, right: 32, top: 33   },
      { type: 'text', style: { text: '📉 Reformed',             fill: '#56B6C2', fontSize: 10, fontWeight: 'bold', opacity: 0.55 }, right: 32, bottom: 60 },
    ],
    grid: { top: 35, left: 80, right: 35, bottom: 70 },
    xAxis: {
      type: 'value',
      name: 'Since 2022 Empty %',
      nameLocation: 'middle',
      nameGap: 32,
      min: 0,
      max: axisMax,
      axisLabel: { color: THEME.muted, fontSize: 12, formatter: '{value}%' },
      splitLine: { lineStyle: { color: THEME.border, type: 'dashed' } },
      axisLine: { lineStyle: { color: THEME.border } },
    },
    yAxis: {
      type: 'value',
      name: 'Last 30d Empty %',
      nameLocation: 'middle',
      nameGap: 50,
      min: 0,
      max: axisMax,
      axisLabel: { color: THEME.muted, fontSize: 12, formatter: '{value}%' },
      splitLine: { lineStyle: { color: THEME.border, type: 'dashed' } },
      axisLine: { lineStyle: { color: THEME.border } },
    },
    series: [...scatterSeries, diagSeries],
  }, true);
}

export let emptyTrendChart = null;
export function renderEmptyTrendChart(monthlyTrend) {
  if (!monthlyTrend || !monthlyTrend.length) return;
  const el = document.getElementById('chart-empty-trend');
  if (!el) return;
  if (!emptyTrendChart) {
    emptyTrendChart = ec().init(el, null, { renderer: 'canvas' });
    window.addEventListener('resize', () => emptyTrendChart.resize());
  }

  // Group by pool
  const poolMap = {};
  monthlyTrend.forEach(r => {
    if (!poolMap[r.pool_name]) poolMap[r.pool_name] = {};
    poolMap[r.pool_name][r.month] = r.ratio;
  });

  const months = [...new Set(monthlyTrend.map(r => r.month))].sort();
  const pools = Object.keys(poolMap);

  // Sort by all-time average empty ratio descending (top offenders first)
  pools.sort((a, b) => {
    const avg = pm => { const v = Object.values(pm); return v.reduce((s, x) => s + x, 0) / v.length; };
    return avg(poolMap[b]) - avg(poolMap[a]);
  });

  const topN = 5;
  const series = pools.map((pool, i) => {
    const isTop = i < topN;
    return {
      name: pool,
      type: 'line',
      smooth: true,
      symbol: 'none',
      lineStyle: {
        color: POOL_COLORS[i % POOL_COLORS.length],
        width: isTop ? 2 : 1,
        opacity: isTop ? 0.9 : 0.35,
      },
      itemStyle: { color: POOL_COLORS[i % POOL_COLORS.length] },
      areaStyle: isTop ? { color: POOL_COLORS[i % POOL_COLORS.length], opacity: 0.06 } : null,
      data: months.map(m => poolMap[pool][m] ?? null),
      connectNulls: true,
    };
  });

  // Monthly unweighted network average across pools present that month
  const netAvgData = months.map(m => {
    const vals = pools.map(p => poolMap[p][m] ?? null).filter(v => v !== null);
    return vals.length ? +(vals.reduce((s, v) => s + v, 0) / vals.length).toFixed(3) : null;
  });
  series.push({
    name: 'Network Avg',
    type: 'line',
    smooth: true,
    symbol: 'none',
    lineStyle: { color: THEME.muted, type: 'dashed', width: 1, opacity: 0.5 },
    itemStyle: { color: THEME.muted },
    data: netAvgData,
    connectNulls: true,
    z: 0,
  });

  emptyTrendChart.setOption({
    backgroundColor: 'transparent',
    tooltip: {
      ...baseTooltip({ confine: true }),
      trigger: 'axis',
      axisPointer: { type: 'cross', lineStyle: { color: THEME.border } },
      formatter: (params) => {
        const month = params[0].axisValue;
        let h = `<b style="color:${THEME.accent}">${month}</b><br/>`;
        [...params]
          .filter(p => p.value != null)
          .sort((a, b) => (b.value || 0) - (a.value || 0))
          .forEach(p => {
            h += `${p.marker} ${p.seriesName}: <b>${(p.value ?? 0).toFixed(2)}%</b><br/>`;
          });
        return h;
      },
    },
    legend: {
      bottom: 0,
      type: 'scroll',
      textStyle: { color: THEME.muted, fontSize: 11 },
      icon: 'circle',
      itemWidth: 9,
      pageIconColor: THEME.accent,
      pageTextStyle: { color: THEME.muted },
    },
    grid: { top: 10, left: 58, right: 15, bottom: 65 },
    xAxis: {
      type: 'category',
      data: months,
      axisLabel: {
        color: THEME.muted,
        fontSize: 11,
        interval: Math.floor(months.length / 10),
      },
      axisLine: { lineStyle: { color: THEME.border } },
      splitLine: { show: false },
    },
    yAxis: {
      type: 'value',
      name: 'Empty %',
      nameTextStyle: { color: THEME.muted, fontSize: 11 },
      axisLabel: { color: THEME.muted, fontSize: 11, formatter: '{value}%' },
      splitLine: { lineStyle: { color: THEME.border, type: 'dashed' } },
    },
    series,
  }, true);
}

// ── KPI 4: Sync Histogram ─────────────────────────────────────────────────────
export let syncChart = null;
export function renderSyncHistogram(syncData) {
  const el = document.getElementById('chart-sync-histogram');
  if (!el || !syncData || syncData.length === 0) return;
  if (!syncChart) {
    syncChart = ec().init(el, null, { renderer: 'canvas' });
    window.addEventListener('resize', () => syncChart.resize());
  }

  // Sort by sub_30s % descending — worst offenders first
  const sortedData = [...syncData].sort((a, b) => {
    const a30 = (a.buckets.sub_30s / a.total_consecutive);
    const b30 = (b.buckets.sub_30s / b.total_consecutive);
    return b30 - a30;
  });

  const poolNames = sortedData.map(d => d.pool);

  // ── Header-First Mining Callout Strip ──────────────────────────────────────────
  // Shows per-pool "X% of fast blocks were empty" badges above the chart
  const calloutEl = document.getElementById('chart-sync-spy-callout');
  if (calloutEl) {
    const badges = sortedData.map(d => {
      const sub30 = d.buckets.sub_30s || 0;
      const emptyIn30 = d.buckets_empty?.sub_30s || 0;
      if (sub30 === 0 || emptyIn30 === 0) return '';
      const spyPct = Math.round(emptyIn30 / sub30 * 100);
      const color = spyPct >= 50 ? '#ff4d4f' : spyPct >= 20 ? '#E2A34A' : '#8b949e';
      return `<span style="display:inline-flex;align-items:center;gap:5px;background:rgba(255,255,255,0.04);border:1px solid ${color}44;border-radius:4px;padding:3px 9px;font-size:0.7rem;color:${color};font-weight:600;">
        ${d.pool} <b>${spyPct}%</b> <span style="font-weight:400;opacity:0.7;">fast blocks empty</span>
      </span>`;
    }).filter(Boolean).join('');

    calloutEl.innerHTML = badges
      ? `<div style="display:flex;flex-wrap:wrap;gap:6px;align-items:center;padding:10px 12px;margin-bottom:10px;background:rgba(226,163,74,0.05);border:1px solid rgba(226,163,74,0.2);border-radius:6px;">
           <span style="font-size:0.65rem;text-transform:uppercase;letter-spacing:0.08em;font-weight:800;color:#E2A34A;flex-shrink:0;margin-right:4px;">
             <i class="fa-solid fa-circle-info"></i> Of sub-30s consecutive blocks — fraction that were also empty
           </span>
           ${badges}
         </div>`
      : '';
  }

  // ── Series: split sub_30s into spy (empty) + normal ──────────────────────────
  // Series 0: Empty blocks within <30s → header-first mining signal (pool skipped validation before starting next block)
  const spySeries = {
    name: '< 30s Empty (fast + empty)',
    type: 'bar',
    stack: 'total',
    itemStyle: { color: '#7B1515' },  // deep crimson — distinct from normal <30s
    label: {
      show: true,
      position: 'inside',
      color: '#ffaaaa',
      fontSize: 9,
      fontWeight: 'bold',
      formatter: (p) => (p.data?.spy_pct >= 10 ? `${p.data.spy_pct}%` : '')
    },
    data: sortedData.map(d => {
      const totalConsec = d.total_consecutive;
      const sub30 = d.buckets.sub_30s || 0;
      const emptyCount = d.buckets_empty?.sub_30s || 0;
      const spyPct = sub30 > 0 ? Math.round(emptyCount / sub30 * 100) : 0;
      return {
        value: totalConsec > 0 ? (emptyCount / totalConsec * 100) : 0,
        count: emptyCount,
        spy_pct: spyPct,
        sub30Count: sub30,
        totalConsec,
        totalBlocks: d.total_blocks || 0
      };
    })
  };

  // Series 1: Non-empty sub_30s blocks (still dangerous, but no validation skip confirmed)
  const normalSub30Series = {
    name: '< 30s Normal',
    type: 'bar',
    stack: 'total',
    itemStyle: { color: '#ff4d4f' },
    data: sortedData.map(d => {
      const totalConsec = d.total_consecutive;
      const sub30 = d.buckets.sub_30s || 0;
      const emptyCount = d.buckets_empty?.sub_30s || 0;
      return {
        value: totalConsec > 0 ? ((sub30 - emptyCount) / totalConsec * 100) : 0,
        count: sub30 - emptyCount,
        totalConsec,
        totalBlocks: d.total_blocks || 0
      };
    })
  };

  // Series 2–5: Remaining time buckets, unchanged
  const restSeries = ['sub_60s', 'sub_2m', 'sub_5m', 'slow'].map((key, i) => ({
    name: ['< 60s', '< 2m', '< 5m', '> 5m'][i],
    type: 'bar',
    stack: 'total',
    itemStyle: { color: ['#E2A34A', '#E5C07B', '#98C379', '#56B6C2'][i] },
    data: sortedData.map(d => {
      const totalConsec = d.total_consecutive;
      const val = d.buckets[key] || 0;
      return {
        value: totalConsec > 0 ? (val / totalConsec * 100) : 0,
        count: val,
        count_empty: d.buckets_empty?.[key] || 0,
        totalConsec,
        totalBlocks: d.total_blocks || 0
      };
    })
  }));

  syncChart.setOption({
    backgroundColor: 'transparent',
    tooltip: {
      ...baseTooltip({ confine: true }),
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params) => {
        const d = params[0].data;
        const consecRatio = d.totalBlocks > 0 ? (d.totalConsec / d.totalBlocks * 100).toFixed(1) : 0;
        const spyItem = params.find(p => p.seriesName === '< 30s Empty (fast + empty)');
        const spyScore = spyItem?.data?.spy_pct ?? 0;

        let h = `<div style="margin-bottom:8px;border-bottom:1px solid rgba(255,255,255,0.1);padding-bottom:5px;">
                   <b style="color:${THEME.accent}">${params[0].name}</b>
                 </div>
                 Lifetime Blocks: <b>${d.totalBlocks.toLocaleString()}</b><br/>
                 Consecutive Pairs: <b>${d.totalConsec.toLocaleString()}</b> (${consecRatio}%)`;

        if (spyScore > 0) {
          const sc = spyScore >= 50 ? '#ff4d4f' : '#E2A34A';
          h += `<div style="margin:6px 0;padding:5px 8px;background:rgba(255,77,79,0.1);border-left:2px solid ${sc};border-radius:2px;">
                  <span style="color:${sc};font-weight:bold;">⚠ ${spyScore}% of &lt;30s blocks were empty — header-first mining signal</span>
                </div>`;
        } else {
          h += '<br/>';
        }

        params.forEach(p => {
          if (p.data.value > 0.01) {
            h += `<div style="margin-bottom:2px;">${p.marker} ${p.seriesName}: <b>${p.data.value.toFixed(1)}%</b> (${p.data.count ?? ''})</div>`;
          }
        });
        return h;
      }
    },
    legend: {
      bottom: 0,
      textStyle: { color: THEME.muted, fontSize: 11 },
      icon: 'circle',
      itemWidth: 10
    },
    grid: { top: 20, left: 115, right: 30, bottom: 70 },
    xAxis: {
      type: 'value',
      max: 100,
      axisLabel: { color: THEME.muted, fontSize: 11, formatter: '{value}%' },
      splitLine: { lineStyle: { color: THEME.border, type: 'dashed' } }
    },
    yAxis: {
      type: 'category',
      data: poolNames,
      axisLabel: { color: THEME.text, fontSize: 12 },
      axisLine: { lineStyle: { color: THEME.border } }
    },
    series: [spySeries, normalSub30Series, ...restSeries]
  }, true);
}

// ── KPI 4b: Second Block Uplift ───────────────────────────────────────────────
// Measures how much more likely a pool is to mine block N+1 given it mined
// block N, vs. what its block-weighted hash share would predict (lift = actual / expected).
export let consecutiveAdvantageChart = null;
export function renderConsecutiveAdvantage(syncData) {
  const el = document.getElementById('chart-consecutive-advantage');
  if (!el || !syncData || syncData.length === 0) return;
  if (!consecutiveAdvantageChart) {
    consecutiveAdvantageChart = ec().init(el, null, { renderer: 'canvas' });
    window.addEventListener('resize', () => consecutiveAdvantageChart.resize());
  }

  const totalAllBlocks = syncData.reduce((s, p) => s + p.total_blocks, 0);

  // Derive per-pool metrics entirely from kpi4_sync fields
  const poolData = syncData.map(p => {
    const hashShare = p.total_blocks / totalAllBlocks * 100;
    const consecRate = p.total_consecutive / Math.max(p.total_blocks - 1, 1) * 100;
    // Use block-weighted expected_consecutive when available — correct for pools with
    // variable hashrate (growing or declining). Falls back to all-time-average method.
    const expectedConsec = p.expected_consecutive || (p.total_blocks * hashShare / 100);
    const lift = p.total_consecutive / expectedConsec;
    const expectedPct = expectedConsec / Math.max(p.total_blocks - 1, 1) * 100;
    return { pool: p.pool, hashShare, consecRate, lift, expectedPct, totalBlocks: p.total_blocks, totalConsec: p.total_consecutive, expectedConsec, consecTiming: p.consec_timing || null };
  }).sort((a, b) => a.lift - b.lift); // ascending → highest lift at top of horiz chart

  // Callout strip: network-wide insight
  const aboveParity = poolData.filter(d => d.lift > 1.0).length;
  const topPool = poolData[poolData.length - 1];
  const calloutEl = document.getElementById('chart-consecutive-callout');
  if (calloutEl) {
    const topColor = topPool.lift > 2 ? '#ff4d4f' : '#E2A34A';
    calloutEl.innerHTML = `<div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;padding:10px 14px;margin-bottom:10px;background:rgba(226,163,74,0.05);border:1px solid rgba(226,163,74,0.2);border-radius:6px;font-size:0.78rem;color:var(--text-secondary);line-height:1.5;">
      <i class="fa-solid fa-signal" style="color:var(--accent);flex-shrink:0;"></i>
      <span><b style="color:var(--text-primary)">${aboveParity} of ${poolData.length}</b> pools mine block N+1 at a rate above their block-weighted expected rate. After correcting for variable hashrate, all lifts are near 1×.&nbsp;
      Highest lift: <b style="color:${topColor}">${topPool.pool}</b> at <b style="color:${topColor}">${topPool.lift.toFixed(2)}×</b> its block-weighted expected rate
      <span style="color:var(--text-secondary);font-size:0.7rem;">(${topPool.consecRate.toFixed(2)}% actual vs ${topPool.expectedPct.toFixed(2)}% block-weighted expected)</span>.
      </span>
    </div>`;
  }

  const maxLift = Math.max(...poolData.map(d => d.lift));
  const xMax = Math.ceil(maxLift * 1.1 * 10) / 10;

  const barColors = poolData.map(d =>
    d.lift > 2.0 ? '#ff4d4f' :
    d.lift > 1.5 ? '#E87E51' :
    d.lift > 1.0 ? '#E2A34A' :
               '#56B6C2'
  );

  consecutiveAdvantageChart.setOption({
    backgroundColor: 'transparent',
    tooltip: {
      ...baseTooltip({ confine: true }),
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params) => {
        const poolName = params[0].name;
        const d = poolData.find(x => x.pool === poolName);
        if (!d) return '';
        const liftColor = d.lift > 2 ? '#ff4d4f' : d.lift > 1.0 ? '#E2A34A' : '#56B6C2';
        const expectedPct = (d.expectedConsec / Math.max(d.totalBlocks - 1, 1) * 100);
        const adv = d.consecRate - expectedPct;
        const EXPECTED_MEDIAN_S = 416; // 600 × ln(2), exponential distribution
        let timingLine = '';
        if (d.consecTiming) {
          const ct = d.consecTiming;
          const flagColor = ct.fast_flag ? '#ff4d4f' : THEME.muted;
          const delta = ct.median_delta_sec - EXPECTED_MEDIAN_S;
          const sign = delta > 0 ? '+' : '';
          timingLine =
            `<br/><span style="color:${flagColor};font-size:11px;">Consec median: <b>${ct.median_delta_sec}s</b> vs expected ~${EXPECTED_MEDIAN_S}s (${sign}${delta.toFixed(0)}s)${ct.fast_flag ? ' ⚑ fast' : ''}</span>` +
            `<br/><span style="color:${THEME.muted};font-size:11px;">Sub-30s: ${ct.pct_sub30s}% · Sub-60s: ${ct.pct_sub60s}%</span>`;
        }
        return `<b style="color:${THEME.accent}">${d.pool}</b><br/>` +
          `Expected consecutive (block-weighted): <b>${expectedPct.toFixed(2)}%</b><br/>` +
          `Actual consecutive rate: <b>${d.consecRate.toFixed(2)}%</b><br/>` +
          `<span style="color:${liftColor}">Second Block Lift: <b>${d.lift.toFixed(2)}×</b></span>` +
          (adv > 0
            ? `<br/><span style="color:${liftColor};font-size:11px;">+${adv.toFixed(2)} pp above expected</span>`
            : `<br/><span style="color:${THEME.muted};font-size:11px;">${adv.toFixed(2)} pp vs expected</span>`) +
          timingLine +
          `<br/><span style="color:${THEME.muted};font-size:11px;">${d.totalConsec.toLocaleString()} pairs · ${d.totalBlocks.toLocaleString()} blocks</span>`;
      },
    },
    graphic: [
      {
        type: 'text',
        style: {
          text: '◀ No structural advantage',
          fill: 'rgba(86,182,194,0.45)',
          fontSize: 9,
          fontWeight: 'bold',
          textAlign: 'center',
        },
        left: '15%',
        top: 28,
      },
      {
        type: 'text',
        style: {
          text: 'Structural advantage ▶',
          fill: 'rgba(255,77,79,0.45)',
          fontSize: 9,
          fontWeight: 'bold',
          textAlign: 'center',
        },
        right: 85,
        top: 28,
      },
    ],
    grid: { top: 46, left: 115, right: 90, bottom: 35 },
    xAxis: {
      type: 'value',
      min: 0,
      max: xMax,
      axisLabel: { color: THEME.muted, fontSize: 11, formatter: v => v.toFixed(1) + '×' },
      splitLine: { lineStyle: { color: THEME.border, type: 'dashed' } },
      axisLine: { lineStyle: { color: THEME.border } },
    },
    yAxis: {
      type: 'category',
      data: poolData.map(d => d.pool),
      axisLabel: { color: THEME.text, fontSize: 11 },
      axisLine: { lineStyle: { color: THEME.border } },
    },
    series: [
      {
        name: 'Second Block Lift',
        type: 'bar',
        barMaxWidth: 22,
        data: poolData.map((d, i) => ({
          value: +d.lift.toFixed(3),
          itemStyle: { color: barColors[i] },
        })),
        label: {
          show: true,
          position: 'right',
          color: THEME.muted,
          fontSize: 10,
          formatter: p => p.data.value.toFixed(2) + '×',
        },
        markLine: {
          silent: true,
          symbol: 'none',
          data: [{
            xAxis: 1.0,
            lineStyle: { color: 'rgba(139,148,158,0.65)', type: 'dashed', width: 1.5 },
            label: {
              show: true,
              position: 'insideStartTop',
              formatter: '1× = Fair\nMining',
              color: THEME.muted,
              fontSize: 9,
              lineHeight: 14,
            },
          }],
        },
      },
    ],
  }, true);
}

// ── KPI 7: BIP 110 Signaling Trend ──────────────────────────────────────────
export let bip110SignalingChart = null;
export function renderBip110Signaling(trendData) {
  const el = document.getElementById('chart-bip110-signaling');
  if (!el || !trendData || trendData.length === 0) return;
  if (!bip110SignalingChart) {
    bip110SignalingChart = ec().init(el, null, { renderer: 'canvas' });
    window.addEventListener('resize', () => bip110SignalingChart.resize());
  }

  const days = trendData.map(d => d.day);
  const globalRolling = trendData.map(d => d.global_rolling);

  // 1. Identify Top 5 Signaling and Top 5 Holdout pools overall (based on last 30 days)
  const recentTrend = trendData.slice(-30);
  const sigTotals = {};
  const holdTotals = {};

  recentTrend.forEach(d => {
    Object.entries(d.pools_total).forEach(([pool, total]) => {
      const sig = d.pools_signaling[pool] || 0;
      const hold = total - sig;
      sigTotals[pool] = (sigTotals[pool] || 0) + sig;
      holdTotals[pool] = (holdTotals[pool] || 0) + hold;
    });
  });

  const topSignalers = Object.entries(sigTotals).sort((a, b) => b[1] - a[1]).slice(0, 5).map(p => p[0]);
  const topHoldouts = Object.entries(holdTotals).sort((a, b) => b[1] - a[1]).slice(0, 5).map(p => p[0]);

  // Update the mini-leaderboard list
  const sigList = document.getElementById('list-top-signalers');
  const holdList = document.getElementById('list-top-holdouts');
  const latestDay = trendData[trendData.length - 1];

  if (sigList) {
    sigList.innerHTML = topSignalers.map((name, i) => {
      const share = latestDay.total_blocks > 0 ? (latestDay.pools_signaling[name] || 0) / latestDay.total_blocks * 100 : 0;
      return `<div style="display:flex; justify-content:space-between; font-size:0.85rem; padding:4px 0; border-bottom:1px solid rgba(255,255,255,0.05);">
                <span style="color:var(--text-primary); font-weight:500;">${name}</span>
                <span style="color:#4ade80; font-weight:bold;">${share.toFixed(1)}%</span>
              </div>`;
    }).join('');
  }

  if (holdList) {
    holdList.innerHTML = topHoldouts.map((name, i) => {
      const total = latestDay.pools_total[name] || 0;
      const sig = latestDay.pools_signaling[name] || 0;
      const share = latestDay.total_blocks > 0 ? (total - sig) / latestDay.total_blocks * 100 : 0;
      return `<div style="display:flex; justify-content:space-between; font-size:0.85rem; padding:4px 0; border-bottom:1px solid rgba(255,255,255,0.05);">
                <span style="color:var(--text-primary); font-weight:500;">${name}</span>
                <span style="color:#ef4444; font-weight:bold;">${share.toFixed(1)}%</span>
              </div>`;
    }).join('');
  }

  const signalerSet = new Set(topSignalers);
  const holdoutSet = new Set(topHoldouts);

  // 2. Build Series (Stacked)
  // We want Signaling at the bottom (Greens), then Holdouts at the top (Grays/Reds)
  const series = [];

  // SIGNALERS (Greenish)
  topSignalers.forEach((name, i) => {
    series.push({
      name: `Signal: ${name}`,
      type: 'line',
      stack: 'total',
      smooth: true,
      symbol: 'none',
      areaStyle: { opacity: 0.85 },
      lineStyle: { width: 0 },
      color: ['#4ade80', '#22c55e', '#16a34a', '#15803d', '#14532d'][i],
      emphasis: { focus: 'series' },
      data: trendData.map(d => d.total_blocks > 0 ? (d.pools_signaling[name] || 0) / d.total_blocks * 100 : 0)
    });
  });

  // OTHER SIGNALERS
  series.push({
    name: 'Other Signalers',
    type: 'line',
    stack: 'total',
    smooth: true,
    symbol: 'none',
    areaStyle: { opacity: 0.6 },
    lineStyle: { width: 0 },
    color: '#064e3b',
    data: trendData.map(d => {
      let sum = 0;
      Object.entries(d.pools_signaling).forEach(([p, c]) => { if (!signalerSet.has(p)) sum += c; });
      return d.total_blocks > 0 ? sum / d.total_blocks * 100 : 0;
    })
  });

  // HOLDOUTS (Reds/Grays)
  topHoldouts.forEach((name, i) => {
    series.push({
      name: `Holdout: ${name}`,
      type: 'line',
      stack: 'total',
      smooth: true,
      symbol: 'none',
      areaStyle: { opacity: 0.7 },
      lineStyle: { width: 0 },
      color: ['#ef4444', '#dc2626', '#b91c1c', '#991b1b', '#7f1d1d'][i],
      emphasis: { focus: 'series' },
      data: trendData.map(d => {
        const total = d.pools_total[name] || 0;
        const sig = d.pools_signaling[name] || 0;
        return d.total_blocks > 0 ? (total - sig) / d.total_blocks * 100 : 0;
      })
    });
  });

  // OTHER HOLDOUTS
  series.push({
    name: 'Other Holdouts',
    type: 'line',
    stack: 'total',
    smooth: true,
    symbol: 'none',
    areaStyle: { opacity: 0.5 },
    lineStyle: { width: 0 },
    color: '#334155',
    data: trendData.map(d => {
      let sum = 0;
      Object.entries(d.pools_total).forEach(([p, t]) => {
        if (!holdoutSet.has(p)) {
          const s = d.pools_signaling[p] || 0;
          sum += (t - s);
        }
      });
      return d.total_blocks > 0 ? sum / d.total_blocks * 100 : 0;
    })
  });

  // Activation Progress Rolling Line
  series.push({
    name: '2,016 Block Activation Progress',
    type: 'line',
    smooth: true,
    symbol: 'none',
    lineStyle: { color: '#E2A34A', width: 4, type: 'solid', shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.5)' },
    data: globalRolling,
    markLine: {
      silent: true,
      symbol: 'none',
      label: { formatter: 'Activation (55%)', position: 'end', color: '#E2A34A', fontWeight: 'bold' },
      lineStyle: { color: '#E2A34A', type: 'dashed', opacity: 0.9, width: 2 },
      data: [{ yAxis: 55 }]
    }
  });

  bip110SignalingChart.setOption({
    backgroundColor: 'transparent',
    tooltip: {
      ...baseTooltip({ confine: true }),
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      formatter: (params) => {
        let h = `<div style="margin-bottom:5px; font-weight:bold; border-bottom:1px solid rgba(255,255,255,0.1); padding-bottom:5px;">${params[0].axisValue} Coverage</div>`;
        let sig = [];
        let hold = [];
        let rolling = null;
        params.forEach(p => {
          if (p.seriesName.includes('Activation')) rolling = p.value;
          else if (p.seriesName.includes('Signal')) sig.push(p);
          else hold.push(p);
        });

        h += `<div style="display:grid; grid-template-columns: 1fr 1fr; gap:15px;">`;
        h += `<div><span style="color:#4ade80; font-size:10px; font-weight:bold;">SIGNALERS</span><br/>`;
        sig.forEach(p => {
          if (p.value > 0.1) h += `<div style="font-size:11px;">${p.marker} ${p.seriesName.replace('Signaling: ', '').replace('Signal: ', '')}: ${p.value.toFixed(1)}%</div>`;
        });
        h += `</div>`;
        h += `<div><span style="color:#ef4444; font-size:10px; font-weight:bold;">HOLDOUTS</span><br/>`;
        hold.forEach(p => {
          if (p.value > 0.1) h += `<div style="font-size:11px;">${p.marker} ${p.seriesName.replace('Holdout: ', '')}: ${p.value.toFixed(1)}%</div>`;
        });
        h += `</div></div>`;
        if (rolling !== null) h += `<div style="margin-top:8px; padding-top:5px; border-top:1px solid rgba(255,255,255,0.1); color:#E2A34A; font-weight:bold;">Activation Progress: ${rolling}%</div>`;
        return h;
      }
    },
    legend: {
      show: false // Too many items, better to use tooltip
    },
    grid: { top: 40, left: 50, right: 50, bottom: 40 },
    xAxis: {
      type: 'category',
      data: days,
      axisLabel: { color: THEME.muted, fontSize: 10, rotate: 30, hideOverlap: true },
      axisLine: { lineStyle: { color: THEME.border } }
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: 100,
      axisLabel: { color: THEME.muted, formatter: '{value}%' },
      splitLine: { lineStyle: { color: THEME.border, type: 'dashed' } }
    },
    series
  }, true);
}

// ── KPI 7: BIP 110 Efficiency (Scatter) ──────────────────────────────────────
export let bip110EfficiencyChart = null;
export function renderBip110Efficiency(efficiencyData) {
  const el = document.getElementById('chart-bip110-efficiency');
  if (!el || !efficiencyData || efficiencyData.length === 0) return;
  if (!bip110EfficiencyChart) {
    bip110EfficiencyChart = ec().init(el, null, { renderer: 'canvas' });
    window.addEventListener('resize', () => bip110EfficiencyChart.resize());
  }

  // Aggregate 4,000+ per-block rows to pool-level averages
  const agg = {};
  efficiencyData.forEach(d => {
    if (!agg[d.pool_name]) agg[d.pool_name] = { tx: 0, bytes: 0, n: 0 };
    agg[d.pool_name].tx    += d.tx_count;
    agg[d.pool_name].bytes += d.bytes_total;
    agg[d.pool_name].n     += 1;
  });

  const poolList = Object.entries(agg)
    .filter(([, v]) => v.n >= 10)  // enough data to be meaningful
    .map(([name, v]) => ({
      name,
      avg_tx: Math.round(v.tx / v.n),
      avg_mb: +(v.bytes / v.n / 1e6).toFixed(3),
      bpt:    Math.round(v.bytes / v.tx),  // bytes per transaction
      n:      v.n,
    }))
    .sort((a, b) => b.bpt - a.bpt);  // most bloated first

  const bpts  = poolList.map(d => d.bpt);
  const minBpt = Math.min(...bpts);
  const maxBpt = Math.max(...bpts);
  const bptColor = (bpt) => {
    const t = (bpt - minBpt) / (maxBpt - minBpt);
    if (t > 0.65) return '#ff4d4f';   // inscription-heavy
    if (t > 0.35) return THEME.accent; // medium
    return '#98C379';                  // compact / fee-dense
  };

  bip110EfficiencyChart.setOption({
    backgroundColor: 'transparent',
    tooltip: {
      ...baseTooltip({ confine: true }),
      trigger: 'item',
      formatter: (p) => {
        const [avg_tx, avg_mb, n, bpt, name] = p.data;
        const c   = bptColor(bpt);
        const tag = bpt > minBpt + (maxBpt - minBpt) * 0.65 ? '🔴 inscription-heavy'
                  : bpt < minBpt + (maxBpt - minBpt) * 0.35 ? '✅ compact'
                  : '🟡 medium';
        return `<b style="color:${THEME.accent}">${name}</b><br/>` +
          `Avg TXs/block: <b>${avg_tx.toLocaleString()}</b><br/>` +
          `Avg block size: <b>${avg_mb.toFixed(2)} MB</b><br/>` +
          `<span style="color:${c}">Bytes/TX: <b>${bpt}</b> ${tag}</span><br/>` +
          `<span style="color:${THEME.muted};font-size:10px">Sample: ${n.toLocaleString()} blocks</span>`;
      },
    },
    grid: { top: 20, left: 75, right: 20, bottom: 55 },
    xAxis: {
      type: 'value',
      name: 'Avg TXs per Block',
      nameLocation: 'middle',
      nameGap: 32,
      axisLabel: { color: THEME.muted, fontSize: 11 },
      splitLine: { lineStyle: { color: THEME.border, type: 'dashed' } },
      axisLine: { lineStyle: { color: THEME.border } },
    },
    yAxis: {
      type: 'value',
      name: 'Avg Block Size (MB)',
      nameLocation: 'middle',
      nameGap: 50,
      axisLabel: { color: THEME.muted, fontSize: 11, formatter: (v) => v.toFixed(1) + ' MB' },
      splitLine: { lineStyle: { color: THEME.border, type: 'dashed' } },
    },
    series: [{
      type: 'scatter',
      // bubble size = sqrt(n_blocks) — shows statistical weight
      symbolSize: (val) => Math.max(10, Math.sqrt(val[2]) * 1.4),
      // [avg_tx, avg_mb, n, bpt, name]
      data: poolList.map(d => [d.avg_tx, d.avg_mb, d.n, d.bpt, d.name]),
      itemStyle: {
        color: (p) => bptColor(p.data[3]),
        opacity: 0.9,
        borderColor: THEME.bg,
        borderWidth: 1.5,
      },
      label: {
        show: true,
        formatter: (p) => p.data[4],
        position: 'top',
        fontSize: 11,
        color: THEME.muted,
        distance: 4,
      },
    }],
  }, true);
}

// ── KPI 7: BIP 110 Over-Limit (Bar) ──────────────────────────────────────────
export let bip110OverheadChart = null;
export function renderBip110Overhead(overheadData) {
  const el = document.getElementById('chart-bip110-overhead');
  if (!el || !overheadData || overheadData.length === 0) return;
  if (!bip110OverheadChart) {
    bip110OverheadChart = ec().init(el, null, { renderer: 'canvas' });
    window.addEventListener('resize', () => bip110OverheadChart.resize());
  }

  const data = [...overheadData].sort((a, b) => a.avg_overhead - b.avg_overhead);

  // 3-tier color scale: massive outlier → bright red, above threshold → amber-red, compliant → green
  const barColor = (v) => v > 2000 ? '#ff4d4f' : v > 256 ? '#E06C75' : '#98C379';

  bip110OverheadChart.setOption({
    backgroundColor: 'transparent',
    tooltip: {
      ...baseTooltip({ confine: true }),
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params) => {
        const pool  = params[0].name;
        const avg   = params[0].value;
        const found = overheadData.find(d => d.pool === pool);
        const max   = found ? found.max_overhead : 0;
        const maxFmt = max >= 1024 ? `${(max / 1024).toFixed(1)} kB/tx` : `${Math.round(max)} B/tx`;
        const c = barColor(avg);
        return `<b style="color:${THEME.accent}">${pool}</b><br/>` +
          `Avg overhead: <b style="color:${c}">${Math.round(avg)} B/tx</b><br/>` +
          `Peak spike: <b>${maxFmt}</b><br/>` +
          `<span style="color:${THEME.muted};font-size:10px">BIP 110 proposed limit: 256 B/tx</span>`;
      },
    },
    grid: { top: 15, left: 120, right: 105, bottom: 52 },
    xAxis: {
      type: 'log',
      logBase: 10,
      name: 'Witness Bytes per TX  (log₁₀ scale)',
      nameLocation: 'middle',
      nameGap: 30,
      min: 100,
      axisLabel: {
        color: THEME.muted,
        fontSize: 11,
        formatter: (v) => v >= 1000 ? `${(v / 1000).toFixed(0)}k` : v,
      },
      splitLine: { lineStyle: { color: THEME.border, type: 'dashed' } },
    },
    yAxis: {
      type: 'category',
      data: data.map(d => d.pool),
      axisLabel: { color: THEME.text, fontSize: 12 },
      axisLine: { lineStyle: { color: THEME.border } },
    },
    series: [{
      name: 'Avg Overhead',
      type: 'bar',
      barWidth: 14,
      data: data.map(d => ({
        value: d.avg_overhead,
        itemStyle: { color: barColor(d.avg_overhead), borderRadius: [0, 3, 3, 0] },
      })),
      label: {
        show: true,
        position: 'right',
        color: THEME.muted,
        fontSize: 11,
        formatter: (p) => `${Math.round(p.value).toLocaleString()} B/tx ${p.value > 256 ? '↑' : '↓'}`,
      },
      markLine: {
        silent: true,
        symbol: 'none',
        label: { formatter: 'BIP 110 limit (256B)', position: 'insideStartBottom', color: '#ff4d4f', fontSize: 9 },
        lineStyle: { color: '#ff4d4f', type: 'dashed', opacity: 0.55 },
        data: [{ xAxis: 256 }],
      },
    }],
  }, true);
}

// ── Quarterly Lift Sparklines (below Second Block Uplift chart) ─────────────
let quarterlyLiftChart = null;
export function renderQuarterlyLift(syncData) {
  const el = document.getElementById('chart-quarterly-lift');
  if (!el || !syncData || syncData.length === 0) return;
  if (!quarterlyLiftChart) {
    quarterlyLiftChart = ec().init(el, null, { renderer: 'canvas' });
    window.addEventListener('resize', () => quarterlyLiftChart.resize());
  }

  // Pick top 5 pools by lift for sparkline clarity
  const totalAllBlocks = syncData.reduce((s, p) => s + p.total_blocks, 0);
  const ranked = syncData.map(p => {
    const exp = p.expected_consecutive || (p.total_blocks / totalAllBlocks * p.total_blocks);
    return { pool: p.pool, lift: p.total_consecutive / exp, quarterly_lift: p.quarterly_lift || [] };
  }).sort((a, b) => b.lift - a.lift).slice(0, 5);

  // Choose the source: quarterly_lift if it has ≥ 4 windows, otherwise use monthly_lift
  // Build a unified quarter/month label set
  const poolsToPlot = ranked.map(p => {
    const ql = p.quarterly_lift;
    const src = (ql && ql.length >= 4) ? ql.map(q => ({ label: q.quarter, lift: q.lift })) :
      (syncData.find(s => s.pool === p.pool)?.monthly_lift || []).map(m => ({ label: m.month, lift: m.lift }));
    return { pool: p.pool, series: src.filter(s => s.lift !== null) };
  });

  // Collect all labels across all pools for the x-axis
  const labelSet = new Set();
  poolsToPlot.forEach(p => p.series.forEach(s => labelSet.add(s.label)));
  const labels = Array.from(labelSet).sort();

  const series = poolsToPlot.map((p, i) => ({
    name: p.pool,
    type: 'bar',
    barMaxWidth: 12,
    data: labels.map(l => {
      const entry = p.series.find(s => s.label === l);
      return entry ? +entry.lift.toFixed(3) : null;
    }),
    itemStyle: { color: POOL_COLORS[i % POOL_COLORS.length] },
    emphasis: { focus: 'series' },
  }));

  quarterlyLiftChart.setOption({
    backgroundColor: 'transparent',
    tooltip: {
      ...baseTooltip({ confine: true }),
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params) => {
        const label = params[0].axisValue;
        let str = `<b style="color:${THEME.accent}">${label}</b>`;
        params.forEach(p => {
          if (p.value === null || p.value === undefined) return;
          const c = p.value > 1.5 ? '#ff4d4f' : p.value > 1.0 ? '#E2A34A' : '#56B6C2';
          str += `<br/>${p.marker}${p.seriesName}: <b style="color:${c}">${p.value.toFixed(2)}×</b>`;
        });
        return str;
      },
    },
    legend: { top: 0, textStyle: { color: THEME.muted, fontSize: 10 }, itemWidth: 10, itemHeight: 10 },
    grid: { top: 30, left: 40, right: 20, bottom: 45 },
    xAxis: {
      type: 'category',
      data: labels,
      axisLabel: { color: THEME.muted, fontSize: 9, rotate: 35, interval: Math.max(0, Math.floor(labels.length / 10) - 1) },
      axisLine: { lineStyle: { color: THEME.border } },
    },
    yAxis: {
      type: 'value',
      name: 'Lift',
      nameTextStyle: { color: THEME.muted, fontSize: 10 },
      axisLabel: { color: THEME.muted, fontSize: 10, formatter: v => v.toFixed(1) + '×' },
      splitLine: { lineStyle: { color: THEME.border, type: 'dashed' } },
      axisLine: { lineStyle: { color: THEME.border } },
    },
    series,
    markLine: {
      silent: true,
      symbol: 'none',
      data: [{ yAxis: 1.0, lineStyle: { color: 'rgba(139,148,158,0.5)', type: 'dashed' } }],
    },
  }, true);
}

// ── KPI 8: Cross-pool Transition Matrix Heatmap ──────────────────────────────
export function renderTransitionMatrix(transitionData) {
  const el = document.getElementById('chart-transition-matrix');
  if (!el || !transitionData) return;

  const pools = transitionData.pools || [];
  const matrix = transitionData.matrix || [];
  const anomalies = transitionData.anomalies || [];
  const notableLowN = transitionData.notable_low_n || [];
  const poolCountries = transitionData.pool_countries || {};
  if (pools.length === 0) return;

  function poolBadge(slug) {
    return countryBadge(poolCountries[slug] || 'Unknown');
  }
  // Are two pools in the same country (and not "Global"/"Unknown")
  function sameCountry(a, b) {
    const ca = poolCountries[a], cb = poolCountries[b];
    return ca && cb && ca === cb && ca !== 'Global' && ca !== 'Unknown';
  }

  // Build quick lookup map
  const liftMap = {};
  const nMap = {};
  matrix.forEach(m => {
    liftMap[`${m.from}||${m.to}`] = m.lift;
    nMap[`${m.from}||${m.to}`] = m.n;
  });

  // Confidence threshold: cells below this n are dimmed
  const LOW_N = 100;

  function liftToColor(lift, n) {
    if (lift === null || lift === undefined) return 'rgba(30,35,45,0.4)';
    const alpha = n < LOW_N ? 0.35 : 1.0;  // dim low-sample cells
    if (lift > 2.0)  return `rgba(255,77,79,${0.75 * alpha})`;
    if (lift > 1.5)  return `rgba(255,77,79,${0.45 * alpha})`;
    if (lift > 1.2)  return `rgba(226,163,74,${0.55 * alpha})`;
    if (lift > 1.0)  return `rgba(226,163,74,${0.18 * alpha})`;
    if (lift > 0.85) return `rgba(255,255,255,${0.04 * alpha})`;
    return `rgba(86,182,194,${0.35 * alpha})`;
  }

  function liftLabel(lift) {
    if (lift === null || lift === undefined) return '—';
    return lift.toFixed(2) + '×';
  }

  // Build header row — column headers show flag badge
  const thStyle = 'padding:5px 6px;font-size:0.65rem;color:var(--text-secondary);font-weight:700;text-align:center;white-space:nowrap;border-bottom:1px solid rgba(48,54,61,0.8);';
  const tdBase = 'padding:4px 5px;font-size:0.7rem;text-align:center;border:1px solid rgba(48,54,61,0.4);line-height:1.3;min-width:62px;';
  const tdLabel = 'padding:5px 8px;font-size:0.72rem;font-weight:600;color:var(--text-primary);white-space:nowrap;border:1px solid rgba(48,54,61,0.4);';

  let thead = `<tr><th style="${thStyle}text-align:left;">Block N →<br><span style="font-weight:400;font-size:0.6rem;">Block N+1 ↓ &nbsp;lift · (n)</span></th>`;
  pools.forEach(col => {
    const abbr = col.length > 8 ? col.slice(0, 7) + '…' : col;
    thead += `<th style="${thStyle}" title="${col} · ${poolCountries[col] || ''}">${abbr}${poolBadge(col)}</th>`;
  });
  thead += '</tr>';

  let tbody = '';
  pools.forEach(rowPool => {
    const rowCountry = poolCountries[rowPool] || 'Unknown';
    const rowBg = COUNTRY_COLOR[rowCountry] || 'transparent';
    let row = `<tr><td style="${tdLabel}background:${rowBg};">${rowPool}${poolBadge(rowPool)}</td>`;
    pools.forEach(colPool => {
      const key = `${rowPool}||${colPool}`;
      const lift = liftMap[key];
      const n = nMap[key] || 0;
      const isDiag = rowPool === colPool;
      const sameCo = !isDiag && sameCountry(rowPool, colPool);
      const bg = liftToColor(lift, n);
      const textOpacity = n < LOW_N ? '0.45' : '1';
      const textColor = (lift !== null && lift > 1.2 && n >= LOW_N) ? 'var(--text-primary)' : `rgba(139,148,158,${textOpacity})`;
      const diagBorder = isDiag ? 'outline:1px solid rgba(226,163,74,0.4);outline-offset:-2px;' : '';
      const sameCoBorder = sameCo ? 'outline:1px dotted rgba(255,180,80,0.3);outline-offset:-2px;' : '';
      const nStr = n > 0 ? `<div style="font-size:0.58rem;color:rgba(139,148,158,0.55);margin-top:1px;">${n < 1000 ? n : (n/1000).toFixed(1)+'k'}</div>` : '';
      const lowNNote = n > 0 && n < LOW_N ? '<span title="Low sample — treat with caution" style="font-size:0.6rem;color:rgba(226,163,74,0.5);"> ⚠</span>' : '';
      row += `<td style="${tdBase}background:${bg};color:${textColor};${diagBorder}${sameCoBorder}" title="${rowPool} → ${colPool}: n=${n.toLocaleString()}, lift=${liftLabel(lift)}, ${poolCountries[rowPool]||'?'} → ${poolCountries[colPool]||'?'}">${liftLabel(lift)}${lowNNote}${nStr}</td>`;
    });
    row += '</tr>';
    tbody += row;
  });

  // Geo summary — count anomalies by country pair
  const geoTally = {};
  [...anomalies, ...notableLowN].forEach(a => {
    const ca = poolCountries[a.from] || 'Unknown';
    const cb = poolCountries[a.to] || 'Unknown';
    const k = ca === cb ? `${ca} → ${ca} (same)` : `${ca} → ${cb}`;
    geoTally[k] = (geoTally[k] || 0) + 1;
  });
  const geoEntries = Object.entries(geoTally).sort((a,b) => b[1]-a[1]);
  const geoHtml = geoEntries.length > 0 ? `
    <div style="margin-top:10px;padding:10px 14px;background:rgba(226,163,74,0.04);border:1px solid rgba(226,163,74,0.12);border-radius:6px;font-size:0.75rem;display:flex;flex-wrap:wrap;gap:10px;align-items:center;">
      <span style="font-size:0.68rem;text-transform:uppercase;letter-spacing:0.07em;color:var(--text-secondary);font-weight:700;flex-shrink:0;">Geographic pattern:</span>
      ${geoEntries.map(([k,v]) => `<span style="color:var(--text-primary);">${k} <b style="color:var(--accent)">${v} pair${v>1?'s':''}</b></span>`).join('<span style="color:var(--text-secondary);margin:0 2px;">·</span>')}
    </div>` : '';

  const tableHtml = `
    <div style="overflow-x:auto;margin-bottom:10px;">
      <table style="border-collapse:collapse;width:100%;">
        <thead>${thead}</thead>
        <tbody>${tbody}</tbody>
      </table>
    </div>
    <div style="display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin-bottom:8px;font-size:0.68rem;color:var(--text-secondary);">
      <span><span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:rgba(255,77,79,0.75);vertical-align:middle;margin-right:3px;"></span>&gt;2.0×</span>
      <span><span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:rgba(255,77,79,0.45);vertical-align:middle;margin-right:3px;"></span>&gt;1.5×</span>
      <span><span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:rgba(226,163,74,0.55);vertical-align:middle;margin-right:3px;"></span>&gt;1.2× elevated</span>
      <span><span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:rgba(255,255,255,0.04);vertical-align:middle;margin-right:3px;"></span>~1.0× baseline</span>
      <span><span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:rgba(86,182,194,0.35);vertical-align:middle;margin-right:3px;"></span>&lt;0.85× avoidance</span>
      <span style="margin-left:8px;">⚠ = n&lt;${LOW_N}, low confidence &nbsp;·&nbsp; diagonal = self-transition &nbsp;·&nbsp; dotted border = same country</span>
    </div>
    ${geoHtml}`;

  function anomalyRow(a, lowN = false) {
    const c = a.lift > 2.0 ? '#ff4d4f' : a.lift > 1.5 ? '#E87E51' : '#E2A34A';
    const caFrom = poolCountries[a.from] || 'Unknown';
    const caTo = poolCountries[a.to] || 'Unknown';
    const flagFrom = countryBadge(caFrom);
    const flagTo = countryBadge(caTo);
    const caveat = lowN ? `<span style="color:rgba(226,163,74,0.6);font-size:0.65rem;"> ⚠ n=${a.n} (low sample)</span>` : '';
    return `<div style="display:flex;align-items:center;gap:8px;padding:6px 10px;border-bottom:1px solid rgba(48,54,61,0.35);font-size:0.76rem;flex-wrap:wrap;">
      <span style="color:var(--text-secondary);min-width:180px;">${flagFrom} ${a.from} <span style="color:${THEME.muted};font-size:0.7rem;">→</span> ${flagTo} ${a.to}${caveat}</span>
      <span style="color:${c};font-weight:700;width:50px;">${a.lift.toFixed(2)}×</span>
      <span style="color:var(--text-secondary);font-size:0.68rem;">n=${a.n.toLocaleString()} &nbsp;|&nbsp; obs ${(a.observed_rate*100).toFixed(2)}% vs exp ${(a.expected_rate*100).toFixed(2)}%</span>
    </div>`;
  }

  let anomalyHtml = '';
  if (anomalies.length > 0) {
    anomalyHtml += `
      <div style="margin-top:12px;">
        <div style="font-size:0.68rem;text-transform:uppercase;letter-spacing:0.08em;color:var(--text-secondary);font-weight:700;padding:6px 10px;border-bottom:1px solid rgba(48,54,61,0.6);">Confirmed Anomalous Pairs (lift &gt; 1.15, n &gt; 200)</div>
        ${anomalies.slice(0, 10).map(a => anomalyRow(a, false)).join('')}
      </div>`;
  }
  if (notableLowN.length > 0) {
    anomalyHtml += `
      <div style="margin-top:10px;">
        <div style="font-size:0.68rem;text-transform:uppercase;letter-spacing:0.08em;color:rgba(226,163,74,0.7);font-weight:700;padding:6px 10px;border-bottom:1px solid rgba(48,54,61,0.6);">High-Lift / Insufficient Sample ⚠ (lift &gt; 1.30, n 30–200 — treat as directional only)</div>
        ${notableLowN.map(a => anomalyRow(a, true)).join('')}
      </div>`;
  }

  el.innerHTML = tableHtml + anomalyHtml;
}

export function resizeAllCharts() {
  const charts = [
    donutChart, countryChart, growthChart, areaChart, hhiChart, concentrationChart,
    zscoreChart, entropyChart, syncChart, consecutiveAdvantageChart, emptyChart, emptyTrendChart,
    bip110SignalingChart, bip110EfficiencyChart, bip110OverheadChart, quarterlyLiftChart
  ];
  charts.forEach(c => c && c.resize());
}
