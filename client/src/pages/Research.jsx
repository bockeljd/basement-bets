import React, { useEffect, useMemo, useRef, useState } from 'react';
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
  SlidersHorizontal,
  X,
} from 'lucide-react';
import api from '../api/axios';
import { loadCache } from '../utils/httpCache';
import ParlayRecommendations from '../components/ParlayRecommendations';
import TodayDataHealthStrip, { summarizeDataHealth } from '../components/today/TodayDataHealthStrip';
import SlatePublication from '../components/today/SlatePublication';
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
  getRecQualityScore,
  hasTop6RiskFlag,
  decodeKenpomHashImport,
  getProjectedScore,
  getLiveGameStatus,
  dedupeBoardGames,
} from '../components/today/todayHelpers';
import '../styles/todayDashboard.css';

const IS_MLB_SEASON = [2, 3, 4, 5, 6, 7, 8, 9].includes(new Date().getMonth());
const LEAGUES = IS_MLB_SEASON ? ['NCAAM', 'MLB', 'NFL', 'EPL'] : ['NCAAM', 'NFL', 'EPL'];

const Research = ({ onAddBet, bankroll = null, showModelPerformanceTab = true }) => {
  const [edges, setEdges] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [toast, setToast] = useState(null); // { tone: 'ok'|'err'|'warn', text }
  const [authPromptOpen, setAuthPromptOpen] = useState(false);
  const [authPassword, setAuthPassword] = useState('');

  const [leagueFilter, setLeagueFilter] = useState('NCAAM');
  const [selectedDate, setSelectedDate] = useState(getTodayEtStr());
  const [activeSubTab, setActiveSubTab] = useState('top_plays'); // top_plays | board | parlays

  const [rowTopPicks, setRowTopPicks] = useState({});
  const [rowTopPicksByKey, setRowTopPicksByKey] = useState({});
  const [matchupProfiles, setMatchupProfiles] = useState({});
  const [dataHealth, setDataHealth] = useState([]);
  const [degradedMode, setDegradedMode] = useState(false);
  const [degradedAsOf, setDegradedAsOf] = useState(null);

  // Top plays controls
  const [pickTypeFilter, setPickTypeFilter] = useState('all'); // all | spread | total | high_conf | soon
  const [pickViewMode, setPickViewMode] = useState('top6'); // top6 | all

  // Modals, popover & rescore state
  const [selectedGame, setSelectedGame] = useState(null);
  const [analysisResult, setAnalysisResult] = useState(null);
  const [correlationResult, setCorrelationResult] = useState(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [showModelLogicDialog, setShowModelLogicDialog] = useState(false);
  const [rescoringSlate, setRescoringSlate] = useState(false);
  const [rescoreProgress, setRescoreProgress] = useState('');
  const [toolsFallbackOpen, setToolsFallbackOpen] = useState(false);
  const toolsPopoverRef = useRef(null);
  const tablistRef = useRef(null);

  const supportsPopover =
    typeof HTMLElement !== 'undefined' && Object.hasOwn(HTMLElement.prototype, 'popover');

  const closeToolsPopover = () => {
    try {
      toolsPopoverRef.current?.hidePopover?.();
    } catch {
      // ignore if not open or unsupported
    }
    setToolsFallbackOpen(false);
  };

  const BOARD_DAYS_DEFAULT = showModelPerformanceTab ? 3 : 1;

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

      const dedupedBoard = dedupeBoardGames(Array.isArray(boardRes.data) ? boardRes.data : []);
      setEdges(dedupedBoard);
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
      } else if (leagueFilter === 'MLB' && dedupedBoard.length > 0 && Array.isArray(mlbRes?.data?.predictions)) {
        const latestPreds = new Map();
        mlbRes.data.predictions
          .filter((p) => !p.day_et || String(p.day_et).slice(0, 10) === selectedDate)
          .forEach((p) => {
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
          setEdges(dedupeBoardGames(cachedBoard.payload || []));
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
          setEdges(dedupeBoardGames(res.data));
        }
      } catch {
        // Ignore silent live-poll errors
      }
    }, 60000);
    return () => clearInterval(timer);
  }, [edges, leagueFilter, selectedDate, BOARD_DAYS_DEFAULT]);

  useEffect(() => {
    if (leagueFilter !== 'NCAAM' && activeSubTab === 'parlays') {
      setActiveSubTab('top_plays');
    }
  }, [leagueFilter, activeSubTab]);

  const importKenpomPayload = async (payloadText) => {
    setToast({
      tone: 'warn',
      text: 'Importing KenPom ratings from your browser...',
    });
    try {
      const res = await api.post('/api/admin/kenpom/upload-csv', { csv_text: payloadText });
      try {
        sessionStorage.removeItem('pending_kenpom_import');
      } catch {
        // ignore
      }
      const rows = res?.data?.rows ?? 'all';
      const asof = res?.data?.asof_date ? ` (${res.data.asof_date})` : '';
      const ds = res?.data?.datasets_synced || {};
      const extras = [
        ds.four_factors > 0 ? 'Four Factors' : null,
        ds.height_experience > 0 ? 'Height/Exp' : null,
        ds.home_court > 0 ? 'HCA' : null,
        ds.player_stats > 0 ? 'Players' : null,
        ds.ref_ratings > 0 ? 'Refs' : null,
        ds.fanmatch_games > 0 ? 'FanMatch' : null,
      ].filter(Boolean);
      const extraMsg = extras.length ? ` + ${extras.join(', ')}` : '';
      setToast({
        tone: 'ok',
        text: `KenPom updated (${rows} teams${extraMsg}${asof}). Refreshing model picks...`,
      });
      await fetchSchedule();
      return true;
    } catch (err) {
      if (err?.response?.status !== 403) {
        try {
          sessionStorage.removeItem('pending_kenpom_import');
        } catch {
          // ignore
        }
      }
      setToast({
        tone: 'err',
        text: `KenPom import failed: ${err?.response?.data?.detail || err?.message || 'Unknown error'}`,
      });
      return false;
    }
  };

  const handlePasteKenpomClipboard = async () => {
    try {
      if (!navigator.clipboard || typeof navigator.clipboard.readText !== 'function') {
        setShowModelLogicDialog(true);
        setToast({
          tone: 'warn',
          text: 'Clipboard access blocked here — press Cmd+V inside the box to import KenPom.',
        });
        return;
      }
      const text = (await navigator.clipboard.readText()) || '';
      if (text.trim().length < 50 || !/(NetRtg|AdjEM|ORtg|AdjOE|_kp_bundle|\t)/i.test(text)) {
        setShowModelLogicDialog(true);
        setToast({
          tone: 'warn',
          text: 'Copy kenpom.com first (Cmd+A then Cmd+C while viewing kenpom.com), then click Paste Sync.',
        });
        return;
      }
      await importKenpomPayload(text);
    } catch {
      setShowModelLogicDialog(true);
      setToast({
        tone: 'warn',
        text: 'Allow clipboard access or press Cmd+V into the KenPom box below.',
      });
    }
  };

  // Auto-import KenPom ratings when opened via the 1-click browser bookmarklet (#kp_import=...)
  useEffect(() => {
    if (typeof window === 'undefined') return;
    let cancelled = false;

    const runHashImportCheck = () => {
      if (window.location.hash === '#kenpom-bookmarklet') {
        setShowModelLogicDialog(true);
        try {
          window.history.replaceState(null, '', window.location.pathname + window.location.search);
        } catch {
          // ignore
        }
        return;
      }

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
      if (!payloadText || cancelled) return;
      importKenpomPayload(payloadText);
    };

    runHashImportCheck();
    window.addEventListener('hashchange', runHashImportCheck);
    return () => {
      cancelled = true;
      window.removeEventListener('hashchange', runHashImportCheck);
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
      setRescoreProgress('Refreshing live sportsbook odds...');
      try {
        await api.post('/api/jobs/ingest_odds');
      } catch {
        // continue with existing odds if cron auth is required on ingest_odds
      }
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
      try {
        await api.post('/api/jobs/lock_morning_slate');
      } catch {
        // best-effort rolling Top 6 refresh
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
          analyzedAt: merged?.analyzed_at || prev[game.id]?.analyzedAt || null,
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
        plays.push({ id: game.id, game, analyzedAt: meta.analyzedAt, rec: meta.rec, context: meta.context || null, conf: getConfidenceMeta(meta.rec) });
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
      plays.push({ id: eid, game: synthGame, analyzedAt: meta.analyzedAt, rec: meta.rec, context: meta.context || null, conf: getConfidenceMeta(meta.rec) });
    });

    plays.sort((a, b) => {
      const riskA = hasTop6RiskFlag(a.rec) ? 1 : 0;
      const riskB = hasTop6RiskFlag(b.rec) ? 1 : 0;
      if (riskA !== riskB) return riskA - riskB;
      const qDiff = getRecQualityScore(b.rec) - getRecQualityScore(a.rec);
      if (Math.abs(qDiff) > 1e-6) return qDiff;
      return (getRecEv(b.rec) ?? -999) - (getRecEv(a.rec) ?? -999);
    });

    const highConf = plays.filter((p) => p.conf.tier === 'HIGH').length;
    const liveGamesList = gamesForLeague.filter((g) => getLiveGameStatus(g).isLive);
    const liveCount = liveGamesList.length;
    const liveTrendingWinCount = liveGamesList.filter((g) => {
      const meta = lookupTopPickForGame(g, rowTopPicks, rowTopPicksByKey);
      const targetRec = meta?.rec || meta?.context?.closest_lean || null;
      if (!targetRec) return false;
      const status = getLiveGameStatus(g, targetRec, meta?.context || null);
      return status.trendVerdict === 'TRENDING_WIN';
    }).length;
    const sharpCount = plays.filter((p) => {
      const tags = Array.isArray(p.rec?.movement_tags) ? p.rec.movement_tags : [];
      return tags.includes('sharp_backing') || tags.includes('rlm_confirmed');
    }).length;
    let staleOddsCount = 0;
    let unlinedCount = 0;
    let trueNoBetCount = 0;
    gamesForLeague.forEach((game) => {
      const meta = lookupTopPickForGame(game, rowTopPicks, rowTopPicksByKey);
      if (!meta || meta.isActionable) return;
      const rLow = String(meta.reason || '').toLowerCase();
      if (meta.odds_status === 'stale_odds' || rLow.includes('stale')) {
        staleOddsCount += 1;
      } else if (meta.odds_status === 'unlined' || rLow.includes('no line') || rLow.includes('waiting') || rLow.includes('unlined')) {
        unlinedCount += 1;
      } else {
        trueNoBetCount += 1;
      }
    });

    return {
      actionablePlays: plays,
      slateSummary: {
        totalGames: gamesForLeague.length,
        actionableCount: plays.length,
        highConfCount: highConf,
        sharpCount,
        liveCount,
        liveTrendingWinCount,
        staleOddsCount,
        unlinedCount,
        trueNoBetCount,
      },
    };
  }, [edges, leagueFilter, rowTopPicks, rowTopPicksByKey, selectedDate]);

  const top6SlatePlays = useMemo(
    () => actionablePlays.filter(({ rec }) => !hasTop6RiskFlag(rec)).slice(0, 6),
    [actionablePlays]
  );

  // Apply Pick Scope (Top 6 vs All Picks) BEFORE sub-filtering by Spread/Total/High Conf/Soon,
  // matching Model Performance so sub-filters inspect the Top 6 slate rather than promoting #7+.
  const scopedTopPlays = useMemo(() => {
    const base = pickViewMode === 'top6' ? top6SlatePlays : actionablePlays;
    return base.map((item, idx) => ({ ...item, slateRank: idx + 1 }));
  }, [pickViewMode, top6SlatePlays, actionablePlays]);

  const filteredTopPlays = useMemo(() => {
    const nowMs = Date.now();
    return scopedTopPlays.filter(({ game, rec, conf }) => {
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
  }, [scopedTopPlays, pickTypeFilter]);

  const pickFilterCounts = useMemo(() => {
    const nowMs = Date.now();
    let spread = 0;
    let total = 0;
    let high_conf = 0;
    let soon = 0;
    scopedTopPlays.forEach(({ game, rec, conf }) => {
      const mkt = String(rec?.bet_type || rec?.market_type || '').toUpperCase();
      if (mkt === 'SPREAD') spread += 1;
      else if (mkt === 'TOTAL') total += 1;
      if (conf.tier === 'HIGH') high_conf += 1;
      const st = game?.start_time ? new Date(game.start_time).getTime() : 0;
      if (st > nowMs - 30 * 60000 && st <= nowMs + 3 * 3600 * 1000) soon += 1;
    });
    return {
      all: scopedTopPlays.length,
      high_conf,
      spread,
      total,
      soon,
    };
  }, [scopedTopPlays]);

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

  const healthSummary = useMemo(
    () => summarizeDataHealth(dataHealth, edges, leagueFilter),
    [dataHealth, edges, leagueFilter]
  );

  const tabs = useMemo(() => {
    const base = [
      { id: 'top_plays', label: `Best Bets (${actionablePlays.length})` },
      { id: 'board', label: `All Games (${slateSummary.totalGames})` },
    ];
    if (leagueFilter === 'NCAAM') {
      base.push({ id: 'parlays', label: '2-Leg Parlays' });
    }
    return base;
  }, [actionablePlays.length, slateSummary.totalGames, leagueFilter]);

  useEffect(() => {
    const activeBtn = tablistRef.current?.querySelector(`[data-tab-id="${activeSubTab}"]`);
    if (activeBtn && typeof activeBtn.scrollIntoView === 'function') {
      activeBtn.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    }
  }, [activeSubTab]);

  const handleTabListKeyDown = (e) => {
    const keys = ['ArrowRight', 'ArrowLeft', 'Home', 'End'];
    if (!keys.includes(e.key) || tabs.length === 0) return;
    const focusedIndex = tabs.findIndex(
      (t) => t.id === document.activeElement?.getAttribute?.('data-tab-id')
    );
    if (focusedIndex === -1) return;
    e.preventDefault();
    let nextIdx = focusedIndex;
    if (e.key === 'ArrowRight') nextIdx = (focusedIndex + 1) % tabs.length;
    else if (e.key === 'ArrowLeft') nextIdx = (focusedIndex - 1 + tabs.length) % tabs.length;
    else if (e.key === 'Home') nextIdx = 0;
    else if (e.key === 'End') nextIdx = tabs.length - 1;
    const nextBtn = tablistRef.current?.querySelector(`[data-tab-id="${tabs[nextIdx].id}"]`);
    nextBtn?.focus();
  };

  const activeSelectedGame = selectedGame
    ? (edges.find((g) => g.id === selectedGame.id) || selectedGame)
    : null;

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

      {/* Streamlined Single-Row Page Header & Core Controls */}
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3">
        <div>
          <h2 className="text-xl sm:text-2xl font-bold text-white tracking-tight">
            Today&apos;s Picks
          </h2>
          <div className="flex flex-wrap items-center gap-1.5 text-xs sm:text-sm text-slate-400 mt-1">
            <button
              type="button"
              onClick={() => setActiveSubTab('board')}
              className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-slate-900 hover:bg-slate-800 border border-slate-800 text-slate-200 font-medium cursor-pointer transition-colors"
            >
              <strong className="font-mono text-white">{slateSummary.totalGames}</strong>
              <span>{leagueFilter} {slateSummary.totalGames === 1 ? 'game' : 'games'}</span>
            </button>
            <button
              type="button"
              onClick={() => setActiveSubTab('top_plays')}
              className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full border font-semibold cursor-pointer transition-colors ${
                actionablePlays.length > 0
                  ? 'bg-emerald-500/10 hover:bg-emerald-500/20 border-emerald-500/30 text-emerald-300'
                  : 'bg-slate-900 hover:bg-slate-800 border-slate-800 text-slate-300'
              }`}
            >
              <strong className="font-mono">{actionablePlays.length}</strong>
              <span>best {actionablePlays.length === 1 ? 'bet' : 'bets'}</span>
            </button>
            {actionablePlays.length < 4 && closestLeans.length > 0 && (
              <button
                type="button"
                onClick={() => {
                  setActiveSubTab('top_plays');
                  setTimeout(() => {
                    document.getElementById('close-calls-heading')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
                  }, 40);
                }}
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-slate-900 hover:bg-slate-800 border border-slate-800 text-indigo-200 font-medium cursor-pointer transition-colors"
              >
                <strong className="font-mono">{closestLeans.length}</strong>
                <span>close calls</span>
              </button>
            )}
            {slateSummary.liveCount > 0 && (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-rose-500/15 border border-rose-500/35 text-rose-300 font-semibold">
                <span className="w-1.5 h-1.5 rounded-full bg-rose-400 animate-pulse" aria-hidden="true" />
                <span>
                  {slateSummary.liveCount} live now
                  {slateSummary.liveTrendingWinCount > 0 ? ` (${slateSummary.liveTrendingWinCount} winning pace)` : ''}
                </span>
              </span>
            )}
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div
            role="group"
            aria-label="Select sport"
            className="inline-flex items-center gap-1 rounded-xl bg-slate-900 border border-slate-700 p-0.5 min-h-[36px]"
          >
            {LEAGUES.map((lg) => {
              const active = leagueFilter === lg;
              return (
                <button
                  key={lg}
                  type="button"
                  aria-pressed={active}
                  onClick={() => setLeagueFilter(lg)}
                  className={`px-2.5 py-1 rounded-lg text-xs font-bold transition-colors cursor-pointer ${
                    active
                      ? 'bg-indigo-600 text-white shadow-sm'
                      : 'text-slate-400 hover:text-slate-100 hover:bg-slate-800/70'
                  }`}
                >
                  {lg}
                </button>
              );
            })}
          </div>

          <div className="flex items-center rounded-xl bg-slate-900 border border-slate-700 p-0.5 min-h-[36px]">
            <button
              type="button"
              aria-label="Previous day"
              onClick={() => setSelectedDate((d) => shiftEtDateStr(d, -1))}
              className="p-1.5 rounded-lg text-slate-300 hover:text-white hover:bg-slate-800 cursor-pointer"
            >
              <ChevronLeft size={14} aria-hidden="true" />
            </button>
            <label htmlFor="today-date-picker" className="sr-only">
              Select date
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
              className="min-h-[36px] px-2.5 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-xs font-semibold text-indigo-200 cursor-pointer"
            >
              Today
            </button>
          )}

          <button
            type="button"
            onClick={() => fetchSchedule({ forceRefresh: true })}
            disabled={loading || rescoringSlate}
            className="min-h-[36px] inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-xs font-semibold text-slate-100 cursor-pointer disabled:opacity-50"
          >
            <RefreshCw size={13} className={loading ? 'animate-spin' : ''} aria-hidden="true" />
            <span>Refresh</span>
          </button>

          <div>
            <button
              type="button"
              {...(supportsPopover ? { popovertarget: 'today-tools-popover' } : {})}
              onClick={!supportsPopover ? () => setToolsFallbackOpen((v) => !v) : undefined}
              className={`min-h-[36px] inline-flex items-center gap-2 px-3 py-1.5 rounded-xl border text-xs font-semibold cursor-pointer transition ${
                !healthSummary.feedsHealthy || (leagueFilter === 'NCAAM' && !healthSummary.kenpomOk)
                  ? 'border-amber-500/45 bg-amber-500/15 hover:bg-amber-500/25 text-amber-200'
                  : 'border-slate-700 bg-slate-900 hover:bg-slate-800 text-slate-200'
              }`}
            >
              <span
                className={`w-2 h-2 rounded-full ${
                  !healthSummary.feedsHealthy || (leagueFilter === 'NCAAM' && !healthSummary.kenpomOk)
                    ? 'bg-amber-400'
                    : 'bg-emerald-400'
                }`}
                aria-hidden="true"
              />
              <SlidersHorizontal size={13} aria-hidden="true" />
              <span>Data &amp; Tools</span>
            </button>

            <div
              id="today-tools-popover"
              ref={toolsPopoverRef}
              popover="auto"
              aria-label="Slate data sources and tools"
              className={`today-tools-popover space-y-3 ${toolsFallbackOpen && !supportsPopover ? ':popover-open' : ''}`}
            >
              <div className="flex items-center justify-between gap-2 pb-2 border-b border-slate-800">
                <span className="text-xs font-bold uppercase tracking-wider text-slate-300">
                  Data &amp; Slate Tools
                </span>
                <button
                  type="button"
                  onClick={closeToolsPopover}
                  aria-label="Close Data & Tools panel"
                  className="p-1 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 cursor-pointer"
                >
                  <X size={14} aria-hidden="true" />
                </button>
              </div>

              <div className="grid grid-cols-1 gap-2">
                {leagueFilter === 'NCAAM' && (
                  <button
                    type="button"
                    onClick={() => {
                      closeToolsPopover();
                      handleRescoreSlate();
                    }}
                    disabled={loading || rescoringSlate}
                    className="w-full min-h-[36px] inline-flex items-center justify-between px-3 py-2 rounded-xl bg-indigo-600/20 hover:bg-indigo-600/35 border border-indigo-400/40 text-xs font-semibold text-indigo-100 cursor-pointer disabled:opacity-50"
                  >
                    <span className="inline-flex items-center gap-2">
                      <Sparkles size={13} className={rescoringSlate ? 'animate-pulse' : ''} aria-hidden="true" />
                      <span>{rescoringSlate ? (rescoreProgress || 'Updating picks...') : 'Recalculate Picks'}</span>
                    </span>
                    <span className="text-[11px] text-indigo-300/80 font-normal">Re-run model</span>
                  </button>
                )}

                <button
                  type="button"
                  onClick={() => {
                    closeToolsPopover();
                    handleGradeResults();
                  }}
                  disabled={loading}
                  className="w-full min-h-[36px] inline-flex items-center justify-between px-3 py-2 rounded-xl bg-emerald-500/15 hover:bg-emerald-500/25 border border-emerald-500/35 text-xs font-semibold text-emerald-200 cursor-pointer disabled:opacity-50"
                >
                  <span className="inline-flex items-center gap-2">
                    <Award size={13} aria-hidden="true" />
                    <span>Grade Past Results</span>
                  </span>
                  <span className="text-[11px] text-emerald-300/80 font-normal">Score finished games</span>
                </button>

                <button
                  type="button"
                  onClick={() => {
                    closeToolsPopover();
                    setShowModelLogicDialog(true);
                  }}
                  className="w-full min-h-[36px] inline-flex items-center justify-between px-3 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-xs font-semibold text-slate-100 cursor-pointer"
                >
                  <span className="inline-flex items-center gap-2">
                    <Info size={13} className="text-sky-400" aria-hidden="true" />
                    <span>How Our Picks Work</span>
                  </span>
                  <span className="text-[11px] text-slate-400 font-normal">Model rules &amp; help</span>
                </button>
              </div>

              <div className="pt-2 border-t border-slate-800">
                <TodayDataHealthStrip
                  embedded
                  dataHealth={dataHealth}
                  edges={edges}
                  leagueFilter={leagueFilter}
                  onOpenKenpomUpload={() => {
                    closeToolsPopover();
                    setShowModelLogicDialog(true);
                  }}
                  onPasteKenpomClipboard={() => {
                    closeToolsPopover();
                    handlePasteKenpomClipboard();
                  }}
                />
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Show a compact alert ONLY when NCAAM KenPom ratings need an update */}
      {leagueFilter === 'NCAAM' && !healthSummary.kenpomOk && !loading && (
        <div className="rounded-xl border border-amber-500/35 bg-amber-950/25 px-3.5 py-2 flex flex-wrap items-center justify-between gap-2 text-xs text-amber-200">
          <span>KenPom ratings need a quick update for full model accuracy today.</span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handlePasteKenpomClipboard}
              className="px-2.5 py-1 rounded-lg bg-emerald-500/20 hover:bg-emerald-500/30 border border-emerald-500/40 font-semibold text-emerald-200 cursor-pointer"
            >
              Paste KenPom
            </button>
            <button
              type="button"
              onClick={() => setShowModelLogicDialog(true)}
              className="px-2.5 py-1 rounded-lg bg-amber-500/20 hover:bg-amber-500/30 border border-amber-500/40 font-semibold text-amber-100 cursor-pointer"
            >
              Update KenPom
            </button>
          </div>
        </div>
      )}

      {/* Single-Row Underline-Indicated Tabs */}
      <div
        ref={tablistRef}
        role="tablist"
        aria-label="Today views"
        onKeyDown={handleTabListKeyDown}
        className="today-tablist"
      >
        {tabs.map((tab) => {
          const selected = activeSubTab === tab.id;
          return (
            <button
              key={tab.id}
              id={`today-tab-${tab.id}`}
              data-tab-id={tab.id}
              type="button"
              role="tab"
              tabIndex={selected ? 0 : -1}
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
        <section role="tabpanel" aria-labelledby="today-tab-top_plays" className="space-y-5">
          {leagueFilter === 'NCAAM' && <SlatePublication day={selectedDate} />}
          {(scopedTopPlays.length > 1 || actionablePlays.length > top6SlatePlays.length) && (
            <div className="flex flex-wrap items-center justify-between gap-2">
              {scopedTopPlays.length > 1 ? (
                <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Filter best bets">
                  {[
                    { id: 'all', label: `All (${pickFilterCounts.all})`, show: true },
                    { id: 'high_conf', label: `Strongest (${pickFilterCounts.high_conf})`, show: pickFilterCounts.high_conf > 0 || pickTypeFilter === 'high_conf' },
                    { id: 'spread', label: `Spreads (${pickFilterCounts.spread})`, show: pickFilterCounts.spread > 0 || pickTypeFilter === 'spread' },
                    { id: 'total', label: `Over / Under (${pickFilterCounts.total})`, show: pickFilterCounts.total > 0 || pickTypeFilter === 'total' },
                    { id: 'soon', label: `Starting Soon (${pickFilterCounts.soon})`, show: pickFilterCounts.soon > 0 || pickTypeFilter === 'soon' },
                  ]
                    .filter((pill) => pill.show)
                    .map((pill) => {
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
              ) : (
                <span />
              )}

              {actionablePlays.length > top6SlatePlays.length && (
                <button
                  type="button"
                  onClick={() => setPickViewMode((m) => (m === 'top6' ? 'all' : 'top6'))}
                  className="text-xs font-semibold text-indigo-300 hover:text-indigo-200 underline cursor-pointer"
                >
                  {pickViewMode === 'top6' ? `Show all ${actionablePlays.length} bets` : 'Show Top 6 only'}
                </button>
              )}
            </div>
          )}

          {loading ? (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              {[1, 2, 3, 4].map((i) => (
                <div key={i} className="h-44 rounded-2xl border border-slate-800 bg-slate-900/50 animate-pulse" />
              ))}
            </div>
          ) : filteredTopPlays.length === 0 ? (
            <div
              className={`rounded-2xl border p-8 text-center space-y-3 ${
                actionablePlays.length === 0 && slateSummary.staleOddsCount > 0
                  ? 'border-amber-500/40 bg-amber-950/15'
                  : 'border-slate-800 bg-slate-900/60'
              }`}
            >
              <h3 className="text-base font-bold text-slate-200">
                {actionablePlays.length === 0
                  ? slateSummary.staleOddsCount > 0
                    ? `Stale Odds Hold on ${slateSummary.staleOddsCount} Game${slateSummary.staleOddsCount === 1 ? '' : 's'} (Not a True No-Bet)`
                    : `True No-Bet Right Now — All ${slateSummary.trueNoBetCount || slateSummary.totalGames} Lined Games Evaluated`
                  : 'No Bets Match This Filter'}
              </h3>
              <p className="text-xs text-slate-400 max-w-md mx-auto">
                {actionablePlays.length === 0
                  ? slateSummary.staleOddsCount > 0
                    ? `${slateSummary.staleOddsCount} game${slateSummary.staleOddsCount === 1 ? ' has' : 's have'} odds older than 90 minutes. Click Recalculate Picks below to refresh lines before tip-off.`
                    : `All ${slateSummary.trueNoBetCount || slateSummary.totalGames} lined games have fresh sportsbook odds and were evaluated as a true pass (no edge cleared our minimum thresholds${slateSummary.unlinedCount > 0 ? `; ${slateSummary.unlinedCount} non-D1/exhibition games have no sportsbook lines posted` : ''}). Check Close Calls below or browse All Games.`
                  : 'Switch back to All bets or browse All Games to inspect every matchup.'}
              </p>
              <div className="flex flex-wrap items-center justify-center gap-2 pt-1">
                {pickTypeFilter !== 'all' && (
                  <button
                    type="button"
                    onClick={() => setPickTypeFilter('all')}
                    className="inline-flex px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-xs font-semibold text-white cursor-pointer"
                  >
                    Show All Bets
                  </button>
                )}
                {actionablePlays.length === 0 && leagueFilter === 'NCAAM' && (
                  <button
                    type="button"
                    onClick={handleRescoreSlate}
                    disabled={rescoringSlate}
                    className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-xs font-semibold text-white cursor-pointer disabled:opacity-50"
                  >
                    <Sparkles size={13} aria-hidden="true" />
                    <span>{rescoringSlate ? (rescoreProgress || 'Updating...') : 'Recalculate Picks'}</span>
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => setActiveSubTab('board')}
                  className="inline-flex px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-xs font-semibold text-white cursor-pointer"
                >
                  View All Games ({slateSummary.totalGames})
                </button>
              </div>
            </div>
          ) : (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              {filteredTopPlays.map((item) => (
                <TodayPlayCard
                  key={item.id}
                  rank={item.slateRank}
                  game={item.game}
                  rec={item.rec}
                  analyzedAt={leagueFilter === 'NCAAM' ? item.analyzedAt : null}
                  context={item.context}
                  bankroll={bankroll}
                  onOpenDetails={handleOpenGameDetails}
                  onAddBet={onAddBet}
                />
              ))}
            </div>
          )}

          {/* Close Calls Watchlist (Near-Miss Board) */}
          {actionablePlays.length < 4 && closestLeans.length > 0 && (
            <section className="pt-2 space-y-3" aria-labelledby="close-calls-heading">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <div>
                  <h3 id="close-calls-heading" className="text-sm font-bold text-indigo-200 tracking-tight">
                    Close Calls (Almost Official Bets)
                  </h3>
                  <p className="text-xs text-slate-400">
                    Games where our line differs from the sportsbook, just shy of an official bet. Pass unless odds move in your favor.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setActiveSubTab('board')}
                  className="text-xs font-semibold text-indigo-300 hover:text-indigo-200 underline cursor-pointer"
                >
                  Browse All Games
                </button>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
                {closestLeans.map(({ id, game, lean, meta, ctx }) => {
                  const reasonTxt = safeReasonText(lean.reason || meta?.reason);
                  const projScore = getProjectedScore(game, { context: ctx }, lean);
                  const liveInfo = getLiveGameStatus(game, lean, ctx);
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
                              {liveInfo.periodLabel ? ` · ${liveInfo.periodLabel}` : ''}
                            </span>
                          ) : liveInfo.isFinal ? (
                            <span className="px-1.5 py-0.5 rounded bg-slate-800 text-slate-200 font-bold text-[10px]">
                              FINAL {liveInfo.hasScore ? `(${liveInfo.awayScore}-${liveInfo.homeScore})` : ''}
                            </span>
                          ) : (
                            <span>{fmtTimeEt(game.start_time)} ET</span>
                          )}
                          <span className="px-2 py-0.5 rounded-full bg-indigo-500/15 border border-indigo-400/30 text-indigo-200 font-bold text-[10px]">
                            Close Call
                          </span>
                        </div>
                        <div className="text-xs font-semibold text-slate-200 truncate">
                          {game.away_team} @ {game.home_team}
                        </div>
                        {(liveInfo.isLive || liveInfo.isFinal) && liveInfo.coverText && (
                          <div className="space-y-1">
                            <span
                              className={`inline-flex items-center px-2 py-0.5 rounded-full border text-[10px] font-bold ${
                                liveInfo.coverTone === 'win'
                                  ? 'bg-emerald-500/15 border-emerald-500/40 text-emerald-300'
                                  : liveInfo.coverTone === 'loss'
                                    ? 'bg-rose-500/15 border-rose-500/40 text-rose-300'
                                    : liveInfo.coverTone === 'tossup'
                                      ? 'bg-amber-500/15 border-amber-500/40 text-amber-200'
                                      : 'bg-slate-800 border-slate-700 text-slate-200'
                              }`}
                            >
                              {liveInfo.coverText}
                            </span>
                            {liveInfo.trendDetail && (
                              <p className="text-[11px] text-slate-300 leading-snug">{liveInfo.trendDetail}</p>
                            )}
                          </div>
                        )}
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
                        <div className="text-[11px] font-mono text-slate-400 flex flex-wrap items-center gap-x-2">
                          <span>Sportsbook: {lean.market_line != null ? lean.market_line : '—'} ({fmtOdds(lean.price)})</span>
                          <span>·</span>
                          <span className="text-indigo-300">Our Line: {lean.fair_line != null ? lean.fair_line : '—'}</span>
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
                            aria-label={`Add Bet ${lean.selection}`}
                            className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-slate-800/90 hover:bg-slate-700 border border-slate-700 text-xs font-semibold text-slate-200 cursor-pointer"
                          >
                            <PlusCircle size={12} aria-hidden="true" />
                            <span>Add Bet</span>
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
            bankroll={bankroll}
            onOpenDetails={handleOpenGameDetails}
            onAddBet={onAddBet}
          />
        </section>
      )}

      {activeSubTab === 'parlays' && leagueFilter === 'NCAAM' && (
        <section role="tabpanel" aria-labelledby="today-tab-parlays">
          <ParlayRecommendations
            date={selectedDate}
            onSelectDate={setSelectedDate}
            bankroll={bankroll}
            onAddBet={onAddBet}
          />
        </section>
      )}

      {/* Native <dialog> Modals */}
      <TodayMatchupModal
        game={activeSelectedGame}
        analysisResult={analysisResult}
        correlationResult={correlationResult}
        matchupProfile={selectedGame ? matchupProfiles[selectedGame.id] : null}
        cachedMeta={activeSelectedGame ? lookupTopPickForGame(activeSelectedGame, rowTopPicks, rowTopPicksByKey) : null}
        bankroll={bankroll}
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
        onPasteKenpomClipboard={handlePasteKenpomClipboard}
      />
    </div>
  );
};

export default Research;
