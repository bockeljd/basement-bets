import React from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell, ReferenceLine } from 'recharts';

const BetTypeAnalysis = ({ data, formatCurrency }) => {
    if (!data || data.length === 0) return null;

    // Sort by profit for the chart (optional, maybe clearer)
    // The backend already sorts by profit descending.

    return (
        <div className="bg-slate-900/50 border border-slate-800 p-6 rounded-xl backdrop-blur-sm mt-6">
            <h3 className="text-xl font-bold mb-4 flex items-center gap-2">
                Bet Type Performance
            </h3>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
                {/* Chart Section */}
                <div className="h-[300px] w-full">
                    <ResponsiveContainer width="100%" height="100%">
                        <BarChart data={data} margin={{ top: 20, right: 30, left: 0, bottom: 5 }}>
                            <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} />
                            <XAxis
                                dataKey="bet_type"
                                stroke="#94a3b8"
                                tick={{ fill: '#94a3b8', fontSize: 12 }}
                                tickLine={false}
                                interval={0}
                                height={60}
                                angle={-45}
                                textAnchor="end"
                            />
                            <YAxis
                                stroke="#94a3b8"
                                tick={{ fill: '#94a3b8', fontSize: 12 }}
                                tickLine={false}
                                tickFormatter={(val) => `$${val}`}
                            />
                            <Tooltip
                                contentStyle={{ backgroundColor: '#1e293b', borderColor: '#334155', color: '#f8fafc' }}
                                formatter={(value) => formatCurrency(value)}
                                cursor={{ fill: '#334155', opacity: 0.2 }}
                            />
                            <ReferenceLine y={0} stroke="#475569" />
                            <Bar dataKey="profit" radius={[4, 4, 0, 0]}>
                                {data.map((entry, index) => (
                                    <Cell key={`cell-${index}`} fill={entry.profit >= 0 ? '#10b981' : '#ef4444'} />
                                ))}
                            </Bar>
                        </BarChart>
                    </ResponsiveContainer>
                </div>

                {/* Table Section */}
                <div className="overflow-x-auto">
                    <table className="w-full text-left text-sm">
                        <thead className="text-slate-400 border-b border-slate-700">
                            <tr>
                                <th className="pb-2 font-medium">Type</th>
                                <th className="pb-2 text-right font-medium">Count</th>
                                <th className="pb-2 text-right font-medium">Wins</th>
                                <th className="pb-2 text-right font-medium">Win %</th>
                                <th className="pb-2 text-right font-medium">ROI</th>
                                <th className="pb-2 text-right font-medium">Profit</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-800">
                            {data.map((row) => (
                                <tr key={row.bet_type} className="hover:bg-slate-800/50 transition-colors">
                                    <td className="py-3 font-medium text-slate-200">{row.bet_type || 'Unknown'}</td>
                                    <td className="py-3 text-right text-slate-400">{row.bets}</td>
                                    <td className="py-3 text-right text-slate-400">{row.wins}</td>
                                    <td className="py-3 text-right text-slate-300">
                                        <div className="flex items-center justify-end gap-2">
                                            <div className="w-16 h-1.5 bg-slate-700 rounded-full overflow-hidden">
                                                <div
                                                    className={`h-full rounded-full ${row.win_rate >= 50 ? 'bg-green-500' : 'bg-yellow-500'}`}
                                                    style={{ width: `${Math.min(row.win_rate, 100)}%` }}
                                                />
                                            </div>
                                            <span>{row.win_rate.toFixed(0)}%</span>
                                        </div>
                                    </td>
                                    <td className={`py-3 text-right font-medium ${row.roi >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                        {row.roi > 0 ? '+' : ''}{row.roi.toFixed(1)}%
                                    </td>
                                    <td className={`py-3 text-right font-bold ${row.profit >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                        {formatCurrency(row.profit)}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    );
};

export default BetTypeAnalysis;
