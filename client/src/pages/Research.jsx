import React, { useState, useEffect } from 'react';
import api from '../api/axios';
import { loadCache } from '../utils/httpCache';
import { ArrowUpDown, ChevronUp, ChevronDown, Filter, RefreshCw, CheckCircle, AlertCircle, Info, Shield, ShieldAlert, ShieldCheck, PlusCircle, TrendingUp } from 'lucide-react';
import ModelPerformanceAnalytics from '../components/ModelPerformanceAnalytics';
import OpenBetsPanel from '../components/OpenBetsPanel';
import ParlayRecommendations from '../components/ParlayRecommendations';

const Research = ({ onAddBet, showModelPerformanceTab = true, formatCurrency, formatDateMDY }) => {
    const [edges, setEdges] = useState([]);
    const [history, setHistory] = useState([]);
    // Top-level tabs: board vs history
    const [activeTab, setActiveTab] = useState('live');

    // Board sub-tabs: recommended vs full board
    const [boardTab, setBoardTab] = useState('recommended');
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    // (Balances removed from this page; tracked in Performance)
    // Research tab focuses on board-backed leagues
    const [leagueFilter, setLeagueFilter] = useState('NCAAM');
    // Date Filtering
    // Always drive date selection in America/New_York so it matches backend queries.
    const getTodayStr = () => new Date().toLocaleDateString('en-CA', { timeZone: 'America/New_York' });
    const [selectedDate, setSelectedDate] = useState(getTodayStr());

    // Game Analysis Modal State
    const [selectedGame, setSelectedGame] = useState(null);
    const [analysisResult, setAnalysisResult] = useState(null);
    const [correlationResult, setCorrelationResult] = useState(null);
    const [isAnalyzing, setIsAnalyzing] = useState(false);

    // Manual referee entry (optional)
    const [ref1, setRef1] = useState('');
    const [ref2, setRef2] = useState('');
    const [ref3, setRef3] = useState('');
    const [refsSaving, setRefsSaving] = useState(false);
    const [refsError, setRefsError] = useState(null);

    // Quick-pick state (board row badges)
    const [rowTopPicks, setRowTopPicks] = useState({}); // event_id -> { rec, analyzedAt }
    const [rowTopPicksByKey, setRowTopPicksByKey] = useState({}); // matchup key -> { rec, analyzedAt }
    const [topPicksError, setTopPicksError] = useState(null);
    const [matchupProfiles, setMatchupProfiles] = useState({}); // event_id -> { home_kenpom, away_kenpom... }
    const [dataHealth, setDataHealth] = useState([]);
    const [topPicksStats, setTopPicksStats] = useState({ games: 0, withPick: 0, server: null, errors: [], actionable: 0, noBet: 0 });

    // Degraded mode: show cached content if DB/API is down.
    const [degradedMode, setDegradedMode] = useState(false);
    const [degradedAsOf, setDegradedAsOf] = useState(null);
    // Edge-engine recs removed: Today should use the core model (stored top picks) to avoid mismatches.
    // const [edgeRecs, setEdgeRecs] = useState(null);
    // const [edgeRecsError, setEdgeRecsError] = useState(null);
    const [rowPickingId, setRowPickingId] = useState(null);

    // Mobile UX: collapse recommended list to Top 6 by default (expandable)
    const [showAllMobileRecs, setShowAllMobileRecs] = useState(false);

    // Sorting State
    const [sortConfig, setSortConfig] = useState({ key: 'edge', direction: 'desc' });

    // Data health hover tooltip (custom, fixed-position to avoid clipping)
    const [dhTip, setDhTip] = useState({ open: false, pinned: false, x: 16, y: 16, text: '' });
    const [dhHideTimer, setDhHideTimer] = useState(null);

    const BOARD_DAYS_DEFAULT = showModelPerformanceTab ? 3 : 1;

    useEffect(() => {
        // reset mobile expansion when the slate changes
        setShowAllMobileRecs(false);
        fetchSchedule();
    }, [selectedDate, leagueFilter]); // Refetch when date/league changes

    const fetchSchedule = async () => {
        setLoading(true);
        setError(null);
        setDegradedMode(false);
        setDegradedAsOf(null);

        const boardParams = { league: leagueFilter, date: selectedDate, days: BOARD_DAYS_DEFAULT };
        const topPicksParams = { date: selectedDate, days: BOARD_DAYS_DEFAULT, limit_games: 250 };
        const historyParams = { limit: 500 };

        try {
            // Fetch board + history
            const [boardRes, historyRes, topPicksRes, healthRes, matchupRes] = await Promise.all([
                api.get('/api/board', { params: boardParams }),
                api.get('/api/ncaam/history', { params: historyParams }).catch((e) => {
                    console.warn("History fetch failed:", e);
                    return { data: [] };
                }),
                (leagueFilter === 'NCAAM'
                    ? api.get('/api/ncaam/top-picks', { params: topPicksParams })
                        .then((r) => ({ ...r, _error: null }))
                        .catch((e) => ({ data: null, _error: e }))
                    : Promise.resolve({ data: null, _error: null })
                ),
                api.get('/api/data-health').catch(() => ({ data: { items: [] } })),
                (leagueFilter === 'NCAAM'
                    ? api.get('/api/ncaam/matchup-profiles', { params: { date: selectedDate } })
                        .catch((e) => ({ data: { matchups: [] } }))
                    : Promise.resolve({ data: { matchups: [] } })
                )
            ]);

            setDataHealth(healthRes?.data?.items || []);

            setEdges(boardRes.data || []);
            setHistory(historyRes.data || []);

            const mProfiles = {};
            (matchupRes?.data?.matchups || []).forEach(m => {
                mProfiles[m.event_id] = m;
            });
            setMatchupProfiles(mProfiles);

            // Hydrate row badges from server-side top picks (avoid N analyze calls)
            try {
                const errTp = topPicksRes?._error;
                if (errTp) {
                    setTopPicksError(errTp?.response?.data?.detail || errTp?.response?.data?.message || errTp?.message || 'Top picks failed');
                } else {
                    setTopPicksError(null);
                }

                // If the latest full run says NO_BETS, keep the cached slate but clearly label it stale.
                try {
                    const rm = topPicksRes?.data?.run_meta || null;
                    if (rm && rm.status === 'NO_BETS') {
                        setDegradedMode(true);
                        if (rm.created_at) setDegradedAsOf(rm.created_at);
                    }
                } catch (e) { }

                const tp = topPicksRes?.data?.picks || null;
                if (tp && typeof tp === 'object') {
                    const mapped = {};
                    const mappedByKey = {};

                    const norm = (s) => String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, '').trim();
                    const makeKey = (dayEt, away, home) => {
                        const d = String(dayEt || '').slice(0, 10);
                        const a = norm(away);
                        const h = norm(home);
                        if (!d || !a || !h) return null;
                        return `${d}|${a}|${h}`;
                    };

                    Object.keys(tp).forEach((eid) => {
                        const recObj = {
                            rec: tp[eid]?.rec,
                            analyzedAt: tp[eid]?.analyzed_at,
                            isActionable: tp[eid]?.is_actionable,
                            reason: tp[eid]?.reason,
                            source: tp[eid]?.source,
                            event: tp[eid]?.event,
                        };
                        mapped[eid] = recObj;

                        // Cross-provider dedupe: board event ids can differ (espn vs action).
                        // Build a fallback map keyed by day_et + away/home names.
                        const ev = tp[eid]?.event || {};
                        const k = makeKey(ev?.day_et, ev?.away_team, ev?.home_team);
                        if (k && !mappedByKey[k]) mappedByKey[k] = recObj;
                    });

                    setRowTopPicks(mapped);
                    setRowTopPicksByKey(mappedByKey);

                    const nGames = Object.keys(tp).length;
                    const vals = Object.values(tp);
                    const nWith = vals.filter((x) => x && x.rec).length;
                    const nAction = vals.filter((x) => x && x.isActionable).length;
                    const nNoBet = vals.filter((x) => x && x.isActionable === false).length;
                    const serverStats = topPicksRes?.data?.stats;
                    setTopPicksStats({
                        games: nGames,
                        withPick: nWith,
                        actionable: nAction,
                        noBet: nNoBet,
                        server: serverStats || null,
                        errors: topPicksRes?.data?.errors || [],
                    });
                    // Default board sub-tab to "Recommended" if we have at least one pick.
                    if (Object.keys(mapped).length > 0) {
                        setBoardTab('recommended');
                    }
                } else {
                    setRowTopPicks({});
                    setRowTopPicksByKey({});
                    setTopPicksStats({ games: 0, withPick: 0, server: null, errors: [] });
                }
            } catch (e) { }

        } catch (err) {
            console.error(err);
            if (err.response?.status === 403) {
                const pass = prompt("Authentication failed. Please enter the Basement Password:");
                if (pass) {
                    localStorage.setItem('basement_password', pass);
                    window.location.reload();
                }
            }

            // Degraded mode fallback: show last cached board/top-picks instead of a blank screen.
            try {
                const cachedBoard = loadCache('/api/board', boardParams);
                const cachedTop = (leagueFilter === 'NCAAM') ? loadCache('/api/ncaam/top-picks', topPicksParams) : null;

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
                        };
                    });
                    setRowTopPicks(mapped);
                }

                if (cachedBoard?.payload || cachedTop?.payload) {
                    setError(null);
                } else {
                    setError('Failed to load schedule.');
                }
            } catch {
                setError('Failed to load schedule.');
            }
        } finally {
            setLoading(false);
        }
    };

    const runModels = async () => {
        // For NCAAM v2, we don't "run models" globally. We just refresh the board.
        // We can add a "Sync All" if needed, but the board fetch is cheap.
        fetchSchedule();
    };

    const gradeResults = async () => {
        try {
            setLoading(true);
            const res = await api.post('/api/research/grade');
            const result = res.data;
            alert(`Grading Complete! ${result.graded || 0} bets updated.`);
            // Fetch layout/refresh data - CONSISTENT ENDPOINTS
            const [boardRes, historyRes, topPicksRes] = await Promise.all([
                api.get('/api/board', { params: { league: leagueFilter, date: selectedDate, days: BOARD_DAYS_DEFAULT } }),
                api.get('/api/ncaam/history', { params: { limit: 500 } }),
                (leagueFilter === 'NCAAM'
                    ? api.get('/api/ncaam/top-picks', { params: { date: selectedDate, days: BOARD_DAYS_DEFAULT, limit_games: 200 } }).catch(() => ({ data: null }))
                    : Promise.resolve({ data: null })
                )
            ]);
            setEdges(boardRes.data || []);
            setHistory(historyRes.data || []);
            try {
                const tp = topPicksRes?.data?.picks || null;
                if (tp && typeof tp === 'object') {
                    const mapped = {};
                    Object.keys(tp).forEach((eid) => {
                        mapped[eid] = { rec: tp[eid]?.rec, analyzedAt: tp[eid]?.analyzed_at };
                    });
                    setRowTopPicks(mapped);
                }
            } catch (e) { }
        } catch (err) {
            console.error(err);
            alert('Grading failed: ' + (err.response?.data?.message || err.message));
        } finally {
            setLoading(false);
        }
    };

    const analyzeGame = async (game) => {
        setSelectedGame(game);
        setIsAnalyzing(true);
        setAnalysisResult(null);
        setCorrelationResult(null);
        setRefsError(null);
        // Keep current manual refs in the inputs; user may want to set them before re-run.

        try {
            const [analysisRes, corrRes] = await Promise.all([
                api.post('/api/ncaam/analyze', { event_id: game.id }),
                api.get('/api/ncaam/correlations/game', { params: { event_id: game.id } }).catch(e => ({ data: null }))
            ]);
            // If analyze returns no recommendations but we already have a cached daily_top_picks rec
            // for this event, fall back so the Details modal still shows *something*.
            // (This happens when the cached pick was computed earlier, but current market/odds inputs
            // are missing or have shifted, causing analyze() to gate it out.)
            const apiData = analysisRes.data;
            const apiTop = (apiData?.recommendations || [])[0] || null;
            const cachedTop = (rowTopPicks?.[game.id]?.rec) || null;
            const merged = (!apiTop && cachedTop)
                ? {
                    ...(apiData || {}),
                    recommendations: [cachedTop],
                    headline: (apiData?.headline || 'Cached pick (daily_top_picks)')
                        + ' — live analyze returned no recommendations',
                    _cached_fallback: true,
                }
                : apiData;

            setAnalysisResult(merged);
            setCorrelationResult(corrRes.data);

            // Also surface the top pick back on the board row
            try {
                const top = (merged?.recommendations || [])[0] || null;
                if (top) {
                    setRowTopPicks(prev => ({
                        ...prev,
                        [game.id]: { rec: top, analyzedAt: new Date().toISOString() }
                    }));
                }
            } catch (e) { }

            // Refresh history in background - isolated so it doesn't block analysis
            try {
                const histRes = await api.get('/api/ncaam/history', { params: { limit: 500 } });
                setHistory(histRes.data || []);
            } catch (histErr) {
                console.warn('History refresh failed (non-blocking):', histErr);
            }
        } catch (err) {
            console.error('Analysis error:', err);
            setAnalysisResult({ error: err.response?.data?.detail || 'Analysis failed' });
        } finally {
            setIsAnalyzing(false);
        }
    };

    const quickPick = async (game) => {
        // Fetch analysis without opening the modal; then show badge + allow one-click add.
        setRowPickingId(game.id);
        try {
            const analysisRes = await api.post('/api/ncaam/analyze', { event_id: game.id });
            const top = (analysisRes.data?.recommendations || [])[0] || null;
            if (top) {
                setRowTopPicks(prev => ({
                    ...prev,
                    [game.id]: { rec: top, analyzedAt: new Date().toISOString() }
                }));
            }
        } catch (err) {
            console.warn('QuickPick failed:', err);
        } finally {
            setRowPickingId(null);
        }
    };

    const closeAnalysisModal = () => {
        setSelectedGame(null);
        setAnalysisResult(null);
        setCorrelationResult(null);
        setRefsError(null);
        setRef1('');
        setRef2('');
        setRef3('');
    };

    const refreshData = async () => {
        try {
            setLoading(true);
            const res = await api.post('/api/jobs/ingest_torvik');
            const result = res.data;
            alert(`Data Refresh Complete! ${result.teams_count || 0} teams updated.`);
            // Fresh fetch
            const [scheduleRes, historyRes] = await Promise.all([
                api.get('/api/schedule?sport=all&days=3'),
                api.get('/api/research/history')
            ]);
            setEdges(scheduleRes.data || []);
            setHistory(historyRes.data || []);
        } catch (err) {
            console.error(err);
            alert('Data refresh failed: ' + (err.response?.data?.message || err.message));
        } finally {
            setLoading(false);
        }
    };

    const handleSort = (key) => {
        let direction = 'desc';
        if (sortConfig.key === key && sortConfig.direction === 'desc') {
            direction = 'asc';
        }
        setSortConfig({ key, direction });
    };

    const shiftDate = (days) => {
        // selectedDate is YYYY-MM-DD (ET day). Avoid JS timezone pitfalls by doing pure UTC date math
        // and returning a YYYY-MM-DD string.
        try {
            const [yy, mm, dd] = String(selectedDate || '').split('-').map(x => parseInt(x, 10));
            if (!yy || !mm || !dd) return;
            const base = Date.UTC(yy, mm - 1, dd, 12, 0, 0);
            const next = new Date(base + (Number(days) * 86400000));
            const y = next.getUTCFullYear();
            const m = String(next.getUTCMonth() + 1).padStart(2, '0');
            const d = String(next.getUTCDate()).padStart(2, '0');
            setSelectedDate(`${y}-${m}-${d}`);
        } catch (e) {
            // fallback: no-op
        }
    };

    const fmtSigned = (n, decimals = 1) => {
        if (n === null || n === undefined || n === '') return '-';
        const x = Number(n);
        if (Number.isNaN(x)) return String(n);
        const s = decimals >= 0 ? x.toFixed(decimals) : String(x);
        return x > 0 ? `+${s}` : s;
    };

    // Simple context labels (Torvik-style). League avg AdjO/AdjD ~106.
    const EFF_AVG = 106.0;
    const labelOffense = (adjO) => {
        const x = Number(adjO);
        if (Number.isNaN(x)) return { label: '—', cls: 'text-slate-400' };
        if (x >= EFF_AVG + 6) return { label: 'Strong', cls: 'text-green-400' };
        if (x <= EFF_AVG - 6) return { label: 'Weak', cls: 'text-red-400' };
        return { label: 'Average', cls: 'text-slate-200' };
    };
    const labelDefense = (adjD) => {
        const x = Number(adjD);
        if (Number.isNaN(x)) return { label: '—', cls: 'text-slate-400' };
        // Lower AdjD is better
        if (x <= EFF_AVG - 6) return { label: 'Strong', cls: 'text-green-400' };
        if (x >= EFF_AVG + 6) return { label: 'Weak', cls: 'text-red-400' };
        return { label: 'Average', cls: 'text-slate-200' };
    };
    const labelPace = (tempo) => {
        const x = Number(tempo);
        if (Number.isNaN(x)) return { label: '—', cls: 'text-slate-400' };
        if (x >= 71) return { label: 'Fast', cls: 'text-amber-300' };
        if (x <= 65) return { label: 'Slow', cls: 'text-blue-300' };
        return { label: 'Average', cls: 'text-slate-200' };
    };

    const getEdgeColor = (edge, sport) => {
        if (edge === null || edge === undefined) return 'text-gray-500';

        // Percent-based (EPL)
        if (sport === 'EPL') {
            if (edge > 10) return 'text-green-400 font-bold';
            if (edge > 5) return 'text-green-300';
            if (edge > 0) return 'text-green-200';
            return 'text-red-400';
        }

        // Point-based (NFL/NCAAM/NCAAF)
        const threshold = (sport === 'NFL' || sport === 'NCAAF') ? 1.5 : 3.0;
        if (edge >= threshold * 2) return 'text-green-400 font-bold';
        if (edge >= threshold) return 'text-green-300';
        if (edge > 0) return 'text-green-200';
        return 'text-red-400';
    };

    const getProcessedEdges = () => {
        let filtered = edges.filter(e => {
            if (leagueFilter && e.sport !== leagueFilter) return false;
            return true;
        });

        return [...filtered].sort((a, b) => {
            let aVal = a[sortConfig.key];
            let bVal = b[sortConfig.key];
            if (aVal === undefined) aVal = '';
            if (bVal === undefined) bVal = '';
            if (aVal < bVal) return sortConfig.direction === 'asc' ? -1 : 1;
            if (aVal > bVal) return sortConfig.direction === 'asc' ? 1 : -1;
            return 0;
        });
    };

    const getSortedHistory = () => {
        return [...history].sort((a, b) => {
            const key = sortConfig.key === 'edge' ? 'created_at' : sortConfig.key; // Default history sort to time
            let aVal = a[key] || '';
            let bVal = b[key] || '';
            if (aVal < bVal) return sortConfig.direction === 'asc' ? -1 : 1;
            if (aVal > bVal) return sortConfig.direction === 'asc' ? 1 : -1;
            return 0;
        });
    };

    // History should reflect only *recommended* model bets.
    // Proxy gate (matches backend + cron): EV/u >= 2% and has a concrete market/selection/pick.
    const isRecommendedHistoryItem = (h) => {
        try {
            const mt = String(h?.market_type || h?.market || '').toUpperCase();
            const sel = String(h?.selection || '').trim();
            const pick = String(h?.pick || '').toUpperCase();
            const ev = Number(h?.ev_per_unit ?? h?.ev ?? 0);
            if (!mt || mt === 'AUTO') return false;
            if (!sel || sel === '—') return false;
            if (!pick || pick === 'NONE') return false;
            if (!Number.isFinite(ev) || ev < 0.02) return false;
            return true;
        } catch (e) {
            return false;
        }
    };

    const isTodayET = (ts) => {
        if (!ts) return false;
        try {
            const d = new Date(ts);
            const day = d.toLocaleDateString('en-US', { timeZone: 'America/New_York' });
            const today = new Date().toLocaleDateString('en-US', { timeZone: 'America/New_York' });
            return day === today;
        } catch (e) {
            return false;
        }
    };

    const isSameEtDay = (ts, ymd) => {
        if (!ts || !ymd) return false;
        try {
            const d = new Date(ts);
            const s = d.toLocaleDateString('en-CA', { timeZone: 'America/New_York' });
            return String(s) === String(ymd);
        } catch (e) {
            return false;
        }
    };

    const getTodayRecommended = () => getSortedHistory()
        .filter(isRecommendedHistoryItem)
        .filter(h => isTodayET(h?.analyzed_at || h?.created_at));

    // History tab is only historical results (exclude today's bets).
    const getRecommendedHistory = () => getSortedHistory()
        .filter(isRecommendedHistoryItem)
        .filter(h => !isTodayET(h?.analyzed_at || h?.created_at));


    const SortIcon = ({ column }) => {
        if (sortConfig.key !== column) return <ArrowUpDown size={12} className="ml-1 opacity-20" />;
        return sortConfig.direction === 'asc' ? <ChevronUp size={12} className="ml-1 text-blue-400" /> : <ChevronDown size={12} className="ml-1 text-blue-400" />;
    };

    // Balance snapshot helpers removed from this page (tracked in Performance).

    // Balances removed from this page (shown in Performance)

    return (
        <div className="p-4 md:p-6 bg-slate-900 min-h-screen text-white">
            {/* Data health tooltip (fixed; rendered at top level to avoid clipping by overflow-hidden containers) */}
            {dhTip?.open && (
                <div
                    className="fixed z-[9999] max-w-[560px] whitespace-pre-line rounded-lg border border-slate-700/70 bg-slate-950/95 px-3 py-2 text-[11px] text-slate-200 shadow-2xl pointer-events-auto"
                    style={{ left: dhTip.x, top: dhTip.y, maxHeight: 360, overflow: 'auto' }}
                    onMouseEnter={() => {
                        if (dhHideTimer) { clearTimeout(dhHideTimer); setDhHideTimer(null); }
                        setDhTip((p) => ({ ...p, open: true }));
                    }}
                    onMouseLeave={() => {
                        if (dhTip?.pinned) return;
                        const t = setTimeout(() => setDhTip((p) => ({ ...p, open: false })), 350);
                        setDhHideTimer(t);
                    }}
                >
                    <div className="flex items-center justify-between mb-1">
                        <div className="text-[10px] uppercase tracking-widest text-slate-400 font-black">
                            {dhTip?.pinned ? 'System status (pinned)' : 'System status'}
                        </div>
                        <button
                            className="text-slate-400 hover:text-white text-xs"
                            onClick={() => setDhTip((p) => ({ ...p, open: false, pinned: false }))}
                        >
                            Close
                        </button>
                    </div>
                    {dhTip.text}
                </div>
            )}
            <div className="flex flex-col md:flex-row md:justify-between md:items-center gap-3 mb-6">
                <div>
                    <h1 className="text-2xl md:text-3xl font-bold bg-gradient-to-r from-blue-400 to-green-400 bg-clip-text text-transparent">
                        {showModelPerformanceTab ? 'Model Recommendations' : "Today's Recommended Bets"}
                    </h1>
                </div>
                <div className="flex flex-wrap gap-2">
                    {showModelPerformanceTab && (
                        <button
                            onClick={() => onAddBet?.()}
                            className="px-4 py-2 bg-emerald-500/15 hover:bg-emerald-500/20 rounded-xl text-sm transition-all flex items-center gap-2 border border-emerald-500/25 text-emerald-200"
                        >
                            <PlusCircle size={14} /> Add Bet
                        </button>
                    )}
                    <button
                        onClick={fetchSchedule}
                        disabled={loading}
                        className="px-4 py-2 bg-slate-700 hover:bg-slate-600 rounded-xl text-sm transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                    >
                        <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
                        Refresh Board
                    </button>
                </div>
            </div>

            {/* Tabs */}
            {showModelPerformanceTab && (
                <div className="inline-flex gap-1 mb-6 p-1 rounded-2xl bg-slate-900/40 border border-slate-700/40">
                    <button
                        onClick={() => setActiveTab('live')}
                        className={`px-4 py-2 text-sm font-semibold rounded-xl transition ${activeTab === 'live' ? 'bg-slate-800/70 text-slate-100 shadow-sm ring-1 ring-white/10' : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/40'}`}
                    >
                        Board
                    </button>
                    <button
                        onClick={() => setActiveTab('march')}
                        className={`px-4 py-2 text-sm font-semibold rounded-xl transition ${activeTab === 'march' ? 'bg-orange-600/80 text-white shadow-sm ring-1 ring-orange-400/30' : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/40'}`}
                    >
                        🏀 March Madness
                    </button>
                    <button
                        onClick={() => setActiveTab('history')}
                        className={`px-4 py-2 text-sm font-semibold rounded-xl transition ${activeTab === 'history' ? 'bg-slate-800/70 text-slate-100 shadow-sm ring-1 ring-white/10' : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/40'}`}
                    >
                        Model Performance
                    </button>
                </div>
            )
            }




            {
                activeTab === 'live' && (
                    <>
                        <div className="flex flex-col md:flex-row md:justify-between md:items-center gap-3 mb-4">
                            <div className="flex flex-wrap items-center gap-3">
                                {/* League Filter */}
                                <div className="flex items-center bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 focus-within:border-blue-500/50 transition-all w-full sm:w-auto">
                                    <Filter size={14} className="text-slate-500 mr-2" />
                                    <select
                                        value={leagueFilter}
                                        onChange={(e) => setLeagueFilter(e.target.value)}
                                        className="bg-transparent text-sm font-medium focus:outline-none cursor-pointer w-full"
                                    >
                                        <option value="NCAAM">NCAAM</option>
                                        <option value="NFL">NFL</option>
                                        <option value="EPL">EPL</option>
                                    </select>
                                </div>

                                {/* Date Navigation */}
                                <div className="flex items-center bg-slate-800 border border-slate-700 rounded-xl px-1 py-1 w-full sm:w-auto">
                                    <button onClick={() => shiftDate(-1)} className="p-1 px-2 hover:bg-slate-700 rounded text-slate-400 hover:text-white transition-colors">
                                        ←
                                    </button>
                                    <input
                                        type="date"
                                        value={selectedDate}
                                        onChange={(e) => setSelectedDate(e.target.value)}
                                        className="bg-transparent text-sm font-bold text-center w-32 sm:w-32 focus:outline-none text-white appearance-none"
                                    />
                                    <button onClick={() => shiftDate(1)} className="p-1 px-2 hover:bg-slate-700 rounded text-slate-400 hover:text-white transition-colors">
                                        →
                                    </button>
                                    <button onClick={() => setSelectedDate(getTodayStr())} className="ml-2 px-2 py-0.5 text-xs bg-blue-600/20 text-blue-400 hover:bg-blue-600/30 rounded">
                                        Today
                                    </button>
                                </div>

                                {/* Board tabs + Data health */}
                                <div className="inline-flex items-center gap-2">
                                    <div className="inline-flex items-center gap-1 p-1 rounded-xl bg-slate-950/30 border border-slate-700/40">
                                        <button
                                            onClick={() => setBoardTab('recommended')}
                                            className={`px-3 py-1.5 rounded-lg text-xs font-semibold border transition ${boardTab === 'recommended'
                                                ? 'bg-slate-800/70 text-slate-100 border-white/10 shadow-sm'
                                                : 'bg-transparent text-slate-400 border-transparent hover:bg-slate-800/40 hover:text-slate-200'
                                                }`}
                                        >
                                            Recommended
                                        </button>
                                        <button
                                            onClick={() => setBoardTab('full')}
                                            className={`px-3 py-1.5 rounded-lg text-xs font-semibold border transition ${boardTab === 'full'
                                                ? 'bg-slate-800/70 text-slate-100 border-white/10 shadow-sm'
                                                : 'bg-transparent text-slate-400 border-transparent hover:bg-slate-800/40 hover:text-slate-200'
                                                }`}
                                        >
                                            Full board
                                        </button>
                                    </div>

                                    {/* Data health shield (hover) */}
                                    {(() => {
                                        let tooltip = 'System status';
                                        let iconStatus = 'unknown';
                                        try {
                                            const fmtTime = (t) => {
                                                if (!t) return '—';
                                                try { return new Date(t).toLocaleString('en-US', { timeZone: 'America/New_York', hour: 'numeric', minute: '2-digit', month: '2-digit', day: '2-digit' }); } catch { return String(t); }
                                            };

                                            // Filter out seasonal NFL rows (no longer relevant)
                                            const items = (dataHealth || []).filter((x) => x && x.source && !String(x.source).includes('NFL'));
                                            const by = {};
                                            items.forEach((x) => { if (x?.source) by[x.source] = x; });

                                            const hasErr = items.some((x) => x?.status === 'error');
                                            const hasStale = items.some((x) => x?.status === 'stale');
                                            const hasAlert = items.some((x) => x?.status === 'alert');

                                            // Icon semantics:
                                            // - error => red
                                            // - stale => amber
                                            // - alert => amber (warning)
                                            // - ok => green
                                            if (hasErr) iconStatus = 'error';
                                            else if (hasStale) iconStatus = 'stale';
                                            else if (hasAlert) iconStatus = 'alert';
                                            else if (items.length) iconStatus = 'ok';
                                            else iconStatus = 'unknown';

                                            const ageMin = (t) => {
                                                if (!t) return null;
                                                try {
                                                    const ms = (new Date(t)).getTime();
                                                    if (!ms) return null;
                                                    return Math.round((Date.now() - ms) / 60000);
                                                } catch {
                                                    return null;
                                                }
                                            };

                                            const shortLine = (src) => {
                                                const x = by[src];
                                                if (!x) return `${src}: —`;
                                                const st = x.status || '—';
                                                const t = fmtTime(x.last_success_at);
                                                const m = ageMin(x.last_success_at);
                                                const ago = (m !== null && m >= 0) ? ` • ${m}m ago` : '';
                                                return `${src}: ${st} (${t})${ago}`;
                                            };

                                            // Plain English summary (do NOT say "job failing" unless error)
                                            if (iconStatus === 'ok') tooltip += `\nOK — everything updating.`;
                                            else if (iconStatus === 'alert') tooltip += `\nWarning — coverage looks thin (not a failure).`;
                                            else if (iconStatus === 'stale') tooltip += `\nStale — data not updating recently.`;
                                            else if (iconStatus === 'error') tooltip += `\nError — one or more jobs failed.`;
                                            else tooltip += `\nUnknown — no health data yet.`;

                                            const boardKey = (leagueFilter === 'EPL') ? 'board:EPL' : 'board:NCAAM';
                                            const key = ['odds', 'torvik', 'kenpom', boardKey];
                                            tooltip += `\n\nKey sources:`;
                                            tooltip += `\n- ${key.map(shortLine).join('\n- ')}`;

                                            const problems = items
                                                .filter((x) => x?.status && x.status !== 'ok')
                                                .slice();

                                            const note = (x) => {
                                                if (!x?.notes) return '';
                                                const s = String(x.notes);
                                                return s.length > 140 ? (s.slice(0, 140) + '…') : s;
                                            };

                                            if (problems.length) {
                                                const errs = problems.filter((x) => x.status === 'error');
                                                const stales = problems.filter((x) => x.status === 'stale');
                                                const alerts = problems.filter((x) => x.status === 'alert');

                                                if (errs.length) {
                                                    tooltip += `\n\nErrors (jobs failing):`;
                                                    errs.slice(0, 6).forEach((x) => {
                                                        tooltip += `\n- ${x.source} (${fmtTime(x.last_success_at)}): ${note(x) || 'error'}`;
                                                    });
                                                }
                                                if (stales.length) {
                                                    tooltip += `\n\nStale (no recent data):`;
                                                    stales.slice(0, 6).forEach((x) => {
                                                        tooltip += `\n- ${x.source} (${fmtTime(x.last_success_at)})${note(x) ? ` — ${note(x)}` : ''}`;
                                                    });
                                                }
                                                if (alerts.length) {
                                                    tooltip += `\n\nWarnings (coverage):`;
                                                    alerts.slice(0, 6).forEach((x) => {
                                                        tooltip += `\n- ${x.source} (${fmtTime(x.last_success_at)})${note(x) ? ` — ${note(x)}` : ''}`;
                                                    });
                                                }
                                            }

                                            try {
                                                const matched = (edges || []).filter((e) => (rowTopPicks?.[e?.id]?.rec)).length;
                                                const tp = topPicksStats || {};
                                                tooltip += `\n\nPicks:`
                                                    + ` games=${edges.length}`
                                                    + ` picks=${tp.withPick || 0}`
                                                    + ` actionable=${tp.actionable || 0}`
                                                    + ` matched=${matched}`
                                                    + (topPicksError ? `\nTop-picks error: ${String(topPicksError).slice(0, 140)}` : '');
                                            } catch { }

                                        } catch {
                                            // ignore
                                        }

                                        const Icon = (iconStatus === 'ok') ? ShieldCheck : (iconStatus === 'error') ? ShieldAlert : (iconStatus === 'stale' || iconStatus === 'alert') ? ShieldAlert : Shield;
                                        const color = (iconStatus === 'ok') ? 'text-emerald-400' : (iconStatus === 'error') ? 'text-red-400' : (iconStatus === 'stale' || iconStatus === 'alert') ? 'text-amber-300' : 'text-slate-400';

                                        return (
                                            <span className="inline-flex items-center">
                                                <span
                                                    className="inline-flex items-center cursor-help"
                                                    onMouseEnter={(e) => {
                                                        try {
                                                            const r = e.currentTarget.getBoundingClientRect();
                                                            const maxW = 560;
                                                            const pad = 12;
                                                            const x = Math.max(pad, Math.min(r.left, window.innerWidth - maxW - pad));
                                                            const y = Math.max(pad, Math.min(r.bottom + 8, window.innerHeight - 320));
                                                            if (dhHideTimer) { clearTimeout(dhHideTimer); setDhHideTimer(null); }
                                                            setDhTip({ open: true, pinned: false, x, y, text: tooltip });
                                                        } catch {
                                                            if (dhHideTimer) { clearTimeout(dhHideTimer); setDhHideTimer(null); }
                                                            setDhTip({ open: true, pinned: false, x: 16, y: 16, text: tooltip });
                                                        }
                                                    }}
                                                    onClick={() => setDhTip((p) => ({ ...p, open: true, pinned: !p?.pinned, text: tooltip }))}
                                                    onMouseLeave={() => {
                                                        if (dhTip?.pinned) return;
                                                        const t = setTimeout(() => setDhTip((p) => ({ ...p, open: false })), 350);
                                                        setDhHideTimer(t);
                                                    }}
                                                >
                                                    <Icon size={16} className={color} />
                                                </span>
                                            </span>
                                        );
                                    })()}
                                </div>
                            </div>
                        </div>

                        <div className="bg-slate-900/40 rounded-2xl border border-slate-700/40 shadow-xl overflow-hidden">

                            {loading && (
                                <div className="flex flex-col justify-center items-center py-20 bg-slate-800/50">
                                    <RefreshCw className="animate-spin text-blue-500 mb-4" size={32} />
                                    <span className="text-slate-400 font-medium tracking-wide">Crunching Monte Carlo & Poisson Sims...</span>
                                </div>
                            )}

                            {error && (
                                <div className="m-6 p-4 bg-red-900/20 border border-red-500/50 rounded-lg text-red-200 flex items-center">
                                    <AlertCircle className="mr-3 text-red-400" size={20} />
                                    {error}
                                </div>
                            )}

                            {degradedMode && (
                                <div className="m-6 p-4 bg-amber-900/20 border border-amber-500/40 rounded-lg text-amber-100 flex items-start">
                                    <ShieldAlert className="mr-3 mt-0.5 text-amber-300" size={20} />
                                    <div>
                                        <div className="font-semibold">Stale slate — latest full run produced NO BETS. Showing last cached picks.</div>
                                        {degradedAsOf && (
                                            <div className="text-xs text-amber-200/80 mt-1">As-of: {new Date(degradedAsOf).toLocaleString()}</div>
                                        )}
                                    </div>
                                </div>
                            )}

                            {!loading && !error && edges.length === 0 && (
                                <div className="text-center py-20 text-slate-500 flex flex-col items-center">
                                    <div className="p-4 bg-slate-700/30 rounded-full mb-4">
                                        <RefreshCw size={24} className="text-slate-600" />
                                    </div>
                                    <p>No active games found in current slate.</p>
                                </div>
                            )}

                            {/* (Removed) Historical Top Model Picks summary to reduce duplication. */}

                            {!loading && leagueFilter === 'NCAAM' && edges.length > 0 && (
                                <div className="px-6 pt-6">
                                    {(() => {
                                        // Show actionable edges up top (these are the actual "bets with an edge" today)
                                        // sourced from server-computed daily_top_picks.
                                        const isSameEtDay = (ts, ymd) => {
                                            if (!ts || !ymd) return false;
                                            try {
                                                const d = new Date(ts);
                                                const s = d.toLocaleDateString('en-CA', { timeZone: 'America/New_York' });
                                                return s === ymd;
                                            } catch (e) {
                                                return false;
                                            }
                                        };

                                        const norm = (s) => String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, '').trim();
                                        const makeKey = (dayEt, away, home) => {
                                            const d = String(dayEt || '').slice(0, 10);
                                            const a = norm(away);
                                            const h = norm(home);
                                            if (!d || !a || !h) return null;
                                            return `${d}|${a}|${h}`;
                                        };

                                        const actionableAll = getProcessedEdges()
                                            .map((e) => {
                                                const direct = rowTopPicks?.[e.id] || null;
                                                const k = makeKey(e?.day_et, e?.away_team, e?.home_team);
                                                const fallback = (k && rowTopPicksByKey?.[k]) ? rowTopPicksByKey[k] : null;
                                                const meta = direct || fallback;
                                                return { edge: e, top: meta?.rec || null, meta };
                                            })
                                            .filter(({ edge, top, meta }) => {
                                                if (!top || !meta?.isActionable) return false;
                                                // match selected ET date
                                                if (edge?.day_et) return String(edge.day_et) === String(selectedDate);
                                                return isSameEtDay(edge?.start_time, selectedDate);
                                            })
                                            .sort((a, b) => {
                                                const aEv = Number(String(a.top?.edge ?? '').replace('%', '').trim()) || 0;
                                                const bEv = Number(String(b.top?.edge ?? '').replace('%', '').trim()) || 0;
                                                return bEv - aEv;
                                            });

                                        const spreadTop = actionableAll.filter((x) => String(x?.top?.bet_type || '').toUpperCase() === 'SPREAD').slice(0, 5);
                                        const totalTop = actionableAll.filter((x) => String(x?.top?.bet_type || '').toUpperCase() === 'TOTAL').slice(0, 5);

                                        const topOverall = [...spreadTop, ...totalTop]
                                            .slice()
                                            .sort((a, b) => {
                                                const aEv = Number(String(a.top?.edge ?? '').replace('%', '').trim()) || 0;
                                                const bEv = Number(String(b.top?.edge ?? '').replace('%', '').trim()) || 0;
                                                return bEv - aEv;
                                            })
                                            .slice(0, 5);

                                        const actionable = topOverall;

                                        const fmtPick = (edge, top) => {
                                            let pickText = String(top.selection || '').trim();
                                            try {
                                                if (top.bet_type === 'SPREAD') {
                                                    if (/^home\b/i.test(pickText)) pickText = pickText.replace(/^home\b/i, edge.home_team);
                                                    if (/^away\b/i.test(pickText)) pickText = pickText.replace(/^away\b/i, edge.away_team);
                                                }
                                                if (top.bet_type === 'TOTAL') pickText = pickText.toUpperCase();
                                            } catch (e) { }
                                            return pickText;
                                        };

                                        // Removed per request: the "Today's edges" tile was duplicative with the main recommended picks.
                                        return null;
                                    })()}
                                </div>
                            )}

                            {!loading && edges.length > 0 && boardTab === 'recommended' && (
                                <div className="p-6">

                                    {/* Top 5 Plays + full recommended table (IIFE) */}
                                    {(() => {
                                        const isSameEtDay = (ts, ymd) => {
                                            if (!ts || !ymd) return false;
                                            try {
                                                const d = new Date(ts);
                                                const s = d.toLocaleDateString('en-CA', { timeZone: 'America/New_York' });
                                                return s === ymd;
                                            } catch (e) {
                                                return false;
                                            }
                                        };

                                        // Build Top-5 rows directly from stored daily_top_picks (rowTopPicks).
                                        // This decouples display from live board odds: if the morning model run
                                        // found an edge, show it — no live odds required.
                                        // If the evening run removes the edge (is_actionable=false), it disappears.
                                        const rows = (() => {
                                            const picks = rowTopPicks || {};
                                            return Object.entries(picks)
                                                .filter(([eid, meta]) => {
                                                    if (!meta?.isActionable) return false;
                                                    const top = meta?.rec;
                                                    if (!top) return false;
                                                    const bt = String(top.bet_type || '').toUpperCase();
                                                    const sel = String(top.selection || '').trim();
                                                    if (!bt || bt === 'AUTO') return false;
                                                    if (!sel || sel === '—') return false;
                                                    // Match selected ET date using event metadata stored in the pick
                                                    const ev = meta?.event || {};
                                                    const dayEt = ev?.day_et || '';
                                                    if (dayEt) return String(dayEt) === String(selectedDate);
                                                    // Fallback: parse start_time
                                                    if (ev?.start_time) {
                                                        try {
                                                            const d = new Date(ev.start_time);
                                                            const s = d.toLocaleDateString('en-CA', { timeZone: 'America/New_York' });
                                                            return s === String(selectedDate);
                                                        } catch (e) { return false; }
                                                    }
                                                    return false;
                                                })
                                                .map(([eid, meta]) => {
                                                    const ev = meta?.event || {};
                                                    // Build a synthetic edge object from stored event metadata
                                                    const edge = {
                                                        id: eid,
                                                        home_team: ev?.home_team || '',
                                                        away_team: ev?.away_team || '',
                                                        start_time: ev?.start_time || null,
                                                        day_et: ev?.day_et || selectedDate,
                                                        sport: 'NCAAM',
                                                    };
                                                    return { edge, top: meta.rec, meta };
                                                })
                                                .sort((a, b) => {
                                                    const aEv = Number(String(a.top?.edge ?? '').replace('%', '').trim()) || 0;
                                                    const bEv = Number(String(b.top?.edge ?? '').replace('%', '').trim()) || 0;
                                                    return bEv - aEv;
                                                });
                                        })();

                                        if (!rows.length) {
                                            return (
                                                <div className="text-slate-500">
                                                    No recommendations available for this window.
                                                </div>
                                            );
                                        }

                                        const fmtPick = (edge, top) => {
                                            let pickText = String(top.selection || '').trim();
                                            try {
                                                if (top.bet_type === 'SPREAD') {
                                                    if (/^home\b/i.test(pickText)) pickText = pickText.replace(/^home\b/i, edge.home_team);
                                                    if (/^away\b/i.test(pickText)) pickText = pickText.replace(/^away\b/i, edge.away_team);
                                                }
                                                if (top.bet_type === 'TOTAL') pickText = pickText.toUpperCase();
                                            } catch (e) { }
                                            return pickText;
                                        };

                                        const top6 = rows.slice(0, 5);

                                        return (
                                            <div className="mb-6">
                                                <div className="flex items-center gap-2 mb-3">
                                                    <TrendingUp className="text-emerald-400" size={18} />
                                                    <div className="text-sm font-black text-slate-100 uppercase tracking-wider">Top 5 Plays Today</div>
                                                    <div className="text-[10px] text-slate-500 ml-auto">{selectedDate} • Sorted by EV%</div>
                                                </div>
                                                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                                                    {top6.map(({ edge, top }, i) => {
                                                        const date = edge.start_time ? new Date(edge.start_time) : null;
                                                        const timeStr = date ? date.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', timeZone: 'America/New_York' }) : '';
                                                        const pickText = fmtPick(edge, top);
                                                        const evRaw = String(top.edge || '').replace('%', '').trim();
                                                        const evNum = Number(evRaw);
                                                        const evFormatted = `${evNum >= 0 ? '+' : ''}${evNum.toFixed(1)}%`;

                                                        return (
                                                            <div key={edge.id} className="relative overflow-hidden p-4 rounded-xl border border-slate-700/60 bg-gradient-to-br from-slate-900 to-slate-950 shadow-lg flex flex-col gap-3 transition hover:border-slate-500/50">
                                                                <div className="flex items-center justify-between border-b border-slate-800/60 pb-3">
                                                                    <div className="flex items-center gap-2">
                                                                        <span className="flex items-center justify-center w-5 h-5 rounded-full bg-emerald-500 text-slate-950 text-[10px] font-black">{i + 1}</span>
                                                                        <span className="text-xs font-bold text-slate-300">NCAAM Pick</span>
                                                                    </div>
                                                                    <div className="flex items-center gap-1 bg-green-500/10 px-2 py-1 rounded-md border border-green-500/20">
                                                                        <TrendingUp size={12} className="text-green-400" />
                                                                        <span className="text-[11px] font-black text-green-400">{evFormatted} EV</span>
                                                                    </div>
                                                                </div>
                                                                <div className="flex flex-col gap-1 min-w-0">
                                                                    <div className="flex items-center gap-2">
                                                                        <span className="text-[10px] text-slate-500 font-bold uppercase">{timeStr}</span>
                                                                        <span className="text-xs text-slate-400 font-medium truncate">{edge.away_team} @ {edge.home_team}</span>
                                                                    </div>
                                                                    <div className="flex items-baseline justify-between gap-4">
                                                                        <div className="flex flex-col min-w-0">
                                                                            <span className="text-[10px] text-slate-500 font-bold uppercase tracking-wider">{top.bet_type}</span>
                                                                            <span className="text-sm font-bold text-slate-100 whitespace-normal leading-tight">{pickText}</span>
                                                                        </div>
                                                                        <div className="flex flex-col items-end shrink-0">
                                                                            <span className="text-xs font-mono font-bold text-slate-400">{(top.price !== null && top.price !== undefined) ? fmtSigned(top.price, 0) : '—'}</span>
                                                                            <span className="text-[10px] text-slate-500 uppercase font-bold">{top.confidence}</span>
                                                                        </div>
                                                                    </div>
                                                                </div>
                                                                <div className="flex gap-2 mt-auto pt-2 border-t border-slate-800/40">
                                                                    <button
                                                                        onClick={() => onAddBet?.({
                                                                            sport: edge.sport,
                                                                            game: `${edge.away_team} @ ${edge.home_team}`,
                                                                            market: top.bet_type,
                                                                            pick: pickText,
                                                                            line: top.market_line,
                                                                            odds: top.price,
                                                                            book: top.book,
                                                                        })}
                                                                        className="flex-1 py-1.5 rounded-lg bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 text-[10px] font-black border border-emerald-500/20 transition-colors uppercase tracking-widest"
                                                                    >
                                                                        Add
                                                                    </button>
                                                                    <button
                                                                        onClick={() => analyzeGame(edge)}
                                                                        className="flex-1 py-1.5 rounded-lg bg-slate-800/40 hover:bg-slate-700/40 text-slate-300 text-[10px] font-black border border-slate-700/50 transition-colors uppercase tracking-widest"
                                                                    >
                                                                        Details
                                                                    </button>
                                                                </div>
                                                            </div>
                                                        );
                                                    })}
                                                </div>
                                            </div>
                                        );
                                    })()}

                                    {/* 2-leg ML Parlay recommendations — below Top 5 Plays */}
                                    {leagueFilter === 'NCAAM' && String(selectedDate) === String(getTodayStr()) && (
                                        <ParlayRecommendations />
                                    )}

                                </div>
                            )}

                            {!loading && edges.length > 0 && boardTab === 'full' && (
                                <div className="overflow-x-auto">
                                    <table className="w-full text-left border-collapse">
                                        <thead>
                                            <tr className="text-slate-400 border-b border-slate-700 bg-slate-800/50">
                                                <th className="py-2 px-4 text-xs font-bold uppercase tracking-wider cursor-pointer hover:text-white transition-colors" onClick={() => handleSort('start_time')}>
                                                    <div className="flex items-center">Time <SortIcon column="start_time" /></div>
                                                </th>
                                                <th className="py-2 px-4 text-xs font-bold uppercase tracking-wider cursor-pointer hover:text-white transition-colors" onClick={() => handleSort('sport')}>
                                                    <div className="flex items-center">League <SortIcon column="sport" /></div>
                                                </th>
                                                <th className="py-2 px-4 text-xs font-bold uppercase tracking-wider cursor-pointer hover:text-white transition-colors" onClick={() => handleSort('game')}>
                                                    <div className="flex items-center">Matchup <SortIcon column="game" /></div>
                                                </th>
                                                {leagueFilter === 'EPL' ? (
                                                    <>
                                                        <th className="py-2 px-4 text-xs font-bold uppercase tracking-wider">
                                                            <div className="flex items-center">Moneyline (1X2)</div>
                                                        </th>
                                                        <th className="py-2 px-4 text-xs font-bold uppercase tracking-wider">
                                                            <div className="flex items-center">Total Goals (O/U)</div>
                                                        </th>
                                                    </>
                                                ) : (
                                                    <>
                                                        <th className="py-2 px-4 text-xs font-bold uppercase tracking-wider">
                                                            <div className="flex items-center">Spread (both sides)</div>
                                                        </th>
                                                        <th className="py-2 px-4 text-xs font-bold uppercase tracking-wider">
                                                            <div className="flex items-center">Total (O/U)</div>
                                                        </th>
                                                    </>
                                                )}
                                                <th className="py-2 px-4 text-xs font-bold uppercase tracking-wider text-center">
                                                    <div className="flex items-center justify-center">Action</div>
                                                </th>
                                            </tr>
                                        </thead>
                                        <tbody className="divide-y divide-slate-700/50">
                                            {getProcessedEdges().length === 0 ? (
                                                <tr>
                                                    <td colSpan="9" className="py-12 text-center text-slate-500">
                                                        <div className="flex flex-col items-center justify-center">
                                                            <Filter size={32} className="mb-3 opacity-20" />
                                                            <p className="text-lg font-medium text-slate-400">No games found for this league/date range.</p>
                                                        </div>
                                                    </td>
                                                </tr>
                                            ) : (
                                                (() => {
                                                    const isSameEtDay = (ts, ymd) => {
                                                        if (!ts || !ymd) return false;
                                                        try {
                                                            const d = new Date(ts);
                                                            const s = d.toLocaleDateString('en-CA', { timeZone: 'America/New_York' });
                                                            return s === ymd;
                                                        } catch (e) {
                                                            return false;
                                                        }
                                                    };

                                                    const boardEdges = (!showModelPerformanceTab)
                                                        ? getProcessedEdges().filter((e) => isSameEtDay(e?.start_time, selectedDate))
                                                        : getProcessedEdges();

                                                    return boardEdges.map((edge, idx) => {
                                                        const date = edge.start_time ? new Date(edge.start_time) : null;
                                                        const dateStr = date ? date.toLocaleDateString('en-US', { month: '2-digit', day: '2-digit', year: 'numeric', timeZone: 'America/New_York' }) : '-';
                                                        const timeStr = date ? date.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', timeZone: 'America/New_York' }) : '';
                                                        const isEdge = edge.is_actionable;

                                                        return (
                                                            <tr key={idx} className={`group hover:bg-slate-700/30 transition-all border-b border-slate-700/30`}>
                                                                <td className="py-3 px-4 text-slate-400 text-xs whitespace-nowrap">
                                                                    {edge.final ? (
                                                                        <div className="flex flex-col">
                                                                            <span className="font-bold text-slate-500 uppercase tracking-wider">Final</span>
                                                                            <span className="text-white font-mono">{edge.home_score}-{edge.away_score}</span>
                                                                        </div>
                                                                    ) : (
                                                                        <>
                                                                            <div className="font-bold text-slate-300">{dateStr}</div>
                                                                            <div>{timeStr}</div>
                                                                        </>
                                                                    )}
                                                                </td>
                                                                <td className="py-3 px-4">
                                                                    <span className={`text-[10px] font-black px-2 py-0.5 rounded tracking-tighter uppercase
                                                                ${edge.sport === 'NFL' ? 'bg-blue-500/20 text-blue-400 border border-blue-500/20' :
                                                                            edge.sport === 'NCAAM' ? 'bg-orange-500/20 text-orange-400 border border-orange-500/20' :
                                                                                edge.sport === 'NCAAF' ? 'bg-amber-500/20 text-amber-400 border border-amber-500/20' :
                                                                                    'bg-slate-700/50 text-slate-400 border border-slate-600'
                                                                        }`}>
                                                                        {edge.sport}
                                                                    </span>
                                                                </td>
                                                                <td className="py-3 px-4 font-bold text-slate-100 text-sm tracking-tight">{edge.away_team} @ {edge.home_team}</td>
                                                                {leagueFilter === 'EPL' ? (
                                                                    <>
                                                                        <td className="py-3 px-4">
                                                                            {(edge.ml_home_odds !== null && edge.ml_home_odds !== undefined) || (edge.ml_away_odds !== null && edge.ml_away_odds !== undefined) || (edge.ml_draw_odds !== null && edge.ml_draw_odds !== undefined) ? (
                                                                                <div className="flex flex-col gap-1">
                                                                                    <div className="flex justify-between gap-2 text-xs">
                                                                                        <span className="text-slate-400 truncate">HOME</span>
                                                                                        <span className="text-white font-mono font-bold whitespace-nowrap">{fmtSigned(edge.ml_home_odds)}</span>
                                                                                    </div>
                                                                                    <div className="flex justify-between gap-2 text-xs">
                                                                                        <span className="text-slate-400 truncate">DRAW</span>
                                                                                        <span className="text-white font-mono font-bold whitespace-nowrap">{fmtSigned(edge.ml_draw_odds)}</span>
                                                                                    </div>
                                                                                    <div className="flex justify-between gap-2 text-xs">
                                                                                        <span className="text-slate-400 truncate">AWAY</span>
                                                                                        <span className="text-white font-mono font-bold whitespace-nowrap">{fmtSigned(edge.ml_away_odds)}</span>
                                                                                    </div>
                                                                                    <div className="text-[10px] text-slate-600">1X2 market odds</div>
                                                                                </div>
                                                                            ) : (
                                                                                <span className="text-slate-600 font-mono text-xs">No moneyline</span>
                                                                            )}
                                                                        </td>
                                                                        <td className="py-3 px-4">
                                                                            {edge.total_line !== null && edge.total_line !== undefined ? (
                                                                                <div className="flex flex-col gap-1">
                                                                                    <div className="flex justify-between gap-2 text-xs">
                                                                                        <span className="text-slate-400">OVER</span>
                                                                                        <span className="text-white font-mono font-bold whitespace-nowrap">{Number(edge.total_line).toFixed(1)}</span>
                                                                                        <span className="text-slate-500 font-mono whitespace-nowrap">{fmtSigned(edge.total_over_odds)}</span>
                                                                                    </div>
                                                                                    <div className="flex justify-between gap-2 text-xs">
                                                                                        <span className="text-slate-400">UNDER</span>
                                                                                        <span className="text-white font-mono font-bold whitespace-nowrap">{Number(edge.total_line).toFixed(1)}</span>
                                                                                        <span className="text-slate-500 font-mono whitespace-nowrap">{fmtSigned(edge.total_under_odds)}</span>
                                                                                    </div>
                                                                                    <div className="text-[10px] text-slate-600">goals total (O/U)</div>
                                                                                </div>
                                                                            ) : (
                                                                                <span className="text-slate-600 font-mono text-xs">No total</span>
                                                                            )}
                                                                        </td>
                                                                    </>
                                                                ) : (
                                                                    <>
                                                                        <td className="py-3 px-4">
                                                                            {(edge.home_spread !== null && edge.home_spread !== undefined) || (edge.away_spread !== null && edge.away_spread !== undefined) ? (
                                                                                <div className="flex flex-col gap-1">
                                                                                    <div className="flex justify-between gap-2 text-xs">
                                                                                        <span className="text-slate-400 truncate">{edge.away_team}</span>
                                                                                        <span className="text-white font-mono font-bold whitespace-nowrap">
                                                                                            {fmtSigned(edge.away_spread ?? (edge.home_spread != null ? -Number(edge.home_spread) : null), 1)}
                                                                                        </span>
                                                                                        <span className="text-slate-500 font-mono whitespace-nowrap">
                                                                                            {fmtSigned(edge.spread_away_odds)}
                                                                                        </span>
                                                                                    </div>
                                                                                    <div className="flex justify-between gap-2 text-xs">
                                                                                        <span className="text-slate-400 truncate">{edge.home_team}</span>
                                                                                        <span className="text-white font-mono font-bold whitespace-nowrap">
                                                                                            {fmtSigned(edge.home_spread, 1)}
                                                                                        </span>
                                                                                        <span className="text-slate-500 font-mono whitespace-nowrap">
                                                                                            {fmtSigned(edge.spread_home_odds ?? edge.moneyline_home)}
                                                                                        </span>
                                                                                    </div>
                                                                                    <div className="text-[10px] text-slate-600">team • line • odds</div>
                                                                                </div>
                                                                            ) : (
                                                                                <span className="text-slate-600 font-mono text-xs">No spread</span>
                                                                            )}
                                                                        </td>
                                                                        <td className="py-3 px-4">
                                                                            {edge.total_line !== null && edge.total_line !== undefined ? (
                                                                                <div className="flex flex-col gap-1">
                                                                                    <div className="flex justify-between gap-2 text-xs">
                                                                                        <span className="text-slate-400">OVER</span>
                                                                                        <span className="text-white font-mono font-bold whitespace-nowrap">{Number(edge.total_line).toFixed(1)}</span>
                                                                                        <span className="text-slate-500 font-mono whitespace-nowrap">{fmtSigned(edge.total_over_odds ?? edge.moneyline_away)}</span>
                                                                                    </div>
                                                                                    <div className="flex justify-between gap-2 text-xs">
                                                                                        <span className="text-slate-400">UNDER</span>
                                                                                        <span className="text-white font-mono font-bold whitespace-nowrap">{Number(edge.total_line).toFixed(1)}</span>
                                                                                        <span className="text-slate-500 font-mono whitespace-nowrap">{fmtSigned(edge.total_under_odds)}</span>
                                                                                    </div>
                                                                                    <div className="text-[10px] text-slate-600">side • line • odds</div>
                                                                                </div>
                                                                            ) : (
                                                                                <span className="text-slate-600 font-mono text-xs">No total</span>
                                                                            )}
                                                                        </td>
                                                                    </>
                                                                )}
                                                                <td className="py-3 px-4 text-center">
                                                                    {(() => {
                                                                        const meta = rowTopPicks?.[edge.id] || null;
                                                                        const top = meta?.rec || null;
                                                                        if (top) {
                                                                            return (
                                                                                <div className="flex flex-col items-center gap-2">
                                                                                    <div className="px-2 py-0.5 rounded bg-indigo-500/20 text-indigo-300 text-[10px] font-black uppercase tracking-widest">
                                                                                        Top pick
                                                                                    </div>
                                                                                    <div className="text-xs font-bold text-white max-w-[180px] truncate" title={top.selection}>
                                                                                        {top.selection}
                                                                                    </div>
                                                                                    <div className="text-[11px] text-green-300 font-mono font-bold">+{top.edge}</div>
                                                                                    <div className="flex items-center gap-2">
                                                                                        <button
                                                                                            onClick={() => onAddBet?.({
                                                                                                sport: edge.sport,
                                                                                                game: `${edge.away_team} @ ${edge.home_team}`,
                                                                                                market: top.bet_type,
                                                                                                pick: top.selection,
                                                                                                line: top.market_line,
                                                                                                odds: top.price,
                                                                                                book: top.book,
                                                                                            })}
                                                                                            className="px-3 py-1 bg-green-500/20 text-green-300 hover:bg-green-500/30 border border-green-500/30 rounded text-xs font-bold transition-colors"
                                                                                        >
                                                                                            Add
                                                                                        </button>
                                                                                        <button
                                                                                            onClick={() => analyzeGame(edge)}
                                                                                            className="px-3 py-1 bg-slate-800/60 text-slate-200 hover:bg-slate-800 border border-slate-700 rounded text-xs font-bold transition-colors"
                                                                                        >
                                                                                            Details
                                                                                        </button>
                                                                                    </div>
                                                                                </div>
                                                                            );
                                                                        }

                                                                        // If server computed a No-Bet state, show it.
                                                                        if (meta && meta.isActionable === false) {
                                                                            return (
                                                                                <div className="flex flex-col items-center gap-2">
                                                                                    <div className="px-2 py-0.5 rounded bg-slate-800/60 text-slate-300 text-[10px] font-black uppercase tracking-widest border border-slate-700/60">
                                                                                        No Bet
                                                                                    </div>
                                                                                    <div className="text-[11px] text-slate-400 max-w-[220px] truncate" title={meta.reason || ''}>
                                                                                        {meta.reason || 'Blocked'}
                                                                                    </div>
                                                                                    <button
                                                                                        onClick={() => analyzeGame(edge)}
                                                                                        disabled={leagueFilter !== 'NCAAM' || (isAnalyzing && selectedGame?.id === edge.id)}
                                                                                        className={`px-4 py-1.5 rounded-lg text-xs font-bold transition-all shadow-lg ring-1 ring-white/10 flex items-center justify-center mx-auto ${(isAnalyzing && selectedGame?.id === edge.id)
                                                                                            ? 'bg-slate-700 text-slate-400'
                                                                                            : 'bg-slate-800 hover:bg-slate-700 text-slate-200'
                                                                                            }`}
                                                                                    >
                                                                                        {isAnalyzing && selectedGame?.id === edge.id ? <RefreshCw className="animate-spin" size={14} /> : 'Details'}
                                                                                    </button>
                                                                                </div>
                                                                            );
                                                                        }

                                                                        // Default: show quick-pick + analyze
                                                                        return (
                                                                            <div className="flex flex-col items-center gap-2">
                                                                                <button
                                                                                    onClick={() => quickPick(edge)}
                                                                                    disabled={leagueFilter !== 'NCAAM' || rowPickingId === edge.id}
                                                                                    className={`px-3 py-1 rounded text-xs font-bold transition-colors border ${rowPickingId === edge.id
                                                                                        ? 'bg-slate-700 text-slate-400 border-slate-600'
                                                                                        : 'bg-indigo-500/20 text-indigo-200 hover:bg-indigo-500/30 border-indigo-500/30'
                                                                                        }`}
                                                                                >
                                                                                    {rowPickingId === edge.id ? 'Picking…' : 'Quick pick'}
                                                                                </button>
                                                                                <button
                                                                                    onClick={() => analyzeGame(edge)}
                                                                                    disabled={leagueFilter !== 'NCAAM' || (isAnalyzing && selectedGame?.id === edge.id)}
                                                                                    className={`px-4 py-1.5 rounded-lg text-xs font-bold transition-all shadow-lg ring-1 ring-white/10 flex items-center justify-center mx-auto ${(isAnalyzing && selectedGame?.id === edge.id)
                                                                                        ? 'bg-slate-700 text-slate-400'
                                                                                        : 'bg-indigo-600 hover:bg-indigo-500 text-white'
                                                                                        }`}
                                                                                >
                                                                                    {isAnalyzing && selectedGame?.id === edge.id ? <RefreshCw className="animate-spin" size={14} /> : 'Analyze'}
                                                                                </button>
                                                                            </div>
                                                                        );
                                                                    })()}
                                                                </td>
                                                            </tr>
                                                        );
                                                    });
                                                })()
                                            )}
                                        </tbody>
                                    </table>
                                </div>
                            )}
                        </div>
                    </>
                )
            }

            {
                activeTab === 'history' && (
                    <div className="bg-slate-900/40 rounded-2xl border border-slate-700/40 shadow-xl overflow-hidden">
                        <div className="px-6 py-4 border-b border-slate-700/40 flex justify-between items-center bg-slate-900/20">
                            <h2 className="text-lg font-semibold text-slate-200">
                                {(() => {
                                    const hist = getRecommendedHistory();
                                    const etDay = (ts) => {
                                        try {
                                            return new Date(ts).toLocaleDateString('en-CA', { timeZone: 'America/New_York' });
                                        } catch (e) {
                                            return null;
                                        }
                                    };
                                    const days = [...new Set(hist.map(h => etDay(h?.analyzed_at || h?.created_at)).filter(Boolean))].sort();
                                    const lastDay = days.length ? days[days.length - 1] : null;
                                    const fmtMDY = (ymd) => {
                                        try {
                                            const [yy, mm, dd] = String(ymd || '').split('-');
                                            if (yy && mm && dd) return `${mm}/${dd}/${yy}`;
                                        } catch (e) { }
                                        return ymd || '';
                                    };
                                    return `Model Performance${lastDay ? ` — ${fmtMDY(lastDay)}` : ''}`;
                                })()}
                            </h2>
                            <div className="flex items-center gap-6">
                            </div>
                        </div>

                        {/* Model Performance Summary removed (covered by analytics below) */}

                        {/* Today's recommended tile removed (History tab is historical only) */}

                        {!loading && getRecommendedHistory().length === 0 && (
                            <div className="text-center py-10 text-slate-500">
                                No recommended-bet history yet.
                            </div>
                        )}

                        {!loading && getRecommendedHistory().length > 0 && (
                            <>
                                {/* Daily recap (most recent graded ET day) */}
                                <div className="px-6 py-4 border-b border-slate-700 bg-slate-900/20">
                                    {(() => {
                                        const hist = getRecommendedHistory();
                                        const etDay = (ts) => {
                                            try {
                                                return new Date(ts).toLocaleDateString('en-CA', { timeZone: 'America/New_York' });
                                            } catch (e) {
                                                return null;
                                            }
                                        };
                                        const normOutcome = (x) => {
                                            const o = (x?.graded_result || x?.outcome || x?.result || 'PENDING');
                                            const s = String(o).toUpperCase();
                                            if (s === 'WON' || s === 'WIN') return 'WON';
                                            if (s === 'LOST' || s === 'LOSS') return 'LOST';
                                            if (s === 'PUSH') return 'PUSH';
                                            return 'PENDING';
                                        };

                                        const days = [...new Set(hist.map(h => etDay(h?.analyzed_at || h?.created_at)).filter(Boolean))].sort();
                                        const lastDay = days.length ? days[days.length - 1] : null;
                                        const dayRows = lastDay ? hist.filter(h => etDay(h?.analyzed_at || h?.created_at) === lastDay) : [];
                                        const graded = dayRows.filter(h => ['WON', 'LOST', 'PUSH'].includes(normOutcome(h)));
                                        const w = graded.filter(h => normOutcome(h) === 'WON').length;
                                        const l = graded.filter(h => normOutcome(h) === 'LOST').length;
                                        const p = graded.filter(h => normOutcome(h) === 'PUSH').length;
                                        const winRate = (w + l) ? (w / (w + l) * 100) : 0;

                                        const confBucket = (h) => {
                                            const c = Number(h?.confidence_0_100 ?? h?.confidence ?? h?.confidence0_100 ?? 0);
                                            if (c >= 80) return 'High';
                                            if (c >= 50) return 'Medium';
                                            return 'Low';
                                        };

                                        const byConf = { High: [], Medium: [], Low: [] };
                                        graded.forEach((h) => {
                                            byConf[confBucket(h)].push(h);
                                        });

                                        const confStats = (arr) => {
                                            const ww = arr.filter(x => normOutcome(x) === 'WON').length;
                                            const ll = arr.filter(x => normOutcome(x) === 'LOST').length;
                                            const pp = arr.filter(x => normOutcome(x) === 'PUSH').length;
                                            const wr = (ww + ll) ? (ww / (ww + ll) * 100) : null;
                                            return { w: ww, l: ll, p: pp, wr };
                                        };

                                        const hi = confStats(byConf.High);
                                        const md = confStats(byConf.Medium);
                                        const lo = confStats(byConf.Low);

                                        const fmtMDY = (ymd) => {
                                            try {
                                                const [yy, mm, dd] = String(ymd || '').split('-');
                                                if (yy && mm && dd) return `${mm}/${dd}/${yy}`;
                                            } catch (e) { }
                                            return ymd || '—';
                                        };

                                        return (
                                            <>
                                                <div className="flex items-end justify-between gap-4 mb-3">
                                                    <div>
                                                        <div className="text-white font-black text-xl">{fmtMDY(lastDay)}</div>
                                                    </div>
                                                    <div className="text-[11px] text-slate-500">most recent day in history</div>
                                                </div>

                                                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                                                    <div className="bg-slate-950/20 border border-slate-700/40 rounded-2xl p-4">
                                                        <div className="text-[11px] text-slate-400 font-semibold">Bets graded</div>
                                                        <div className="mt-1 text-slate-100 font-black text-3xl">{graded.length}</div>
                                                        <div className="text-[11px] text-slate-400">W / L / P only</div>
                                                        {dayRows.length !== graded.length && (
                                                            <div className="text-[12px] text-slate-300 mt-1">Pending: {Math.max(0, dayRows.length - graded.length)}</div>
                                                        )}
                                                    </div>
                                                    <div className="bg-slate-950/20 border border-slate-700/40 rounded-2xl p-4">
                                                        <div className="text-[11px] text-slate-400 font-semibold">Record</div>
                                                        <div className="mt-1 text-slate-100 font-black text-3xl">{w}-{l}{p ? `-${p}` : ''}</div>
                                                        <div className="text-[11px] text-slate-400">graded only</div>
                                                    </div>
                                                    <div className="bg-slate-950/20 border border-slate-700/40 rounded-2xl p-4">
                                                        <div className="text-[11px] text-slate-400 font-semibold">Win rate</div>
                                                        <div className="mt-1 text-slate-100 font-black text-3xl">{(w + l) ? `${winRate.toFixed(1)}%` : '—'}</div>
                                                        <div className="text-[11px] text-slate-400">W/L only</div>
                                                    </div>
                                                </div>

                                                <div className="mt-3 grid grid-cols-1 md:grid-cols-3 gap-3">
                                                    {(() => {
                                                        const tiles = [
                                                            { label: 'High', s: hi, cls: 'text-green-300' },
                                                            { label: 'Medium', s: md, cls: 'text-amber-300' },
                                                            { label: 'Low', s: lo, cls: 'text-purple-300' },
                                                        ];
                                                        return tiles.map(({ label, s, cls }) => (
                                                            <div key={label} className="bg-slate-950/20 border border-slate-700/40 rounded-2xl p-4">
                                                                <div className="text-[11px] text-slate-400 font-semibold">{label} confidence</div>
                                                                <div className={`mt-1 font-black text-xl ${cls}`}>{s.w}-{s.l}{s.p ? `-${s.p}` : ''}</div>
                                                                <div className="text-[11px] text-slate-400">Win%: <span className="text-slate-200 font-semibold">{s.wr === null ? '—' : `${s.wr.toFixed(1)}%`}</span> • N={(s.w + s.l + s.p)}</div>
                                                            </div>
                                                        ));
                                                    })()}
                                                </div>
                                            </>
                                        );
                                    })()}
                                </div>

                                <ModelPerformanceAnalytics history={getRecommendedHistory()} />

                                <div className="overflow-x-auto">
                                    <table className="w-full text-left border-collapse">
                                        <thead>
                                            <tr className="text-slate-400 border-b border-slate-700 bg-slate-800/50">
                                                <th className="py-2 px-4 text-xs font-bold uppercase tracking-wider cursor-pointer hover:text-white transition-colors" onClick={() => handleSort('created_at')}>
                                                    <div className="flex items-center">Date <SortIcon column="created_at" /></div>
                                                </th>
                                                <th className="py-2 px-4 text-xs font-bold uppercase tracking-wider">Rec#</th>
                                                <th className="py-2 px-4 text-xs font-bold uppercase tracking-wider cursor-pointer hover:text-white transition-colors" onClick={() => handleSort('sport')}>
                                                    <div className="flex items-center">Sport <SortIcon column="sport" /></div>
                                                </th>
                                                <th className="py-2 px-4 text-xs font-bold uppercase tracking-wider cursor-pointer hover:text-white transition-colors" onClick={() => handleSort('matchup')}>
                                                    <div className="flex items-center">Matchup <SortIcon column="matchup" /></div>
                                                </th>
                                                <th className="py-2 px-4 text-xs font-bold uppercase tracking-wider cursor-pointer hover:text-white transition-colors" onClick={() => handleSort('bet_on')}>
                                                    <div className="flex items-center">Pick <SortIcon column="bet_on" /></div>
                                                </th>
                                                <th className="py-2 px-4 text-xs font-bold uppercase tracking-wider">Lines</th>
                                                <th className="py-2 px-4 text-xs font-bold uppercase tracking-wider cursor-pointer hover:text-white transition-colors" onClick={() => handleSort('edge')}>
                                                    <div className="flex items-center">Edge <SortIcon column="edge" /></div>
                                                </th>
                                                <th className="py-2 px-4 text-xs font-bold uppercase tracking-wider cursor-pointer hover:text-white transition-colors" onClick={() => handleSort('result')}>
                                                    <div className="flex items-center">Result <SortIcon column="result" /></div>
                                                </th>
                                                <th className="py-2 px-4 text-xs font-bold uppercase tracking-wider">Score</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {(() => {
                                                const histAll = getRecommendedHistory();
                                                const etDay = (ts) => {
                                                    try {
                                                        return new Date(ts).toLocaleDateString('en-CA', { timeZone: 'America/New_York' });
                                                    } catch (e) {
                                                        return null;
                                                    }
                                                };
                                                const keyFor = (x) => {
                                                    return String(x?.id || '')
                                                        || `${x?.event_id || 'evt'}|${x?.market_type || x?.market || ''}|${x?.selection || ''}|${x?.bet_price || ''}|${x?.analyzed_at || x?.created_at || ''}`;
                                                };

                                                // Rank = order recommended (per ET day), approximated as EV-sorted (same as Top picks texts).
                                                const rankByKey = {};
                                                const groups = {};
                                                histAll.forEach((h) => {
                                                    const d = etDay(h?.analyzed_at || h?.created_at);
                                                    if (!d) return;
                                                    groups[d] = groups[d] || [];
                                                    groups[d].push(h);
                                                });
                                                Object.keys(groups).forEach((d) => {
                                                    const arr = groups[d];
                                                    arr.sort((a, b) => {
                                                        const ae = Number(a?.ev_per_unit ?? a?.ev ?? 0);
                                                        const be = Number(b?.ev_per_unit ?? b?.ev ?? 0);
                                                        return be - ae;
                                                    });
                                                    arr.forEach((h, i) => {
                                                        rankByKey[keyFor(h)] = i + 1;
                                                    });
                                                });

                                                return histAll.map((item, idx) => {
                                                    // Robust Recommendation Parsing
                                                    let recs = [];
                                                    try {
                                                        if (item.outputs_json) {
                                                            const out = JSON.parse(item.outputs_json);
                                                            if (out.recommendations) recs = out.recommendations;
                                                        }
                                                        if (recs.length === 0 && item.recommendation_json) {
                                                            recs = JSON.parse(item.recommendation_json);
                                                        }
                                                        // Fallback to legacy fields if needed
                                                        if (recs.length === 0 && item.pick) {
                                                            recs = [{ side: item.pick, line: item.bet_line, edge: item.ev_per_unit || item.edge }];
                                                        }
                                                    } catch (e) {
                                                        console.warn('Failed to parse history recs', e);
                                                    }

                                                    const recRank = rankByKey[keyFor(item)] || null;

                                                    const mainRec = recs[0] || {};

                                                    // Result Logic
                                                    const resultStatus = item.graded_result || item.outcome || 'Pending';

                                                    return (
                                                        <tr key={item.id || `${item.event_id || 'evt'}:${idx}`} className="border-b border-slate-700/50 hover:bg-slate-700/30 transition-colors">
                                                            <td className="py-2 px-4 text-slate-400 text-xs whitespace-nowrap">
                                                                <div className="font-bold text-slate-300">
                                                                    {new Date(item.analyzed_at).toLocaleDateString('en-US', { month: '2-digit', day: '2-digit', year: 'numeric' })}
                                                                </div>
                                                                <div className="opacity-70">
                                                                    {new Date(item.analyzed_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}
                                                                </div>
                                                            </td>
                                                            <td className="py-2 px-4 text-xs text-slate-300 font-mono">
                                                                {recRank ? `#${recRank}` : '—'}
                                                            </td>
                                                            <td className="py-2 px-4">
                                                                <span className={`text-[10px] font-black px-2 py-0.5 rounded tracking-tighter uppercase
                                                        ${item.league === 'NFL' ? 'bg-blue-500/20 text-blue-400 border border-blue-500/20' :
                                                                        item.league === 'NCAAM' ? 'bg-orange-500/20 text-orange-400 border border-orange-500/20' :
                                                                            item.league === 'NCAAF' ? 'bg-amber-500/20 text-amber-400 border border-amber-500/20' :
                                                                                'bg-slate-700/50 text-slate-400 border border-slate-600'}`}>
                                                                    {item.league}
                                                                </span>
                                                            </td>
                                                            <td className="py-2 px-4 font-medium text-sm text-slate-200">{item.away_team} @ {item.home_team}</td>
                                                            <td className="py-2 px-4 text-white font-bold">
                                                                {(() => {
                                                                    const rawSide = mainRec.side;
                                                                    const sideStr = String(rawSide || '').trim();
                                                                    const sideKey = sideStr.toLowerCase();

                                                                    // Map HOME/AWAY to actual team names for readability.
                                                                    const side = (sideKey === 'home' || sideKey === 'h')
                                                                        ? item.home_team
                                                                        : (sideKey === 'away' || sideKey === 'a')
                                                                            ? item.away_team
                                                                            : sideStr;

                                                                    const line = mainRec.line;
                                                                    if (side && line !== null && line !== undefined && String(line).trim() !== '') {
                                                                        const num = Number(line);
                                                                        if (!Number.isNaN(num)) {
                                                                            const signed = num > 0 ? `+${num}` : `${num}`;
                                                                            return `${side} ${signed}`;
                                                                        }
                                                                    }
                                                                    return `${side || ''} ${line || ''}`.trim();
                                                                })()}
                                                            </td>
                                                            <td className="py-2 px-4 text-slate-400 text-xs">
                                                                <div className="flex flex-col">
                                                                    <span>Mkt: <span className="text-slate-300 font-mono">{(() => {
                                                                        const v = mainRec.market_line;
                                                                        if (v === null || v === undefined || v === '') return '-';
                                                                        const num = Number(v);
                                                                        if (Number.isNaN(num)) return String(v);
                                                                        return num > 0 ? `+${num}` : `${num}`;
                                                                    })()}</span></span>
                                                                    <span>Fair: <span className="text-slate-500 font-mono">{(() => {
                                                                        const v = (mainRec.fair_line || item.bet_line);
                                                                        if (v === null || v === undefined || v === '') return '-';
                                                                        const num = Number(v);
                                                                        if (Number.isNaN(num)) return String(v);
                                                                        return num > 0 ? `+${num}` : `${num}`;
                                                                    })()}</span></span>
                                                                </div>
                                                            </td>
                                                            <td className={`py-2 px-4 font-bold ${getEdgeColor(item.edge ?? mainRec.edge ?? item.ev_per_unit, item.league)}`}>
                                                                {(() => {
                                                                    const v = item.edge ?? mainRec.edge;
                                                                    const ev = Number(item.ev_per_unit ?? mainRec.ev_per_unit ?? item.ev ?? (v && !String(v).includes('%') ? v : null));
                                                                    if (Number.isFinite(ev)) {
                                                                        const val = ev > 1 ? ev / 100 : ev; // Handle internal 0.1 vs 10 diffs if any
                                                                        // Most likely ev_per_unit is 0.05 for 5%.
                                                                        const pct = val * 100;
                                                                        return `${pct >= 0 ? '+' : ''}${pct.toFixed(1)}%`;
                                                                    }
                                                                    if (v && String(v).includes('%')) return v;
                                                                    return '—';
                                                                })()}
                                                            </td>
                                                            <td className="py-2 px-4 text-right sm:text-left">
                                                                <span className={`px-2 py-1 rounded text-[10px] font-black uppercase tracking-widest
                                                        ${resultStatus === 'WON' || resultStatus === 'Win' ? 'bg-green-500/20 text-green-400 border border-green-500/20' :
                                                                        resultStatus === 'LOST' || resultStatus === 'Loss' ? 'bg-red-500/20 text-red-400 border border-red-500/20' :
                                                                            resultStatus === 'PUSH' || resultStatus === 'Push' ? 'bg-yellow-500/20 text-yellow-400 border border-yellow-500/20' :
                                                                                'bg-slate-700/50 text-slate-400 border border-slate-600'}`}>
                                                                    {resultStatus === 'PENDING' ? 'Analyzed' : resultStatus}
                                                                </span>
                                                            </td>
                                                            <td className="py-2 px-4 text-slate-300 font-mono text-xs">
                                                                {(() => {
                                                                    const hs = item.final_score_home ?? item.home_score ?? item.score_home ?? item.home_points;
                                                                    const as = item.final_score_away ?? item.away_score ?? item.score_away ?? item.away_points;

                                                                    // If backend ever sends a single string like "72-68".
                                                                    const fs = item.final_score || item.score_final;
                                                                    if ((hs === null || hs === undefined) && (as === null || as === undefined) && fs) {
                                                                        return <span className="text-white font-bold">{String(fs)}</span>;
                                                                    }

                                                                    const hsn = Number(hs);
                                                                    const asn = Number(as);
                                                                    if (Number.isFinite(hsn) && Number.isFinite(asn)) {
                                                                        return (
                                                                            <div className="flex flex-col">
                                                                                <span className="text-white font-bold">{hsn}-{asn}</span>
                                                                                <span className="text-[10px] text-slate-500">T: {hsn + asn}</span>
                                                                            </div>
                                                                        );
                                                                    }

                                                                    return '-';
                                                                })()}
                                                            </td>
                                                        </tr>
                                                    );
                                                });
                                            })()}
                                        </tbody>
                                    </table>
                                </div>
                            </>
                        )}

                        <div className="mt-8 grid grid-cols-1 md:grid-cols-3 gap-6">
                            <div className="bg-slate-800 p-4 rounded-lg border border-slate-700">
                                <h3 className="font-bold text-blue-400 mb-2">NFL Model</h3>
                                <p className="text-sm text-slate-400">Monte Carlo simulation (Gaussian) using EPA/Play volatility. Simulates game flow to find edges &gt;1.5pts.</p>
                            </div>
                            <div className="bg-slate-800 p-4 rounded-lg border border-slate-700">
                                <h3 className="font-bold text-orange-400 mb-2">NCAAM Model</h3>
                                <p className="text-sm text-slate-400">Efficiency-based Monte Carlo (10k runs). Uses Tempo & Efficiency metrics to project Totals &gt;4pt edge.</p>
                            </div>
                            <div className="bg-slate-800 p-4 rounded-lg border border-slate-700">
                                <h3 className="font-bold text-purple-400 mb-2">EPL Model</h3>
                                <p className="text-sm text-slate-400">Poisson Distribution using scraped xG (Expected Goals) data. Finds Moneyline bets with &gt;5% Expected Value.</p>
                            </div>
                        </div>
                    </div>
                )
            }

            {/* Analysis Modal */}
            {
                selectedGame && (
                    <div className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4">
                        <div className="bg-slate-900 border border-slate-700 w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-2xl shadow-2xl relative animate-in fade-in zoom-in duration-200">
                            {/* Header */}
                            <div className="sticky top-0 bg-slate-900/95 backdrop-blur border-b border-slate-700 px-6 py-4 flex justify-between items-center z-10">
                                <div>
                                    <h2 className="text-xl font-bold bg-gradient-to-r from-blue-400 to-green-400 bg-clip-text text-transparent">
                                        {selectedGame.game}
                                    </h2>
                                    <div className="text-xs text-slate-400 mt-1 flex gap-2">
                                        <span>{new Date(selectedGame.start_time).toLocaleString('en-US', { timeZone: 'America/New_York' })} ET</span>
                                        <span>•</span>
                                        <span className="uppercase font-bold">{selectedGame.sport} Analysis</span>
                                    </div>
                                </div>
                                <button
                                    onClick={closeAnalysisModal}
                                    className="p-2 hover:bg-slate-800 rounded-lg transition-colors text-slate-400 hover:text-white"
                                >
                                    ✕
                                </button>
                            </div>

                            {/* Content */}
                            <div className="p-6">
                                {/* Manual referee assignment (optional). Model uses aggregate ref tendencies if not set. */}
                                {selectedGame?.sport === 'NCAAM' && (
                                    <div className="mb-4 p-3 rounded-xl border border-slate-700/60 bg-slate-950/20">
                                        <div className="flex items-center justify-between gap-3">
                                            <div>
                                                <div className="text-[10px] uppercase tracking-widest text-slate-500 font-black">Refs (manual override)</div>
                                                <div className="text-xs text-slate-400 mt-1">If you know the crew, paste names here and re-run. Otherwise the model uses KenPom ref tendencies in aggregate.</div>
                                            </div>
                                            <button
                                                disabled={refsSaving || !selectedGame?.id}
                                                onClick={async () => {
                                                    try {
                                                        setRefsSaving(true);
                                                        setRefsError(null);
                                                        await api.post('/api/ncaam/referees', {
                                                            event_id: selectedGame.id,
                                                            referee_1: ref1 || null,
                                                            referee_2: ref2 || null,
                                                            referee_3: ref3 || null,
                                                        });
                                                        // re-run analysis in-place
                                                        const analysisRes = await api.post('/api/ncaam/analyze', { event_id: selectedGame.id });
                                                        setAnalysisResult(analysisRes.data);
                                                    } catch (e) {
                                                        setRefsError(e?.response?.data?.detail || e?.message || 'Failed to save refs');
                                                    } finally {
                                                        setRefsSaving(false);
                                                    }
                                                }}
                                                className="px-3 py-1.5 rounded-lg text-xs font-bold bg-slate-800/60 hover:bg-slate-700/60 text-slate-200 border border-white/10"
                                            >
                                                {refsSaving ? 'Saving…' : 'Save & Re-run'}
                                            </button>
                                        </div>

                                        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 mt-3">
                                            <input value={ref1} onChange={(e) => setRef1(e.target.value)} placeholder="Referee 1" className="bg-slate-900/40 border border-slate-700/50 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder:text-slate-500 focus:outline-none" />
                                            <input value={ref2} onChange={(e) => setRef2(e.target.value)} placeholder="Referee 2" className="bg-slate-900/40 border border-slate-700/50 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder:text-slate-500 focus:outline-none" />
                                            <input value={ref3} onChange={(e) => setRef3(e.target.value)} placeholder="Referee 3" className="bg-slate-900/40 border border-slate-700/50 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder:text-slate-500 focus:outline-none" />
                                        </div>

                                        {refsError && (
                                            <div className="text-xs text-red-300 mt-2">{refsError}</div>
                                        )}
                                    </div>
                                )}

                                {isAnalyzing && !analysisResult ? (
                                    <div className="py-20 flex flex-col items-center justify-center text-slate-400">
                                        <RefreshCw className="animate-spin w-12 h-12 text-blue-500 mb-4" />
                                        <p className="font-medium">Crunching numbers...</p>
                                        <p className="text-sm opacity-60 mt-2">Checking efficiency metrics & generating narrative</p>
                                    </div>
                                ) : analysisResult?.error ? (
                                    <div className="p-4 bg-red-900/20 border border-red-500/50 rounded-lg text-red-200">
                                        <div className="font-bold flex items-center gap-2 mb-1">
                                            <ShieldAlert size={16} /> Analysis Failed
                                        </div>
                                        {analysisResult.error}
                                    </div>
                                ) : analysisResult ? (
                                    <div className="space-y-6">
                                        {/* Final Score Banner (for completed games) */}
                                        {selectedGame?.final && (
                                            <div className="bg-slate-800/80 p-4 rounded-xl border border-green-500/30">
                                                <div className="flex justify-between items-center">
                                                    <div>
                                                        <div className="text-[10px] text-green-400 uppercase font-black tracking-widest mb-1">Game Complete</div>
                                                        <div className="text-xl font-bold text-white">
                                                            {selectedGame.away_team} <span className="font-mono">{selectedGame.away_score}</span> @ {selectedGame.home_team} <span className="font-mono">{selectedGame.home_score}</span>
                                                        </div>
                                                        <div className="text-xs text-slate-400 mt-1">
                                                            Final Margin: <span className="font-mono font-bold text-white">{Number(selectedGame.home_score) - Number(selectedGame.away_score) > 0 ? '+' : ''}{Number(selectedGame.home_score) - Number(selectedGame.away_score)}</span> (Home perspective)
                                                        </div>
                                                    </div>
                                                    {(() => {
                                                        // Determine outcome: WON/LOST/PUSH/NO BET
                                                        const rec = analysisResult.recommendations?.[0];

                                                        if (!rec) {
                                                            return (
                                                                <div className="text-right">
                                                                    <div className="text-[10px] text-slate-500 uppercase font-bold mb-1">Model Pick</div>
                                                                    <div className="px-3 py-1 rounded-lg text-sm font-black inline-block bg-slate-700/50 text-slate-400 border border-slate-600/30">
                                                                        NO BET
                                                                    </div>
                                                                </div>
                                                            );
                                                        }

                                                        const homeMargin = Number(selectedGame.home_score) - Number(selectedGame.away_score);
                                                        const selection = String(rec.selection || '');
                                                        const lineMatch = selection.match(/[-+]?\d+(\.\d+)?$/);
                                                        const line = lineMatch ? Number(lineMatch[0]) : 0;
                                                        const isHome = selection.includes(selectedGame.home_team);

                                                        // Build display string for the bet
                                                        let betDisplay = '';
                                                        if (rec.bet_type === 'SPREAD') {
                                                            const teamName = isHome ? selectedGame.home_team : selectedGame.away_team;
                                                            const rawLine = rec.line;
                                                            if (rawLine != null && !isNaN(Number(rawLine))) {
                                                                const spreadLine = isHome ? Number(rawLine) : -Number(rawLine);
                                                                betDisplay = `${teamName} ${spreadLine > 0 ? '+' : ''}${spreadLine.toFixed(1)}`;
                                                            } else {
                                                                betDisplay = `${teamName} (Spread)`;
                                                            }
                                                        } else if (rec.bet_type === 'MONEYLINE') {
                                                            const teamName = isHome ? selectedGame.home_team : selectedGame.away_team;
                                                            betDisplay = `${teamName} ML`;
                                                        } else if (rec.bet_type === 'TOTAL') {
                                                            const isOver = selection.toLowerCase().includes('over');
                                                            const totalLine = rec.line != null && !isNaN(Number(rec.line)) ? Number(rec.line).toFixed(1) : 'N/A';
                                                            betDisplay = `${isOver ? 'Over' : 'Under'} ${totalLine}`;
                                                        } else {
                                                            betDisplay = selection || rec.bet_type || 'Unknown';
                                                        }

                                                        // Add Correlations Card
                                                        // (Removed floating/malformed logic)

                                                        let result = 'PENDING';
                                                        if (rec.bet_type === 'SPREAD') {
                                                            const effectiveMargin = isHome ? homeMargin : -homeMargin;
                                                            const spread = isHome ? line : -line;
                                                            if (effectiveMargin + spread > 0) result = 'WON';
                                                            else if (effectiveMargin + spread < 0) result = 'LOST';
                                                            else result = 'PUSH';
                                                        } else if (rec.bet_type === 'MONEYLINE') {
                                                            if (isHome) {
                                                                result = homeMargin > 0 ? 'WON' : homeMargin < 0 ? 'LOST' : 'PUSH';
                                                            } else {
                                                                result = homeMargin < 0 ? 'WON' : homeMargin > 0 ? 'LOST' : 'PUSH';
                                                            }
                                                        } else if (rec.bet_type === 'TOTAL') {
                                                            const totalScore = Number(selectedGame.home_score) + Number(selectedGame.away_score);
                                                            const totalLine = Number(rec.line || 0);
                                                            const isOver = selection.toLowerCase().includes('over');
                                                            if (isOver) {
                                                                result = totalScore > totalLine ? 'WON' : totalScore < totalLine ? 'LOST' : 'PUSH';
                                                            } else {
                                                                result = totalScore < totalLine ? 'WON' : totalScore > totalLine ? 'LOST' : 'PUSH';
                                                            }
                                                        }

                                                        return (
                                                            <div className="text-right">
                                                                <div className="text-[10px] text-slate-500 uppercase font-bold mb-1">Model Pick</div>
                                                                <div className="text-sm font-bold text-white mb-1">{betDisplay}</div>
                                                                <div className={`px-3 py-1 rounded-lg text-sm font-black inline-block ${result === 'WON' ? 'bg-green-500/20 text-green-400 border border-green-500/30' :
                                                                    result === 'LOST' ? 'bg-red-500/20 text-red-400 border border-red-500/30' :
                                                                        result === 'PUSH' ? 'bg-yellow-500/20 text-yellow-400 border border-yellow-500/30' :
                                                                            'bg-slate-700 text-slate-400'
                                                                    }`}>
                                                                    {result}
                                                                </div>
                                                            </div>
                                                        );
                                                    })()}
                                                </div>
                                            </div>
                                        )}

                                        {/* Recommended Bet (make it painfully obvious) */}
                                        {(() => {
                                            const top = (analysisResult.recommendations || [])[0] || null;
                                            if (!top) return null;

                                            const priceStr = top.price !== null && top.price !== undefined ? fmtSigned(top.price, 0) : '—';
                                            const wp = (top.win_prob !== null && top.win_prob !== undefined) ? `${Math.round(Number(top.win_prob) * 100)}%` : '—';
                                            const kelly = (top.kelly !== null && top.kelly !== undefined) ? `${Math.max(0, Math.round(Number(top.kelly) * 100))}%` : '—';

                                            return (
                                                <div className="bg-gradient-to-br from-indigo-900/30 to-slate-900/70 p-4 rounded-xl border border-indigo-500/30">
                                                    <div className="flex items-start gap-3">
                                                        <div className="px-2 py-1 rounded bg-indigo-500/20 text-indigo-300 text-[10px] font-black uppercase tracking-widest">Recommended Bet</div>
                                                        <div className="ml-auto flex gap-2">
                                                            <button
                                                                onClick={() => onAddBet?.({
                                                                    sport: selectedGame.sport,
                                                                    game: `${selectedGame.away_team} @ ${selectedGame.home_team}`,
                                                                    market: top.bet_type,
                                                                    pick: top.selection,
                                                                    line: top.market_line,
                                                                    odds: top.price,
                                                                    book: top.book,
                                                                })}
                                                                className="px-3 py-1.5 rounded-lg text-xs font-bold bg-green-500/20 text-green-300 hover:bg-green-500/30 border border-green-500/30 transition-colors"
                                                            >
                                                                Add to slip
                                                            </button>
                                                            <button
                                                                onClick={() => navigator.clipboard?.writeText(`${top.selection} @ ${priceStr} (${top.book || 'book'})`)}
                                                                className="px-3 py-1.5 rounded-lg text-xs font-bold bg-slate-800/60 text-slate-200 hover:bg-slate-800 border border-slate-700 transition-colors"
                                                            >
                                                                Copy
                                                            </button>
                                                        </div>
                                                    </div>

                                                    <div className="mt-3 text-3xl font-black text-white leading-tight">
                                                        {(() => {
                                                            try {
                                                                if (top.bet_type === 'SPREAD') {
                                                                    const m = String(top.selection || '').match(/^(.*)\s([-+]?\d+(?:\.\d+)?)$/);
                                                                    if (!m) return top.selection;
                                                                    const team = m[1].trim();
                                                                    const line = Number(m[2]);
                                                                    return `${team} ${fmtSigned(line, 1)}`;
                                                                }
                                                            } catch (e) { }
                                                            return top.selection;
                                                        })()}
                                                    </div>

                                                    <div className="mt-2 grid grid-cols-2 md:grid-cols-5 gap-2 text-xs">
                                                        <div className="bg-slate-900/40 p-2 rounded border border-slate-700/50">
                                                            <div className="text-[10px] text-slate-500 uppercase font-black">Book</div>
                                                            <div className="text-slate-200 font-bold truncate">{top.book || '—'}</div>
                                                        </div>
                                                        <div className="bg-slate-900/40 p-2 rounded border border-slate-700/50">
                                                            <div className="text-[10px] text-slate-500 uppercase font-black">Odds</div>
                                                            <div className="text-slate-200 font-mono font-bold">{priceStr}</div>
                                                        </div>
                                                        <div className="bg-slate-900/40 p-2 rounded border border-slate-700/50">
                                                            <div className="text-[10px] text-slate-500 uppercase font-black">EV</div>
                                                            <div className="text-green-300 font-mono font-bold">+{top.edge}</div>
                                                        </div>
                                                        <div className="bg-slate-900/40 p-2 rounded border border-slate-700/50">
                                                            <div className="text-[10px] text-slate-500 uppercase font-black">Win Prob</div>
                                                            <div className="text-slate-200 font-mono font-bold">{wp}</div>
                                                        </div>
                                                        <div className="bg-slate-900/40 p-2 rounded border border-slate-700/50">
                                                            <div className="text-[10px] text-slate-500 uppercase font-black">Stake (Kelly)</div>
                                                            <div className="text-slate-200 font-mono font-bold">{kelly}</div>
                                                        </div>
                                                    </div>

                                                    {(analysisResult.key_factors?.length || analysisResult.game_script?.length) ? (
                                                        <div className="mt-3 text-xs text-slate-300">
                                                            <div className="text-[10px] text-slate-500 uppercase font-black mb-1">Narrative</div>
                                                            <ul className="list-disc list-inside space-y-1">
                                                                {(analysisResult.key_factors || []).slice(0, 3).map((x, i) => <li key={`rkf-${i}`}>{x}</li>)}
                                                                {(analysisResult.game_script || []).slice(0, 2).map((x, i) => <li key={`rgs-${i}`}>{x}</li>)}
                                                            </ul>
                                                            {analysisResult.news_summary ? (
                                                                <div className="mt-2 text-[11px] text-slate-400">News: {analysisResult.news_summary}</div>
                                                            ) : null}
                                                        </div>
                                                    ) : null}
                                                </div>
                                            );
                                        })()}

                                        {/* Quick Read (removed — duplicated by Recommended Bet / Narrative) */}
                                        {false && (() => {
                                            const rec = (analysisResult.recommendations || [])[0] || null;
                                            if (!rec) return null;
                                            const ms = String(analysisResult.narrative?.market_summary || '').trim();
                                            const kf = (analysisResult.key_factors || []).filter(Boolean);
                                            const rk = (analysisResult.risks || []).filter(Boolean);

                                            return (
                                                <div className="bg-slate-800/50 p-4 rounded-xl border border-slate-700/50">
                                                    <div className="text-[10px] text-slate-500 uppercase font-black tracking-widest mb-2">Quick Read</div>
                                                    <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-sm">
                                                        <div className="bg-slate-900/30 p-3 rounded-lg border border-slate-700/50">
                                                            <div className="text-[10px] text-slate-500 uppercase font-black mb-1">The bet</div>
                                                            <div className="text-slate-200 font-black break-words">{rec.selection}</div>
                                                            <div className="mt-1 text-[11px] text-slate-400 break-words">
                                                                {rec.bet_type} • EV {rec.edge ? `+${rec.edge}` : '—'} • {rec.confidence || '—'} confidence
                                                            </div>
                                                        </div>
                                                        <div className="bg-slate-900/30 p-3 rounded-lg border border-slate-700/50">
                                                            <div className="text-[10px] text-slate-500 uppercase font-black mb-1">Why</div>
                                                            {ms ? (
                                                                <div className="text-slate-300 text-xs leading-snug whitespace-pre-wrap break-words">{ms}</div>
                                                            ) : (
                                                                <ul className="list-disc list-inside text-xs text-slate-300 space-y-1 break-words">
                                                                    {kf.slice(0, 3).map((x, i) => <li key={`qk-${i}`} className="break-words">{x}</li>)}
                                                                </ul>
                                                            )}
                                                        </div>
                                                        <div className="bg-slate-900/30 p-3 rounded-lg border border-slate-700/50">
                                                            <div className="text-[10px] text-slate-500 uppercase font-black mb-1">Risks</div>
                                                            {rk.length ? (
                                                                <ul className="list-disc list-inside text-xs text-slate-300 space-y-1 break-words">
                                                                    {rk.slice(0, 3).map((x, i) => <li key={`qr-${i}`} className="break-words">{x}</li>)}
                                                                </ul>
                                                            ) : (
                                                                <div className="text-xs text-slate-500">No major risks flagged.</div>
                                                            )}
                                                        </div>
                                                    </div>
                                                </div>
                                            );
                                        })()}

                                        {/* Market (clean, compact) */}
                                        <div className="bg-slate-900/40 p-5 rounded-2xl border border-slate-700/40">
                                            <div className="text-sm font-semibold text-slate-200 mb-3">Market</div>
                                            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
                                                <div className="bg-slate-900/40 p-3 rounded-lg border border-slate-700/50">
                                                    <div className="text-[10px] text-slate-500 uppercase font-black mb-1">Spread (team / line / odds)</div>
                                                    {(selectedGame.home_spread !== null && selectedGame.home_spread !== undefined) || (selectedGame.away_spread !== null && selectedGame.away_spread !== undefined) ? (() => {
                                                        const hs = selectedGame.home_spread !== null && selectedGame.home_spread !== undefined ? Number(selectedGame.home_spread) : null;
                                                        const as = selectedGame.away_spread !== null && selectedGame.away_spread !== undefined ? Number(selectedGame.away_spread) : (hs !== null ? -hs : null);
                                                        const favored = hs !== null ? (hs < 0 ? selectedGame.home_team : (hs > 0 ? selectedGame.away_team : 'Pick')) : '—';
                                                        return (
                                                            <div className="space-y-1 text-xs">
                                                                <div className="flex justify-between gap-2">
                                                                    <span className="text-slate-400 break-words">{selectedGame.away_team}</span>
                                                                    <span className="text-slate-200 font-mono font-bold">{fmtSigned(as, 1)}</span>
                                                                    <span className="text-slate-500 font-mono">{fmtSigned(selectedGame.spread_away_odds)}</span>
                                                                </div>
                                                                <div className="flex justify-between gap-2">
                                                                    <span className="text-slate-400 break-words">{selectedGame.home_team}</span>
                                                                    <span className="text-slate-200 font-mono font-bold">{fmtSigned(hs, 1)}</span>
                                                                    <span className="text-slate-500 font-mono">{fmtSigned(selectedGame.spread_home_odds ?? selectedGame.moneyline_home)}</span>
                                                                </div>
                                                                <div className="text-[10px] text-slate-600">Favored: <span className="text-slate-300 font-bold">{favored}</span></div>
                                                            </div>
                                                        );
                                                    })() : <div className="text-slate-500">No spread found</div>}
                                                </div>
                                                <div className="bg-slate-900/40 p-3 rounded-lg border border-slate-700/50">
                                                    <div className="text-[10px] text-slate-500 uppercase font-black mb-1">Total (side / line / odds)</div>
                                                    {selectedGame.total_line !== null && selectedGame.total_line !== undefined ? (
                                                        <div className="space-y-1 text-xs">
                                                            <div className="flex justify-between gap-2">
                                                                <span className="text-slate-400">OVER</span>
                                                                <span className="text-slate-200 font-mono font-bold">{Number(selectedGame.total_line).toFixed(1)}</span>
                                                                <span className="text-slate-500 font-mono">{fmtSigned(selectedGame.total_over_odds ?? selectedGame.moneyline_away)}</span>
                                                            </div>
                                                            <div className="flex justify-between gap-2">
                                                                <span className="text-slate-400">UNDER</span>
                                                                <span className="text-slate-200 font-mono font-bold">{Number(selectedGame.total_line).toFixed(1)}</span>
                                                                <span className="text-slate-500 font-mono">{fmtSigned(selectedGame.total_under_odds)}</span>
                                                            </div>
                                                        </div>
                                                    ) : <div className="text-slate-500">No total found</div>}
                                                    <div className="text-[10px] text-slate-500 mt-1">Market total (O/U)</div>
                                                </div>
                                                {/* Model Summary removed (shown in Quick Read / Why the model likes it) */}
                                            </div>
                                        </div>

                                        {/* Recommendations (avoid repetition: only show "Other leans" if multiple) */}
                                        {(() => {
                                            const recs = analysisResult.recommendations || [];
                                            if (!recs.length) {
                                                return <div className="text-center py-4 text-slate-500">No recommendations generated.</div>;
                                            }
                                            if (recs.length <= 1) return null;

                                            return (
                                                <div className="bg-slate-800/50 p-4 rounded-xl border border-slate-700">
                                                    <div className="text-[10px] text-slate-500 uppercase font-black tracking-widest mb-2">Other leans</div>
                                                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                                                        {recs.slice(1, 5).map((rec, idx) => (
                                                            <div key={idx} className="bg-slate-900/30 p-3 rounded-lg border border-slate-700/50">
                                                                <div className="flex items-center justify-between">
                                                                    <div className="text-white font-bold text-sm">{rec.selection}</div>
                                                                    <div className="text-xs text-green-300 font-mono font-bold">+{rec.edge}</div>
                                                                </div>
                                                                <div className="mt-1 text-[11px] text-slate-400">
                                                                    {rec.bet_type} • win {rec.win_prob !== null && rec.win_prob !== undefined ? `${Math.round(rec.win_prob * 100)}%` : '—'}
                                                                    {rec.price !== null && rec.price !== undefined ? ` • ${fmtSigned(rec.price, 0)}` : ''}
                                                                </div>
                                                            </div>
                                                        ))}
                                                    </div>
                                                </div>
                                            );
                                        })()}

                                        {/* Narrative & Torvik View */}
                                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                            <div className="bg-gradient-to-br from-slate-800 to-slate-900 p-6 rounded-xl border border-slate-700/50 relative overflow-hidden">
                                                <h3 className="font-bold text-slate-200 mb-3 flex items-center gap-2 text-sm uppercase tracking-wider">
                                                    <Info size={16} className="text-blue-400" />
                                                    Why the model likes it
                                                </h3>

                                                {(() => {
                                                    const rec = (analysisResult.recommendations || [])[0] || null;
                                                    if (!rec) return <div className="text-slate-500 text-sm">No recommendation summary available.</div>;

                                                    const marketSummary = analysisResult.narrative?.market_summary || '';
                                                    const kf = analysisResult.key_factors || [];
                                                    const gs = analysisResult.game_script || [];

                                                    return (
                                                        <div className="text-slate-300 text-sm leading-relaxed space-y-3">
                                                            {marketSummary ? (
                                                                <div className="text-blue-300 font-semibold">{marketSummary}</div>
                                                            ) : null}

                                                            <div className="bg-slate-900/30 p-3 rounded-lg border border-slate-700/50">
                                                                <div className="text-[10px] text-slate-500 uppercase font-black mb-2">Reasoning (matchup-specific)</div>

                                                                <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-xs">
                                                                    <div className="flex justify-between">
                                                                        <span className="text-slate-500">Market line</span>
                                                                        <span className="text-slate-200 font-mono font-bold">{rec.market_line ?? '—'}</span>
                                                                    </div>
                                                                    <div className="flex justify-between">
                                                                        <span className="text-slate-500">Model fair</span>
                                                                        <span className="text-slate-200 font-mono font-bold">{rec.fair_line ?? '—'}</span>
                                                                    </div>
                                                                    <div className="flex justify-between">
                                                                        <span className="text-slate-500">Line value</span>
                                                                        <span className={`${(rec.edge_points ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'} font-mono font-bold`}>{rec.edge_points !== null && rec.edge_points !== undefined ? `${rec.edge_points >= 0 ? '+' : ''}${rec.edge_points} pts` : '—'}</span>
                                                                    </div>
                                                                    <div className="flex justify-between">
                                                                        <span className="text-slate-500">Win prob</span>
                                                                        <span className="text-slate-200 font-mono font-bold">{rec.win_prob !== null && rec.win_prob !== undefined ? `${Math.round(rec.win_prob * 100)}%` : '—'}</span>
                                                                    </div>
                                                                    <div className="flex justify-between">
                                                                        <span className="text-slate-500">EV</span>
                                                                        <span className="text-green-400 font-mono font-bold">+{rec.edge ?? '—'}</span>
                                                                    </div>
                                                                    <div className="flex justify-between">
                                                                        <span className="text-slate-500">Confidence</span>
                                                                        <span className="text-slate-200 font-bold">{rec.confidence ?? '—'}</span>
                                                                    </div>
                                                                </div>

                                                                {(kf.length || gs.length) ? (
                                                                    <ul className="mt-3 list-disc list-inside space-y-1 opacity-90 text-xs">
                                                                        {kf.slice(0, 3).map((x, i) => <li key={`kf-${i}`}>{x}</li>)}
                                                                        {gs.slice(0, 2).map((x, i) => <li key={`gs-${i}`}>{x}</li>)}
                                                                    </ul>
                                                                ) : (
                                                                    <div className="mt-3 text-slate-500 text-xs">No matchup-specific factors available yet.</div>
                                                                )}

                                                                {analysisResult.risks?.length ? (
                                                                    <div className="mt-3 text-[10px] text-slate-500">Risks: {analysisResult.risks.slice(0, 2).join(' • ')}</div>
                                                                ) : null}
                                                            </div>
                                                        </div>
                                                    );
                                                })()}
                                            </div>

                                            <div className="bg-slate-900/40 p-6 rounded-2xl border border-slate-700/40">
                                                <h3 className="font-semibold text-slate-200 mb-4 flex items-center gap-2 text-sm group relative">
                                                    <ShieldCheck size={16} className="text-green-400" />
                                                    Torvik View
                                                    <span className="ml-auto text-[9px] text-slate-500 font-normal normal-case cursor-help" title={`Data from BartTorvik.com\n\nScraped Fields:\n• Adj Offensive Efficiency\n• Adj Defensive Efficiency\n• Adj Tempo\n• Luck Factor\n\nLast Refresh: ${analysisResult.torvik_view?.data_date || analysisResult.debug_info?.torvik_refresh || 'Live fetch'}`}>
                                                        ⓘ Data Source
                                                    </span>
                                                </h3>
                                                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                                    {/* Model Inputs (Torvik team metrics used in narrative) */}
                                                    <div className="col-span-2 bg-slate-900/30 p-3 rounded-lg border border-slate-700/50">
                                                        <div className="text-[11px] text-slate-400 font-semibold mb-2">Team inputs</div>
                                                        {(() => {
                                                            const ts = analysisResult.torvik_team_stats || {};
                                                            const h = ts.home || {};
                                                            const a = ts.away || {};
                                                            const tempo = ts.game_tempo;

                                                            const fmt = (v, d = 1) => {
                                                                const n = Number(v);
                                                                if (!Number.isFinite(n)) return '—';
                                                                return n.toFixed(d);
                                                            };

                                                            const rows = [
                                                                { k: 'AdjO', a: (a.adj_off ?? a.adjO), h: (h.adj_off ?? h.adjO), tip: 'Adjusted Offensive Efficiency (pts / 100 poss)' },
                                                                { k: 'AdjD', a: (a.adj_def ?? a.adjD), h: (h.adj_def ?? h.adjD), tip: 'Adjusted Defensive Efficiency (pts allowed / 100 poss; lower is better)' },
                                                                { k: 'Tempo', a: (a.tempo ?? a.adj_tempo), h: (h.tempo ?? h.adj_tempo), tip: 'Adjusted tempo (possessions / 40)' },
                                                                { k: 'Luck', a: a.luck, h: h.luck, tip: 'Torvik luck factor' },
                                                                { k: 'Continuity', a: a.continuity, h: h.continuity, tip: 'Roster continuity factor' },
                                                            ];

                                                            const awayName = selectedGame?.away_team || analysisResult.away_team || 'Away';
                                                            const homeName = selectedGame?.home_team || analysisResult.home_team || 'Home';

                                                            return (
                                                                <>
                                                                    <div className="grid grid-cols-3 gap-2 text-[11px]">
                                                                        <div className="text-slate-500 font-semibold">Metric</div>
                                                                        <div className="text-slate-300 font-semibold min-w-0 whitespace-normal break-words">{awayName}</div>
                                                                        <div className="text-slate-300 font-semibold min-w-0 whitespace-normal break-words">{homeName}</div>

                                                                        {/* Team context */}
                                                                        <div className="text-slate-500 text-[10px] font-semibold">Context</div>
                                                                        <div className="text-slate-400 text-[10px] font-semibold min-w-0 whitespace-normal break-words">
                                                                            {a?.record ? `Rec ${a.record}` : 'Rec —'}
                                                                            {analysisResult?.net_data?.away?.rank ? ` • NET #${analysisResult.net_data.away.rank}` : ''}
                                                                        </div>
                                                                        <div className="text-slate-400 text-[10px] font-semibold min-w-0 whitespace-normal break-words">
                                                                            {h?.record ? `Rec ${h.record}` : 'Rec —'}
                                                                            {analysisResult?.net_data?.home?.rank ? ` • NET #${analysisResult.net_data.home.rank}` : ''}
                                                                        </div>

                                                                        {rows.map((r) => {
                                                                            const dec = (r.k === 'Luck' || r.k === 'Continuity') ? 2 : 1;
                                                                            return (
                                                                                <React.Fragment key={r.k}>
                                                                                    <div className="text-slate-500" title={r.tip}>{r.k}</div>
                                                                                    <div className="text-slate-200 font-mono font-bold">{fmt(r.a, dec)}</div>
                                                                                    <div className="text-slate-200 font-mono font-bold">{fmt(r.h, dec)}</div>
                                                                                </React.Fragment>
                                                                            );
                                                                        })}
                                                                    </div>

                                                                    <div className="mt-2 text-[11px] text-slate-400">
                                                                        Avg possessions (est.): <span className="text-slate-100 font-mono font-semibold">{tempo !== undefined && tempo !== null ? fmt(tempo, 1) : '—'}</span>
                                                                    </div>

                                                                    {(() => {
                                                                        // Pace context: translate tempo into what it means for totals.
                                                                        const t = Number(tempo);

                                                                        // Prefer the bet line we're recommending (if this is a TOTAL pick), otherwise fall back to market total.
                                                                        const topRec = (analysisResult?.recommendations || [])[0] || null;
                                                                        const recTotal = topRec && String(topRec.bet_type || '').toUpperCase() === 'TOTAL'
                                                                            ? Number(topRec.market_line ?? topRec.line ?? null)
                                                                            : null;

                                                                        const totalLine = Number(
                                                                            (Number.isFinite(recTotal) ? recTotal : null)
                                                                            ?? selectedGame?.total_line
                                                                            ?? selectedGame?.total
                                                                            ?? null
                                                                        );

                                                                        if (!Number.isFinite(t) || !Number.isFinite(totalLine) || t <= 1) return null;

                                                                        // Combined points per possession (both teams) implied by the market total.
                                                                        const pppCombined = totalLine / t;
                                                                        const pppTeam = pppCombined / 2;

                                                                        // Approx scoring-trip rate assuming ~2.05 pts per scoring trip (2s + 3s + FTs blend).
                                                                        const ptsPerScoringTrip = 2.05;
                                                                        const scoringTripRate = Math.min(1, Math.max(0, totalLine / (ptsPerScoringTrip * t)));

                                                                        // Simple qualitative labels vs typical D1 averages (~1.02–1.06 PPP per team).
                                                                        const lbl = (pppTeam >= 1.10) ? { txt: 'high-efficiency game', cls: 'text-emerald-300' }
                                                                            : (pppTeam >= 1.03) ? { txt: 'around average efficiency', cls: 'text-slate-300' }
                                                                                : { txt: 'lower-efficiency game', cls: 'text-amber-300' };

                                                                        const paceLbl = (t >= 71) ? { txt: 'fast', cls: 'text-emerald-300' }
                                                                            : (t >= 67) ? { txt: 'average', cls: 'text-slate-300' }
                                                                                : { txt: 'slow', cls: 'text-amber-300' };

                                                                        return (
                                                                            <div className="mt-2 text-[11px] text-slate-500 space-y-1 leading-snug">
                                                                                <div>
                                                                                    Pace: <span className={`${paceLbl.cls} font-semibold`}>{paceLbl.txt}</span> • Total implies <span className="text-slate-200 font-mono font-semibold">{pppTeam.toFixed(2)}</span> pts/poss/team.
                                                                                </div>
                                                                                <div>
                                                                                    Rough scoring-trip rate: <span className="text-slate-200 font-mono font-semibold">{(scoringTripRate * 100).toFixed(0)}%</span>
                                                                                    <span className="text-slate-600"> (assumes ~{ptsPerScoringTrip.toFixed(2)} pts per scoring trip)</span>.
                                                                                </div>
                                                                                <div>
                                                                                    Read: slow pace means fewer possessions—totals need more efficiency per trip. This looks like <span className={`${lbl.cls} font-semibold`}>{lbl.txt}</span>.
                                                                                </div>
                                                                            </div>
                                                                        );
                                                                    })()}
                                                                </>
                                                            );
                                                        })()}
                                                    </div>
                                                    <div className="bg-slate-900/50 p-3 rounded-lg border border-slate-700 cursor-help" title="Projected final score computed from Torvik efficiency ratings (AdjO, AdjD) and tempo">
                                                        <div className="text-[11px] text-slate-400 font-semibold mb-1">Projected score</div>
                                                        {(() => {
                                                            // torvik_view.projected_score is often "AwayScore-HomeScore"; make it explicit.
                                                            const ps = String(analysisResult.torvik_view?.projected_score || '').trim();
                                                            const parts = ps ? ps.split('-').map(x => x.trim()) : [];
                                                            const awayScore = parts.length === 2 ? parts[0] : (ps || '—');
                                                            const homeScore = parts.length === 2 ? parts[1] : (parts.length === 1 ? '—' : '');
                                                            const awayName = selectedGame?.away_team || analysisResult.away_team || 'Away';
                                                            const homeName = selectedGame?.home_team || analysisResult.home_team || 'Home';
                                                            return (
                                                                <div className="space-y-1">
                                                                    <div className="flex justify-between text-white font-bold gap-2">
                                                                        <span className="min-w-0 whitespace-normal break-words">{awayName}</span>
                                                                        <span className="font-mono">{awayScore}</span>
                                                                    </div>
                                                                    <div className="flex justify-between text-white font-bold gap-2">
                                                                        <span className="min-w-0 whitespace-normal break-words">{homeName}</span>
                                                                        <span className="font-mono">{homeScore}</span>
                                                                    </div>
                                                                </div>
                                                            );
                                                        })()}
                                                    </div>
                                                    <div className="bg-slate-900/50 p-3 rounded-lg border border-slate-700 cursor-help" title="Expected margin based on efficiency differential and home court advantage">
                                                        <div className="text-[11px] text-slate-400 font-semibold mb-1">Projected margin</div>
                                                        <div className="text-lg font-bold text-white">
                                                            {analysisResult.torvik_view?.margin !== undefined && analysisResult.torvik_view.margin !== null
                                                                ? `${Number(analysisResult.torvik_view.margin) > 0 ? '+' : ''}${Number(analysisResult.torvik_view.margin).toFixed(1)}`
                                                                : '—'}
                                                        </div>
                                                    </div>
                                                </div>
                                                <div className="mt-4 text-[10px] text-slate-500 italic">
                                                    {analysisResult.torvik_view?.lean || 'No data available'}
                                                </div>
                                                {/* Data freshness indicator */}
                                                <div className="mt-3 pt-3 border-t border-slate-700/50 text-[9px] text-slate-500 flex items-center gap-2">
                                                    <span className={`inline-block w-2 h-2 rounded-full ${analysisResult.torvik_view ? 'bg-green-500 animate-pulse' : 'bg-red-500'}`}></span>
                                                    {analysisResult.torvik_view ? 'Computed from Raw Efficiency' : 'Data Missing'} • {analysisResult.debug_info?.torvik_refresh || new Date().toLocaleDateString()}
                                                </div>
                                            </div>

                                            {/* KenPom View */}
                                            {analysisResult.kenpom_data && (
                                                <div className="bg-slate-900/40 p-6 rounded-2xl border border-slate-700/40">
                                                    <h3 className="font-semibold text-slate-200 mb-4 flex items-center gap-2 text-sm">
                                                        <Shield size={16} className="text-purple-400" />
                                                        KenPom
                                                    </h3>
                                                    <div className="grid grid-cols-2 gap-4">
                                                        <div className="bg-slate-900/50 p-3 rounded-lg border border-slate-700">
                                                            <div className="text-[10px] text-slate-500 uppercase font-black mb-1">Spread Adj</div>
                                                            <div className="text-lg font-bold text-white">
                                                                {(analysisResult.kenpom_data.spread_adj || 0) > 0 ? '+' : ''}
                                                                {Math.round((analysisResult.kenpom_data.spread_adj || 0) * 10) / 10}
                                                            </div>
                                                        </div>
                                                        <div className="bg-slate-900/50 p-3 rounded-lg border border-slate-700">
                                                            <div className="text-[10px] text-slate-500 uppercase font-black mb-1">Total Adj</div>
                                                            <div className="text-lg font-bold text-white">
                                                                {(analysisResult.kenpom_data.total_adj || 0) > 0 ? '+' : ''}
                                                                {Math.round((analysisResult.kenpom_data.total_adj || 0) * 10) / 10}
                                                            </div>
                                                        </div>
                                                    </div>
                                                    <div className="mt-4 text-[10px] text-slate-500 italic">
                                                        {analysisResult.kenpom_data.summary || 'No Summary'}
                                                    </div>
                                                </div>
                                            )}

                                            {/* News View */}
                                            {analysisResult.news_summary && (
                                                <div className="bg-slate-900/40 p-6 rounded-2xl border border-slate-700/40">
                                                    <h3 className="font-semibold text-slate-200 mb-4 flex items-center gap-2 text-sm">
                                                        <AlertCircle size={16} className="text-amber-400" />
                                                        News
                                                    </h3>
                                                    <div className="text-sm text-slate-300 bg-slate-900/30 p-3 rounded-lg border border-slate-700/50 min-h-[80px]">
                                                        {analysisResult.news_summary}
                                                    </div>
                                                </div>
                                            )}
                                        </div>

                                        {/* Torvik Team Stats + Game Script (removed — duplicated by Torvik View above) */}
                                        {false && (analysisResult.torvik_team_stats || analysisResult.game_script) && (
                                            <div>
                                                <h3 className="text-sm font-bold text-slate-400 uppercase tracking-wider mb-3">Team Efficiency (Torvik) + Game Script</h3>
                                                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                                    <div className="bg-slate-800/60 p-4 rounded-xl border border-slate-700/50">
                                                        <div className="text-[10px] text-slate-500 uppercase font-black mb-2">Efficiency snapshot</div>
                                                        {(() => {
                                                            const ts = analysisResult.torvik_team_stats || {};
                                                            const h = ts.home || {};
                                                            const a = ts.away || {};
                                                            const tempo = ts.game_tempo;
                                                            const paceLbl = labelPace(tempo);
                                                            const hOff = labelOffense(h.adj_off);
                                                            const hDef = labelDefense(h.adj_def);
                                                            const aOff = labelOffense(a.adj_off);
                                                            const aDef = labelDefense(a.adj_def);
                                                            return (
                                                                <div className="space-y-2 text-xs">
                                                                    <div className="flex justify-between items-center">
                                                                        <span className="text-slate-500">Avg possessions / team</span>
                                                                        <span className={`${paceLbl.cls} font-bold`}>{tempo ? `${tempo}` : '—'}</span>
                                                                    </div>
                                                                    <div className="text-[10px] text-slate-500">Pace label: <span className={`${paceLbl.cls} font-bold`}>{paceLbl.label}</span></div>

                                                                    <div className="border-t border-slate-700/50 pt-2">
                                                                        <div className="flex items-center justify-between gap-2 mb-1">
                                                                            <div className="text-slate-300 font-bold">{selectedGame?.home_team}</div>
                                                                            <div className="text-[10px] text-slate-500 flex items-center gap-2">
                                                                                {h.torvik_rank ? <span>Torvik #{h.torvik_rank}</span> : null}
                                                                                {analysisResult?.kenpom_data?.home_rank ? <span>KenPom #{analysisResult.kenpom_data.home_rank}</span> : null}
                                                                                {analysisResult?.net_data?.home?.rank ? <span>NET #{analysisResult.net_data.home.rank}</span> : null}
                                                                                {analysisResult?.net_data?.home?.rank && Number(analysisResult.net_data.home.rank) <= 25 ? <span className="px-1.5 py-0.5 rounded border border-emerald-500/30 bg-emerald-500/10 text-emerald-200">Top 25</span> : null}
                                                                                {analysisResult?.kenpom_data?.home_rank && Number(analysisResult.kenpom_data.home_rank) <= 25 ? <span className="px-1.5 py-0.5 rounded border border-emerald-500/30 bg-emerald-500/10 text-emerald-200">KenPom Top 25</span> : null}
                                                                            </div>
                                                                        </div>
                                                                        {h.record ? <div className="text-[11px] text-slate-400 mb-1">Record: <span className="text-slate-200 font-bold">{h.record}</span></div> : null}
                                                                        {analysisResult?.net_data?.home ? (
                                                                            <div className="text-[11px] text-slate-500 mb-1">
                                                                                Q1 {analysisResult.net_data.home.quad1 || '—'} • Q2 {analysisResult.net_data.home.quad2 || '—'} • Q3 {analysisResult.net_data.home.quad3 || '—'} • Q4 {analysisResult.net_data.home.quad4 || '—'}
                                                                                <span className="text-slate-600"> • </span>
                                                                                H {analysisResult.net_data.home.home || '—'} / A {analysisResult.net_data.home.road || '—'} / N {analysisResult.net_data.home.neutral || '—'}
                                                                            </div>
                                                                        ) : null}
                                                                        <div className="flex justify-between"><span className="text-slate-500">Offense</span><span className={`${hOff.cls} font-bold`}>{hOff.label}</span></div>
                                                                        <div className="flex justify-between"><span className="text-slate-500">Defense</span><span className={`${hDef.cls} font-bold`}>{hDef.label}</span></div>
                                                                        <div className="text-[10px] text-slate-500 mt-1">AdjO {h.adj_off?.toFixed ? h.adj_off.toFixed(1) : (h.adj_off ?? '—')} • AdjD {h.adj_def?.toFixed ? h.adj_def.toFixed(1) : (h.adj_def ?? '—')} • AdjT {h.adj_tempo?.toFixed ? h.adj_tempo.toFixed(1) : (h.adj_tempo ?? '—')}</div>
                                                                    </div>

                                                                    <div className="border-t border-slate-700/50 pt-2">
                                                                        <div className="flex items-center justify-between gap-2 mb-1">
                                                                            <div className="text-slate-300 font-bold">{selectedGame?.away_team}</div>
                                                                            <div className="text-[10px] text-slate-500 flex items-center gap-2">
                                                                                {a.torvik_rank ? <span>Torvik #{a.torvik_rank}</span> : null}
                                                                                {analysisResult?.kenpom_data?.away_rank ? <span>KenPom #{analysisResult.kenpom_data.away_rank}</span> : null}
                                                                                {analysisResult?.net_data?.away?.rank ? <span>NET #{analysisResult.net_data.away.rank}</span> : null}
                                                                                {analysisResult?.net_data?.away?.rank && Number(analysisResult.net_data.away.rank) <= 25 ? <span className="px-1.5 py-0.5 rounded border border-emerald-500/30 bg-emerald-500/10 text-emerald-200">Top 25</span> : null}
                                                                                {analysisResult?.kenpom_data?.away_rank && Number(analysisResult.kenpom_data.away_rank) <= 25 ? <span className="px-1.5 py-0.5 rounded border border-emerald-500/30 bg-emerald-500/10 text-emerald-200">KenPom Top 25</span> : null}
                                                                            </div>
                                                                        </div>
                                                                        {a.record ? <div className="text-[11px] text-slate-400 mb-1">Record: <span className="text-slate-200 font-bold">{a.record}</span></div> : null}
                                                                        {analysisResult?.net_data?.away ? (
                                                                            <div className="text-[11px] text-slate-500 mb-1">
                                                                                Q1 {analysisResult.net_data.away.quad1 || '—'} • Q2 {analysisResult.net_data.away.quad2 || '—'} • Q3 {analysisResult.net_data.away.quad3 || '—'} • Q4 {analysisResult.net_data.away.quad4 || '—'}
                                                                                <span className="text-slate-600"> • </span>
                                                                                H {analysisResult.net_data.away.home || '—'} / A {analysisResult.net_data.away.road || '—'} / N {analysisResult.net_data.away.neutral || '—'}
                                                                            </div>
                                                                        ) : null}
                                                                        <div className="flex justify-between"><span className="text-slate-500">Offense</span><span className={`${aOff.cls} font-bold`}>{aOff.label}</span></div>
                                                                        <div className="flex justify-between"><span className="text-slate-500">Defense</span><span className={`${aDef.cls} font-bold`}>{aDef.label}</span></div>
                                                                        <div className="text-[10px] text-slate-500 mt-1">AdjO {a.adj_off?.toFixed ? a.adj_off.toFixed(1) : (a.adj_off ?? '—')} • AdjD {a.adj_def?.toFixed ? a.adj_def.toFixed(1) : (a.adj_def ?? '—')} • AdjT {a.adj_tempo?.toFixed ? a.adj_tempo.toFixed(1) : (a.adj_tempo ?? '—')}</div>
                                                                    </div>
                                                                </div>
                                                            );
                                                        })()}
                                                    </div>

                                                    <div className="bg-slate-800/60 p-4 rounded-xl border border-slate-700/50">
                                                        <div className="text-[10px] text-slate-500 uppercase font-black mb-2">Game script (model view)</div>
                                                        <div className="space-y-2">
                                                            {(analysisResult.game_script || []).length ? (
                                                                (analysisResult.game_script || []).slice(0, 5).map((x, i) => (
                                                                    <div key={i} className="flex items-start gap-3 text-sm text-slate-300">
                                                                        <div className="w-1.5 h-1.5 rounded-full bg-indigo-400 mt-2"></div>
                                                                        <div>{x}</div>
                                                                    </div>
                                                                ))
                                                            ) : (
                                                                <div className="text-slate-500 text-sm">No game script available yet.</div>
                                                            )}
                                                        </div>
                                                    </div>

                                                    {/* Market Correlations */}
                                                    {correlationResult && (
                                                        <div className="bg-slate-800 p-4 rounded-xl border border-slate-700 mt-4">
                                                            <div className="flex items-center justify-between mb-3">
                                                                <h3 className="font-bold text-white flex items-center gap-2">
                                                                    <RefreshCw size={16} className="text-blue-400" />
                                                                    Market Correlations
                                                                </h3>
                                                                {correlationResult.archetype && (
                                                                    <div className="flex gap-2">
                                                                        <span className="px-2 py-1 rounded bg-slate-700 text-xs font-mono text-slate-300">
                                                                            {correlationResult.archetype.pace}
                                                                        </span>
                                                                        <span className="px-2 py-1 rounded bg-slate-700 text-xs font-mono text-slate-300">
                                                                            {correlationResult.archetype.eff}
                                                                        </span>
                                                                    </div>
                                                                )}
                                                            </div>
                                                            {correlationResult.correlations?.pairs?.over_home_cover ? (
                                                                <div className="bg-slate-900/50 p-3 rounded-lg border border-slate-700/50 flex justify-between items-center">
                                                                    <div>
                                                                        <div className="text-xs text-slate-500 uppercase font-bold">If OVER Hits → Home Cover %</div>
                                                                        <div className="text-xl font-bold text-white">
                                                                            {(correlationResult.correlations.pairs.over_home_cover.p_b_given_a * 100).toFixed(1)}%
                                                                        </div>
                                                                    </div>
                                                                    <div className="text-right">
                                                                        <div className="text-xs text-slate-500">Lift</div>
                                                                        <div className={`text-lg font-bold ${correlationResult.correlations.pairs.over_home_cover.lift >= 1.2 ? 'text-green-400' : 'text-slate-200'}`}>
                                                                            {correlationResult.correlations.pairs.over_home_cover.lift}x
                                                                        </div>
                                                                    </div>
                                                                </div>
                                                            ) : (
                                                                <div className="text-sm text-slate-500">Insufficient data for archetype.</div>
                                                            )}
                                                        </div>
                                                    )}
                                                </div>
                                            </div>
                                        )}

                                        {/* Key Factors (removed — shown in Recommended Bet narrative above) */}
                                        {false && analysisResult.key_factors && (
                                            <div>
                                                <h3 className="text-sm font-bold text-slate-400 uppercase tracking-wider mb-3">Key Factors</h3>
                                                <div className="space-y-2">
                                                    {analysisResult.key_factors?.map((factor, i) => (
                                                        <div key={i} className="flex items-center gap-3 text-sm text-slate-300">
                                                            <div className="w-1.5 h-1.5 rounded-full bg-blue-500"></div>
                                                            {factor}
                                                        </div>
                                                    ))}
                                                </div>
                                            </div>
                                        )}

                                        {/* Risks (removed — shown in Recommended Bet narrative above) */}
                                        {false && analysisResult.risks && (
                                            <div>
                                                <h3 className="text-sm font-bold text-slate-400 uppercase tracking-wider mb-3">Risk Factors</h3>
                                                <div className="space-y-2">
                                                    {analysisResult.risks?.map((risk, i) => (
                                                        <div key={i} className="flex items-center gap-3 text-sm text-slate-300">
                                                            <div className="w-1.5 h-1.5 rounded-full bg-red-500"></div>
                                                            {risk}
                                                        </div>
                                                    ))}
                                                </div>
                                            </div>
                                        )}
                                    </div>
                                ) : null}
                            </div>
                        </div>
                    </div>
                )
            }

        </div >
    );
};

export default Research;
