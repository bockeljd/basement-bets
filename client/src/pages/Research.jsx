import React, { useState, useEffect } from 'react';
import api from '../api/axios';
import { ArrowUpDown, ChevronUp, ChevronDown, Filter, RefreshCw, CheckCircle, AlertCircle, Info, Shield, ShieldAlert, ShieldCheck } from 'lucide-react';

const Research = () => {
    const [edges, setEdges] = useState([]);
    const [history, setHistory] = useState([]);
    const [activeTab, setActiveTab] = useState('live');
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [showAll, setShowAll] = useState(false);

    // Sorting & Filtering State
    const [sortConfig, setSortConfig] = useState({ key: 'edge', direction: 'desc' });
    const [sportFilter, setSportFilter] = useState('All');
    const [edgeThreshold, setEdgeThreshold] = useState(2.0); // Default to 2.0 pts or 5% EV
    const [confidenceThreshold, setConfidenceThreshold] = useState(50); // Default 50%

    useEffect(() => {
        fetchEdges();
    }, []);

    const fetchEdges = async () => {
        try {
            setLoading(true);

            const [edgesRes, historyRes] = await Promise.all([
                api.get('/api/research'),
                api.get('/api/research/history')
            ]);

            setEdges(edgesRes.data || []);
            setHistory(historyRes.data || []);

        } catch (err) {
            console.error(err);
            setError('Failed to load predictive models.');
        } finally {
            setLoading(false);
        }
    };

    const gradeResults = async () => {
        try {
            setLoading(true);
            const res = await api.post('/api/research/grade');
            const result = res.data;
            alert(`Grading Complete! ${result.graded || 0} bets updated.`);
            await fetchEdges();
        } catch (err) {
            console.error(err);
            alert('Grading failed: ' + (err.response?.data?.message || err.message));
        } finally {
            setLoading(false);
        }
    };

    const refreshData = async () => {
        try {
            setLoading(true);
            const res = await api.post('/api/jobs/ingest_torvik');
            const result = res.data;
            alert(`Data Refresh Complete! ${result.teams_count || 0} teams updated.`);
            await fetchEdges();
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

    const getEdgeColor = (edge, sport) => {
        if (edge === null || edge === undefined) return 'text-gray-500';

        // Percent-based (EPL)
        if (sport === 'EPL') {
            if (edge > 10) return 'text-green-400 font-bold';
            if (edge > 5) return 'text-green-300';
            if (edge > 0) return 'text-green-200';
            return 'text-red-400';
        }

        // Point-based (NFL/NCAAM)
        const threshold = sport === 'NFL' ? 1.5 : 3.0;
        if (edge >= threshold * 2) return 'text-green-400 font-bold';
        if (edge >= threshold) return 'text-green-300';
        if (edge > 0) return 'text-green-200';
        return 'text-red-400';
    };

    const getProcessedEdges = () => {
        let filtered = edges.filter(e => {
            if (!showAll && !e.is_actionable) return false;

            const edgeVal = e.edge || 0;
            const confVal = e.audit_score || 50;

            // Adjust edge threshold based on sport
            const meetEdge = e.sport === 'EPL' ? edgeVal >= (edgeThreshold * 2.5) : edgeVal >= edgeThreshold;
            const meetConf = confVal >= confidenceThreshold;

            if (sportFilter !== 'All' && e.sport !== sportFilter) return false;

            return meetEdge && meetConf;
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

    const getFilteredHistory = () => {
        return history.filter(h => {
            const edgeVal = h.edge || 0;
            // Missing audit_score in DB history. Default to High if Edge is high?
            // If historical item exists, it WAS actionable.
            const confVal = h.audit_score || (h.is_actionable ? 85 : 50);

            const meetEdge = h.sport === 'EPL' ? edgeVal >= (edgeThreshold * 2.5) : edgeVal >= edgeThreshold;
            const meetConf = confVal >= confidenceThreshold;
            return meetEdge && meetConf;
        });
    };

    const getSortedHistory = () => {
        return [...getFilteredHistory()].sort((a, b) => {
            let aVal = a[sortConfig.key] || '';
            let bVal = b[sortConfig.key] || '';
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
                <h1 className="text-3xl font-bold bg-gradient-to-r from-blue-400 to-green-400 bg-clip-text text-transparent">
                    Bet Research
                </h1>
                <div className="flex gap-2">
                    <button
                        onClick={refreshData}
                        disabled={loading}
                        className="px-4 py-2 bg-green-600 hover:bg-green-500 rounded-lg text-sm transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                    >
                        <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
                        Refresh Data
                    </button>
                    <button
                        onClick={fetchEdges}
                        className="px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded-lg text-sm transition-all"
                    >
                        {loading ? 'Running Models...' : 'Refresh Models'}
                    </button>
                </div>
            </div>

            {/* Tabs */}
            <div className="flex space-x-4 mb-6 border-b border-slate-700">
                <button
                    onClick={() => setActiveTab('live')}
                    className={`pb-2 px-4 text-sm font-medium transition-colors ${activeTab === 'live' ? 'text-blue-400 border-b-2 border-blue-400' : 'text-slate-400 hover:text-slate-200'}`}
                >
                    Live Edges
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
                            {/* Sport Filter */}
                            <div className="flex items-center bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 focus-within:border-blue-500/50 transition-all">
                                <Filter size={14} className="text-slate-500 mr-2" />
                                <select
                                    value={sportFilter}
                                    onChange={(e) => setSportFilter(e.target.value)}
                                    className="bg-transparent text-sm font-medium focus:outline-none cursor-pointer"
                                >
                                    <option value="All">All Sports</option>
                                    <option value="NFL">NFL</option>
                                    <option value="NCAAM">NCAAM</option>
                                    <option value="EPL">EPL</option>
                                </select>
                            </div>
                        </div>

                        <label className="flex items-center cursor-pointer group">
                            <div className="relative">
                                <input
                                    type="checkbox"
                                    className="sr-only"
                                    checked={showAll}
                                    onChange={() => setShowAll(!showAll)}
                                />
                                <div className={`block w-14 h-8 rounded-full transition-colors ${showAll ? 'bg-blue-600' : 'bg-slate-700 border border-slate-600'}`}></div>
                                <div className={`dot absolute left-1 top-1 bg-white w-6 h-6 rounded-full transition-transform ${showAll ? 'transform translate-x-6' : ''}`}></div>
                            </div>
                            <div className="ml-3 text-slate-400 group-hover:text-slate-200 font-medium transition-colors">
                                Show No Edge Games
                            </div>
                        </label>
                    </div>

                    <div className="bg-slate-800 rounded-xl border border-slate-700 shadow-xl overflow-hidden">
                        <div className="px-6 py-4 border-b border-slate-700 flex justify-between items-center">
                            <h2 className="text-lg font-semibold text-slate-200">Live Model Edges</h2>
                            <div className="text-xs text-slate-500 flex items-center">
                                <AlertCircle size={12} className="mr-1" />
                                Updated in real-time
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
                                                <div className="flex items-center">Sport <SortIcon column="sport" /></div>
                                            </th>
                                            <th className="py-2 px-4 text-xs font-bold uppercase tracking-wider cursor-pointer hover:text-white transition-colors" onClick={() => handleSort('game')}>
                                                <div className="flex items-center">Matchup <SortIcon column="game" /></div>
                                            </th>
                                            <th className="py-2 px-4 text-xs font-bold uppercase tracking-wider cursor-pointer hover:text-white transition-colors" onClick={() => handleSort('bet_on')}>
                                                <div className="flex items-center">Best Bet <SortIcon column="bet_on" /></div>
                                            </th>
                                            <th className="py-2 px-4 text-xs font-bold uppercase tracking-wider">
                                                <div className="flex items-center group relative cursor-help">
                                                    Market / Fair
                                                    <Info size={14} className="ml-2 text-slate-500 group-hover:text-blue-400 transition-colors" />

                                                    {/* Tooltip Content */}
                                                    <div className="absolute left-0 bottom-full mb-2 w-72 p-4 bg-slate-900 border border-slate-700 rounded-xl shadow-2xl opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all z-50 text-[11px] leading-relaxed normal-case font-medium ring-1 ring-white/5">
                                                        <div className="text-blue-400 font-black mb-2 tracking-widest uppercase">Market vs Fair</div>
                                                        <div className="space-y-3">
                                                            <p className="text-slate-300">
                                                                <span className="text-white font-bold block mb-0.5">Market (The Book)</span>
                                                                The current line offered by sportsbooks. It reflects public consensus and includes the "vig" (commission).
                                                            </p>
                                                            <div className="h-px bg-slate-800 w-full"></div>
                                                            <p className="text-slate-300">
                                                                <span className="text-white font-bold block mb-0.5">Fair (The Model)</span>
                                                                Our model's statistical "true price" (via EPA, Monte Carlo, or Poisson). The difference between Market and Fair is your <span className="text-green-400 font-bold underline">Edge</span>.
                                                            </p>
                                                        </div>
                                                        {/* Tooltip Arrow */}
                                                        <div className="absolute top-full left-6 -mt-1 border-[6px] border-transparent border-t-slate-700"></div>
                                                        <div className="absolute top-full left-6 -mt-1.5 border-[6px] border-transparent border-t-slate-900"></div>
                                                    </div>
                                                </div>
                                            </th>
                                            <th className="py-2 px-4 text-xs font-bold uppercase tracking-wider cursor-pointer hover:text-white transition-colors" onClick={() => handleSort('edge')}>
                                                <div className="flex items-center">Edge <SortIcon column="edge" /></div>
                                            </th>
                                            <th className="py-2 px-4 text-xs font-bold uppercase tracking-wider">
                                                <div className="flex items-center">Size / Risk</div>
                                            </th>
                                            <th className="py-2 px-4 text-xs font-bold uppercase tracking-wider cursor-pointer hover:text-white transition-colors" onClick={() => handleSort('audit_score')}>
                                                <div className="flex items-center">Conf <SortIcon column="audit_score" /></div>
                                            </th>
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y divide-slate-700/50">
                                        {getProcessedEdges().map((edge, idx) => {
                                            const date = edge.start_time ? new Date(edge.start_time) : null;
                                            const dateStr = date ? date.toLocaleDateString('en-US', { month: 'numeric', day: 'numeric' }) : '-';
                                            const timeStr = date ? date.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' }) : '';
                                            const isEdge = edge.is_actionable;

                                            return (
                                                <tr key={idx} className={`group hover:bg-slate-700/30 transition-all ${!isEdge ? 'opacity-50 grayscale-[0.5]' : ''}`}>
                                                    <td className="py-2 px-4 text-slate-400 text-xs whitespace-nowrap">
                                                        <div className="font-bold text-slate-300">{dateStr}</div>
                                                        <div>{timeStr}</div>
                                                    </td>
                                                    <td className="py-2 px-4">
                                                        <span className={`text-[10px] font-black px-2 py-0.5 rounded tracking-tighter uppercase
                                                                ${edge.sport === 'NFL' ? 'bg-blue-500/20 text-blue-400 border border-blue-500/20' :
                                                                edge.sport === 'NCAAM' ? 'bg-orange-500/20 text-orange-400 border border-orange-500/20' :
                                                                    'bg-purple-500/20 text-purple-400 border border-purple-500/20'}`}>
                                                            {edge.sport}
                                                        </span>
                                                    </td>
                                                    <td className="py-2 px-4 font-semibold text-slate-200 text-sm">{edge.game}</td>
                                                    <td className="py-2 px-4">
                                                        <div className="text-white font-bold flex items-center">
                                                            {edge.market === 'Total' ? edge.bet_on : edge.bet_on}
                                                            {isEdge && <CheckCircle size={12} className="ml-2 text-green-500" />}
                                                        </div>
                                                        <div className="text-[10px] text-slate-500 uppercase font-bold tracking-widest mt-0.5">{edge.market}</div>
                                                        {edge.audit_reason && (
                                                            <div className="text-[10px] text-slate-400 mt-1 italic leading-tight">
                                                                {edge.audit_reason}
                                                            </div>
                                                        )}
                                                    </td>
                                                    <td className="py-2 px-4">
                                                        <div className="flex flex-col">
                                                            <div className="text-xs text-slate-300">Market: <span className="text-white font-mono">{edge.market_line}</span></div>
                                                            <div className="text-xs text-slate-500">Fair: <span className="font-mono">{edge.fair_line}</span></div>
                                                        </div>
                                                    </td>
                                                    <td className={`py-2 px-4 w-32 ${getEdgeColor(edge.edge, edge.sport)}`}>
                                                        <div className="flex flex-col items-start whitespace-nowrap">
                                                            <span className="text-lg font-bold">
                                                                {edge.sport === 'EPL' ? `${edge.edge}%` : `${edge.edge} pts`}
                                                            </span>
                                                            <span className="text-[10px] uppercase tracking-tighter opacity-70 font-black">
                                                                {edge.sport === 'EPL' ? 'Exp. Value' : 'Line Value'}
                                                            </span>
                                                        </div>
                                                    </td>
                                                    <td className="py-2 px-4">
                                                        <div className="flex flex-col">
                                                            {edge.suggested_stake ? (
                                                                <>
                                                                    <div className="text-green-400 font-bold">${edge.suggested_stake}</div>
                                                                    <div className="text-[10px] text-slate-500">{edge.bankroll_pct}% Bankroll</div>
                                                                </>
                                                            ) : (
                                                                <span className="text-slate-600">No Edge</span>
                                                            )}
                                                        </div>
                                                    </td>
                                                    <td className="py-2 px-4">
                                                        <div className="group relative flex items-center cursor-help">
                                                            {edge.audit_class === 'high' ? (
                                                                <ShieldCheck className="text-green-400" size={18} />
                                                            ) : edge.audit_class === 'medium' ? (
                                                                <Shield className="text-yellow-400" size={18} />
                                                            ) : (
                                                                <ShieldAlert className="text-red-400 animate-pulse" size={18} />
                                                            )}

                                                            {/* Tooltip */}
                                                            <div className="absolute right-full mr-2 w-48 p-3 bg-slate-900 border border-slate-700 rounded-lg shadow-xl opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all z-50 text-[10px]">
                                                                <div className={`font-bold uppercase tracking-wider mb-1 ${edge.audit_class === 'high' ? 'text-green-400' :
                                                                    edge.audit_class === 'medium' ? 'text-yellow-400' : 'text-red-400'
                                                                    }`}>
                                                                    {edge.audit_class === 'high' ? 'High Confidence' :
                                                                        edge.audit_class === 'medium' ? 'Medium Confidence' : 'Low Confidence'}
                                                                </div>
                                                                <p className="text-slate-300 leading-tight">{edge.audit_reason}</p>
                                                            </div>
                                                        </div>
                                                    </td>
                                                </tr>
                                            );
                                        })}
                                    </tbody>
                                </table>
                            </div>
                        )}
                    </div>
                </>
            )}

            {activeTab === 'history' && (
                <div className="bg-slate-800 rounded-xl border border-slate-700 shadow-xl overflow-hidden">
                    <div className="px-6 py-4 border-b border-slate-700 flex justify-between items-center bg-slate-800/50">
                        <h2 className="text-lg font-semibold text-slate-200">Model History (Auto-Tracked)</h2>
                        <button
                            onClick={gradeResults}
                            disabled={loading}
                            className="px-4 py-2 bg-green-600/20 hover:bg-green-600/30 text-green-400 border border-green-500/20 disabled:opacity-50 rounded-lg text-xs font-bold transition-all flex items-center"
                        >
                            {loading ? <RefreshCw className="animate-spin mr-2" size={12} /> : null}
                            Grade Results
                        </button>
                    </div>

                    {/* Model Performance Summary */}
                    <div className="px-6 py-6 bg-slate-800/30 border-b border-slate-700 grid grid-cols-2 lg:grid-cols-4 gap-4">
                        {[
                            {
                                label: 'Graded Bets',
                                value: getFilteredHistory().filter(h => h.result && h.result !== 'Pending').length,
                                icon: <CheckCircle size={14} className="text-blue-400" />
                            },
                            {
                                label: 'Record',
                                value: (() => {
                                    const h = getFilteredHistory();
                                    const w = h.filter(x => x.result === 'Win').length;
                                    const l = h.filter(x => x.result === 'Loss').length;
                                    const p = h.filter(x => x.result === 'Push').length;
                                    return `${w}-${l}${p > 0 ? `-${p}` : ''}`;
                                })(),
                                icon: <ArrowUpDown size={14} className="text-green-400" />
                            },
                            {
                                label: 'Win Rate',
                                value: (() => {
                                    const h = getFilteredHistory().filter(x => x.result && x.result !== 'Pending');
                                    const w = h.filter(x => x.result === 'Win').length;
                                    return h.length > 0 ? `${((w / h.length) * 100).toFixed(1)}%` : '0.0%';
                                })(),
                                icon: <CheckCircle size={14} className="text-purple-400" />
                            },
                            {
                                label: 'Est. Return ($10/bet)',
                                value: `$${getFilteredHistory().reduce((acc, h) => {
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
                                    {getSortedHistory().map((item, idx) => (
                                        <tr key={idx} className="border-b border-slate-700/50 hover:bg-slate-700/30 transition-colors">
                                            <td className="py-2 px-4 text-slate-400 text-xs whitespace-nowrap">
                                                <div className="font-bold text-slate-300">
                                                    {new Date(item.date || item.created_at).toLocaleDateString([], { month: 'numeric', day: 'numeric' })}
                                                </div>
                                                <div className="opacity-70">
                                                    {new Date(item.date || item.created_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}
                                                </div>
                                            </td>
                                            <td className="py-2 px-4">
                                                <span className={`text-[10px] font-black px-2 py-0.5 rounded tracking-tighter uppercase
                                                    ${item.sport === 'NFL' ? 'bg-blue-500/20 text-blue-400 border border-blue-500/20' :
                                                        item.sport === 'NCAAM' ? 'bg-orange-500/20 text-orange-400 border border-orange-500/20' :
                                                            'bg-purple-500/20 text-purple-400 border border-purple-500/20'}`}>
                                                    {item.sport}
                                                </span>
                                            </td>
                                            <td className="py-2 px-4 font-medium text-sm text-slate-200">{item.matchup}</td>
                                            <td className="py-2 px-4 text-white font-bold">
                                                {item.bet_on}
                                            </td>
                                            <td className="py-2 px-4 text-slate-400 text-xs">
                                                <div className="flex flex-col">
                                                    <span>Mkt: <span className="text-slate-300 font-mono">{item.market_line}</span></span>
                                                    <span>Fair: <span className="text-slate-500 font-mono">{item.fair_line}</span></span>
                                                </div>
                                            </td>
                                            <td className={`py-2 px-4 font-bold ${getEdgeColor(item.edge, item.sport)}`}>
                                                {item.edge}{item.sport === 'EPL' ? '%' : ' pts'}
                                            </td>
                                            <td className="py-2 px-4 text-right sm:text-left">
                                                <span className={`px-2 py-1 rounded text-[10px] font-black uppercase tracking-widest
                                                    ${item.result === 'Win' ? 'bg-green-500/20 text-green-400 border border-green-500/20' :
                                                        item.result === 'Loss' ? 'bg-red-500/20 text-red-400 border border-red-500/20' :
                                                            item.result === 'Push' ? 'bg-yellow-500/20 text-yellow-400 border border-yellow-500/20' :
                                                                'bg-slate-700/50 text-slate-400 border border-slate-600'}`}>
                                                    {item.result || 'Pending'}
                                                </span>
                                            </td>
                                            <td className="py-2 px-4 text-slate-300 font-mono text-xs">
                                                {item.home_score !== null && item.away_score !== null ? (
                                                    <div className="flex flex-col">
                                                        <span className="text-white font-bold">{item.home_score}-{item.away_score}</span>
                                                        <span className="text-[10px] text-slate-500">T: {item.home_score + item.away_score}</span>
                                                    </div>
                                                ) : '-'}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </div>
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
    );
};

export default Research;
