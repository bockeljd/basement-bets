import React, { useEffect, useMemo, useState } from 'react';
import {
  RefreshCw,
  CheckCircle2,
  AlertCircle,
  Info,
  Calendar,
  ChevronLeft,
  ChevronRight,
  Award,
  X,
} from 'lucide-react';
import api from '../api/axios';
import { loadCache } from '../utils/httpCache';
import ParlayRecommendations from '../components/ParlayRecommendations';
import MarchMadness from './MarchMadness';
import TodayDataHealthStrip from '../components/today/TodayDataHealthStrip';
import TodayPlayCard from '../components/today/TodayPlayCard';
import TodayFullBoardTable from '../components/today/TodayFullBoardTable';
import TodayMatchupModal from '../components/today/TodayMatchupModal';
import ModelLogicDialog from '../components/today/ModelLogicDialog';
import {
  getTodayEtStr,
  shiftEtDateStr,
  makeMatchupKey,
  lookupTopPickForGame,
  getConfidenceMeta,
} from '../components/today/todayHelpers';
import '../styles/todayDashboard.css';

const LEAGUES = ['NCAAM', 'MLB', 'NFL', 'EPL'];

const Research = ({ onAddBet, showModelPerformanceTab = true }) => {
  const [edges, setEdges] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [toast, setToast] = useState(null); // { tone: 'ok'|'err'|'warn', text }
  const [authPromptOpen, setAuthPromptOpen] = useState(false);
  const [authPassword, setAuthPassword] = useState('');

  const [leagueFilter, setLeagueFilter] = useState('NCAAM');
  const [selectedDate, setSelectedDate] = useState(getTodayEtStr());
  const [activeSubTab, setActiveSubTab] = useState('top_plays'); // top_plays | board | parlays | march_madness

  const [rowTopPicks, setRowTopPicks] = useState({});
  const [rowTopPicksByKey, setRowTopPicksByKey] = useState({});
  const [matchupProfiles, setMatchupProfiles] = useState({});
  const [dataHealth, setDataHealth] = useState([]);
  const [degradedMode, setDegradedMode] = useState(false);
  const [degradedAsOf, setDegradedAsOf] = useState(null);

  // Top plays controls
  const [pickTypeFilter, setPickTypeFilter] = useState('all'); // all | spread | total | high_conf | soon
  const [pickViewMode, setPickViewMode] = useState('top6'); // top6 | all
  const [expandedPickIds, setExpandedPickIds] = useState(new Set());

  // Modals
  const [selectedGame, setSelectedGame] = useState(null);
  const [analysisResult, setAnalysisResult] = useState(null);
  const [correlationResult, setCorrelationResult] = useState(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [showModelLogicDialog, setShowModelLogicDialog] = useState(false);

  const BOARD_DAYS_DEFAULT = showModelPerformanceTab ? 3 : 1;

  const toggleWhyPick = (id) => {
    setExpandedPickIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const fetchSchedule = async () => {
    setLoading(true);
    setError(null);
    setDegradedMode(false);
    setDegradedAsOf(null);

    const boardParams = { league: leagueFilter, date: selectedDate, days: BOARD_DAYS_DEFAULT };
    const topPicksParams = { date: selectedDate, days: BOARD_DAYS_DEFAULT, limit_games: 250 };

    try {
      const [boardRes, topPicksRes, healthRes, matchupRes, mlbRes] = await Promise.all([
        api.get('/api/board', { params: boardParams }),
        leagueFilter === 'NCAAM'
          ? api
              .get('/api/ncaam/top-picks', { params: topPicksParams })
              .catch((e) => ({ data: null, _error: e }))
          : Promise.resolve({ data: null }),
        api.get('/api/data-health').catch(() => ({ data: { items: [] } })),
        leagueFilter === 'NCAAM'
          ? api.get('/api/ncaam/matchup-profiles', { params: { date: selectedDate } }).catch(() => ({ data: { profiles: [] } }))
          : Promise.resolve({ data: { profiles: [] } }),
        leagueFilter === 'MLB'
          ? api.get('/api/mlb/predictions', { params: { lookback_days: BOARD_DAYS_DEFAULT } }).catch(() => ({ data: { predictions: [] } }))
          : Promise.resolve({ data: { predictions: [] } }),
      ]);

      setEdges(Array.isArray(boardRes.data) ? boardRes.data : []);
      setDataHealth(healthRes?.data?.items || []);

      const mProfiles = {};
      (matchupRes?.data?.profiles || []).forEach((p) => {
        if (p?.event_id) mProfiles[p.event_id] = p;
      });
      setMatchupProfiles(mProfiles);

      const mapped = {};
      const mappedByKey = {};

      if (leagueFilter === 'NCAAM' && topPicksRes?.data?.picks && typeof topPicksRes.data.picks === 'object') {
        const tp = topPicksRes.data.picks;
        Object.keys(tp).forEach((eid) => {
          const item = tp[eid];
          const recObj = {
            rec: item?.rec,
            analyzedAt: item?.analyzed_at,
            isActionable: item?.is_actionable,
            reason: item?.reason,
            source: item?.source,
            event: item?.event,
          };
          mapped[eid] = recObj;
          const ev = item?.event || {};
          const k = makeMatchupKey(String(ev.day_et || '').slice(0, 10), ev.away_team, ev.home_team);
          if (k && !mappedByKey[k]) mappedByKey[k] = recObj;
        });
      } else if (leagueFilter === 'MLB' && Array.isArray(mlbRes?.data?.predictions)) {
        const latestPreds = new Map();
        mlbRes.data.predictions.forEach((p) => {
          const key = `${p.away_team || ''}_${p.home_team || ''}_${String(p.market_type || '').toUpperCase()}`;
          const prev = latestPreds.get(key);
          const prevT = prev?.analyzed_at ? new Date(prev.analyzed_at).getTime() : 0;
          const nextT = p?.analyzed_at ? new Date(p.analyzed_at).getTime() : 0;
          if (!prev || nextT > prevT) latestPreds.set(key, p);
        });

        Array.from(latestPreds.values()).forEach((p) => {
          const fakeEid = `mlb-${p.id}`;
          const confVal = Number(p.confidence_0_100 || 0);
          const recObj = {
            rec: {
              bet_type: String(p.market_type || 'ML').toUpperCase(),
              selection: p.selection || p.pick,
              pick: p.pick,
              market_line: p.bet_line,
              fair_line: null,
              price: p.bet_price,
              book: p.book || 'Consensus',
              ev: Number(p.ev_per_unit || 0),
              win_prob: p.win_prob,
              confidence_0_100: confVal,
              confidence_tier: confVal >= 75 ? 'HIGH' : confVal >= 50 ? 'MEDIUM' : 'LOW',
            },
            analyzedAt: p.analyzed_at,
            isActionable: true,
            reason: 'MLB Core Model',
            source: 'MLB Analytics',
            event: {
              home_team: p.home_team || 'Home',
              away_team: p.away_team || 'Away',
              start_time: p.analyzed_at,
              day_et: p.day_et,
              sport: 'MLB',
            },
          };
          mapped[fakeEid] = recObj;
          const k = makeMatchupKey(String(p.day_et || '').slice(0, 10), p.away_team, p.home_team);
          if (k && !mappedByKey[k]) mappedByKey[k] = recObj;
        });
      }

      setRowTopPicks(mapped);
      setRowTopPicksByKey(mappedByKey);

      if (topPicksRes?._error) {
        setToast({ tone: 'warn', text: 'Board odds loaded, but top-picks cache returned a warning.' });
      }
    } catch (err) {
      if (err?.response?.status === 403) {
        setAuthPromptOpen(true);
      }
      try {
        const cachedBoard = loadCache('/api/board', boardParams);
        const cachedTop = leagueFilter === 'NCAAM' ? loadCache('/api/ncaam/top-picks', topPicksParams) : null;
        if (cachedBoard?.payload) {
          setEdges(cachedBoard.payload || []);
          setDegradedMode(true);
          setDegradedAsOf(cachedBoard?.at || null);
        }
        if (cachedTop?.payload?.picks) {
          const tp = cachedTop.payload.picks;
          const mapped = {};
          Object.keys(tp).forEach((eid) => {
            mapped[eid] = {
              rec: tp[eid]?.rec,
              analyzedAt: tp[eid]?.analyzed_at,
              isActionable: tp[eid]?.is_actionable,
              reason: tp[eid]?.reason,
              source: tp[eid]?.source,
              event: tp[eid]?.event,
            };
          });
          setRowTopPicks(mapped);
        }
        if (!cachedBoard?.payload && !cachedTop?.payload) {
          setError('Failed to load today’s slate. Please try refreshing.');
        }
      } catch {
        setError('Failed to load today’s slate.');
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSchedule();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [leagueFilter, selectedDate]);

  useEffect(() => {
    if (leagueFilter !== 'NCAAM' && (activeSubTab === 'march_madness' || activeSubTab === 'parlays')) {
      setActiveSubTab('top_plays');
    }
  }, [leagueFilter, activeSubTab]);

  const handleGradeResults = async () => {
    setLoading(true);
    try {
      const res = await api.post('/api/research/grade');
      setToast({
        tone: 'ok',
        text: `Grading complete: ${res?.data?.graded || 0} model predictions updated.`,
      });
      await fetchSchedule();
    } catch (err) {
      setToast({
        tone: 'err',
        text: `Grading failed: ${err?.response?.data?.detail || err?.message || 'Unknown error'}`,
      });
      setLoading(false);
    }
  };

  const handleOpenGameDetails = async (game) => {
    setSelectedGame(game);
    setIsAnalyzing(true);
    setAnalysisResult(null);
    setCorrelationResult(null);
    try {
      const [analysisRes, corrRes] = await Promise.all([
        api.post('/api/ncaam/analyze', { event_id: game.id }),
        api.get('/api/ncaam/correlations/game', { params: { event_id: game.id } }).catch(() => ({ data: null })),
      ]);
      const apiData = analysisRes.data;
      const apiTop = (apiData?.recommendations || [])[0] || null;
      const cachedMeta = lookupTopPickForGame(game, rowTopPicks, rowTopPicksByKey);
      const cachedTop = cachedMeta?.rec || null;
      const merged =
        !apiTop && cachedTop
          ? {
              ...(apiData || {}),
              recommendations: [cachedTop],
              headline: `${apiData?.headline || 'Cached top play'} — using stored snapshot`,
            }
          : apiData;
      setAnalysisResult(merged);
      setCorrelationResult(corrRes?.data || null);

      if ((merged?.recommendations || [])[0]) {
        const freshRec = merged.recommendations[0];
        setRowTopPicks((prev) => ({
          ...prev,
          [game.id]: {
            ...(prev[game.id] || {}),
            rec: freshRec,
            isActionable: true,
            analyzedAt: new Date().toISOString(),
          },
        }));
      }
    } catch (err) {
      setToast({
        tone: 'err',
        text: `Failed to analyze ${game.away_team} @ ${game.home_team}: ${err?.response?.data?.detail || err?.message || 'timeout'}`,
      });
    } finally {
      setIsAnalyzing(false);
    }
  };

  // Build deduplicated list of actionable top plays for Today's Top Plays tab
  const { actionablePlays, slateSummary } = useMemo(() => {
    const gamesForLeague = (edges || []).filter((e) => !leagueFilter || e.sport === leagueFilter);
    const seenIds = new Set();
    const plays = [];

    // First match against board events (so start_time & live scores come through cleanly)
    gamesForLeague.forEach((game) => {
      const meta = lookupTopPickForGame(game, rowTopPicks, rowTopPicksByKey);
      if (meta?.isActionable && meta.rec) {
        seenIds.add(game.id);
        plays.push({ id: game.id, game, rec: meta.rec, conf: getConfidenceMeta(meta.rec) });
      }
    });

    // Also surface any actionable stored picks whose event isn't on the active filtered board slice
    Object.entries(rowTopPicks || {}).forEach(([eid, meta]) => {
      if (seenIds.has(eid) || !meta?.isActionable || !meta?.rec) return;
      const ev = meta.event || {};
      const matchBoard = gamesForLeague.find(
        (g) =>
          makeMatchupKey(g.day_et, g.away_team, g.home_team) ===
          makeMatchupKey(ev.day_et, ev.away_team, ev.home_team)
      );
      if (matchBoard && seenIds.has(matchBoard.id)) return;
      const synthGame = matchBoard || {
        id: eid,
        sport: ev.sport || leagueFilter,
        home_team: ev.home_team || 'Home',
        away_team: ev.away_team || 'Away',
        start_time: ev.start_time || null,
        day_et: ev.day_et || selectedDate,
      };
      seenIds.add(eid);
      plays.push({ id: eid, game: synthGame, rec: meta.rec, conf: getConfidenceMeta(meta.rec) });
    });

    plays.sort((a, b) => Number(b.rec?.ev || 0) - Number(a.rec?.ev || 0));

    const highConf = plays.filter((p) => p.conf.tier === 'HIGH').length;
    const sharpCount = plays.filter((p) => {
      const tags = Array.isArray(p.rec?.movement_tags) ? p.rec.movement_tags : [];
      return tags.includes('sharp_backing') || tags.includes('rlm_confirmed');
    }).length;

    return {
      actionablePlays: plays,
      slateSummary: {
        totalGames: gamesForLeague.length,
        actionableCount: plays.length,
        highConfCount: highConf,
        sharpCount,
      },
    };
  }, [edges, leagueFilter, rowTopPicks, rowTopPicksByKey, selectedDate]);

  const filteredTopPlays = useMemo(() => {
    const nowMs = Date.now();
    const list = actionablePlays.filter(({ game, rec, conf }) => {
      const mkt = String(rec?.bet_type || rec?.market_type || '').toUpperCase();
      if (pickTypeFilter === 'spread') return mkt === 'SPREAD';
      if (pickTypeFilter === 'total') return mkt === 'TOTAL';
      if (pickTypeFilter === 'high_conf') return conf.tier === 'HIGH';
      if (pickTypeFilter === 'soon') {
        const st = game?.start_time ? new Date(game.start_time).getTime() : 0;
        return st > nowMs - 30 * 60000 && st <= nowMs + 3 * 3600 * 1000;
      }
      return true;
    });
    return pickViewMode === 'top6' ? list.slice(0, 6) : list;
  }, [actionablePlays, pickTypeFilter, pickViewMode]);

  const tabs = useMemo(() => {
    const base = [
      { id: 'top_plays', label: `Today's Top Plays (${actionablePlays.length})` },
      { id: 'board', label: `Full Board (${slateSummary.totalGames})` },
    ];
    if (leagueFilter === 'NCAAM') {
      base.push({ id: 'parlays', label: '2-Leg Parlays' });
      base.push({ id: 'march_madness', label: 'March Madness' });
    }
    return base;
  }, [actionablePlays.length, slateSummary.totalGames, leagueFilter]);

  return (
    <div className="space-y-5 pb-12">
      {/* Inline auth banner (replaces window.prompt) */}
      {authPromptOpen && (
        <div className="rounded-xl border border-amber-500/40 bg-amber-950/35 p-3.5 flex flex-wrap items-center justify-between gap-3 text-xs">
          <span className="text-amber-200 font-medium">
            Session authentication required to load protected research endpoints.
          </span>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (!authPassword.trim()) return;
              localStorage.setItem('basement_password', authPassword.trim());
              setAuthPromptOpen(false);
              setAuthPassword('');
              fetchSchedule();
            }}
            className="flex items-center gap-2"
          >
            <label htmlFor="today-auth-input" className="sr-only">
              Basement Password
            </label>
            <input
              id="today-auth-input"
              type="password"
              value={authPassword}
              onChange={(e) => setAuthPassword(e.target.value)}
              placeholder="Password..."
              className="px-2.5 py-1.5 rounded-lg bg-slate-950 border border-slate-700 text-slate-100"
            />
            <button
              type="submit"
              className="px-3 py-1.5 rounded-lg bg-amber-600 hover:bg-amber-500 text-white font-semibold cursor-pointer"
            >
              Unlock
            </button>
          </form>
        </div>
      )}

      {/* Dismissible Status Toast (replaces alert()) */}
      {toast && (
        <div
          role="status"
          className={`rounded-xl border px-4 py-2.5 text-xs flex items-center justify-between gap-3 ${
            toast.tone === 'ok'
              ? 'border-emerald-500/35 bg-emerald-950/35 text-emerald-200'
              : toast.tone === 'warn'
                ? 'border-amber-500/35 bg-amber-950/35 text-amber-200'
                : 'border-rose-500/35 bg-rose-950/35 text-rose-200'
          }`}
        >
          <div className="flex items-center gap-2">
            {toast.tone === 'ok' ? (
              <CheckCircle2 size={15} aria-hidden="true" />
            ) : (
              <AlertCircle size={15} aria-hidden="true" />
            )}
            <span>{toast.text}</span>
          </div>
          <button
            type="button"
            aria-label="Dismiss notification"
            onClick={() => setToast(null)}
            className="text-slate-400 hover:text-white cursor-pointer"
          >
            <X size={14} aria-hidden="true" />
          </button>
        </div>
      )}

      {/* Degraded Cache Notice */}
      {degradedMode && (
        <div className="rounded-xl border border-amber-500/30 bg-amber-950/25 px-4 py-2 text-xs text-amber-200">
          Showing cached slate snapshot{degradedAsOf ? ` from ${new Date(degradedAsOf).toLocaleTimeString()}` : ''}. Live feed refresh will resume automatically.
        </div>
      )}

      {/* Top Header + Controls */}
      <section className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl sm:text-2xl font-bold text-white tracking-tight">
            Today&apos;s Slate &amp; Model Edges
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Blends live sportsbook odds with team strength ratings, injuries, and sharp money movement.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-1.5">
            <label htmlFor="today-league-select" className="text-xs font-semibold text-slate-400">
              League
            </label>
            <select
              id="today-league-select"
              value={leagueFilter}
              onChange={(e) => setLeagueFilter(e.target.value)}
              className="px-2.5 py-1.5 rounded-xl bg-slate-900 border border-slate-700 text-xs font-bold text-white focus:outline-none focus:ring-2 focus:ring-indigo-500/50"
            >
              {LEAGUES.map((lg) => (
                <option key={lg} value={lg}>
                  {lg}
                </option>
              ))}
            </select>
          </div>

          <div className="flex items-center rounded-xl bg-slate-900 border border-slate-700 p-0.5">
            <button
              type="button"
              aria-label="Previous day"
              onClick={() => setSelectedDate((d) => shiftEtDateStr(d, -1))}
              className="p-1.5 rounded-lg text-slate-300 hover:text-white hover:bg-slate-800 cursor-pointer"
            >
              <ChevronLeft size={14} aria-hidden="true" />
            </button>
            <label htmlFor="today-date-picker" className="sr-only">
              Select slate date
            </label>
            <div className="relative flex items-center px-1">
              <Calendar size={13} className="text-slate-400 mr-1.5 pointer-events-none" aria-hidden="true" />
              <input
                id="today-date-picker"
                type="date"
                value={selectedDate}
                onChange={(e) => e.target.value && setSelectedDate(e.target.value)}
                className="bg-transparent text-xs font-mono font-semibold text-slate-100 focus:outline-none"
              />
            </div>
            <button
              type="button"
              aria-label="Next day"
              onClick={() => setSelectedDate((d) => shiftEtDateStr(d, 1))}
              className="p-1.5 rounded-lg text-slate-300 hover:text-white hover:bg-slate-800 cursor-pointer"
            >
              <ChevronRight size={14} aria-hidden="true" />
            </button>
          </div>

          <button
            type="button"
            onClick={fetchSchedule}
            disabled={loading}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-xs font-semibold text-slate-100 cursor-pointer disabled:opacity-50"
          >
            <RefreshCw size={13} className={loading ? 'animate-spin' : ''} aria-hidden="true" />
            <span>Refresh</span>
          </button>

          <button
            type="button"
            onClick={handleGradeResults}
            disabled={loading}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-emerald-500/15 hover:bg-emerald-500/25 border border-emerald-500/35 text-xs font-semibold text-emerald-200 cursor-pointer disabled:opacity-50"
          >
            <Award size={13} aria-hidden="true" />
            <span>Grade Results</span>
          </button>

          <button
            type="button"
            onClick={() => setShowModelLogicDialog(true)}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-blue-500/15 hover:bg-blue-500/25 border border-blue-500/30 text-xs font-semibold text-blue-200 cursor-pointer"
          >
            <Info size={13} aria-hidden="true" />
            <span>Model Logic</span>
          </button>
        </div>
      </section>

      {/* Slate Summary KPI Strip */}
      <section aria-label="Slate summary metrics" className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: `${leagueFilter} Games`, value: slateSummary.totalGames, accent: 'text-white' },
          { label: 'Actionable Plays', value: slateSummary.actionableCount, accent: 'text-emerald-300' },
          { label: 'High Confidence', value: slateSummary.highConfCount, accent: 'text-indigo-300' },
          { label: 'Sharp Money Signals', value: slateSummary.sharpCount, accent: 'text-amber-300' },
        ].map((kpi) => (
          <div
            key={kpi.label}
            className="rounded-2xl border border-slate-800 bg-slate-900/75 px-4 py-3"
          >
            <div className="text-[11px] font-bold uppercase tracking-wider text-slate-400">{kpi.label}</div>
            <div className={`mt-1 text-2xl font-extrabold font-mono ${kpi.accent}`}>{kpi.value}</div>
          </div>
        ))}
      </section>

      {/* Data Health Pill Strip */}
      <TodayDataHealthStrip
        dataHealth={dataHealth}
        edges={edges}
        leagueFilter={leagueFilter}
        onOpenKenpomUpload={() => setShowModelLogicDialog(true)}
      />

      {/* Single-Row Underline-Indicated Tabs (never wrap; underline shape + color; no aria-controls) */}
      <div
        role="tablist"
        aria-label="Today dashboard views"
        className="flex flex-nowrap overflow-x-auto items-center gap-1 border-b border-slate-800"
      >
        {tabs.map((tab) => {
          const selected = activeSubTab === tab.id;
          return (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={selected}
              onClick={() => setActiveSubTab(tab.id)}
              className={`shrink-0 whitespace-nowrap px-4 py-2.5 text-xs sm:text-sm font-semibold border-b-2 transition-colors cursor-pointer ${
                selected
                  ? 'border-indigo-400 text-white bg-indigo-500/10'
                  : 'border-transparent text-slate-400 hover:text-slate-200 hover:border-slate-700'
              }`}
            >
              {tab.label}
            </button>
          );
        })}
      </div>

      {/* Main Error */}
      {error && (
        <div className="rounded-xl border border-rose-500/40 bg-rose-950/35 p-4 text-xs text-rose-200">
          {error}
        </div>
      )}

      {/* Active Tab Panel */}
      {activeSubTab === 'top_plays' && (
        <section role="tabpanel" aria-label="Today's top plays" className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Filter top plays">
              {[
                { id: 'all', label: 'All Plays' },
                { id: 'spread', label: 'Spreads' },
                { id: 'total', label: 'Totals' },
                { id: 'high_conf', label: 'High Conf' },
                { id: 'soon', label: 'Tipping Soon' },
              ].map((pill) => {
                const active = pickTypeFilter === pill.id;
                return (
                  <button
                    key={pill.id}
                    type="button"
                    aria-pressed={active}
                    onClick={() => setPickTypeFilter(pill.id)}
                    className={`px-3 py-1 rounded-full border text-xs font-semibold transition cursor-pointer ${
                      active
                        ? 'bg-indigo-500/20 border-indigo-400/50 text-indigo-200'
                        : 'bg-slate-900 border-slate-800 text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    {pill.label}
                  </button>
                );
              })}
            </div>

            {actionablePlays.length > 6 && (
              <button
                type="button"
                onClick={() => setPickViewMode((m) => (m === 'top6' ? 'all' : 'top6'))}
                className="text-xs font-semibold text-indigo-300 hover:text-indigo-200 underline cursor-pointer"
              >
                {pickViewMode === 'top6' ? `Show all ${actionablePlays.length} plays` : 'Show Top 6 only'}
              </button>
            )}
          </div>

          {loading ? (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              {[1, 2, 3, 4].map((i) => (
                <div key={i} className="h-44 rounded-2xl border border-slate-800 bg-slate-900/50 animate-pulse" />
              ))}
            </div>
          ) : filteredTopPlays.length === 0 ? (
            <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-8 text-center space-y-2">
              <h3 className="text-base font-bold text-slate-200">
                No Qualifying Top Plays Match This Filter
              </h3>
              <p className="text-xs text-slate-400 max-w-md mx-auto">
                Switch filters above or open the Full Board tab to inspect every game&apos;s fair line, injuries, and public splits.
              </p>
              <button
                type="button"
                onClick={() => setActiveSubTab('board')}
                className="mt-2 inline-flex px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-xs font-semibold text-white cursor-pointer"
              >
                View Full Board ({slateSummary.totalGames} games)
              </button>
            </div>
          ) : (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              {filteredTopPlays.map((item, idx) => (
                <TodayPlayCard
                  key={item.id}
                  rank={idx + 1}
                  game={item.game}
                  rec={item.rec}
                  isExpanded={expandedPickIds.has(item.id)}
                  onToggleExpand={() => toggleWhyPick(item.id)}
                  onOpenDetails={handleOpenGameDetails}
                  onAddBet={onAddBet}
                />
              ))}
            </div>
          )}
        </section>
      )}

      {activeSubTab === 'board' && (
        <section role="tabpanel" aria-label="Full daily betting board">
          <TodayFullBoardTable
            edges={edges}
            leagueFilter={leagueFilter}
            rowTopPicks={rowTopPicks}
            rowTopPicksByKey={rowTopPicksByKey}
            onOpenDetails={handleOpenGameDetails}
            onAddBet={onAddBet}
          />
        </section>
      )}

      {activeSubTab === 'parlays' && leagueFilter === 'NCAAM' && (
        <section role="tabpanel" aria-label="2-Leg Parlay Recommendations">
          <ParlayRecommendations date={selectedDate} />
        </section>
      )}

      {activeSubTab === 'march_madness' && leagueFilter === 'NCAAM' && (
        <section role="tabpanel" aria-label="March Madness Bracket">
          <MarchMadness />
        </section>
      )}

      {/* Native <dialog> Modals */}
      <TodayMatchupModal
        game={selectedGame}
        analysisResult={analysisResult}
        correlationResult={correlationResult}
        matchupProfile={selectedGame ? matchupProfiles[selectedGame.id] : null}
        isAnalyzing={isAnalyzing}
        onClose={() => {
          setSelectedGame(null);
          setAnalysisResult(null);
          setCorrelationResult(null);
        }}
        onAddBet={onAddBet}
        onAnalysisUpdated={(fresh) => setAnalysisResult(fresh)}
      />

      <ModelLogicDialog
        open={showModelLogicDialog}
        onClose={() => setShowModelLogicDialog(false)}
        dataHealth={dataHealth}
        onKenpomUploaded={fetchSchedule}
      />
    </div>
  );
};

export default Research;
