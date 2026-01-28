import React, { useState, useEffect } from 'react';
import api from './api/axios';
import {
    LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, BarChart, Bar, Cell,
    ScatterChart, Scatter, ZAxis, ReferenceLine
} from 'recharts';
import { TrendingUp, TrendingDown, ArrowUpRight, ArrowDownRight, DollarSign, Activity, PieChart, BarChart2, BarChart3, Calendar, Layout, LayoutDashboard, Search, Menu, X, PlusCircle, Trash, Trash2, CheckCircle, Clock, Percent, List, FileText, Info, Settings, User, RefreshCw, AlertTriangle, AlertCircle, Filter, ChevronDown, ChevronRight, MessageSquare, BookOpen, ExternalLink, ArrowRight, Table } from 'lucide-react';

console.log("Basement Bets Frontend v1.2.1 (Profit X-Axis) Loaded at " + new Date().toISOString());
import axios from 'axios';
import BetTypeAnalysis from './components/BetTypeAnalysis';
import Research from './pages/Research';
import { PasteSlipContainer } from './components/PasteSlipContainer';
// import { StagingBanner } from './components/StagingBanner';

// --- Login Modal Component ---
const LoginModal = ({ onSubmit }) => {
    const [pass, setPass] = useState('');
    return (
        <div className="fixed inset-0 bg-black/80 flex items-center justify-center z-[9999]">
            <div className="bg-slate-900 border border-slate-700 p-8 rounded-xl max-w-md w-full shadow-2xl">
                <h2 className="text-2xl font-bold text-white mb-4">Authentication</h2>
                <p className="text-slate-400 mb-6">Enter the Basement Password to access this server.</p>
                <form onSubmit={(e) => { e.preventDefault(); onSubmit(pass); }}>
                    <input
                        type="password"
                        value={pass}
                        onChange={(e) => setPass(e.target.value)}
                        className="w-full bg-slate-800 border border-slate-600 text-white rounded p-3 mb-4 focus:ring-2 focus:ring-blue-500 outline-none"
                        placeholder="Password..."
                        autoFocus
                    />
                    <button
                        type="submit"
                        className="w-full bg-blue-600 hover:bg-blue-500 text-white font-bold py-3 rounded transition-colors"
                    >
                        Login
                    </button>
                </form>
            </div>
        </div>
    );
};

// Helpers
const formatCurrency = (val) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).filter ? new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(val) : (typeof val === 'number' ? `$${val.toFixed(2)}` : val);

class ErrorBoundary extends React.Component {
    constructor(props) {
        super(props);
        this.state = { hasError: false, error: null };
    }

    static getDerivedStateFromError(error) {
        return { hasError: true, error };
    }

    componentDidCatch(error, errorInfo) {
        console.error("UI Error:", error, errorInfo);
    }

    render() {
        if (this.state.hasError) {
            return (
                <div className="p-10 text-red-500 bg-slate-900 border border-red-900 m-8 rounded-xl">
                    <h2 className="text-xl font-bold mb-2">Something went wrong.</h2>
                    <pre className="text-sm bg-black p-4 rounded overflow-auto">
                        {this.state.error?.toString()}
                    </pre>
                </div>
            );
        }

        return this.props.children;
    }
}

function App() {
    const [view, setView] = useState('summary');
    const [stats, setStats] = useState(null);
    const [bets, setBets] = useState([]);
    const [sportBreakdown, setSportBreakdown] = useState([]);
    const [playerBreakdown, setPlayerBreakdown] = useState([]);
    const [monthlyBreakdown, setMonthlyBreakdown] = useState([]);
    const [betTypeBreakdown, setBetTypeBreakdown] = useState([]);
    const [balances, setBalances] = useState({});
    const [error, setError] = useState(null);
    const [timeSeries, setTimeSeries] = useState([]);
    const [drawdown, setDrawdown] = useState(null);
    const [financials, setFinancials] = useState({ total_in_play: 0, total_deposited: 0, total_withdrawn: 0, realized_profit: 0 });
    const [periodStats, setPeriodStats] = useState({ '7d': null, '30d': null, 'ytd': null, 'all': null });
    const [edgeBreakdown, setEdgeBreakdown] = useState([]);
    const [showAddBet, setShowAddBet] = useState(false);
    const [isSyncing, setIsSyncing] = useState(false);

    // Auth State
    const [showLogin, setShowLogin] = useState(() => {
        return !localStorage.getItem('basement_password');
    });

    const handleLogin = (pass) => {
        localStorage.setItem('basement_password', pass);
        window.location.reload();
    };

    const handleSyncResults = async () => {
        setIsSyncing(true);
        try {
            // Sync all active leagues
            const leagues = ['NFL', 'NCAAM', 'NCAAF', 'EPL'];
            for (const league of leagues) {
                await api.post(`/api/jobs/ingest_results/${league}`);
            }
            // Add reconciliation and grading
            await api.post('/api/jobs/reconcile');
            await api.post('/api/jobs/grade_predictions');

            alert("Results synced and bets settled successfully!");
            window.location.reload();
        } catch (err) {
            console.error("Sync Error", err);
            alert("Failed to sync results. Check backend logs.");
        } finally {
            setIsSyncing(false);
        }
    };

    if (showLogin) {
        return <LoginModal onSubmit={handleLogin} />;
    }

    useEffect(() => {
        // Fetch Data
        const fetchData = async () => {
            try {
                // Helper to get data or default
                const getVal = (res, defaultVal) => res.status === 'fulfilled' ? res.value.data : defaultVal;

                // Parallelize API calls
                const results = await Promise.allSettled([
                    api.get('/api/stats'),
                    api.get('/api/bets'),
                    api.get('/api/breakdown/sport'),
                    api.get('/api/breakdown/player'),
                    api.get('/api/breakdown/monthly'),
                    api.get('/api/breakdown/bet_type'),
                    api.get('/api/balances'),
                    api.get('/api/financials'),
                    api.get('/api/analytics/series'),
                    api.get('/api/analytics/drawdown'),
                    api.get('/api/breakdown/edge')
                ]);

                // Check for 403 or 500 in results to alert user
                const failed = results.find(r => r.status === 'rejected');
                if (failed) {
                    const reason = failed.reason;
                    if (reason && ((reason.response && reason.response.status === 403) || (reason.message && reason.message.includes("403")))) {
                        localStorage.removeItem('basement_password'); // Force clear storage
                        setShowLogin(true);
                    }
                    // Since we catch globally in axios for 403, this is likely 500 or Network
                    // throw failed.reason;
                }

                // Fetch Period Stats in parallel
                const currentYear = new Date().getFullYear();
                const periodResults = await Promise.allSettled([
                    api.get('/api/stats/period?days=7'),
                    api.get('/api/stats/period?days=30'),
                    api.get(`/api/stats/period?year=${currentYear}`),
                    api.get('/api/stats/period')
                ]);

                setStats(getVal(results[0], { total_bets: 0, total_profit: 0, win_rate: 0, roi: 0 }));
                setBets(getVal(results[1], []));
                setSportBreakdown(getVal(results[2], []));
                setPlayerBreakdown(getVal(results[3], []));
                setMonthlyBreakdown(getVal(results[4], []));

                // Manual Fallback for Bet Type Wins if API returns 0s
                const rawBets = getVal(results[1], []);
                const apiBetBreakdown = getVal(results[5], []);

                // Re-calculate wins from raw bets to be safe
                const calculatedBreakdown = {};
                apiBetBreakdown.forEach(b => {
                    calculatedBreakdown[b.bet_type] = { ...b };
                });

                if (rawBets.length > 0) {
                    rawBets.forEach(bet => {
                        const type = bet.bet_type || 'Unknown';
                        if (!calculatedBreakdown[type]) {
                            calculatedBreakdown[type] = { bet_type: type, bets: 0, wins: 0, profit: 0, wager: 0, roi: 0 };
                        }

                        // Force recalculation
                        // We trust total count and profit from API, but Wins might be 0 due to backend bug?
                        // Actually, let's just re-aggregate wins here.
                        if (bet.status && bet.status.toUpperCase() === 'WON') {
                            // Note: API returns aggregated wins. If we just += 1 here, we might double count if we started with API val.
                            // But since user says API returns 0 wins...
                            // Let's rely on our calc if API says 0.
                            if (calculatedBreakdown[type].wins === 0) {
                                // Just increment local counter (we need a separate tracker or assume 0 start)
                            }
                        }
                    });

                    // Better approach: Re-build breakdown completely from raw bets to guarantee accuracy
                    const freshBreakdown = {};
                    rawBets.forEach(bet => {
                        const type = bet.bet_type || 'Unknown';
                        if (!freshBreakdown[type]) {
                            freshBreakdown[type] = { bet_type: type, bets: 0, wins: 0, profit: 0, wager: 0 };
                        }
                        freshBreakdown[type].bets += 1;
                        freshBreakdown[type].profit += bet.profit;
                        freshBreakdown[type].wager += bet.wager;
                        if (bet.status && bet.status.toUpperCase() === 'WON') {
                            freshBreakdown[type].wins += 1;
                        }
                    });

                    // Convert to array and calc rates, filtering out financials
                    const finalBreakdown = Object.values(freshBreakdown)
                        .filter(item => item.bet_type !== 'Deposit' && item.bet_type !== 'Withdrawal' && item.bet_type !== 'Other')
                        .map(item => ({
                            ...item,
                            win_rate: item.bets > 0 ? (item.wins / item.bets * 100) : 0,
                            roi: item.wager > 0 ? (item.profit / item.wager * 100) : 0
                        })).sort((a, b) => b.profit - a.profit);

                    setBetTypeBreakdown(finalBreakdown);
                } else {
                    setBetTypeBreakdown(apiBetBreakdown);
                }

                setBalances(getVal(results[6], {}));
                setFinancials(getVal(results[7], { total_in_play: 0, total_deposited: 0, total_withdrawn: 0, realized_profit: 0 }));
                setTimeSeries(getVal(results[8], []));
                setDrawdown(getVal(results[9], { max_drawdown: 0.0, current_drawdown: 0.0, peak_profit: 0.0 }));
                setEdgeBreakdown(getVal(results[10], []));

                setPeriodStats({
                    '7d': getVal(periodResults[0], { net_profit: 0, roi: 0, wins: 0, losses: 0, total_bets: 0, actual_win_rate: 0, implied_win_rate: 0 }),
                    '30d': getVal(periodResults[1], { net_profit: 0, roi: 0, wins: 0, losses: 0, total_bets: 0, actual_win_rate: 0, implied_win_rate: 0 }),
                    'ytd': getVal(periodResults[2], { net_profit: 0, roi: 0, wins: 0, losses: 0, total_bets: 0, actual_win_rate: 0, implied_win_rate: 0 }),
                    'all': getVal(periodResults[3], { net_profit: 0, roi: 0, wins: 0, losses: 0, total_bets: 0, actual_win_rate: 0, implied_win_rate: 0 })
                });

            } catch (err) {
                console.error("API Error", err);
                setError(err.message || "Failed to load dashboard data.");
            }
        };
        fetchData();
    }, []);

    if (error) return (
        <div className="flex flex-col items-center justify-center min-h-screen text-red-500 bg-slate-950 p-6 text-center">
            <AlertCircle size={48} className="mb-4" />
            <h2 className="text-2xl font-bold mb-2">Connection Error</h2>
            <p className="text-gray-400 mb-6">{error}</p>
            <p className="text-sm text-gray-500 mb-6">
                Most common cause: Database not initialized.<br />
            </p>
            <div className="flex flex-wrap gap-4 justify-center">
                <button
                    onClick={() => {
                        const pass = prompt("Enter Basement Password:");
                        if (pass) {
                            localStorage.setItem('basement_password', pass);
                            window.location.reload();
                        }
                    }}
                    className="px-6 py-2 bg-slate-100 hover:bg-white text-slate-950 rounded-lg font-bold transition"
                >
                    Update Password
                </button>
                <button
                    onClick={() => {
                        api.get('/api/admin/init-db')
                            .then(() => alert("Database Initialized!"))
                            .catch(e => alert("Error: " + (e.response?.data?.message || e.message)));
                    }}
                    className="px-6 py-2 bg-blue-600 hover:bg-blue-500 rounded-lg text-white font-bold transition"
                >
                    Initialize Database
                </button>
                <button
                    onClick={() => window.location.reload()}
                    className="px-6 py-2 bg-slate-800 hover:bg-slate-700 rounded-lg text-white font-bold transition"
                >
                    Retry
                </button>
            </div>
        </div>
    );

    if (!stats) return <div className="min-h-screen flex items-center justify-center bg-slate-950 text-white font-mono animate-pulse">Loading Basement Bets...</div>;

    return (
        <ErrorBoundary>
            {/* <StagingBanner /> */}
            <div className="min-h-screen bg-slate-950 text-white p-8 font-sans selection:bg-green-500 selection:text-black">
                <div className="max-w-7xl mx-auto">
                    {/* Header */}
                    <header className="mb-8 flex justify-between items-center">
                        <div>
                            <div>
                                <h1 className="text-3xl font-bold bg-gradient-to-r from-green-400 to-blue-500 bg-clip-text text-transparent">
                                    Basement Bets
                                </h1>
                                <p className="text-gray-400">Your Historical Transaction Ledger</p>
                            </div>        </div>
                        <div className="flex gap-2">
                            <button
                                onClick={() => setView('summary')}
                                className={`px-4 py-2 rounded-lg flex items-center gap-2 transition-all ${view === 'summary' ? 'bg-green-500 text-black font-bold shadow-[0_0_15px_rgba(34,197,94,0.4)]' : 'bg-slate-800 hover:bg-slate-700'}`}
                            >
                                <LayoutDashboard size={18} /> Summary
                            </button>
                            <button
                                onClick={() => setView('transactions')}
                                className={`px-4 py-2 rounded-lg flex items-center gap-2 transition-all ${view === 'transactions' ? 'bg-green-500 text-black font-bold shadow-[0_0_15px_rgba(34,197,94,0.4)]' : 'bg-slate-800 hover:bg-slate-700'}`}
                            >
                                <List size={18} /> Transactions
                            </button>
                            <button
                                onClick={() => setView('research')}
                                className={`px-4 py-2 rounded-lg flex items-center gap-2 transition-all ${view === 'research' ? 'bg-purple-500 text-white font-bold shadow-[0_0_15px_rgba(168,85,247,0.4)]' : 'bg-slate-800 hover:bg-slate-700'}`}
                            >
                                <TrendingUp size={18} /> Research
                            </button>
                            <button
                                onClick={() => setView('performance')}
                                className={`px-4 py-2 rounded-lg flex items-center gap-2 transition-all ${view === 'performance' ? 'bg-blue-500 text-white font-bold shadow-[0_0_15px_rgba(59,130,246,0.4)]' : 'bg-slate-800 hover:bg-slate-700'}`}
                            >
                                <TrendingUp size={18} /> Performance
                            </button>
                            <button
                                onClick={handleSyncResults}
                                disabled={isSyncing}
                                className={`px-4 py-2 rounded-lg flex items-center gap-2 font-bold transition-all ${isSyncing ? 'bg-slate-800 text-gray-500 animate-pulse' : 'bg-slate-800 hover:bg-slate-700 text-blue-400'}`}
                            >
                                <RefreshCw size={18} className={isSyncing ? 'animate-spin' : ''} />
                                {isSyncing ? 'Syncing...' : 'Sync Scores'}
                            </button>
                            <button
                                onClick={async () => {
                                    if (confirm("Launch DraftKings Scraper?\n\nThis will open a Chrome window. Please log in if needed.")) {
                                        setIsSyncing(true);
                                        try {
                                            const res = await api.post('/api/sync/draftkings');
                                            alert(`Sync Complete!\nFound: ${res.data.bets_found} bets\nNew Saved: ${res.data.bets_saved}`);
                                            window.location.reload();
                                        } catch (e) {
                                            alert("Sync Failed: " + (e.response?.data?.detail || e.message));
                                        } finally {
                                            setIsSyncing(false);
                                        }
                                    }
                                }}
                                disabled={isSyncing}
                                className={`px-4 py-2 rounded-lg flex items-center gap-2 font-bold transition-all ${isSyncing ? 'bg-slate-800 text-gray-500' : 'bg-orange-600 hover:bg-orange-500 text-white shadow-[0_0_15px_rgba(249,115,22,0.4)]'}`}
                            >
                                <RefreshCw size={18} className={isSyncing ? 'animate-spin' : ''} />
                                Sync DK
                            </button>
                            <button
                                onClick={() => setShowAddBet(true)}
                                className="px-4 py-2 bg-green-600 hover:bg-green-500 rounded-lg flex items-center gap-2 font-bold transition-all shadow-[0_0_15px_rgba(34,197,94,0.3)]"
                            >
                                <PlusCircle size={18} /> Add Bet
                            </button>
                        </div>
                    </header>

                    {/* Content */}
                    {showAddBet && (
                        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200">
                            <div className="w-full max-w-2xl relative">
                                <PasteSlipContainer
                                    onSaveSuccess={() => {
                                        setShowAddBet(false);
                                        // Refresh data
                                        window.location.reload(); // Simple refresh for now
                                    }}
                                    onClose={() => setShowAddBet(false)}
                                />
                            </div>
                        </div>
                    )}

                    {view === 'summary' ? (
                        <SummaryView
                            stats={stats}
                            sportBreakdown={sportBreakdown}
                            playerBreakdown={playerBreakdown}
                            monthlyBreakdown={monthlyBreakdown}
                            timeSeries={timeSeries}
                            betTypeBreakdown={betTypeBreakdown}
                            balances={balances}
                            periodStats={periodStats}
                            financials={financials}
                            edgeBreakdown={edgeBreakdown}
                        />
                    ) : view === 'transactions' ? (
                        <TransactionView bets={bets} financials={financials} />
                    ) : view === 'performance' ? (
                        <PerformanceView timeSeries={timeSeries} drawdown={drawdown} financials={financials} />
                    ) : (
                        <Research />
                    )}
                </div>
            </div>
        </ErrorBoundary>
    );
}

function PerformanceView({ timeSeries, drawdown, financials }) {
    if (!timeSeries || timeSeries.length === 0) {
        return (
            <div className="bg-slate-900 border border-slate-800 p-10 rounded-xl text-center">
                <p className="text-gray-400">No performance data available yet. Settle some bets to see your equity curve!</p>
            </div>
        );
    }

    return (
        <div className="space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
            {/* Financial Overview */}
            <div className="flex flex-wrap gap-4 items-stretch">
                <FinancialHeader financials={financials} mode="performance" />
            </div>

            {/* Sportsbook Balance Summary Tiles */}
            {financials?.breakdown && (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
                    {financials.breakdown
                        .filter(prov => prov.provider === 'DraftKings' || prov.provider === 'FanDuel')
                        .map((prov) => (
                            <div key={prov.provider} className={`bg-slate-900 border rounded-xl p-5 ${prov.provider === 'DraftKings' ? 'border-orange-600/30' : 'border-blue-600/30'}`}>
                                <div className="flex items-center justify-between mb-3">
                                    <span className={`text-sm font-bold uppercase tracking-wider ${prov.provider === 'DraftKings' ? 'text-orange-400' : 'text-blue-400'}`}>
                                        {prov.provider}
                                    </span>
                                    <DollarSign className={`w-5 h-5 ${prov.provider === 'DraftKings' ? 'text-orange-400' : 'text-blue-400'}`} />
                                </div>
                                <div className="text-3xl font-bold text-white mb-1">
                                    {formatCurrency(prov.in_play || 0)}
                                </div>
                                <div className="text-xs text-gray-400">Current Balance</div>
                            </div>
                        ))}
                    {/* Total In Play Tile (Calculated) */}
                    {(() => {
                        const calculatedTotal = financials.breakdown
                            .filter(prov => prov.provider === 'DraftKings' || prov.provider === 'FanDuel')
                            .reduce((sum, p) => sum + (p.in_play || 0), 0);

                        return (
                            <div className="bg-slate-900 border border-green-600/30 rounded-xl p-5">
                                <div className="flex items-center justify-between mb-3">
                                    <span className="text-sm font-bold uppercase tracking-wider text-green-400">Total In Play</span>
                                    <Activity className="w-5 h-5 text-green-400" />
                                </div>
                                <div className="text-3xl font-bold text-white mb-1">
                                    {formatCurrency(calculatedTotal)}
                                </div>
                                <div className="text-xs text-gray-400">All Sportsbooks</div>
                            </div>
                        );
                    })()}
                </div>
            )}

            {/* Audit Message */}
            <div className="text-[10px] text-gray-600 text-center mb-8 uppercase tracking-widest opacity-50">
                Data Integrity Audit: Totals calculated from individual sportsbook balances.
            </div>

            {/* Provider Breakdown Table */}
            {
                financials?.breakdown && (
                    <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-xl mb-8 p-6">
                        <h3 className="text-xl font-bold mb-4 flex items-center gap-2">
                            <DollarSign className="text-green-400" /> Sportsbook Financials
                        </h3>
                        <table className="w-full text-left text-sm">
                            <thead>
                                <tr className="text-gray-400 border-b border-gray-700">
                                    <th className="pb-2">Sportsbook</th>
                                    <th className="pb-2 text-right">In Play</th>
                                    <th className="pb-2 text-right">Total Deposited</th>
                                    <th className="pb-2 text-right">Total Withdrawn</th>
                                    <th className="pb-2 text-right">Realized Profit</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-800">
                                {financials.breakdown.map((prov) => (
                                    <tr key={prov.provider} className="hover:bg-gray-800/30">
                                        <td className="py-3 font-bold text-white">{prov.provider}</td>
                                        <td className={`py-3 text-right font-bold ${(prov.in_play || 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                            {formatCurrency(prov.in_play || 0)}
                                        </td>
                                        <td className="py-3 text-right text-gray-400">{formatCurrency(prov.deposited)}</td>
                                        <td className="py-3 text-right text-gray-400">{formatCurrency(prov.withdrawn)}</td>
                                        <td className={`py-3 text-right font-bold ${prov.net_profit >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                            {formatCurrency(prov.net_profit)}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )
            }

            {/* Drawdown & Peak Metrics */}
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                <div className="bg-slate-900 border border-slate-800 p-6 rounded-xl backdrop-blur-sm">
                    <div className="text-gray-400 text-xs font-bold uppercase tracking-wider mb-1">Max Drawdown</div>
                    <div className="text-2xl font-bold text-red-400">{formatCurrency(drawdown?.max_drawdown || 0)}</div>
                </div>
                <div className="bg-slate-900 border border-slate-800 p-6 rounded-xl backdrop-blur-sm">
                    <div className="text-gray-400 text-xs font-bold uppercase tracking-wider mb-1">Current Drawdown</div>
                    <div className="text-2xl font-bold text-orange-400">{formatCurrency(drawdown?.current_drawdown || 0)}</div>
                </div>
                <div className="bg-slate-900 border border-slate-800 p-6 rounded-xl backdrop-blur-sm">
                    <div className="text-gray-400 text-xs font-bold uppercase tracking-wider mb-1">Peak Profit</div>
                    <div className="text-2xl font-bold text-green-400">{formatCurrency(drawdown?.peak_profit || 0)}</div>
                </div>
                <div className="bg-slate-900 border border-slate-800 p-6 rounded-xl backdrop-blur-sm">
                    <div className="text-gray-400 text-xs font-bold uppercase tracking-wider mb-1">Recovery</div>
                    <div className="text-2xl font-bold text-blue-400">{drawdown?.recovery_pct || 0}%</div>
                </div>
            </div>

            {/* Equity Curve Chart */}
            <div className="bg-slate-900 border border-slate-800 p-6 rounded-xl backdrop-blur-sm">
                <h3 className="text-xl font-bold mb-6 flex items-center gap-2">
                    <TrendingUp className="text-green-400" /> Bankroll Curve
                </h3>
                <div className="h-[400px] w-full">
                    <ResponsiveContainer width="100%" height="100%">
                        <LineChart data={timeSeries}>
                            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
                            <XAxis
                                dataKey="date"
                                stroke="#64748b"
                                fontSize={10}
                                tickLine={false}
                                axisLine={false}
                            />
                            <YAxis
                                stroke="#64748b"
                                fontSize={10}
                                tickLine={false}
                                axisLine={false}
                                tickFormatter={(val) => `$${val}`}
                            />
                            <Tooltip
                                contentStyle={{ backgroundColor: '#0f172a', border: '1px solid #1e293b', borderRadius: '8px' }}
                                itemStyle={{ color: '#22c55e', fontWeight: 'bold' }}
                                formatter={(val) => [formatCurrency(val), "Net Balance"]}
                            />
                            <Line
                                type="monotone"
                                dataKey="cumulative"
                                stroke="#22c55e"
                                strokeWidth={3}
                                dot={timeSeries.length < 50 ? { fill: '#22c55e', strokeWidth: 2, r: 4, stroke: '#0f172a' } : false}
                                activeDot={{ r: 6, strokeWidth: 0 }}
                                animationDuration={1500}
                            />
                        </LineChart>
                    </ResponsiveContainer>
                </div>
                <div className="mt-4 text-center text-xs text-gray-500">
                    Cumulative net balance over time including all bets and transactions.
                </div>
            </div>
        </div>
    );
}

const BankrollCard = ({ provider, data }) => (
    <div className="bg-slate-900 border border-slate-800 p-4 rounded-xl flex items-center justify-between min-w-[220px]">
        <div>
            <div className="text-gray-400 text-xs font-bold uppercase tracking-wider mb-0.5">{provider}</div>
            <div className={`text-xl font-bold ${data.balance >= 0 ? 'text-white' : 'text-red-400'}`}>
                {formatCurrency(data.balance)}
            </div>
            {data.last_bet && (
                <div className="text-[10px] text-gray-600 mt-1 font-mono">
                    Last: {data.last_bet}
                </div>
            )}
        </div>
        <div className={`p-2 rounded-full ${provider === 'DraftKings' ? 'bg-orange-900/20 text-orange-400' : 'bg-blue-900/20 text-blue-400'}`}>
            <DollarSign size={20} />
        </div>
    </div>
);

function SummaryView({ stats, sportBreakdown, playerBreakdown, monthlyBreakdown, timeSeries, betTypeBreakdown, edgeBreakdown, balances, periodStats, financials }) {
    const [sortConfig, setSortConfig] = useState({ key: 'edge', direction: 'desc' });

    // Sort sport breakdown by profit for chart
    const sortedSportBreakdown = [...sportBreakdown].sort((a, b) => b.profit - a.profit);

    // Sorting Logic for Edge Analysis
    const handleSort = (key) => {
        let direction = 'desc';
        if (sortConfig.key === key && sortConfig.direction === 'desc') {
            direction = 'asc';
        }
        setSortConfig({ key, direction });
    };

    const sortedEdgeBreakdown = [...edgeBreakdown].sort((a, b) => {
        if (a[sortConfig.key] < b[sortConfig.key]) {
            return sortConfig.direction === 'asc' ? -1 : 1;
        }
        if (a[sortConfig.key] > b[sortConfig.key]) {
            return sortConfig.direction === 'asc' ? 1 : -1;
        }
        return 0;
    });

    return (
        <div className="space-y-8">
            {/* Bankroll Section */}
            <div className="flex flex-wrap gap-4 items-stretch">
                {/* Clean Summary: No FinancialHeader here */}
                {Object.entries(balances)
                    .filter(([provider]) => provider && provider !== 'Barstool' && provider !== 'Other' && provider !== 'Total Net Profit')
                    .map(([provider, data]) => (
                        <BankrollCard key={provider} provider={provider} data={data} />
                    ))}

                {/* Total In Play Tile (Audited) */}
                {financials?.breakdown && (
                    <div className="bg-slate-900 border border-green-600/30 rounded-xl p-4 flex items-center justify-between min-w-[220px]">
                        <div>
                            <div className="text-gray-400 text-xs font-bold uppercase tracking-wider mb-0.5">Total In Play</div>
                            <div className="text-xl font-bold text-white">
                                {formatCurrency(
                                    financials.breakdown
                                        .filter(prov => prov.provider === 'DraftKings' || prov.provider === 'FanDuel')
                                        .reduce((sum, p) => sum + (p.in_play || 0), 0)
                                )}
                            </div>
                            <div className="text-[10px] text-gray-600 mt-1 font-mono">
                                Audit: Sum of DK + FD
                            </div>
                        </div>
                        <div className="p-2 rounded-full bg-green-900/20 text-green-400">
                            <Activity size={20} />
                        </div>
                    </div>
                )}
            </div>



            {/* Period Analytics (7d, 30d, YTD) */}
            <div>
                <h3 className="text-xl font-bold mb-4 flex items-center gap-2">
                    <TrendingUp className="text-green-400" /> Performance Windows
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    {['7d', '30d', 'ytd'].map(period => {
                        const data = periodStats[period];
                        if (!data) return null;
                        const label = period === 'ytd' ? 'Year to Date' : `Last ${period.replace('d', ' Days')}`;
                        return (
                            <div key={period} className="bg-slate-900/50 border border-slate-800 p-5 rounded-xl">
                                <div className="text-gray-400 text-xs font-bold uppercase mb-2">{label}</div>
                                <div className="flex justify-between items-end mb-2">
                                    <span className={`text-2xl font-bold ${data.net_profit >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                        {formatCurrency(data.net_profit)}
                                    </span>
                                    <span className={`text-sm font-bold ${data.roi >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                        {data.roi.toFixed(1)}% ROI
                                    </span>
                                </div>
                                <div className="text-xs text-gray-500 flex justify-between">
                                    <span>{data.wins}W - {data.losses}L</span>
                                    <span>{data.total_bets} Bets</span>
                                </div>
                            </div>
                        );
                    })}
                </div>
            </div>

            {/* Bet Performance Summary Table */}
            <div className="bg-slate-900/50 border border-slate-800 rounded-xl overflow-hidden p-6">
                <h3 className="text-xl font-bold mb-4">Bet Performance Summary</h3>
                <div className="overflow-x-auto">
                    <table className="w-full text-left text-sm">
                        <thead>
                            <tr className="text-gray-400 border-b border-slate-800 text-[10px] uppercase tracking-wider">
                                <th className="pb-3 pl-2">Period</th>
                                <th className="pb-3 text-right">Record</th>
                                <th className="pb-3 text-right">Implied WR</th>
                                <th className="pb-3 text-right">Actual WR</th>
                                <th className="pb-3 text-right pr-2">Edge</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-800/50">
                            {['7d', '30d', 'ytd', 'all'].map(p => {
                                const d = periodStats[p];
                                if (!d || d.total_bets === 0) return null;
                                const label = p === 'all' ? 'All Time' : p === 'ytd' ? 'Year to Date' : `Last ${p.replace('d', ' Days')}`;
                                const edge = d.actual_win_rate - d.implied_win_rate;
                                return (
                                    <tr key={p} className="hover:bg-slate-800/20">
                                        <td className="py-3 pl-2 font-medium text-white">{label}</td>
                                        <td className="py-3 text-right text-gray-400">
                                            {d.wins} - {d.losses} {(d.total_bets - d.wins - d.losses) > 0 ? `- ${d.total_bets - d.wins - d.losses} (P/V)` : ''}
                                        </td>
                                        <td className="py-3 text-right text-gray-400">
                                            {d.implied_win_rate.toFixed(1)}%
                                        </td>
                                        <td className={`py-3 text-right font-bold ${d.actual_win_rate >= d.implied_win_rate ? 'text-green-400' : 'text-gray-200'}`}>
                                            {d.actual_win_rate.toFixed(1)}%
                                        </td>
                                        <td className={`py-3 text-right pr-2 font-bold ${edge >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                            {edge > 0 ? '+' : ''}{edge.toFixed(1)}%
                                        </td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                </div>
            </div>

            {/* Charts Grid */}
            {/* Charts Grid */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {/* Total Money In Play (Daily) */}
                <div className="bg-slate-900/50 border border-slate-800 p-6 rounded-xl backdrop-blur-sm">
                    <h3 className="text-xl font-bold mb-4 flex items-center gap-2">
                        Total Money In Play
                    </h3>
                    <div className="h-[300px]">
                        <ResponsiveContainer width="100%" height="100%">
                            <LineChart data={timeSeries}>
                                <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                                <XAxis
                                    dataKey="date"
                                    stroke="#94a3b8"
                                    tickFormatter={(val) => new Date(val).toLocaleDateString([], { month: 'numeric', day: 'numeric' })}
                                    minTickGap={30}
                                />
                                <YAxis stroke="#94a3b8" />
                                <Tooltip
                                    contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b' }}
                                    itemStyle={{ color: '#fff' }}
                                    formatter={(value) => formatCurrency(value)}
                                    labelFormatter={(label) => new Date(label).toLocaleDateString([], { month: 'long', day: 'numeric', year: 'numeric' })}
                                />
                                <Line type="monotone" dataKey="balance" stroke="#3b82f6" strokeWidth={2} dot={false} activeDot={{ r: 6 }} name="Balance" />
                            </LineChart>
                        </ResponsiveContainer>
                    </div>
                </div>

                {/* Profit by Sport (Bar Chart) */}
                <div className="bg-slate-900/50 border border-slate-800 p-6 rounded-xl backdrop-blur-sm">
                    <h3 className="text-xl font-bold mb-4 flex items-center gap-2">
                        Profit by Sport
                    </h3>
                    <div className="h-[300px]">
                        <ResponsiveContainer width="100%" height="100%">
                            <BarChart data={sortedSportBreakdown}>
                                <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} />
                                <XAxis dataKey="sport" stroke="#94a3b8" fontSize={12} tickLine={false} axisLine={false} height={60} angle={-45} textAnchor="end" interval={0} />
                                <YAxis stroke="#94a3b8" fontSize={12} tickLine={false} axisLine={false} tickFormatter={(val) => `$${val}`} />
                                <Tooltip
                                    contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b' }}
                                    itemStyle={{ color: '#fff' }}
                                    formatter={(value) => formatCurrency(value)}
                                />
                                <Bar dataKey="profit" radius={[4, 4, 0, 0]}>
                                    {sortedSportBreakdown.map((entry, index) => (
                                        <Cell key={`cell-${index}`} fill={entry.profit >= 0 ? '#22c55e' : '#ef4444'} />
                                    ))}
                                </Bar>
                            </BarChart>
                        </ResponsiveContainer>
                    </div>
                </div>
            </div>

            {/* Advanced Edge Analysis Segment */}
            <div className="bg-slate-900/50 border border-slate-800 p-6 rounded-xl backdrop-blur-sm mt-8">
                <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-6">
                    <h3 className="text-xl font-bold flex items-center gap-2">
                        <BarChart3 className="text-blue-400" /> Integrated Edge Analysis
                    </h3>

                    {edgeBreakdown.length > 0 && (
                        <div className="flex flex-wrap gap-4 text-xs">
                            {(() => {
                                const total = edgeBreakdown.reduce((s, i) => s + i.bets, 0);
                                const wins = edgeBreakdown.reduce((s, i) => s + i.wins, 0);
                                const profit = edgeBreakdown.reduce((s, i) => s + i.profit, 0);
                                const impliedSum = edgeBreakdown.reduce((s, i) => s + (i.implied_win_rate * i.bets), 0);
                                const avgImplied = total > 0 ? impliedSum / total : 0;
                                const avgActual = total > 0 ? (wins / total) * 100 : 0;

                                return (
                                    <>
                                        <div className="bg-slate-800/50 px-3 py-1.5 rounded-lg border border-slate-700">
                                            <span className="text-slate-400">Total Bets: </span>
                                            <span className="text-white font-bold">{total}</span>
                                            <span className="text-slate-500 ml-2">({wins}W - {total - wins}L)</span>
                                        </div>
                                        <div className="bg-slate-800/50 px-3 py-1.5 rounded-lg border border-slate-700">
                                            <span className="text-slate-400">Actual WR: </span>
                                            <span className="text-white font-bold">{avgActual.toFixed(1)}%</span>
                                        </div>
                                        <div className="bg-slate-800/50 px-3 py-1.5 rounded-lg border border-slate-700">
                                            <span className="text-slate-400">Implied WR: </span>
                                            <span className="text-white font-bold">{avgImplied.toFixed(1)}%</span>
                                        </div>
                                        <div className="bg-slate-800/50 px-3 py-1.5 rounded-lg border border-slate-700">
                                            <span className="text-slate-400">Total P/L: </span>
                                            <span className={profit >= 0 ? 'text-green-400 font-bold' : 'text-red-400 font-bold'}>
                                                {formatCurrency(profit)}
                                            </span>
                                        </div>
                                    </>
                                );
                            })()}
                        </div>
                    )}
                </div>

                {/* Weighted Performance Visualization */}
                <div className="h-[400px] mb-8 bg-slate-800/20 rounded-xl border border-slate-800/50 p-4">
                    <ResponsiveContainer width="100%" height="100%">
                        <ScatterChart margin={{ top: 20, right: 20, bottom: 20, left: 20 }}>
                            <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                            <XAxis
                                type="number"
                                dataKey="profit"
                                name="Profit"
                                unit="$"
                                stroke="#94a3b8"
                                fontSize={10}
                                domain={['auto', 'auto']}
                                label={{ value: 'Profit', position: 'bottom', fill: '#64748b', fontSize: 10 }}
                                tickFormatter={(val) => `$${val}`}
                            />
                            <YAxis
                                type="number"
                                dataKey="actual_win_rate"
                                name="Actual Win Rate"
                                unit="%"
                                stroke="#94a3b8"
                                fontSize={10}
                                domain={[0, 100]}
                                label={{ value: 'Your Performance (Actual WR)', angle: -90, position: 'left', fill: '#64748b', fontSize: 10 }}
                            />
                            <ZAxis type="number" dataKey="bets" range={[50, 400]} name="Volume" />
                            <Tooltip
                                cursor={{ strokeDasharray: '3 3' }}
                                contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b', borderRadius: '8px' }}
                                itemStyle={{ color: '#fff' }}
                                content={({ active, payload }) => {
                                    if (active && payload && payload.length) {
                                        const data = payload[0].payload;
                                        return (
                                            <div className="bg-slate-900 border border-slate-700 p-3 rounded-lg shadow-xl">
                                                <p className="font-bold text-blue-400 mb-1">{data.sport} - {data.bet_type}</p>
                                                <div className="grid grid-cols-2 gap-x-4 text-[10px]">
                                                    <span className="text-slate-400">Bets:</span> <span className="text-white text-right">{data.bets}</span>
                                                    <span className="text-slate-400">Profit:</span> <span className={data.profit >= 0 ? 'text-green-400 text-right' : 'text-red-400 text-right'}>{formatCurrency(data.profit)}</span>
                                                    <span className="text-slate-400">Actual WR:</span> <span className="text-white text-right">{data.actual_win_rate}%</span>
                                                    <span className="text-slate-400">Implied WR:</span> <span className="text-white text-right">{data.implied_win_rate}%</span>
                                                    <span className="text-slate-400">Edge:</span> <span className={data.edge >= 0 ? 'text-green-400 text-right' : 'text-red-400 text-right'}>{data.edge > 0 ? '+' : ''}{data.edge}%</span>
                                                </div>
                                            </div>
                                        );
                                    }
                                    return null;
                                }}
                            />
                            {/* Profit/Loss Reference Line */}
                            <ReferenceLine x={0} stroke="#475569" strokeWidth={1} />

                            <Scatter name="Segments" data={edgeBreakdown}>
                                {edgeBreakdown.map((entry, index) => (
                                    <Cell key={`cell-${index}`} fill={entry.profit >= 0 ? '#10b981' : '#ef4444'} fillOpacity={0.6} stroke={entry.profit >= 0 ? '#10b981' : '#ef4444'} />
                                ))}
                            </Scatter>
                        </ScatterChart>
                    </ResponsiveContainer>
                    <div className="text-[10px] text-slate-500 text-center mt-2 italic">
                        Segments plotted by Profit (X) and Actual Win Rate (Y). Bubble size represents bet volume.
                    </div>
                </div>

                <div className="overflow-x-auto">
                    <table className="w-full text-left text-sm">
                        <thead className="text-slate-400 border-b border-slate-700 text-[10px] uppercase tracking-wider">
                            <tr>
                                <th
                                    className="pb-3 pl-2 cursor-pointer hover:text-white transition-colors"
                                    onClick={() => handleSort('sport')}
                                >
                                    Segment {sortConfig.key === 'sport' ? (sortConfig.direction === 'asc' ? '↑' : '↓') : ''}
                                </th>
                                <th
                                    className="pb-3 text-right cursor-pointer hover:text-white transition-colors"
                                    onClick={() => handleSort('bets')}
                                >
                                    Volume {sortConfig.key === 'bets' ? (sortConfig.direction === 'asc' ? '↑' : '↓') : ''}
                                </th>
                                <th
                                    className="pb-3 text-right cursor-pointer hover:text-white transition-colors"
                                    onClick={() => handleSort('profit')}
                                >
                                    Profit {sortConfig.key === 'profit' ? (sortConfig.direction === 'asc' ? '↑' : '↓') : ''}
                                </th>
                                <th
                                    className="pb-3 text-right cursor-pointer hover:text-white transition-colors"
                                    onClick={() => handleSort('roi')}
                                >
                                    ROI {sortConfig.key === 'roi' ? (sortConfig.direction === 'asc' ? '↑' : '↓') : ''}
                                </th>
                                <th
                                    className="pb-3 text-right pr-2 cursor-pointer hover:text-white transition-colors"
                                    onClick={() => handleSort('edge')}
                                >
                                    Edge vs Market {sortConfig.key === 'edge' ? (sortConfig.direction === 'asc' ? '↑' : '↓') : ''}
                                </th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-800/50">
                            {sortedEdgeBreakdown.map((item, idx) => {
                                const isPositive = item.edge >= 0;
                                return (
                                    <tr key={idx} className="hover:bg-slate-800/20 transition-colors group">
                                        <td className="py-3 pl-2">
                                            <div className="flex flex-col">
                                                <span className="font-bold text-slate-200">{item.sport}</span>
                                                <span className="text-xs text-slate-500">{item.bet_type}</span>
                                            </div>
                                        </td>
                                        <td className="py-3 text-right text-slate-400 font-mono">
                                            {item.bets} <span className="text-[10px] text-slate-600">bets</span>
                                        </td>
                                        <td className={`py-3 text-right font-bold ${item.profit >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                            {formatCurrency(item.profit)}
                                        </td>
                                        <td className={`py-3 text-right font-medium ${item.roi >= 0 ? 'text-slate-300' : 'text-red-400/80'}`}>
                                            {item.roi > 0 ? '+' : ''}{item.roi.toFixed(1)}%
                                        </td>
                                        <td className={`py-3 text-right pr-2 font-bold ${isPositive ? 'text-emerald-400' : 'text-rose-400'}`}>
                                            <div className="flex items-center justify-end gap-1 font-mono">
                                                <span>{item.edge > 0 ? '+' : ''}{item.edge.toFixed(1)}%</span>
                                                {isPositive ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
                                            </div>
                                        </td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                </div>
                <div className="mt-4 p-3 bg-blue-900/10 border border-blue-900/20 rounded-lg text-[11px] text-blue-300 leading-relaxed">
                    <strong>How to read this:</strong> We compare your actual win percentage for each (Sport + Bet Type) combination against the market's implied expectations.
                    Segments with high <strong>positive edge</strong> are where you consistently find value. Focus your bankroll on these green zones.
                </div>
            </div>



            {/* Live Odds Section (Full Width) */}
            <div className="bg-slate-900/50 border border-slate-800 p-6 rounded-xl backdrop-blur-sm">
                <div className="flex justify-between items-center mb-4">
                    <h3 className="text-xl font-bold flex items-center gap-2">
                        Live Odds (NFL)
                    </h3>
                    <span className="text-xs text-green-400 bg-green-900/30 border border-green-800 px-2 py-1 rounded">Live Data Active</span>
                </div>
                <OddsTicker />
            </div>
        </div >
    );
}

function OddsTicker() {
    const [odds, setOdds] = useState([]);

    useEffect(() => {
        api.get('/api/odds/NFL')
            .then(res => {
                if (Array.isArray(res.data)) {
                    setOdds(res.data);
                } else {
                    console.warn("Odds API returned non-array:", res.data);
                    setOdds([]);
                }
            })
            .catch(err => {
                console.error("Odds API Error:", err);
                setOdds([]);
            });
    }, []);

    if (!Array.isArray(odds) || odds.length === 0) return <div className="text-gray-400 text-sm">Loading Live Odds (or no live games)...</div>;

    return (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            {odds.slice(0, 4).map((game) => {
                // Safe access
                const book = game.bookmakers?.[0];
                const market = book?.markets?.[0];
                if (!market) return null;

                const home = market.outcomes.find(o => o.name === game.home_team);
                const away = market.outcomes.find(o => o.name === game.away_team);

                return (
                    <div key={game.id} className="bg-slate-800 p-3 rounded-lg border border-slate-700 text-sm">
                        <div className="flex justify-between items-center mb-2">
                            <span className="text-xs text-blue-400 font-bold uppercase">{game.sport_key.replace('americanfootball_', '')}</span>
                            <span className="text-[10px] text-gray-500">FanDuel</span>
                        </div>
                        <div className="flex justify-between items-center mb-1">
                            <span className="font-medium text-gray-300">{game.away_team}</span>
                            <span className="font-mono text-green-400">{away?.price}</span>
                        </div>
                        <div className="flex justify-between items-center">
                            <span className="font-medium text-gray-300">{game.home_team}</span>
                            <span className="font-mono text-green-400">{home?.price}</span>
                        </div>
                    </div>
                );
            })}
        </div>
    );
}

function TransactionView({ bets, financials }) {
    const [filters, setFilters] = useState({
        date: "",
        sportsbook: "All",
        sport: "All",
        type: "All",
        selection: "",
        status: "All"
    });

    const [showManualAdd, setShowManualAdd] = useState(false);
    const [manualBet, setManualBet] = useState({
        sportsbook: "DraftKings",
        sport: "NFL",
        market_type: "Straight",
        event_name: "",
        selection: "",
        odds: "",
        stake: "",
        status: "LOST",
        placed_at: new Date().toISOString().slice(0, 10)
    });

    // Extract unique options for dropdowns - keep "All" at top
    const sportsbooks = ["All", ...[...new Set(bets.map(b => b.provider).filter(Boolean))].sort()];
    const sports = ["All", ...[...new Set(bets.map(b => b.sport).filter(Boolean))].sort()];
    const types = ["All", ...[...new Set(bets.map(b => b.bet_type).filter(Boolean))].sort()];
    const [sortConfig, setSortConfig] = useState({ key: 'date', direction: 'descending' });
    const [error, setError] = useState(null);
    const [isUpdating, setIsUpdating] = useState(false);

    const requestSort = (key) => {
        let direction = 'ascending';
        if (sortConfig.key === key && sortConfig.direction === 'ascending') {
            direction = 'descending';
        }
        setSortConfig({ key, direction });
    };

    const getSortIcon = (name) => {
        if (sortConfig.key !== name) return <div className="w-3 h-3 inline-block ml-1 opacity-20">↕</div>;
        return sortConfig.direction === 'ascending' ?
            <div className="w-3 h-3 inline-block ml-1">↑</div> :
            <div className="w-3 h-3 inline-block ml-1">↓</div>;
    };

    const handleSettle = async (betId, status) => {
        setIsUpdating(true);
        try {
            await api.patch(`/api/bets/${betId}/settle`, { status });
            // For now, reload to get fresh stats
            window.location.reload();
        } catch (err) {
            console.error("Settle Error:", err);
            alert("Failed to settle bet.");
        } finally {
            setIsUpdating(false);
        }
    };

    const handleDelete = async (betId) => {
        if (!confirm("Are you sure you want to delete this bet?")) return;
        setIsUpdating(true);
        try {
            await api.delete(`/api/bets/${betId}`);
            window.location.reload();
        } catch (err) {
            console.error("Delete Error:", err);
            alert("Failed to delete bet.");
        } finally {
            setIsUpdating(false);
        }
    };

    const submitManualBet = async () => {
        setIsUpdating(true);
        try {
            const american = manualBet.odds ? parseInt(manualBet.odds, 10) : null;
            const stake = manualBet.stake ? parseFloat(manualBet.stake) : 0;

            await api.post('/api/bets/manual', {
                sportsbook: manualBet.sportsbook,
                sport: manualBet.sport,
                market_type: manualBet.market_type,
                event_name: manualBet.event_name,
                selection: manualBet.selection,
                price: { american },
                stake,
                status: manualBet.status,
                placed_at: manualBet.placed_at,
                raw_text: 'manual-ui'
            });

            setShowManualAdd(false);
            setManualBet({
                sportsbook: manualBet.sportsbook,
                sport: manualBet.sport,
                market_type: manualBet.market_type,
                event_name: "",
                selection: "",
                odds: "",
                stake: "",
                status: manualBet.status,
                placed_at: new Date().toISOString().slice(0, 10)
            });
            window.location.reload();
        } catch (err) {
            console.error('Manual bet save failed', err);
            alert('Failed to add bet. Check required fields.');
        } finally {
            setIsUpdating(false);
        }
    };

    const statuses = ['All', 'PENDING', 'WON', 'LOST', 'PUSH'];
    const filtered = bets.filter(b => {
        // Filter out internal Wallet Transfers
        if ((b.description || "").toLowerCase().includes("wallet transfer")) return false;

        const matchDate = b.date.includes(filters.date);
        const matchSportsbook = filters.sportsbook === "All" || b.provider === filters.sportsbook;
        const matchSport = filters.sport === "All" || b.sport === filters.sport;
        const matchType = filters.type === "All" || b.bet_type === filters.type;
        const matchSelection = (b.selection || b.description || "").toLowerCase().includes(filters.selection.toLowerCase());
        const matchStatus = filters.status === "All" || b.status === filters.status;
        return matchDate && matchSportsbook && matchSport && matchType && matchSelection && matchStatus;
    });

    const sortedBets = React.useMemo(() => {
        let sortableItems = [...filtered];
        if (sortConfig.key !== null) {
            sortableItems.sort((a, b) => {
                let aValue = a[sortConfig.key];
                let bValue = b[sortConfig.key];

                // Special handling for date: use sort_date for proper chronological sort
                if (sortConfig.key === 'date') {
                    aValue = a.sort_date || a.date || "";
                    bValue = b.sort_date || b.date || "";
                }

                // Special handling for selection fallback
                if (sortConfig.key === 'selection') {
                    aValue = a.selection || a.description || "";
                    bValue = b.selection || b.description || "";
                }

                // Handle string comparisons
                if (typeof aValue === 'string') aValue = aValue.toLowerCase();
                if (typeof bValue === 'string') bValue = bValue.toLowerCase();

                // Handle null/undefined (push to bottom usually, or top? let's standardise)
                if (aValue === null || aValue === undefined) return 1;
                if (bValue === null || bValue === undefined) return -1;

                if (aValue < bValue) {
                    return sortConfig.direction === 'ascending' ? -1 : 1;
                }
                if (aValue > bValue) {
                    return sortConfig.direction === 'ascending' ? 1 : -1;
                }
                return 0;
            });
        }
        return sortableItems;
    }, [filtered, sortConfig]);

    const resetFilters = () => setFilters({ date: "", sportsbook: "All", sport: "All", type: "All", selection: "", status: "All" });

    return (
        <div className="space-y-8">
            {showManualAdd && (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
                    <div className="w-full max-w-2xl bg-slate-900 border border-slate-700 rounded-xl shadow-2xl p-5">
                        <div className="flex items-center justify-between mb-4">
                            <div className="text-white font-bold">Add Bet (Manual)</div>
                            <button type="button" className="text-gray-400 hover:text-white" onClick={() => setShowManualAdd(false)}>✕</button>
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                            <div>
                                <label className="text-xs text-gray-400">Sportsbook</label>
                                <select className="w-full bg-slate-950 border border-slate-700 rounded px-2 py-2 text-sm text-white"
                                    value={manualBet.sportsbook}
                                    onChange={e => setManualBet({ ...manualBet, sportsbook: e.target.value })}
                                >
                                    <option>DraftKings</option>
                                    <option>FanDuel</option>
                                </select>
                            </div>
                            <div>
                                <label className="text-xs text-gray-400">Date (YYYY-MM-DD)</label>
                                <input className="w-full bg-slate-950 border border-slate-700 rounded px-2 py-2 text-sm text-white"
                                    value={manualBet.placed_at}
                                    onChange={e => setManualBet({ ...manualBet, placed_at: e.target.value })}
                                />
                            </div>
                            <div>
                                <label className="text-xs text-gray-400">Sport</label>
                                <input className="w-full bg-slate-950 border border-slate-700 rounded px-2 py-2 text-sm text-white"
                                    placeholder="NFL, NBA, NCAAM..."
                                    value={manualBet.sport}
                                    onChange={e => setManualBet({ ...manualBet, sport: e.target.value })}
                                />
                            </div>
                            <div>
                                <label className="text-xs text-gray-400">Type</label>
                                <input className="w-full bg-slate-950 border border-slate-700 rounded px-2 py-2 text-sm text-white"
                                    placeholder="Straight, SGP, Parlay..."
                                    value={manualBet.market_type}
                                    onChange={e => setManualBet({ ...manualBet, market_type: e.target.value })}
                                />
                            </div>
                            <div className="md:col-span-2">
                                <label className="text-xs text-gray-400">Event / Game</label>
                                <input className="w-full bg-slate-950 border border-slate-700 rounded px-2 py-2 text-sm text-white"
                                    placeholder="e.g., Patriots vs Broncos"
                                    value={manualBet.event_name}
                                    onChange={e => setManualBet({ ...manualBet, event_name: e.target.value })}
                                />
                            </div>
                            <div className="md:col-span-2">
                                <label className="text-xs text-gray-400">Selection</label>
                                <input className="w-full bg-slate-950 border border-slate-700 rounded px-2 py-2 text-sm text-white"
                                    placeholder="e.g., Under 28.5"
                                    value={manualBet.selection}
                                    onChange={e => setManualBet({ ...manualBet, selection: e.target.value })}
                                />
                            </div>
                            <div>
                                <label className="text-xs text-gray-400">Odds (American)</label>
                                <input className="w-full bg-slate-950 border border-slate-700 rounded px-2 py-2 text-sm text-white"
                                    placeholder="e.g., -110 or 254"
                                    value={manualBet.odds}
                                    onChange={e => setManualBet({ ...manualBet, odds: e.target.value })}
                                />
                            </div>
                            <div>
                                <label className="text-xs text-gray-400">Wager ($)</label>
                                <input className="w-full bg-slate-950 border border-slate-700 rounded px-2 py-2 text-sm text-white"
                                    placeholder="e.g., 10"
                                    value={manualBet.stake}
                                    onChange={e => setManualBet({ ...manualBet, stake: e.target.value })}
                                />
                            </div>
                            <div>
                                <label className="text-xs text-gray-400">Status</label>
                                <select className="w-full bg-slate-950 border border-slate-700 rounded px-2 py-2 text-sm text-white"
                                    value={manualBet.status}
                                    onChange={e => setManualBet({ ...manualBet, status: e.target.value })}
                                >
                                    <option value="WON">WON</option>
                                    <option value="LOST">LOST</option>
                                    <option value="PENDING">PENDING</option>
                                    <option value="PUSH">PUSH</option>
                                </select>
                            </div>
                            <div className="md:col-span-1 flex items-end justify-end gap-2">
                                <button
                                    type="button"
                                    className="px-3 py-2 rounded-lg border border-slate-700 text-gray-200 hover:bg-slate-800"
                                    onClick={() => setShowManualAdd(false)}
                                >
                                    Cancel
                                </button>
                                <button
                                    type="button"
                                    className="px-3 py-2 rounded-lg bg-green-600 hover:bg-green-500 text-white font-bold"
                                    onClick={submitManualBet}
                                    disabled={isUpdating}
                                >
                                    Save
                                </button>
                            </div>
                        </div>

                        <div className="mt-3 text-[11px] text-gray-500">
                            This creates a bet row directly in your Transactions table (manual tracking).
                        </div>
                    </div>
                </div>
            )}
            {/* Sportsbook Balance Summary Tiles */}
            {financials?.breakdown && (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
                    {financials.breakdown
                        .filter(prov => prov.provider === 'DraftKings' || prov.provider === 'FanDuel')
                        .map((prov) => (
                            <div key={prov.provider} className={`bg-slate-900 border rounded-xl p-5 ${prov.provider === 'DraftKings' ? 'border-orange-600/30' : 'border-blue-600/30'}`}>
                                <div className="flex items-center justify-between mb-3">
                                    <span className={`text-sm font-bold uppercase tracking-wider ${prov.provider === 'DraftKings' ? 'text-orange-400' : 'text-blue-400'}`}>
                                        {prov.provider}
                                    </span>
                                    <DollarSign className={`w-5 h-5 ${prov.provider === 'DraftKings' ? 'text-orange-400' : 'text-blue-400'}`} />
                                </div>
                                <div className="text-3xl font-bold text-white mb-1">
                                    {formatCurrency(prov.in_play || 0)}
                                </div>
                                <div className="text-xs text-gray-400">Current Balance</div>
                            </div>
                        ))}
                    {/* Total In Play Tile (Calculated) */}
                    {(() => {
                        const calculatedTotal = financials.breakdown
                            .filter(prov => prov.provider === 'DraftKings' || prov.provider === 'FanDuel')
                            .reduce((sum, p) => sum + (p.in_play || 0), 0);

                        return (
                            <div className="bg-slate-900 border border-green-600/30 rounded-xl p-5">
                                <div className="flex items-center justify-between mb-3">
                                    <span className="text-sm font-bold uppercase tracking-wider text-green-400">Total In Play</span>
                                    <Activity className="w-5 h-5 text-green-400" />
                                </div>
                                <div className="text-3xl font-bold text-white mb-1">
                                    {formatCurrency(calculatedTotal)}
                                </div>
                                <div className="text-xs text-gray-400">All Sportsbooks</div>
                            </div>
                        );
                    })()}
                </div>
            )}




            <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden shadow-xl">
                {/* Toolbar / Summary */}
                <div className="p-4 border-b border-gray-800 flex justify-between items-center bg-gray-900/50 backdrop-blur">
                    <div className="text-gray-400 text-sm">
                        Showing <span className="text-white font-bold">{filtered.length}</span> of {bets.length} transactions
                    </div>
                    <div className="flex items-center gap-2">
                        <button
                            onClick={() => setShowManualAdd(true)}
                            className="text-xs text-green-300 hover:text-green-200 font-medium px-3 py-1.5 rounded-lg border border-green-900/40 hover:bg-green-900/20 transition"
                        >
                            + Add Bet
                        </button>
                        <button
                            onClick={resetFilters}
                            className="text-xs text-blue-400 hover:text-blue-300 font-medium px-3 py-1.5 rounded-lg border border-blue-900/30 hover:bg-blue-900/20 transition"
                        >
                            Clear Filters
                        </button>
                    </div>
                </div>

                {/* Grid */}
                <div className="overflow-x-auto">
                    <table className="w-full text-left text-sm whitespace-nowrap">
                        <thead className="bg-gray-800 text-gray-400 font-medium uppercase text-xs tracking-wider">
                            {/* Header Labels */}
                            <tr>
                                <th
                                    className="px-6 py-3 border-b border-gray-700 cursor-pointer hover:bg-gray-800 select-none"
                                    onClick={() => requestSort('date')}
                                >
                                    Date {getSortIcon('date')}
                                </th>
                                <th
                                    className="px-6 py-3 border-b border-gray-700 cursor-pointer hover:bg-gray-800 select-none"
                                    onClick={() => requestSort('provider')}
                                >
                                    Sportsbook {getSortIcon('provider')}
                                </th>
                                <th
                                    className="px-6 py-3 border-b border-gray-700 cursor-pointer hover:bg-gray-800 select-none"
                                    onClick={() => requestSort('sport')}
                                >
                                    Sport {getSortIcon('sport')}
                                </th>
                                <th
                                    className="px-6 py-3 border-b border-gray-700 cursor-pointer hover:bg-gray-800 select-none"
                                    onClick={() => requestSort('bet_type')}
                                >
                                    Type {getSortIcon('bet_type')}
                                </th>
                                <th
                                    className="px-6 py-3 border-b border-gray-700 cursor-pointer hover:bg-gray-800 select-none"
                                    onClick={() => requestSort('selection')}
                                >
                                    Selection {getSortIcon('selection')}
                                </th>
                                <th
                                    className="px-6 py-3 border-b border-gray-700 text-right cursor-pointer hover:bg-gray-800 select-none"
                                    onClick={() => requestSort('odds')}
                                >
                                    Odds {getSortIcon('odds')}
                                </th>
                                <th
                                    className="px-6 py-3 border-b border-gray-700 text-right cursor-pointer hover:bg-gray-800 select-none"
                                    onClick={() => requestSort('wager')}
                                >
                                    Wager {getSortIcon('wager')}
                                </th>
                                <th
                                    className="px-6 py-3 border-b border-gray-700 text-center cursor-pointer hover:bg-gray-800 select-none"
                                    onClick={() => requestSort('status')}
                                >
                                    Status {getSortIcon('status')}
                                </th>
                                <th
                                    className="px-6 py-3 border-b border-gray-700 text-right cursor-pointer hover:bg-gray-800 select-none"
                                    onClick={() => requestSort('profit')}
                                >
                                    Profit / Loss {getSortIcon('profit')}
                                </th>
                                <th className="px-6 py-3 border-b border-gray-700 text-right">Actions</th>
                            </tr>
                            {/* Filter Row */}
                            <tr className="bg-gray-850">
                                <th className="px-2 py-2">
                                    <input
                                        type="text"
                                        placeholder="Filter Date..."
                                        className="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-xs text-white focus:border-blue-500 outline-none"
                                        value={filters.date}
                                        onChange={e => setFilters({ ...filters, date: e.target.value })}
                                    />
                                </th>
                                <th className="px-2 py-2">
                                    <select
                                        className="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-xs text-white focus:border-blue-500 outline-none"
                                        value={filters.sportsbook}
                                        onChange={e => setFilters({ ...filters, sportsbook: e.target.value })}
                                    >
                                        <option value="All">All Books</option>
                                        {sportsbooks.filter(s => s !== 'All').map(s => <option key={s} value={s}>{s}</option>)}
                                    </select>
                                </th>
                                <th className="px-2 py-2">
                                    <select
                                        className="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-xs text-white focus:border-blue-500 outline-none"
                                        value={filters.sport}
                                        onChange={e => setFilters({ ...filters, sport: e.target.value })}
                                    >
                                        <option value="All">All Sports</option>
                                        {sports.filter(s => s !== 'All').map(s => <option key={s} value={s}>{s}</option>)}
                                    </select>
                                </th>
                                <th className="px-2 py-2">
                                    <select
                                        className="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-xs text-white focus:border-blue-500 outline-none"
                                        value={filters.type}
                                        onChange={e => setFilters({ ...filters, type: e.target.value })}
                                    >
                                        {types.map(t => <option key={t} value={t}>{t}</option>)}
                                    </select>
                                </th>
                                <th className="px-2 py-2">
                                    <input
                                        type="text"
                                        placeholder="Search Selection..."
                                        className="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-xs text-white focus:border-blue-500 outline-none"
                                        value={filters.selection}
                                        onChange={e => setFilters({ ...filters, selection: e.target.value })}
                                    />
                                </th>
                                <th className="px-2 py-2"></th> {/* Odds */}
                                <th className="px-2 py-2"></th> {/* Wager */}
                                <th className="px-2 py-2">
                                    <select
                                        className="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-xs text-white focus:border-blue-500 outline-none"
                                        value={filters.status}
                                        onChange={e => setFilters({ ...filters, status: e.target.value })}
                                    >
                                        {statuses.map(s => <option key={s} value={s}>{s}</option>)}
                                    </select>
                                </th>
                                <th className="px-2 py-2"></th> {/* Profit */}
                                <th className="px-2 py-2"></th> {/* Actions */}
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-800">
                            {sortedBets.map((bet) => {
                                const isTxn = bet.category === 'Transaction';
                                const isDeposit = bet.bet_type === 'Deposit' || (bet.bet_type === 'Other' && bet.amount > 0);
                                return (
                                    <tr key={bet.id || bet.txn_id} className="hover:bg-gray-800/50 transition duration-150">
                                        <td className="px-6 py-3 text-gray-300 font-mono text-xs">{bet.date}</td>
                                        <td className="px-6 py-3">
                                            <span className="px-2 py-1 rounded text-[10px] text-gray-300 border border-gray-700 bg-gray-800 shadow-sm uppercase font-bold tracking-wider">
                                                {bet.provider}
                                            </span>
                                        </td>
                                        <td className="px-6 py-3">
                                            <span className="px-2 py-1 rounded text-[10px] text-gray-300 border border-gray-700 bg-gray-800 shadow-sm uppercase font-bold tracking-wider">
                                                {bet.sport}
                                            </span>
                                        </td>
                                        <td className="px-6 py-3 text-gray-400 text-xs">{bet.bet_type}</td>
                                        <td className="px-6 py-3 max-w-xs truncate text-gray-300 text-xs" title={bet.selection || bet.description}>
                                            {bet.selection || bet.description}
                                            {bet.is_live && <span className="ml-2 text-[9px] bg-red-900/50 text-red-300 px-1 rounded border border-red-800">LIVE</span>}
                                            {bet.is_bonus && <span className="ml-2 text-[9px] bg-yellow-900/50 text-yellow-300 px-1 rounded border border-yellow-800">BONUS</span>}
                                        </td>
                                        <td className="px-6 py-3 text-right font-mono text-gray-400 text-xs">
                                            {!isTxn ? (
                                                <>
                                                    {bet.odds ? (bet.odds > 0 ? `+${bet.odds}` : bet.odds) : '-'}
                                                    {bet.closing_odds && (
                                                        <div className="flex flex-col items-end mt-1">
                                                            <span className="text-[10px] text-gray-500 font-mono">
                                                                CL: {bet.closing_odds > 0 ? '+' : ''}{bet.closing_odds}
                                                            </span>
                                                            <span className={`text-[10px] font-bold ${calculateCLV(bet.odds, bet.closing_odds) > 0 ? 'text-green-400' : 'text-red-400'
                                                                }`}>
                                                                {calculateCLV(bet.odds, bet.closing_odds) > 0 ? '+' : ''}{calculateCLV(bet.odds, bet.closing_odds).toFixed(1)}% CLV
                                                            </span>
                                                        </div>
                                                    )}
                                                </>
                                            ) : '-'}
                                        </td>
                                        <td className={`px-6 py-3 text-right font-medium text-xs ${isTxn ? 'text-gray-400' : 'text-gray-300'}`}>
                                            {formatCurrency(bet.wager)}
                                        </td>
                                        <td className="px-6 py-3 text-center">
                                            <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider border ${isTxn ? (isDeposit ? 'bg-green-900/20 text-green-400 border-green-900' : 'bg-gray-800 text-gray-400 border-gray-700') :
                                                ['WON', 'WIN'].includes(bet.status) ? 'bg-green-900/20 text-green-400 border-green-900' :
                                                    ['LOST', 'LOSE'].includes(bet.status) ? 'bg-red-900/20 text-red-400 border-red-900' :
                                                        'bg-gray-800 text-gray-400 border-gray-700'
                                                }`}>
                                                {isTxn ? (isDeposit ? 'DEPOSIT' : 'WITHDRAWAL') : bet.status}
                                            </span>
                                        </td>
                                        <td className={`px-6 py-3 text-right font-bold text-xs ${bet.profit >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                            {(bet.profit !== undefined && bet.profit !== null) ? (bet.profit >= 0 ? '+' : '') + formatCurrency(bet.profit) : '-'}
                                        </td>
                                        <td className="px-6 py-3 text-right space-x-2">
                                            {!isTxn && (
                                                <>
                                                    <button
                                                        onClick={() => handleSettle(bet.id, 'WON')}
                                                        className="p-1 text-green-500 hover:bg-green-500/10 rounded border border-green-500/20 title='Settle as Win'"
                                                        disabled={isUpdating}
                                                    >
                                                        W
                                                    </button>
                                                    <button
                                                        onClick={() => handleSettle(bet.id, 'LOST')}
                                                        className="p-1 text-red-500 hover:bg-red-500/10 rounded border border-red-500/20 title='Settle as Loss'"
                                                        disabled={isUpdating}
                                                    >
                                                        L
                                                    </button>
                                                    <button
                                                        onClick={() => handleSettle(bet.id, 'PUSH')}
                                                        className="p-1 text-yellow-500 hover:bg-yellow-500/10 rounded border border-yellow-500/20 title='Settle as Push'"
                                                        disabled={isUpdating}
                                                    >
                                                        P
                                                    </button>
                                                    <button
                                                        onClick={() => handleDelete(bet.id)}
                                                        className="p-1 text-gray-500 hover:text-red-400 title='Delete'"
                                                        disabled={isUpdating}
                                                    >
                                                        <Trash size={12} />
                                                    </button>
                                                </>
                                            )}
                                        </td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                </div>

                {filtered.length === 0 && (
                    <div className="p-8 text-center text-gray-500 text-sm">
                        No transactions found matching criteria.
                    </div>
                )}
            </div>
        </div >
    );
}

const calculateCLV = (placed, closing) => {
    const implied = (o) => o > 0 ? 100 / (o + 100) : Math.abs(o) / (Math.abs(o) + 100);
    const p = implied(Number(placed));
    const c = implied(Number(closing));
    if (!p || !c) return 0;
    // EV = (TrueProb / BreakEvenProb) - 1
    // TrueProb = Implied(Closing) (assuming efficient market)
    // BreakEvenProb = Implied(Placed)
    return ((c / p) - 1) * 100;
};

// --- Financial Summary Component ---
// --- Financial Header Component ---
const FinancialCard = ({ label, value, icon: Icon, colorClass, borderColor }) => (
    <div className={`bg-slate-900 border ${borderColor || 'border-slate-800'} p-4 rounded-xl flex items-center justify-between min-w-[220px] shadow-sm`}>
        <div>
            <div className="text-gray-400 text-[10px] font-bold uppercase tracking-wider mb-1">{label}</div>
            <div className={`text-xl font-bold ${value < 0 ? 'text-red-400' : 'text-white'}`}>
                {formatCurrency(value)}
            </div>
        </div>
        <div className={`p-2 rounded-full ${colorClass}`}>
            <Icon size={20} />
        </div>
    </div>
);

const FinancialHeader = ({ financials, mode = 'all' }) => {
    if (!financials) return null;
    return (
        <div className="flex flex-wrap gap-4 mb-8">
            <div className="text-[10px] text-slate-500 absolute top-2 right-4">v1.2.1</div>

            {mode !== 'performance' && (
                <FinancialCard
                    label="Total In Play"
                    value={financials.total_in_play}
                    icon={TrendingUp}
                    borderColor="border-green-500/30"
                    colorClass="bg-green-900/20 text-green-400"
                />
            )}
            {mode === 'performance' && (
                <>
                    <FinancialCard
                        label="Net Deposits"
                        value={financials.total_deposited}
                        icon={ArrowUpRight}
                        colorClass="bg-blue-900/20 text-blue-400"
                    />
                    <FinancialCard
                        label="Net Withdrawals"
                        value={financials.total_withdrawn}
                        icon={ArrowDownRight}
                        colorClass="bg-orange-900/20 text-orange-400"
                    />
                    <FinancialCard
                        label="Realized Profit"
                        value={financials.realized_profit}
                        icon={DollarSign}
                        borderColor={financials.realized_profit >= 0 ? "border-green-500/20" : "border-red-500/20"}
                        colorClass={financials.realized_profit >= 0 ? "bg-green-900/10 text-green-500" : "bg-red-900/10 text-red-500"}
                    />
                </>
            )}
        </div>
    );
};




export default App;
// force rebuild
