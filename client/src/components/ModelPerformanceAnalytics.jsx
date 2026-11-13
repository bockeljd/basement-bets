import React, { useMemo, useState } from 'react';
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  ComposedChart,
  BarChart,
  Bar,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  Cell,
} from 'recharts';
import {
  getPerformanceDay,
  roiPerUnit,
  getConfidenceBucket,
  getNumericConfidence,
  getRawOutcome,
  getEffectivePrice,
  normalizeOutcome,
  formatMarketLabel,
  getNumericEdge,
  normalizeSport,
} from '../utils/modelPerformance';

const TOOLTIP_STYLE = {
  backgroundColor: '#020617',
  borderColor: '#334155',
  borderRadius: '0.75rem',
  color: '#f8fafc',
  fontSize: '12px',
  padding: '8px 12px',
};

const formatUnits = (u) => {
  const val = Number(u || 0);
  if (Math.abs(val) < 0.005) return '0.00u';
  return `${val > 0 ? '+' : ''}${val.toFixed(2)}u`;
};

const formatPct = (p, digits = 1) => {
  const val = Number(p || 0);
  return `${val.toFixed(digits)}%`;
};

const formatSignedPct = (p, digits = 1) => {
  const val = Number(p || 0);
  if (Math.abs(val) < 0.05) return '0.0%';
  return `${val > 0 ? '+' : ''}${val.toFixed(digits)}%`;
};

const shortDayLabel = (isoDay) => {
  if (!isoDay || isoDay.length < 10) return isoDay || '';
  return isoDay.slice(5); // MM-DD
};

const createBucketAccumulator = (label) => ({
  label,
  total: 0,
  wins: 0,
  losses: 0,
  pushes: 0,
  profitUnits: 0,
  clvSum: 0,
  clvCount: 0,
});

const accumulateRowInto = (acc, h) => {
  const out = getRawOutcome(h);
  const norm = normalizeOutcome(out);
  const roi = roiPerUnit(out, getEffectivePrice(h));
  acc.total += 1;
  if (norm === 'WON') acc.wins += 1;
  else if (norm === 'LOST') acc.losses += 1;
  else if (norm === 'PUSH') acc.pushes += 1;
  acc.profitUnits += roi;
  const clv = parseFloat(h?.clv_points);
  if (Number.isFinite(clv)) {
    acc.clvSum += clv;
    acc.clvCount += 1;
  }
};

const finalizeBucket = (b) => {
  const decided = b.wins + b.losses;
  const settled = decided + b.pushes;
  return {
    ...b,
    decided,
    settled,
    recordText: `${b.wins}-${b.losses}${b.pushes > 0 ? `-${b.pushes}` : ''}`,
    winRate: decided > 0 ? (b.wins / decided) * 100 : 0,
    roiPct: settled > 0 ? (b.profitUnits / settled) * 100 : 0,
    avgClv: b.clvCount > 0 ? b.clvSum / b.clvCount : null,
  };
};

const ModelPerformanceAnalytics = ({
  history = [],
  allHistory = null,
  selectedSport = 'ALL',
  onSelectSport = null,
  scopeLabel = 'all recommended picks',
  filterSummary = 'All Sports • All Time',
}) => {
  const [trendTab, setTrendTab] = useState('cumulative');
  const [edgeTab, setEdgeTab] = useState('chart');

  const analytics = useMemo(() => {
    const safeHistory = Array.isArray(history) ? history : [];
    const graded = safeHistory.filter((h) => {
      const n = normalizeOutcome(getRawOutcome(h));
      return n === 'WON' || n === 'LOST' || n === 'PUSH';
    });

    // 1. Daily chronological aggregation (for Cumulative Units, Daily Bars, Recent Windows)
    const dayMap = {};
    for (const h of safeHistory) {
      const day = getPerformanceDay(h);
      if (!day) continue;
      if (!dayMap[day]) {
        dayMap[day] = {
          day,
          shortDay: shortDayLabel(day),
          wins: 0,
          losses: 0,
          pushes: 0,
          profitUnits: 0,
          confSum: 0,
          confCount: 0,
          totalPicks: 0,
        };
      }
      const d = dayMap[day];
      d.totalPicks += 1;
      const conf = getNumericConfidence(h);
      if (conf > 0) {
        d.confSum += conf;
        d.confCount += 1;
      }

      const out = getRawOutcome(h);
      const norm = normalizeOutcome(out);
      const roi = roiPerUnit(out, getEffectivePrice(h));
      if (norm === 'WON') d.wins += 1;
      else if (norm === 'LOST') d.losses += 1;
      else if (norm === 'PUSH') d.pushes += 1;
      if (norm === 'WON' || norm === 'LOST' || norm === 'PUSH') {
        d.profitUnits += roi;
      }
    }

    let runningUnits = 0;
    const chronologicalDays = Object.values(dayMap)
      .sort((a, b) => a.day.localeCompare(b.day))
      .map((d) => {
        const decided = d.wins + d.losses;
        const settled = decided + d.pushes;
        runningUnits += d.profitUnits;
        return {
          ...d,
          decided,
          settled,
          recordText: `${d.wins}-${d.losses}${d.pushes > 0 ? `-${d.pushes}` : ''}`,
          winRate: decided > 0 ? Number(((d.wins / decided) * 100).toFixed(1)) : null,
          profitUnits: Number(d.profitUnits.toFixed(2)),
          cumulativeUnits: Number(runningUnits.toFixed(2)),
          avgConf: d.confCount > 0 ? Number((d.confSum / d.confCount).toFixed(1)) : null,
        };
      });

    const settledDays = chronologicalDays.filter((d) => d.settled > 0);
    const recentDailyBars = settledDays.slice(-45);

    // 2. Recent Rolling Windows (ET calendar relative to latest ET day / today)
    const nowEtStr = new Date().toLocaleDateString('en-CA', { timeZone: 'America/New_York' });
    const etMinusDays = (daysAgo) => {
      const dt = new Date(`${nowEtStr}T12:00:00Z`);
      dt.setUTCDate(dt.getUTCDate() - daysAgo);
      return dt.toISOString().slice(0, 10);
    };
    const yesterdayStr = etMinusDays(1);
    const cutoff3 = etMinusDays(3);
    const cutoff7 = etMinusDays(7);
    const cutoff30 = etMinusDays(30);

    const rollAcc = {
      Yesterday: createBucketAccumulator('Yesterday'),
      'Last 3 Days': createBucketAccumulator('Last 3 Days'),
      'Last 7 Days': createBucketAccumulator('Last 7 Days'),
      'Last 30 Days': createBucketAccumulator('Last 30 Days'),
    };
    for (const h of graded) {
      const day = getPerformanceDay(h);
      if (!day) continue;
      if (day === yesterdayStr) accumulateRowInto(rollAcc.Yesterday, h);
      if (day >= cutoff3 && day <= nowEtStr) accumulateRowInto(rollAcc['Last 3 Days'], h);
      if (day >= cutoff7 && day <= nowEtStr) accumulateRowInto(rollAcc['Last 7 Days'], h);
      if (day >= cutoff30 && day <= nowEtStr) accumulateRowInto(rollAcc['Last 30 Days'], h);
    }
    const recentWindows = Object.values(rollAcc).map(finalizeBucket);

    // 3. Edge Calibration Buckets
    const edgeDefs = [
      { key: 'under2', label: '< 2%', match: (pct) => pct < 2 },
      { key: '2to5', label: '2% – 5%', match: (pct) => pct >= 2 && pct < 5 },
      { key: '5to10', label: '5% – 10%', match: (pct) => pct >= 5 && pct < 10 },
      { key: '10to15', label: '10% – 15%', match: (pct) => pct >= 10 && pct < 15 },
      { key: '15to25', label: '15% – 25%', match: (pct) => pct >= 15 && pct < 25 },
      { key: '25plus', label: '25%+', match: (pct) => pct >= 25 },
    ];
    const edgeMap = Object.fromEntries(edgeDefs.map((d) => [d.key, createBucketAccumulator(d.label)]));
    for (const h of graded) {
      const edgeDecimal = getNumericEdge(h);
      const edgePct = edgeDecimal != null ? edgeDecimal * 100 : 0;
      const def = edgeDefs.find((d) => d.match(edgePct)) || edgeDefs[0];
      accumulateRowInto(edgeMap[def.key], h);
    }
    const edgeBuckets = edgeDefs
      .map((d) => finalizeBucket(edgeMap[d.key]))
      .filter((b) => b.label !== '< 2%' || b.settled > 0);

    // 4. Confidence Tiers (High >= 80, Medium 50-79, Low < 50)
    const confDefs = ['High', 'Medium', 'Low'];
    const confMap = Object.fromEntries(confDefs.map((k) => [k, createBucketAccumulator(k)]));
    for (const h of graded) {
      const tier = getConfidenceBucket(h);
      if (!confMap[tier]) confMap[tier] = createBucketAccumulator(tier);
      accumulateRowInto(confMap[tier], h);
    }
    const confidenceTiers = confDefs.map((k) => ({
      ...finalizeBucket(confMap[k]),
      desc: k === 'High' ? 'Score 80+' : k === 'Medium' ? 'Score 50–79' : 'Score < 50',
    }));

    // 5. Bet Type Breakdown
    const marketMap = {};
    for (const h of graded) {
      const label = formatMarketLabel(h);
      if (!marketMap[label]) marketMap[label] = createBucketAccumulator(label);
      accumulateRowInto(marketMap[label], h);
    }
    const betTypes = Object.values(marketMap)
      .map(finalizeBucket)
      .sort((a, b) => b.settled - a.settled);

    // 6. By Sport Comparison (from allHistory across sports if supplied)
    const sportSource = Array.isArray(allHistory) ? allHistory : safeHistory;
    const sportMap = {};
    for (const h of sportSource) {
      const out = getRawOutcome(h);
      const norm = normalizeOutcome(out);
      const sp = normalizeSport(h);
      if (!sportMap[sp]) {
        sportMap[sp] = {
          ...createBucketAccumulator(sp),
          sport: sp,
          pending: 0,
          voids: 0,
        };
      }
      if (norm === 'WON' || norm === 'LOST' || norm === 'PUSH') {
        accumulateRowInto(sportMap[sp], h);
      } else if (norm === 'VOID') {
        sportMap[sp].voids += 1;
      } else {
        sportMap[sp].pending += 1;
      }
    }
    const sportBreakdown = Object.values(sportMap)
      .map(finalizeBucket)
      .sort((a, b) => (b.settled + b.pending) - (a.settled + a.pending));

    // 7. Flat 1u vs Quarter-Kelly Sizing Comparison & Closing Line Value (CLV)
    let flatUnitsTotal = 0;
    let kellyUnitsTotal = 0;
    let kellyTaggedCount = 0;
    let clvTotalSum = 0;
    let clvTotalCount = 0;
    let clvPositiveCount = 0;
    for (const h of graded) {
      const unitPl = roiPerUnit(getRawOutcome(h), getEffectivePrice(h));
      flatUnitsTotal += unitPl;
      const rawKelly = parseFloat(h?.kelly ?? h?.kelly_fraction);
      const stakeU =
        Number.isFinite(rawKelly) && rawKelly > 0
          ? Math.max(0.25, Math.min(2.0, rawKelly <= 1 ? rawKelly * 25 : rawKelly / 4))
          : 1.0;
      if (Number.isFinite(rawKelly) && rawKelly > 0) kellyTaggedCount += 1;
      kellyUnitsTotal += unitPl * stakeU;

      const clv = parseFloat(h?.clv_points);
      if (Number.isFinite(clv)) {
        clvTotalSum += clv;
        clvTotalCount += 1;
        if (clv > 0) clvPositiveCount += 1;
      }
    }

    return {
      gradedCount: graded.length,
      settledDays,
      recentDailyBars,
      confidenceDays: chronologicalDays.filter((d) => d.avgConf !== null),
      recentWindows,
      edgeBuckets,
      confidenceTiers,
      betTypes,
      sportBreakdown,
      latestCumulativeUnits: settledDays.length > 0 ? settledDays[settledDays.length - 1].cumulativeUnits : 0,
      stakingComparison: {
        flatUnits: Number(flatUnitsTotal.toFixed(2)),
        kellyUnits: Number(kellyUnitsTotal.toFixed(2)),
        kellyTaggedCount,
        avgClv: clvTotalCount > 0 ? clvTotalSum / clvTotalCount : null,
        clvCount: clvTotalCount,
        clvBeatRate: clvTotalCount > 0 ? (clvPositiveCount / clvTotalCount) * 100 : null,
      },
    };
  }, [history, allHistory]);

  return (
    <section className="space-y-6" aria-label="Model Performance Charts and Breakdowns">
      {/* Card 1: Performance Over Time */}
      <article className="ui-card p-5 sm:p-6 space-y-4" aria-labelledby="perf-trend-heading">
        <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-3">
          <div>
            <h3 id="perf-trend-heading" className="text-lg font-bold text-slate-100">
              Profit & Performance Over Time
            </h3>
            <p className="text-xs text-slate-400">
              {filterSummary} • Running 1-unit bankroll P/L across {analytics.settledDays.length} settled game days ({scopeLabel}).
            </p>
          </div>

          <div
            role="tablist"
            aria-label="Performance trend view"
            className="flex flex-wrap items-center gap-1 border-b border-slate-800 pb-0.5"
          >
            {[
              { id: 'cumulative', label: 'Cumulative Profit (u)' },
              { id: 'daily', label: 'Daily Profit & Win %' },
              { id: 'confidence', label: 'Daily Confidence' },
            ].map((t) => {
              const active = trendTab === t.id;
              return (
                <button
                  key={t.id}
                  id={`trend-tab-${t.id}`}
                  role="tab"
                  type="button"
                  aria-selected={active}
                  aria-controls={`trend-panel-${t.id}`}
                  onClick={() => setTrendTab(t.id)}
                  className={`px-3 py-2 text-xs font-semibold border-b-2 transition-colors cursor-pointer ${
                    active
                      ? 'border-indigo-400 text-indigo-300 bg-indigo-500/10 rounded-t-md'
                      : 'border-transparent text-slate-400 hover:text-slate-200'
                  }`}
                >
                  {t.label}
                </button>
              );
            })}
          </div>
        </div>

        {/* Cumulative Profit Curve */}
        {trendTab === 'cumulative' && (
          <div
            id="trend-panel-cumulative"
            role="tabpanel"
            aria-labelledby="trend-tab-cumulative"
            className="space-y-2"
          >
            {analytics.settledDays.length === 0 ? (
              <div className="h-[260px] flex items-center justify-center rounded-xl border border-slate-800 bg-slate-950/60 text-sm text-slate-500">
                No settled picks match the current filters.
              </div>
            ) : (
              <div className="h-[280px] w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={analytics.settledDays} margin={{ top: 10, right: 16, left: 0, bottom: 0 }}>
                    <defs>
                      <linearGradient id="cumProfitFillPos" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#10b981" stopOpacity={0.35} />
                        <stop offset="95%" stopColor="#10b981" stopOpacity={0.02} />
                      </linearGradient>
                      <linearGradient id="cumProfitFillNeg" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#f43f5e" stopOpacity={0.32} />
                        <stop offset="95%" stopColor="#f43f5e" stopOpacity={0.02} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
                    <XAxis
                      dataKey="shortDay"
                      stroke="#64748b"
                      fontSize={11}
                      tickLine={false}
                      minTickGap={26}
                    />
                    <YAxis
                      stroke="#64748b"
                      fontSize={11}
                      tickLine={false}
                      tickFormatter={(v) => `${v > 0 ? '+' : ''}${v}u`}
                      width={52}
                    />
                    <ReferenceLine y={0} stroke="#475569" strokeDasharray="4 4" label={{ value: '0u Even', fill: '#94a3b8', fontSize: 10, position: 'insideTopRight' }} />
                    <Tooltip
                      contentStyle={TOOLTIP_STYLE}
                      formatter={(value, name) => {
                        if (name === 'cumulativeUnits') return [formatUnits(value), 'Cumulative Profit'];
                        return [value, name];
                      }}
                      labelFormatter={(_, payload) => {
                        const p = payload?.[0]?.payload;
                        if (!p) return '';
                        return `${p.day} • Record ${p.recordText} • Day P/L ${formatUnits(p.profitUnits)}`;
                      }}
                    />
                    <Area
                      type="monotone"
                      dataKey="cumulativeUnits"
                      stroke={analytics.latestCumulativeUnits >= 0 ? '#10b981' : '#f43f5e'}
                      strokeWidth={2.5}
                      fill={analytics.latestCumulativeUnits >= 0 ? 'url(#cumProfitFillPos)' : 'url(#cumProfitFillNeg)'}
                      dot={analytics.settledDays.length <= 15 ? { r: 3 } : false}
                      activeDot={{ r: 5 }}
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            )}
            <p className="text-[11px] text-slate-400">
              Assumes flat 1-unit stake per graded pick using recorded odds. Above 0u means profitable; hover any date for that day&apos;s record.
            </p>
          </div>
        )}

        {/* Daily Profit Bars + Win Rate Line */}
        {trendTab === 'daily' && (
          <div
            id="trend-panel-daily"
            role="tabpanel"
            aria-labelledby="trend-tab-daily"
            className="space-y-2"
          >
            {analytics.recentDailyBars.length === 0 ? (
              <div className="h-[260px] flex items-center justify-center rounded-xl border border-slate-800 bg-slate-950/60 text-sm text-slate-500">
                No daily settled results match the current filters.
              </div>
            ) : (
              <div className="h-[280px] w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={analytics.recentDailyBars} margin={{ top: 10, right: 12, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
                    <XAxis dataKey="shortDay" stroke="#64748b" fontSize={11} tickLine={false} minTickGap={20} />
                    <YAxis
                      yAxisId="left"
                      stroke="#64748b"
                      fontSize={11}
                      tickLine={false}
                      tickFormatter={(v) => `${v > 0 ? '+' : ''}${v}u`}
                      width={48}
                    />
                    <YAxis
                      yAxisId="right"
                      orientation="right"
                      domain={[0, 100]}
                      stroke="#64748b"
                      fontSize={11}
                      tickLine={false}
                      tickFormatter={(v) => `${v}%`}
                      width={40}
                    />
                    <ReferenceLine yAxisId="left" y={0} stroke="#475569" strokeDasharray="3 3" />
                    <ReferenceLine
                      yAxisId="right"
                      y={52.4}
                      stroke="#f59e0b"
                      strokeDasharray="4 4"
                      label={{ value: '52.4% Break-Even', fill: '#f59e0b', fontSize: 10, position: 'insideTopRight' }}
                    />
                    <Tooltip
                      contentStyle={TOOLTIP_STYLE}
                      formatter={(value, name) => {
                        if (name === 'profitUnits') return [formatUnits(value), 'Day Profit'];
                        if (name === 'winRate') return [`${value}%`, 'Daily Win Rate'];
                        return [value, name];
                      }}
                      labelFormatter={(_, payload) => {
                        const p = payload?.[0]?.payload;
                        return p ? `${p.day} • ${p.recordText} (${p.settled} settled)` : '';
                      }}
                    />
                    <Bar yAxisId="left" dataKey="profitUnits" radius={[4, 4, 0, 0]} maxBarSize={24}>
                      {analytics.recentDailyBars.map((d) => (
                        <Cell key={d.day} fill={d.profitUnits >= 0 ? '#10b981' : '#f43f5e'} fillOpacity={0.85} />
                      ))}
                    </Bar>
                    <Line
                      yAxisId="right"
                      type="monotone"
                      dataKey="winRate"
                      stroke="#818cf8"
                      strokeWidth={2}
                      dot={{ r: 2.5, fill: '#818cf8' }}
                      connectNulls
                    />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            )}
            <p className="text-[11px] text-slate-400">
              Showing up to the last 45 active game days. Green/red bars show daily unit P/L; the purple line tracks daily win rate vs the dashed 52.4% break-even line.
            </p>
          </div>
        )}

        {/* Daily Confidence Trend */}
        {trendTab === 'confidence' && (
          <div
            id="trend-panel-confidence"
            role="tabpanel"
            aria-labelledby="trend-tab-confidence"
            className="space-y-2"
          >
            {analytics.confidenceDays.length === 0 ? (
              <div className="h-[260px] flex items-center justify-center rounded-xl border border-slate-800 bg-slate-950/60 text-sm text-slate-500">
                No confidence scores available for this selection.
              </div>
            ) : (
              <div className="h-[280px] w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={analytics.confidenceDays} margin={{ top: 10, right: 16, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
                    <XAxis dataKey="shortDay" stroke="#64748b" fontSize={11} tickLine={false} minTickGap={26} />
                    <YAxis domain={[0, 100]} stroke="#64748b" fontSize={11} tickLine={false} tickFormatter={(v) => `${v}%`} width={42} />
                    <ReferenceLine y={80} stroke="#10b981" strokeDasharray="4 4" label={{ value: 'High (80+)', fill: '#10b981', fontSize: 10, position: 'insideTopRight' }} />
                    <ReferenceLine y={50} stroke="#f59e0b" strokeDasharray="4 4" label={{ value: 'Medium (50+)', fill: '#f59e0b', fontSize: 10, position: 'insideTopRight' }} />
                    <Tooltip
                      contentStyle={TOOLTIP_STYLE}
                      formatter={(value) => [`${value}`, 'Avg Confidence']}
                      labelFormatter={(_, payload) => {
                        const p = payload?.[0]?.payload;
                        return p ? `${p.day} • ${p.totalPicks} picks (${p.recordText})` : '';
                      }}
                    />
                    <Line
                      type="monotone"
                      dataKey="avgConf"
                      stroke="#38bdf8"
                      strokeWidth={2.5}
                      dot={{ r: 3, fill: '#38bdf8' }}
                      activeDot={{ r: 5 }}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}
            <p className="text-[11px] text-slate-400">
              Average model conviction score (0–100) per slate day. Threshold lines mark Medium (50+) and High (80+) confidence tiers.
            </p>
          </div>
        )}
      </article>

      {/* Row 2: Edge Calibration & Confidence / Recent Form */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Card 2: Edge Calibration */}
        <article className="ui-card p-5 sm:p-6 space-y-4" aria-labelledby="edge-cal-heading">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <h3 id="edge-cal-heading" className="text-base font-bold text-slate-100">
                Win Rate & Return by Projected Edge
              </h3>
              <p className="text-xs text-slate-400">
                Tests if bigger model edges actually win more often than the 52.4% break-even line (-110 odds).
              </p>
            </div>
            <div role="tablist" aria-label="Edge view mode" className="flex items-center gap-1 border-b border-slate-800">
              {[
                { id: 'chart', label: 'Chart' },
                { id: 'table', label: 'Table' },
              ].map((t) => (
                <button
                  key={t.id}
                  id={`edge-tab-${t.id}`}
                  role="tab"
                  type="button"
                  aria-selected={edgeTab === t.id}
                  aria-controls={`edge-panel-${t.id}`}
                  onClick={() => setEdgeTab(t.id)}
                  className={`px-2.5 py-1.5 text-xs font-semibold border-b-2 transition-colors cursor-pointer ${
                    edgeTab === t.id
                      ? 'border-indigo-400 text-indigo-300'
                      : 'border-transparent text-slate-400 hover:text-slate-200'
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>
          </div>

          {edgeTab === 'chart' ? (
            <div id="edge-panel-chart" role="tabpanel" aria-labelledby="edge-tab-chart" className="h-[245px] w-full">
              {analytics.edgeBuckets.every((b) => b.settled === 0) ? (
                <div className="h-full flex items-center justify-center rounded-xl border border-slate-800 bg-slate-950/60 text-sm text-slate-500">
                  No settled picks to bucket by edge.
                </div>
              ) : (
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={analytics.edgeBuckets} margin={{ top: 10, right: 12, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
                    <XAxis dataKey="label" stroke="#64748b" fontSize={11} tickLine={false} />
                    <YAxis domain={[0, 100]} stroke="#64748b" fontSize={11} tickLine={false} tickFormatter={(v) => `${v}%`} width={40} />
                    <ReferenceLine
                      y={52.4}
                      stroke="#f59e0b"
                      strokeDasharray="4 4"
                      label={{ value: '52.4% Break-Even', fill: '#f59e0b', fontSize: 10, position: 'insideTopRight' }}
                    />
                    <Tooltip
                      contentStyle={TOOLTIP_STYLE}
                      formatter={(val, name) => {
                        if (name === 'winRate') return [`${Number(val).toFixed(1)}%`, 'Win Rate'];
                        return [val, name];
                      }}
                      labelFormatter={(_, payload) => {
                        const p = payload?.[0]?.payload;
                        if (!p) return '';
                        return `${p.label} Edge • ${p.recordText} • ${formatUnits(p.profitUnits)} (${formatSignedPct(p.roiPct)} ROI)`;
                      }}
                    />
                    <Bar dataKey="winRate" radius={[4, 4, 0, 0]} maxBarSize={38}>
                      {analytics.edgeBuckets.map((b) => (
                        <Cell
                          key={b.label}
                          fill={b.settled === 0 ? '#334155' : b.winRate >= 52.4 ? '#10b981' : b.winRate >= 48 ? '#f59e0b' : '#f43f5e'}
                        />
                      ))}
                    </Bar>
                  </ComposedChart>
                </ResponsiveContainer>
              )}
            </div>
          ) : (
            <div id="edge-panel-table" role="tabpanel" aria-labelledby="edge-tab-table" className="table-wrapper overflow-x-auto" tabIndex={0}>
              <table className="w-full text-left border-collapse text-xs">
                <thead>
                  <tr className="border-b border-slate-800 text-slate-400">
                    <th scope="col" className="py-2 pr-3 font-medium">Projected Edge</th>
                    <th scope="col" className="py-2 px-3 font-medium text-right">Settled</th>
                    <th scope="col" className="py-2 px-3 font-medium">Record</th>
                    <th scope="col" className="py-2 px-3 font-medium text-right">Win %</th>
                    <th scope="col" className="py-2 px-3 font-medium text-right">Units</th>
                    <th scope="col" className="py-2 pl-3 font-medium text-right">ROI</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/70">
                  {analytics.edgeBuckets.map((b) => (
                    <tr key={b.label} className="hover:bg-slate-900/50">
                      <td className="py-2 pr-3 font-medium text-slate-200">{b.label}</td>
                      <td className="py-2 px-3 text-right text-slate-400">{b.settled}</td>
                      <td className="py-2 px-3 font-mono text-slate-300">{b.recordText}</td>
                      <td className={`py-2 px-3 text-right font-mono font-semibold ${b.winRate >= 52.4 ? 'text-emerald-400' : 'text-slate-300'}`}>
                        {b.decided > 0 ? formatPct(b.winRate) : '—'}
                      </td>
                      <td className={`py-2 px-3 text-right font-mono font-semibold ${b.profitUnits >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                        {formatUnits(b.profitUnits)}
                      </td>
                      <td className={`py-2 pl-3 text-right font-mono font-semibold ${b.roiPct >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                        {b.settled > 0 ? formatSignedPct(b.roiPct) : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </article>

        {/* Card 3: Confidence Tiers & Recent Form */}
        <article className="ui-card p-5 sm:p-6 space-y-4" aria-labelledby="conf-form-heading">
          <div>
            <h3 id="conf-form-heading" className="text-base font-bold text-slate-100">
              Confidence Tiers & Recent Form
            </h3>
            <p className="text-xs text-slate-400">
              Every recommended pick (&ge; +2% EV) is tracked here across High, Medium, and Low conviction.
            </p>
          </div>

          <div className="grid grid-cols-3 gap-2.5">
            {analytics.confidenceTiers.map((t) => {
              const badgeColor =
                t.label === 'High'
                  ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
                  : t.label === 'Medium'
                    ? 'border-amber-500/30 bg-amber-500/10 text-amber-300'
                    : 'border-slate-700 bg-slate-900/80 text-slate-300';
              return (
                <div key={t.label} className={`rounded-xl border p-3 ${badgeColor}`}>
                  <div className="flex items-center justify-between gap-1">
                    <span className="text-xs font-bold">{t.label}</span>
                    <span className="text-[10px] opacity-80">{t.desc}</span>
                  </div>
                  <div className="mt-1.5 text-lg font-extrabold font-mono text-slate-100">
                    {t.decided > 0 ? formatPct(t.winRate) : '—'}
                  </div>
                  <div className="mt-0.5 text-[11px] font-mono text-slate-300">{t.recordText}</div>
                  <div className={`mt-1 text-[11px] font-mono font-semibold ${t.roiPct >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {formatUnits(t.profitUnits)} ({t.settled > 0 ? formatSignedPct(t.roiPct) : '—'})
                  </div>
                </div>
              );
            })}
          </div>

          <div className="space-y-2">
            <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400">Recent Form Windows</h4>
            <div className="table-wrapper overflow-x-auto" tabIndex={0}>
              <table className="w-full text-left border-collapse text-xs">
                <thead>
                  <tr className="border-b border-slate-800 text-slate-400">
                    <th scope="col" className="py-1.5 pr-3 font-medium">Window</th>
                    <th scope="col" className="py-1.5 px-3 font-medium">Record</th>
                    <th scope="col" className="py-1.5 px-3 font-medium text-right">Win %</th>
                    <th scope="col" className="py-1.5 px-3 font-medium text-right">Units</th>
                    <th scope="col" className="py-1.5 pl-3 font-medium text-right">ROI</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/70">
                  {analytics.recentWindows.map((w) => (
                    <tr key={w.label} className="hover:bg-slate-900/50">
                      <td className="py-1.5 pr-3 font-medium text-slate-200">{w.label}</td>
                      <td className="py-1.5 px-3 font-mono text-slate-300">{w.recordText}</td>
                      <td className={`py-1.5 px-3 text-right font-mono font-semibold ${w.winRate >= 52.4 ? 'text-emerald-400' : 'text-slate-300'}`}>
                        {w.decided > 0 ? formatPct(w.winRate) : '—'}
                      </td>
                      <td className={`py-1.5 px-3 text-right font-mono font-semibold ${w.profitUnits >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                        {w.settled > 0 ? formatUnits(w.profitUnits) : '—'}
                      </td>
                      <td className={`py-1.5 pl-3 text-right font-mono font-semibold ${w.roiPct >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                        {w.settled > 0 ? formatSignedPct(w.roiPct) : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </article>
      </div>

      {/* Staking & CLV Summary Strip */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <article className="ui-card p-4 space-y-1">
          <h3 className="text-[11px] font-bold uppercase tracking-wider text-slate-400">Flat 1-Unit Profit</h3>
          <div className={`text-xl font-mono font-bold ${analytics.stakingComparison.flatUnits >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
            {formatUnits(analytics.stakingComparison.flatUnits)}
          </div>
          <p className="text-[11px] text-slate-400">Uniform 1 unit risked per settled play</p>
        </article>

        <article className="ui-card p-4 space-y-1">
          <h3 className="text-[11px] font-bold uppercase tracking-wider text-slate-400">Confidence-Adjusted Sizing</h3>
          <div className={`text-xl font-mono font-bold ${analytics.stakingComparison.kellyUnits >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
            {formatUnits(analytics.stakingComparison.kellyUnits)}
          </div>
          <p className="text-[11px] text-slate-400">
            Scales bet size by confidence &amp; edge ({analytics.stakingComparison.kellyTaggedCount} sized plays)
          </p>
        </article>

        <article className="ui-card p-4 space-y-1">
          <h3 className="text-[11px] font-bold uppercase tracking-wider text-slate-400">Beating the Closing Line (CLV)</h3>
          <div
            className={`text-xl font-mono font-bold ${
              analytics.stakingComparison.avgClv === null
                ? 'text-slate-400'
                : analytics.stakingComparison.avgClv >= 0
                  ? 'text-emerald-400'
                  : 'text-rose-400'
            }`}
          >
            {analytics.stakingComparison.avgClv !== null
              ? `${analytics.stakingComparison.avgClv > 0 ? '+' : ''}${analytics.stakingComparison.avgClv.toFixed(2)}`
              : '—'}
          </div>
          <p className="text-[11px] text-slate-400">
            {analytics.stakingComparison.clvCount > 0
              ? `Beat close ${formatPct(analytics.stakingComparison.clvBeatRate)} across ${analytics.stakingComparison.clvCount} graded picks`
              : 'No closing snapshot comparison recorded yet'}
          </p>
        </article>
      </div>

      {/* Row 3: Bet Type Chart + By Sport Comparison */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Card 4: Bet Type Performance */}
        <article className="ui-card p-5 sm:p-6 space-y-4" aria-labelledby="bet-type-heading">
          <div>
            <h3 id="bet-type-heading" className="text-base font-bold text-slate-100">
              Performance by Bet Type
            </h3>
            <p className="text-xs text-slate-400">
              Compares return on bets (%) across Spreads, Totals (Over/Under), Moneylines, and Parlays.
            </p>
          </div>

          {analytics.betTypes.length === 0 ? (
            <div className="h-[200px] flex items-center justify-center rounded-xl border border-slate-800 bg-slate-950/60 text-sm text-slate-500">
              No settled picks in this view.
            </div>
          ) : (
            <>
              <div className="h-[190px] w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart
                    data={analytics.betTypes.map((b) => ({ ...b, roiRounded: Number(b.roiPct.toFixed(1)) }))}
                    layout="vertical"
                    margin={{ top: 4, right: 20, left: 8, bottom: 4 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" horizontal={false} />
                    <XAxis type="number" stroke="#64748b" fontSize={11} tickLine={false} tickFormatter={(v) => `${v > 0 ? '+' : ''}${v}%`} />
                    <YAxis type="category" dataKey="label" stroke="#cbd5e1" fontSize={11} tickLine={false} width={88} />
                    <ReferenceLine x={0} stroke="#475569" strokeDasharray="3 3" />
                    <Tooltip
                      contentStyle={TOOLTIP_STYLE}
                      formatter={(val) => [formatSignedPct(val), 'ROI']}
                      labelFormatter={(_, payload) => {
                        const p = payload?.[0]?.payload;
                        return p ? `${p.label} • ${p.recordText} • ${formatPct(p.winRate)} Win (${formatUnits(p.profitUnits)})` : '';
                      }}
                    />
                    <Bar dataKey="roiRounded" radius={[0, 4, 4, 0]} maxBarSize={24}>
                      {analytics.betTypes.map((b) => (
                        <Cell key={b.label} fill={b.roiPct >= 0 ? '#10b981' : '#f43f5e'} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>

              <div className="table-wrapper overflow-x-auto" tabIndex={0}>
                <table className="w-full text-left border-collapse text-xs">
                  <thead>
                    <tr className="border-b border-slate-800 text-slate-400">
                      <th scope="col" className="py-1.5 pr-3 font-medium">Market</th>
                      <th scope="col" className="py-1.5 px-3 font-medium">Record</th>
                      <th scope="col" className="py-1.5 px-3 font-medium text-right">Win %</th>
                      <th scope="col" className="py-1.5 px-3 font-medium text-right">Units</th>
                      <th scope="col" className="py-1.5 px-3 font-medium text-right">ROI</th>
                      <th scope="col" className="py-1.5 pl-3 font-medium text-right">Avg CLV</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/70">
                    {analytics.betTypes.map((m) => (
                      <tr key={m.label} className="hover:bg-slate-900/50">
                        <td className="py-1.5 pr-3 font-semibold text-slate-200">{m.label}</td>
                        <td className="py-1.5 px-3 font-mono text-slate-300">{m.recordText}</td>
                        <td className={`py-1.5 px-3 text-right font-mono ${m.winRate >= 52.4 ? 'text-emerald-400 font-semibold' : 'text-slate-300'}`}>
                          {formatPct(m.winRate)}
                        </td>
                        <td className={`py-1.5 px-3 text-right font-mono font-semibold ${m.profitUnits >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                          {formatUnits(m.profitUnits)}
                        </td>
                        <td className={`py-1.5 px-3 text-right font-mono font-semibold ${m.roiPct >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                          {formatSignedPct(m.roiPct)}
                        </td>
                        <td className={`py-1.5 pl-3 text-right font-mono font-semibold ${m.avgClv === null ? 'text-slate-500' : m.avgClv >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                          {m.avgClv !== null ? `${m.avgClv > 0 ? '+' : ''}${m.avgClv.toFixed(2)}` : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </article>

        {/* Card 5: Performance by Sport (Click to Filter) */}
        <article className="ui-card p-5 sm:p-6 space-y-4" aria-labelledby="by-sport-heading">
          <div className="flex items-start justify-between gap-2">
            <div>
              <h3 id="by-sport-heading" className="text-base font-bold text-slate-100">
                Performance by Sport
              </h3>
              <p className="text-xs text-slate-400">
                Click any sport row to focus all charts and pick history on that sport.
              </p>
            </div>
            {selectedSport !== 'ALL' && onSelectSport && (
              <button
                type="button"
                onClick={() => onSelectSport('ALL')}
                className="text-xs font-semibold text-indigo-300 hover:text-indigo-200 underline cursor-pointer"
              >
                Show All Sports
              </button>
            )}
          </div>

          {analytics.sportBreakdown.length === 0 ? (
            <div className="h-[200px] flex items-center justify-center rounded-xl border border-slate-800 bg-slate-950/60 text-sm text-slate-500">
              No sport history found.
            </div>
          ) : (
            <div className="space-y-2.5">
              {analytics.sportBreakdown.map((s) => {
                const isSelected = selectedSport === s.sport;
                return (
                  <button
                    key={s.sport}
                    type="button"
                    aria-pressed={isSelected}
                    onClick={() => onSelectSport && onSelectSport(isSelected ? 'ALL' : s.sport)}
                    className={`w-full text-left rounded-xl border p-3.5 transition-all cursor-pointer ${
                      isSelected
                        ? 'border-indigo-400 bg-indigo-500/15 ring-1 ring-indigo-400/50'
                        : 'border-slate-800 bg-slate-950/60 hover:border-slate-700 hover:bg-slate-900/70'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="flex items-center gap-2.5">
                        <span className="px-2.5 py-1 rounded-lg text-xs font-extrabold tracking-wide bg-slate-800 text-slate-100">
                          {s.sport}
                        </span>
                        <div>
                          <div className="text-sm font-mono font-semibold text-slate-100">{s.recordText}</div>
                          <div className="text-[11px] text-slate-400">
                            {s.settled} settled{s.voids > 0 ? ` • ${s.voids} void` : ''}{s.pending > 0 ? ` • ${s.pending} pending` : ''}
                          </div>
                        </div>
                      </div>

                      <div className="text-right">
                        <div className={`text-sm font-mono font-bold ${s.roiPct >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                          {formatUnits(s.profitUnits)} ({s.settled > 0 ? formatSignedPct(s.roiPct) : '—'})
                        </div>
                        <div className="text-xs font-mono text-slate-300">
                          {s.decided > 0 ? `${formatPct(s.winRate)} Win Rate` : 'Awaiting settlement'}
                        </div>
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </article>
      </div>
    </section>
  );
};

export default ModelPerformanceAnalytics;
