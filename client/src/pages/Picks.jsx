import React, { useEffect, useMemo, useState } from 'react';
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
import {
  normalizeOutcome,
  isGradedOutcome,
  toEtDay,
  getPerformanceDay,
  getNumericConfidence,
  getConfidenceBucket,
  getRawOutcome,
  normalizeMarketType,
  formatMarketLabel,
  formatMatchup,
  formatPickLabel,
  formatLineAndOdds,
  getNumericEdge,
  selectTopPicksPerDay,
  computeRecordStats,
  normalizeSport,
  computeRowProfitUnits,
  computeRankBreakdown,
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

  // Filters & interactive UI state
  const [selectedSport, setSelectedSport] = useState('ALL');
  const [windowFilter, setWindowFilter] = useState('ALL');
  const [marketFilter, setMarketFilter] = useState('ALL');
  const [historyScope, setHistoryScope] = useState('all');
  const [outcomeFilter, setOutcomeFilter] = useState('ALL');
  const [searchQuery, setSearchQuery] = useState('');
  const [historyRowLimit, setHistoryRowLimit] = useState(100);
  const [showExplainer, setShowExplainer] = useState(false);
  const [sortConfig, setSortConfig] = useState({ key: 'created_at', direction: 'desc' });

  const load = async () => {
    setLoading(true);
    setErr(null);
    try {
      const res = await api.get('/api/research/history', { params: { limit: 20000, lookback_days: 400 } });
      let rows = res.data || [];

      try {
        const ys = await api.get('/api/ncaam/recommended-slate/yesterday');
        setYesterdayReco(ys.data || null);
      } catch (e) {
        setYesterdayReco(null);
      }

      if (!(Array.isArray(rows) && rows.length > 0)) {
        const n = await api.get('/api/ncaam/history', { params: { limit: 2000 } }).catch(() => ({ data: [] }));
        rows = n.data || [];
      }

      // Ensure yesterday's pending picks are auto-graded once per day if scores are available
      try {
        const yesterdayEtStr = toEtDay(new Date(Date.now() - 86400000));
        const pendingYesterday = (rows || []).filter(
          (h) => getPerformanceDay(h) === yesterdayEtStr && !isGradedOutcome(getRawOutcome(h)) && normalizeOutcome(getRawOutcome(h)) !== 'VOID'
        ).length;
        const k = `grade_yesterday_attempt_${yesterdayEtStr}`;
        if (pendingYesterday > 0 && !localStorage.getItem(k)) {
          localStorage.setItem(k, '1');
          await api.post('/api/research/grade');
          const res2 = await api.get('/api/research/history', { params: { limit: 20000, lookback_days: 400 } });
          rows = res2.data || rows;
        }
      } catch (e) {
        // non-blocking
      }

      setHistory(rows);
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
      const res = await api.post('/api/research/grade', {
        backfill_pending: true,
        max_grade_rows: 5000,
      });
      const data = res?.data || {};
      const gradedCount = Number(data.graded_predictions ?? data.predictions_graded ?? 0);
      const checkedGames = Number(data.ingested_games ?? data.games_checked ?? 0);
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
    return Object.entries(counts)
      .map(([sport, count]) => ({ sport, count }))
      .sort((a, b) => b.count - a.count);
  }, [recommendedHistory]);

  // Dynamic bet type options within active sport
  const availableMarkets = useMemo(() => {
    const set = new Set();
    for (const h of recommendedHistory) {
      if (selectedSport !== 'ALL' && normalizeSport(h) !== selectedSport) continue;
      set.add(normalizeMarketType(h));
    }
    return Array.from(set).sort();
  }, [recommendedHistory, selectedSport]);

  useEffect(() => {
    if (marketFilter !== 'ALL' && availableMarkets.length > 0 && !availableMarkets.includes(marketFilter)) {
      setMarketFilter('ALL');
    }
  }, [availableMarkets, marketFilter]);

  // Filter by Window & Bet Type (kept cross-sport so "By Sport" comparison stays live)
  const windowMarketHistory = useMemo(() => {
    const cutoff =
      windowFilter === '90'
        ? etDaysAgoIso(90)
        : windowFilter === '30'
          ? etDaysAgoIso(30)
          : windowFilter === '7'
            ? etDaysAgoIso(7)
            : null;

    return recommendedHistory.filter((h) => {
      if (cutoff) {
        const day = getPerformanceDay(h);
        if (!day || day < cutoff) return false;
      }
      if (marketFilter !== 'ALL' && normalizeMarketType(h) !== marketFilter) {
        return false;
      }
      return true;
    });
  }, [recommendedHistory, windowFilter, marketFilter]);

  // Filter by selected Sport
  const sportWindowMarketHistory = useMemo(() => {
    if (selectedSport === 'ALL') return windowMarketHistory;
    return windowMarketHistory.filter((h) => normalizeSport(h) === selectedSport);
  }, [windowMarketHistory, selectedSport]);

  // Apply Scope (All Recommended Picks vs Top 6 Daily Best)
  const scopedHistory = useMemo(() => {
    if (historyScope === 'top6') {
      return selectTopPicksPerDay(sportWindowMarketHistory, 6);
    }
    return sportWindowMarketHistory;
  }, [historyScope, sportWindowMarketHistory]);

  // Precompute rank map (#1-#6 per day in active sport) for table badges & Rank chart
  const rankByRowKey = useMemo(() => {
    const byDay = {};
    for (const h of sportWindowMarketHistory) {
      const day = getPerformanceDay(h) || 'unknown';
      if (!byDay[day]) byDay[day] = [];
      byDay[day].push(h);
    }
    const map = new WeakMap();
    for (const day of Object.keys(byDay)) {
      const sorted = byDay[day].slice().sort((a, b) => {
        const evA = getNumericEdge(a) ?? -999;
        const evB = getNumericEdge(b) ?? -999;
        if (evB !== evA) return evB - evA;
        const rkA = Number(a?.rank) || 999;
        const rkB = Number(b?.rank) || 999;
        return rkA - rkB;
      });
      sorted.forEach((row, idx) => {
        map.set(row, idx + 1);
      });
    }
    return map;
  }, [sportWindowMarketHistory]);

  const rankBreakdown = useMemo(
    () => computeRankBreakdown(sportWindowMarketHistory, 6),
    [sportWindowMarketHistory]
  );

  // Overall KPI stats (settled + pending + void + profit)
  const scopedStats = useMemo(() => computeRecordStats(scopedHistory), [scopedHistory]);

  const clvStats = useMemo(() => {
    let sum = 0;
    let count = 0;
    for (const h of scopedHistory) {
      const v = parseFloat(h?.clv_points);
      if (Number.isFinite(v)) {
        sum += v;
        count += 1;
      }
    }
    return { count, avg: count > 0 ? sum / count : null };
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
      hasReco &&
      recoStraight.length + recoMlParlay.length > 0;

    if (ncaamYesterdayActive) {
      const combined = [...recoStraight, ...recoMlParlay];
      const normalized = combined.map((p) => ({
        id: p.prediction_id || p.event_id,
        matchup: p.matchup || formatMatchup(p),
        sport: 'NCAAM',
        market: formatMarketLabel(p.market_type),
        pick: p.selection || p.side || formatPickLabel(p),
        lineOdds: formatLineAndOdds({ bet_line: p.bet_line ?? p.line, bet_price: p.bet_price ?? p.price ?? p.odds }),
        outcome: p.outcome,
        score: p.score || null,
        evPct: p.ev_per_unit != null ? Number(p.ev_per_unit) * 100 : null,
      }));
      return {
        title: `Yesterday's Top Recommended Slate (${yesterdayReco?.date_et || yesterdayEt})`,
        subtitle: `${recoStraight.length} straight • ${recoMlParlay.length} ML/parlay picks`,
        rows: normalized,
      };
    }

    // Fallback to latest active day for the chosen sport/filters
    const dayRowsMap = {};
    for (const h of sportWindowMarketHistory) {
      const d = getPerformanceDay(h);
      if (!d) continue;
      if (!dayRowsMap[d]) dayRowsMap[d] = [];
      dayRowsMap[d].push(h);
    }
    const sortedDays = Object.keys(dayRowsMap).sort((a, b) => b.localeCompare(a));
    const latestDay = sortedDays.find((d) => dayRowsMap[d].some((r) => isGradedOutcome(getRawOutcome(r)))) || sortedDays[0];
    const picks = (latestDay ? dayRowsMap[latestDay] : []).slice().sort((a, b) => (getNumericEdge(b) ?? -1) - (getNumericEdge(a) ?? -1));
    const isActuallyYesterday = latestDay === yesterdayEt;

    return {
      title: latestDay
        ? isActuallyYesterday
          ? `Yesterday's Graded Picks (${latestDay})`
          : `Most Recent Graded Day (${latestDay})`
        : 'Recent Slate Recap',
      subtitle:
        picks.length > 0
          ? `${selectedSport === 'ALL' ? 'All sports' : selectedSport} • Top ${Math.min(picks.length, 6)} picks by projected edge`
          : `No recent picks recorded for ${selectedSport === 'ALL' ? 'selected filters' : selectedSport}.`,
      rows: picks.slice(0, 6).map((h, i) => ({
        id: h.id || h.prediction_id || `${h.event_id}-${i}`,
        matchup: formatMatchup(h),
        sport: normalizeSport(h),
        market: formatMarketLabel(h),
        pick: formatPickLabel(h),
        lineOdds: formatLineAndOdds(h),
        outcome: getRawOutcome(h),
        score: h.score || null,
        evPct: getNumericEdge(h) != null ? getNumericEdge(h) * 100 : null,
      })),
    };
  }, [selectedSport, hasReco, recoStraight, recoMlParlay, yesterdayReco, yesterdayEt, sportWindowMarketHistory]);

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
        const getVal = (item) => {
          const e = getNumericEdge(item);
          if (e !== null) return e;
          const raw = item?.ev_per_unit ?? item?.ev ?? item?.edge;
          return raw !== undefined && raw !== null ? parseFloat(raw) : -999;
        };
        valA = getVal(a);
        valB = getVal(b);
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
  }, [scopedHistory, outcomeFilter, searchQuery, sortConfig]);

  const visibleTableRows = useMemo(() => {
    if (historyRowLimit === 'ALL') return filteredAndSortedTableRows;
    return filteredAndSortedTableRows.slice(0, Number(historyRowLimit) || 100);
  }, [filteredAndSortedTableRows, historyRowLimit]);

  const hasNonDefaultFilters =
    selectedSport !== 'ALL' ||
    windowFilter !== 'ALL' ||
    marketFilter !== 'ALL' ||
    historyScope !== 'all' ||
    outcomeFilter !== 'ALL' ||
    searchQuery.trim() !== '';

  const resetAllFilters = () => {
    setSelectedSport('ALL');
    setWindowFilter('ALL');
    setMarketFilter('ALL');
    setHistoryScope('all');
    setOutcomeFilter('ALL');
    setSearchQuery('');
  };

  const windowLabel =
    windowFilter === 'ALL' ? 'All Time' : `Last ${windowFilter} Days`;
  const sportLabel = selectedSport === 'ALL' ? 'All Sports' : selectedSport;
  const filterSummaryText = `${sportLabel} • ${windowLabel}${marketFilter !== 'ALL' ? ` • ${formatMarketLabel(marketFilter)}` : ''}`;

  const renderSortIcon = (colKey) => {
    if (sortConfig.key !== colKey) return <ArrowUpDown className="w-3.5 h-3.5 opacity-45" aria-hidden="true" />;
    return sortConfig.direction === 'asc' ? (
      <ChevronUp className="w-3.5 h-3.5 text-indigo-400" aria-hidden="true" />
    ) : (
      <ChevronDown className="w-3.5 h-3.5 text-indigo-400" aria-hidden="true" />
    );
  };

  const renderSortableHeader = (colKey, label, align = 'left') => {
    const isActive = sortConfig.key === colKey;
    const ariaSort = isActive ? (sortConfig.direction === 'asc' ? 'ascending' : 'descending') : undefined;
    return (
      <th scope="col" aria-sort={ariaSort} className={`py-3 px-3 font-semibold text-xs uppercase tracking-wider text-slate-400 ${align === 'right' ? 'text-right' : 'text-left'}`}>
        <button
          type="button"
          onClick={() => handleSort(colKey)}
          className={`inline-flex items-center gap-1.5 hover:text-slate-100 transition-colors cursor-pointer ${
            align === 'right' ? 'ml-auto justify-end' : ''
          }`}
        >
          <span>{label}</span>
          {renderSortIcon(colKey)}
        </button>
      </th>
    );
  };

  const breakEvenDelta = scopedStats.decided > 0 ? scopedStats.winRate - 52.38 : null;

  return (
    <div className="space-y-6 pb-12">
      {/* Page Header */}
      <header className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div>
          <h1>Model Performance</h1>
          <p className="text-sm text-slate-400 mt-1">
            Track pick accuracy, unit profit, and ROI across sports. Winning over <strong className="text-slate-200 font-semibold">52.4%</strong> at standard -110 odds is profitable.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2.5">
          <button
            type="button"
            aria-expanded={showExplainer}
            aria-controls="grading-explainer-panel"
            onClick={() => setShowExplainer((prev) => !prev)}
            className="inline-flex items-center gap-2 px-3.5 py-2 rounded-xl border border-slate-700 bg-slate-900 hover:bg-slate-800 text-slate-200 text-sm font-medium transition-colors cursor-pointer"
          >
            <HelpCircle className="w-4 h-4 text-indigo-400" aria-hidden="true" />
            <span>How Grading Works</span>
          </button>

          <button
            type="button"
            onClick={gradeNow}
            disabled={isGrading || loading}
            className="inline-flex items-center gap-2 px-3.5 py-2 rounded-xl border border-indigo-500/40 bg-indigo-500/15 hover:bg-indigo-500/25 disabled:opacity-50 text-indigo-200 text-sm font-semibold transition-colors cursor-pointer"
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
            className="inline-flex items-center gap-2 px-3.5 py-2 rounded-xl border border-slate-700 bg-slate-900 hover:bg-slate-800 disabled:opacity-50 text-slate-200 text-sm font-medium transition-colors cursor-pointer"
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
              How Pick Tracking & Grading Works
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
              <div className="font-bold text-indigo-300">1. Which Picks Are Graded?</div>
              <p className="text-xs text-slate-300">
                Only picks passing positive expected-value gates (<strong className="text-slate-100">+2.0% EV or higher</strong>; Moneylines <strong className="text-slate-100">+5.0% EV &amp; 45%+ win chance</strong>) are saved and graded. <strong className="text-slate-100">No Bet</strong> games are skipped, while <strong className="text-slate-100">all confidence levels</strong> (High, Medium, Low) on recommended picks are graded.
              </p>
            </div>
            <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3.5 space-y-1.5">
              <div className="font-bold text-emerald-300">2. What Each Outcome Means</div>
              <p className="text-xs text-slate-300">
                <strong className="text-emerald-300">Won / Lost</strong> set Win % and 1-unit profit using the bet&apos;s posted odds. <strong className="text-slate-100">Push</strong> ties the line (<code className="text-slate-200">0.00u</code>, excluded from Win %). <strong className="text-amber-300">Void</strong> marks postponed/canceled games (<code className="text-slate-200">0.00u</code>, excluded from ROI).
              </p>
            </div>
            <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3.5 space-y-1.5">
              <div className="font-bold text-sky-300">3. All Picks vs Top 6 Daily Best</div>
              <p className="text-xs text-slate-300">
                Use <strong className="text-slate-100">All Recommended</strong> to audit total model volume, or switch to <strong className="text-slate-100">Top 6 Daily Best</strong> to track only the 6 highest-edge plays per day. Filter by Sport above to isolate NCAAM vs MLB.
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

      {/* Unified Filter Toolbar */}
      <search aria-label="Filter model performance" className="ui-card p-4 sm:p-5 space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 items-end">
          {/* Sport Dropdown */}
          <div className="space-y-1.5">
            <label htmlFor="perf-sport-select" className="block text-xs font-semibold uppercase tracking-wider text-slate-400">
              Sport
            </label>
            <select
              id="perf-sport-select"
              value={selectedSport}
              onChange={(e) => setSelectedSport(e.target.value)}
              className="w-full min-h-[40px] rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-indigo-500 cursor-pointer"
            >
              <option value="ALL">All Sports ({recommendedHistory.length.toLocaleString()})</option>
              {availableSports.map((s) => (
                <option key={s.sport} value={s.sport}>
                  {s.sport} ({s.count.toLocaleString()})
                </option>
              ))}
            </select>
          </div>

          {/* Bet Type Dropdown */}
          <div className="space-y-1.5">
            <label htmlFor="perf-market-select" className="block text-xs font-semibold uppercase tracking-wider text-slate-400">
              Bet Type
            </label>
            <select
              id="perf-market-select"
              value={marketFilter}
              onChange={(e) => setMarketFilter(e.target.value)}
              className="w-full min-h-[40px] rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-indigo-500 cursor-pointer"
            >
              <option value="ALL">All Bet Types</option>
              {availableMarkets.map((m) => (
                <option key={m} value={m}>
                  {formatMarketLabel(m)}
                </option>
              ))}
            </select>
          </div>

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
                    className={`flex items-center justify-center min-h-[32px] rounded-lg text-xs font-semibold cursor-pointer transition-colors ${
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

          {/* Pick Scope Radio Group */}
          <fieldset className="space-y-1.5">
            <legend className="text-xs font-semibold uppercase tracking-wider text-slate-400">
              Pick Scope
            </legend>
            <div className="grid grid-cols-2 gap-1 rounded-xl border border-slate-800 bg-slate-950 p-1">
              {[
                { val: 'all', label: 'All Picks' },
                { val: 'top6', label: 'Top 6 / Day' },
              ].map((opt) => {
                const active = historyScope === opt.val;
                return (
                  <label
                    key={opt.val}
                    className={`flex items-center justify-center min-h-[32px] rounded-lg text-xs font-semibold cursor-pointer transition-colors ${
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
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-slate-800/80 text-xs text-slate-400">
          <div className="flex items-center gap-2">
            <Filter className="w-3.5 h-3.5 text-indigo-400" aria-hidden="true" />
            <span>
              Viewing <strong className="text-slate-200">{filterSummaryText}</strong> •{' '}
              <span className="font-mono text-slate-200">{scopedStats.settled.toLocaleString()}</span> settled out of{' '}
              <span className="font-mono text-slate-200">{scopedStats.total.toLocaleString()}</span> picks
            </span>
          </div>
          {hasNonDefaultFilters && (
            <button
              type="button"
              onClick={resetAllFilters}
              className="inline-flex items-center gap-1.5 text-xs font-semibold text-indigo-300 hover:text-indigo-200 cursor-pointer"
            >
              <RotateCcw className="w-3.5 h-3.5" aria-hidden="true" />
              <span>Reset filters</span>
            </button>
          )}
        </div>
      </search>

      {/* Top KPI Summary Cards */}
      <section aria-labelledby="kpi-summary-heading" className="space-y-3">
        <h2 id="kpi-summary-heading" className="sr-only">
          Key Performance Summary
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <article className="ui-card p-5 space-y-1.5">
            <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">Settled Record</div>
            <div className="text-2xl font-extrabold font-mono text-slate-100">
              {scopedStats.wins}-{scopedStats.losses}-{scopedStats.pushes}
            </div>
            <div className="text-xs text-slate-400">
              {scopedStats.settled.toLocaleString()} settled
              {scopedStats.voids > 0 ? ` • ${scopedStats.voids} void` : ''}
              {scopedStats.pending > 0 ? ` • ${scopedStats.pending} pending` : ''}
            </div>
          </article>

          <article className="ui-card p-5 space-y-1.5">
            <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">Win Rate</div>
            <div
              className={`text-2xl font-extrabold font-mono ${
                scopedStats.decided === 0
                  ? 'text-slate-300'
                  : scopedStats.winRate >= 52.38
                    ? 'text-emerald-400'
                    : 'text-rose-400'
              }`}
            >
              {scopedStats.decided > 0 ? `${scopedStats.winRate.toFixed(1)}%` : '—'}
            </div>
            <div className="text-xs text-slate-400">
              {breakEvenDelta === null
                ? 'Break-even at -110 odds is 52.4%'
                : `${breakEvenDelta >= 0 ? '+' : ''}${breakEvenDelta.toFixed(1)}% vs 52.4% break-even`}
            </div>
          </article>

          <article className="ui-card p-5 space-y-1.5">
            <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">Net Profit &amp; ROI</div>
            <div
              className={`text-2xl font-extrabold font-mono ${
                scopedStats.profitUnits >= 0 ? 'text-emerald-400' : 'text-rose-400'
              }`}
            >
              {formatUnits(scopedStats.profitUnits)}
            </div>
            <div className="text-xs text-slate-400">
              {scopedStats.settled > 0
                ? `${formatSignedPct(scopedStats.roiPct)} ROI across 1u flat stakes`
                : 'Awaiting settled bets'}
            </div>
          </article>

          <article className="ui-card p-5 space-y-1.5">
            <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">Closing Line Edge (CLV)</div>
            <div
              className={`text-2xl font-extrabold font-mono ${
                clvStats.avg === null
                  ? 'text-slate-300'
                  : clvStats.avg >= 0
                    ? 'text-emerald-400'
                    : 'text-amber-300'
              }`}
            >
              {clvStats.avg === null ? 'N/A' : `${clvStats.avg >= 0 ? '+' : ''}${clvStats.avg.toFixed(2)} pts`}
            </div>
            <div className="text-xs text-slate-400">
              {clvStats.count > 0
                ? `Tracked on ${clvStats.count.toLocaleString()} picks w/ closing line`
                : 'No closing-line deltas logged in selection'}
            </div>
          </article>
        </div>
      </section>

      {/* Main Recharts Visualizations & Breakdowns */}
      <h2 className="sr-only">Model Performance Charts and Breakdowns</h2>
      <ModelPerformanceAnalytics
        history={scopedHistory}
        allHistory={windowMarketHistory}
        selectedSport={selectedSport}
        onSelectSport={setSelectedSport}
        scopeLabel={historyScope === 'top6' ? 'Top 6 daily picks' : 'all recommended picks'}
        filterSummary={filterSummaryText}
      />

      {/* Top 6 Rank Breakdown + Yesterday / Latest Slate Recap */}
      <section aria-label="Daily Rank Performance and Recent Slate Recap" className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Daily Rank #1 - #6 */}
        <article className="ui-card p-5 sm:p-6 space-y-4" aria-labelledby="rank-breakdown-heading">
          <div>
            <h2 id="rank-breakdown-heading" className="text-base font-bold text-slate-100">
              Daily Best Picks by Rank (#1 to #6)
            </h2>
            <p className="text-xs text-slate-400">
              Ranks each day&apos;s picks by highest projected EV (#1 = strongest play of the day) for {sportLabel}.
            </p>
          </div>

          {rankBreakdown.every((r) => r.settled === 0) ? (
            <div className="h-[220px] flex items-center justify-center rounded-xl border border-slate-800 bg-slate-950/60 text-sm text-slate-500">
              No ranked settled picks match this filter.
            </div>
          ) : (
            <>
              <div className="h-[210px] w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart
                    data={rankBreakdown.map((r) => ({ ...r, winRateRounded: Number(r.winRate.toFixed(1)) }))}
                    margin={{ top: 10, right: 12, left: 0, bottom: 0 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
                    <XAxis dataKey="label" stroke="#cbd5e1" fontSize={12} tickLine={false} />
                    <YAxis domain={[0, 100]} stroke="#64748b" fontSize={11} tickLine={false} tickFormatter={(v) => `${v}%`} width={40} />
                    <ReferenceLine
                      y={52.4}
                      stroke="#f59e0b"
                      strokeDasharray="4 4"
                      label={{ value: '52.4% Break-Even', fill: '#f59e0b', fontSize: 10, position: 'insideTopRight' }}
                    />
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
                      {r.wins}-{r.losses}
                    </div>
                    <div className={`text-[10px] font-mono ${r.roiPct >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {r.settled > 0 ? formatSignedPct(r.roiPct) : '—'}
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </article>

        {/* Yesterday / Most Recent Active Slate Recap */}
        <article className="ui-card p-5 sm:p-6 space-y-4" aria-labelledby="recent-slate-heading">
          <div>
            <h2 id="recent-slate-heading" className="text-base font-bold text-slate-100">
              {recentSlateDisplay.title}
            </h2>
            <p className="text-xs text-slate-400">{recentSlateDisplay.subtitle}</p>
          </div>

          {recentSlateDisplay.rows.length === 0 ? (
            <div className="h-[220px] flex items-center justify-center rounded-xl border border-slate-800 bg-slate-950/60 text-sm text-slate-500">
              No recent graded picks to show for this sport yet.
            </div>
          ) : (
            <div className="space-y-2 max-h-[300px] overflow-y-auto pr-1">
              {recentSlateDisplay.rows.map((item) => {
                const badge = formatOutcomeBadge(item.outcome);
                return (
                  <div
                    key={item.id}
                    className="flex items-center justify-between gap-3 rounded-xl border border-slate-800/90 bg-slate-950/60 px-3.5 py-2.5"
                  >
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="px-1.5 py-0.5 rounded bg-slate-800 text-[10px] font-bold text-slate-300">
                          {item.sport}
                        </span>
                        <span className="text-xs font-semibold text-slate-100 truncate">{item.matchup}</span>
                      </div>
                      <div className="text-xs text-slate-300 mt-0.5 truncate">
                        <span className="font-semibold text-indigo-300">{item.pick}</span>{' '}
                        <span className="text-slate-400">{item.lineOdds}</span>{' '}
                        <span className="text-slate-500">• {item.market}</span>
                      </div>
                    </div>

                    <div className="text-right shrink-0 space-y-0.5">
                      <span className={`inline-block px-2 py-0.5 rounded-full border text-[11px] font-semibold ${badge.cls}`}>
                        {badge.label}
                      </span>
                      {(item.score || item.evPct != null) && (
                        <div className="text-[11px] font-mono text-slate-400">
                          {item.score ? item.score : `${item.evPct >= 0 ? '+' : ''}${item.evPct.toFixed(1)}% EV`}
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </article>
      </section>

      {/* Bottom Pick History & Grading Explorer Table */}
      <article className="ui-card p-5 sm:p-6 space-y-4" aria-labelledby="pick-history-heading">
        <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-3">
          <div>
            <h2 id="pick-history-heading" className="text-lg font-bold text-slate-100">
              Pick History &amp; Grading Log
            </h2>
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

            {/* Row Limit */}
            <div className="flex items-center gap-1.5">
              <label htmlFor="row-limit-select" className="text-xs text-slate-400">
                Show
              </label>
              <select
                id="row-limit-select"
                value={historyRowLimit}
                onChange={(e) => setHistoryRowLimit(e.target.value === 'ALL' ? 'ALL' : Number(e.target.value))}
                className="min-h-[38px] rounded-xl border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100 focus:outline-none focus:ring-2 focus:ring-indigo-500 cursor-pointer"
              >
                <option value={50}>50 rows</option>
                <option value={100}>100 rows</option>
                <option value={250}>250 rows</option>
                <option value={500}>500 rows</option>
                <option value="ALL">All ({filteredAndSortedTableRows.length})</option>
              </select>
            </div>
          </div>
        </div>

        {/* Outcome Filter Pills */}
        <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Filter picks by outcome">
          {[
            { key: 'ALL', label: 'All' },
            { key: 'SETTLED', label: 'Settled Only' },
            { key: 'WON', label: 'Won' },
            { key: 'LOST', label: 'Lost' },
            { key: 'PUSH', label: 'Push' },
            { key: 'VOID', label: 'Void' },
            { key: 'PENDING', label: 'Pending' },
          ].map((pill) => {
            const active = outcomeFilter === pill.key;
            return (
              <button
                key={pill.key}
                type="button"
                aria-pressed={active}
                onClick={() => setOutcomeFilter(pill.key)}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold border transition-colors cursor-pointer ${
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
        <div className="table-wrapper overflow-x-auto rounded-xl border border-slate-800/80" tabIndex={0}>
          <table className="w-full text-left border-collapse text-sm">
            <thead className="bg-slate-950/80 border-b border-slate-800">
              <tr>
                {renderSortableHeader('created_at', 'Date (ET)')}
                {renderSortableHeader('sport', 'Sport')}
                {renderSortableHeader('matchup', 'Matchup')}
                {renderSortableHeader('pick', 'Pick & Odds')}
                {renderSortableHeader('edge', 'Edge & Tier', 'right')}
                {renderSortableHeader('result', 'Grade & Score')}
                {renderSortableHeader('pl', 'Profit (1u)', 'right')}
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
                  const profitUnits = computeRowProfitUnits(h);
                  const rankNum = rankByRowKey.get(h);

                  const tierCls =
                    confTier === 'High'
                      ? 'text-emerald-300 bg-emerald-500/10 border-emerald-500/30'
                      : confTier === 'Medium'
                        ? 'text-amber-300 bg-amber-500/10 border-amber-500/30'
                        : 'text-slate-300 bg-slate-800/80 border-slate-700';

                  return (
                    <tr key={h.id || h.prediction_id || `${h.event_id}-${idx}`} className="hover:bg-slate-900/55 transition-colors">
                      <td className="py-3 px-3 font-mono text-xs text-slate-300 whitespace-nowrap">{day}</td>
                      <td className="py-3 px-3 whitespace-nowrap">
                        <span className="px-2 py-0.5 rounded-md bg-slate-800 text-slate-200 text-xs font-bold">
                          {sp}
                        </span>
                      </td>
                      <td className="py-3 px-3 font-medium text-slate-100 max-w-[240px]">
                        <div className="truncate" title={matchup}>
                          {matchup}
                        </div>
                      </td>
                      <td className="py-3 px-3 max-w-[260px]">
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
                        <div className="text-xs text-slate-400">
                          {lineOdds} • {market}
                        </div>
                      </td>
                      <td className="py-3 px-3 text-right whitespace-nowrap">
                        <div className="font-mono text-xs font-semibold text-slate-200">
                          {evPct != null ? `${evPct >= 0 ? '+' : ''}${evPct.toFixed(1)}% EV` : '—'}
                        </div>
                        <span className={`inline-block mt-0.5 px-1.5 py-0.5 rounded border text-[10px] font-semibold ${tierCls}`}>
                          {confTier}{confScore > 0 ? ` (${confScore})` : ''}
                        </span>
                      </td>
                      <td className="py-3 px-3 whitespace-nowrap">
                        <div className="flex items-center gap-2">
                          <span className={`px-2 py-0.5 rounded-full border text-xs font-semibold ${badge.cls}`}>
                            {badge.label}
                          </span>
                          {h.score && <span className="font-mono text-xs text-slate-400">{h.score}</span>}
                        </div>
                      </td>
                      <td
                        className={`py-3 px-3 text-right font-mono text-xs font-bold whitespace-nowrap ${
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
      </article>
    </div>
  );
}
