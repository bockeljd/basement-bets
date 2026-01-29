import React, { useState, useEffect } from 'react';
import api from '../api/axios';
import { ArrowUpDown, ChevronUp, ChevronDown, Filter, RefreshCw, CheckCircle, AlertCircle, Info, Shield, ShieldAlert, ShieldCheck, PlusCircle } from 'lucide-react';
import ModelPerformanceAnalytics from '../components/ModelPerformanceAnalytics';

const Research = ({ onAddBet }) => {
    const [edges, setEdges] = useState([]);
    const [history, setHistory] = useState([]);
    const [activeTab, setActiveTab] = useState('live');
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    // Research tab focuses on board-backed leagues
    const [leagueFilter, setLeagueFilter] = useState('NCAAM');
    // Date Filtering
    // Always drive date selection in America/New_York so it matches backend queries.
    const getTodayStr = () => new Date().toLocaleDateString('en-CA', { timeZone: 'America/New_York' });
    const [selectedDate, setSelectedDate] = useState(getTodayStr());

    // Game Analysis Modal State
    const [selectedGame, setSelectedGame] = useState(null);
    const [analysisResult, setAnalysisResult] = useState(null);
    const [isAnalyzing, setIsAnalyzing] = useState(false);

    // Sorting State
    const [sortConfig, setSortConfig] = useState({ key: 'edge', direction: 'desc' });

    const BOARD_DAYS_DEFAULT = 3;

    useEffect(() => {
        fetchSchedule();
    }, [selectedDate, leagueFilter]); // Refetch when date/league changes

    const fetchSchedule = async () => {
        try {
            setLoading(true);
            setError(null);

            // Fetch NCAAM board (next N days from selected date) and overall history
            const [boardRes, historyRes] = await Promise.all([
                api.get('/api/board', { params: { league: leagueFilter, date: selectedDate, days: BOARD_DAYS_DEFAULT } }),
                api.get('/api/ncaam/history')
            ]);

            setEdges(boardRes.data || []);
            setHistory(historyRes.data || []);

        } catch (err) {
            console.error(err);
            if (err.response?.status === 403) {
                const pass = prompt("Authentication failed. Please enter the Basement Password:");
                if (pass) {
                    localStorage.setItem('basement_password', pass);
                    window.location.reload();
                }
            }
            setError('Failed to load schedule.');
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
            const [boardRes, historyRes] = await Promise.all([
                api.get('/api/ncaam/board', { params: { date: selectedDate } }),
                api.get('/api/ncaam/history')
            ]);
            setEdges(boardRes.data || []);
            setHistory(historyRes.data || []);
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

        try {
            const response = await api.post('/api/ncaam/analyze', {
                event_id: game.id
            });
            setAnalysisResult(response.data);
            // Refresh history in background
            const histRes = await api.get('/api/ncaam/history');
            setHistory(histRes.data || []);
        } catch (err) {
            console.error('Analysis error:', err);
            setAnalysisResult({ error: err.response?.data?.detail || 'Analysis failed' });
        } finally {
            setIsAnalyzing(false);
        }
    };

    const closeAnalysisModal = () => {
        setSelectedGame(null);
        setAnalysisResult(null);
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
        const current = new Date(selectedDate);
        current.setDate(current.getDate() + days);
        // Correct timezone offset issue if any, or just use simple string manipulation if date is reliable
        // To be safe with 'en-CA' (YYYY-MM-DD)
        const nextDate = current.toLocaleDateString('en-CA', { timeZone: 'America/New_York' });
        setSelectedDate(nextDate);
    };

    const fmtSigned = (n, decimals = 0) => {
        if (n === null || n === undefined || n === '') return '-';
        const x = Number(n);
        if (Number.isNaN(x)) return String(n);
        const s = decimals > 0 ? x.toFixed(decimals) : String(x);
        return x > 0 ? `+${s}` : s;
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


    const SortIcon = ({ column }) => {
        if (sortConfig.key !== column) return <ArrowUpDown size={12} className="ml-1 opacity-20" />;
        return sortConfig.direction === 'asc' ? <ChevronUp size={12} className="ml-1 text-blue-400" /> : <ChevronDown size={12} className="ml-1 text-blue-400" />;
    };

    return (
        <div className="p-6 bg-slate-900 min-h-screen text-white">
            <div className="flex justify-between items-center mb-6">
                <div>
                    <h1 className="text-3xl font-bold bg-gradient-to-r from-blue-400 to-green-400 bg-clip-text text-transparent">
                        Bet Research
                    </h1>
                    <div className="text-xs text-slate-500 mt-1">
                        Showing NCAAM board for next <span className="text-slate-300 font-bold">3</span> days from selected date.
                    </div>
                </div>
                <div className="flex gap-2">
                    <button
                        onClick={fetchSchedule}
                        disabled={loading}
                        className="px-4 py-2 bg-slate-700 hover:bg-slate-600 rounded-lg text-sm transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                    >
                        <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
                        Refresh Board
                    </button>

                    <button
                        onClick={() => onAddBet?.()}
                        className="px-4 py-2 bg-green-600 hover:bg-green-500 rounded-lg text-sm transition-all flex items-center gap-2"
                        title="Add a bet manually"
                    >
                        <PlusCircle size={14} />
                        Add Bet
                    </button>

                    <button
                        onClick={runModels}
                        disabled={loading}
                        className="px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded-lg text-sm transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                        title="(Legacy) Global model run. NCAAM board is refreshed via Refresh Board."
                    >
                        {loading ? <RefreshCw size={14} className="animate-spin" /> : null}
                        {loading ? 'Running Models...' : 'Run Models'}
                    </button>
                </div>
            </div>

            {/* Tabs */}
            <div className="flex space-x-4 mb-6 border-b border-slate-700">
                <button
                    onClick={() => setActiveTab('live')}
                    className={`pb-2 px-4 text-sm font-medium transition-colors ${activeTab === 'live' ? 'text-blue-400 border-b-2 border-blue-400' : 'text-slate-400 hover:text-slate-200'}`}
                >
                    Market Board
                </button>
                <button
                    onClick={() => setActiveTab('history')}
                    className={`pb-2 px-4 text-sm font-medium transition-colors ${activeTab === 'history' ? 'text-blue-400 border-b-2 border-blue-400' : 'text-slate-400 hover:text-slate-200'}`}
                >
                    History
                </button>
            </div>


            {activeTab === 'live' && (
                <>
                    <div className="flex justify-between items-center mb-4">
                        <div className="flex items-center space-x-4">
                            {/* League Filter */}
                            <div className="flex items-center bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 focus-within:border-blue-500/50 transition-all">
                                <Filter size={14} className="text-slate-500 mr-2" />
                                <select
                                    value={leagueFilter}
                                    onChange={(e) => setLeagueFilter(e.target.value)}
                                    className="bg-transparent text-sm font-medium focus:outline-none cursor-pointer"
                                >
                                    <option value="NCAAM">NCAAM</option>
                                    <option value="NFL">NFL</option>
                                    <option value="EPL">EPL</option>
                                </select>
                            </div>

                            {/* Date Navigation */}
                            <div className="flex items-center bg-slate-800 border border-slate-700 rounded-lg px-1 py-1">
                                <button onClick={() => shiftDate(-1)} className="p-1 px-2 hover:bg-slate-700 rounded text-slate-400 hover:text-white transition-colors">
                                    ←
                                </button>
                                <input
                                    type="date"
                                    value={selectedDate}
                                    onChange={(e) => setSelectedDate(e.target.value)}
                                    className="bg-transparent text-sm font-bold text-center w-32 focus:outline-none text-white appearance-none"
                                />
                                <button onClick={() => shiftDate(1)} className="p-1 px-2 hover:bg-slate-700 rounded text-slate-400 hover:text-white transition-colors">
                                    →
                                </button>
                                <button onClick={() => setSelectedDate(new Date().toLocaleDateString('en-CA', { timeZone: 'America/New_York' }))} className="ml-2 px-2 py-0.5 text-xs bg-blue-600/20 text-blue-400 hover:bg-blue-600/30 rounded">
                                    Today
                                </button>
                            </div>
                        </div>
                    </div>

                    <div className="bg-slate-800 rounded-xl border border-slate-700 shadow-xl overflow-hidden">
                        <div className="px-6 py-4 border-b border-slate-700 flex justify-between items-center">
                            <h2 className="text-lg font-semibold text-slate-200">Market Board</h2>
                            <div className="text-xs text-slate-500 flex items-center">
                                <Info size={12} className="mr-1" />
                                Times shown in ET • lines shown as (team/side, line, odds)
                            </div>
                        </div>

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


                        {!loading && !error && edges.length === 0 && (
                            <div className="text-center py-20 text-slate-500 flex flex-col items-center">
                                <div className="p-4 bg-slate-700/30 rounded-full mb-4">
                                    <RefreshCw size={24} className="text-slate-600" />
                                </div>
                                <p>No active games found in current slate.</p>
                            </div>
                        )}

                        {!loading && edges.length > 0 && (
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
                                            getProcessedEdges().map((edge, idx) => {
                                                const date = edge.start_time ? new Date(edge.start_time) : null;
                                                const dateStr = date ? date.toLocaleDateString('en-US', { month: 'numeric', day: 'numeric', timeZone: 'America/New_York' }) : '-';
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
                                                            <button
                                                                onClick={() => analyzeGame(edge)}
                                                                disabled={leagueFilter !== 'NCAAM' || (isAnalyzing && selectedGame?.id === edge.id)}
                                                                title={leagueFilter !== 'NCAAM' ? 'Analysis currently supported for NCAAM only' : ''}
                                                                className="px-4 py-1.5 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg text-xs font-bold transition-all shadow-lg ring-1 ring-white/10 flex items-center justify-center mx-auto"
                                                            >
                                                                {leagueFilter !== 'NCAAM' ? 'N/A' : (isAnalyzing && selectedGame?.id === edge.id ? (
                                                                    <RefreshCw className="animate-spin" size={14} />
                                                                ) : 'Analyze')}
                                                            </button>
                                                        </td>
                                                    </tr>
                                                );
                                            })
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
                    <div className="bg-slate-800 rounded-xl border border-slate-700 shadow-xl overflow-hidden">
                        <div className="px-6 py-4 border-b border-slate-700 flex justify-between items-center bg-slate-800/50">
                            <h2 className="text-lg font-semibold text-slate-200">Model History (Auto-Tracked)</h2>
                            <div className="flex items-center gap-6">
                                <button
                                    onClick={gradeResults}
                                    disabled={loading}
                                    className="px-4 py-2 bg-green-600/20 hover:bg-green-600/30 text-green-400 border border-green-500/20 disabled:opacity-50 rounded-lg text-xs font-bold transition-all flex items-center"
                                >
                                    {loading ? <RefreshCw className="animate-spin mr-2" size={12} /> : null}
                                    Grade Results
                                </button>
                            </div>
                        </div>

                        {/* Model Performance Summary */}
                        <div className="px-6 py-6 bg-slate-800/30 border-b border-slate-700 grid grid-cols-2 lg:grid-cols-4 gap-4">
                            {[
                                {
                                    label: 'Graded Bets',
                                    value: history.filter(h => h.result && h.result !== 'Pending').length,
                                    icon: <CheckCircle size={14} className="text-blue-400" />
                                },
                                {
                                    label: 'Record',
                                    value: (() => {
                                        const w = history.filter(x => x.result === 'Win').length;
                                        const l = history.filter(x => x.result === 'Loss').length;
                                        const p = history.filter(x => x.result === 'Push').length;
                                        return `${w}-${l}${p > 0 ? `-${p}` : ''}`;
                                    })(),
                                    icon: <ArrowUpDown size={14} className="text-green-400" />
                                },
                                {
                                    label: 'Win Rate',
                                    value: (() => {
                                        const h = history.filter(x => x.result && x.result !== 'Pending');
                                        const w = h.filter(x => x.result === 'Win').length;
                                        return h.length > 0 ? `${((w / h.length) * 100).toFixed(1)}%` : '0.0%';
                                    })(),
                                    icon: <CheckCircle size={14} className="text-purple-400" />
                                },
                                {
                                    label: 'Est. Return ($10/bet)',
                                    value: `$${history.reduce((acc, h) => {
                                        if (h.result === 'Win') return acc + 9.09;
                                        if (h.result === 'Loss') return acc - 10.0;
                                        return acc;
                                    }, 0).toFixed(2)}`,
                                    icon: <RefreshCw size={14} className="text-emerald-400" />
                                }
                            ].map((stat, i) => (
                                <div key={i} className="bg-slate-900/50 p-4 rounded-xl border border-slate-700/50 shadow-sm relative overflow-hidden group">
                                    <div className="absolute top-0 right-0 p-2 opacity-20 group-hover:opacity-100 transition-opacity">
                                        {stat.icon}
                                    </div>
                                    <div className="text-[10px] font-black text-slate-500 uppercase tracking-widest mb-1">{stat.label}</div>
                                    <div className="text-xl font-bold text-white">{stat.value}</div>
                                </div>
                            ))}
                        </div>

                        {!loading && history.length === 0 && (
                            <div className="text-center py-10 text-slate-500">
                                No history yet. Run models to auto-track.
                            </div>
                        )}

                        {!loading && history.length > 0 && (
                            <>
                                <ModelPerformanceAnalytics history={history} />

                                <div className="overflow-x-auto">
                                    <table className="w-full text-left border-collapse">
                                        <thead>
                                            <tr className="text-slate-400 border-b border-slate-700 bg-slate-800/50">
                                                <th className="py-2 px-4 text-xs font-bold uppercase tracking-wider cursor-pointer hover:text-white transition-colors" onClick={() => handleSort('created_at')}>
                                                    <div className="flex items-center">Date <SortIcon column="created_at" /></div>
                                                </th>
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
                                            {getSortedHistory().map((item, idx) => {
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

                                                const mainRec = recs[0] || {};

                                                // Result Logic
                                                const resultStatus = item.graded_result || item.outcome || 'Pending';

                                                return (
                                                    <tr key={idx} className="border-b border-slate-700/50 hover:bg-slate-700/30 transition-colors">
                                                        <td className="py-2 px-4 text-slate-400 text-xs whitespace-nowrap">
                                                            <div className="font-bold text-slate-300">
                                                                {new Date(item.analyzed_at).toLocaleDateString([], { month: 'numeric', day: 'numeric' })}
                                                            </div>
                                                            <div className="opacity-70">
                                                                {new Date(item.analyzed_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}
                                                            </div>
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
                                                            {mainRec.side} {mainRec.line || ''}
                                                        </td>
                                                        <td className="py-2 px-4 text-slate-400 text-xs">
                                                            <div className="flex flex-col">
                                                                <span>Mkt: <span className="text-slate-300 font-mono">{mainRec.market_line || '-'}</span></span>
                                                                <span>Fair: <span className="text-slate-500 font-mono">{mainRec.fair_line || item.bet_line || '-'}</span></span>
                                                            </div>
                                                        </td>
                                                        <td className={`py-2 px-4 font-bold ${getEdgeColor(item.edge || mainRec.edge, item.league)}`}>
                                                            {item.edge || mainRec.edge}
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
                                                            {item.final_score_home !== null && item.final_score_home !== undefined ? (
                                                                <div className="flex flex-col">
                                                                    <span className="text-white font-bold">{item.final_score_home}-{item.final_score_away}</span>
                                                                    <span className="text-[10px] text-slate-500">T: {item.final_score_home + item.final_score_away}</span>
                                                                </div>
                                                            ) : '-'}
                                                        </td>
                                                    </tr>
                                                );
                                            })}
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
                                        <span>{new Date(selectedGame.start_time).toLocaleString()}</span>
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
                                {isAnalyzing && !analysisResult ? (
                                    <div className="py-20 flex flex-col items-center justify-center text-slate-400">
                                        <RefreshCw className="animate-spin w-12 h-12 text-blue-500 mb-4" />
                                        <p className="font-medium">Cruching numbers...</p>
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
                                        {/* Market Lines (clarify who is favored) */}
                                        <div className="bg-slate-800/60 p-4 rounded-xl border border-slate-700/50">
                                            <div className="text-[10px] text-slate-500 uppercase font-black tracking-widest mb-2">Market Lines</div>
                                            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-sm">
                                                <div className="bg-slate-900/40 p-3 rounded-lg border border-slate-700/50">
                                                    <div className="text-[10px] text-slate-500 uppercase font-black mb-1">Spread (team / line / odds)</div>
                                                    {(selectedGame.home_spread !== null && selectedGame.home_spread !== undefined) || (selectedGame.away_spread !== null && selectedGame.away_spread !== undefined) ? (() => {
                                                        const hs = selectedGame.home_spread !== null && selectedGame.home_spread !== undefined ? Number(selectedGame.home_spread) : null;
                                                        const as = selectedGame.away_spread !== null && selectedGame.away_spread !== undefined ? Number(selectedGame.away_spread) : (hs !== null ? -hs : null);
                                                        const favored = hs !== null ? (hs < 0 ? selectedGame.home_team : (hs > 0 ? selectedGame.away_team : 'Pick')) : '—';
                                                        return (
                                                            <div className="space-y-1 text-xs">
                                                                <div className="flex justify-between gap-2">
                                                                    <span className="text-slate-400 truncate">{selectedGame.away_team}</span>
                                                                    <span className="text-slate-200 font-mono font-bold">{fmtSigned(as, 1)}</span>
                                                                    <span className="text-slate-500 font-mono">{fmtSigned(selectedGame.spread_away_odds)}</span>
                                                                </div>
                                                                <div className="flex justify-between gap-2">
                                                                    <span className="text-slate-400 truncate">{selectedGame.home_team}</span>
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
                                                <div className="bg-slate-900/40 p-3 rounded-lg border border-slate-700/50">
                                                    <div className="text-[10px] text-slate-500 uppercase font-black mb-1">Model Summary</div>
                                                    <div className="text-slate-300 text-xs leading-snug">
                                                        {analysisResult.narrative?.market_summary || '—'}
                                                    </div>
                                                </div>
                                            </div>
                                        </div>

                                        {/* Recommendations */}
                                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                            {analysisResult.recommendations?.map((rec, idx) => (
                                                <div key={idx} className="bg-slate-800/50 p-4 rounded-xl border border-slate-700">
                                                    <div className="flex justify-between items-start mb-2">
                                                        <span className="text-[10px] font-black uppercase tracking-widest text-slate-500">
                                                            {rec.bet_type} Recommendation
                                                        </span>
                                                        <span className={`text-[10px] px-2 py-0.5 rounded font-bold uppercase ${rec.confidence === 'High' ? 'bg-green-500/20 text-green-400' :
                                                            rec.confidence === 'Medium' ? 'bg-yellow-500/20 text-yellow-400' :
                                                                'bg-slate-700 text-slate-400'
                                                            }`}>
                                                            {rec.confidence} Confidence
                                                        </span>
                                                    </div>
                                                    <div className="text-2xl font-bold text-white mb-1">
                                                        {(() => {
                                                            // Ensure spread picks display with a + when appropriate (avoid ambiguity)
                                                            try {
                                                                if (rec.bet_type === 'SPREAD') {
                                                                    const m = String(rec.selection || '').match(/^(.*)\s([-+]?\d+(?:\.\d+)?)$/);
                                                                    if (!m) return rec.selection;
                                                                    const team = m[1].trim();
                                                                    const line = Number(m[2]);
                                                                    if (Number.isNaN(line)) return rec.selection;
                                                                    return `${team} ${fmtSigned(line, 1)}`;
                                                                }
                                                            } catch (e) {}
                                                            return rec.selection;
                                                        })()}
                                                    </div>
                                                    <div className="text-xs text-slate-400">
                                                        Edge: <span className="text-green-400 font-bold">+{rec.edge}</span> •
                                                        Fair: {rec.fair_line}
                                                    </div>
                                                    <div className="mt-3 text-xs text-slate-300 bg-slate-900/30 p-3 rounded-lg border border-slate-700/50">
                                                        <div className="text-[10px] text-slate-500 uppercase font-black mb-1">What needs to happen</div>
                                                        {(() => {
                                                            try {
                                                                if (rec.bet_type === 'SPREAD') {
                                                                    // selection looks like: "TeamName -12.5" or "TeamName 4.5"
                                                                    const m = String(rec.selection || '').match(/^(.*)\s([-+]?\d+(?:\.\d+)?)$/);
                                                                    const team = (m?.[1] || rec.selection || '').trim();
                                                                    const line = m ? Number(m[2]) : null;
                                                                    if (line === null || Number.isNaN(line)) return 'Team must cover the spread.';
                                                                    const needed = line < 0 ? `win by ${Math.abs(line) + 0.5}+` : `lose by ${Math.abs(line) - 0.5} or win`;
                                                                    return `${team} must cover ${line > 0 ? '+' : ''}${line} (i.e., ${needed}).`;
                                                                }
                                                                if (rec.bet_type === 'TOTAL') {
                                                                    // selection looks like: "OVER 151.5" / "UNDER 151.5"
                                                                    const mm = String(rec.selection || '').match(/^(OVER|UNDER)\s+(\d+(?:\.\d+)?)$/i);
                                                                    const side = (mm?.[1] || 'TOTAL').toUpperCase();
                                                                    const line = mm ? Number(mm[2]) : null;
                                                                    if (line === null || Number.isNaN(line)) return 'Game total must land on the correct side of the total.';
                                                                    return side === 'OVER'
                                                                        ? `Combined score must finish OVER ${line}.`
                                                                        : `Combined score must finish UNDER ${line}.`;
                                                                }
                                                                return 'Bet outcome must align with the recommended side.';
                                                            } catch (e) {
                                                                return 'Bet outcome must align with the recommended side.';
                                                            }
                                                        })()}
                                                    </div>
                                                </div>
                                            ))}
                                            {!analysisResult.recommendations?.length && (
                                                <div className="col-span-2 text-center py-4 text-slate-500">
                                                    No recommendations generated.
                                                </div>
                                            )}
                                        </div>

                                        {/* Narrative & Torvik View */}
                                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                            <div className="bg-gradient-to-br from-slate-800 to-slate-900 p-6 rounded-xl border border-slate-700/50 relative overflow-hidden">
                                                <h3 className="font-bold text-slate-200 mb-3 flex items-center gap-2 text-sm uppercase tracking-wider">
                                                    <Info size={16} className="text-blue-400" />
                                                    Summary (what needs to happen)
                                                </h3>

                                                {(() => {
                                                    const rec = (analysisResult.recommendations || [])[0] || null;
                                                    if (!rec) return <div className="text-slate-500 text-sm">No recommendation summary available.</div>;

                                                    const betType = String(rec.bet_type || '').toUpperCase();
                                                    const selection = String(rec.selection || '').trim();
                                                    let what = '';

                                                    try {
                                                        if (betType === 'SPREAD') {
                                                            const m = selection.match(/^(.*)\s([-+]?\d+(?:\.\d+)?)$/);
                                                            const team = (m?.[1] || selection).trim();
                                                            const line = m ? Number(m[2]) : null;
                                                            if (line !== null && !Number.isNaN(line)) {
                                                                what = line < 0
                                                                    ? `${team} must win by ${Math.abs(line) + 0.5}+.`
                                                                    : `${team} must lose by ${Math.abs(line) - 0.5} or win.`;
                                                            } else {
                                                                what = `${team} must cover the spread.`;
                                                            }
                                                        } else if (betType === 'TOTAL') {
                                                            const mm = selection.match(/^(OVER|UNDER)\s+(\d+(?:\.\d+)?)$/i);
                                                            const side = (mm?.[1] || '').toUpperCase();
                                                            const line = mm ? Number(mm[2]) : null;
                                                            if (side && line !== null && !Number.isNaN(line)) {
                                                                what = side === 'OVER'
                                                                    ? `Combined score must finish OVER ${line}.`
                                                                    : `Combined score must finish UNDER ${line}.`;
                                                            } else {
                                                                what = 'Game total must land on the correct side of the total.';
                                                            }
                                                        } else {
                                                            what = 'Bet outcome must align with the recommended side.';
                                                        }
                                                    } catch (e) {
                                                        what = 'Bet outcome must align with the recommended side.';
                                                    }

                                                    const marketSummary = analysisResult.narrative?.market_summary || '';
                                                    const rationale = analysisResult.narrative?.rationale || [];

                                                    return (
                                                        <div className="text-slate-300 text-sm leading-relaxed space-y-3">
                                                            {marketSummary ? (
                                                                <div className="text-blue-300 font-semibold">{marketSummary}</div>
                                                            ) : null}

                                                            <div className="bg-slate-900/30 p-3 rounded-lg border border-slate-700/50">
                                                                <div className="text-[10px] text-slate-500 uppercase font-black mb-1">Primary condition</div>
                                                                <div className="text-slate-100 font-bold">{what}</div>
                                                            </div>

                                                            {analysisResult.narrative?.recommendation ? (
                                                                <div className="opacity-90">{analysisResult.narrative.recommendation}</div>
                                                            ) : null}

                                                            {rationale?.length ? (
                                                                <ul className="list-disc list-inside space-y-1 opacity-80">
                                                                    {rationale.map((r, i) => (
                                                                        <li key={i}>{r}</li>
                                                                    ))}
                                                                </ul>
                                                            ) : null}
                                                        </div>
                                                    );
                                                })()}
                                            </div>

                                            <div className="bg-slate-800/80 p-6 rounded-xl border border-slate-700/50">
                                                <h3 className="font-bold text-slate-200 mb-4 flex items-center gap-2 text-sm uppercase tracking-wider">
                                                    <ShieldCheck size={16} className="text-green-400" />
                                                    Torvik View
                                                </h3>
                                                <div className="grid grid-cols-2 gap-4">
                                                    <div className="bg-slate-900/50 p-3 rounded-lg border border-slate-700">
                                                        <div className="text-[10px] text-slate-500 uppercase font-black mb-1">Projected Score</div>
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
                                                                    <div className="flex justify-between text-white font-bold">
                                                                        <span className="truncate pr-2">{awayName}</span>
                                                                        <span className="font-mono">{awayScore}</span>
                                                                    </div>
                                                                    <div className="flex justify-between text-white font-bold">
                                                                        <span className="truncate pr-2">{homeName}</span>
                                                                        <span className="font-mono">{homeScore}</span>
                                                                    </div>
                                                                </div>
                                                            );
                                                        })()}
                                                    </div>
                                                    <div className="bg-slate-900/50 p-3 rounded-lg border border-slate-700">
                                                        <div className="text-[10px] text-slate-500 uppercase font-black mb-1">Proj Margin</div>
                                                        <div className="text-lg font-bold text-white">{analysisResult.torvik_view.margin > 0 ? '+' : ''}{analysisResult.torvik_view.margin}</div>
                                                    </div>
                                                </div>
                                                <div className="mt-4 text-[10px] text-slate-500 italic">
                                                    {analysisResult.torvik_view.lean}
                                                </div>
                                            </div>

                                            {/* KenPom View */}
                                            {analysisResult.kenpom_data && (
                                                <div className="bg-slate-800/80 p-6 rounded-xl border border-slate-700/50">
                                                    <h3 className="font-bold text-slate-200 mb-4 flex items-center gap-2 text-sm uppercase tracking-wider">
                                                        <Shield size={16} className="text-purple-400" />
                                                        KenPom View
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
                                                <div className="bg-slate-800/80 p-6 rounded-xl border border-slate-700/50">
                                                    <h3 className="font-bold text-slate-200 mb-4 flex items-center gap-2 text-sm uppercase tracking-wider">
                                                        <AlertCircle size={16} className="text-amber-400" />
                                                        News / Context
                                                    </h3>
                                                    <div className="text-sm text-slate-300 bg-slate-900/30 p-3 rounded-lg border border-slate-700/50 min-h-[80px]">
                                                        {analysisResult.news_summary}
                                                    </div>
                                                </div>
                                            )}
                                        </div>

                                        {/* Key Factors */}
                                        {analysisResult.key_factors && (
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

                                        {/* Risks */}
                                        {analysisResult.risks && (
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
