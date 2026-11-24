import React, { useEffect, useMemo, useRef, useState } from 'react';
import api from '../api/axios';
import {
  RefreshCw,
  ArrowUpDown,
  ChevronUp,
  ChevronDown,
  HelpCircle,
  Search,
  Filter,
  RotateCcw,
  TrendingUp,
  Target,
  ShieldCheck,
  Activity,
  Flame,
  Sparkles,
  Layers,
} from 'lucide-react';
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  ReferenceLine,
  Cell,
} from 'recharts';
import ModelPerformanceAnalytics from '../components/ModelPerformanceAnalytics';
import ParlayPerformanceSection from '../components/ParlayPerformanceSection';
import {
  normalizeOutcome,
  isGradedOutcome,
  toEtDay,
  getPerformanceDay,
  getNumericConfidence,
  getConfidenceBucket,
  getConfidenceTierWeightUnits,
  getRawOutcome,
  getEffectivePrice,
  roiPerUnit,
  normalizeMarketType,
  formatMarketLabel,
  formatMatchup,
  formatPickLabel,
  formatLineAndOdds,
  getNumericEdge,
  dedupeDayRowsByEvent,
  hasTop6RiskFlag,
  selectTopPicksPerDay,
  computeRecordStats,
  normalizeSport,
  computeRowProfitUnits,
  computeRankBreakdown,
  getRowSeason,
} from '../utils/modelPerformance';
import { computeParlayAnalytics } from '../utils/parlayPerformance';
import { getCurrentNcaamSeasonShort, formatSeasonLabel } from '../utils/ncaamSeason';
import { getOutcomeOutlineClasses } from '../components/today/todayHelpers';

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

const formatSignedPct = (p, digits = 1) => {
  const val = Number(p || 0);
  if (Math.abs(val) < 0.05) return '0.0%';
  return `${val > 0 ? '+' : ''}${val.toFixed(digits)}%`;
};

const formatOutcomeBadge = (rawOutcome) => {
  const norm = normalizeOutcome(rawOutcome);
  if (norm === 'WON') return { key: 'WON', label: 'Won', cls: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30' };
  if (norm === 'LOST') return { key: 'LOST', label: 'Lost', cls: 'bg-rose-500/15 text-rose-300 border-rose-500/30' };
  if (norm === 'PUSH') return { key: 'PUSH', label: 'Push', cls: 'bg-slate-600/25 text-slate-300 border-slate-500/40' };
  if (norm === 'VOID') return { key: 'VOID', label: 'Void', cls: 'bg-amber-500/15 text-amber-300 border-amber-500/30' };
  return { key: 'PENDING', label: 'Pending', cls: 'bg-sky-500/15 text-sky-300 border-sky-500/30' };
};

const etDaysAgoIso = (days) => {
  const todayEt = toEtDay(new Date()) || new Date().toISOString().slice(0, 10);
  const dt = new Date(`${todayEt}T12:00:00Z`);
  dt.setUTCDate(dt.getUTCDate() - days);
  return dt.toISOString().slice(0, 10);
};

export default function Picks() {
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(null);
  const [isGrading, setIsGrading] = useState(false);
  const [gradeMessage, setGradeMessage] = useState(null);
  const [yesterdayReco, setYesterdayReco] = useState(null);
  const [liveCalibration, setLiveCalibration] = useState(null);
  const [parlayReport, setParlayReport] = useState(null);
  const [modelLearning, setModelLearning] = useState(null);
  const [lastRefreshedAt, setLastRefreshedAt] = useState(null);

  const defaultNcaamSeason = useMemo(() => getCurrentNcaamSeasonShort(), []);

  // Filters & interactive UI state (default to current NCAAM 2026-2027 season)
  const [selectedSport, setSelectedSport] = useState('NCAAM');
  const [selectedSeason, setSelectedSeason] = useState(() => getCurrentNcaamSeasonShort());
  const [windowFilter, setWindowFilter] = useState('ALL');
  const [marketFilter, setMarketFilter] = useState('ALL');
  const [confFilter, setConfFilter] = useState('ALL');
  const [historyScope, setHistoryScope] = useState('top6');
  const [outcomeFilter, setOutcomeFilter] = useState('ALL');
  const [searchQuery, setSearchQuery] = useState('');
  const [historyRowLimit, setHistoryRowLimit] = useState(100);
  const [showExplainer, setShowExplainer] = useState(false);
  const [activeSection, setActiveSection] = useState('all'); // 'all' | 'core' | 'parlays'
  const focusTabRefs = useRef({});
  const [sortConfig, setSortConfig] = useState({ key: 'created_at', direction: 'desc' });

  const load = async () => {
    setLoading(true);
    setErr(null);
    const cacheHeaders = { 'Cache-Control': 'no-cache' };
    const ts = Date.now();
    try {
      const [res, ysRes, liveCalRes, parlayRes, learningRes] = await Promise.all([
        api.get('/api/research/history', {
          params: { limit: 20000, lookback_days: 400, _t: ts },
          headers: cacheHeaders,
        }),
        api
          .get('/api/ncaam/recommended-slate/yesterday', {
            params: { _t: ts },
            headers: cacheHeaders,
          })
          .catch(() => ({ data: null })),
        api
          .get('/api/ncaam/live-calibration', {
            params: { _t: ts },
            headers: cacheHeaders,
          })
          .catch(() => ({ data: null })),
        api
          .get('/api/ncaam/parlays/performance-report', {
            params: { days: 400, _t: ts },
            headers: cacheHeaders,
          })
          .catch(() => ({ data: null })),
        api
          .get('/api/ncaam/model-learning', {
            params: { _t: ts },
            headers: cacheHeaders,
          })
          .catch(() => ({ data: null })),
      ]);

      let rows = res.data || [];
      setYesterdayReco(ysRes?.data || null);
      setLiveCalibration(liveCalRes?.data || null);
      setParlayReport(parlayRes?.data || null);
      setModelLearning(learningRes?.data || null);

      if (!(Array.isArray(rows) && rows.length > 0)) {
        const n = await api
          .get('/api/ncaam/history', { params: { limit: 2000, _t: ts }, headers: cacheHeaders })
          .catch(() => ({ data: [] }));
        rows = n.data || [];
      }

      // Auto-grade once per 15-minute cooldown if yesterday or finished today (>3.5h since tip) still has open picks
      try {
        const todayEtStr = toEtDay(new Date());
        const yesterdayEtStr = toEtDay(new Date(Date.now() - 86400000));
        const nowMs = Date.now();
        const needsGrade = (rows || []).some((h) => {
          const norm = normalizeOutcome(getRawOutcome(h));
          if (norm !== null) return false; // already WON/LOST/PUSH/VOID
          const day = getPerformanceDay(h);
          if (day === yesterdayEtStr) return true;
          if (day === todayEtStr && h.start_time) {
            const stMs = Date.parse(h.start_time);
            if (Number.isFinite(stMs) && nowMs - stMs > 3.5 * 3600 * 1000) return true;
          }
          return false;
        });

        const cooldownKey = 'grade_auto_attempt_ts';
        const lastAttemptMs = Number(sessionStorage.getItem(cooldownKey) || 0);
        if (needsGrade && (!lastAttemptMs || nowMs - lastAttemptMs > 15 * 60 * 1000)) {
          sessionStorage.setItem(cooldownKey, String(nowMs));
          await api.post('/api/research/grade', null, {
            params: { backfill_pending: true, backfill_days: 7, max_grade_rows: 1000 },
          });
          const ts2 = Date.now();
          const [res2, ys2, liveCal2, parlay2] = await Promise.all([
            api.get('/api/research/history', {
              params: { limit: 20000, lookback_days: 400, _t: ts2 },
              headers: cacheHeaders,
            }),
            api
              .get('/api/ncaam/recommended-slate/yesterday', {
                params: { _t: ts2 },
                headers: cacheHeaders,
              })
              .catch(() => ({ data: ysRes?.data || null })),
            api
              .get('/api/ncaam/live-calibration', {
                params: { _t: ts2 },
                headers: cacheHeaders,
              })
              .catch(() => ({ data: liveCalRes?.data || null })),
            api
              .get('/api/ncaam/parlays/performance-report', {
                params: { days: 400, _t: ts2 },
                headers: cacheHeaders,
              })
              .catch(() => ({ data: parlayRes?.data || null })),
          ]);
          rows = res2.data || rows;
          if (ys2?.data) setYesterdayReco(ys2.data);
          if (liveCal2?.data) setLiveCalibration(liveCal2.data);
          if (parlay2?.data) setParlayReport(parlay2.data);
        }
      } catch (e) {
        // non-blocking
      }

      setHistory(rows);
      setLastRefreshedAt(new Date());
    } catch (e) {
      if (e?.response?.status === 403) {
        const pass = prompt('Authentication failed. Please enter the Basement Password:');
        if (pass) {
          try {
            localStorage.setItem('basement_password', pass);
          } catch (storageErr) {
            // ignore storage errors
          }
          window.location.reload();
          return;
        }
      }
      setErr(e?.response?.data?.detail || e?.response?.data?.message || e?.message || 'Failed to load model performance');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const gradeNow = async () => {
    try {
      setIsGrading(true);
      setGradeMessage(null);
      setErr(null);
      try {
        sessionStorage.setItem('grade_auto_attempt_ts', String(Date.now()));
      } catch {
        // ignore storage errors
      }
      const res = await api.post('/api/research/grade', null, {
        params: {
          backfill_pending: true,
          backfill_days: 30,
          max_grade_rows: 5000,
        },
      });
      const data = res?.data || {};
      const gradedCount = Number(data.graded ?? data.graded_predictions ?? data.predictions_graded ?? 0);
      const checkedGames = Number(data.scores_ingested ?? data.ingested_games ?? data.games_checked ?? 0);
      setGradeMessage(
        `Checked ${checkedGames.toLocaleString()} final game scores and updated ${gradedCount.toLocaleString()} pending pick(s).`
      );
      await load();
    } catch (e) {
      setErr(e?.response?.data?.detail || e?.message || 'Could not update past pick results right now.');
    } finally {
      setIsGrading(false);
    }
  };

  // Canonical recommended rows (keeps all actionable bets across every sport)
  const recommendedHistory = useMemo(() => {
    const base = Array.isArray(history) ? history : [];
    const usable = base.filter((h) => {
      if (!h) return false;
      const mt = String(h.market_type || '').toUpperCase();
      if (mt === 'AUTO') return false;
      const pk = formatPickLabel(h);
      const ev = getNumericEdge(h);
      return Boolean((h.id || h.prediction_id || h.event_id) && (pk !== '—' || (ev !== null && ev >= 0.02)));
    });
    return usable.length > 0 ? usable : base;
  }, [history]);

  // Dynamic sport options with counts
  const availableSports = useMemo(() => {
    const counts = {};
    for (const h of recommendedHistory) {
      const sp = normalizeSport(h);
      counts[sp] = (counts[sp] || 0) + 1;
    }
    if (selectedSport !== 'ALL' && counts[selectedSport] === undefined) {
      counts[selectedSport] = 0;
    }
    return Object.entries(counts)
      .map(([sport, count]) => ({ sport, count }))
      .sort((a, b) => b.count - a.count);
  }, [recommendedHistory, selectedSport]);

  // Dynamic season options scoped to the selected sport (descending, newest first)
  const availableSeasons = useMemo(() => {
    const counts = {};
    for (const h of recommendedHistory) {
      if (selectedSport !== 'ALL' && normalizeSport(h) !== selectedSport) continue;
      const se = getRowSeason(h);
      if (!se) continue;
      counts[se] = (counts[se] || 0) + 1;
    }
    if (selectedSport === 'NCAAM' && counts[defaultNcaamSeason] === undefined) {
      counts[defaultNcaamSeason] = 0;
    }
    return Object.entries(counts)
      .map(([season, count]) => ({ season, count }))
      .sort((a, b) => b.season.localeCompare(a.season));
  }, [recommendedHistory, selectedSport, defaultNcaamSeason]);

  const handleSportChange = (nextSport) => {
    setSelectedSport(nextSport);
    if (nextSport === 'ALL') {
      setSelectedSeason('ALL');
      return;
    }
    if (selectedSeason === 'ALL') return;
    const sportSeasons = Array.from(
      new Set(
        recommendedHistory
          .filter((h) => normalizeSport(h) === nextSport)
          .map((h) => getRowSeason(h))
          .filter(Boolean)
      )
    ).sort((a, b) => b.localeCompare(a));
    if (nextSport === 'NCAAM' && !sportSeasons.includes(defaultNcaamSeason)) {
      sportSeasons.unshift(defaultNcaamSeason);
    }
    if (sportSeasons.length > 0 && !sportSeasons.includes(selectedSeason)) {
      setSelectedSeason(sportSeasons[0]);
    }
  };

  // Dynamic bet type options within active sport & season
  const availableMarkets = useMemo(() => {
    const set = new Set();
    for (const h of recommendedHistory) {
      if (selectedSport !== 'ALL' && normalizeSport(h) !== selectedSport) continue;
      if (selectedSeason !== 'ALL' && getRowSeason(h) !== selectedSeason) continue;
      set.add(normalizeMarketType(h));
    }
    return Array.from(set).sort();
  }, [recommendedHistory, selectedSport, selectedSeason]);

  useEffect(() => {
    if (marketFilter !== 'ALL' && availableMarkets.length > 0 && !availableMarkets.includes(marketFilter)) {
      setMarketFilter('ALL');
    }
  }, [availableMarkets, marketFilter]);

  // 1. Filter by Time Window across all sports first (keeps "By Sport" comparison aligned)
  const windowAllHistory = useMemo(() => {
    const cutoff =
      windowFilter === '90'
        ? etDaysAgoIso(90)
        : windowFilter === '30'
          ? etDaysAgoIso(30)
          : windowFilter === '7'
            ? etDaysAgoIso(7)
            : null;

    if (!cutoff) return recommendedHistory;
    return recommendedHistory.filter((h) => {
      const day = getPerformanceDay(h);
      return Boolean(day && day >= cutoff);
    });
  }, [recommendedHistory, windowFilter]);

  // 2. Filter by selected Sport + Season (still before Top 6, Bet Type, and Confidence)
  const sportSeasonWindowHistory = useMemo(() => {
    return windowAllHistory.filter((h) => {
      if (selectedSport !== 'ALL' && normalizeSport(h) !== selectedSport) return false;
      if (selectedSeason !== 'ALL' && getRowSeason(h) !== selectedSeason) return false;
      return true;
    });
  }, [windowAllHistory, selectedSport, selectedSeason]);

  const matchesConfFilter = (row, filterKey) => {
    if (!filterKey || filterKey === 'ALL') return true;
    const tier = String(getConfidenceBucket(row) || '').toUpperCase();
    return tier === filterKey;
  };

  const matchesMarketFilter = (row, mktKey) => {
    if (!mktKey || mktKey === 'ALL') return true;
    return normalizeMarketType(row) === mktKey;
  };

  // 3. Apply Pick Scope (All Recommended vs Top 6 / Day) BEFORE Bet Type & Confidence
  // so Spread + Over / Under + ML === All and High + Medium + Low === All under Top 6 / Day.
  const scopeBaseAllMarketsHistory = useMemo(() => {
    if (historyScope === 'top6') {
      return selectTopPicksPerDay(sportSeasonWindowHistory, 6);
    }
    return sportSeasonWindowHistory;
  }, [historyScope, sportSeasonWindowHistory]);

  const scopePreConfHistory = useMemo(() => {
    if (marketFilter === 'ALL') return scopeBaseAllMarketsHistory;
    return scopeBaseAllMarketsHistory.filter((h) => matchesMarketFilter(h, marketFilter));
  }, [scopeBaseAllMarketsHistory, marketFilter]);

  const scopePreMarketHistory = useMemo(() => {
    if (confFilter === 'ALL') return scopeBaseAllMarketsHistory;
    return scopeBaseAllMarketsHistory.filter((h) => matchesConfFilter(h, confFilter));
  }, [scopeBaseAllMarketsHistory, confFilter]);

  const scopedHistory = useMemo(() => {
    if (confFilter === 'ALL') return scopePreConfHistory;
    return scopePreConfHistory.filter((h) => matchesConfFilter(h, confFilter));
  }, [scopePreConfHistory, confFilter]);

  // Precompute true daily rank (#1-#6 per day across all bet types & confidence levels)
  const rankByRowKey = useMemo(() => {
    const byDay = {};
    for (const h of sportSeasonWindowHistory) {
      const day = getPerformanceDay(h) || 'unknown';
      if (!byDay[day]) byDay[day] = [];
      byDay[day].push(h);
    }
    const map = new WeakMap();
    for (const day of Object.keys(byDay)) {
      const uniqueDay = dedupeDayRowsByEvent(byDay[day]);
      uniqueDay.forEach((row, idx) => {
        map.set(row, idx + 1);
      });
    }
    return map;
  }, [sportSeasonWindowHistory]);

  const rankBreakdown = useMemo(
    () =>
      computeRankBreakdown(
        sportSeasonWindowHistory,
        6,
        marketFilter === 'ALL' && confFilter === 'ALL'
          ? null
          : (row) => matchesMarketFilter(row, marketFilter) && matchesConfFilter(row, confFilter)
      ),
    [sportSeasonWindowHistory, marketFilter, confFilter]
  );

  // Overall KPI stats (settled + pending + void + profit)
  const scopedStats = useMemo(() => computeRecordStats(scopedHistory), [scopedHistory]);

  // Confidence-weighted staking comparison & quick takeaway metrics
  const weightedProfitUnits = useMemo(() => {
    let sum = 0;
    for (const h of scopedHistory) {
      const out = getRawOutcome(h);
      if (!isGradedOutcome(out)) continue;
      sum += roiPerUnit(out, getEffectivePrice(h)) * getConfidenceTierWeightUnits(h);
    }
    return sum;
  }, [scopedHistory]);

  const scopeComparison = useMemo(() => {
    const top6AllMarkets = selectTopPicksPerDay(sportSeasonWindowHistory, 6);
    const applySubFilters = (rows) =>
      rows.filter((h) => matchesMarketFilter(h, marketFilter) && matchesConfFilter(h, confFilter));
    return {
      allStats: computeRecordStats(applySubFilters(sportSeasonWindowHistory)),
      top6Stats: computeRecordStats(applySubFilters(top6AllMarkets)),
    };
  }, [sportSeasonWindowHistory, marketFilter, confFilter]);

  const bestMarketTakeaway = useMemo(() => {
    const map = {};
    for (const h of scopePreMarketHistory) {
      const out = getRawOutcome(h);
      if (!isGradedOutcome(out)) continue;
      const mKey = normalizeMarketType(h);
      if (!map[mKey]) map[mKey] = [];
      map[mKey].push(h);
    }
    const entries = Object.entries(map)
      .map(([marketKey, rows]) => ({ marketKey, label: formatMarketLabel(marketKey), ...computeRecordStats(rows) }))
      .filter((m) => m.settled > 0);
    if (entries.length === 0) return null;
    const sorted = entries.slice().sort((a, b) => b.roiPct - a.roiPct);
    const best = sorted[0];
    const worst = sorted.length > 1 ? sorted[sorted.length - 1] : null;
    return { best, worst };
  }, [scopePreMarketHistory]);

  const confTakeaway = useMemo(() => {
    const highRows = scopePreConfHistory.filter((h) => matchesConfFilter(h, 'HIGH'));
    const medRows = scopePreConfHistory.filter((h) => matchesConfFilter(h, 'MEDIUM'));
    const lowRows = scopePreConfHistory.filter((h) => matchesConfFilter(h, 'LOW'));
    const candidates = [
      { key: 'HIGH', label: 'High (80+)', ...computeRecordStats(highRows) },
      { key: 'MEDIUM', label: 'Medium (50–79)', ...computeRecordStats(medRows) },
      { key: 'LOW', label: 'Low (<50)', ...computeRecordStats(lowRows) },
    ];
    const withSettled = candidates.filter((c) => c.settled > 0).sort((a, b) => b.roiPct - a.roiPct);
    return {
      high: candidates[0],
      med: candidates[1],
      low: candidates[2],
      best: withSettled[0] || candidates[0],
    };
  }, [scopePreConfHistory]);

  const clvStats = useMemo(() => {
    let sum = 0;
    let count = 0;
    let beatCount = 0;
    for (const h of scopedHistory) {
      const v = parseFloat(h?.clv_points);
      if (Number.isFinite(v)) {
        sum += v;
        count += 1;
        if (v > 0) beatCount += 1;
      }
    }
    return { count, beatCount, avg: count > 0 ? sum / count : null };
  }, [scopedHistory]);

  const riskTierBreakdown = useMemo(() => {
    const coreRows = [];
    const smartRiskRows = [];
    for (const h of scopedHistory) {
      const isSmart = Boolean(h?.is_smart_risk) || String(h?.risk_tier || '').toUpperCase() === 'SMART_RISK';
      if (isSmart) smartRiskRows.push(h);
      else coreRows.push(h);
    }
    const summarizeClv = (rows) => {
      let sum = 0;
      let count = 0;
      for (const r of rows) {
        const v = parseFloat(r?.clv_points);
        if (Number.isFinite(v)) {
          sum += v;
          count += 1;
        }
      }
      return { count, avg: count > 0 ? sum / count : null };
    };
    return {
      core: { ...computeRecordStats(coreRows), clv: summarizeClv(coreRows) },
      smartRisk: { ...computeRecordStats(smartRiskRows), clv: summarizeClv(smartRiskRows) },
    };
  }, [scopedHistory]);

  const parlayAnalytics = useMemo(
    () => computeParlayAnalytics(parlayReport, { selectedSeason, windowFilter }),
    [parlayReport, selectedSeason, windowFilter]
  );

  const executiveMetrics = useMemo(() => {
    const graded = (scopedHistory || [])
      .filter((h) => {
        const n = normalizeOutcome(getRawOutcome(h));
        return n === 'WON' || n === 'LOST' || n === 'PUSH';
      })
      .slice()
      .sort((a, b) => {
        const da = getPerformanceDay(a) || '';
        const db = getPerformanceDay(b) || '';
        if (da !== db) return da.localeCompare(db);
        return String(a?.start_time || a?.analyzed_at || '').localeCompare(
          String(b?.start_time || b?.analyzed_at || '')
        );
      });

    let running = 0;
    let peak = 0;
    let maxDrawdown = 0;
    let grossWon = 0;
    let grossLost = 0;
    const dayTotals = new Map();

    for (const row of graded) {
      const pnl = computeRowProfitUnits(row);
      running += pnl;
      if (running > peak) peak = running;
      const dd = peak - running;
      if (dd > maxDrawdown) maxDrawdown = dd;
      if (pnl > 0) grossWon += pnl;
      else if (pnl < 0) grossLost += Math.abs(pnl);

      const day = getPerformanceDay(row);
      if (day) {
        dayTotals.set(day, (dayTotals.get(day) || 0) + pnl);
      }
    }

    // Current win/loss streak (ignoring pushes)
    let streakType = null;
    let streakCount = 0;
    for (let i = graded.length - 1; i >= 0; i -= 1) {
      const n = normalizeOutcome(getRawOutcome(graded[i]));
      if (n !== 'WON' && n !== 'LOST') continue;
      if (!streakType) {
        streakType = n === 'WON' ? 'W' : 'L';
        streakCount = 1;
      } else if ((n === 'WON' && streakType === 'W') || (n === 'LOST' && streakType === 'L')) {
        streakCount += 1;
      } else {
        break;
      }
    }

    // Daily cumulative sparkline points
    let dayRun = 0;
    const sparkPoints = [];
    const sortedDays = Array.from(dayTotals.keys()).sort();
    for (const d of sortedDays) {
      dayRun += dayTotals.get(d);
      sparkPoints.push(Number(dayRun.toFixed(2)));
    }

    const activeDays = sortedDays.length;
    const profitFactor =
      grossLost > 0.001 ? grossWon / grossLost : grossWon > 0 ? Infinity : null;

    return {
      maxDrawdown: Number(maxDrawdown.toFixed(2)),
      profitFactor,
      streak: streakType ? { type: streakType, count: streakCount } : null,
      activeDays,
      avgDailyUnits: activeDays > 0 ? running / activeDays : null,
      sparkPoints,
      currentDrawdown: Number(Math.max(0, peak - running).toFixed(2)),
    };
  }, [scopedHistory]);

  const pastPendingCount = useMemo(() => {
    const todayEt = toEtDay(new Date());
    return (recommendedHistory || []).filter((h) => {
      const day = getPerformanceDay(h);
      if (!day || day >= todayEt) return false;
      const norm = normalizeOutcome(getRawOutcome(h));
      return !isGradedOutcome(norm) && norm !== 'VOID';
    }).length;
  }, [recommendedHistory]);

  // Yesterday / Latest Graded Slate Recap (preserving canonical slate markers)
  const yesterdayEt = useMemo(() => {
    const d = new Date();
    d.setDate(d.getDate() - 1);
    return d.toLocaleDateString('en-CA', { timeZone: 'America/New_York' });
  }, []);

  const recoStraight = useMemo(() => yesterdayReco?.straight || [], [yesterdayReco]);
  const recoMlParlay = useMemo(() => yesterdayReco?.ml_parlay || [], [yesterdayReco]);
  const hasReco = useMemo(() => Boolean(yesterdayReco?.slate?.id), [yesterdayReco]);

  const recentSlateDisplay = useMemo(() => {
    const ncaamYesterdayActive =
      (selectedSport === 'ALL' || selectedSport === 'NCAAM') &&
      (selectedSeason === 'ALL' || selectedSeason === defaultNcaamSeason) &&
      hasReco &&
      recoStraight.length + recoMlParlay.length > 0;

    if (ncaamYesterdayActive) {
      const combined = [...recoStraight, ...recoMlParlay].slice().sort((a, b) => {
        const rkA = Number(a?.rank) > 0 ? Number(a.rank) : 999;
        const rkB = Number(b?.rank) > 0 ? Number(b.rank) : 999;
        if (rkA !== rkB) return rkA - rkB;
        return (getNumericEdge(b) ?? -999) - (getNumericEdge(a) ?? -999);
      });
      const normalized = combined
        .map((p, idx) => {
          const marketKey = normalizeMarketType(p);
          return {
            id: p.prediction_id || p.event_id || `${idx}`,
            rank: Number(p.rank) > 0 ? Number(p.rank) : idx + 1,
            matchup: p.matchup || formatMatchup(p),
            sport: 'NCAAM',
            marketKey,
            market: formatMarketLabel(marketKey),
            pick: p.selection || p.side || formatPickLabel(p),
            lineOdds: formatLineAndOdds({ bet_line: p.bet_line ?? p.line, bet_price: p.bet_price ?? p.price ?? p.odds }),
            outcome: p.outcome,
            score: p.score && String(p.score).trim() !== '0-0' ? p.score : null,
            evPct: getNumericEdge(p) != null ? getNumericEdge(p) * 100 : null,
            confidence_0_100: p.confidence_0_100 ?? p.confidence,
            confidence_label: p.confidence_label,
            bet_price: p.bet_price ?? p.price ?? p.odds,
            profitUnits: computeRowProfitUnits(p),
          };
        })
        .filter((item) => {
          if (marketFilter !== 'ALL' && item.marketKey !== marketFilter) return false;
          if (confFilter !== 'ALL' && !matchesConfFilter(item, confFilter)) return false;
          return true;
        });
      const stats = computeRecordStats(normalized);
      return {
        title: `Yesterday's Top Recommended Slate (${yesterdayReco?.date_et || yesterdayEt})`,
        subtitle:
          marketFilter === 'ALL' && confFilter === 'ALL'
            ? `${recoStraight.length} straight • ${recoMlParlay.length} ML/parlay picks • ${historyScope === 'top6' ? 'Matches Top 6 / Day' : 'Recommended Top 6 slate'}`
            : `Filtered view showing ${normalized.length} of ${combined.length} slate picks`,
        rows: normalized,
        stats,
      };
    }

    // Fallback to latest active day across all markets first, then apply Bet Type & Confidence
    const dayRowsMap = {};
    for (const h of sportSeasonWindowHistory) {
      const d = getPerformanceDay(h);
      if (!d) continue;
      if (!dayRowsMap[d]) dayRowsMap[d] = [];
      dayRowsMap[d].push(h);
    }
    const sortedDays = Object.keys(dayRowsMap).sort((a, b) => b.localeCompare(a));
    const latestDay = sortedDays.find((d) => dayRowsMap[d].some((r) => isGradedOutcome(getRawOutcome(r)))) || sortedDays[0];
    const dayTopPicks = latestDay ? dedupeDayRowsByEvent(dayRowsMap[latestDay]).filter((r) => !hasTop6RiskFlag(r)).slice(0, 6) : [];
    const picks = dayTopPicks.filter(
      (r) => matchesMarketFilter(r, marketFilter) && matchesConfFilter(r, confFilter)
    );
    const isActuallyYesterday = latestDay === yesterdayEt;
    const normalized = picks.map((h, i) => ({
      id: h.id || h.prediction_id || `${h.event_id}-${i}`,
      rank: rankByRowKey.get(h) || i + 1,
      matchup: formatMatchup(h),
      sport: normalizeSport(h),
      marketKey: normalizeMarketType(h),
      market: formatMarketLabel(h),
      pick: formatPickLabel(h),
      lineOdds: formatLineAndOdds(h),
      outcome: getRawOutcome(h),
      score: h.score && (normalizeSport(h) === 'EPL' || String(h.score).trim() !== '0-0') ? h.score : null,
      evPct: getNumericEdge(h) != null ? getNumericEdge(h) * 100 : null,
      confidence_0_100: h.confidence_0_100 ?? h.confidence,
      confidence_label: h.confidence_label,
      bet_price: getEffectivePrice(h),
      profitUnits: computeRowProfitUnits(h),
    }));

    return {
      title: latestDay
        ? isActuallyYesterday
          ? `Yesterday's Top 6 Picks (${latestDay})`
          : `Most Recent Graded Day (${latestDay})`
        : 'Recent Slate Recap',
      subtitle:
        picks.length > 0
          ? `${selectedSport === 'ALL' ? 'All sports' : selectedSport} • Top ${picks.length} canonical picks (1 per game)`
          : `No recent picks recorded for ${selectedSport === 'ALL' ? 'selected filters' : selectedSport}.`,
      rows: normalized,
      stats: computeRecordStats(normalized),
    };
  }, [selectedSport, selectedSeason, defaultNcaamSeason, hasReco, recoStraight, recoMlParlay, yesterdayReco, yesterdayEt, sportSeasonWindowHistory, marketFilter, confFilter, historyScope, rankByRowKey]);

  const handleSort = (key) => {
    setSortConfig((prev) => ({
      key,
      direction: prev.key === key && prev.direction === 'desc' ? 'asc' : 'desc',
    }));
  };

  // Outcome + Search + Sort for Bottom Pick History Table
  const filteredAndSortedTableRows = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();

    const filtered = scopedHistory.filter((h) => {
      const norm = normalizeOutcome(getRawOutcome(h));
      if (outcomeFilter === 'SETTLED') {
        if (norm !== 'WON' && norm !== 'LOST' && norm !== 'PUSH') return false;
      } else if (outcomeFilter === 'WON' && norm !== 'WON') {
        return false;
      } else if (outcomeFilter === 'LOST' && norm !== 'LOST') {
        return false;
      } else if (outcomeFilter === 'PUSH' && norm !== 'PUSH') {
        return false;
      } else if (outcomeFilter === 'VOID' && norm !== 'VOID') {
        return false;
      } else if (outcomeFilter === 'PENDING' && norm !== null) {
        return false;
      }

      if (q) {
        const hay = [
          formatMatchup(h),
          formatPickLabel(h),
          normalizeSport(h),
          formatMarketLabel(h),
          getPerformanceDay(h),
        ]
          .join(' ')
          .toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });

    const { key, direction } = sortConfig;
    return filtered.slice().sort((a, b) => {
      let valA;
      let valB;

      if (key === 'created_at') {
        valA = getPerformanceDay(a) || String(a.analyzed_at || a.start_time || '');
        valB = getPerformanceDay(b) || String(b.analyzed_at || b.start_time || '');
        const cmpDay = direction === 'asc' ? valA.localeCompare(valB) : valB.localeCompare(valA);
        if (cmpDay !== 0) return cmpDay;
        return (rankByRowKey.get(a) ?? 999) - (rankByRowKey.get(b) ?? 999);
      } else if (key === 'sport') {
        valA = normalizeSport(a);
        valB = normalizeSport(b);
      } else if (key === 'matchup') {
        valA = formatMatchup(a);
        valB = formatMatchup(b);
      } else if (key === 'pick') {
        valA = formatPickLabel(a);
        valB = formatPickLabel(b);
      } else if (key === 'edge') {
        valA = getNumericEdge(a) ?? -999;
        valB = getNumericEdge(b) ?? -999;
      } else if (key === 'result') {
        const order = { WON: 4, PUSH: 3, VOID: 2, PENDING: 1, LOST: 0 };
        valA = order[normalizeOutcome(getRawOutcome(a)) || 'PENDING'] ?? 1;
        valB = order[normalizeOutcome(getRawOutcome(b)) || 'PENDING'] ?? 1;
      } else if (key === 'pl') {
        valA = computeRowProfitUnits(a);
        valB = computeRowProfitUnits(b);
      }

      if (typeof valA === 'string' && typeof valB === 'string') {
        return direction === 'asc' ? valA.localeCompare(valB) : valB.localeCompare(valA);
      }
      const numA = Number(valA ?? 0);
      const numB = Number(valB ?? 0);
      return direction === 'asc' ? numA - numB : numB - numA;
    });
  }, [scopedHistory, outcomeFilter, searchQuery, sortConfig, rankByRowKey]);

  const visibleTableRows = useMemo(() => {
    if (historyRowLimit === 'ALL') return filteredAndSortedTableRows;
    return filteredAndSortedTableRows.slice(0, Number(historyRowLimit) || 100);
  }, [filteredAndSortedTableRows, historyRowLimit]);

  const hasNonDefaultFilters =
    selectedSport !== 'NCAAM' ||
    selectedSeason !== defaultNcaamSeason ||
    windowFilter !== 'ALL' ||
    marketFilter !== 'ALL' ||
    confFilter !== 'ALL' ||
    historyScope !== 'top6' ||
    outcomeFilter !== 'ALL' ||
    searchQuery.trim() !== '';

  const resetAllFilters = () => {
    setSelectedSport('NCAAM');
    setSelectedSeason(defaultNcaamSeason);
    setWindowFilter('ALL');
    setMarketFilter('ALL');
    setConfFilter('ALL');
    setHistoryScope('top6');
    setOutcomeFilter('ALL');
    setSearchQuery('');
  };

  const windowLabel =
    windowFilter === 'ALL' ? 'All Time' : `Last ${windowFilter} Days`;
  const sportLabel = selectedSport === 'ALL' ? 'All Sports' : selectedSport;
  const seasonLabel = formatSeasonLabel(selectedSeason);
  const confLabelMap = {
    HIGH: 'High Conf (80+)',
    MEDIUM: 'Medium Conf (50–79)',
    LOW: 'Low Conf (<50)',
  };
  const filterSummaryText = `${sportLabel} • ${seasonLabel} • ${windowLabel}${marketFilter !== 'ALL' ? ` • ${formatMarketLabel(marketFilter)}` : ''}${confFilter !== 'ALL' ? ` • ${confLabelMap[confFilter] || confFilter}` : ''}`;

  const renderSortIcon = (colKey) => {
    if (sortConfig.key !== colKey) return <ArrowUpDown className="w-3.5 h-3.5 opacity-45 shrink-0" aria-hidden="true" />;
    return sortConfig.direction === 'asc' ? (
      <ChevronUp className="w-3.5 h-3.5 text-indigo-400 shrink-0" aria-hidden="true" />
    ) : (
      <ChevronDown className="w-3.5 h-3.5 text-indigo-400 shrink-0" aria-hidden="true" />
    );
  };

  const renderSortableHeader = (colKey, label, align = 'left') => {
    const isActive = sortConfig.key === colKey;
    const ariaSort = isActive ? (sortConfig.direction === 'asc' ? 'ascending' : 'descending') : undefined;
    return (
      <th scope="col" aria-sort={ariaSort} className={`py-2.5 px-2.5 font-semibold text-xs uppercase tracking-wider text-slate-400 ${align === 'right' ? 'text-right' : 'text-left'}`}>
        <button
          type="button"
          onClick={() => handleSort(colKey)}
          className={`w-full min-h-[26px] inline-flex items-center gap-1.5 rounded px-1 -mx-1 hover:text-slate-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-400 transition-colors cursor-pointer ${
            align === 'right' ? 'justify-end' : 'justify-start'
          }`}
        >
          <span>{label}</span>
          {renderSortIcon(colKey)}
        </button>
      </th>
    );
  };

  const breakEvenDelta = scopedStats.decided > 0 ? scopedStats.winRate - 52.38 : null;

  const renderEquitySparkline = (points, isPositive) => {
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
    const areaPoints = `0,${h} ${coords.join(' ')} ${w},${h}`;
    return (
      <svg
        viewBox={`0 0 ${w} ${h}`}
        className="w-28 h-8 shrink-0 overflow-visible"
        aria-hidden="true"
      >
        <defs>
          <linearGradient id={isPositive ? 'kpiSparkPos' : 'kpiSparkNeg'} x1="0" y1="0" x2="0" y2="1">
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
        <polygon points={areaPoints} fill={`url(#${isPositive ? 'kpiSparkPos' : 'kpiSparkNeg'})`} />
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

  return (
    <div className="space-y-6 pb-12">
      {/* Executive Hero Header */}
      <header className="perf-hero-surface p-5 sm:p-6 flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full border border-indigo-400/35 bg-indigo-500/15 text-indigo-200 text-[11px] font-bold uppercase tracking-wider">
              <Sparkles className="w-3 h-3" aria-hidden="true" />
              <span>Performance Command Center</span>
            </span>
            {scopedStats.decided > 0 && (
              <span
                className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full border text-[11px] font-bold ${
                  scopedStats.winRate >= 52.38
                    ? 'border-emerald-500/35 bg-emerald-500/15 text-emerald-300'
                    : 'border-amber-500/35 bg-amber-500/15 text-amber-200'
                }`}
              >
                <TrendingUp className="w-3 h-3" aria-hidden="true" />
                <span>{scopedStats.winRate >= 52.38 ? 'Beating Break-Even' : 'Tracking Below 52.4%'}</span>
              </span>
            )}
            {executiveMetrics.streak && executiveMetrics.streak.count >= 2 && (
              <span
                className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full border text-[11px] font-mono font-bold ${
                  executiveMetrics.streak.type === 'W'
                    ? 'border-emerald-500/35 bg-emerald-500/15 text-emerald-300'
                    : 'border-rose-500/35 bg-rose-500/15 text-rose-300'
                }`}
              >
                <Flame className="w-3 h-3" aria-hidden="true" />
                <span>
                  {executiveMetrics.streak.type}
                  {executiveMetrics.streak.count} Streak
                </span>
              </span>
            )}
            {lastRefreshedAt && (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full border border-slate-700/80 bg-slate-900/75 text-slate-300 text-[11px] font-mono">
                Updated{' '}
                {lastRefreshedAt.toLocaleTimeString('en-US', {
                  timeZone: 'America/New_York',
                  hour: 'numeric',
                  minute: '2-digit',
                })}{' '}
                ET
              </span>
            )}
          </div>
          <h1>Model Performance</h1>
          <p className="text-sm text-slate-300/90 max-w-2xl">
            Live profit curve, drawdown risk, closing-line sharpness, and bet-type intelligence. At standard -110 odds, winning over <strong className="text-white font-semibold">52.4%</strong> generates long-term profit.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2.5 shrink-0">
          <button
            type="button"
            aria-expanded={showExplainer}
            aria-controls="grading-explainer-panel"
            onClick={() => setShowExplainer((prev) => !prev)}
            className="inline-flex items-center gap-2 px-3.5 py-2 rounded-xl border border-slate-700/80 bg-slate-950/70 hover:bg-slate-800 text-slate-200 text-sm font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-400 transition-colors cursor-pointer"
          >
            <HelpCircle className="w-4 h-4 text-indigo-400" aria-hidden="true" />
            <span>How Grading Works</span>
          </button>

          <button
            type="button"
            onClick={gradeNow}
            disabled={isGrading || loading}
            className="inline-flex items-center gap-2 px-3.5 py-2 rounded-xl border border-indigo-500/45 bg-indigo-500/20 hover:bg-indigo-500/30 disabled:opacity-50 text-indigo-100 text-sm font-semibold focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-400 transition-colors cursor-pointer"
          >
            <RefreshCw className={`w-4 h-4 ${isGrading ? 'animate-spin' : ''}`} aria-hidden="true" />
            <span>{isGrading ? 'Grading...' : 'Grade Pending'}</span>
            {pastPendingCount > 0 && (
              <span className="px-1.5 py-0.5 rounded-full bg-amber-500/25 text-amber-200 text-xs font-mono">
                {pastPendingCount}
              </span>
            )}
          </button>

          <button
            type="button"
            onClick={load}
            disabled={loading}
            className="inline-flex items-center gap-2 px-3.5 py-2 rounded-xl border border-slate-700 bg-slate-900 hover:bg-slate-800 disabled:opacity-50 text-slate-200 text-sm font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-400 transition-colors cursor-pointer"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} aria-hidden="true" />
            <span>Refresh</span>
          </button>
        </div>
      </header>

      {/* Collapsible Plain-Language Grading Explainer */}
      {showExplainer && (
        <section
          id="grading-explainer-panel"
          aria-labelledby="grading-explainer-heading"
          className="ui-card p-5 sm:p-6 border-indigo-500/30 bg-slate-900/70 space-y-4"
        >
          <div className="flex items-center justify-between gap-2">
            <h2 id="grading-explainer-heading" className="text-base font-bold text-slate-100">
              How Pick Tracking Works
            </h2>
            <button
              type="button"
              onClick={() => setShowExplainer(false)}
              className="text-xs font-medium text-slate-400 hover:text-slate-200 cursor-pointer"
            >
              Hide guide
            </button>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs text-slate-300 leading-relaxed">
            <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3.5 space-y-1.5">
              <div className="font-bold text-indigo-300">1. Straight Bets, 1H &amp; Risk Tiers</div>
              <p className="text-xs text-slate-300">
                Tracks actionable <strong className="text-slate-100">Spreads, 1H Spreads, Totals, 1H Totals, and Moneylines</strong> using <strong className="text-emerald-300">Core</strong> (up to 1.0u) and <strong className="text-indigo-300">Smart Risk</strong> (0.5u risk cap) filters plus early-season situational guardrails. Passed games (<strong className="text-slate-100">No Bet</strong>) are excluded.
              </p>
            </div>
            <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3.5 space-y-1.5">
              <div className="font-bold text-emerald-300">2. Straight KPIs vs. Parlays</div>
              <p className="text-xs text-slate-300">
                <strong className="text-emerald-300">Won / Lost</strong> set flat 1-unit profit vs. the <strong className="text-slate-100">52.4%</strong> (-110) break-even line (<strong className="text-slate-100">Push / Void</strong> = <code className="text-slate-200">0.00u</code>). Higher-odds <strong className="text-indigo-200">Official Daily Parlays</strong> are tracked in their own section so longshot variance never skews straight Win %.
              </p>
            </div>
            <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3.5 space-y-1.5">
              <div className="font-bold text-sky-300">3. Top 6 / Day &amp; When to Bet</div>
              <p className="text-xs text-slate-300">
                <strong className="text-slate-100">Top 6 / Day</strong> keeps the single highest-quality play per game up to 6 games daily, alongside <strong className="text-emerald-300">When to Bet</strong> closing-line validation. Switch to <strong className="text-slate-100">All Picks</strong> to inspect every recommended bet.
              </p>
            </div>
          </div>
        </section>
      )}

      {/* Alerts */}
      {gradeMessage && (
        <div role="status" className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-200">
          {gradeMessage}
        </div>
      )}
      {err && (
        <div role="alert" className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
          {err}
        </div>
      )}

      {/* Section Focus Switcher + Unified Visual Filter Toolbar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 px-1">
        <div
          role="tablist"
          aria-label="Model performance section view"
          className="perf-tablist border-slate-800/90"
        >
          {[
            { id: 'all', label: 'All (Grouped)', pill: null },
            {
              id: 'core',
              label: 'Core Model',
              pill:
                scopedStats.decided > 0
                  ? `${scopedStats.wins}-${scopedStats.losses}`
                  : null,
            },
            {
              id: 'parlays',
              label: 'Parlays',
              pill:
                parlayAnalytics.settled > 0
                  ? parlayAnalytics.recordText
                  : parlayAnalytics.pending > 0
                    ? `${parlayAnalytics.pending} open`
                    : null,
            },
          ].map((tab, idx, arr) => {
            const active = activeSection === tab.id;
            const onKeyDown = (e) => {
              let nextIdx = null;
              if (e.key === 'ArrowRight') nextIdx = (idx + 1) % arr.length;
              else if (e.key === 'ArrowLeft') nextIdx = (idx - 1 + arr.length) % arr.length;
              else if (e.key === 'Home') nextIdx = 0;
              else if (e.key === 'End') nextIdx = arr.length - 1;
              if (nextIdx !== null) {
                e.preventDefault();
                const targetTab = arr[nextIdx];
                setActiveSection(targetTab.id);
                focusTabRefs.current[targetTab.id]?.focus();
              }
            };
            return (
              <button
                key={tab.id}
                ref={(el) => {
                  focusTabRefs.current[tab.id] = el;
                }}
                id={`perf-focus-tab-${tab.id}`}
                role="tab"
                type="button"
                aria-selected={active}
                tabIndex={active ? 0 : -1}
                onKeyDown={onKeyDown}
                onClick={() => setActiveSection(tab.id)}
                className="perf-tab text-xs sm:text-sm"
              >
                <span>{tab.label}</span>
                {tab.pill && (
                  <span className="px-1.5 py-0.5 rounded-full border border-slate-700/80 bg-slate-900/90 text-[10px] font-mono text-slate-300">
                    {tab.pill}
                  </span>
                )}
              </button>
            );
          })}
        </div>
        <span className="text-[11px] text-slate-400">
          {activeSection === 'all'
            ? 'Core Straight Bets & Official Parlays grouped separately below'
            : activeSection === 'core'
              ? 'Focused on straight bets, CLV, and live model calibration'
              : 'Focused on Official 2-Leg Daily Parlays and leg analytics'}
        </span>
      </div>

      {/* Unified Visual Filter Toolbar (only 1 dropdown: Season) */}
      <search aria-label="Filter model performance" className="ui-card p-4 sm:p-5 space-y-4">
        <div className="flex flex-col lg:flex-row lg:items-end justify-between gap-4">
          {/* Sport Pills */}
          <div className="space-y-1.5 min-w-0">
            <span className="block text-xs font-semibold uppercase tracking-wider text-slate-400">
              Sport
            </span>
            <div role="group" aria-label="Filter by sport" className="flex flex-wrap items-center gap-1.5">
              <button
                type="button"
                aria-pressed={selectedSport === 'ALL'}
                onClick={() => handleSportChange('ALL')}
                className={`min-h-[36px] px-3 py-1.5 rounded-xl border text-xs font-semibold transition-colors cursor-pointer ${
                  selectedSport === 'ALL'
                    ? 'bg-indigo-500 border-indigo-400 text-white shadow-sm'
                    : 'bg-slate-950 border-slate-800 text-slate-300 hover:text-white hover:border-slate-700'
                }`}
              >
                All Sports ({recommendedHistory.length.toLocaleString()})
              </button>
              {availableSports.map((s) => {
                const active = selectedSport === s.sport;
                return (
                  <button
                    key={s.sport}
                    type="button"
                    aria-pressed={active}
                    onClick={() => handleSportChange(s.sport)}
                    className={`min-h-[36px] px-3 py-1.5 rounded-xl border text-xs font-semibold transition-colors cursor-pointer ${
                      active
                        ? 'bg-indigo-500 border-indigo-400 text-white shadow-sm'
                        : 'bg-slate-950 border-slate-800 text-slate-300 hover:text-white hover:border-slate-700'
                    }`}
                  >
                    {s.sport} ({s.count.toLocaleString()})
                  </button>
                );
              })}
            </div>
          </div>

          {/* Season Dropdown (only select) + Pick Scope */}
          <div className="flex flex-wrap items-end gap-3 shrink-0">
            <div className="space-y-1.5">
              <label htmlFor="perf-season-select" className="block text-xs font-semibold uppercase tracking-wider text-slate-400">
                Season
              </label>
              <select
                id="perf-season-select"
                name="season"
                value={selectedSeason}
                onChange={(e) => setSelectedSeason(e.target.value)}
                className="min-h-[36px] rounded-xl border border-slate-700 bg-slate-950 px-3 py-1.5 text-xs font-semibold text-slate-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400 cursor-pointer [color-scheme:dark]"
              >
                <option value="ALL">All Seasons</option>
                {availableSeasons.map((s) => (
                  <option key={s.season} value={s.season}>
                    {formatSeasonLabel(s.season)} ({s.count.toLocaleString()})
                  </option>
                ))}
              </select>
            </div>

            {activeSection !== 'parlays' && (
              <fieldset className="space-y-1.5">
                <legend className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                  Pick Scope
                </legend>
                <div className="grid grid-cols-2 gap-1 rounded-xl border border-slate-800 bg-slate-950 p-1">
                  {[
                    { val: 'top6', label: 'Top 6 / Day' },
                    { val: 'all', label: 'All Picks' },
                  ].map((opt) => {
                    const active = historyScope === opt.val;
                    return (
                      <label
                        key={opt.val}
                        className={`perf-radio-pill flex items-center justify-center min-h-[28px] px-2.5 rounded-lg text-xs font-semibold cursor-pointer transition-colors ${
                          active ? 'bg-indigo-500 text-white' : 'text-slate-400 hover:text-slate-200'
                        }`}
                      >
                        <input
                          type="radio"
                          name="perf-scope"
                          value={opt.val}
                          checked={active}
                          onChange={() => setHistoryScope(opt.val)}
                          className="sr-only"
                        />
                        <span>{opt.label}</span>
                      </label>
                    );
                  })}
                </div>
              </fieldset>
            )}
          </div>
        </div>

        <div className={`grid grid-cols-1 ${activeSection !== 'parlays' ? 'md:grid-cols-2 xl:grid-cols-3' : 'md:grid-cols-1 max-w-xs'} gap-3.5 items-end pt-1`}>
          {/* Bet Type Pills (Straight bets only) */}
          {activeSection !== 'parlays' && (
            <div className="space-y-1.5">
              <span className="block text-xs font-semibold uppercase tracking-wider text-slate-400">
                Bet Type
              </span>
              <div role="group" aria-label="Filter by bet type" className="flex flex-wrap items-center gap-1.5">
                <button
                  type="button"
                  aria-pressed={marketFilter === 'ALL'}
                  onClick={() => setMarketFilter('ALL')}
                  className={`min-h-[34px] px-2.5 py-1 rounded-lg border text-xs font-semibold transition-colors cursor-pointer ${
                    marketFilter === 'ALL'
                      ? 'bg-indigo-500/25 border-indigo-400 text-indigo-100'
                      : 'bg-slate-950 border-slate-800 text-slate-400 hover:text-slate-200 hover:border-slate-700'
                  }`}
                >
                  All Types
                </button>
                {availableMarkets.map((m) => {
                  const active = marketFilter === m;
                  return (
                    <button
                      key={m}
                      type="button"
                      aria-pressed={active}
                      onClick={() => setMarketFilter(active ? 'ALL' : m)}
                      className={`min-h-[34px] px-2.5 py-1 rounded-lg border text-xs font-semibold transition-colors cursor-pointer ${
                        active
                          ? 'bg-indigo-500/25 border-indigo-400 text-indigo-100'
                          : 'bg-slate-950 border-slate-800 text-slate-400 hover:text-slate-200 hover:border-slate-700'
                      }`}
                    >
                      {formatMarketLabel(m)}
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* Confidence Pills (Straight bets only) */}
          {activeSection !== 'parlays' && (
            <div className="space-y-1.5">
              <span className="block text-xs font-semibold uppercase tracking-wider text-slate-400">
                Confidence
              </span>
              <div role="group" aria-label="Filter by confidence level" className="flex flex-wrap items-center gap-1.5">
                {[
                  { key: 'ALL', label: 'All Levels' },
                  { key: 'HIGH', label: 'High (80+)' },
                  { key: 'MEDIUM', label: 'Medium (50–79)' },
                  { key: 'LOW', label: 'Low (<50)' },
                ].map((opt) => {
                  const active = confFilter === opt.key;
                  return (
                    <button
                      key={opt.key}
                      type="button"
                      aria-pressed={active}
                      onClick={() => setConfFilter(active && opt.key !== 'ALL' ? 'ALL' : opt.key)}
                      className={`min-h-[34px] px-2.5 py-1 rounded-lg border text-xs font-semibold transition-colors cursor-pointer ${
                        active
                          ? 'bg-indigo-500/25 border-indigo-400 text-indigo-100'
                          : 'bg-slate-950 border-slate-800 text-slate-400 hover:text-slate-200 hover:border-slate-700'
                      }`}
                    >
                      {opt.label}
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* Time Window Radio Group */}
          <fieldset className="space-y-1.5">
            <legend className="text-xs font-semibold uppercase tracking-wider text-slate-400">
              Time Window
            </legend>
            <div className="grid grid-cols-4 gap-1 rounded-xl border border-slate-800 bg-slate-950 p-1">
              {[
                { val: 'ALL', label: 'All' },
                { val: '90', label: '90d' },
                { val: '30', label: '30d' },
                { val: '7', label: '7d' },
              ].map((opt) => {
                const active = windowFilter === opt.val;
                return (
                  <label
                    key={opt.val}
                    className={`perf-radio-pill flex items-center justify-center min-h-[28px] rounded-lg text-xs font-semibold cursor-pointer transition-colors ${
                      active ? 'bg-indigo-500 text-white' : 'text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    <input
                      type="radio"
                      name="perf-window"
                      value={opt.val}
                      checked={active}
                      onChange={() => setWindowFilter(opt.val)}
                      className="sr-only"
                    />
                    <span>{opt.label}</span>
                  </label>
                );
              })}
            </div>
          </fieldset>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-slate-800/80 text-xs text-slate-400">
          <div className="flex flex-wrap items-center gap-2">
            <Filter className="w-3.5 h-3.5 text-indigo-400" aria-hidden="true" />
            {activeSection === 'parlays' ? (
              <span>
                Showing <strong className="text-slate-200">{sportLabel} • {seasonLabel} • {windowLabel}</strong> •{' '}
                <span className="font-mono text-slate-200">{parlayAnalytics.settled}</span> settled out of{' '}
                <span className="font-mono text-slate-200">{parlayAnalytics.items.length}</span> official parlays
              </span>
            ) : (
              <span>
                Showing <strong className="text-slate-200">{filterSummaryText}</strong> •{' '}
                <span className="font-mono text-slate-200">{scopedStats.settled.toLocaleString()}</span> graded out of{' '}
                <span className="font-mono text-slate-200">{scopedStats.total.toLocaleString()}</span> picks
                {historyScope === 'top6' && ' • 1 best pick per game'}
              </span>
            )}
          </div>
          {hasNonDefaultFilters && (
            <button
              type="button"
              onClick={resetAllFilters}
              className="inline-flex items-center gap-1.5 text-xs font-semibold text-indigo-300 hover:text-indigo-200 cursor-pointer"
            >
              <RotateCcw className="w-3.5 h-3.5" aria-hidden="true" />
              <span>Reset to Top 6 default</span>
            </button>
          )}
        </div>
      </search>

      <div
        id="perf-focus-panel"
        role="tabpanel"
        aria-labelledby={`perf-focus-tab-${activeSection}`}
        className="space-y-10"
      >
        {/* GROUP 1: CORE MODEL DATA & INSIGHTS */}
        {(activeSection === 'all' || activeSection === 'core') && (
          <section aria-labelledby="core-group-heading" className="space-y-6">
            <div className="rounded-2xl border border-emerald-500/25 bg-gradient-to-r from-emerald-500/10 via-slate-900/70 to-indigo-500/10 px-5 py-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div className="flex items-start gap-3">
                <span className="mt-0.5 p-2 rounded-xl border border-emerald-500/30 bg-emerald-500/15 text-emerald-300 shrink-0">
                  <Target className="w-4 h-4" aria-hidden="true" />
                </span>
                <div>
                  <h2 id="core-group-heading" className="text-base sm:text-lg font-bold text-slate-100">
                    Core Model Data &amp; Insights
                  </h2>
                  <p className="text-xs text-slate-300/90">
                    Straight-bet profit, Core vs. Smart Risk tiers, closing-line edge, strategy sweet spots, and pick log.
                  </p>
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-2 text-xs font-mono shrink-0">
                <span className="px-2.5 py-1 rounded-full border border-slate-700 bg-slate-950/80 text-slate-200 font-bold">
                  {scopedStats.wins}-{scopedStats.losses}
                  {scopedStats.pushes > 0 ? `-${scopedStats.pushes}` : ''}
                </span>
                {scopedStats.settled > 0 && (
                  <span
                    className={`px-2.5 py-1 rounded-full border font-bold ${
                      scopedStats.profitUnits >= 0
                        ? 'border-emerald-500/35 bg-emerald-500/15 text-emerald-300'
                        : 'border-rose-500/35 bg-rose-500/15 text-rose-300'
                    }`}
                  >
                    {formatUnits(scopedStats.profitUnits)} · {formatSignedPct(scopedStats.roiPct)} ROI
                  </span>
                )}
              </div>
            </div>

            {/* Top KPI Summary Cards + Actionable Key Takeaways */}
            <div className="space-y-4">
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
          {/* Card 1: Net Profit & ROI + Inline Equity Sparkline */}
          <article className="perf-kpi-card p-5 flex flex-col justify-between gap-3">
            <div className="flex items-start justify-between gap-3">
              <div className="space-y-1 min-w-0">
                <div className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wider text-slate-400">
                  <TrendingUp className="w-3.5 h-3.5 text-emerald-400" aria-hidden="true" />
                  <span>Net Profit</span>
                </div>
                <div
                  className={`perf-kpi-value font-extrabold font-mono ${
                    scopedStats.profitUnits >= 0 ? 'text-emerald-400' : 'text-rose-400'
                  }`}
                >
                  {formatUnits(scopedStats.profitUnits)}
                </div>
                <div className="text-xs text-slate-400">
                  {scopedStats.settled > 0 ? (
                    <span className="inline-flex items-center gap-1.5">
                      <span
                        className={`font-mono font-semibold ${
                          scopedStats.roiPct >= 0 ? 'text-emerald-300' : 'text-rose-300'
                        }`}
                      >
                        {formatSignedPct(scopedStats.roiPct)} ROI
                      </span>
                      <span className="text-slate-600">·</span>
                      <span>1u flat</span>
                    </span>
                  ) : (
                    'Waiting on finished games'
                  )}
                </div>
              </div>
              {renderEquitySparkline(executiveMetrics.sparkPoints, scopedStats.profitUnits >= 0)}
            </div>
            {scopedStats.settled > 0 && (
              <div className="grid grid-cols-2 gap-1.5 text-[11px] font-mono pt-1">
                <div className={`rounded-lg border px-2.5 py-1 flex items-center justify-between ${scopedStats.profitUnits >= 0 ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300' : 'border-rose-500/30 bg-rose-500/10 text-rose-300'}`}>
                  <span className="font-sans text-[10px] text-slate-300">1u Flat</span>
                  <span className="font-bold">{formatUnits(scopedStats.profitUnits)}</span>
                </div>
                <div className={`rounded-lg border px-2.5 py-1 flex items-center justify-between ${weightedProfitUnits >= 0 ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300' : 'border-rose-500/30 bg-rose-500/10 text-rose-300'}`}>
                  <span className="font-sans text-[10px] text-slate-300">Tier-Sized</span>
                  <span className="font-bold">{formatUnits(weightedProfitUnits)}</span>
                </div>
              </div>
            )}
          </article>

          {/* Card 2: Win Rate & Record */}
          <article className="perf-kpi-card p-5 flex flex-col justify-between gap-3">
            <div className="flex items-start justify-between gap-2">
              <div className="space-y-1">
                <div className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wider text-slate-400">
                  <Target className="w-3.5 h-3.5 text-sky-400" aria-hidden="true" />
                  <span>Win Rate &amp; Record</span>
                </div>
                <div className="flex items-baseline gap-2.5">
                  <span
                    className={`perf-kpi-value font-extrabold font-mono ${
                      scopedStats.decided === 0
                        ? 'text-slate-300'
                        : scopedStats.winRate >= 52.38
                          ? 'text-emerald-400'
                          : 'text-rose-400'
                    }`}
                  >
                    {scopedStats.decided > 0 ? `${scopedStats.winRate.toFixed(1)}%` : '—'}
                  </span>
                  <span className="text-sm font-mono font-bold text-slate-200">
                    {scopedStats.wins}-{scopedStats.losses}
                    {scopedStats.pushes > 0 ? `-${scopedStats.pushes}` : ''}
                  </span>
                </div>
                <div className="text-xs text-slate-400">
                  {breakEvenDelta === null
                    ? 'Break-even at -110 odds is 52.4%'
                    : `${breakEvenDelta >= 0 ? '+' : ''}${breakEvenDelta.toFixed(1)}% vs 52.4% · ${scopedStats.settled.toLocaleString()} graded`}
                </div>
              </div>
              {scopedStats.pending > 0 && (
                <span className="px-2 py-0.5 rounded-full border border-slate-700 bg-slate-900 text-[10px] font-mono text-slate-300 shrink-0">
                  {scopedStats.pending} open
                </span>
              )}
            </div>
            <div className="space-y-1">
              <div className="relative h-2.5 w-full rounded-full bg-slate-800/90 overflow-hidden" aria-hidden="true">
                <div
                  className={`h-full rounded-full transition-all ${
                    scopedStats.decided === 0
                      ? 'bg-slate-600'
                      : scopedStats.winRate >= 52.38
                        ? 'bg-gradient-to-r from-emerald-500 to-teal-400'
                        : 'bg-gradient-to-r from-rose-500 to-amber-500'
                  }`}
                  style={{ width: `${scopedStats.decided > 0 ? Math.max(0, Math.min(100, scopedStats.winRate)) : 0}%` }}
                />
                <div
                  className="absolute top-0 bottom-0 w-0.5 bg-amber-300 shadow-[0_0_6px_rgba(251,191,36,0.9)]"
                  style={{ left: '52.4%' }}
                />
              </div>
              <div className="flex items-center justify-between text-[10px] text-slate-500 font-mono">
                <span>0%</span>
                <span className="text-amber-300/90">52.4% Break-Even</span>
                <span>100%</span>
              </div>
            </div>
          </article>

          {/* Card 3: Closing Line Value (CLV) */}
          <article className="perf-kpi-card p-5 flex flex-col justify-between gap-3">
            <div className="flex items-start justify-between gap-2">
              <div className="space-y-1">
                <div className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wider text-slate-400">
                  <ShieldCheck className="w-3.5 h-3.5 text-indigo-400" aria-hidden="true" />
                  <span>Closing Line Edge</span>
                </div>
                <div
                  className={`perf-kpi-value font-extrabold font-mono ${
                    clvStats.avg === null
                      ? 'text-slate-300'
                      : clvStats.avg > 0
                        ? 'text-emerald-400'
                        : clvStats.avg === 0
                          ? 'text-slate-200'
                          : 'text-amber-300'
                  }`}
                >
                  {clvStats.avg === null ? 'N/A' : `${clvStats.avg > 0 ? '+' : ''}${clvStats.avg.toFixed(2)} pts`}
                </div>
                <div className="text-xs text-slate-400">
                  {clvStats.count > 0
                    ? `Beat closing line ${((clvStats.beatCount / clvStats.count) * 100).toFixed(1)}% (${clvStats.count.toLocaleString()} picks)`
                    : 'No closing-line checks saved yet'}
                </div>
              </div>
              {clvStats.avg !== null && (
                <span
                  className={`px-2 py-0.5 rounded-full border text-[10px] font-bold uppercase tracking-wider shrink-0 ${
                    clvStats.avg >= 1.0
                      ? 'border-emerald-500/40 bg-emerald-500/15 text-emerald-300'
                      : clvStats.avg > 0
                        ? 'border-sky-500/40 bg-sky-500/15 text-sky-300'
                        : 'border-amber-500/35 bg-amber-500/10 text-amber-200'
                  }`}
                >
                  {clvStats.avg >= 1.0 ? 'Elite' : clvStats.avg > 0 ? 'Sharp' : 'Neutral'}
                </span>
              )}
            </div>
            <div className="space-y-1">
              <div className="h-2.5 w-full rounded-full bg-slate-800/90 overflow-hidden" aria-hidden="true">
                <div
                  className={`h-full rounded-full transition-all ${
                    clvStats.count === 0
                      ? 'bg-slate-700'
                      : (clvStats.beatCount / clvStats.count) >= 0.5
                        ? 'bg-gradient-to-r from-indigo-500 to-emerald-400'
                        : 'bg-amber-400'
                  }`}
                  style={{ width: `${clvStats.count > 0 ? Math.max(4, Math.min(100, (clvStats.beatCount / clvStats.count) * 100)) : 0}%` }}
                />
              </div>
              <div className="flex items-center justify-between text-[10px] text-slate-500">
                <span>Market Sharpness</span>
                <span className="font-mono text-slate-300">
                  {clvStats.count > 0 ? `${clvStats.beatCount}/${clvStats.count} beat close` : 'Pending close'}
                </span>
              </div>
            </div>
          </article>

          {/* Card 4: Risk, Profit Factor & Drawdown */}
          <article className="perf-kpi-card p-5 flex flex-col justify-between gap-3">
            <div className="space-y-1">
              <div className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wider text-slate-400">
                <Activity className="w-3.5 h-3.5 text-purple-400" aria-hidden="true" />
                <span>Risk &amp; Consistency</span>
              </div>
              <div className="flex items-baseline gap-2">
                <span
                  className={`perf-kpi-value font-extrabold font-mono ${
                    executiveMetrics.profitFactor === null
                      ? 'text-slate-300'
                      : executiveMetrics.profitFactor >= 1.15
                        ? 'text-emerald-400'
                        : executiveMetrics.profitFactor >= 1.0
                          ? 'text-sky-300'
                          : 'text-rose-400'
                  }`}
                >
                  {executiveMetrics.profitFactor === null
                    ? '—'
                    : executiveMetrics.profitFactor === Infinity
                      ? '∞'
                      : `${executiveMetrics.profitFactor.toFixed(2)}x`}
                </span>
                <span className="text-xs text-slate-400">Profit Factor</span>
              </div>
              <div className="text-xs text-slate-400">
                {executiveMetrics.activeDays > 0
                  ? `${formatUnits(executiveMetrics.avgDailyUnits)} avg across ${executiveMetrics.activeDays} active days`
                  : 'Waiting on finished game days'}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-1.5 text-[11px] font-mono pt-1">
              <div className="rounded-lg border border-slate-800 bg-slate-950/75 px-2.5 py-1 flex items-center justify-between">
                <span className="font-sans text-[10px] text-slate-400">Max Dip</span>
                <span className={`font-bold ${executiveMetrics.maxDrawdown > 0 ? 'text-rose-300' : 'text-emerald-300'}`}>
                  {executiveMetrics.maxDrawdown > 0 ? `-${executiveMetrics.maxDrawdown.toFixed(2)}u` : '0.00u'}
                </span>
              </div>
              <div className="rounded-lg border border-slate-800 bg-slate-950/75 px-2.5 py-1 flex items-center justify-between">
                <span className="font-sans text-[10px] text-slate-400">From Peak</span>
                <span className={`font-bold ${executiveMetrics.currentDrawdown > 0 ? 'text-amber-300' : 'text-emerald-300'}`}>
                  {executiveMetrics.currentDrawdown > 0 ? `-${executiveMetrics.currentDrawdown.toFixed(2)}u` : 'At Peak'}
                </span>
              </div>
            </div>
          </article>
        </div>

        {/* Core vs. Smart Risk Visual Breakdown */}
        {scopedStats.settled > 0 && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
            {[
              {
                key: 'core',
                title: 'Core Picks',
                subtitle: 'Full-confidence plays (up to 1.0u)',
                badgeCls: 'border-emerald-500/35 bg-emerald-500/15 text-emerald-300',
                barCls: 'bg-gradient-to-r from-emerald-500 to-teal-400',
                stats: riskTierBreakdown.core,
              },
              {
                key: 'smart',
                title: 'Smart Risk Picks',
                subtitle: 'Higher-upside plays (0.5u risk cap)',
                badgeCls: 'border-indigo-400/35 bg-indigo-500/15 text-indigo-200',
                barCls: 'bg-gradient-to-r from-indigo-500 to-purple-400',
                stats: riskTierBreakdown.smartRisk,
              },
            ].map((tier) => (
              <div
                key={tier.key}
                className="perf-chart-card px-4 py-3.5 space-y-2.5"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className={`px-2 py-0.5 rounded-full border text-[10px] font-bold uppercase tracking-wider ${tier.badgeCls}`}>
                      {tier.title}
                    </span>
                    <span className="text-[11px] text-slate-400">{tier.subtitle}</span>
                  </div>
                  {tier.stats.settled > 0 && (
                    <div className="text-right font-mono">
                      <span className={`text-sm font-extrabold ${tier.stats.profitUnits >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                        {formatUnits(tier.stats.profitUnits)}
                      </span>
                      <span className="text-[10px] text-slate-400 ml-1.5">
                        ({formatSignedPct(tier.stats.roiPct)} ROI)
                      </span>
                    </div>
                  )}
                </div>

                {tier.stats.settled > 0 ? (
                  <>
                    <div className="relative h-2 w-full rounded-full bg-slate-800/90 overflow-hidden" aria-hidden="true">
                      <div
                        className={`h-full rounded-full ${tier.barCls}`}
                        style={{ width: `${Math.max(4, Math.min(100, tier.stats.winRate))}%` }}
                      />
                      <div className="absolute top-0 bottom-0 w-0.5 bg-amber-300/90" style={{ left: '52.4%' }} />
                    </div>
                    <div className="flex flex-wrap items-center justify-between gap-2 text-slate-300 font-mono text-[11px]">
                      <span>
                        Record:{' '}
                        <strong className="text-white">
                          {tier.stats.wins}-{tier.stats.losses}
                          {tier.stats.pushes > 0 ? `-${tier.stats.pushes}` : ''}
                        </strong>{' '}
                        · Win %:{' '}
                        <strong className={tier.stats.winRate >= 52.38 ? 'text-emerald-300' : 'text-rose-300'}>
                          {tier.stats.decided > 0 ? `${tier.stats.winRate.toFixed(1)}%` : '—'}
                        </strong>
                      </span>
                      {tier.stats.clv.avg !== null && (
                        <span>
                          Avg CLV:{' '}
                          <strong className={tier.stats.clv.avg >= 0 ? 'text-emerald-300' : 'text-amber-300'}>
                            {tier.stats.clv.avg > 0 ? '+' : ''}{tier.stats.clv.avg.toFixed(2)} pts
                          </strong>
                        </span>
                      )}
                    </div>
                  </>
                ) : (
                  <div className="font-sans text-slate-500 text-xs">
                    No graded picks in this tier for current filters yet
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Main Recharts Visualizations & Breakdowns */}
      <ModelPerformanceAnalytics
        history={scopedHistory}
        preConfHistory={scopePreConfHistory}
        preMarketHistory={scopePreMarketHistory}
        isTop6Scope={historyScope === 'top6'}
        selectedSport={selectedSport}
        onSelectSport={handleSportChange}
        selectedMarket={marketFilter}
        onSelectMarket={(nextMkt) => setMarketFilter(nextMkt)}
        selectedConf={confFilter}
        onSelectConf={(nextConf) => setConfFilter(nextConf)}
        scopeLabel={historyScope === 'top6' ? 'Top 6 daily picks' : 'all recommended picks'}
        filterSummary={filterSummaryText}
        liveCalibration={liveCalibration}
        modelLearning={modelLearning}
        slateAndRankSlot={(
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Yesterday / Most Recent Active Slate Recap */}
            <article className="ui-card p-5 sm:p-6 space-y-4" aria-labelledby="recent-slate-heading">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <h3 id="recent-slate-heading" className="text-base font-bold text-slate-100">
                    {recentSlateDisplay.title}
                  </h3>
                  <p className="text-xs text-slate-400">{recentSlateDisplay.subtitle}</p>
                </div>
                {recentSlateDisplay.rows.length > 0 && recentSlateDisplay.stats?.settled > 0 && (
                  <div className="flex items-center gap-2 px-2.5 py-1 rounded-full border border-slate-700 bg-slate-950 text-xs font-mono shrink-0">
                    <span className="font-bold text-slate-100">
                      {recentSlateDisplay.stats.wins}-{recentSlateDisplay.stats.losses}
                      {recentSlateDisplay.stats.pushes > 0 ? `-${recentSlateDisplay.stats.pushes}` : ''}
                    </span>
                    <span className="text-slate-600">•</span>
                    <span className={`font-bold ${recentSlateDisplay.stats.profitUnits >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {formatUnits(recentSlateDisplay.stats.profitUnits)}
                    </span>
                    <span className="text-slate-600">•</span>
                    <span className="text-slate-300">
                      {recentSlateDisplay.stats.decided > 0 ? `${recentSlateDisplay.stats.winRate.toFixed(1)}%` : '—'}
                    </span>
                  </div>
                )}
              </div>

              {recentSlateDisplay.rows.length === 0 ? (
                <div className="h-[220px] flex items-center justify-center rounded-xl border border-slate-800 bg-slate-950/60 text-sm text-slate-500">
                  No recent graded picks match the active filters.
                </div>
              ) : (
                <div className="space-y-2">
                  {recentSlateDisplay.rows.map((item) => {
                    const badge = formatOutcomeBadge(item.outcome);
                    const rowPl = item.profitUnits ?? computeRowProfitUnits(item);
                    const confTier = getConfidenceBucket(item);
                    const confScore = Math.round(getNumericConfidence(item));
                    const cardSurface = getOutcomeOutlineClasses(badge.key, 'bet');
                    return (
                      <div
                        key={item.id}
                        className={`flex items-center justify-between gap-3 rounded-xl px-3.5 py-2.5 transition-colors ${
                          cardSurface.outcome ? cardSurface.cardCls : 'border border-slate-800/90 bg-slate-950/60'
                        }`}
                      >
                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            {item.rank && (
                              <span className="px-1.5 py-0.5 rounded bg-indigo-500/20 text-[10px] font-mono font-bold text-indigo-300 shrink-0">
                                #{item.rank}
                              </span>
                            )}
                            <span className="px-1.5 py-0.5 rounded bg-slate-800 text-[10px] font-bold text-slate-300 shrink-0">
                              {item.sport}
                            </span>
                            <span className="text-xs font-semibold text-slate-100 truncate">{item.matchup}</span>
                          </div>
                          <div className="text-xs text-slate-300 mt-0.5 truncate">
                            <span className="font-semibold text-indigo-300">{item.pick}</span>{' '}
                            <span className="text-slate-400">{item.lineOdds}</span>{' '}
                            <span className="text-slate-500">• {item.market}</span>
                            {item.evPct != null && (
                              <span className="text-slate-400 font-mono">
                                {' '}• {item.evPct >= 0 ? '+' : ''}{item.evPct.toFixed(1)}% Edge
                              </span>
                            )}
                            {confScore > 0 && (
                              <span className="text-slate-500"> • {confTier} ({confScore})</span>
                            )}
                          </div>
                        </div>

                        <div className="text-right shrink-0 space-y-0.5">
                          <div className="flex items-center justify-end gap-1.5">
                            {item.score && <span className="text-[11px] font-mono text-slate-400">{item.score}</span>}
                            <span className={`inline-block px-2 py-0.5 rounded-full border text-[11px] font-semibold ${badge.cls}`}>
                              {badge.label}
                            </span>
                          </div>
                          <div
                            className={`text-[11px] font-mono font-bold ${
                              badge.key === 'PENDING'
                                ? 'text-slate-500'
                                : badge.key === 'WON'
                                  ? 'text-emerald-400'
                                  : badge.key === 'LOST'
                                    ? 'text-rose-400'
                                    : 'text-slate-400'
                            }`}
                          >
                            {badge.key === 'PENDING' ? 'Pending' : formatUnits(rowPl)}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </article>

            {/* Daily Rank #1 - #6 */}
            <article className="ui-card p-5 sm:p-6 space-y-4" aria-labelledby="rank-breakdown-heading">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <h3 id="rank-breakdown-heading" className="text-base font-bold text-slate-100">
                    Daily Best Picks by Rank (#1 to #6)
                  </h3>
                  <p className="text-xs text-slate-400">
                    1 best pick per game each day for {sportLabel}, ordered from #1 (highest-rated pick) to #6.
                  </p>
                </div>
                <span className="inline-flex items-center gap-1.5 text-[11px] font-medium text-amber-300 bg-amber-500/10 border border-amber-500/30 rounded-full px-2.5 py-0.5 shrink-0">
                  <span className="w-2.5 border-t border-dashed border-amber-400 inline-block" />
                  52.4% Break-Even
                </span>
              </div>

              {rankBreakdown.every((r) => r.settled === 0) ? (
                <div className="h-[220px] flex items-center justify-center rounded-xl border border-slate-800 bg-slate-950/60 text-sm text-slate-500">
                  No ranked settled picks match this filter.
                </div>
              ) : (
                <>
                  <div className="h-[220px] w-full">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart
                        data={rankBreakdown.map((r) => ({ ...r, winRateRounded: Number(r.winRate.toFixed(1)) }))}
                        margin={{ top: 10, right: 12, left: 0, bottom: 0 }}
                      >
                        <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
                        <XAxis dataKey="label" stroke="#cbd5e1" fontSize={12} tickLine={false} />
                        <YAxis domain={[0, 100]} stroke="#64748b" fontSize={11} tickLine={false} tickFormatter={(v) => `${v}%`} width={40} />
                        <ReferenceLine y={52.4} stroke="#f59e0b" strokeDasharray="4 4" />
                        <Tooltip
                          contentStyle={TOOLTIP_STYLE}
                          formatter={(val) => [`${val}%`, 'Win Rate']}
                          labelFormatter={(_, payload) => {
                            const p = payload?.[0]?.payload;
                            return p ? `Rank ${p.label} • ${p.wins}-${p.losses}${p.pushes > 0 ? `-${p.pushes}` : ''} • ${formatUnits(p.profitUnits)} (${formatSignedPct(p.roiPct)})` : '';
                          }}
                        />
                        <Bar dataKey="winRateRounded" radius={[5, 5, 0, 0]} maxBarSize={38}>
                          {rankBreakdown.map((r) => (
                            <Cell
                              key={r.rank}
                              fill={r.settled === 0 ? '#334155' : r.winRate >= 52.4 ? '#10b981' : '#f43f5e'}
                            />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>

                  <div className="grid grid-cols-3 sm:grid-cols-6 gap-2">
                    {rankBreakdown.map((r) => (
                      <div key={r.rank} className="rounded-xl border border-slate-800 bg-slate-950/60 p-2 text-center">
                        <div className="text-[11px] font-bold text-indigo-300">{r.label}</div>
                        <div className={`text-xs font-mono font-bold mt-0.5 ${r.winRate >= 52.4 ? 'text-emerald-400' : 'text-slate-200'}`}>
                          {r.decided > 0 ? `${r.winRate.toFixed(0)}%` : '—'}
                        </div>
                        <div className="text-[10px] font-mono text-slate-400">
                          {r.wins}-{r.losses}{r.pushes > 0 ? `-${r.pushes}` : ''}
                        </div>
                        <div className={`text-[10px] font-mono ${r.profitUnits >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                          {r.settled > 0 ? formatUnits(r.profitUnits) : '—'}
                        </div>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </article>
          </div>
        )}
      />

      {/* Bottom Pick History & Grading Explorer Table */}
      <article className="ui-card p-5 sm:p-6 space-y-4" aria-labelledby="pick-history-heading">
        <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-3">
          <div>
            <h3 id="pick-history-heading" className="text-lg font-bold text-slate-100">
              Pick History &amp; Results
            </h3>
            <p className="text-xs text-slate-400">
              Showing {visibleTableRows.length.toLocaleString()} of {filteredAndSortedTableRows.length.toLocaleString()} matching picks ({filterSummaryText}).
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {/* Search Box */}
            <search aria-label="Search pick history" className="relative">
              <label htmlFor="pick-search-input" className="sr-only">
                Search matchup or pick
              </label>
              <Search className="w-3.5 h-3.5 text-slate-500 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" aria-hidden="true" />
              <input
                id="pick-search-input"
                type="search"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search team or pick..."
                className="min-h-[38px] w-56 rounded-xl border border-slate-700 bg-slate-950 pl-8 pr-3 py-1.5 text-xs text-slate-100 placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </search>

            {/* Row Limit Pills */}
            <div role="group" aria-label="Rows to display" className="inline-flex items-center gap-1 rounded-xl border border-slate-800 bg-slate-950 p-1">
              {[
                { val: 50, label: '50' },
                { val: 100, label: '100' },
                { val: 'ALL', label: `All (${filteredAndSortedTableRows.length})` },
              ].map((opt) => {
                const active = historyRowLimit === opt.val;
                return (
                  <button
                    key={String(opt.val)}
                    type="button"
                    aria-pressed={active}
                    onClick={() => setHistoryRowLimit(opt.val)}
                    className={`min-h-[30px] px-2.5 py-1 rounded-lg text-xs font-semibold cursor-pointer transition-colors ${
                      active ? 'bg-indigo-500 text-white' : 'text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    {opt.label}
                  </button>
                );
              })}
            </div>
          </div>
        </div>

        {/* Outcome Filter Pills */}
        <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Filter picks by outcome">
          {[
            { key: 'ALL', label: 'All' },
            { key: 'SETTLED', label: 'Finished' },
            { key: 'WON', label: 'Won' },
            { key: 'LOST', label: 'Lost' },
            { key: 'PUSH', label: 'Push' },
            { key: 'VOID', label: 'Void' },
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

        {/* Sortable Responsive Table */}
        <div
          role="region"
          aria-labelledby="pick-history-heading"
          tabIndex={0}
          className="perf-table-wrapper max-h-[560px] overflow-y-auto rounded-xl border border-slate-800/80"
        >
          <table className="perf-sticky-table w-full text-left border-collapse text-sm">
            <caption className="sr-only">Pick History and Results ({filterSummaryText})</caption>
            <thead className="bg-slate-950/90 border-b border-slate-800">
              <tr>
                {renderSortableHeader('created_at', 'Date')}
                {renderSortableHeader('sport', 'Sport')}
                {renderSortableHeader('matchup', 'Matchup')}
                {renderSortableHeader('pick', 'Pick & Odds')}
                {renderSortableHeader('edge', 'Edge & Confidence', 'right')}
                {renderSortableHeader('result', 'Result & Score')}
                {renderSortableHeader('pl', 'Profit', 'right')}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/70">
              {loading && visibleTableRows.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-10 text-center text-sm text-slate-400">
                    Loading model performance history...
                  </td>
                </tr>
              ) : visibleTableRows.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-10 text-center text-sm text-slate-400">
                    No picks match your current filters.
                  </td>
                </tr>
              ) : (
                visibleTableRows.map((h, idx) => {
                  const day = getPerformanceDay(h) || '—';
                  const sp = normalizeSport(h);
                  const matchup = formatMatchup(h);
                  const pickLabel = formatPickLabel(h);
                  const lineOdds = formatLineAndOdds(h);
                  const market = formatMarketLabel(h);
                  const evDec = getNumericEdge(h);
                  const evPct = evDec != null ? evDec * 100 : null;
                  const confTier = getConfidenceBucket(h);
                  const confScore = Math.round(getNumericConfidence(h));
                  const badge = formatOutcomeBadge(getRawOutcome(h));
                  const rowSurface = getOutcomeOutlineClasses(badge.key, 'bet');
                  const profitUnits = computeRowProfitUnits(h);
                  const rankNum = rankByRowKey.get(h);

                  const tierCls =
                    confTier === 'High'
                      ? 'text-emerald-300 bg-emerald-500/10 border-emerald-500/30'
                      : confTier === 'Medium'
                        ? 'text-amber-300 bg-amber-500/10 border-amber-500/30'
                        : 'text-slate-300 bg-slate-800/80 border-slate-700';

                  return (
                    <tr key={h.id || h.prediction_id || `${h.event_id}-${idx}`} className={`${rowSurface.outcome ? rowSurface.rowCls : 'hover:bg-slate-900/55'} transition-colors`}>
                      <td className={`py-2.5 px-2.5 font-mono text-xs text-slate-300 whitespace-nowrap ${rowSurface.stripeCls}`}>{day}</td>
                      <td className="py-2.5 px-2.5 whitespace-nowrap">
                        <span className="px-2 py-0.5 rounded-md bg-slate-800 text-slate-200 text-xs font-bold">
                          {sp}
                        </span>
                      </td>
                      <td className="py-2.5 px-2.5 font-medium text-slate-100 max-w-[190px]">
                        <div className="truncate" title={matchup}>
                          {matchup}
                        </div>
                      </td>
                      <td className="py-2.5 px-2.5 max-w-[200px]">
                        <div className="flex items-center gap-1.5">
                          {rankNum && rankNum <= 6 && (
                            <span className="px-1.5 py-0.5 rounded bg-indigo-500/20 text-indigo-300 text-[10px] font-mono font-bold shrink-0">
                              #{rankNum}
                            </span>
                          )}
                          <span className="font-semibold text-indigo-300 truncate" title={`${pickLabel} ${lineOdds}`}>
                            {pickLabel}
                          </span>
                        </div>
                        <div className="text-xs text-slate-400 truncate" title={`${lineOdds} • ${market}`}>
                          {lineOdds} • {market}
                        </div>
                      </td>
                      <td className="py-2.5 px-2.5 text-right whitespace-nowrap">
                        <div className="font-mono text-xs font-semibold text-slate-200">
                          {evPct != null ? `${evPct >= 0 ? '+' : ''}${evPct.toFixed(1)}% Edge` : '—'}
                        </div>
                        <span className={`inline-block mt-0.5 px-1.5 py-0.5 rounded border text-[10px] font-semibold ${tierCls}`}>
                          {confTier}{confScore > 0 ? ` (${confScore})` : ''}
                        </span>
                      </td>
                      <td className="py-2.5 px-2.5 whitespace-nowrap">
                        <div className="flex items-center gap-1.5">
                          <span className={`px-2 py-0.5 rounded-full border text-xs font-semibold ${badge.cls}`}>
                            {badge.label}
                          </span>
                          {h.score && (sp === 'EPL' || String(h.score).trim() !== '0-0') && (
                            <span className="font-mono text-xs text-slate-400">{h.score}</span>
                          )}
                        </div>
                      </td>
                      <td
                        className={`py-2.5 px-2.5 text-right font-mono text-xs font-bold whitespace-nowrap ${
                          badge.key === 'WON'
                            ? 'text-emerald-400'
                            : badge.key === 'LOST'
                              ? 'text-rose-400'
                              : 'text-slate-400'
                        }`}
                      >
                        {badge.key === 'PENDING' ? '—' : formatUnits(profitUnits)}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {historyRowLimit !== 'ALL' && visibleTableRows.length < filteredAndSortedTableRows.length && (
          <div className="flex justify-center pt-1">
            <button
              type="button"
              onClick={() =>
                setHistoryRowLimit((prev) =>
                  typeof prev === 'number' ? prev + 100 : 'ALL'
                )
              }
              className="px-4 py-2 rounded-xl border border-slate-700 bg-slate-900 hover:bg-slate-800 text-xs font-semibold text-indigo-200 cursor-pointer transition-colors"
            >
              Show More Rows ({(filteredAndSortedTableRows.length - visibleTableRows.length).toLocaleString()} remaining)
            </button>
          </div>
        )}
      </article>
          </section>
        )}

        {/* GROUP 2: PARLAY DATA & INSIGHTS */}
        {(activeSection === 'all' || activeSection === 'parlays') && (
          <section aria-labelledby="parlay-group-heading" className="space-y-6">
            <div className="rounded-2xl border border-indigo-500/30 bg-gradient-to-r from-indigo-500/12 via-slate-900/75 to-amber-500/10 px-5 py-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div className="flex items-start gap-3">
                <span className="mt-0.5 p-2 rounded-xl border border-indigo-400/35 bg-indigo-500/15 text-indigo-300 shrink-0">
                  <Layers className="w-4 h-4" aria-hidden="true" />
                </span>
                <div>
                  <h2 id="parlay-group-heading" className="text-base sm:text-lg font-bold text-slate-100">
                    Parlay Data &amp; Insights
                  </h2>
                  <p className="text-xs text-slate-300/90">
                    Official 2-leg daily parlays locked 10m pre-tip — leg hit rates, strategy &amp; odds bands, and running equity curve.
                  </p>
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-2 text-xs font-mono shrink-0">
                <span className="px-2.5 py-1 rounded-full border border-slate-700 bg-slate-950/80 text-slate-200 font-bold">
                  {parlayAnalytics.recordText}
                </span>
                {parlayAnalytics.settled > 0 ? (
                  <span
                    className={`px-2.5 py-1 rounded-full border font-bold ${
                      parlayAnalytics.profitUnits >= 0
                        ? 'border-emerald-500/35 bg-emerald-500/15 text-emerald-300'
                        : 'border-rose-500/35 bg-rose-500/15 text-rose-300'
                    }`}
                  >
                    {formatUnits(parlayAnalytics.profitUnits)} · {formatSignedPct(parlayAnalytics.roiPct)} ROI
                  </span>
                ) : parlayAnalytics.pending > 0 ? (
                  <span className="px-2.5 py-1 rounded-full border border-sky-500/35 bg-sky-500/15 text-sky-300 font-bold">
                    {parlayAnalytics.pending} open
                  </span>
                ) : null}
              </div>
            </div>

            <ParlayPerformanceSection
              parlayAnalytics={parlayAnalytics}
              selectedSport={selectedSport}
              onSwitchToNcaam={() => handleSportChange('NCAAM')}
              filterSummary={`${sportLabel} • ${seasonLabel} • ${windowLabel}`}
            />
          </section>
        )}
      </div>
    </div>
  );
}
