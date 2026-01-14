import React, { useState, useEffect } from 'react';
import api from './api/axios';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell, LineChart, Line } from 'recharts';
import { LayoutDashboard, List, ArrowUpRight, ArrowDownRight, TrendingUp, DollarSign, AlertCircle } from 'lucide-react';
import BetTypeAnalysis from './components/BetTypeAnalysis';
import Research from './pages/Research';

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
    const [financials, setFinancials] = useState(null);
    const [periodStats, setPeriodStats] = useState({});
    const [error, setError] = useState(null);

    useEffect(() => {
        // Fetch Data
        const fetchData = async () => {
            try {
                // Helper to get data or default
                const getVal = (res, defaultVal) => res.status === 'fulfilled' ? res.value.data : defaultVal;

                const results = await Promise.allSettled([
                    api.get('/api/stats'),
                    api.get('/api/bets'),
                    api.get('/api/breakdown/sport'),
                    api.get('/api/breakdown/player'),
                    api.get('/api/breakdown/monthly'),
                    api.get('/api/breakdown/bet_type'),
                    api.get('/api/balances'),
                    api.get('/api/financials')
                ]);

                // Check for 403 or 500 in results to alert user
                const failed = results.find(r => r.status === 'rejected');
                if (failed) {
                    // Since we catch globally in axios for 403, this is likely 500 or Network
                    throw failed.reason;
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
                setBetTypeBreakdown(getVal(results[5], []));
                setBalances(getVal(results[6], {}));
                setFinancials(getVal(results[7], { total_in_play: 0, total_deposited: 0, total_withdrawn: 0, realized_profit: 0 }));

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
            <div className="flex gap-4">
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
                        </div>
                    </header>

                    {/* Content */}
                    {view === 'summary' ? (
                        <SummaryView
                            stats={stats}
                            sportBreakdown={sportBreakdown}
                            playerBreakdown={playerBreakdown}
                            monthlyBreakdown={monthlyBreakdown}
                            betTypeBreakdown={betTypeBreakdown}
                            balances={balances}
                            periodStats={periodStats}
                            financials={financials}
                        />
                    ) : view === 'transactions' ? (
                        <TransactionView bets={bets} financials={financials} />
                    ) : (
                        <Research />
                    )}
                </div>
            </div>
        </ErrorBoundary>
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

function SummaryView({ stats, sportBreakdown, playerBreakdown, monthlyBreakdown, betTypeBreakdown, balances, periodStats, financials }) {
    const [chartMode, setChartMode] = useState('monthly'); // 'sport' or 'monthly'

    // Sort sport breakdown by profit for chart
    const sortedSportBreakdown = [...sportBreakdown].sort((a, b) => b.profit - a.profit);

    return (
        <div className="space-y-8">
            {/* Bankroll Section */}
            <div className="flex flex-wrap gap-4 items-stretch">
                <FinancialHeader financials={financials} mode="summary" />
                {Object.entries(balances)
                    .filter(([provider]) => provider && provider !== 'Barstool' && provider !== 'Other' && provider !== 'Total Net Profit')
                    .map(([provider, data]) => (
                        <BankrollCard key={provider} provider={provider} data={data} />
                    ))}
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
                                {(data.adj_wins !== undefined) && (
                                    <div className="text-[10px] text-gray-600 mt-2 pt-2 border-t border-slate-800 flex justify-between" title="Risk-Adjusted Record (Wins discounted by Implied Prob)">
                                        <span>Fair Record:</span>
                                        <span className="font-mono text-gray-400">{data.adj_wins} - {data.adj_losses}</span>
                                    </div>
                                )}
                            </div>
                        );

                    })}
                </div>
            </div>

            {/* Implied Win Rate Table */}
            <div className="bg-slate-900/50 border border-slate-800 rounded-xl overflow-hidden p-6">
                <h3 className="text-xl font-bold mb-4">Win Rate Analysis (Actual vs Implied)</h3>
                <div className="overflow-x-auto">
                    <table className="w-full text-left text-sm">
                        <thead>
                            <tr className="text-gray-400 border-b border-slate-800">
                                <th className="pb-3 pl-2">Period</th>
                                <th className="pb-3 text-right">Record</th>
                                <th className="pb-3 text-right">Actual WR</th>
                                <th className="pb-3 text-right">Implied WR</th>
                                <th className="pb-3 text-right pr-2">Edge</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-800/50">
                            {['7d', '30d', 'ytd', 'all'].map(p => {
                                const d = periodStats[p];
                                if (!d) return null;
                                const edge = d.actual_win_rate - d.implied_win_rate;
                                const label = p === 'all' ? 'All Time' : p === 'ytd' ? 'Year to Date' : `Last ${p.replace('d', ' Days')}`;
                                return (
                                    <tr key={p} className="hover:bg-slate-800/20">
                                        <td className="py-3 pl-2 font-medium text-white">{label}</td>
                                        <td className="py-3 text-right text-gray-400">{d.wins}-{d.losses}-{d.total_bets - d.wins - d.losses}</td>
                                        <td className="py-3 text-right font-bold text-gray-200">{d.actual_win_rate.toFixed(1)}%</td>
                                        <td className="py-3 text-right text-gray-400">{d.implied_win_rate.toFixed(1)}%</td>
                                        <td className={`py-3 text-right pr-2 font-bold ${edge > 0 ? 'text-green-400' : 'text-red-400'}`}>
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
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                {/* Chart Section */}
                <div className="lg:col-span-2 bg-slate-900/50 border border-slate-800 p-6 rounded-xl backdrop-blur-sm">
                    <div className="flex justify-between items-center mb-4">
                        <h3 className="text-xl font-bold flex items-center gap-2">
                            {chartMode === 'monthly' ? "Bankroll Growth" : "Profit by Sport"}
                        </h3>
                        <div className="flex bg-slate-800 rounded-lg p-1 gap-1">
                            <button
                                onClick={() => setChartMode('monthly')}
                                className={`px-3 py-1 text-sm rounded-md transition-all ${chartMode === 'monthly' ? 'bg-slate-600 text-white' : 'text-gray-400 hover:text-white'}`}
                            >
                                Monthly
                            </button>
                            <button
                                onClick={() => setChartMode('sport')}
                                className={`px-3 py-1 text-sm rounded-md transition-all ${chartMode === 'sport' ? 'bg-slate-600 text-white' : 'text-gray-400 hover:text-white'}`}
                            >
                                By Sport
                            </button>
                        </div>
                    </div>

                    <div className="h-[300px]">
                        <ResponsiveContainer width="100%" height="100%">
                            {chartMode === 'monthly' ? (
                                <LineChart data={monthlyBreakdown}>
                                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                                    <XAxis dataKey="month" stroke="#94a3b8" />
                                    <YAxis stroke="#94a3b8" />
                                    <Tooltip
                                        contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b' }}
                                        itemStyle={{ color: '#fff' }}
                                        formatter={(value) => formatCurrency(value)}
                                    />
                                    <Line type="monotone" dataKey="cumulative" stroke="#22c55e" strokeWidth={3} dot={{ r: 4, fill: '#22c55e' }} activeDot={{ r: 8 }} />
                                </LineChart>
                            ) : (
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
                            )}
                        </ResponsiveContainer>
                    </div>
                </div>

                {/* Top Players Table (Column 3) */}
                <div className="bg-slate-900/50 border border-slate-800 p-6 rounded-xl backdrop-blur-sm overflow-hidden flex flex-col">
                    <h3 className="text-xl font-bold mb-4">Top Players</h3>
                    <div className="overflow-y-auto flex-1 max-h-[300px] pr-2 custom-scrollbar">
                        <table className="w-full text-left">
                            <thead>
                                <tr className="text-gray-400 border-b border-slate-800">
                                    <th className="pb-2 font-medium">Player</th>
                                    <th className="pb-2 font-medium text-right">Profit</th>
                                    <th className="pb-2 font-medium text-right">Win Rates</th>
                                </tr>
                            </thead>
                            <tbody>
                                {playerBreakdown.slice(0, 10).map((p, i) => (
                                    <tr key={i} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                                        <td className="py-3 text-sm font-medium text-white">{p.player}</td>
                                        <td className={`py-3 text-sm text-right font-bold ${p.profit >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                            {formatCurrency(p.profit)}
                                        </td>
                                        <td className="py-3 text-sm text-right text-gray-400">
                                            {p.win_rate.toFixed(0)}%
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            {/* Bet Type Analysis */}
            <BetTypeAnalysis data={betTypeBreakdown} formatCurrency={formatCurrency} />



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
        sport: "All",
        type: "All",
        selection: "",
        status: "All"
    });

    // Extract unique options for dropdowns
    const sports = ["All", ...new Set(bets.map(b => b.sport).filter(Boolean))].sort();
    const types = ["All", ...new Set(bets.map(b => b.bet_type).filter(Boolean))].sort();
    const statuses = ["All", ...new Set(bets.map(b => b.status).filter(Boolean))].sort();

    const filtered = bets.filter(b => {
        const matchDate = b.date.includes(filters.date);
        const matchSport = filters.sport === "All" || b.sport === filters.sport;
        const matchType = filters.type === "All" || b.bet_type === filters.type;
        const matchSelection = (b.selection || b.description || "").toLowerCase().includes(filters.selection.toLowerCase());
        const matchStatus = filters.status === "All" || b.status === filters.status;
        return matchDate && matchSport && matchType && matchSelection && matchStatus;
    });

    const resetFilters = () => setFilters({ date: "", sport: "All", type: "All", selection: "", status: "All" });

    return (
        <div className="space-y-8">
            <div className="flex flex-wrap gap-4 items-stretch">
                <FinancialHeader financials={financials} mode="all" />
            </div>



            {/* Provider Breakdown Table (New Request) */}
            {
                financials?.breakdown && (
                    <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden shadow-xl mb-8 p-6">
                        <h3 className="text-xl font-bold mb-4 flex items-center gap-2">
                            <DollarSign className="text-green-400" /> Sportsbook Financials
                        </h3>
                        <table className="w-full text-left text-sm">
                            <thead>
                                <tr className="text-gray-400 border-b border-gray-700">
                                    <th className="pb-2">Sportsbook</th>
                                    <th className="pb-2 text-right">Total Deposited</th>
                                    <th className="pb-2 text-right">Total Withdrawn</th>
                                    <th className="pb-2 text-right">Realized Profit</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-800">
                                {financials.breakdown.map((prov) => (
                                    <tr key={prov.provider} className="hover:bg-gray-800/30">
                                        <td className="py-3 font-bold text-white">{prov.provider}</td>
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

            <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden shadow-xl">
                {/* Toolbar / Summary */}
                <div className="p-4 border-b border-gray-800 flex justify-between items-center bg-gray-900/50 backdrop-blur">
                    <div className="text-gray-400 text-sm">
                        Showing <span className="text-white font-bold">{filtered.length}</span> of {bets.length} transactions
                    </div>
                    <button
                        onClick={resetFilters}
                        className="text-xs text-blue-400 hover:text-blue-300 font-medium px-3 py-1.5 rounded-lg border border-blue-900/30 hover:bg-blue-900/20 transition"
                    >
                        Clear Filters
                    </button>
                </div>

                {/* Grid */}
                <div className="overflow-x-auto">
                    <table className="w-full text-left text-sm whitespace-nowrap">
                        <thead className="bg-gray-800 text-gray-400 font-medium uppercase text-xs tracking-wider">
                            {/* Header Labels */}
                            <tr>
                                <th className="px-6 py-3 border-b border-gray-700">Date</th>
                                <th className="px-6 py-3 border-b border-gray-700">Sport</th>
                                <th className="px-6 py-3 border-b border-gray-700">Type</th>
                                <th className="px-6 py-3 border-b border-gray-700">Selection</th>
                                <th className="px-6 py-3 border-b border-gray-700 text-right">Odds</th>
                                <th className="px-6 py-3 border-b border-gray-700 text-right">Wager</th>
                                <th className="px-6 py-3 border-b border-gray-700 text-center">Status</th>
                                <th className="px-6 py-3 border-b border-gray-700 text-right">Profit</th>
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
                                        value={filters.sport}
                                        onChange={e => setFilters({ ...filters, sport: e.target.value })}
                                    >
                                        {sports.map(s => <option key={s} value={s}>{s}</option>)}
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
                                <th className="px-2 py-2"></th> {/* Odds no filter */}
                                <th className="px-2 py-2"></th> {/* Wager no filter */}
                                <th className="px-2 py-2">
                                    <select
                                        className="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-xs text-white focus:border-blue-500 outline-none"
                                        value={filters.status}
                                        onChange={e => setFilters({ ...filters, status: e.target.value })}
                                    >
                                        {statuses.map(s => <option key={s} value={s}>{s}</option>)}
                                    </select>
                                </th>
                                <th className="px-2 py-2"></th> {/* Profit no filter */}
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-800">
                            {filtered.map((bet) => {
                                const isTxn = bet.category === 'Transaction';
                                const isDeposit = bet.bet_type === 'Deposit' || (bet.bet_type === 'Other' && bet.amount > 0);
                                return (
                                    <tr key={bet.id || bet.txn_id} className="hover:bg-gray-800/50 transition duration-150">
                                        <td className="px-6 py-3 text-gray-300 font-mono text-xs">{bet.date}</td>
                                        <td className="px-6 py-3">
                                            <span className={`px-2 py-1 rounded text-[10px] text-gray-300 border shadow-sm uppercase font-bold tracking-wider ${isTxn ? 'bg-indigo-900/30 border-indigo-800 text-indigo-300' : 'bg-gray-800 border-gray-700'}`}>
                                                {isTxn ? bet.provider : bet.sport}
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
                                                bet.status === 'WON' ? 'bg-green-900/20 text-green-400 border-green-900' :
                                                    bet.status === 'LOST' ? 'bg-red-900/20 text-red-400 border-red-900' :
                                                        'bg-gray-800 text-gray-400 border-gray-700'
                                                }`}>
                                                {isTxn ? (isDeposit ? 'DEPOSIT' : 'WITHDRAWAL') : bet.status}
                                            </span>
                                        </td>
                                        <td className={`px-6 py-3 text-right font-bold text-xs ${bet.profit >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                            {!isTxn ? (bet.profit >= 0 ? '+' : '') + formatCurrency(bet.profit) : '-'}
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
        <>
            <FinancialCard
                label="Total In Play"
                value={financials.total_in_play}
                icon={TrendingUp}
                borderColor="border-green-500/30"
                colorClass="bg-green-900/20 text-green-400"
            />
            {mode === 'all' && (
                <>
                    <FinancialCard
                        label="Total Deposited"
                        value={financials.total_deposited}
                        icon={ArrowUpRight}
                        colorClass="bg-blue-900/20 text-blue-400"
                    />
                    <FinancialCard
                        label="Total Withdrawn"
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
        </>
    );
};




export default App;
