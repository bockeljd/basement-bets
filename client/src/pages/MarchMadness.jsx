import React, { useState, useEffect } from 'react';
import api from '../api/axios';
import { RefreshCw } from 'lucide-react';

const MarchMadness = () => {
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [teams, setTeams] = useState([]);

    useEffect(() => {
        fetchData();
    }, []);

    const fetchData = async () => {
        setLoading(true);
        setError(null);

        try {
            const res = await api.get('/api/ncaam/tournament-teams', { params: { limit: 68 } });
            setTeams(res.data.teams || []);
        } catch (err) {
            console.error("Failed to load tournament teams", err);
            setError("Failed to load tournament data.");
        } finally {
            setLoading(false);
        }
    };

    const SELECTION_SUNDAY = new Date('2026-03-15T00:00:00-05:00');
    const now = new Date();
    const daysToTourney = Math.max(0, Math.ceil((SELECTION_SUNDAY - now) / (1000 * 60 * 60 * 24)));
    const tourneyStarted = now >= SELECTION_SUNDAY;

    return (
        <div className="p-4 md:p-6 bg-slate-950 min-h-screen text-white rounded-2xl">
            <div className="flex flex-col md:flex-row md:justify-between md:items-center gap-3 mb-6">
                <div>
                    <h1 className="text-2xl md:text-3xl font-bold bg-gradient-to-r from-orange-400 to-red-500 bg-clip-text text-transparent">
                        March Madness
                    </h1>
                </div>
                <div className="flex flex-wrap items-center gap-3">
                    <button
                        onClick={fetchData}
                        disabled={loading}
                        className="px-4 py-2 bg-slate-800 border border-slate-700 hover:bg-slate-700 rounded-xl text-sm transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                    >
                        <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
                        Refresh
                    </button>
                </div>
            </div>

            {/* Tournament countdown / header */}
            <div className="mb-6 rounded-2xl overflow-hidden" style={{ background: 'linear-gradient(135deg, #7c2d12 0%, #9a3412 40%, #1e293b 100%)' }}>
                <div className="px-6 py-5 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
                    <div>
                        <div className="text-xs font-bold text-orange-300 uppercase tracking-widest mb-1">NCAA Tournament 2026</div>
                        <div className="text-xl font-black text-white">
                            {tourneyStarted ? '🏀 Tournament is Live!' : `${daysToTourney} day${daysToTourney !== 1 ? 's' : ''} to Selection Sunday`}
                        </div>
                        <div className="text-sm text-orange-200/70 mt-1">
                            Tracking the Top 68 KenPom teams to profile potential bracket winners.
                        </div>
                    </div>
                </div>
            </div>

            {/* Pick cards Grid */}
            {loading ? (
                <div className="text-center py-12 text-slate-400 font-mono animate-pulse">Loading tournament profiles...</div>
            ) : error ? (
                <div className="text-center py-12 bg-red-900/20 border border-red-500/50 rounded-2xl text-red-400">
                    {error}
                </div>
            ) : teams.length === 0 ? (
                <div className="text-center py-12 bg-slate-900/40 rounded-2xl border border-slate-800">
                    <div className="text-4xl mb-3">🏀</div>
                    <div className="text-slate-300 font-semibold text-lg mb-1">No profiles generated yet</div>
                </div>
            ) : (
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
                    {teams.map((t) => {
                        const torvik = t.torvik || {};
                        return (
                            <div key={t.team_name} className="relative rounded-2xl border border-slate-700/50 bg-slate-800/60 p-5 hover:border-orange-500/40 hover:bg-slate-800/80 transition-all flex flex-col shadow-lg">
                                {/* Rank badge */}
                                <div className="absolute top-4 right-4 w-8 h-8 rounded-full bg-slate-900/80 border border-slate-600/50 flex items-center justify-center text-xs font-black text-slate-200">
                                    #{t.rank}
                                </div>

                                {/* Team Header */}
                                <div className="mb-4 pr-10">
                                    <h3 className="text-lg font-bold text-white leading-tight truncate" title={t.team_name}>
                                        {t.team_name}
                                    </h3>
                                    <div className="text-xs text-slate-400 mt-1 flex items-center gap-2">
                                        <span>{t.conference || '—'}</span>
                                        <span className="text-slate-600">•</span>
                                        <span className="font-mono">{t.record || '—'}</span>
                                    </div>
                                </div>

                                {/* Main Metrics Grid */}
                                <div className="grid grid-cols-2 gap-2 mb-4">
                                    <div className="bg-slate-900/50 rounded-xl p-3 border border-slate-700/30">
                                        <div className="text-[10px] text-slate-500 uppercase font-bold mb-1">AdjEM</div>
                                        <div className="text-xl font-black text-white">
                                            {t.adj_em ? (t.adj_em > 0 ? `+${t.adj_em}` : t.adj_em) : '—'}
                                        </div>
                                    </div>
                                    <div className="bg-slate-900/50 rounded-xl p-3 border border-slate-700/30">
                                        <div className="text-[10px] text-slate-500 uppercase font-bold mb-1">AdjTempo</div>
                                        <div className="text-xl font-black text-white">
                                            {t.adj_t || '—'}
                                        </div>
                                    </div>
                                </div>

                                {/* Offense/Defense Splits */}
                                <div className="bg-slate-900/50 rounded-xl p-3 border border-slate-700/30 text-sm mb-4">
                                    <div className="flex justify-between items-center mb-2 pb-2 border-b border-slate-700/50">
                                        <span className="text-slate-400 font-semibold text-xs">Adj Offensive Eff.</span>
                                        <span className="font-mono font-bold text-emerald-400">{t.adj_o || '—'}</span>
                                    </div>
                                    <div className="flex justify-between items-center">
                                        <span className="text-slate-400 font-semibold text-xs">Adj Defensive Eff.</span>
                                        <span className="font-mono font-bold text-red-400">{t.adj_d || '—'}</span>
                                    </div>
                                </div>

                                <div className="flex-1"></div>

                                {/* Torvik Context (if available) */}
                                {torvik.barthag && (
                                    <div className="pt-3 border-t border-slate-700/50 flex justify-between items-center text-xs">
                                        <span className="text-slate-500 font-medium">Torvik Barthag</span>
                                        <span className="font-mono text-slate-300">{(torvik.barthag * 100).toFixed(1)}%</span>
                                    </div>
                                )}
                            </div>
                        );
                    })}
                </div>
            )}
        </div>
    );
};

export default MarchMadness;
