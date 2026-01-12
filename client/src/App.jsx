import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from 'recharts';
import { LayoutDashboard, List, ArrowUpRight, ArrowDownRight, TrendingUp, DollarSign } from 'lucide-react';

// Helpers
const formatCurrency = (val) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(val);

function App() {
    const [view, setView] = useState('summary');
    const [stats, setStats] = useState(null);
    const [bets, setBets] = useState([]);
    const [sportBreakdown, setSportBreakdown] = useState([]);

    useEffect(() => {
        // Fetch Data
        const fetchData = async () => {
            try {
                const statsRes = await axios.get('/api/stats');
                setStats(statsRes.data);

                const betsRes = await axios.get('/api/bets');
                setBets(betsRes.data);

                const breakRes = await axios.get('/api/breakdown/sport');
                setSportBreakdown(breakRes.data);
            } catch (err) {
                console.error("API Error", err);
            }
        };
        fetchData();
    }, []);

    if (!stats) return <div className="p-10 text-center">Loading Dashboard...</div>;

    return (
        <div className="min-h-screen bg-gray-950 text-gray-100 p-6 md:p-10 font-sans">
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
                        className={`flex items-center gap-2 px-4 py-2 rounded-lg transition ${view === 'summary' ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-400 hover:bg-gray-700'}`}
                    >
                        <LayoutDashboard size={18} /> Summary
                    </button>
                    <button
                        onClick={() => setView('log')}
                        className={`flex items-center gap-2 px-4 py-2 rounded-lg transition ${view === 'log' ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-400 hover:bg-gray-700'}`}
                    >
                        <List size={18} /> Transactions
                    </button>
                </div>
            </header>

            {/* View Content */}
            {view === 'summary' ? (
                <SummaryView stats={stats} sportBreakdown={sportBreakdown} />
            ) : (
                <TransactionView bets={bets} />
            )}
        </div>
    );
}

const KPICard = ({ title, value, sub, type }) => {
    const isPos = type === 'profit' ? value >= 0 : true;
    const isWinRate = type === 'winrate';

    let colorClass = "text-white";
    if (type === 'profit') colorClass = value >= 0 ? "text-green-400" : "text-red-400";
    if (type === 'roi') colorClass = value >= 0 ? "text-blue-400" : "text-red-400";

    return (
        <div className="bg-gray-900 border border-gray-800 p-5 rounded-xl shadow-lg">
            <div className="text-gray-400 text-sm font-medium uppercase tracking-wider mb-1">{title}</div>
            <div className={`text-3xl font-bold ${colorClass}`}>
                {type === 'profit' || type === 'money' ? formatCurrency(value) : value}
                {type === 'roi' || type === 'winrate' ? '%' : ''}
            </div>
            {sub && <div className="text-gray-500 text-xs mt-2">{sub}</div>}
        </div>
    );
};

function SummaryView({ stats, sportBreakdown }) {
    // Sort breakdown by profit for chart
    const data = [...sportBreakdown].sort((a, b) => b.profit - a.profit);

    return (
        <div className="space-y-6">
            {/* KPI Grid */}
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                <KPICard title="Net Profit" value={stats.net_profit} type="profit" sub="All Time" />
                <KPICard title="ROI" value={stats.roi.toFixed(1)} type="roi" sub="Return on Investment" />
                <KPICard title="Win Rate" value={stats.win_rate.toFixed(1)} type="winrate" sub={`${stats.total_bets} Total Bets`} />
                <KPICard title="Total Wagered" value={stats.total_wagered} type="money" sub="Volume" />
            </div>

            {/* Charts & Tables */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                {/* Chart Section */}
                <div className="lg:col-span-2 bg-gray-900 border border-gray-800 p-6 rounded-xl">
                    <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
                        <TrendingUp size={20} className="text-blue-400" /> Profit by Sport
                    </h3>
                    <div className="h-64 w-full">
                        <ResponsiveContainer width="100%" height="100%">
                            <BarChart data={data}>
                                <CartesianGrid strokeDasharray="3 3" stroke="#333" vertical={false} />
                                <XAxis dataKey="sport" stroke="#666" fontSize={12} tickLine={false} axisLine={false} />
                                <YAxis stroke="#666" fontSize={12} tickLine={false} axisLine={false} tickFormatter={(val) => `$${val}`} />
                                <Tooltip
                                    contentStyle={{ backgroundColor: '#111', borderColor: '#333' }}
                                    itemStyle={{ color: '#fff' }}
                                />
                                <Bar dataKey="profit" radius={[4, 4, 0, 0]}>
                                    {data.map((entry, index) => (
                                        <Cell key={`cell-${index}`} fill={entry.profit >= 0 ? '#4ade80' : '#f87171'} />
                                    ))}
                                </Bar>
                            </BarChart>
                        </ResponsiveContainer>
                    </div>
                </div>

                {/* Breakdown Table (Mini) */}
                <div className="bg-gray-900 border border-gray-800 p-6 rounded-xl overflow-hidden">
                    <h3 className="text-lg font-semibold mb-4">Top Performers</h3>
                    <div className="overflow-x-auto">
                        <table className="w-full text-sm">
                            <thead>
                                <tr className="text-left text-gray-500 border-b border-gray-800">
                                    <th className="pb-2 font-medium">Sport</th>
                                    <th className="pb-2 font-medium text-right">Win %</th>
                                    <th className="pb-2 font-medium text-right">Profit</th>
                                </tr>
                            </thead>
                            <tbody>
                                {data.map((row, i) => (
                                    <tr key={i} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                                        <td className="py-2.5">{row.sport}</td>
                                        <td className="py-2.5 text-right text-gray-300">{row.win_rate.toFixed(0)}%</td>
                                        <td className={`py-2.5 text-right font-medium ${row.profit >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                            {formatCurrency(row.profit)}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>
    );
}

function TransactionView({ bets }) {
    // Add simple search/filter locally
    const [search, setSearch] = useState("");
    const filtered = bets.filter(b =>
        b.description.toLowerCase().includes(search.toLowerCase()) ||
        b.sport.toLowerCase().includes(search.toLowerCase()) ||
        (b.selection && b.selection.toLowerCase().includes(search.toLowerCase()))
    );

    return (
        <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
            {/* Toolbar */}
            <div className="p-4 border-b border-gray-800 flex gap-4">
                <input
                    type="text"
                    placeholder="Search bets..."
                    className="bg-gray-950 border border-gray-700 text-white px-4 py-2 rounded-lg text-sm w-full max-w-sm focus:outline-none focus:border-blue-500"
                    value={search}
                    onChange={e => setSearch(e.target.value)}
                />
            </div>

            {/* Grid */}
            <div className="overflow-x-auto">
                <table className="w-full text-left text-sm whitespace-nowrap">
                    <thead className="bg-gray-800 text-gray-400 font-medium uppercase text-xs tracking-wider">
                        <tr>
                            <th className="px-6 py-3">Date</th>
                            <th className="px-6 py-3">Sport</th>
                            <th className="px-6 py-3">Type</th>
                            <th className="px-6 py-3">Selection</th>
                            <th className="px-6 py-3 text-right">Odds</th>
                            <th className="px-6 py-3 text-right">Wager</th>
                            <th className="px-6 py-3 text-center">Status</th>
                            <th className="px-6 py-3 text-right">Profit</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-800">
                        {filtered.map((bet) => (
                            <tr key={bet.id} className="hover:bg-gray-800/50 transition">
                                <td className="px-6 py-3 text-gray-300">{bet.date}</td>
                                <td className="px-6 py-3">
                                    <span className="bg-gray-800 px-2 py-1 rounded text-xs text-gray-300 border border-gray-700">
                                        {bet.sport}
                                    </span>
                                </td>
                                <td className="px-6 py-3 text-gray-400">{bet.bet_type}</td>
                                <td className="px-6 py-3 max-w-xs truncate text-gray-300" title={bet.selection || bet.description}>
                                    {bet.selection || bet.description}
                                    {bet.is_live && <span className="ml-2 text-[10px] bg-red-900/50 text-red-300 px-1 rounded border border-red-800">LIVE</span>}
                                    {bet.is_bonus && <span className="ml-2 text-[10px] bg-yellow-900/50 text-yellow-300 px-1 rounded border border-yellow-800">BONUS</span>}
                                </td>
                                <td className="px-6 py-3 text-right font-mono text-gray-400">
                                    {bet.odds ? (bet.odds > 0 ? `+${bet.odds}` : bet.odds) : '-'}
                                </td>
                                <td className="px-6 py-3 text-right text-gray-300">{formatCurrency(bet.wager)}</td>
                                <td className="px-6 py-3 text-center">
                                    <span className={`px-2 py-0.5 rounded textxs font-medium border ${bet.status === 'WON' ? 'bg-green-900/20 text-green-400 border-green-900' :
                                        bet.status === 'LOST' ? 'bg-red-900/20 text-red-400 border-red-900' :
                                            'bg-gray-800 text-gray-400 border-gray-700'
                                        }`}>
                                        {bet.status}
                                    </span>
                                </td>
                                <td className={`px-6 py-3 text-right font-medium ${bet.profit >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                    {bet.profit >= 0 ? '+' : ''}{formatCurrency(bet.profit)}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
            <div className="p-4 border-t border-gray-800 text-xs text-gray-500 text-center">
                Showing {filtered.length} transactions
            </div>
        </div>
    );
}

export default App;
