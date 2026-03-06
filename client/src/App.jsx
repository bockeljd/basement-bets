import React, { useState, useEffect, useRef } from 'react';
import api from './api/axios';
import {
    LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, BarChart, Bar, Cell,
    ScatterChart, Scatter, ZAxis, ReferenceLine, AreaChart, Area
} from 'recharts';
import { TrendingUp, TrendingDown, ArrowUpRight, ArrowDownRight, DollarSign, Activity, BarChart3, LayoutDashboard, Search, X, PlusCircle, Trash, RefreshCw, AlertCircle, Filter, Table } from 'lucide-react';

import Research from './pages/Research';
import Picks from './pages/Picks';
import Bankroll from './pages/Bankroll';
import AgentCouncil from './pages/AgentCouncil';
import MarchMadness from './pages/MarchMadness';
import { PasteSlipContainer } from './components/PasteSlipContainer';
import TransactionView from './components/TransactionView';
import ManualAddBetModal from './components/ManualAddBetModal';
// import { StagingBanner } from './components/StagingBanner';

console.log("Basement Bets Frontend v1.6.5 Loaded at " + new Date().toISOString());

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

// Always show dates as MM/DD/YYYY (ET)
const formatDateMDY = (s) => {
    if (!s) return '';
    try {
        const str = String(s).trim();
        // handle YYYY-MM-DD
        const m = str.match(/^(\d{4})-(\d{2})-(\d{2})/);
        if (m) {
            const [, yy, mm, dd] = m;
            return `${mm}/${dd}/${yy}`;
        }
        const d = new Date(str);
        if (!isNaN(d.getTime())) {
            return d.toLocaleDateString('en-US', {
                month: '2-digit',
                day: '2-digit',
                year: 'numeric',
                timeZone: 'America/New_York'
            });
        }
    } catch (e) { }
    return String(s);
};

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

// --- Logo Icon Component ---
const LogoIcon = ({ className }) => (
    <svg viewBox="0 0 100 80" className={className} fill="none" xmlns="http://www.w3.org/2000/svg">
        {/* House Roof */}
        <path d="M10 40L50 10L90 40" stroke="white" strokeWidth="6" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M75 30V15H82V35" stroke="white" strokeWidth="6" strokeLinecap="round" />
        {/* BB Initials as the house body */}
        <text x="50" y="70" textAnchor="middle" fontSize="45" fontWeight="900" fill="white" fontFamily="sans-serif" style={{ letterSpacing: '-2px' }}>BB</text>
        {/* Door */}
        <rect x="44" y="55" width="12" height="20" stroke="white" strokeWidth="2" fill="none" />
        <circle cx="53" cy="65" r="1" fill="white" />
    </svg>
);

function App() {
    const [page, setPage] = useState('today'); // today | model | actuals | council | march

    // Actuals sub-tabs
    const [actualsTab, setActualsTab] = useState('transactions'); // transactions | performance | bankroll

    const [stats, setStats] = useState(null);
    const [bets, setBets] = useState([]);
    const [sportBreakdown, setSportBreakdown] = useState([]);
    const [playerBreakdown, setPlayerBreakdown] = useState([]);
    const [monthlyBreakdown, setMonthlyBreakdown] = useState([]);
    const [betTypeBreakdown, setBetTypeBreakdown] = useState([]);
    const [balances, setBalances] = useState({});
    const [error, setError] = useState(null);
    const [timeSeries, setTimeSeries] = useState([]);
    const [inPlaySeries, setInPlaySeries] = useState([]);
    const [drawdown, setDrawdown] = useState(null);
    const [financials, setFinancials] = useState({ total_in_play: 0, total_deposited: 0, total_withdrawn: 0, realized_profit: 0 });
    const [reconciliation, setReconciliation] = useState(null);
    const [periodStats, setPeriodStats] = useState({ '7d': null, '30d': null, 'ytd': null, 'all': null });
    const [edgeBreakdown, setEdgeBreakdown] = useState([]);
    const [showAddBet, setShowAddBet] = useState(false);
    const [addBetMode, setAddBetMode] = useState('slip'); // slip | manual
    const [manualBet, setManualBet] = useState({
        sportsbook: "DraftKings",
        account_id: "Main",
        sport: "NFL",
        market_type: "Straight",
        event_name: "",
        selection: "",
        odds: "",
        stake: "",
        status: "PENDING",
        placed_at: new Date().toISOString().slice(0, 10)
    });
    const [isManualSaving, setIsManualSaving] = useState(false);
    const [isSyncing, setIsSyncing] = useState(false);
    const [loading, setLoading] = useState(true);

    // Auth State
    const [showLogin, setShowLogin] = useState(() => {
        return !localStorage.getItem('basement_password');
    });

    const handleLogin = (pass) => {
        localStorage.setItem('basement_password', pass);
        window.location.reload();
    };

    const submitManualBet = async () => {
        setIsManualSaving(true);
        try {
            const american = manualBet.odds ? parseInt(manualBet.odds, 10) : null;
            const stake = manualBet.stake ? parseFloat(manualBet.stake) : 0;

            await api.post('/api/bets/manual', {
                sportsbook: manualBet.sportsbook,
                account_id: manualBet.account_id,
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

            setShowAddBet(false);
            setAddBetMode('slip');
            try { localStorage.setItem('nav_after_save', 'today'); } catch (e) { }
            window.location.reload();
        } catch (err) {
            console.error('Manual bet save failed', err);
            alert('Failed to add bet. Check required fields.');
        } finally {
            setIsManualSaving(false);
        }
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

    // If we reloaded after saving a bet/transaction, respect the requested landing tab.
    useEffect(() => {
        try {
            const nav = localStorage.getItem('nav_after_save');
            if (nav === 'transactions') {
                setPage('actuals');
                setActualsTab('transactions');
            } else if (nav === 'today') {
                setPage('today');
            } else if (nav === 'bankroll') {
                // Back-compat: bankroll is now a sub-tab within Actuals.
                setPage('actuals');
                setActualsTab('bankroll');
            }
            if (nav) localStorage.removeItem('nav_after_save');
        } catch (e) { }
    }, []);

    // StrictMode guard - prevents double initial fetch in development
    const didLoad = useRef(false);

    useEffect(() => {
        // If user is not authenticated, don't fetch dashboard yet.
        if (showLogin) return;
        if (didLoad.current) return;
        didLoad.current = true;

        // Single batch fetch - replaces 16 parallel API calls
        const reloadDashboard = async () => {
            setLoading(true);
            try {
                const { data: d } = await api.get('/api/dashboard');
                // Snapshot (reported) vs computed in-play series (snapshots + newly-added settled bets)
                const { data: inplay } = await api.get('/api/financials/inplay/series', { params: { days: 120 } });

                setStats(d.stats || { total_bets: 0, total_profit: 0, win_rate: 0, roi: 0 });
                setBets(d.bets || []);
                setSportBreakdown(d.sport_breakdown || []);
                setPlayerBreakdown(d.player_breakdown || []);
                setMonthlyBreakdown(d.monthly_breakdown || []);

                // Re-calculate bet type breakdown from raw bets (matches previous behavior)
                const rawBets = d.bets || [];
                const apiBetBreakdown = d.bet_type_breakdown || [];

                if (rawBets.length > 0) {
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

                // Balances from explicit snapshots
                const rawSnaps = d.balance_snapshots || {};
                const mapped = {};
                try {
                    Object.entries(rawSnaps).forEach(([provider, snap]) => {
                        if (!provider) return;
                        mapped[provider] = {
                            balance: snap?.balance ?? 0,
                            captured_at: snap?.captured_at || snap?.capturedAt || null,
                            source: snap?.source || 'manual'
                        };
                    });
                } catch (e) { }
                setBalances(mapped);
                setFinancials(d.financials || { total_in_play: 0, total_deposited: 0, total_withdrawn: 0, realized_profit: 0 });
                setReconciliation(d.reconciliation || null);
                setTimeSeries(d.time_series || []);
                setInPlaySeries(inplay?.series || []);
                setDrawdown(d.drawdown || { max_drawdown: 0.0, current_drawdown: 0.0, peak_profit: 0.0 });
                setEdgeBreakdown(d.edge_breakdown || []);

                const ps = d.period_stats || {};
                const defaultPeriod = { net_profit: 0, roi: 0, wins: 0, losses: 0, total_bets: 0, actual_win_rate: 0, implied_win_rate: 0 };

                // Source of truth: sportsbook financials (snapshots + cashflows). For all-time P/L,
                // prefer financials.net_bet_profit over summing bet rows.
                const allPeriod = ps['all'] || defaultPeriod;
                const finAll = d?.financials?.net_bet_profit;
                const allMerged = {
                    ...allPeriod,
                    net_profit: (finAll !== undefined && finAll !== null) ? Number(finAll) : allPeriod.net_profit,
                };

                setPeriodStats({
                    '7d': ps['7d'] || defaultPeriod,
                    '30d': ps['30d'] || defaultPeriod,
                    'ytd': ps['ytd'] || defaultPeriod,
                    'all': allMerged
                });

            } catch (err) {
                console.error("API Error", err);
                if (err?.response?.status === 403) {
                    try { localStorage.removeItem('basement_password'); } catch (e) { }
                    setShowLogin(true);
                    setError('Wrong password. Please log in again.');
                } else {
                    setError(err?.response?.data?.message || err?.message || 'Failed to load dashboard.');
                }
            } finally {
                setLoading(false);
            }
        };
        reloadDashboard();

        // expose for child components (Transactions edit) without prop drilling
        window.__BB_RELOAD_DASHBOARD__ = reloadDashboard;
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

    // Actuals sub-tab state moved above (before any conditional returns) to avoid hook-order issues.

    if (!stats) {
        if (loading) {
            return <div className="min-h-screen flex items-center justify-center bg-slate-950 text-white font-mono animate-pulse">Loading Basement Bets...</div>;
        }
        // If we're not loading and still have no stats, something went wrong (often auth).
        return (
            <div className="flex flex-col items-center justify-center min-h-screen text-red-500 bg-slate-950 p-6 text-center">
                <AlertCircle size={48} className="mb-4" />
                <h2 className="text-2xl font-bold mb-2">Unable to load dashboard</h2>
                <p className="text-gray-400 mb-6">Most common cause: wrong Basement password saved in your browser.</p>
                <div className="flex flex-wrap gap-4 justify-center">
                    <button
                        onClick={() => {
                            try { localStorage.removeItem('basement_password'); } catch (e) { }
                            window.location.reload();
                        }}
                        className="px-6 py-2 bg-slate-100 hover:bg-white text-slate-950 rounded-lg font-bold transition"
                    >
                        Clear Password & Retry
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
    }

    return (
        <ErrorBoundary>
            {showLogin && <LoginModal onSubmit={handleLogin} />}
            {/* <StagingBanner /> */}
            <div className="min-h-screen bg-slate-950 text-white p-4 md:p-8 font-sans selection:bg-brand-blue/30">
                <div className="max-w-7xl mx-auto">
                    {/* Header */}
                    <header className="mb-6 md:mb-8 flex flex-col md:flex-row md:justify-between md:items-center gap-4">
                        <div>
                            <div className="flex items-center gap-4">
                                <LogoIcon className="h-16 md:h-20 w-auto" />
                                <h1 className="text-3xl md:text-4xl font-semibold tracking-tight leading-none text-gradient from-blue-400 to-green-400">
                                    Basement Bets
                                </h1>
                            </div>
                        </div>
                        <div className="flex flex-wrap gap-2 items-center">
                            {/* Primary nav (segmented control) */}
                            <div className="inline-flex gap-1 p-1 rounded-2xl bg-slate-900/40 border border-slate-700/40">
                                <button
                                    onClick={() => setPage('today')}
                                    className={`px-3 md:px-4 py-2 rounded-xl flex items-center gap-2 text-sm font-semibold transition ${page === 'today' ? 'bg-slate-800/70 text-slate-100 shadow-sm ring-1 ring-white/10' : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/40'}`}
                                >
                                    <TrendingUp size={18} />
                                    <span className="hidden sm:inline">Today</span>
                                    <span className="sm:hidden">Today</span>
                                </button>
                                <button
                                    onClick={() => setPage('model')}
                                    className={`px-3 md:px-4 py-2 rounded-xl flex items-center gap-2 text-sm font-semibold transition ${page === 'model' ? 'bg-slate-800/70 text-slate-100 shadow-sm ring-1 ring-white/10' : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/40'}`}
                                >
                                    <BarChart3 size={18} />
                                    <span className="hidden sm:inline">Model Performance</span>
                                    <span className="sm:hidden">Model</span>
                                </button>
                                <button
                                    onClick={() => { setPage('actuals'); setActualsTab('transactions'); }}
                                    className={`px-3 md:px-4 py-2 rounded-xl flex items-center gap-2 text-sm font-semibold transition ${page === 'actuals' ? 'bg-slate-800/70 text-slate-100 shadow-sm ring-1 ring-white/10' : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/40'}`}
                                >
                                    <LayoutDashboard size={18} />
                                    <span className="hidden sm:inline">Actuals</span>
                                    <span className="sm:hidden">Actuals</span>
                                </button>
                                {/* Bankroll moved under Actuals */}
                                <button
                                    onClick={() => setPage('council')}
                                    className={`px-3 md:px-4 py-2 rounded-xl flex items-center gap-2 text-sm font-semibold transition ${page === 'council' ? 'bg-blue-900/40 text-blue-100 shadow-sm ring-1 ring-blue-500/50' : 'text-blue-400/70 hover:text-blue-200 hover:bg-blue-900/20'}`}
                                >
                                    <Search size={18} />
                                    <span className="hidden sm:inline">Agent Council</span>
                                    <span className="sm:hidden">Council</span>
                                </button>
                                <button
                                    onClick={() => setPage('march')}
                                    className={`px-3 md:px-4 py-2 rounded-xl flex items-center gap-2 text-sm font-semibold transition ${page === 'march' ? 'bg-orange-600/80 text-white shadow-sm ring-1 ring-orange-400/30' : 'text-orange-400/70 hover:text-orange-200 hover:bg-orange-900/20'}`}
                                >
                                    <span className="text-[16px]">🏀</span>
                                    <span className="hidden sm:inline">March Madness</span>
                                    <span className="sm:hidden">March Madness</span>
                                </button>
                            </div>

                            <button
                                onClick={handleSyncResults}
                                disabled={isSyncing}
                                className={`px-4 py-2 rounded-2xl flex items-center gap-2 font-semibold transition ${isSyncing ? 'bg-slate-900/40 text-slate-500 animate-pulse border border-slate-700/40' : 'bg-slate-900/40 hover:bg-slate-800/40 text-slate-200 border border-slate-700/40'}`}
                            >
                                <RefreshCw size={18} className={isSyncing ? 'animate-spin' : ''} />
                                {isSyncing ? 'Syncing…' : 'Sync Scores'}
                            </button>
                            {/* Sync DK temporarily removed (rate limits / unreliable) */}
                            <button
                                onClick={() => { setAddBetMode('slip'); setShowAddBet(true); }}
                                className="px-4 py-2 bg-emerald-500/15 hover:bg-emerald-500/20 rounded-2xl flex items-center gap-2 font-semibold transition border border-emerald-500/25 text-emerald-200"
                            >
                                <PlusCircle size={18} /> Add Bet
                            </button>
                        </div>
                    </header>

                    {page === 'actuals' && (
                        <div className="mb-6 flex justify-end">
                            <div className="inline-flex gap-1 p-1 rounded-2xl bg-slate-900/40 border border-slate-700/40">
                                <button
                                    onClick={() => setActualsTab('transactions')}
                                    className={`px-3 py-2 rounded-xl text-sm font-semibold transition ${actualsTab === 'transactions' ? 'bg-slate-800/70 text-slate-100 shadow-sm ring-1 ring-white/10' : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/40'}`}
                                >
                                    Transactions
                                </button>
                                <button
                                    onClick={() => setActualsTab('performance')}
                                    className={`px-3 py-2 rounded-xl text-sm font-semibold transition ${actualsTab === 'performance' ? 'bg-slate-800/70 text-slate-100 shadow-sm ring-1 ring-white/10' : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/40'}`}
                                >
                                    Performance
                                </button>
                                <button
                                    onClick={() => setActualsTab('bankroll')}
                                    className={`px-3 py-2 rounded-xl text-sm font-semibold transition ${actualsTab === 'bankroll' ? 'bg-slate-800/70 text-slate-100 shadow-sm ring-1 ring-white/10' : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/40'}`}
                                >
                                    Bankroll
                                </button>
                            </div>
                        </div>
                    )}


                    {/* Content */}
                    {showAddBet && (
                        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200">
                            <div className="w-full max-w-2xl relative">
                                <div className="mb-3 inline-flex gap-1 p-1 rounded-2xl bg-slate-900/60 border border-slate-700/50">
                                    <button
                                        onClick={() => setAddBetMode('slip')}
                                        className={`px-3 py-2 rounded-xl text-sm font-semibold transition ${addBetMode === 'slip' ? 'bg-slate-800/70 text-slate-100 shadow-sm ring-1 ring-white/10' : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/40'}`}
                                    >
                                        Paste Slip
                                    </button>
                                    <button
                                        onClick={() => setAddBetMode('manual')}
                                        className={`px-3 py-2 rounded-xl text-sm font-semibold transition ${addBetMode === 'manual' ? 'bg-slate-800/70 text-slate-100 shadow-sm ring-1 ring-white/10' : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/40'}`}
                                    >
                                        Manual
                                    </button>
                                </div>

                                {addBetMode === 'slip' ? (
                                    <PasteSlipContainer
                                        onSaveSuccess={() => {
                                            setShowAddBet(false);
                                            setAddBetMode('slip');
                                            try { localStorage.setItem('nav_after_save', 'today'); } catch (e) { }
                                            window.location.reload();
                                        }}
                                        onClose={() => setShowAddBet(false)}
                                    />
                                ) : (
                                    <ManualAddBetModal
                                        show={true}
                                        embedded={true}
                                        manualBet={manualBet}
                                        setManualBet={setManualBet}
                                        isUpdating={isManualSaving}
                                        onSave={submitManualBet}
                                        onClose={() => setShowAddBet(false)}
                                    />
                                )}
                            </div>
                        </div>
                    )}

                    {page === 'today' ? (
                        <Research
                            onAddBet={(prefill) => {
                                // If a pick row is passed, open manual add-bet prefilled.
                                if (prefill && typeof prefill === 'object') {
                                    setAddBetMode('manual');
                                    setManualBet(prev => ({
                                        ...prev,
                                        sport: prefill.sport || prev.sport,
                                        event_name: prefill.game || prev.event_name,
                                        selection: prefill.pick || prev.selection,
                                        odds: (prefill.odds !== null && prefill.odds !== undefined) ? String(prefill.odds) : prev.odds,
                                        placed_at: prev.placed_at || new Date().toISOString().slice(0, 10),
                                    }));
                                } else {
                                    // Default Add Bet button opens the slip flow.
                                    setAddBetMode('slip');
                                }
                                setShowAddBet(true);
                            }}
                            showModelPerformanceTab={false}
                            formatCurrency={formatCurrency}
                            formatDateMDY={formatDateMDY}
                        />
                    ) : page === 'model' ? (
                        <Picks />
                    ) : page === 'council' ? (
                        <AgentCouncil />
                    ) : page === 'march' ? (
                        <MarchMadness />
                    ) : (
                        <>
                            {actualsTab === 'transactions' ? (
                                <TransactionView
                                    bets={bets}
                                    setBets={setBets}
                                    financials={financials}
                                    reconciliation={reconciliation}
                                    loading={loading}
                                    formatCurrency={formatCurrency}
                                    formatDateMDY={formatDateMDY}
                                    showOpenBets={false}
                                    showFinancials={false}
                                />
                            ) : actualsTab === 'bankroll' ? (
                                <Bankroll financials={financials} bets={bets} formatCurrency={formatCurrency} />
                            ) : (
                                <PerformanceView
                                    timeSeries={timeSeries}
                                    inPlaySeries={inPlaySeries}
                                    financials={financials}
                                    periodStats={periodStats}
                                    edgeBreakdown={edgeBreakdown}
                                    bets={bets}
                                    reconciliation={reconciliation}
                                    onOpenTransactions={(prefill) => {
                                        try { localStorage.setItem('txn_prefill', JSON.stringify(prefill || {})); } catch (e) { }
                                        setPage('actuals');
                                        setActualsTab('transactions');
                                    }}
                                />
                            )}
                        </>
                    )}
                </div>
            </div>
        </ErrorBoundary>
    );
}

function PerformanceView({ timeSeries, inPlaySeries, financials, periodStats, edgeBreakdown, bets, reconciliation, onOpenTransactions }) {
    // Performance tab is focused on actual betting performance + breakdowns.

    // Scatter / drivers controls
    const [minSegmentBets, setMinSegmentBets] = useState(5);
    const [segmentWindow, setSegmentWindow] = useState('30d'); // 30d | 90d | all
    const [scatterColorMode, setScatterColorMode] = useState('profit'); // profit | sport
    const [scatterBubbleMode, setScatterBubbleMode] = useState('bets'); // bets | wager

    const settledBets = React.useMemo(() => {
        const xs = (bets || []);
        return xs.filter(b => {
            const prov = (b.provider || '').toLowerCase();
            if (!(prov.includes('fanduel') || prov.includes('draftkings'))) return false;
            const st = (b.status || '').toUpperCase();
            if (!['WON', 'LOST', 'PUSH'].includes(st)) return false;
            if (b.category && String(b.category).toLowerCase() === 'transaction') return false;
            // Guard: ignore rows that look like deposits/withdrawals in bet table
            const bt = (b.bet_type || '').toLowerCase();
            if (bt === 'deposit' || bt === 'withdrawal') return false;
            return true;
        });
    }, [bets]);

    const parseBetDate = (b) => {
        const s = b?.sort_date || b?.date;
        if (!s) return null;
        const d = new Date(String(s));
        return isNaN(d.getTime()) ? null : d;
    };

    const segmentAgg = React.useMemo(() => {
        const now = new Date();
        const msDay = 24 * 60 * 60 * 1000;
        const cutoff = segmentWindow === '30d' ? new Date(now.getTime() - 30 * msDay)
            : segmentWindow === '90d' ? new Date(now.getTime() - 90 * msDay)
                : null;

        const inWindow = (b) => {
            if (!cutoff) return true;
            const d = parseBetDate(b);
            if (!d) return false;
            return d >= cutoff;
        };

        const add = (map, b) => {
            const sport = (b.sport || 'Unknown').toUpperCase();
            const bt = (b.bet_type || 'Unknown');
            const key = `${sport}|||${bt}`;
            if (!map[key]) map[key] = { sport, bet_type: bt, bets: 0, wins: 0, losses: 0, push: 0, wager: 0, profit: 0, odds_sum: 0, odds_n: 0 };
            const r = map[key];
            const st = (b.status || '').toUpperCase();
            r.bets += 1;
            if (st === 'WON') r.wins += 1;
            else if (st === 'LOST') r.losses += 1;
            else r.push += 1;
            r.wager += Number(b.wager || 0);
            r.profit += Number(b.profit || 0);

            const o = (b.odds === null || b.odds === undefined || b.odds === '') ? null : Number(b.odds);
            if (o !== null && Number.isFinite(o)) {
                r.odds_sum += o;
                r.odds_n += 1;
            }
        };

        const all = {};
        const w = {};
        settledBets.filter(inWindow).forEach(b => add(all, b));

        // driver deltas: last 30d vs prior 30d (always computed off settled bets)
        const last30Cutoff = new Date(now.getTime() - 30 * msDay);
        const prev30Cutoff = new Date(now.getTime() - 60 * msDay);
        const inLast30 = (b) => {
            const d = parseBetDate(b);
            return d && d >= last30Cutoff;
        };
        const inPrev30 = (b) => {
            const d = parseBetDate(b);
            return d && d >= prev30Cutoff && d < last30Cutoff;
        };
        const last30 = {};
        const prev30 = {};
        settledBets.filter(inLast30).forEach(b => add(last30, b));
        settledBets.filter(inPrev30).forEach(b => add(prev30, b));

        const toRows = (map) => Object.values(map).map(r => {
            const decided = r.wins + r.losses;
            const winp = decided > 0 ? (r.wins / decided * 100) : 0;
            const roi = r.wager > 0 ? (r.profit / r.wager * 100) : 0;
            const avgStake = r.bets > 0 ? (r.wager / r.bets) : 0;
            const profitPerBet = r.bets > 0 ? (r.profit / r.bets) : 0;
            const avgOdds = r.odds_n > 0 ? (r.odds_sum / r.odds_n) : null;
            return {
                ...r,
                actual_win_rate: Number(winp.toFixed(1)),
                roi: Number(roi.toFixed(1)),
                profit: Number(r.profit.toFixed(2)),
                wager: Number(r.wager.toFixed(2)),
                avg_stake: Number(avgStake.toFixed(2)),
                profit_per_bet: Number(profitPerBet.toFixed(2)),
                avg_odds: (avgOdds === null) ? null : Number(avgOdds.toFixed(0)),
            };
        });

        const rows = toRows(all).filter(r => r.bets >= minSegmentBets);
        const rowsLast30 = toRows(last30);
        const rowsPrev30 = toRows(prev30);

        const lookup = (rows) => {
            const m = {};
            rows.forEach(r => { m[`${r.sport}|||${r.bet_type}`] = r; });
            return m;
        };

        const m30 = lookup(rowsLast30);
        const mp30 = lookup(rowsPrev30);

        const driving = rows.map(r => {
            const key = `${r.sport}|||${r.bet_type}`;
            const a = m30[key];
            const p = mp30[key];
            const roi30 = a ? a.roi : null;
            const roiPrev = p ? p.roi : null;
            const profit30 = a ? a.profit : null;
            const profitPrev = p ? p.profit : null;
            const roiDelta = (roi30 === null || roiPrev === null) ? null : Number((roi30 - roiPrev).toFixed(1));
            return { ...r, roi_30d: roi30, roi_prev30d: roiPrev, roi_delta: roiDelta, profit_30d: profit30, profit_prev30d: profitPrev, bets_30d: a ? a.bets : 0 };
        });

        return {
            rows,
            driving
        };
    }, [settledBets, minSegmentBets, segmentWindow]);

    // Charts-only view (no daily picks feed here).
    if (!timeSeries || timeSeries.length === 0) {
        return (
            <div className="bg-slate-900 border border-slate-800 p-10 rounded-xl text-center">
                <p className="text-gray-400">No performance data available yet. Settle some bets to see your equity curve!</p>
            </div>
        );
    }

    return (
        <div className="space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
            {/* Financial Overview tiles removed for Performance tab (focus on betting performance) */}

            {/* Sportsbook financials moved to Transactions tab */}

            {/* Drawdown tiles removed (keep Performance tab focused on betting performance + curves) */}

            {/* Betting performance windows (settled bets) */}
            <div className="bg-slate-900 border border-slate-800 p-6 rounded-xl backdrop-blur-sm">
                <h3 className="text-xl font-bold mb-4 flex items-center gap-2">
                    <TrendingUp className="text-blue-400" /> Betting Performance
                </h3>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {(['7d', '30d', 'ytd', 'all']).map((k) => {
                        const w = periodStats?.[k];
                        if (!w) return null;
                        const profit = Number(w.net_profit || 0);
                        const roi = Number(w.roi || 0);
                        return (
                            <div key={k} className="bg-slate-800/40 border border-slate-700 rounded-xl p-4">
                                <div className="text-[10px] uppercase tracking-widest text-slate-500 font-black mb-2">
                                    {k === '7d' ? 'Last 7 days' : k === '30d' ? 'Last 30 days' : k === 'ytd' ? 'YTD' : 'All-time'}
                                </div>
                                <div className="grid grid-cols-2 gap-3 text-sm">
                                    <div>
                                        <div className="text-slate-400 text-xs">Net P/L</div>
                                        <div className={`font-black text-lg ${profit >= 0 ? 'text-green-400' : 'text-red-400'}`}>{formatCurrency(profit)}</div>
                                    </div>
                                    <div>
                                        <div className="text-slate-400 text-xs">ROI</div>
                                        <div className={`font-black text-lg ${roi >= 0 ? 'text-green-400' : 'text-red-400'}`}>{roi.toFixed(1)}%</div>
                                    </div>
                                    <div>
                                        <div className="text-slate-400 text-xs">Record</div>
                                        <div className="text-white font-bold">{w.wins}-{w.losses}</div>
                                    </div>
                                    <div>
                                        <div className="text-slate-400 text-xs">Win%</div>
                                        <div className="text-white font-bold">{Number(w.actual_win_rate || 0).toFixed(1)}%</div>
                                    </div>
                                </div>
                            </div>
                        );
                    })}
                </div>
            </div>

            {/* Scatter: Win% vs ROI by sport + bet type */}
            <div className="bg-slate-900 border border-slate-800 p-6 rounded-xl backdrop-blur-sm">
                <div className="flex items-center justify-between gap-4 mb-4">
                    <h3 className="text-xl font-bold flex items-center gap-2">
                        <BarChart3 className="text-blue-400" /> Win% vs ROI (by sport + bet type)
                    </h3>
                    <div className="text-xs text-slate-500">Click a dot to filter Transactions</div>
                </div>

                <div className="flex flex-wrap items-center gap-3 mb-3">
                    <div className="text-xs text-slate-500">Window</div>
                    <select
                        className="bg-slate-950/40 border border-slate-700 rounded px-2 py-1 text-xs text-slate-200"
                        value={segmentWindow}
                        onChange={(e) => setSegmentWindow(e.target.value)}
                    >
                        <option value="30d">Last 30 days</option>
                        <option value="90d">Last 90 days</option>
                        <option value="all">All-time</option>
                    </select>

                    <div className="ml-2 text-xs text-slate-500">Color</div>
                    <select
                        className="bg-slate-950/40 border border-slate-700 rounded px-2 py-1 text-xs text-slate-200"
                        value={scatterColorMode}
                        onChange={(e) => setScatterColorMode(e.target.value)}
                    >
                        <option value="profit">Profit sign</option>
                        <option value="sport">Sport</option>
                    </select>

                    <div className="ml-2 text-xs text-slate-500">Bubble</div>
                    <select
                        className="bg-slate-950/40 border border-slate-700 rounded px-2 py-1 text-xs text-slate-200"
                        value={scatterBubbleMode}
                        onChange={(e) => setScatterBubbleMode(e.target.value)}
                    >
                        <option value="bets"># Bets</option>
                        <option value="wager">$ Wager</option>
                    </select>

                    <div className="ml-2 text-xs text-slate-500">Min N</div>
                    <input
                        type="number"
                        min={1}
                        max={999}
                        value={minSegmentBets}
                        onChange={(e) => setMinSegmentBets(Math.max(1, parseInt(e.target.value || '1', 10)))}
                        className="w-20 bg-slate-950/40 border border-slate-700 rounded px-2 py-1 text-xs text-slate-200"
                    />
                    <button
                        type="button"
                        onClick={() => setMinSegmentBets(10)}
                        className={`px-2 py-1 text-xs rounded border ${minSegmentBets >= 10 ? 'bg-blue-600/20 text-blue-300 border-blue-500/30' : 'bg-slate-900/40 text-slate-300 border-slate-700'}`}
                    >
                        N≥10
                    </button>
                </div>

                {(segmentAgg.rows || []).length === 0 ? (
                    <div className="text-slate-500 text-sm">No segments meet the filter yet (try lowering min bets).</div>
                ) : (
                    <div className="h-[440px] bg-slate-800/20 rounded-xl border border-slate-800/50 p-4">
                        <ResponsiveContainer width="100%" height="100%">
                            <ScatterChart margin={{ top: 20, right: 20, bottom: 20, left: 20 }}>
                                <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                                <XAxis
                                    type="number"
                                    dataKey="roi"
                                    name="ROI"
                                    unit="%"
                                    stroke="#94a3b8"
                                    fontSize={10}
                                    domain={['auto', 'auto']}
                                    label={{ value: 'ROI (%)', position: 'bottom', fill: '#64748b', fontSize: 10 }}
                                    tickFormatter={(val) => `${val}%`}
                                />
                                <YAxis
                                    type="number"
                                    dataKey="actual_win_rate"
                                    name="Win Rate"
                                    unit="%"
                                    stroke="#94a3b8"
                                    fontSize={10}
                                    domain={[0, 100]}
                                    label={{ value: 'Win% (settled)', angle: -90, position: 'left', fill: '#64748b', fontSize: 10 }}
                                />
                                <ZAxis type="number" dataKey={scatterBubbleMode === 'wager' ? 'wager' : 'bets'} range={[60, 360]} name="Volume" />
                                <Tooltip
                                    cursor={{ strokeDasharray: '3 3' }}
                                    contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b', borderRadius: '8px' }}
                                    itemStyle={{ color: '#fff' }}
                                    content={({ active, payload }) => {
                                        if (active && payload && payload.length) {
                                            const d = payload[0].payload;
                                            return (
                                                <div className="bg-slate-900 border border-slate-700 p-3 rounded-lg shadow-xl">
                                                    <p className="font-bold text-blue-400 mb-1">{d.sport} - {d.bet_type}</p>
                                                    <div className="grid grid-cols-2 gap-x-4 text-[10px]">
                                                        <span className="text-slate-400">Bets:</span> <span className="text-white text-right">{d.bets}</span>
                                                        <span className="text-slate-400">Record:</span> <span className="text-white text-right">{d.wins}-{d.losses}{d.push ? `-${d.push}` : ''}</span>
                                                        <span className="text-slate-400">Net P/L:</span> <span className={d.profit >= 0 ? 'text-green-400 text-right' : 'text-red-400 text-right'}>{formatCurrency(d.profit)}</span>
                                                        <span className="text-slate-400">Wager:</span> <span className="text-white text-right">{formatCurrency(d.wager)}</span>
                                                        <span className="text-slate-400">ROI:</span> <span className="text-white text-right">{d.roi}%</span>
                                                        <span className="text-slate-400">Win%:</span> <span className="text-white text-right">{d.actual_win_rate}%</span>
                                                    </div>
                                                </div>
                                            );
                                        }
                                        return null;
                                    }}
                                />
                                <ReferenceLine x={0} stroke="#475569" strokeWidth={1} />
                                <ReferenceLine y={50} stroke="#1f2937" strokeWidth={1} strokeDasharray="4 4" />

                                <Scatter
                                    name="Segments"
                                    data={segmentAgg.rows}
                                    onClick={(d) => {
                                        const payload = d?.payload || d;
                                        const sport = payload?.sport;
                                        const betType = payload?.bet_type;
                                        if (sport && betType && typeof onOpenTransactions === 'function') {
                                            onOpenTransactions({ sport, type: betType });
                                        }
                                    }}
                                >
                                    {(segmentAgg.rows || []).map((entry, index) => {
                                        const sportColors = {
                                            NFL: '#60a5fa',
                                            NBA: '#a78bfa',
                                            NCAAM: '#f97316',
                                            NCAAF: '#fbbf24',
                                            MLB: '#22c55e',
                                            NHL: '#38bdf8',
                                            UNKNOWN: '#94a3b8'
                                        };
                                        const fill = scatterColorMode === 'sport'
                                            ? (sportColors[String(entry.sport || 'UNKNOWN').toUpperCase()] || '#94a3b8')
                                            : (entry.profit >= 0 ? '#10b981' : '#ef4444');
                                        const stroke = fill;
                                        return (
                                            <Cell
                                                key={`cell-${index}`}
                                                fill={fill}
                                                fillOpacity={0.55}
                                                stroke={stroke}
                                            />
                                        );
                                    })}
                                </Scatter>
                            </ScatterChart>
                        </ResponsiveContainer>
                    </div>
                )}

                <div className="text-[10px] text-slate-500 text-center mt-2 italic">
                    Breakeven line at ROI=0%. Dotted line at Win%=50% (context only).
                </div>

                {/* What's driving results */}
                <div className="mt-6">
                    <div className="flex items-center justify-between mb-2">
                        <h4 className="text-sm font-black text-slate-200 uppercase tracking-widest">What's driving results (last 30d vs prior 30d)</h4>
                        <div className="text-xs text-slate-500">Sorted by last 30d ROI (then 30d volume)</div>
                    </div>

                    {/* Top winners / losers */}
                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-4">
                        {(() => {
                            const rows = (segmentAgg.driving || []).slice().filter(r => (r.bets_30d || 0) >= Math.max(3, Math.min(10, minSegmentBets)));
                            const winners = rows.slice().sort((a, b) => Number(b.profit_30d || 0) - Number(a.profit_30d || 0)).slice(0, 10);
                            const losers = rows.slice().sort((a, b) => Number(a.profit_30d || 0) - Number(b.profit_30d || 0)).slice(0, 10);
                            const Card = ({ title, data }) => (
                                <div className="bg-slate-800/20 border border-slate-800 rounded-xl p-4">
                                    <div className="text-[10px] uppercase tracking-widest text-slate-500 font-black mb-2">{title}</div>
                                    <div className="space-y-2">
                                        {data.length === 0 ? (
                                            <div className="text-xs text-slate-500">No segments meet the min-N.</div>
                                        ) : data.map((r, i) => (
                                            <div key={i} className="flex items-center justify-between text-sm">
                                                <div className="text-slate-200 font-bold truncate pr-3">{r.sport} - <span className="text-slate-400 font-normal">{r.bet_type}</span></div>
                                                <div className={`font-mono font-bold ${Number(r.profit_30d || 0) >= 0 ? 'text-green-300' : 'text-red-300'}`}>{formatCurrency(Number(r.profit_30d || 0))}</div>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            );
                            return (
                                <>
                                    <Card title="Top winners (30d net P/L)" data={winners} />
                                    <Card title="Top losers (30d net P/L)" data={losers} />
                                </>
                            );
                        })()}
                    </div>

                    {/* Biggest changes */}
                    <div className="bg-slate-800/20 border border-slate-800 rounded-xl p-4 mb-4">
                        <div className="text-[10px] uppercase tracking-widest text-slate-500 font-black mb-2">Biggest changes (ROI Δ, min N)</div>
                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                            {(() => {
                                const rows = (segmentAgg.driving || [])
                                    .filter(r => r.roi_delta !== null && r.roi_delta !== undefined)
                                    .filter(r => (r.bets_30d || 0) >= Math.max(3, minSegmentBets));
                                const top = rows.slice().sort((a, b) => Math.abs(Number(b.roi_delta || 0)) - Math.abs(Number(a.roi_delta || 0))).slice(0, 9);
                                return top.map((r, i) => (
                                    <div key={i} className="bg-slate-900/30 border border-slate-800 rounded-xl p-3">
                                        <div className="text-slate-200 font-bold text-sm truncate">{r.sport} - <span className="text-slate-400 font-normal">{r.bet_type}</span></div>
                                        <div className={`mt-1 font-mono font-black ${(Number(r.roi_delta || 0) >= 0) ? 'text-green-300' : 'text-red-300'}`}>{Number(r.roi_delta) >= 0 ? '+' : ''}{Number(r.roi_delta).toFixed(1)}%</div>
                                        <div className="text-[10px] text-slate-500">ROI 30d: {r.roi_30d === null ? '-' : `${Number(r.roi_30d).toFixed(1)}%`} • prev: {r.roi_prev30d === null ? '-' : `${Number(r.roi_prev30d).toFixed(1)}%`} • N={r.bets_30d || 0}</div>
                                    </div>
                                ));
                            })()}
                        </div>
                    </div>

                    <div className="overflow-x-auto border border-slate-800 rounded-xl">
                        <table className="min-w-full text-left text-sm">
                            <thead className="bg-slate-900/60 border-b border-slate-800">
                                <tr className="text-[10px] uppercase tracking-wider text-slate-500">
                                    <th className="py-2 px-3">Segment</th>
                                    <th className="py-2 px-3 text-right">Bets (all)</th>
                                    <th className="py-2 px-3 text-right">Avg odds</th>
                                    <th className="py-2 px-3 text-right">Avg stake</th>
                                    <th className="py-2 px-3 text-right">P/B</th>
                                    <th className="py-2 px-3 text-right">ROI (all)</th>
                                    <th className="py-2 px-3 text-right">Win% (all)</th>
                                    <th className="py-2 px-3 text-right">P/L (30d)</th>
                                    <th className="py-2 px-3 text-right">ROI (30d)</th>
                                    <th className="py-2 px-3 text-right">ROI Δ</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-slate-800/60">
                                {(segmentAgg.driving || [])
                                    .slice()
                                    .sort((a, b) => {
                                        // sort by last 30d ROI desc, then by sample size desc
                                        const ar = (a.roi_30d === null || a.roi_30d === undefined) ? -Infinity : Number(a.roi_30d);
                                        const br = (b.roi_30d === null || b.roi_30d === undefined) ? -Infinity : Number(b.roi_30d);
                                        if (br !== ar) return br - ar;
                                        const an = Number(a.bets_30d || 0);
                                        const bn = Number(b.bets_30d || 0);
                                        if (bn !== an) return bn - an;
                                        return Number(b.profit_30d || 0) - Number(a.profit_30d || 0);
                                    })
                                    .slice(0, 25)
                                    .map((r, i) => {
                                        const roiDelta = r.roi_delta;
                                        const roiDeltaCls = roiDelta === null ? 'text-slate-500' : roiDelta >= 0 ? 'text-green-400' : 'text-red-400';
                                        return (
                                            <tr key={i} className="hover:bg-slate-800/30">
                                                <td className="py-2 px-3 text-slate-200 font-bold">{r.sport} - <span className="text-slate-400 font-normal">{r.bet_type}</span></td>
                                                <td className="py-2 px-3 text-right text-slate-300 font-mono">{r.bets}</td>
                                                <td className="py-2 px-3 text-right text-slate-300 font-mono">{r.avg_odds === null ? '-' : (r.avg_odds > 0 ? `+${r.avg_odds}` : String(r.avg_odds))}</td>
                                                <td className="py-2 px-3 text-right text-slate-300 font-mono">{formatCurrency(r.avg_stake || 0)}</td>
                                                <td className={`py-2 px-3 text-right font-mono ${(r.profit_per_bet || 0) >= 0 ? 'text-green-300' : 'text-red-300'}`}>{formatCurrency(r.profit_per_bet || 0)}</td>
                                                <td className={`py-2 px-3 text-right font-mono ${Number(r.roi || 0) >= 0 ? 'text-green-300' : 'text-red-300'}`}>{r.roi.toFixed(1)}%</td>
                                                <td className="py-2 px-3 text-right text-slate-300 font-mono">{Number(r.actual_win_rate || 0).toFixed(1)}%</td>
                                                <td className={`py-2 px-3 text-right font-mono ${Number(r.profit_30d || 0) >= 0 ? 'text-green-300' : 'text-red-300'}`}>{r.profit_30d === null ? '-' : formatCurrency(r.profit_30d)}</td>
                                                <td className="py-2 px-3 text-right text-slate-300 font-mono">{r.roi_30d === null ? '-' : `${Number(r.roi_30d).toFixed(1)}%`}</td>
                                                <td className={`py-2 px-3 text-right font-mono ${roiDeltaCls}`}>{roiDelta === null ? '-' : `${roiDelta >= 0 ? '+' : ''}${roiDelta.toFixed(1)}%`}</td>
                                            </tr>
                                        );
                                    })}
                            </tbody>
                        </table>
                    </div>

                    <div className="mt-2 text-[10px] text-slate-600">
                        ROI Δ compares last 30d ROI to prior 30d ROI for the same (sport, bet type) segment.
                    </div>
                </div>
            </div>
        </div>
    );
}

const BankrollCard = ({ provider, data }) => (
    <div className="bg-slate-900 border border-slate-800 p-4 rounded-xl flex items-center justify-between min-w-[220px]">
        <div>
            <div className="text-gray-400 text-xs font-bold uppercase tracking-wider mb-0.5">{provider}</div>
            <div className={`text-xl font-bold ${Number(data.balance) >= 0 ? 'text-white' : 'text-red-400'}`}>
                {formatCurrency(Number(data.balance || 0))}
            </div>

            <div className="text-[10px] text-gray-600 mt-1 font-mono">
                Source: {data.source || 'manual'}
                {data.captured_at ? ` • ${new Date(data.captured_at).toLocaleString([], { month: 'numeric', day: 'numeric', hour: 'numeric', minute: '2-digit' })}` : ''}
            </div>
        </div>
        <div className={`p-2 rounded-full ${provider === 'DraftKings' ? 'bg-orange-900/20 text-orange-400' : 'bg-blue-900/20 text-blue-400'}`}>
            <DollarSign size={20} />
        </div>
    </div>
);

function SummaryView({ stats, sportBreakdown, playerBreakdown, monthlyBreakdown, timeSeries, inPlaySeries, betTypeBreakdown, edgeBreakdown, balances, periodStats, financials }) {
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
                            <LineChart data={(inPlaySeries && inPlaySeries.length) ? inPlaySeries : timeSeries}>
                                <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                                <XAxis
                                    dataKey={(inPlaySeries && inPlaySeries.length) ? "day" : "date"}
                                    stroke="#94a3b8"
                                    tickFormatter={(val) => formatDateMDY(val)}
                                    minTickGap={30}
                                />
                                <YAxis stroke="#94a3b8" tickFormatter={(v) => formatCurrency(v)} />
                                <Tooltip
                                    contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b' }}
                                    itemStyle={{ color: '#fff' }}
                                    formatter={(value) => formatCurrency(value)}
                                    labelFormatter={(label) => formatDateMDY(label)}
                                />
                                {(inPlaySeries && inPlaySeries.length) ? (
                                    <>
                                        <Legend />
                                        <Line type="monotone" dataKey="reported_total_in_play" stroke="#64748b" strokeWidth={2} dot={false} activeDot={{ r: 5 }} name="Reported (snapshots)" />
                                        <Line type="monotone" dataKey="computed_total_in_play" stroke="#22c55e" strokeWidth={2} dot={false} activeDot={{ r: 5 }} name="Computed (snapshots + settled bets)" />
                                    </>
                                ) : (
                                    <Line type="monotone" dataKey="balance" stroke="#3b82f6" strokeWidth={2} dot={false} activeDot={{ r: 6 }} name="Balance" />
                                )}
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
                        <BarChart3 className="text-blue-400" /> Win% vs ROI (by sport + bet type)
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
                                dataKey="roi"
                                name="ROI"
                                unit="%"
                                stroke="#94a3b8"
                                fontSize={10}
                                domain={['auto', 'auto']}
                                label={{ value: 'ROI (%)', position: 'bottom', fill: '#64748b', fontSize: 10 }}
                                tickFormatter={(val) => `${val}%`}
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
                                                    <span className="text-slate-400">ROI:</span> <span className="text-white text-right">{data.roi}%</span>
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
                            {/* Breakeven ROI Reference Line */}
                            <ReferenceLine x={0} stroke="#475569" strokeWidth={1} />

                            <Scatter name="Segments" data={edgeBreakdown}>
                                {edgeBreakdown.map((entry, index) => (
                                    <Cell key={`cell-${index}`} fill={entry.profit >= 0 ? '#10b981' : '#ef4444'} fillOpacity={0.6} stroke={entry.profit >= 0 ? '#10b981' : '#ef4444'} />
                                ))}
                            </Scatter>
                        </ScatterChart>
                    </ResponsiveContainer>
                    <div className="text-[10px] text-slate-500 text-center mt-2 italic">
                        Segments plotted by ROI (X) and Actual Win Rate (Y). Bubble size represents bet volume.
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

// TransactionView extracted to ./components/TransactionView

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
            <div className="text-[10px] text-slate-500 absolute top-2 right-4">v1.6.5</div>

            {mode !== 'performance' && (
                <FinancialCard
                    label="Total In Play"
                    value={financials?.ledger_total_in_play ?? financials?.total_in_play}
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
