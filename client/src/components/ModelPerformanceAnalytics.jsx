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
  normalizeMarketType,
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
  preConfHistory = null,
  preMarketHistory = null,
  isTop6Scope = false,
  selectedSport = 'ALL',
  onSelectSport = null,
  selectedMarket = 'ALL',
  onSelectMarket = null,
  selectedConf = 'ALL',
  onSelectConf = null,
  scopeLabel = 'all recommended picks',
  filterSummary = 'All Sports • All Time',
  liveCalibration = null,
  slateAndRankSlot = null,
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
          recordText:
            settled > 0
              ? `${d.wins}-${d.losses}${d.pushes > 0 ? `-${d.pushes}` : ''}`
              : `${d.totalPicks} open`,
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
    const calendarWindows = Object.values(rollAcc).map(finalizeBucket);
    const hasRecentCalendarData = calendarWindows.some((w) => w.settled > 0);
    let recentWindows = calendarWindows;
    if (!hasRecentCalendarData && settledDays.length > 0) {
      const latestDay = settledDays[settledDays.length - 1].day;
      const latestDt = new Date(`${latestDay}T12:00:00Z`);
      const latestMinus = (d) => {
        const dt = new Date(latestDt);
        dt.setUTCDate(dt.getUTCDate() - d);
        return dt.toISOString().slice(0, 10);
      };
      const histAcc = {
        [`Latest Day (${shortDayLabel(latestDay)})`]: createBucketAccumulator(`Latest Day (${shortDayLabel(latestDay)})`),
        'Final 7 Active Days': createBucketAccumulator('Final 7 Active Days'),
        'Final 30 Active Days': createBucketAccumulator('Final 30 Active Days'),
        'Selected Total': createBucketAccumulator('Selected Total'),
      };
      const c7 = latestMinus(7);
      const c30 = latestMinus(30);
      for (const h of graded) {
        const day = getPerformanceDay(h);
        if (!day) continue;
        if (day === latestDay) accumulateRowInto(histAcc[`Latest Day (${shortDayLabel(latestDay)})`], h);
        if (day >= c7 && day <= latestDay) accumulateRowInto(histAcc['Final 7 Active Days'], h);
        if (day >= c30 && day <= latestDay) accumulateRowInto(histAcc['Final 30 Active Days'], h);
        accumulateRowInto(histAcc['Selected Total'], h);
      }
      recentWindows = Object.values(histAcc).map(finalizeBucket);
    }

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
    // Compute from preConfHistory when provided so clicking a tier leaves sibling tier totals visible.
    const confSource = Array.isArray(preConfHistory)
      ? preConfHistory.filter((h) => {
          const n = normalizeOutcome(getRawOutcome(h));
          return n === 'WON' || n === 'LOST' || n === 'PUSH';
        })
      : graded;
    const confDefs = ['High', 'Medium', 'Low'];
    const confMap = Object.fromEntries(confDefs.map((k) => [k, createBucketAccumulator(k)]));
    for (const h of confSource) {
      const tier = getConfidenceBucket(h);
      if (!confMap[tier]) confMap[tier] = createBucketAccumulator(tier);
      accumulateRowInto(confMap[tier], h);
    }
    const confidenceTiers = confDefs.map((k) => ({
      ...finalizeBucket(confMap[k]),
      desc: k === 'High' ? 'Score 80+' : k === 'Medium' ? 'Score 50–79' : 'Score < 50',
    }));

    // 5. Bet Type Breakdown (computed from preMarketHistory when provided so sibling bet types stay visible)
    const marketSource = Array.isArray(preMarketHistory)
      ? preMarketHistory.filter((h) => {
          const n = normalizeOutcome(getRawOutcome(h));
          return n === 'WON' || n === 'LOST' || n === 'PUSH';
        })
      : graded;
    const marketMap = {};
    for (const h of marketSource) {
      const marketKey = normalizeMarketType(h);
      const label = formatMarketLabel(marketKey);
      if (!marketMap[marketKey]) {
        marketMap[marketKey] = {
          ...createBucketAccumulator(label),
          marketKey,
        };
      }
      accumulateRowInto(marketMap[marketKey], h);
    }
    const betTypes = Object.values(marketMap)
      .map(finalizeBucket)
      .sort((a, b) => b.settled - a.settled);

    // 6. By Sport Breakdown (respects active filters via history unless overridden)
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

    // 7. NCAAM Edge Insights & Sweet Spots (simple breakdown + walk-forward benchmark)
    const ncaamGraded = graded.filter((h) => normalizeSport(h) === 'NCAAM');
    const roleAcc = {
      away_dog: createBucketAccumulator('Away Underdog (+)'),
      home_dog: createBucketAccumulator('Home Underdog (+)'),
      home_fav: createBucketAccumulator('Home Favorite (-)'),
      away_fav: createBucketAccumulator('Away Favorite (-)'),
    };
    const zoneAcc = {
      tight_sp: createBucketAccumulator('Tight Spread (<6 pts)'),
      mid_tot: createBucketAccumulator('Mid Total (140–151.5)'),
      high_under: createBucketAccumulator('High Total Under (152+)'),
      mid_sp: createBucketAccumulator('Mid Spread (6–13.5 pts)'),
      high_over: createBucketAccumulator('High Total Over (152+)'),
    };
    const convAcc = {
      sharp: createBucketAccumulator('Sharp / RLM Backed'),
      high_conf: createBucketAccumulator('High Confidence (80+)'),
      med_conf: createBucketAccumulator('Medium (50–79)'),
    };

    for (const h of ncaamGraded) {
      const mkt = normalizeMarketType(h);
      const rawLine = h?.bet_line ?? h?.market_line ?? h?.line;
      const numLine = rawLine !== null && rawLine !== undefined && rawLine !== '' ? Number(rawLine) : NaN;
      if (mkt === 'SPREAD' && Number.isFinite(numLine)) {
        const absSp = Math.abs(numLine);
        if (absSp < 6) accumulateRowInto(zoneAcc.tight_sp, h);
        else if (absSp < 14) accumulateRowInto(zoneAcc.mid_sp, h);

        const sideHint = String(h?.side || '').trim().toLowerCase();
        let isAway = null;
        if (sideHint === 'away' || sideHint === 'home') {
          isAway = sideHint === 'away';
        } else {
          const selLow = String(h?.selection || h?.pick || '').trim().toLowerCase();
          let awayTeam = String(h?.away_team || '').trim().toLowerCase();
          let homeTeam = String(h?.home_team || '').trim().toLowerCase();
          if (!awayTeam && !homeTeam) {
            const mTxt = String(h?.matchup || '').trim().toLowerCase();
            if (mTxt.includes(' @ ')) [awayTeam, homeTeam] = mTxt.split(' @ ').map((s) => s.trim());
            else if (mTxt.includes(' vs ')) [awayTeam, homeTeam] = mTxt.split(' vs ').map((s) => s.trim());
          }
          if (awayTeam && selLow.startsWith(awayTeam)) isAway = true;
          else if (homeTeam && selLow.startsWith(homeTeam)) isAway = false;
        }
        if (numLine > 0 && isAway === true) accumulateRowInto(roleAcc.away_dog, h);
        else if (numLine > 0 && isAway === false) accumulateRowInto(roleAcc.home_dog, h);
        else if (numLine < 0 && isAway === false) accumulateRowInto(roleAcc.home_fav, h);
        else if (numLine < 0 && isAway === true) accumulateRowInto(roleAcc.away_fav, h);
      } else if (mkt === 'TOTAL' && Number.isFinite(numLine)) {
        const totLine = Math.abs(numLine);
        const sideTxt = `${h?.side || ''} ${h?.selection || ''} ${h?.pick || ''}`.toUpperCase();
        const isOver = sideTxt.includes('OVER');
        const isUnder = sideTxt.includes('UNDER');
        if (totLine >= 140 && totLine < 152) {
          accumulateRowInto(zoneAcc.mid_tot, h);
        } else if (totLine >= 152) {
          if (isUnder) accumulateRowInto(zoneAcc.high_under, h);
          else if (isOver) accumulateRowInto(zoneAcc.high_over, h);
        }
      }

      const rawTags = h?.movement_tags || h?.sanity_reasons;
      const tags = (
        Array.isArray(rawTags)
          ? rawTags
          : typeof rawTags === 'string'
            ? rawTags.split(',')
            : []
      ).map((t) => String(t || '').trim().toLowerCase());
      if (tags.includes('sharp_backing') || tags.includes('rlm_confirmed')) {
        accumulateRowInto(convAcc.sharp, h);
      }

      const cTier = getConfidenceBucket(h);
      if (cTier === 'High') accumulateRowInto(convAcc.high_conf, h);
      else if (cTier === 'Medium') accumulateRowInto(convAcc.med_conf, h);
    }

    const withMeta = (acc, badge, tone, benchmark) => ({
      ...finalizeBucket(acc),
      badge,
      tone,
      benchmark,
    });

    const ncaamEdgeInsights = {
      sampleCount: ncaamGraded.length,
      spreadRoles: [
        withMeta(roleAcc.away_dog, 'Sweet Spot', 'emerald', 'Backtest: 63.5% WR · +20.9% ROI'),
        withMeta(roleAcc.home_dog, 'Strong Edge', 'emerald', 'Backtest: 61.4% WR · +16.8% ROI'),
        withMeta(roleAcc.home_fav, 'Solid', 'sky', 'Backtest: 56.7% WR · +8.2% ROI'),
        withMeta(roleAcc.away_fav, 'Guarded', 'amber', 'Backtest: 39.5% WR · -24.6% ROI (Tight EV Gate)'),
      ],
      lineZones: [
        withMeta(zoneAcc.tight_sp, 'Best Spread Zone', 'emerald', 'Backtest: 55.3% WR · +5.6% ROI'),
        withMeta(zoneAcc.mid_tot, 'Best Total Zone', 'emerald', 'Backtest: 69.4% WR · +31.7% ROI'),
        withMeta(zoneAcc.high_under, 'Pace Ceiling', 'sky', 'Backtest: 58.3% WR · +11.4% ROI'),
        withMeta(zoneAcc.mid_sp, 'Damped / High-Bar', 'amber', 'Raised EV bar & shrink vs backdoor risk'),
        withMeta(zoneAcc.high_over, 'Damped / High-Bar', 'amber', 'Backtest: 51.7% WR · -1.3% ROI (Capped Over)'),
      ],
      conviction: [
        withMeta(convAcc.sharp, 'Top Multiplier', 'emerald', 'Backtest: 65.5% WR · +24.5% ROI'),
        withMeta(convAcc.high_conf, 'Top Tier', 'sky', 'Filtered to highest lower-bound win chance'),
        withMeta(convAcc.med_conf, 'Baseline', 'slate', 'Standard qualifying picks (50–79 score)'),
      ],
    };

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
      ncaamEdgeInsights,
      latestCumulativeUnits: settledDays.length > 0 ? settledDays[settledDays.length - 1].cumulativeUnits : 0,
    };
  }, [history, allHistory, preConfHistory, preMarketHistory]);

  return (
    <section className="space-y-6" aria-label="Model Performance Charts and Breakdowns">
      {/* Card 1: Performance Over Time */}
      <article className="ui-card p-5 sm:p-6 space-y-4" aria-labelledby="perf-trend-heading">
        <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-3">
          <div>
            <h3 id="perf-trend-heading" className="text-lg font-bold text-slate-100">
              Profit &amp; Results Over Time
            </h3>
            <p className="text-xs text-slate-400">
              {filterSummary} • Flat 1-unit profit across {analytics.settledDays.length} finished days ({scopeLabel}).
            </p>
          </div>

          <div
            role="tablist"
            aria-label="Performance trend view"
            className="perf-tablist"
          >
            {[
              { id: 'cumulative', label: 'Total Profit' },
              { id: 'daily', label: 'Day by Day' },
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
                  onClick={() => setTrendTab(t.id)}
                  className="perf-tab"
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
                        if (name === 'cumulativeUnits') return [formatUnits(value), 'Running Total'];
                        return [value, name];
                      }}
                      labelFormatter={(_, payload) => {
                        const p = payload?.[0]?.payload;
                        if (!p) return '';
                        return `${p.day} • Record ${p.recordText} • Day Profit ${formatUnits(p.profitUnits)}`;
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
              Assumes the same 1-unit bet on every graded pick. Above 0u means ahead overall; hover a date to see that day&apos;s record.
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
              <>
                <div className="flex flex-wrap items-center gap-3 text-[11px] text-slate-300">
                  <span className="inline-flex items-center gap-1.5">
                    <span className="w-2.5 h-2.5 rounded-sm bg-emerald-500 inline-block" />
                    <span className="w-2.5 h-2.5 rounded-sm bg-rose-500 inline-block -ml-1" />
                    Daily Profit (u)
                  </span>
                  <span className="inline-flex items-center gap-1.5">
                    <span className="w-3 h-0.5 bg-indigo-400 inline-block" />
                    Daily Win %
                  </span>
                  <span className="inline-flex items-center gap-1.5 text-amber-300">
                    <span className="w-3 border-t border-dashed border-amber-400 inline-block" />
                    52.4% Break-Even
                  </span>
                </div>
                <div className="h-[270px] w-full">
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
                      <ReferenceLine yAxisId="right" y={52.4} stroke="#f59e0b" strokeDasharray="4 4" />
                      <Tooltip
                        contentStyle={TOOLTIP_STYLE}
                        formatter={(value, name) => {
                          if (name === 'profitUnits') return [formatUnits(value), 'Day Profit'];
                          if (name === 'winRate') return [`${value}%`, 'Daily Win %'];
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
              </>
            )}
            <p className="text-[11px] text-slate-400">
              Shows up to the last 45 active game days. Bars show daily profit or loss; the line tracks daily win % against 52.4% break-even.
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
              <>
                <div className="flex flex-wrap items-center gap-3 text-[11px] text-slate-300">
                  <span className="inline-flex items-center gap-1.5 text-emerald-300">
                    <span className="w-3 border-t border-dashed border-emerald-400 inline-block" />
                    High Confidence (80+)
                  </span>
                  <span className="inline-flex items-center gap-1.5 text-amber-300">
                    <span className="w-3 border-t border-dashed border-amber-400 inline-block" />
                    Medium Confidence (50+)
                  </span>
                </div>
                <div className="h-[270px] w-full">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={analytics.confidenceDays} margin={{ top: 10, right: 16, left: 0, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
                      <XAxis dataKey="shortDay" stroke="#64748b" fontSize={11} tickLine={false} minTickGap={26} />
                      <YAxis domain={[0, 100]} stroke="#64748b" fontSize={11} tickLine={false} tickFormatter={(v) => `${v}`} width={36} />
                      <ReferenceLine y={80} stroke="#10b981" strokeDasharray="4 4" />
                      <ReferenceLine y={50} stroke="#f59e0b" strokeDasharray="4 4" />
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
              </>
            )}
            <p className="text-[11px] text-slate-400">
              Average pick confidence score (0–100) per day across graded and pending picks.
            </p>
          </div>
        )}
      </article>

      {slateAndRankSlot}

      {/* Row 2: Bet Type Performance & Edge Calibration */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Card 2: Bet Type Performance */}
        <article className="ui-card p-5 sm:p-6 space-y-4" aria-labelledby="bet-type-heading">
          <div className="flex items-start justify-between gap-2">
            <div>
              <h3 id="bet-type-heading" className="text-base font-bold text-slate-100">
                Performance by Bet Type
              </h3>
              <p className="text-xs text-slate-400">
                Return on 1-unit bets across Spreads, Over/Under Totals, Moneylines, and Parlays. Click a row to filter.
              </p>
            </div>
            {selectedMarket !== 'ALL' && onSelectMarket && (
              <button
                type="button"
                onClick={() => onSelectMarket('ALL')}
                className="text-xs font-semibold text-indigo-300 hover:text-indigo-200 underline cursor-pointer shrink-0"
              >
                All Types
              </button>
            )}
          </div>

          {analytics.betTypes.length === 0 ? (
            <div className="h-[200px] flex items-center justify-center rounded-xl border border-slate-800 bg-slate-950/60 text-sm text-slate-500">
              No settled picks in this view.
            </div>
          ) : (
            <>
              <div className="h-[185px] w-full">
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

              <div role="region" aria-labelledby="bet-type-heading" tabIndex={0} className="perf-table-wrapper">
                <table className="perf-sticky-table w-full text-left border-collapse text-xs">
                  <thead>
                    <tr className="border-b border-slate-800 text-slate-400">
                      <th scope="col" className="py-1.5 pr-3 font-medium">Bet Type</th>
                      <th scope="col" className="py-1.5 px-3 font-medium">Record</th>
                      <th scope="col" className="py-1.5 px-3 font-medium text-right">Win %</th>
                      <th scope="col" className="py-1.5 px-3 font-medium text-right">Profit</th>
                      <th scope="col" className="py-1.5 px-3 font-medium text-right">ROI</th>
                      <th scope="col" className="py-1.5 pl-3 font-medium text-right">Line Beat</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/70">
                    {analytics.betTypes.map((m) => {
                      const activeMkt = selectedMarket === m.marketKey;
                      const clvCls =
                        m.avgClv === null
                          ? 'text-slate-500'
                          : m.avgClv > 0
                            ? 'text-emerald-400'
                            : m.avgClv === 0
                              ? 'text-slate-300'
                              : 'text-rose-400';
                      return (
                        <tr
                          key={m.label}
                          onClick={() => onSelectMarket && onSelectMarket(activeMkt ? 'ALL' : m.marketKey)}
                          className={`transition-colors ${onSelectMarket ? 'cursor-pointer' : ''} ${
                            activeMkt ? 'bg-indigo-500/15' : 'hover:bg-slate-900/50'
                          }`}
                        >
                          <th scope="row" className="py-1.5 pr-3 font-semibold text-slate-200">{m.label}</th>
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
                          <td className={`py-1.5 pl-3 text-right font-mono font-semibold ${clvCls}`}>
                            {m.avgClv !== null ? `${m.avgClv > 0 ? '+' : ''}${m.avgClv.toFixed(2)}` : '—'}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </article>

        {/* Card 3: Edge Calibration */}
        <article className="ui-card p-5 sm:p-6 space-y-4" aria-labelledby="edge-cal-heading">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <h3 id="edge-cal-heading" className="text-base font-bold text-slate-100">
                Win % by Edge Size
              </h3>
              <p className="text-xs text-slate-400">
                Checks if larger projected edges win more often. At standard -110 odds, 52.4% breaks even.
              </p>
            </div>
            <div className="flex items-center gap-3">
              <span className="inline-flex items-center gap-1.5 text-[11px] font-medium text-amber-300 bg-amber-500/10 border border-amber-500/30 rounded-full px-2.5 py-0.5">
                <span className="w-2.5 border-t border-dashed border-amber-400 inline-block" />
                52.4% Break-Even
              </span>
              <div role="tablist" aria-label="Edge view mode" className="perf-tablist">
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
                    onClick={() => setEdgeTab(t.id)}
                    className="perf-tab"
                  >
                    {t.label}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {edgeTab === 'chart' ? (
            <div id="edge-panel-chart" role="tabpanel" aria-labelledby="edge-tab-chart" className="space-y-2">
              <div className="h-[245px] w-full">
                {analytics.edgeBuckets.every((b) => b.settled === 0) ? (
                  <div className="h-full flex items-center justify-center rounded-xl border border-slate-800 bg-slate-950/60 text-sm text-slate-500">
                    No settled picks to group by edge.
                  </div>
                ) : (
                  <ResponsiveContainer width="100%" height="100%">
                    <ComposedChart
                      data={analytics.edgeBuckets.map((b) => ({
                        ...b,
                        axisLabel: b.settled > 0 ? `${b.label} (${b.settled})` : b.label,
                      }))}
                      margin={{ top: 10, right: 12, left: 0, bottom: 0 }}
                    >
                      <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
                      <XAxis dataKey="axisLabel" stroke="#64748b" fontSize={10} tickLine={false} interval={0} />
                      <YAxis domain={[0, 100]} stroke="#64748b" fontSize={11} tickLine={false} tickFormatter={(v) => `${v}%`} width={40} />
                      <ReferenceLine y={52.4} stroke="#f59e0b" strokeDasharray="4 4" />
                      <Tooltip
                        contentStyle={TOOLTIP_STYLE}
                        formatter={(val, name) => {
                          if (name === 'winRate') return [`${Number(val).toFixed(1)}%`, 'Win %'];
                          return [val, name];
                        }}
                        labelFormatter={(_, payload) => {
                          const p = payload?.[0]?.payload;
                          if (!p) return '';
                          return `${p.label} Edge • ${p.recordText} (${p.settled} settled) • ${formatUnits(p.profitUnits)} (${formatSignedPct(p.roiPct)})`;
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
              <p className="text-[11px] text-slate-400">
                Picks in parentheses. Small groups (under 10 picks) swing widely from game to game.
              </p>
            </div>
          ) : (
            <div id="edge-panel-table" role="tabpanel" aria-labelledby="edge-tab-table">
              <div role="region" aria-labelledby="edge-cal-heading" tabIndex={0} className="perf-table-wrapper">
                <table className="perf-sticky-table w-full text-left border-collapse text-xs">
                  <thead>
                    <tr className="border-b border-slate-800 text-slate-400">
                      <th scope="col" className="py-2 pr-3 font-medium">Edge Size</th>
                      <th scope="col" className="py-2 px-3 font-medium text-right">Settled</th>
                      <th scope="col" className="py-2 px-3 font-medium">Record</th>
                      <th scope="col" className="py-2 px-3 font-medium text-right">Win %</th>
                      <th scope="col" className="py-2 px-3 font-medium text-right">Profit</th>
                      <th scope="col" className="py-2 px-3 font-medium text-right">ROI</th>
                      <th scope="col" className="py-2 pl-3 font-medium text-right">Line Beat</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/70">
                    {analytics.edgeBuckets.map((b) => {
                      const clvCls =
                        b.avgClv === null
                          ? 'text-slate-500'
                          : b.avgClv > 0
                            ? 'text-emerald-400'
                            : b.avgClv === 0
                              ? 'text-slate-300'
                              : 'text-rose-400';
                      return (
                        <tr key={b.label} className="hover:bg-slate-900/50">
                          <th scope="row" className="py-2 pr-3 font-medium text-slate-200">{b.label}</th>
                          <td className="py-2 px-3 text-right text-slate-400">{b.settled}</td>
                          <td className="py-2 px-3 font-mono text-slate-300">{b.recordText}</td>
                          <td className={`py-2 px-3 text-right font-mono font-semibold ${b.winRate >= 52.4 ? 'text-emerald-400' : 'text-slate-300'}`}>
                            {b.decided > 0 ? formatPct(b.winRate) : '—'}
                          </td>
                          <td className={`py-2 px-3 text-right font-mono font-semibold ${b.profitUnits >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                            {formatUnits(b.profitUnits)}
                          </td>
                          <td className={`py-2 px-3 text-right font-mono font-semibold ${b.roiPct >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                            {b.settled > 0 ? formatSignedPct(b.roiPct) : '—'}
                          </td>
                          <td className={`py-2 pl-3 text-right font-mono font-semibold ${clvCls}`}>
                            {b.avgClv !== null ? `${b.avgClv > 0 ? '+' : ''}${b.avgClv.toFixed(2)}` : '—'}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </article>
      </div>

      {/* Row 3: Confidence Tiers & Recent Form + By Sport Comparison */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Card 4: Confidence Tiers & Recent Form */}
        <article className="ui-card p-5 sm:p-6 space-y-4" aria-labelledby="conf-form-heading">
          <div className="flex items-start justify-between gap-2">
            <div>
              <h3 id="conf-form-heading" className="text-base font-bold text-slate-100">
                Confidence Levels &amp; Recent Form
              </h3>
              <p className="text-xs text-slate-400">
                High (80+), Medium (50–79), and Low (&lt;50) pick scores. Click a box to filter.
              </p>
            </div>
            {selectedConf !== 'ALL' && onSelectConf && (
              <button
                type="button"
                onClick={() => onSelectConf('ALL')}
                className="text-xs font-semibold text-indigo-300 hover:text-indigo-200 underline cursor-pointer shrink-0"
              >
                All Levels
              </button>
            )}
          </div>

          <div className="grid grid-cols-3 gap-2.5">
            {analytics.confidenceTiers.map((t) => {
              const tierKey = t.label.toUpperCase();
              const isSelected = selectedConf === tierKey;
              const badgeColor =
                t.label === 'High'
                  ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
                  : t.label === 'Medium'
                    ? 'border-amber-500/30 bg-amber-500/10 text-amber-300'
                    : 'border-slate-700 bg-slate-900/80 text-slate-300';
              return (
                <button
                  key={t.label}
                  type="button"
                  aria-pressed={isSelected}
                  onClick={() => onSelectConf && onSelectConf(isSelected ? 'ALL' : tierKey)}
                  className={`text-left rounded-xl border p-3 transition-all focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-400 ${onSelectConf ? 'cursor-pointer hover:brightness-110' : ''} ${badgeColor} ${
                    isSelected ? 'ring-2 ring-indigo-400/70' : ''
                  }`}
                >
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
                </button>
              );
            })}
          </div>

          <div className="space-y-2">
            <h4 id="recent-form-heading" className="text-xs font-bold uppercase tracking-wider text-slate-400">Recent Form</h4>
            <div role="region" aria-labelledby="recent-form-heading" tabIndex={0} className="perf-table-wrapper">
              <table className="perf-sticky-table w-full text-left border-collapse text-xs">
                <thead>
                  <tr className="border-b border-slate-800 text-slate-400">
                    <th scope="col" className="py-1.5 pr-3 font-medium">Timeframe</th>
                    <th scope="col" className="py-1.5 px-3 font-medium">Record</th>
                    <th scope="col" className="py-1.5 px-3 font-medium text-right">Win %</th>
                    <th scope="col" className="py-1.5 px-3 font-medium text-right">Profit</th>
                    <th scope="col" className="py-1.5 pl-3 font-medium text-right">ROI</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/70">
                  {analytics.recentWindows.map((w) => (
                    <tr key={w.label} className="hover:bg-slate-900/50">
                      <th scope="row" className="py-1.5 pr-3 font-medium text-slate-200">{w.label}</th>
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

        {/* Card 5: Performance by Sport (Click to Filter) */}
        <article className="ui-card p-5 sm:p-6 space-y-4" aria-labelledby="by-sport-heading">
          <div className="flex items-start justify-between gap-2">
            <div>
              <h3 id="by-sport-heading" className="text-base font-bold text-slate-100">
                Performance by Sport
              </h3>
              <p className="text-xs text-slate-400">
                {selectedSport !== 'ALL'
                  ? `Filtered to ${filterSummary} (${isTop6Scope ? 'Top 6 / Day' : 'All Picks'}). Click Show All Sports to compare sports.`
                  : `${filterSummary} (${isTop6Scope ? 'Top 6 / Day' : 'All Picks'}). Click any sport row to filter the whole page.`}
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
                    className={`w-full text-left rounded-xl border p-3.5 transition-all cursor-pointer focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-400 ${
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

      {/* Row 3.5: NCAAM Model Insights & Sweet Spots */}
      {(selectedSport === 'NCAAM' || selectedSport === 'ALL') && (() => {
        const insights = analytics.ncaamEdgeInsights;
        const toneCls = {
          emerald: 'bg-emerald-500/15 border-emerald-500/35 text-emerald-300',
          sky: 'bg-sky-500/15 border-sky-500/35 text-sky-300',
          amber: 'bg-amber-500/15 border-amber-500/35 text-amber-300',
          slate: 'bg-slate-800 border-slate-700 text-slate-300',
        };
        const renderInsightCol = (title, subtitle, items) => (
          <div className="rounded-xl border border-slate-800 bg-slate-950/55 p-4 space-y-2.5">
            <div>
              <h4 className="text-xs font-bold uppercase tracking-wider text-slate-200">{title}</h4>
              <p className="text-[11px] text-slate-400">{subtitle}</p>
            </div>
            <div className="space-y-2">
              {items.map((item) => (
                <div
                  key={item.label}
                  className="rounded-lg border border-slate-800/80 bg-slate-900/50 px-3 py-2 space-y-1"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs font-semibold text-slate-100">{item.label}</span>
                    <span className={`px-2 py-0.5 rounded-full border text-[10px] font-semibold shrink-0 ${toneCls[item.tone] || toneCls.slate}`}>
                      {item.badge}
                    </span>
                  </div>
                  <div className="flex items-center justify-between gap-2 text-[11px]">
                    {item.settled > 0 ? (
                      <>
                        <span className="font-mono text-slate-300">
                          {item.recordText} · {formatPct(item.winRate)}
                        </span>
                        <span className={`font-mono font-semibold ${item.profitUnits >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                          {formatUnits(item.profitUnits)} ({formatSignedPct(item.roiPct)})
                        </span>
                      </>
                    ) : (
                      <span className="text-slate-500">No settled picks in filter</span>
                    )}
                  </div>
                  <div className="text-[10px] text-slate-400 font-mono">{item.benchmark}</div>
                </div>
              ))}
            </div>
          </div>
        );

        return (
          <article className="ui-card p-5 sm:p-6 space-y-4" aria-labelledby="ncaam-insights-heading">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <h3 id="ncaam-insights-heading" className="text-base font-bold text-slate-100">
                  NCAAM Model Insights &amp; Sweet Spots
                </h3>
                <p className="text-xs text-slate-400">
                  Compares your live graded NCAAM picks ({insights.sampleCount.toLocaleString()} settled in current filter) against 1,600-game walk-forward benchmarks so you know which spots deserve trust.
                </p>
              </div>
              <span className="px-2.5 py-1 rounded-full border border-indigo-500/35 bg-indigo-500/15 text-indigo-200 text-xs font-semibold">
                NCAAM Strategy Intel
              </span>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
              {renderInsightCol(
                'Spread Role Edge',
                'Underdogs & home favorites outperform road favorites.',
                insights.spreadRoles
              )}
              {renderInsightCol(
                'Spread & Total Zones',
                'Tight spreads (<6) and 140–151.5 totals lead ROI.',
                insights.lineZones
              )}
              {renderInsightCol(
                'Conviction Signals',
                'Sharp/RLM confirmation is our highest-ROI multiplier.',
                insights.conviction
              )}
            </div>
          </article>
        );
      })()}

      {/* Row 4: Live In-Game Win-Chance Accuracy */}
      {(() => {
        const cal = liveCalibration && typeof liveCalibration === 'object' ? liveCalibration : {};
        const minReq = Number(cal.min_obs_required || 25);
        const decidedObs = Number(cal.decided_snapshots ?? cal.n_obs ?? 0);
        const isCalibrated = Boolean(cal.active) || decidedObs >= minReq;
        const pendingObs = Number(cal.pending_snapshots || 0);
        const params = cal.params || {};
        const liveWtPct = Math.round((Number(params.live_weight_scale ?? 0.85)) * 100);
        const sigmaSpread = Number(params.sigma_spread_rem ?? 10.5).toFixed(1);
        const sigmaTotal = Number(params.sigma_total_rem ?? 13.5).toFixed(1);
        const bins = Array.isArray(cal.bins) ? cal.bins : [];

        return (
          <article className="ui-card p-5 sm:p-6 space-y-4" aria-labelledby="live-cal-heading">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h3 id="live-cal-heading" className="text-base font-bold text-slate-100">
                  Live Win-Chance Accuracy
                </h3>
                <p className="text-xs text-slate-400">
                  Checks whether our live in-game win % predictions match how games actually finish.
                </p>
              </div>
              <span
                className={`px-2.5 py-1 rounded-full border text-xs font-semibold ${
                  cal.active
                    ? 'bg-emerald-500/15 border-emerald-500/35 text-emerald-300'
                    : isCalibrated
                      ? 'bg-indigo-500/15 border-indigo-500/35 text-indigo-300'
                      : 'bg-amber-500/15 border-amber-500/35 text-amber-300'
                }`}
              >
                {cal.active
                  ? `Active · ${decidedObs.toLocaleString()} live checks`
                  : isCalibrated
                    ? `Ready · ${decidedObs.toLocaleString()} graded (updates next sync)`
                    : `Collecting Data (${decidedObs} / ${minReq} graded)`}
              </span>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3.5 space-y-1">
                <div className="text-[11px] font-bold uppercase tracking-wider text-slate-400">Checks Logged</div>
                <div className="text-lg font-mono font-bold text-slate-100">
                  {decidedObs.toLocaleString()} graded
                </div>
                <div className="text-[11px] text-slate-400">
                  {pendingObs > 0 ? `${pendingObs.toLocaleString()} waiting for final score` : 'Saved automatically during live games'}
                </div>
              </div>

              <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3.5 space-y-1">
                <div className="text-[11px] font-bold uppercase tracking-wider text-slate-400">Prediction Accuracy</div>
                <div className="text-lg font-mono font-bold text-slate-100">
                  {cal.brier_calibrated != null
                    ? `${Number(cal.brier_calibrated).toFixed(3)}`
                    : cal.brier_raw != null
                      ? `${Number(cal.brier_raw).toFixed(3)} (baseline)`
                      : '—'}
                </div>
                <div className="text-[11px] text-slate-400">
                  {cal.brier_raw != null && cal.brier_calibrated != null
                    ? `Down from ${Number(cal.brier_raw).toFixed(3)} baseline (lower is better)`
                    : `Brier error score (lower is better; tunes at ${minReq}+ graded)`}
                </div>
              </div>

              <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3.5 space-y-1">
                <div className="text-[11px] font-bold uppercase tracking-wider text-slate-400">Live Game Formula</div>
                <div className="text-sm font-mono font-bold text-indigo-300">
                  {liveWtPct}% live weight · ±{sigmaSpread} spread · ±{sigmaTotal} total
                </div>
                <div className="text-[11px] text-slate-400">
                  {cal.active ? 'Auto-tuned from finished live games' : 'Using default pregame + live blend'}
                </div>
              </div>
            </div>

            {bins.some((b) => Number(b.count || 0) > 0) ? (
              <div role="region" aria-labelledby="live-cal-heading" tabIndex={0} className="perf-table-wrapper">
                <table className="perf-sticky-table w-full text-left border-collapse text-xs">
                  <thead>
                    <tr className="border-b border-slate-800 text-slate-400">
                      <th scope="col" className="py-1.5 pr-3 font-medium">Predicted Chance</th>
                      <th scope="col" className="py-1.5 px-3 font-medium text-right">Checks</th>
                      <th scope="col" className="py-1.5 px-3 font-medium text-right">Model Said</th>
                      <th scope="col" className="py-1.5 px-3 font-medium text-right">Actually Won</th>
                      <th scope="col" className="py-1.5 px-3 font-medium min-w-[140px]">Visual Match</th>
                      <th scope="col" className="py-1.5 pl-3 font-medium text-right">Difference</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/70">
                    {bins.map((b) => {
                      const pred = b.avg_predicted_pct != null ? Number(b.avg_predicted_pct) : null;
                      const actual = b.actual_win_pct != null ? Number(b.actual_win_pct) : null;
                      const gap = pred != null && actual != null ? actual - pred : null;
                      const gapColor =
                        gap === null
                          ? 'text-slate-500'
                          : Math.abs(gap) <= 6
                            ? 'text-emerald-400'
                            : Math.abs(gap) <= 15
                              ? 'text-amber-300'
                              : 'text-rose-400';
                      return (
                        <tr key={b.label} className="hover:bg-slate-900/50">
                          <th scope="row" className="py-2 pr-3 font-medium text-slate-200">{b.label}</th>
                          <td className="py-2 px-3 text-right font-mono text-slate-400">{b.count || 0}</td>
                          <td className="py-2 px-3 text-right font-mono text-slate-300">
                            {pred != null ? `${pred.toFixed(1)}%` : '—'}
                          </td>
                          <td className="py-2 px-3 text-right font-mono font-semibold text-emerald-300">
                            {actual != null ? `${actual.toFixed(1)}%` : '—'}
                          </td>
                          <td className="py-2 px-3">
                            {pred != null && actual != null ? (
                              <div
                                className="relative h-2.5 w-full rounded-full bg-slate-900 border border-slate-800 overflow-hidden"
                                title={`Model said ${pred.toFixed(1)}% (yellow line) vs Actually won ${actual.toFixed(1)}% (green bar)`}
                              >
                                <div
                                  className="h-full rounded-full bg-emerald-500/75"
                                  style={{ width: `${Math.max(0, Math.min(100, actual))}%` }}
                                />
                                <div
                                  className="absolute top-0 bottom-0 w-0.5 bg-amber-300"
                                  style={{ left: `${Math.max(0, Math.min(99, pred))}%` }}
                                />
                              </div>
                            ) : (
                              '—'
                            )}
                          </td>
                          <td className={`py-2 pl-3 text-right font-mono font-semibold ${gapColor}`}>
                            {gap !== null ? `${gap > 0 ? '+' : ''}${gap.toFixed(1)}%` : '—'}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="rounded-xl border border-slate-800/80 bg-slate-950/50 px-4 py-3 text-xs text-slate-400">
                Live checks are saved automatically whenever tracked college basketball games are in progress. Once {minReq}+ finish grading, this table will compare predicted live win % against final outcomes.
              </div>
            )}
          </article>
        );
      })()}
    </section>
  );
};

export default ModelPerformanceAnalytics;
