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
  BarChart2,
  PlusCircle,
  Sparkles,
  X,
  HelpCircle,
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
  fmtTimeEt,
  fmtOdds,
  fmtSigned,
  safeReasonText,
  makeMatchupKey,
  lookupTopPickForGame,
  getConfidenceMeta,
  getRecEv,
  decodeKenpomHashImport,
  getProjectedScore,
  explainPickPlainly,
  getLiveGameStatus,
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

  // Modals & rescore state
  const [selectedGame, setSelectedGame] = useState(null);
  const [analysisResult, setAnalysisResult] = useState(null);
  const [correlationResult, setCorrelationResult] = useState(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [showModelLogicDialog, setShowModelLogicDialog] = useState(false);
  const [showBetGuide, setShowBetGuide] = useState(false);
  const [rescoringSlate, setRescoringSlate] = useState(false);
  const [rescoreProgress, setRescoreProgress] = useState('');

  const BOARD_DAYS_DEFAULT = showModelPerformanceTab ? 3 : 1;

  const toggleWhyPick = (id) => {
    setExpandedPickIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const fetchSchedule = async (opts = {}) => {
    const forceRefresh = Boolean(opts && typeof opts === 'object' && opts.forceRefresh === true);
    setLoading(true);
    setError(null);
    setDegradedMode(false);
    setDegradedAsOf(null);

    const boardParams = { league: leagueFilter, date: selectedDate, days: BOARD_DAYS_DEFAULT };
    const topPicksParams = {
      date: selectedDate,
      days: BOARD_DAYS_DEFAULT,
      limit_games: 250,
      ...(forceRefresh ? { refresh: true } : {}),
    };

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
            context: item?.context || null,
            model_version: item?.model_version || null,
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
              context: tp[eid]?.context || null,
              model_version: tp[eid]?.model_version || null,
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

  // Quietly poll live in-game scores every 60s when viewing today's active slate
  useEffect(() => {
    if (selectedDate !== getTodayEtStr()) return undefined;
    const nowMs = Date.now();
    const hasActiveWindow = (edges || []).some((g) => {
      const liveInfo = getLiveGameStatus(g);
      if (liveInfo.isLive) return true;
      if (liveInfo.isFinal) return false;
      const st = g?.start_time ? new Date(g.start_time).getTime() : 0;
      return st > 0 && st <= nowMs + 10 * 60 * 1000 && st >= nowMs - 4 * 3600 * 1000;
    });
    if (!hasActiveWindow) return undefined;

    const timer = setInterval(async () => {
      try {
        const res = await api.get('/api/board', {
          params: { league: leagueFilter, date: selectedDate, days: BOARD_DAYS_DEFAULT, live: true },
        });
        if (Array.isArray(res?.data)) {
          setEdges(res.data);
        }
      } catch {
        // Ignore silent live-poll errors
      }
    }, 60000);
    return () => clearInterval(timer);
  }, [edges, leagueFilter, selectedDate, BOARD_DAYS_DEFAULT]);

  useEffect(() => {
    if (leagueFilter !== 'NCAAM' && (activeSubTab === 'march_madness' || activeSubTab === 'parlays')) {
      setActiveSubTab('top_plays');
    }
  }, [leagueFilter, activeSubTab]);

  // Auto-import KenPom ratings when opened via the 1-click browser bookmarklet (#kp_import=...)
  useEffect(() => {
    if (typeof window === 'undefined') return;
    let payloadText = null;
    try {
      const fromHash = decodeKenpomHashImport(window.location.hash);
      if (fromHash) {
        payloadText = fromHash;
        sessionStorage.setItem('pending_kenpom_import', fromHash);
        window.history.replaceState(null, '', window.location.pathname + window.location.search);
      } else {
        payloadText = sessionStorage.getItem('pending_kenpom_import');
      }
    } catch (e) {
      setToast({
        tone: 'err',
        text: `Could not read KenPom browser import: ${e?.message || 'invalid payload'}.`,
      });
      try {
        window.history.replaceState(null, '', window.location.pathname + window.location.search);
      } catch {
        // ignore
      }
      return;
    }
    if (!payloadText) return;

    let cancelled = false;
    (async () => {
      setToast({
        tone: 'warn',
        text: 'Importing KenPom ratings from your open browser tab...',
      });
      try {
        const res = await api.post('/api/admin/kenpom/upload-csv', { csv_text: payloadText });
        try {
          sessionStorage.removeItem('pending_kenpom_import');
        } catch {
          // ignore
        }
        if (cancelled) return;
        const rows = res?.data?.rows ?? 'all';
        const asof = res?.data?.asof_date ? ` (${res.data.asof_date})` : '';
        setToast({
          tone: 'ok',
          text: `KenPom updated from your browser tab: imported ${rows} teams${asof}. Refreshing model picks...`,
        });
        await fetchSchedule();
      } catch (err) {
        if (err?.response?.status !== 403) {
          try {
            sessionStorage.removeItem('pending_kenpom_import');
          } catch {
            // ignore
          }
        }
        if (cancelled) return;
        setToast({
          tone: 'err',
          text: `KenPom import failed: ${err?.response?.data?.detail || err?.message || 'Unknown error'}`,
        });
      }
    })();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleGradeResults = async () => {
    setLoading(true);
    try {
      const res = await api.post('/api/research/grade');
      setToast({
        tone: 'ok',
        text: `Grading complete: ${res?.data?.graded || 0} model predictions updated.`,
      });
      await fetchSchedule({ forceRefresh: true });
    } catch (err) {
      setToast({
        tone: 'err',
        text: `Grading failed: ${err?.response?.data?.detail || err?.message || 'Unknown error'}`,
      });
      setLoading(false);
    }
  };

  const handleRescoreSlate = async () => {
    if (rescoringSlate || leagueFilter !== 'NCAAM') return;
    setRescoringSlate(true);
    setRescoreProgress('Re-scoring slate...');
    setToast({
      tone: 'warn',
      text: `Re-scoring ${selectedDate} NCAAM slate with latest KenPom, Haslametrics & Torvik projections...`,
    });
    try {
      let offset = 0;
      let done = false;
      let loops = 0;
      let totalOk = 0;
      let eventsTotal = 0;
      while (!done && loops < 10) {
        loops += 1;
        const res = await api.post('/api/jobs/build_daily_top_picks', null, {
          params: {
            date: selectedDate,
            days: 1,
            offset,
            max_events: 20,
            limit_games: 250,
          },
        });
        const d = res?.data || {};
        eventsTotal = Number(d.events_total || eventsTotal || 0);
        totalOk += Number(d.ok || 0);
        const nextOffset = Number(d.next_offset ?? offset + Number(d.processed || 0));
        done = Boolean(d.done) || nextOffset <= offset;
        offset = nextOffset;
        if (eventsTotal > 0) {
          setRescoreProgress(`Re-scoring ${Math.min(offset, eventsTotal)}/${eventsTotal}...`);
        }
      }
      setToast({
        tone: 'ok',
        text: `Slate re-scored (${totalOk} games evaluated). Refreshing Top Plays & Full Board...`,
      });
      await fetchSchedule({ forceRefresh: true });
    } catch (err) {
      if (err?.response?.status === 401 || err?.response?.status === 403) {
        setAuthPromptOpen(true);
      }
      setToast({
        tone: 'err',
        text: `Re-score failed: ${err?.response?.data?.detail || err?.message || 'Could not re-score slate'}`,
      });
    } finally {
      setRescoringSlate(false);
      setRescoreProgress('');
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

      const freshRec = (merged?.recommendations || [])[0] || null;
      const freshCtx =
        merged?.context ||
        (() => {
          try {
            return typeof merged?.context_json === 'string' ? JSON.parse(merged.context_json) : merged?.context_json || null;
          } catch {
            return null;
          }
        })();
      setRowTopPicks((prev) => ({
        ...prev,
        [game.id]: {
          ...(prev[game.id] || {}),
          rec: freshRec,
          isActionable: Boolean(freshRec),
          reason: freshRec ? null : (merged?.block_reason || merged?.headline || prev[game.id]?.reason || null),
          context: freshCtx || prev[game.id]?.context || null,
          model_version: merged?.model_version || prev[game.id]?.model_version || null,
          analyzedAt: new Date().toISOString(),
        },
      }));
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
        plays.push({ id: game.id, game, rec: meta.rec, context: meta.context || null, conf: getConfidenceMeta(meta.rec) });
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
      plays.push({ id: eid, game: synthGame, rec: meta.rec, context: meta.context || null, conf: getConfidenceMeta(meta.rec) });
    });

    plays.sort((a, b) => (getRecEv(b.rec) ?? -999) - (getRecEv(a.rec) ?? -999));

    const highConf = plays.filter((p) => p.conf.tier === 'HIGH').length;
    const liveCount = gamesForLeague.filter((g) => getLiveGameStatus(g).isLive).length;
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
        liveCount,
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

  const pickFilterCounts = useMemo(() => {
    const nowMs = Date.now();
    let spread = 0;
    let total = 0;
    let soon = 0;
    actionablePlays.forEach(({ game, rec }) => {
      const mkt = String(rec?.bet_type || rec?.market_type || '').toUpperCase();
      if (mkt === 'SPREAD') spread += 1;
      else if (mkt === 'TOTAL') total += 1;
      const st = game?.start_time ? new Date(game.start_time).getTime() : 0;
      if (st > nowMs - 30 * 60000 && st <= nowMs + 3 * 3600 * 1000) soon += 1;
    });
    return {
      all: actionablePlays.length,
      high_conf: slateSummary.highConfCount,
      spread,
      total,
      soon,
    };
  }, [actionablePlays, slateSummary.highConfCount]);

  const closestLeans = useMemo(() => {
    const gamesForLeague = (edges || []).filter((e) => !leagueFilter || e.sport === leagueFilter);
    const leans = [];
    gamesForLeague.forEach((game) => {
      const meta = lookupTopPickForGame(game, rowTopPicks, rowTopPicksByKey);
      if (meta?.isActionable) return;
      const ctx = meta?.context || null;
      const lean = ctx?.closest_lean || null;
      if (!lean || !lean.selection) return;
      const evVal = lean.ev != null ? Number(lean.ev) : null;
      const edgePts = lean.edge_points != null ? Number(lean.edge_points) : 0;
      if ((evVal !== null && evVal > 0) || Math.abs(edgePts) >= 0.8) {
        leans.push({
          id: game.id,
          game,
          meta,
          ctx,
          lean,
          evVal: evVal ?? -999,
          edgePts,
        });
      }
    });
    leans.sort((a, b) => {
      if (a.evVal !== b.evVal) return b.evVal - a.evVal;
      return Math.abs(b.edgePts) - Math.abs(a.edgePts);
    });
    return leans.slice(0, 6);
  }, [edges, leagueFilter, rowTopPicks, rowTopPicksByKey]);

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

      {/* Unified Compact Header + Inline Summary Pills */}
      <div className="flex flex-col xl:flex-row xl:items-center justify-between gap-3">
        <div className="space-y-2">
          <div>
            <h2 className="text-xl sm:text-2xl font-bold text-white tracking-tight">
              Today&apos;s Slate &amp; Best Bets
            </h2>
            <p className="text-xs text-slate-400 mt-0.5">
              Independent team power ratings compared directly against live sportsbook odds.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-slate-900 border border-slate-800 text-slate-200 font-semibold">
              <strong className="font-mono text-white">{slateSummary.totalGames}</strong>
              <span className="text-slate-400">{leagueFilter} Games</span>
            </span>
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 font-semibold">
              <strong className="font-mono">{slateSummary.actionableCount}</strong>
              <span>Actionable Plays</span>
            </span>
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-indigo-500/10 border border-indigo-400/30 text-indigo-200 font-semibold">
              <strong className="font-mono">{slateSummary.highConfCount}</strong>
              <span>High Confidence</span>
            </span>
            {slateSummary.liveCount > 0 && (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-rose-500/15 border border-rose-500/40 text-rose-200 font-semibold">
                <span className="w-1.5 h-1.5 rounded-full bg-rose-400 animate-pulse" aria-hidden="true" />
                <strong className="font-mono">{slateSummary.liveCount}</strong>
                <span>Live Now</span>
              </span>
            )}
            {slateSummary.sharpCount > 0 && (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-amber-500/10 border border-amber-500/30 text-amber-200 font-semibold">
                <strong className="font-mono">{slateSummary.sharpCount}</strong>
                <span>Sharp Signals</span>
              </span>
            )}
          </div>
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

          {selectedDate !== getTodayEtStr() && (
            <button
              type="button"
              onClick={() => setSelectedDate(getTodayEtStr())}
              className="px-2.5 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-xs font-semibold text-indigo-200 cursor-pointer"
            >
              Today
            </button>
          )}

          {leagueFilter === 'NCAAM' && (
            <button
              type="button"
              onClick={handleRescoreSlate}
              disabled={loading || rescoringSlate}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-indigo-600/25 hover:bg-indigo-600/40 border border-indigo-400/50 text-xs font-semibold text-indigo-100 cursor-pointer disabled:opacity-50"
            >
              <Sparkles size={13} className={rescoringSlate ? 'animate-pulse' : ''} aria-hidden="true" />
              <span>{rescoringSlate ? (rescoreProgress || 'Re-scoring...') : 'Re-Score Slate'}</span>
            </button>
          )}

          <button
            type="button"
            onClick={() => fetchSchedule({ forceRefresh: true })}
            disabled={loading || rescoringSlate}
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
            onClick={() => setShowBetGuide((v) => !v)}
            aria-expanded={showBetGuide}
            className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl border text-xs font-semibold cursor-pointer ${
              showBetGuide
                ? 'bg-emerald-500/20 border-emerald-400/50 text-emerald-200'
                : 'bg-slate-800 hover:bg-slate-700 border-slate-700 text-slate-200'
            }`}
          >
            <HelpCircle size={13} aria-hidden="true" />
            <span>Betting Terms Guide</span>
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
      </div>

      {/* Collapsible Plain-English Betting Cheat Sheet */}
      {showBetGuide && (
        <div className="rounded-2xl border border-emerald-500/30 bg-slate-900/90 p-4 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 text-xs">
          <div className="rounded-xl bg-slate-950/75 border border-slate-800 p-3 space-y-1">
            <div className="font-bold text-emerald-300">+ Underdog Spread (e.g. +37.5)</div>
            <p className="text-slate-300 leading-relaxed">
              The team gets <strong>+37.5 bonus points</strong> added to their final score. You win if they win OR lose by 37 or fewer points.
            </p>
          </div>
          <div className="rounded-xl bg-slate-950/75 border border-slate-800 p-3 space-y-1">
            <div className="font-bold text-sky-300">- Favorite Spread (e.g. -4.5)</div>
            <p className="text-slate-300 leading-relaxed">
              The team is favored and spots <strong>4.5 points</strong>. You win only if they win the final score by 5 or more points.
            </p>
          </div>
          <div className="rounded-xl bg-slate-950/75 border border-slate-800 p-3 space-y-1">
            <div className="font-bold text-indigo-300">Total (OVER / UNDER 146.5)</div>
            <p className="text-slate-300 leading-relaxed">
              Add <strong>both teams&apos; final scores</strong> together. OVER wins at 147+ combined points; UNDER wins at 146 or fewer.
            </p>
          </div>
          <div className="rounded-xl bg-slate-950/75 border border-slate-800 p-3 space-y-1">
            <div className="font-bold text-amber-300">Model Cushion &amp; +EV%</div>
            <p className="text-slate-300 leading-relaxed">
              <strong>+EV%</strong> is expected long-term profit per $100 staked. More point cushion vs. sportsbooks = bigger margin of safety.
            </p>
          </div>
        </div>
      )}

      {/* Collapsible Data Health Bar */}
      <TodayDataHealthStrip
        dataHealth={dataHealth}
        edges={edges}
        leagueFilter={leagueFilter}
        onOpenKenpomUpload={() => setShowModelLogicDialog(true)}
      />

      {/* Single-Row Underline-Indicated Tabs */}
      <div
        role="tablist"
        aria-label="Today dashboard views"
        className="today-tablist"
      >
        {tabs.map((tab) => {
          const selected = activeSubTab === tab.id;
          return (
            <button
              key={tab.id}
              id={`today-tab-${tab.id}`}
              type="button"
              role="tab"
              aria-selected={selected}
              onClick={(e) => {
                setActiveSubTab(tab.id);
                e.currentTarget.scrollIntoView({ block: 'nearest', inline: 'nearest' });
              }}
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
        <section role="tabpanel" aria-labelledby="today-tab-top_plays" className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Filter top plays">
              {[
                { id: 'all', label: `All Plays (${pickFilterCounts.all})` },
                { id: 'high_conf', label: `High Conf (${pickFilterCounts.high_conf})` },
                { id: 'spread', label: `Spreads (${pickFilterCounts.spread})` },
                { id: 'total', label: `Totals (${pickFilterCounts.total})` },
                { id: 'soon', label: `Tipping Soon (${pickFilterCounts.soon})` },
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
            <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-8 text-center space-y-3">
              <h3 className="text-base font-bold text-slate-200">
                {actionablePlays.length === 0
                  ? 'No Plays Passed Strict Publish Risk Gates'
                  : 'No Qualifying Top Plays Match This Filter'}
              </h3>
              <p className="text-xs text-slate-400 max-w-md mx-auto">
                {actionablePlays.length === 0
                  ? 'Try Re-Scoring the slate after KenPom/odds updates, review Closest Model Leans below, or open the Full Board to see Model Fair spreads and totals for every game.'
                  : 'Switch filters above or open the Full Board tab to inspect every game’s fair line, injuries, and public splits.'}
              </p>
              <div className="flex flex-wrap items-center justify-center gap-2 pt-1">
                {leagueFilter === 'NCAAM' && (
                  <button
                    type="button"
                    onClick={handleRescoreSlate}
                    disabled={rescoringSlate}
                    className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-xs font-semibold text-white cursor-pointer disabled:opacity-50"
                  >
                    <Sparkles size={13} aria-hidden="true" />
                    <span>{rescoringSlate ? (rescoreProgress || 'Re-scoring...') : 'Re-Score Slate'}</span>
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => setActiveSubTab('board')}
                  className="inline-flex px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-xs font-semibold text-white cursor-pointer"
                >
                  View Full Board ({slateSummary.totalGames} games)
                </button>
              </div>
            </div>
          ) : (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              {filteredTopPlays.map((item, idx) => (
                <TodayPlayCard
                  key={item.id}
                  rank={idx + 1}
                  game={item.game}
                  rec={item.rec}
                  context={item.context}
                  isExpanded={expandedPickIds.has(item.id)}
                  onToggleExpand={() => toggleWhyPick(item.id)}
                  onOpenDetails={handleOpenGameDetails}
                  onAddBet={onAddBet}
                />
              ))}
            </div>
          )}

          {/* Closest Model Leans (Near-Miss Board) */}
          {actionablePlays.length < 4 && closestLeans.length > 0 && (
            <section className="pt-2 space-y-3">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <div>
                  <h3 className="text-sm font-bold text-indigo-200 tracking-tight">
                    Closest Model Leans (Below Strict Publish Gate)
                  </h3>
                  <p className="text-[11px] text-slate-400">
                    Top near-miss edges ranked by expected value — helpful when strict publish gates hold plays back.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setActiveSubTab('board')}
                  className="text-xs font-semibold text-indigo-300 hover:text-indigo-200 underline cursor-pointer"
                >
                  Compare all Model Fair lines on Full Board
                </button>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
                {closestLeans.map(({ id, game, lean, meta, ctx }) => {
                  const reasonTxt = safeReasonText(lean.reason || meta?.reason);
                  const projScore = getProjectedScore(game, { context: ctx }, lean);
                  const plainLean = explainPickPlainly(lean, game);
                  const liveInfo = getLiveGameStatus(game, lean);
                  return (
                    <article
                      key={id}
                      className="rounded-2xl border border-slate-800 bg-slate-900/75 p-4 flex flex-col justify-between gap-3"
                    >
                      <div className="space-y-1.5">
                        <div className="flex items-center justify-between gap-2 text-[11px] font-mono text-slate-400">
                          {liveInfo.isLive ? (
                            <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-rose-500/20 border border-rose-500/40 text-rose-200 font-bold text-[10px]">
                              <span className="w-1.5 h-1.5 rounded-full bg-rose-400 animate-pulse" aria-hidden="true" />
                              LIVE {liveInfo.hasScore ? `(${liveInfo.awayScore}-${liveInfo.homeScore})` : ''}
                            </span>
                          ) : liveInfo.isFinal ? (
                            <span className="px-1.5 py-0.5 rounded bg-slate-800 text-slate-200 font-bold text-[10px]">
                              FINAL {liveInfo.hasScore ? `(${liveInfo.awayScore}-${liveInfo.homeScore})` : ''}
                            </span>
                          ) : (
                            <span>{fmtTimeEt(game.start_time)} ET</span>
                          )}
                          <span className="px-2 py-0.5 rounded-full bg-indigo-500/15 border border-indigo-400/30 text-indigo-200 font-bold uppercase text-[10px]">
                            {lean.bet_type || 'LEAN'} NEAR-MISS
                          </span>
                        </div>
                        <div className="text-xs font-semibold text-slate-200 truncate">
                          {game.away_team} @ {game.home_team}
                        </div>
                        {projScore && (
                          <div className="text-[11px] text-sky-300 font-medium truncate">
                            Projected Final: {projScore.text}
                          </div>
                        )}
                        <div className="flex items-baseline justify-between gap-2 pt-0.5">
                          <span className="text-sm font-bold text-white truncate">
                            {lean.selection}
                          </span>
                          <span className="text-xs font-mono font-bold text-indigo-300 shrink-0">
                            {lean.edge_points != null ? `${Math.abs(Number(lean.edge_points)).toFixed(1)} pt gap` : ''}{' '}
                            {lean.ev_pct != null ? `(${fmtSigned(lean.ev_pct, 1)}%)` : ''}
                          </span>
                        </div>
                        {plainLean?.howItWins && (
                          <p className="text-[11px] text-emerald-200/90 leading-snug">
                            {plainLean.howItWins}
                          </p>
                        )}
                        <div className="text-[11px] font-mono text-slate-400 flex flex-wrap items-center gap-x-2">
                          <span>Sportsbook: {lean.market_line != null ? lean.market_line : '—'} ({fmtOdds(lean.price)})</span>
                          <span>·</span>
                          <span className="text-indigo-300">Model Fair: {lean.fair_line != null ? lean.fair_line : '—'}</span>
                        </div>
                        {reasonTxt && (
                          <p className="text-[11px] text-slate-400 line-clamp-2">{reasonTxt}</p>
                        )}
                      </div>

                      <div className="flex items-center justify-between gap-2 pt-2 border-t border-slate-800/80">
                        <button
                          type="button"
                          onClick={() => handleOpenGameDetails(game)}
                          aria-label={`Details for ${game.away_team} at ${game.home_team}`}
                          className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-xs font-semibold text-slate-100 cursor-pointer"
                        >
                          <BarChart2 size={12} aria-hidden="true" />
                          <span>Details</span>
                        </button>
                        {onAddBet && (
                          <button
                            type="button"
                            onClick={() =>
                              onAddBet({
                                sport: game.sport || leagueFilter,
                                game: `${game.away_team} @ ${game.home_team}`,
                                market: lean.bet_type,
                                pick: lean.selection,
                                line: lean.market_line,
                                odds: lean.price,
                                book: lean.book || 'Consensus',
                              })
                            }
                            aria-label={`Log Lean ${lean.selection}`}
                            className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-slate-800/90 hover:bg-slate-700 border border-slate-700 text-xs font-semibold text-slate-200 cursor-pointer"
                          >
                            <PlusCircle size={12} aria-hidden="true" />
                            <span>Log Lean</span>
                          </button>
                        )}
                      </div>
                    </article>
                  );
                })}
              </div>
            </section>
          )}
        </section>
      )}

      {activeSubTab === 'board' && (
        <section role="tabpanel" aria-labelledby="today-tab-board">
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
        <section role="tabpanel" aria-labelledby="today-tab-parlays">
          <ParlayRecommendations date={selectedDate} />
        </section>
      )}

      {activeSubTab === 'march_madness' && leagueFilter === 'NCAAM' && (
        <section role="tabpanel" aria-labelledby="today-tab-march_madness">
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
