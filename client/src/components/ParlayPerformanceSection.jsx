import React, { useMemo, useState } from 'react';
import { Layers, Target, TrendingUp, Gauge, CheckCircle2 } from 'lucide-react';
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
} from 'recharts';
import {
  formatAmericanOdds,
  formatMarketLabel,
  normalizeOutcome,
} from '../utils/modelPerformance';
import { getOutcomeOutlineClasses } from './today/todayHelpers';

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

const formatPct = (p, digits = 1) => `${Number(p || 0).toFixed(digits)}%`;

const formatSignedPct = (p, digits = 1) => {
  const val = Number(p || 0);
  if (Math.abs(val) < 0.05) return '0.0%';
  return `${val > 0 ? '+' : ''}${val.toFixed(digits)}%`;
};

const renderParlaySparkline = (points, isPositive) => {
  if (!Array.isArray(points) || points.length < 2) return null;
  const w = 132;
  const h = 34;
  const min = Math.min(0, ...points);
  const max = Math.max(0, ...points);
  const span = Math.max(0.01, max - min);
  const coords = points.map((v, idx) => {
    const x = (idx / (points.length - 1)) * w;
    const y = h - 3 - ((v - min) / span) * (h - 6);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const zeroY = h - 3 - ((0 - min) / span) * (h - 6);
  const stroke = isPositive ? '#10b981' : '#f43f5e';
  const gradId = isPositive ? 'parlaySparkPos' : 'parlaySparkNeg';
  const areaPoints = `0,${h} ${coords.join(' ')} ${w},${h}`;

  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="w-28 h-8 shrink-0 overflow-visible" aria-hidden="true">
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={stroke} stopOpacity="0.32" />
          <stop offset="100%" stopColor={stroke} stopOpacity="0.0" />
        </linearGradient>
      </defs>
      <line
        x1="0"
        y1={zeroY.toFixed(1)}
        x2={w}
        y2={zeroY.toFixed(1)}
        stroke="#475569"
        strokeDasharray="2 2"
        strokeWidth="1"
      />
      <polygon points={areaPoints} fill={`url(#${gradId})`} />
      <polyline
        fill="none"
        stroke={stroke}
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        points={coords.join(' ')}
      />
    </svg>
  );
};

export default function ParlayPerformanceSection({
  parlayAnalytics = null,
  selectedSport = 'NCAAM',
  onSwitchToNcaam = null,
  filterSummary = 'All Time',
}) {
  const [outcomeFilter, setOutcomeFilter] = useState('ALL');

  const stats = parlayAnalytics || {
    items: [],
    wins: 0,
    losses: 0,
    pushes: 0,
    voids: 0,
    pending: 0,
    decided: 0,
    settled: 0,
    recordText: '0-0',
    winRate: 0,
    profitUnits: 0,
    roiPct: 0,
    avgOdds: null,
    breakEvenWinPct: null,
    avgModelWinPct: null,
    avgProjectedEvPct: null,
    legWins: 0,
    legLosses: 0,
    legPushes: 0,
    legPending: 0,
    legDecided: 0,
    legRecordText: '0-0',
    legWinRate: 0,
    legMarkets: [],
    buckets: [],
    oddsBands: [],
    equityCurve: [],
    sparkPoints: [],
  };

  const filteredItems = useMemo(() => {
    return (stats.items || []).filter((item) => {
      const outKey = String(item?.outcome || 'PENDING').toUpperCase();
      const norm = outKey === 'WON (PARTIAL)' ? 'WON' : normalizeOutcome(outKey);
      if (outcomeFilter === 'SETTLED') return norm === 'WON' || norm === 'LOST' || norm === 'PUSH';
      if (outcomeFilter === 'WON') return norm === 'WON';
      if (outcomeFilter === 'LOST') return norm === 'LOST';
      if (outcomeFilter === 'PENDING') return norm === null;
      return true;
    });
  }, [stats.items, outcomeFilter]);

  if (selectedSport !== 'NCAAM' && selectedSport !== 'ALL') {
    return (
      <div className="perf-chart-card p-6 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="space-y-1">
          <h3 className="text-base font-bold text-slate-100">
            Official Daily Parlays are tracked for NCAAM
          </h3>
          <p className="text-xs text-slate-400">
            You currently have <strong className="text-slate-200">{selectedSport}</strong> selected above. Switch to NCAAM or All Sports to review Official Daily Parlay KPIs, strategy splits, and leg results.
          </p>
        </div>
        {onSwitchToNcaam && (
          <button
            type="button"
            onClick={onSwitchToNcaam}
            className="px-4 py-2 rounded-xl border border-indigo-400/45 bg-indigo-500/20 hover:bg-indigo-500/30 text-indigo-100 text-xs font-semibold cursor-pointer shrink-0 transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-400"
          >
            View NCAAM Parlays
          </button>
        )}
      </div>
    );
  }

  const breakEvenPct = stats.breakEvenWinPct ?? 33.3;
  const calDiffPct =
    stats.decided > 0 && stats.avgModelWinPct !== null
      ? Number((stats.winRate - stats.avgModelWinPct).toFixed(1))
      : null;

  return (
    <div className="space-y-6">
      {/* Row 1: 4 Parlay KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        {/* KPI 1: Parlay Net Profit & ROI */}
        <article className="perf-kpi-card p-5 flex flex-col justify-between gap-3">
          <div className="flex items-start justify-between gap-3">
            <div className="space-y-1 min-w-0">
              <div className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wider text-slate-400">
                <TrendingUp className="w-3.5 h-3.5 text-emerald-400" aria-hidden="true" />
                <span>Parlay Net Profit</span>
              </div>
              <div
                className={`perf-kpi-value font-extrabold font-mono ${
                  stats.settled === 0
                    ? 'text-slate-200'
                    : stats.profitUnits >= 0
                      ? 'text-emerald-400'
                      : 'text-rose-400'
                }`}
              >
                {stats.settled > 0 ? formatUnits(stats.profitUnits) : '0.00u'}
              </div>
              <div className="text-xs text-slate-400">
                {stats.settled > 0 ? (
                  <span className="inline-flex items-center gap-1.5">
                    <span
                      className={`font-mono font-semibold ${
                        stats.roiPct >= 0 ? 'text-emerald-300' : 'text-rose-300'
                      }`}
                    >
                      {formatSignedPct(stats.roiPct)} ROI
                    </span>
                    <span className="text-slate-600">·</span>
                    <span>1u flat</span>
                  </span>
                ) : (
                  'Waiting on settled parlays'
                )}
              </div>
            </div>
            {renderParlaySparkline(stats.sparkPoints, stats.profitUnits >= 0)}
          </div>
          <div className="text-[11px] text-slate-400 pt-1 border-t border-slate-800/70">
            Official 2-leg parlays lock 10m pre-tip
          </div>
        </article>

        {/* KPI 2: Parlay Record & Win % vs Dynamic Break-Even */}
        <article className="perf-kpi-card p-5 flex flex-col justify-between gap-3">
          <div className="flex items-start justify-between gap-2">
            <div className="space-y-1">
              <div className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wider text-slate-400">
                <Target className="w-3.5 h-3.5 text-indigo-400" aria-hidden="true" />
                <span>Parlay Record &amp; Win %</span>
              </div>
              <div className="flex items-baseline gap-2.5">
                <span
                  className={`perf-kpi-value font-extrabold font-mono ${
                    stats.decided === 0
                      ? 'text-slate-300'
                      : stats.winRate >= breakEvenPct
                        ? 'text-emerald-400'
                        : 'text-rose-400'
                  }`}
                >
                  {stats.decided > 0 ? `${stats.winRate.toFixed(1)}%` : '—'}
                </span>
                <span className="text-sm font-mono font-bold text-slate-200">
                  {stats.recordText}
                </span>
              </div>
              <div className="text-xs text-slate-400">
                {stats.breakEvenWinPct !== null
                  ? `Break-even at avg odds is ${breakEvenPct.toFixed(1)}%`
                  : 'Plus-money break-even sits near 33%'}
              </div>
            </div>
            {stats.pending > 0 && (
              <span className="px-2 py-0.5 rounded-full border border-slate-700 bg-slate-900 text-[10px] font-mono text-slate-300 shrink-0">
                {stats.pending} open
              </span>
            )}
          </div>
          <div className="space-y-1">
            <div className="relative h-2.5 w-full rounded-full bg-slate-800/90 overflow-hidden" aria-hidden="true">
              <div
                className={`h-full rounded-full transition-all ${
                  stats.decided === 0
                    ? 'bg-slate-600'
                    : stats.winRate >= breakEvenPct
                      ? 'bg-gradient-to-r from-indigo-500 to-emerald-400'
                      : 'bg-gradient-to-r from-rose-500 to-amber-500'
                }`}
                style={{ width: `${stats.decided > 0 ? Math.max(0, Math.min(100, stats.winRate)) : 0}%` }}
              />
              <div
                className="absolute top-0 bottom-0 w-0.5 bg-amber-300 shadow-[0_0_6px_rgba(251,191,36,0.9)]"
                style={{ left: `${Math.max(5, Math.min(95, breakEvenPct))}%` }}
              />
            </div>
            <div className="flex items-center justify-between text-[10px] text-slate-500 font-mono">
              <span>0%</span>
              <span className="text-amber-300/90">{breakEvenPct.toFixed(1)}% Break-Even</span>
              <span>100%</span>
            </div>
          </div>
        </article>

        {/* KPI 3: Individual Leg Hit Rate */}
        <article className="perf-kpi-card p-5 flex flex-col justify-between gap-3">
          <div className="flex items-start justify-between gap-2">
            <div className="space-y-1">
              <div className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wider text-slate-400">
                <CheckCircle2 className="w-3.5 h-3.5 text-sky-400" aria-hidden="true" />
                <span>Individual Leg Hit Rate</span>
              </div>
              <div className="flex items-baseline gap-2.5">
                <span
                  className={`perf-kpi-value font-extrabold font-mono ${
                    stats.legDecided === 0
                      ? 'text-slate-300'
                      : stats.legWinRate >= 55
                        ? 'text-emerald-400'
                        : 'text-sky-300'
                  }`}
                >
                  {stats.legDecided > 0 ? `${stats.legWinRate.toFixed(1)}%` : '—'}
                </span>
                <span className="text-sm font-mono font-bold text-slate-200">
                  {stats.legRecordText}
                </span>
              </div>
              <div className="text-xs text-slate-400">
                {stats.avgOdds !== null
                  ? `Avg Parlay Odds: ${formatAmericanOdds(stats.avgOdds)}`
                  : 'Across Spread, Total & ML legs'}
              </div>
            </div>
            {stats.legPending > 0 && (
              <span className="px-2 py-0.5 rounded-full border border-slate-700 bg-slate-900 text-[10px] font-mono text-slate-300 shrink-0">
                {stats.legPending} open
              </span>
            )}
          </div>
          <div className="space-y-1">
            <div className="h-2.5 w-full rounded-full bg-slate-800/90 overflow-hidden" aria-hidden="true">
              <div
                className="h-full rounded-full bg-gradient-to-r from-sky-500 to-emerald-400 transition-all"
                style={{ width: `${stats.legDecided > 0 ? Math.max(0, Math.min(100, stats.legWinRate)) : 0}%` }}
              />
            </div>
            <div className="flex items-center justify-between text-[10px] text-slate-500 font-mono">
              <span>{stats.legDecided} decided legs</span>
              <span>{stats.legPushes > 0 ? `${stats.legPushes} push` : 'Leg Accuracy'}</span>
            </div>
          </div>
        </article>

        {/* KPI 4: Parlay Calibration (Model Expected vs Actual) */}
        <article className="perf-kpi-card p-5 flex flex-col justify-between gap-3">
          <div className="space-y-1">
            <div className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wider text-slate-400">
              <Gauge className="w-3.5 h-3.5 text-purple-400" aria-hidden="true" />
              <span>Model vs. Actual Win %</span>
            </div>
            <div className="flex items-baseline gap-2">
              <span className="perf-kpi-value font-extrabold font-mono text-indigo-300">
                {stats.avgModelWinPct !== null ? `${stats.avgModelWinPct.toFixed(1)}%` : '—'}
              </span>
              <span className="text-xs text-slate-400">Expected</span>
            </div>
            <div className="text-xs text-slate-400">
              {calDiffPct !== null
                ? `Actual ${stats.winRate.toFixed(1)}% (${calDiffPct >= 0 ? '+' : ''}${calDiffPct.toFixed(1)}% vs model)`
                : 'Compares predicted P(hit) vs settled'}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-1.5 text-[11px] font-mono pt-1">
            <div className="rounded-lg border border-slate-800 bg-slate-950/75 px-2.5 py-1 flex items-center justify-between">
              <span className="font-sans text-[10px] text-slate-400">Avg EV</span>
              <span className="font-bold text-emerald-300">
                {stats.avgProjectedEvPct !== null ? formatSignedPct(stats.avgProjectedEvPct) : '—'}
              </span>
            </div>
            <div className="rounded-lg border border-slate-800 bg-slate-950/75 px-2.5 py-1 flex items-center justify-between">
              <span className="font-sans text-[10px] text-slate-400">Avg Price</span>
              <span className="font-bold text-indigo-200">
                {stats.avgOdds !== null ? formatAmericanOdds(stats.avgOdds) : '—'}
              </span>
            </div>
          </div>
        </article>
      </div>

      {/* Row 2: Parlay Equity Curve + Parlay Strategy & Leg Insights */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Left: Parlay Cumulative Profit Curve */}
        <article className="perf-chart-card p-5 sm:p-6 space-y-4" aria-labelledby="parlay-equity-heading">
          <div className="flex items-start justify-between gap-2">
            <div>
              <h3 id="parlay-equity-heading" className="text-base font-bold text-slate-100">
                Parlay Equity Curve
              </h3>
              <p className="text-xs text-slate-400">
                Running 1-unit profit across {stats.equityCurve.length} settled parlay day{stats.equityCurve.length === 1 ? '' : 's'} ({filterSummary}).
              </p>
            </div>
            <span className="px-2.5 py-0.5 rounded-full border border-slate-700 bg-slate-950 text-[11px] font-mono text-slate-300 shrink-0">
              {stats.settled} settled
            </span>
          </div>

          {stats.equityCurve.length === 0 ? (
            <div className="h-[240px] flex items-center justify-center rounded-xl border border-slate-800 bg-slate-950/60 px-4 text-center text-xs text-slate-400">
              No settled Official Daily Parlays yet in this filter. Once locked parlays finish grading, the running unit curve will plot here.
            </div>
          ) : (
            <div className="h-[240px] w-full">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={stats.equityCurve} margin={{ top: 10, right: 16, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="parlayCumPos" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#10b981" stopOpacity={0.35} />
                      <stop offset="95%" stopColor="#10b981" stopOpacity={0.02} />
                    </linearGradient>
                    <linearGradient id="parlayCumNeg" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#f43f5e" stopOpacity={0.32} />
                      <stop offset="95%" stopColor="#f43f5e" stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
                  <XAxis dataKey="shortDay" stroke="#64748b" fontSize={11} tickLine={false} minTickGap={22} />
                  <YAxis
                    stroke="#64748b"
                    fontSize={11}
                    tickLine={false}
                    tickFormatter={(v) => `${v > 0 ? '+' : ''}${v}u`}
                    width={48}
                  />
                  <ReferenceLine
                    y={0}
                    stroke="#475569"
                    strokeDasharray="4 4"
                    label={{ value: '0u Even', fill: '#94a3b8', fontSize: 10, position: 'insideTopRight' }}
                  />
                  <Tooltip
                    contentStyle={TOOLTIP_STYLE}
                    formatter={(val) => [formatUnits(val), 'Parlay Total']}
                    labelFormatter={(_, payload) => {
                      const p = payload?.[0]?.payload;
                      return p ? `${p.day} • ${p.recordText} • Day ${formatUnits(p.dayUnits)}` : '';
                    }}
                  />
                  <Area
                    type="monotone"
                    dataKey="cumulativeUnits"
                    stroke={stats.profitUnits >= 0 ? '#10b981' : '#f43f5e'}
                    strokeWidth={2.5}
                    fill={stats.profitUnits >= 0 ? 'url(#parlayCumPos)' : 'url(#parlayCumNeg)'}
                    dot={stats.equityCurve.length <= 15 ? { r: 3.5 } : false}
                    activeDot={{ r: 5 }}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}
        </article>

        {/* Right: Parlay Strategy & Leg Insights */}
        <article className="perf-chart-card p-5 sm:p-6 space-y-4" aria-labelledby="parlay-insights-heading">
          <div className="flex items-start justify-between gap-2">
            <div>
              <h3 id="parlay-insights-heading" className="text-base font-bold text-slate-100">
                Parlay Strategy &amp; Leg Insights
              </h3>
              <p className="text-xs text-slate-400">
                Hit rate and ROI split by parlay strategy tier, price band, and individual leg market.
              </p>
            </div>
            <Layers className="w-4 h-4 text-indigo-400 shrink-0 mt-0.5" aria-hidden="true" />
          </div>

          <div className="space-y-4 text-xs">
            {/* Strategy Bucket */}
            <div className="space-y-2">
              <div className="text-[11px] font-bold uppercase tracking-wider text-slate-400">
                By Strategy Bucket
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                {stats.buckets.map((b) => (
                  <div
                    key={b.key}
                    className="rounded-xl border border-slate-800 bg-slate-950/60 p-3 space-y-1"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-semibold text-slate-100">{b.label}</span>
                      <span className="font-mono text-slate-300">{b.recordText}</span>
                    </div>
                    <div className="flex items-center justify-between text-[11px] font-mono">
                      <span className="text-slate-400">
                        Win %:{' '}
                        <strong className="text-slate-200">
                          {b.decided > 0 ? formatPct(b.winRate) : '—'}
                        </strong>
                      </span>
                      <span
                        className={`font-semibold ${
                          b.settled === 0
                            ? 'text-slate-500'
                            : b.profitUnits >= 0
                              ? 'text-emerald-400'
                              : 'text-rose-400'
                        }`}
                      >
                        {b.settled > 0 ? `${formatUnits(b.profitUnits)} (${formatSignedPct(b.roiPct)})` : 'No settled'}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Combined Odds Bands */}
            <div className="space-y-2">
              <div className="text-[11px] font-bold uppercase tracking-wider text-slate-400">
                By Combined Odds Band
              </div>
              <div className="grid grid-cols-3 gap-2">
                {stats.oddsBands.map((band) => (
                  <div
                    key={band.key}
                    className="rounded-xl border border-slate-800 bg-slate-950/60 p-2.5 text-center space-y-0.5"
                  >
                    <div className="text-[11px] font-bold text-indigo-300">{band.label}</div>
                    <div className="text-xs font-mono font-semibold text-slate-200">{band.recordText}</div>
                    <div
                      className={`text-[11px] font-mono font-semibold ${
                        band.settled === 0
                          ? 'text-slate-500'
                          : band.profitUnits >= 0
                            ? 'text-emerald-400'
                            : 'text-rose-400'
                      }`}
                    >
                      {band.settled > 0 ? `${formatUnits(band.profitUnits)}` : band.pending > 0 ? `${band.pending} open` : '—'}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Individual Leg Market Hit Rates & Calibration */}
            <div className="space-y-2">
              <div className="text-[11px] font-bold uppercase tracking-wider text-slate-400">
                Leg Hit Rate &amp; Calibration by Market
              </div>
              {stats.legMarkets.length === 0 ? (
                <div className="rounded-xl border border-slate-800/80 bg-slate-950/50 px-3 py-2 text-slate-500">
                  No parlay legs recorded in this filter yet.
                </div>
              ) : (
                <div className="space-y-2">
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                    {stats.legMarkets.map((lm) => (
                      <div
                        key={lm.marketKey}
                        className="rounded-xl border border-slate-800 bg-slate-950/65 px-3 py-2 flex flex-col gap-1 text-[11px]"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-semibold text-slate-200">{lm.label}</span>
                          <div className="flex items-center gap-1.5 font-mono">
                            <span className="text-slate-300">{lm.recordText}</span>
                            <span
                              className={`font-bold ${
                                lm.decided === 0
                                  ? 'text-sky-300'
                                  : lm.winRate >= 55
                                    ? 'text-emerald-400'
                                    : 'text-slate-200'
                              }`}
                            >
                              {lm.decided > 0 ? formatPct(lm.winRate) : `${lm.pending} open`}
                            </span>
                          </div>
                        </div>
                        {(lm.avgExpectedWinPct !== null || lm.avgImpliedWinPct !== null) && (
                          <div className="flex flex-wrap items-center justify-between gap-2 text-[10px] font-mono text-slate-400">
                            <span>
                              {lm.avgExpectedWinPct !== null ? `Exp ${formatPct(lm.avgExpectedWinPct)}` : ''}
                              {lm.avgExpectedWinPct !== null && lm.avgImpliedWinPct !== null ? ' · ' : ''}
                              {lm.avgImpliedWinPct !== null ? `Imp ${formatPct(lm.avgImpliedWinPct)}` : ''}
                            </span>
                            {lm.calibrationGapPct !== null && (
                              <span
                                className={`font-bold ${
                                  lm.calibrationGapPct >= 0 ? 'text-emerald-400' : 'text-rose-400'
                                }`}
                              >
                                {formatSignedPct(lm.calibrationGapPct)} vs model
                              </span>
                            )}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                  {stats.mlVsSpreadAudit?.summaryText && (
                    <div
                      className={`rounded-lg border px-2.5 py-1.5 text-[11px] font-mono ${
                        stats.mlVsSpreadAudit.overconfidentWarning
                          ? 'border-amber-500/35 bg-amber-950/20 text-amber-200'
                          : 'border-slate-800/80 bg-slate-950/50 text-slate-300'
                      }`}
                    >
                      {stats.mlVsSpreadAudit.summaryText}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </article>
      </div>

      {/* Row 3: Official Daily Parlay History & Leg Results Table */}
      <article className="perf-chart-card p-5 sm:p-6 space-y-4" aria-labelledby="parlay-history-heading">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div>
            <h3 id="parlay-history-heading" className="text-base font-bold text-slate-100">
              Official Daily Parlay History &amp; Leg Results
            </h3>
            <p className="text-xs text-slate-400">
              Showing {filteredItems.length} of {(stats.items || []).length} tracked official parlays ({filterSummary}).
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Filter parlays by outcome">
            {[
              { key: 'ALL', label: 'All' },
              { key: 'SETTLED', label: 'Finished' },
              { key: 'WON', label: 'Won' },
              { key: 'LOST', label: 'Lost' },
              { key: 'PENDING', label: 'Open' },
            ].map((pill) => {
              const active = outcomeFilter === pill.key;
              return (
                <button
                  key={pill.key}
                  type="button"
                  aria-pressed={active}
                  onClick={() => setOutcomeFilter(pill.key)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-semibold border focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-400 transition-colors cursor-pointer ${
                    active
                      ? 'border-indigo-400 bg-indigo-500/20 text-indigo-200'
                      : 'border-slate-800 bg-slate-950/60 text-slate-400 hover:text-slate-200 hover:border-slate-700'
                  }`}
                >
                  {pill.label}
                </button>
              );
            })}
          </div>
        </div>

        {filteredItems.length === 0 ? (
          <div className="rounded-xl border border-slate-800/80 bg-slate-950/50 px-4 py-5 text-xs text-slate-400">
            No Official Daily Parlays match the active filters. Once an official parlay reaches its 10-minute pre-tip lock window, its legs, odds, and graded ROI appear here automatically.
          </div>
        ) : (
          <div
            role="region"
            aria-labelledby="parlay-history-heading"
            tabIndex={0}
            className="perf-table-wrapper max-h-[420px] rounded-xl border border-slate-800/80"
          >
            <table className="perf-sticky-table w-full text-left border-collapse text-xs">
              <caption className="sr-only">Official Daily Parlay results and leg breakdown</caption>
              <thead>
                <tr className="border-b border-slate-800 text-slate-400">
                  <th scope="col" className="py-2 px-3 font-medium">Date</th>
                  <th scope="col" className="py-2 px-3 font-medium">Legs &amp; Scores</th>
                  <th scope="col" className="py-2 px-3 font-medium text-right">Odds</th>
                  <th scope="col" className="py-2 px-3 font-medium">Result</th>
                  <th scope="col" className="py-2 px-3 font-medium text-right">Profit</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/70">
                {filteredItems.slice(0, 50).map((item, idx) => {
                  const outKey = String(item.outcome || 'PENDING').toUpperCase();
                  const normKey = outKey === 'WON (PARTIAL)' ? 'WON' : (normalizeOutcome(outKey) || 'PENDING');
                  const rowSurface = getOutcomeOutlineClasses(normKey, 'bet');
                  const badgeCls =
                    normKey === 'WON'
                      ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/35'
                      : normKey === 'LOST'
                        ? 'bg-rose-500/15 text-rose-300 border-rose-500/35'
                        : normKey === 'PUSH'
                          ? 'bg-slate-600/25 text-slate-300 border-slate-500/40'
                          : normKey === 'VOID'
                            ? 'bg-amber-500/15 text-amber-300 border-amber-500/30'
                            : 'bg-sky-500/15 text-sky-300 border-sky-500/30';
                  const outLabel =
                    outKey === 'WON (PARTIAL)'
                      ? 'Won (Partial)'
                      : normKey === 'WON'
                        ? 'Won'
                        : normKey === 'LOST'
                          ? 'Lost'
                          : normKey === 'PUSH'
                            ? 'Push'
                            : normKey === 'VOID'
                              ? 'Void'
                              : 'Pending';
                  const oddsStr = formatAmericanOdds(item.american_odds) || '—';
                  const legs = Array.isArray(item.legs) ? item.legs : [];

                  return (
                    <tr
                      key={item.id || `${item.date_et}-${idx}`}
                      className={`${rowSurface.outcome ? rowSurface.rowCls : 'hover:bg-slate-900/50'} transition-colors`}
                    >
                      <th
                        scope="row"
                        className={`py-2.5 px-3 font-mono text-slate-300 whitespace-nowrap font-normal ${rowSurface.stripeCls}`}
                      >
                        {item.date_et || '—'}
                      </th>
                      <td className="py-2.5 px-3 min-w-[260px]">
                        <div className="space-y-1">
                          {legs.map((lg, lIdx) => {
                            const lgOut = String(lg?.outcome || 'PENDING').toUpperCase();
                            const lgCls =
                              lgOut === 'WON'
                                ? 'text-emerald-300'
                                : lgOut === 'LOST'
                                  ? 'text-rose-300'
                                  : lgOut === 'PUSH'
                                    ? 'text-slate-400'
                                    : 'text-sky-300';
                            const lgOdds = formatAmericanOdds(lg?.price);
                            const mktLabel = lg?.market_type ? formatMarketLabel(lg.market_type) : null;
                            return (
                              <div key={lg?.event_id || lIdx} className="flex flex-wrap items-center gap-1.5 text-[11px]">
                                {mktLabel && (
                                  <span className="px-1.5 py-0.5 rounded bg-slate-800 text-[10px] font-semibold text-slate-300">
                                    {mktLabel}
                                  </span>
                                )}
                                <span className="font-semibold text-slate-100">
                                  {lg?.team_pick || lg?.matchup || `Leg ${lIdx + 1}`}
                                </span>
                                {lgOdds && <span className="font-mono text-slate-400">({lgOdds})</span>}
                                <span className={`font-mono font-bold ${lgCls}`}>{lgOut}</span>
                                {lg?.score && <span className="font-mono text-slate-500">{lg.score}</span>}
                              </div>
                            );
                          })}
                        </div>
                      </td>
                      <td className="py-2.5 px-3 text-right font-mono font-semibold text-indigo-200 whitespace-nowrap">
                        {oddsStr}
                      </td>
                      <td className="py-2.5 px-3 whitespace-nowrap">
                        <span className={`inline-block px-2 py-0.5 rounded-full border text-[11px] font-semibold ${badgeCls}`}>
                          {outLabel}
                        </span>
                      </td>
                      <td
                        className={`py-2.5 px-3 text-right font-mono font-bold whitespace-nowrap ${
                          normKey === 'WON'
                            ? 'text-emerald-400'
                            : normKey === 'LOST'
                              ? 'text-rose-400'
                              : 'text-slate-400'
                        }`}
                      >
                        {normKey === 'PENDING' || item.roi_per_unit == null ? '—' : formatUnits(item.roi_per_unit)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </article>
    </div>
  );
}
