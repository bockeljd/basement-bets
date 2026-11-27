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
  computePerformanceDiagnostics,
  getSegmentStatusMeta,
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
  modelLearning = null,
  slateAndRankSlot = null,
  viewMode = 'all', // 'all' | 'overview' | 'diagnostics'
  onSelectWindow = null,
  onOpenLedger = null,
}) => {
  const [trendTab, setTrendTab] = useState('cumulative');
  const [edgeTab, setEdgeTab] = useState('chart');

  const showOverview = viewMode === 'all' || viewMode === 'overview';
  const showDiagnostics = viewMode === 'all' || viewMode === 'diagnostics';

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
    let peakUnits = 0;
    const chronologicalDays = Object.values(dayMap)
      .sort((a, b) => a.day.localeCompare(b.day))
      .map((d) => {
        const decided = d.wins + d.losses;
        const settled = decided + d.pushes;
        runningUnits += d.profitUnits;
        if (runningUnits > peakUnits) peakUnits = runningUnits;
        const drawdownUnits = Number(Math.min(0, runningUnits - peakUnits).toFixed(2));
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
          peakUnits: Number(peakUnits.toFixed(2)),
          drawdownUnits,
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

    const timingAcc = {
      BET_NOW: createBucketAccumulator('Bet Now'),
      WAIT_LINEUPS: createBucketAccumulator('Wait · Check Lineups'),
      MONITOR: createBucketAccumulator('Monitor · May Improve'),
    };
    const timingClvPos = { BET_NOW: 0, WAIT_LINEUPS: 0, MONITOR: 0 };
    const timingOpen = { BET_NOW: 0, WAIT_LINEUPS: 0, MONITOR: 0 };

    for (const h of safeHistory) {
      const tAct = String(
        h?.bet_timing_action || h?.bet_timing?.action || h?.rec_json?.bet_timing?.action || ''
      )
        .trim()
        .toUpperCase();
      if (!timingAcc[tAct]) continue;
      const normOut = normalizeOutcome(getRawOutcome(h));
      if (normOut === 'WON' || normOut === 'LOST' || normOut === 'PUSH') {
        accumulateRowInto(timingAcc[tAct], h);
        const clv = parseFloat(h?.clv_points);
        if (Number.isFinite(clv) && clv > 0) {
          timingClvPos[tAct] += 1;
        }
      } else if (normOut !== 'VOID') {
        timingOpen[tAct] += 1;
      }
    }

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

    const withMeta = (acc, note) => {
      const fin = finalizeBucket(acc);
      const st = getSegmentStatusMeta(fin.settled, fin.roiPct);
      return {
        ...fin,
        badge: st.label,
        tone: st.tone,
        benchmark: note,
      };
    };

    const adaptiveDesc = (section, key, fallbackText) => {
      const bucket = modelLearning?.[section]?.[key];
      const rawRoi = bucket?.roi_per_unit ?? bucket?.roi;
      if (bucket && Number(bucket.n || 0) >= 3 && bucket.win_rate != null && rawRoi != null) {
        const wr = (Number(bucket.win_rate) * 100).toFixed(1);
        const roiNum = Number(rawRoi) * 100;
        const roiStr = `${roiNum >= 0 ? '+' : ''}${roiNum.toFixed(1)}%`;
        return `Season Adaptive: ${wr}% WR · ${roiStr} ROI (${bucket.n} graded) · ${fallbackText}`;
      }
      return fallbackText;
    };

    const ncaamEdgeInsights = {
      sampleCount: ncaamGraded.length,
      spreadRoles: [
        withMeta(roleAcc.away_dog, adaptiveDesc('by_spread_role', 'away_dog', 'Road underdogs protected by role-aware gate')),
        withMeta(roleAcc.home_dog, adaptiveDesc('by_spread_role', 'home_dog', 'Home dogs shielded from Home Fav chalk bump')),
        withMeta(roleAcc.home_fav, adaptiveDesc('by_spread_role', 'home_fav', 'Guarded in v2.4.4: 0.80x early chalk damp + EV hurdle')),
        withMeta(roleAcc.away_fav, adaptiveDesc('by_spread_role', 'away_fav', 'Road fav gate: +2.4%/+3.2% EV hurdle & damping')),
      ],
      lineZones: [
        withMeta(zoneAcc.tight_sp, adaptiveDesc('by_spread_bucket', 'under_6', 'Tight spread (<6 pts) · Extra early-season selectivity')),
        withMeta(zoneAcc.mid_tot, adaptiveDesc('by_total_zone', 'under_mid_140_152', 'Mid totals (140–151.5) · Tight Over cap & Under focus')),
        withMeta(zoneAcc.high_under, adaptiveDesc('by_total_zone', 'under_high_152+', 'High-total Under (152+) · Pace ceiling regression')),
        withMeta(zoneAcc.mid_sp, adaptiveDesc('by_spread_bucket', 'mid_6_14', 'Mid spread (6–13.5) · Ranked over blowout garbage time')),
        withMeta(zoneAcc.high_over, adaptiveDesc('by_total_zone', 'over_high_152+', 'High-total Over (152+) · Stricter Over cap & EV bar')),
      ],
      conviction: [
        withMeta(convAcc.sharp, 'Sharp / RLM confirmed · Highest confirmation signal'),
        withMeta(convAcc.high_conf, 'High score (80+) lower-bound probability'),
        withMeta(convAcc.med_conf, 'Medium tier (50–79) qualifying baseline'),
      ],
    };

    const timingBuckets = ['BET_NOW', 'WAIT_LINEUPS', 'MONITOR'].map((action) => {
      const fin = finalizeBucket(timingAcc[action]);
      const posRate =
        fin.clvCount > 0 ? Math.round((timingClvPos[action] / fin.clvCount) * 100) : null;
      return {
        ...fin,
        action,
        openCount: timingOpen[action] || 0,
        posClvRate: posRate,
      };
    });

    const cumVals = settledDays.map((d) => d.cumulativeUnits);
    const minCum = cumVals.length > 0 ? Math.min(0, ...cumVals) : 0;
    const maxCum = cumVals.length > 0 ? Math.max(0, ...cumVals) : 0;
    const zeroSplitOffset =
      maxCum > 0 && minCum < 0
        ? Math.max(0.001, Math.min(0.999, maxCum / (maxCum - minCum)))
        : maxCum > 0
          ? 1
          : 0;

    const diagnostics = computePerformanceDiagnostics(safeHistory, modelLearning);

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
      timingBuckets,
      diagnostics,
      zeroSplitOffset,
      latestCumulativeUnits: settledDays.length > 0 ? settledDays[settledDays.length - 1].cumulativeUnits : 0,
    };
  }, [history, allHistory, preConfHistory, preMarketHistory, modelLearning]);

  const diag = analytics.diagnostics;

  return (
    <section className="space-y-6" aria-label="Model Performance Charts and Breakdowns">
      {/* Overview: Equity Curve + Leak Radar + Slate Recap */}
      {showOverview && (
        <>
          {/* Edge Health & Leak Radar */}
          {diag.settledCount > 0 && (
            <article className="perf-chart-card p-5 sm:p-6 space-y-5" aria-labelledby="leak-radar-heading">
              <div className="flex flex-col lg:flex-row lg:items-start justify-between gap-3">
                <div className="space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 id="leak-radar-heading" className="text-lg font-bold text-slate-100">
                      Edge Health &amp; Leak Radar
                    </h3>
                    {diag.eraComparison && (
                      <span className="px-2.5 py-0.5 rounded-full border border-indigo-500/35 bg-indigo-500/15 text-indigo-200 text-[11px] font-semibold">
                        Nov 16+ Guarded Era Active
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-slate-300/90 max-w-3xl">
                    {diag.headlineSummary}
                  </p>
                </div>
                {onOpenLedger && (
                  <button
                    type="button"
                    onClick={onOpenLedger}
                    className="self-start px-3 py-1.5 rounded-xl border border-slate-700 bg-slate-900 hover:bg-slate-800 text-xs font-semibold text-indigo-200 transition-colors cursor-pointer shrink-0"
                  >
                    Inspect All {history.length.toLocaleString()} Picks →
                  </button>
                )}
              </div>

              <div className="grid grid-cols-1 xl:grid-cols-12 gap-5">
                {/* Left 7 cols: Top Winners vs Top Leaks + Era Shift */}
                <div className="xl:col-span-7 space-y-4">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5">
                    {/* Working Edges */}
                    <div className="rounded-xl border border-emerald-500/25 bg-emerald-950/15 p-3.5 space-y-2.5">
                      <div className="flex items-center justify-between">
                        <span className="text-[11px] font-bold uppercase tracking-wider text-emerald-300">
                          What&apos;s Winning
                        </span>
                        <span className="text-[10px] font-mono text-emerald-300/80">
                          {diag.topWinners.length} positive segments
                        </span>
                      </div>
                      {diag.topWinners.length === 0 ? (
                        <p className="text-xs text-slate-400">
                          No multi-pick profitable segment in the current filter.
                        </p>
                      ) : (
                        <div className="space-y-2">
                          {diag.topWinners.map((seg) => (
                            <div
                              key={seg.key}
                              className="rounded-lg border border-emerald-500/20 bg-slate-950/70 px-3 py-2 space-y-1"
                            >
                              <div className="flex items-center justify-between gap-2">
                                <span className="text-xs font-semibold text-slate-100">{seg.label}</span>
                                <span className="font-mono text-xs font-bold text-emerald-400">
                                  {formatUnits(seg.profitUnits)}
                                </span>
                              </div>
                              <div className="flex items-center justify-between text-[11px] font-mono text-slate-400">
                                <span>{seg.recordText} · {formatPct(seg.winRate)} WR</span>
                                <span className="text-emerald-300">{formatSignedPct(seg.roiPct)} ROI</span>
                              </div>
                              {seg.guardrailNote && (
                                <div className="text-[10px] text-emerald-200/80">{seg.guardrailNote}</div>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>

                    {/* Top Leaks & Active Guardrails */}
                    <div className="rounded-xl border border-rose-500/25 bg-rose-950/10 p-3.5 space-y-2.5">
                      <div className="flex items-center justify-between">
                        <span className="text-[11px] font-bold uppercase tracking-wider text-rose-300">
                          Biggest Drags &amp; Fixes
                        </span>
                        <span className="text-[10px] font-mono text-rose-300/80">
                          {diag.topLeaks.length} leaking segments
                        </span>
                      </div>
                      {diag.topLeaks.length === 0 ? (
                        <p className="text-xs text-emerald-300/90">
                          No multi-pick leaking segments detected in this slice.
                        </p>
                      ) : (
                        <div className="space-y-2">
                          {diag.topLeaks.map((seg) => (
                            <div
                              key={seg.key}
                              className="rounded-lg border border-rose-500/20 bg-slate-950/70 px-3 py-2 space-y-1"
                            >
                              <div className="flex items-center justify-between gap-2">
                                <span className="text-xs font-semibold text-slate-100">{seg.label}</span>
                                <span className="font-mono text-xs font-bold text-rose-400">
                                  {formatUnits(seg.profitUnits)}
                                </span>
                              </div>
                              <div className="flex items-center justify-between text-[11px] font-mono text-slate-400">
                                <span>{seg.recordText} · {formatPct(seg.winRate)} WR</span>
                                <span className="text-rose-300">{formatSignedPct(seg.roiPct)} ROI</span>
                              </div>
                              {seg.guardrailNote && (
                                <div className="text-[10px] text-amber-200/90">{seg.guardrailNote}</div>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Regime Comparison: Pre-Guardrail Firehose vs Nov 16+ Curated */}
                  {diag.eraComparison && (
                    <div className="rounded-xl border border-slate-800 bg-slate-950/65 p-3.5 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                      <div className="space-y-1">
                        <div className="text-[11px] font-bold uppercase tracking-wider text-slate-400">
                          Volume vs. Selectivity Regime Shift
                        </div>
                        <div className="flex flex-wrap items-center gap-3 text-xs">
                          <span className="text-slate-300">
                            <strong className="text-slate-100">Nov 12–15 Firehose:</strong>{' '}
                            <span className="font-mono">
                              {diag.eraComparison.pre.wins}-{diag.eraComparison.pre.losses}
                              {diag.eraComparison.pre.pushes > 0 ? `-${diag.eraComparison.pre.pushes}` : ''}
                            </span>{' '}
                            <span className={`font-mono font-semibold ${diag.eraComparison.pre.profitUnits >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                              ({formatUnits(diag.eraComparison.pre.profitUnits)})
                            </span>
                          </span>
                          <span className="text-slate-600">→</span>
                          <span className="text-slate-300">
                            <strong className="text-indigo-200">Nov 16+ Guarded:</strong>{' '}
                            <span className="font-mono">
                              {diag.eraComparison.current.wins}-{diag.eraComparison.current.losses}
                              {diag.eraComparison.current.pushes > 0 ? `-${diag.eraComparison.current.pushes}` : ''}
                            </span>{' '}
                            <span className={`font-mono font-semibold ${diag.eraComparison.current.profitUnits >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                              ({formatUnits(diag.eraComparison.current.profitUnits)})
                            </span>
                          </span>
                        </div>
                      </div>
                      {onSelectWindow && (
                        <button
                          type="button"
                          onClick={() => onSelectWindow('ERA')}
                          className="px-3 py-1.5 rounded-lg border border-indigo-400/40 bg-indigo-500/15 hover:bg-indigo-500/25 text-xs font-semibold text-indigo-200 cursor-pointer shrink-0"
                        >
                          Focus Nov 16+ Era
                        </button>
                      )}
                    </div>
                  )}
                </div>

                {/* Right 5 cols: Market Side Split + Feed Accuracy Benchmark */}
                <div className="xl:col-span-5 space-y-4">
                  {diag.marketSideSplit.length > 0 && (
                    <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3.5 space-y-2.5">
                      <div className="flex items-center justify-between">
                        <span className="text-[11px] font-bold uppercase tracking-wider text-slate-400">
                          Market Side Split
                        </span>
                        <span className="text-[10px] font-mono text-amber-300">52.4% Break-Even</span>
                      </div>
                      <div className="grid grid-cols-2 gap-2">
                        {diag.marketSideSplit.map((m) => (
                          <div
                            key={m.key}
                            className="rounded-lg border border-slate-800/90 bg-slate-900/55 px-2.5 py-2 space-y-1"
                          >
                            <div className="flex items-center justify-between gap-1">
                              <span className="text-[11px] font-semibold text-slate-200 truncate">{m.label}</span>
                              <span className={`text-[11px] font-mono font-bold ${m.profitUnits >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                                {formatUnits(m.profitUnits)}
                              </span>
                            </div>
                            <div className="flex items-center justify-between text-[10px] font-mono text-slate-400">
                              <span>{m.recordText}</span>
                              <span className={m.winRate >= 52.4 ? 'text-emerald-300' : 'text-slate-300'}>
                                {formatPct(m.winRate)}
                              </span>
                            </div>
                            <div className="relative h-1.5 w-full rounded-full bg-slate-800 overflow-hidden" aria-hidden="true">
                              <div
                                className={`h-full rounded-full ${m.winRate >= 52.4 ? 'bg-emerald-500' : 'bg-rose-500'}`}
                                style={{ width: `${Math.max(4, Math.min(100, m.winRate))}%` }}
                              />
                              <div className="absolute top-0 bottom-0 w-0.5 bg-amber-300" style={{ left: '52.4%' }} />
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {diag.feedBenchmark.length > 0 && (
                    <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3.5 space-y-2.5">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-[11px] font-bold uppercase tracking-wider text-slate-400">
                          Rating Error Benchmark (MAE)
                        </span>
                        <span className="text-[10px] font-mono text-slate-400">
                          {diag.allGamesCount.toLocaleString()} NCAAM games
                        </span>
                      </div>
                      <div className="space-y-1.5">
                        {diag.feedBenchmark.map((f) => {
                          const maxMae = Math.max(...diag.feedBenchmark.map((x) => x.mae), 11.5);
                          const barPct = Math.max(20, Math.min(100, (f.mae / maxMae) * 100));
                          const isBestNonMarket = f.key === 'blended_fair';
                          const isWorst = f.key === 'haslametrics';
                          return (
                            <div key={f.key} className="space-y-0.5">
                              <div className="flex items-center justify-between text-[11px]">
                                <span className={`font-medium ${isBestNonMarket ? 'text-indigo-200' : 'text-slate-300'}`}>
                                  {f.label}
                                </span>
                                <span className="font-mono text-slate-300">
                                  {f.mae.toFixed(2)} pts
                                  {f.atsWinRate != null && (
                                    <span className="text-slate-500"> · {f.atsWinRate.toFixed(1)}% ATS</span>
                                  )}
                                </span>
                              </div>
                              <div className="h-1.5 w-full rounded-full bg-slate-800/90 overflow-hidden" aria-hidden="true">
                                <div
                                  className={`h-full rounded-full ${
                                    f.key === 'market'
                                      ? 'bg-sky-400'
                                      : isBestNonMarket
                                        ? 'bg-emerald-400'
                                        : isWorst
                                          ? 'bg-amber-400/85'
                                          : 'bg-indigo-400'
                                  }`}
                                  style={{ width: `${barPct}%` }}
                                />
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </article>
          )}

      {/* Card 1: Performance Over Time */}
      <article className="perf-chart-card p-5 sm:p-6 space-y-4" aria-labelledby="perf-trend-heading">
        <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-3">
          <div>
            <h3 id="perf-trend-heading" className="text-lg font-bold text-slate-100">
              Equity Curve, Drawdown &amp; Daily Results
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
              { id: 'cumulative', label: 'Equity Curve' },
              { id: 'daily', label: 'Day by Day' },
              { id: 'drawdown', label: 'Drawdown' },
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
                  onClick={(e) => {
                    setTrendTab(t.id);
                    e.currentTarget.scrollIntoView?.({ block: 'nearest', inline: 'nearest' });
                  }}
                  className="perf-tab"
                >
                  {t.label}
                </button>
              );
            })}
          </div>
        </div>

        {/* Cumulative Profit Curve (Dual-Color Zero-Split Gradient) */}
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
                      <linearGradient id="cumProfitSplitStroke" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#10b981" />
                        <stop offset={`${(analytics.zeroSplitOffset * 100).toFixed(2)}%`} stopColor="#10b981" />
                        <stop offset={`${(analytics.zeroSplitOffset * 100).toFixed(2)}%`} stopColor="#f43f5e" />
                        <stop offset="100%" stopColor="#f43f5e" />
                      </linearGradient>
                      <linearGradient id="cumProfitSplitFill" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#10b981" stopOpacity={0.34} />
                        <stop offset={`${(analytics.zeroSplitOffset * 100).toFixed(2)}%`} stopColor="#10b981" stopOpacity={0.04} />
                        <stop offset={`${(analytics.zeroSplitOffset * 100).toFixed(2)}%`} stopColor="#f43f5e" stopOpacity={0.08} />
                        <stop offset="100%" stopColor="#f43f5e" stopOpacity={0.34} />
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
                      stroke="url(#cumProfitSplitStroke)"
                      strokeWidth={2.5}
                      fill="url(#cumProfitSplitFill)"
                      dot={analytics.settledDays.length <= 15 ? { r: 3 } : false}
                      activeDot={{ r: 5 }}
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            )}
            <p className="text-[11px] text-slate-400">
              Assumes a flat 1-unit stake on every graded pick. Green shades profit above 0u; rose shades drawdown below 0u.
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

        {/* Underwater Drawdown Chart */}
        {trendTab === 'drawdown' && (
          <div
            id="trend-panel-drawdown"
            role="tabpanel"
            aria-labelledby="trend-tab-drawdown"
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
                      <linearGradient id="drawdownFill" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#f43f5e" stopOpacity={0.08} />
                        <stop offset="95%" stopColor="#f43f5e" stopOpacity={0.38} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
                    <XAxis dataKey="shortDay" stroke="#64748b" fontSize={11} tickLine={false} minTickGap={26} />
                    <YAxis
                      stroke="#64748b"
                      fontSize={11}
                      tickLine={false}
                      domain={['dataMin', 0]}
                      tickFormatter={(v) => `${v === 0 ? '0' : v}u`}
                      width={52}
                    />
                    <ReferenceLine y={0} stroke="#10b981" strokeDasharray="4 4" label={{ value: 'Peak High', fill: '#6ee7b7', fontSize: 10, position: 'insideBottomRight' }} />
                    <Tooltip
                      contentStyle={TOOLTIP_STYLE}
                      formatter={(value) => [formatUnits(value), 'Drawdown from Peak']}
                      labelFormatter={(_, payload) => {
                        const p = payload?.[0]?.payload;
                        if (!p) return '';
                        return `${p.day} • Peak ${formatUnits(p.peakUnits)} • Running ${formatUnits(p.cumulativeUnits)}`;
                      }}
                    />
                    <Area
                      type="monotone"
                      dataKey="drawdownUnits"
                      stroke="#fb7185"
                      strokeWidth={2}
                      fill="url(#drawdownFill)"
                      dot={false}
                      activeDot={{ r: 4, fill: '#fb7185' }}
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            )}
            <p className="text-[11px] text-slate-400">
              Shows how far cumulative profit dipped below its highest peak on each day. Shallow dips mean smoother bankroll growth.
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
        </>
      )}

      {showDiagnostics && (
        <>
      {/* Row 2: Bet Type Performance & Edge Calibration */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Card 2: Bet Type Performance */}
        <article className="perf-chart-card p-5 sm:p-6 space-y-4" aria-labelledby="bet-type-heading">
          <div className="flex items-start justify-between gap-2">
            <div>
              <h3 id="bet-type-heading" className="text-base font-bold text-slate-100">
                Performance by Bet Type
              </h3>
              <p className="text-xs text-slate-400">
                Return on 1-unit straight bets across Spreads, 1H Spreads, Over/Under Totals, 1H Totals, and Moneylines. Official Parlays are tracked separately below. Click a row to filter.
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
                  <caption className="sr-only">Straight bet performance breakdown by bet type</caption>
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
        <article className="perf-chart-card p-5 sm:p-6 space-y-4" aria-labelledby="edge-cal-heading">
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
                  <caption className="sr-only">Win rate and ROI by projected edge bucket</caption>
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

      {/* Row 3: Confidence Tiers & Recent Form (Full-Width 2-Column Layout) */}
      <article className="perf-chart-card p-5 sm:p-6 space-y-4" aria-labelledby="conf-form-heading">
        <div className="flex items-start justify-between gap-2">
          <div>
            <h3 id="conf-form-heading" className="text-base font-bold text-slate-100">
              Confidence Levels &amp; Recent Form
            </h3>
            <p className="text-xs text-slate-400">
              High (80+), Medium (50–79), and Low (&lt;50) pick scores alongside rolling momentum. Click a confidence box to filter.
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

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-start">
          {/* Left: Confidence Tiers + Last 14 Active Days Momentum */}
          <div className="space-y-4">
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

            {analytics.recentDailyBars.length > 0 && (
              <div className="space-y-1.5">
                <div className="flex items-center justify-between text-[11px]">
                  <span className="font-bold uppercase tracking-wider text-slate-400">
                    Last {Math.min(14, analytics.recentDailyBars.length)} Active Days
                  </span>
                  <span className="text-slate-500">Hover tile for record</span>
                </div>
                <div className="grid grid-cols-7 gap-1.5">
                  {analytics.recentDailyBars.slice(-14).map((d) => {
                    const isPos = d.profitUnits > 0;
                    const isNeg = d.profitUnits < 0;
                    const cls = isPos
                      ? 'border-emerald-500/40 bg-emerald-500/15 text-emerald-300'
                      : isNeg
                        ? 'border-rose-500/40 bg-rose-500/15 text-rose-300'
                        : 'border-slate-700 bg-slate-900/70 text-slate-300';
                    return (
                      <div
                        key={d.day}
                        title={`${d.day}: ${d.recordText} (${formatUnits(d.profitUnits)})`}
                        className={`rounded-lg border px-1.5 py-1.5 text-center transition hover:brightness-125 ${cls}`}
                      >
                        <div className="text-[9px] font-mono opacity-80">{d.shortDay}</div>
                        <div className="text-[11px] font-mono font-bold leading-tight">
                          {d.profitUnits > 0 ? `+${d.profitUnits.toFixed(1)}` : d.profitUnits.toFixed(1)}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </div>

          {/* Right: Recent Form Timeframe Breakdown */}
          <div className="space-y-2">
            <h4 id="recent-form-heading" className="text-xs font-bold uppercase tracking-wider text-slate-400">
              Recent Form by Window
            </h4>
            <div role="region" aria-labelledby="recent-form-heading" tabIndex={0} className="perf-table-wrapper">
              <table className="perf-sticky-table w-full text-left border-collapse text-xs">
                <caption className="sr-only">Recent model performance across calendar timeframes</caption>
                <thead>
                  <tr className="border-b border-slate-800 text-slate-400">
                    <th scope="col" className="py-2 pr-3 font-medium">Timeframe</th>
                    <th scope="col" className="py-2 px-3 font-medium">Record</th>
                    <th scope="col" className="py-2 px-3 font-medium text-right">Win %</th>
                    <th scope="col" className="py-2 px-3 font-medium text-right">Profit</th>
                    <th scope="col" className="py-2 pl-3 font-medium text-right">ROI</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/70">
                  {analytics.recentWindows.map((w) => (
                    <tr key={w.label} className="hover:bg-slate-900/50">
                      <th scope="row" className="py-2 pr-3 font-medium text-slate-200">{w.label}</th>
                      <td className="py-2 px-3 font-mono text-slate-300">{w.recordText}</td>
                      <td className={`py-2 px-3 text-right font-mono font-semibold ${w.winRate >= 52.4 ? 'text-emerald-400' : 'text-slate-300'}`}>
                        {w.decided > 0 ? formatPct(w.winRate) : '—'}
                      </td>
                      <td className={`py-2 px-3 text-right font-mono font-semibold ${w.profitUnits >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                        {w.settled > 0 ? formatUnits(w.profitUnits) : '—'}
                      </td>
                      <td className={`py-2 pl-3 text-right font-mono font-semibold ${w.roiPct >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                        {w.settled > 0 ? formatSignedPct(w.roiPct) : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </article>

      {/* Row 3.5: NCAAM Model Insights & Sweet Spots */}
      {(selectedSport === 'NCAAM' || selectedSport === 'ALL') && (() => {
        const insights = analytics.ncaamEdgeInsights;
        const toneCls = {
          emerald: 'bg-emerald-500/15 border-emerald-500/35 text-emerald-300',
          sky: 'bg-sky-500/15 border-sky-500/35 text-sky-300',
          amber: 'bg-amber-500/15 border-amber-500/35 text-amber-300',
          rose: 'bg-rose-500/15 border-rose-500/35 text-rose-300',
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
                  {item.settled > 0 && (
                    <div className="relative h-1.5 w-full rounded-full bg-slate-800/90 overflow-hidden" aria-hidden="true">
                      <div
                        className={`h-full rounded-full ${item.winRate >= 52.4 ? 'bg-emerald-500' : 'bg-rose-500'}`}
                        style={{ width: `${Math.max(4, Math.min(100, item.winRate))}%` }}
                      />
                      <div className="absolute top-0 bottom-0 w-0.5 bg-amber-300/90" style={{ left: '52.4%' }} />
                    </div>
                  )}
                  <div className="text-[10px] text-slate-400 font-mono">{item.benchmark}</div>
                </div>
              ))}
            </div>
          </div>
        );

        return (
          <article className="perf-chart-card p-5 sm:p-6 space-y-4" aria-labelledby="ncaam-insights-heading">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <h3 id="ncaam-insights-heading" className="text-base font-bold text-slate-100">
                  NCAAM Model Insights &amp; Sweet Spots
                </h3>
                <p className="text-xs text-slate-400">
                  Live graded NCAAM picks ({insights.sampleCount.toLocaleString()} settled in current filter) broken down across role edges, active Early-Season &amp; Smart Risk (0.5u) guardrails, and Sharp/RLM multipliers.
                </p>
              </div>
              <span
                className="px-2.5 py-1 rounded-full border border-indigo-500/35 bg-indigo-500/15 text-indigo-200 text-xs font-semibold shrink-0"
                title={modelLearning?.updated_at ? `Last adaptive learning sync: ${modelLearning.updated_at}` : undefined}
              >
                {modelLearning?.status === 'active'
                  ? `Adaptive Learning · ${Number(modelLearning.total_graded || 0).toLocaleString()} graded`
                  : 'NCAAM Strategy Intel'}
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

      {/* When to Bet · Closing Line Check (shown when graded or open rows have timing tags) */}
      {analytics.timingBuckets.some((b) => b.settled > 0 || b.openCount > 0) && (
        <article className="perf-chart-card p-5 sm:p-6 space-y-4" aria-labelledby="timing-clv-heading">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <h3 id="timing-clv-heading" className="text-base font-bold text-slate-100">
                When to Bet · Closing Line Check
              </h3>
              <p className="text-xs text-slate-400">
                Tracks whether &ldquo;Bet Now&rdquo; calls beat the final closing line and shows open &amp; settled timing signals.
              </p>
            </div>
            <span className="px-2.5 py-1 rounded-full border border-emerald-500/35 bg-emerald-500/15 text-emerald-200 text-xs font-semibold">
              Timing Validation
            </span>
          </div>

          <div role="region" aria-labelledby="timing-clv-heading" tabIndex={0} className="perf-table-wrapper">
            <table className="perf-sticky-table w-full text-left border-collapse text-xs">
              <caption className="sr-only">Performance and closing line value by When to Bet timing signal</caption>
              <thead>
                <tr className="border-b border-slate-800 text-slate-400">
                  <th scope="col" className="py-2 pr-3 font-medium">Timing Signal</th>
                  <th scope="col" className="py-2 px-3 font-medium text-right">Settled</th>
                  <th scope="col" className="py-2 px-3 font-medium text-right">Open</th>
                  <th scope="col" className="py-2 px-3 font-medium">Record</th>
                  <th scope="col" className="py-2 px-3 font-medium text-right">Win %</th>
                  <th scope="col" className="py-2 px-3 font-medium text-right">ROI</th>
                  <th scope="col" className="py-2 px-3 font-medium text-right">Avg Line Beat</th>
                  <th scope="col" className="py-2 pl-3 font-medium text-right">Beat Close %</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/70">
                {analytics.timingBuckets
                  .filter((b) => b.settled > 0 || b.openCount > 0)
                  .map((b) => {
                    const clvCls =
                      b.avgClv === null
                        ? 'text-slate-400'
                        : b.avgClv > 0
                          ? 'text-emerald-300'
                          : b.avgClv === 0
                            ? 'text-slate-200'
                            : 'text-rose-300';
                    const toneCls =
                      b.action === 'BET_NOW'
                        ? 'bg-emerald-500/15 border-emerald-400/45 text-emerald-200'
                        : b.action === 'WAIT_LINEUPS'
                          ? 'bg-amber-500/15 border-amber-400/45 text-amber-200'
                          : 'bg-sky-500/15 border-sky-400/45 text-sky-200';
                    return (
                      <tr key={b.action} className="hover:bg-slate-900/50">
                        <th scope="row" className="py-2 pr-3 font-medium">
                          <span className={`inline-flex items-center px-2 py-0.5 rounded-full border text-[11px] font-semibold ${toneCls}`}>
                            {b.label}
                          </span>
                        </th>
                        <td className="py-2 px-3 text-right text-slate-300">{b.settled}</td>
                        <td className="py-2 px-3 text-right font-mono text-sky-300">{b.openCount || 0}</td>
                        <td className="py-2 px-3 font-mono text-slate-200">{b.settled > 0 ? b.recordText : 'Pending'}</td>
                        <td className={`py-2 px-3 text-right font-mono font-semibold ${b.winRate >= 52.4 ? 'text-emerald-300' : 'text-slate-200'}`}>
                          {b.decided > 0 ? formatPct(b.winRate) : '—'}
                        </td>
                        <td className={`py-2 px-3 text-right font-mono font-semibold ${b.roiPct >= 0 ? 'text-emerald-300' : 'text-rose-300'}`}>
                          {b.settled > 0 ? formatSignedPct(b.roiPct) : '—'}
                        </td>
                        <td className={`py-2 px-3 text-right font-mono font-semibold ${clvCls}`}>
                          {b.avgClv !== null ? `${b.avgClv > 0 ? '+' : ''}${b.avgClv.toFixed(2)}` : '—'}
                        </td>
                        <td className="py-2 pl-3 text-right font-mono text-slate-200">
                          {b.posClvRate !== null ? `${b.posClvRate}%` : '—'}
                        </td>
                      </tr>
                    );
                  })}
              </tbody>
            </table>
          </div>
        </article>
      )}

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
        const firstHalfPct = Math.round(Number(params.first_half_share ?? 0.47) * 100);
        const secondHalfPct = 100 - firstHalfPct;
        const foulBoost = Number(params.late_foul_boost_pts ?? 4.5).toFixed(1);
        const blowoutDrag = Number(params.late_blowout_drag_pts ?? 3.0).toFixed(1);
        const otExtra = Number(params.ot_extra_pts ?? 14.5).toFixed(1);
        const calUpdatedLabel = cal.updated_at
          ? new Date(cal.updated_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'America/New_York' })
          : null;
        const bins = Array.isArray(cal.bins) ? cal.bins : [];

        return (
          <article className="perf-chart-card p-5 sm:p-6 space-y-4" aria-labelledby="live-cal-heading">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h3 id="live-cal-heading" className="text-base font-bold text-slate-100">
                  Live Win-Chance Accuracy
                </h3>
                <p className="text-xs text-slate-400">
                  Checks whether our live in-game win % and CBB pacing curves match how games actually finish.
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
                <div className="text-[11px] font-mono text-slate-300">
                  {firstHalfPct}%/{secondHalfPct}% 1H/2H · +{foulBoost} foul · -{blowoutDrag} blowout · +{otExtra} OT
                </div>
                <div className="text-[11px] text-slate-400">
                  {cal.active
                    ? `Auto-tuned from finished live games${calUpdatedLabel ? ` (${calUpdatedLabel})` : ''}`
                    : 'Using CBB 1H/2H & late-game defaults'}
                </div>
              </div>
            </div>

            {bins.some((b) => Number(b.count || 0) > 0) ? (
              <div className="space-y-4">
                <div className="h-[210px] w-full rounded-xl border border-slate-800/80 bg-slate-950/55 p-3">
                  <ResponsiveContainer width="100%" height="100%">
                    <ComposedChart
                      data={bins
                        .filter((b) => Number(b.count || 0) > 0)
                        .map((b) => ({
                          label: b.label,
                          count: b.count || 0,
                          predicted: b.avg_predicted_pct != null ? Number(Number(b.avg_predicted_pct).toFixed(1)) : null,
                          actual: b.actual_win_pct != null ? Number(Number(b.actual_win_pct).toFixed(1)) : null,
                        }))}
                      margin={{ top: 8, right: 16, left: 0, bottom: 0 }}
                    >
                      <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
                      <XAxis dataKey="label" stroke="#64748b" fontSize={11} tickLine={false} />
                      <YAxis domain={[0, 100]} stroke="#64748b" fontSize={11} tickLine={false} tickFormatter={(v) => `${v}%`} width={40} />
                      <Tooltip
                        contentStyle={TOOLTIP_STYLE}
                        formatter={(val, name) => [`${val}%`, name === 'actual' ? 'Actually Won' : 'Model Predicted']}
                        labelFormatter={(lbl, payload) => {
                          const cnt = payload?.[0]?.payload?.count;
                          return `${lbl}${cnt ? ` (${cnt} live checks)` : ''}`;
                        }}
                      />
                      <Bar dataKey="actual" fill="#10b981" fillOpacity={0.75} radius={[4, 4, 0, 0]} maxBarSize={36} />
                      <Line type="monotone" dataKey="predicted" stroke="#fbbf24" strokeWidth={2.5} dot={{ r: 3.5, fill: '#fbbf24' }} />
                    </ComposedChart>
                  </ResponsiveContainer>
                </div>

                <div role="region" aria-labelledby="live-cal-heading" tabIndex={0} className="perf-table-wrapper">
                <table className="perf-sticky-table w-full text-left border-collapse text-xs">
                  <caption className="sr-only">Live win probability calibration bins vs actual outcomes</caption>
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
              </div>
            ) : (
              <div className="rounded-xl border border-slate-800/80 bg-slate-950/50 px-4 py-3 text-xs text-slate-400">
                Live checks are saved automatically whenever tracked college basketball games are in progress. Once {minReq}+ finish grading, this table will compare predicted live win % against final outcomes.
              </div>
            )}
          </article>
        );
      })()}
        </>
      )}
    </section>
  );
};

export default ModelPerformanceAnalytics;
