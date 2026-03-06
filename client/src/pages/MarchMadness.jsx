import React, { useState, useEffect } from 'react';
import api from '../api/axios';
import { RefreshCw } from 'lucide-react';

const MarchMadness = () => {
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    const getTodayStr = () => new Date().toLocaleDateString('en-CA', { timeZone: 'America/New_York' });
    const [selectedDate, setSelectedDate] = useState(getTodayStr());

    const [rowTopPicks, setRowTopPicks] = useState({});
    const [matchupProfiles, setMatchupProfiles] = useState({});

    useEffect(() => {
        fetchData();
    }, [selectedDate]);

    const fetchData = async () => {
        setLoading(true);
        setError(null);

        const topPicksParams = { date: selectedDate, days: 3, limit_games: 250 };

        try {
            const [topPicksRes, matchupRes] = await Promise.all([
                api.get('/api/ncaam/top-picks', { params: topPicksParams })
                    .catch((e) => ({ data: null, _error: e })),
                api.get('/api/ncaam/matchup-profiles', { params: { date: selectedDate } })
                    .catch((e) => ({ data: { matchups: [] } }))
            ]);

            const mProfiles = {};
            (matchupRes?.data?.matchups || []).forEach(m => {
                mProfiles[m.event_id] = m;
            });
            setMatchupProfiles(mProfiles);

            const tp = topPicksRes?.data?.picks || null;
            if (tp && typeof tp === 'object') {
                const mapped = {};
                Object.keys(tp).forEach((eid) => {
                    if (tp[eid]?.rec && tp[eid]?.is_actionable) {
                        mapped[eid] = tp[eid];
                    }
                });
                setRowTopPicks(mapped);
            } else {
                setRowTopPicks({});
            }

        } catch (err) {
            console.error("Failed to load March Madness data", err);
            setError("Failed to load tournament data.");
        } finally {
            setLoading(false);
        }
    };

    const shiftDate = (offset) => {
        try {
            const d = new Date(selectedDate + 'T12:00:00Z');
            d.setDate(d.getDate() + offset);
            setSelectedDate(d.toISOString().slice(0, 10));
        } catch (e) { }
    };

    const SELECTION_SUNDAY = new Date('2026-03-15T00:00:00-05:00');
    const now = new Date();
    const daysToTourney = Math.max(0, Math.ceil((SELECTION_SUNDAY - now) / (1000 * 60 * 60 * 24)));
    const tourneyStarted = now >= SELECTION_SUNDAY;

    const mmPicks = Object.entries(rowTopPicks || {})
        .filter(([eid, meta]) => {
            if (!meta?.is_actionable || !meta?.rec) return false;
            const bt = String(meta.rec.bet_type || '').toUpperCase();
            const sel = String(meta.rec.selection || '').trim();
            if (!bt || bt === 'AUTO' || !sel || sel === '—') return false;
            const ev = meta?.event || {};
            const dayEt = ev?.day_et || '';
            if (dayEt) return String(dayEt) === String(selectedDate);
            if (ev?.start_time) {
                try {
                    const d = new Date(ev.start_time);
                    return d.toLocaleDateString('en-CA', { timeZone: 'America/New_York' }) === String(selectedDate);
                } catch (e) { return false; }
            }
            return false;
        })
        .map(([eid, meta]) => ({ eid, meta }))
        .sort((a, b) => {
            const aEv = Number(String(a.meta.rec?.edge ?? '').replace('%', '')) || 0;
            const bEv = Number(String(b.meta.rec?.edge ?? '').replace('%', '')) || 0;
            return bEv - aEv;
        });

    return (
        <div className="p-4 md:p-6 bg-slate-950 min-h-screen text-white rounded-2xl">
            <div className="flex flex-col md:flex-row md:justify-between md:items-center gap-3 mb-6">
                <div>
                    <h1 className="text-2xl md:text-3xl font-bold bg-gradient-to-r from-orange-400 to-red-500 bg-clip-text text-transparent">
                        March Madness
                    </h1>
                </div>
                <div className="flex flex-wrap items-center gap-3">
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
                        <button onClick={() => setSelectedDate(getTodayStr())} className="ml-2 px-2 py-0.5 text-xs bg-orange-600/20 text-orange-400 hover:bg-orange-600/30 rounded">
                            Today
                        </button>
                    </div>
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
                            {tourneyStarted ? 'Showing actionable tournament picks for ' + selectedDate : 'Showing conference tournament picks for ' + selectedDate + ' · Selection Sunday: Mar 15'}
                        </div>
                    </div>
                    <div className="text-right shrink-0">
                        <div className="text-3xl font-black text-orange-300">{mmPicks.length}</div>
                        <div className="text-xs text-orange-200/60 uppercase tracking-wide">Actionable Picks</div>
                    </div>
                </div>
            </div>

            <section className="mb-6 rounded-2xl border border-slate-800 bg-slate-900/60 p-5 space-y-4">
                <div className="flex items-center justify-between gap-4">
                    <div>
                        <div className="text-xs uppercase tracking-widest text-slate-400">Template Preview</div>
                        <h2 className="text-lg font-semibold">UConn Huskies — Template + Modeling</h2>
                        <p className="text-sm text-slate-400">This is the polished UConn team-profile card we rendered earlier. It includes the same KPIs, player heatmap, upset flags, and matchup notes that we want to lock in before filling out the remaining research.</p>
                    </div>
                    <div className="text-xs text-slate-500 uppercase tracking-wider font-semibold">Live preview</div>
                </div>
                <div className="h-[720px] border border-slate-800 rounded-2xl overflow-hidden">
                    <iframe
                        title="UConn Template Preview"
                        src="/march-madness/preview-uconn-polished.html"
                        className="w-full h-full"
                    />
                </div>
            </section>

            {/* Pick cards */}
            {loading ? (
                <div className="text-center py-12 text-slate-400 font-mono animate-pulse">Loading tournament board...</div>
            ) : mmPicks.length === 0 ? (
                <div className="text-center py-12 bg-slate-900/40 rounded-2xl border border-slate-800">
                    <div className="text-4xl mb-3">🏀</div>
                    <div className="text-slate-300 font-semibold text-lg mb-1">No picks for {selectedDate}</div>
                    <div className="text-slate-500 text-sm">The model found no edge on today's slate. Check back tomorrow.</div>
                </div>
            ) : (
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
                    {mmPicks.map(({ eid, meta }, i) => {
                        const rec = meta.rec;
                        const ev = meta.event || {};
                        const evPct = Number(String(rec.edge || '').replace('%', '')) || 0;
                        const confLabel = rec.confidence || 'Medium';
                        const confColor = confLabel === 'High' ? 'text-emerald-400' : confLabel === 'Medium' ? 'text-yellow-400' : 'text-slate-400';
                        const confBg = confLabel === 'High' ? 'bg-emerald-500/10 border-emerald-500/20' : confLabel === 'Medium' ? 'bg-yellow-500/10 border-yellow-500/20' : 'bg-slate-500/10 border-slate-500/20';

                        const profile = matchupProfiles[eid] || {};
                        const hk = profile.home_kenpom || {};
                        const ak = profile.away_kenpom || {};

                        return (
                            <div key={eid} className="relative rounded-2xl border border-slate-700/50 bg-slate-800/60 p-5 hover:border-orange-500/40 hover:bg-slate-800/80 transition-all flex flex-col shadow-lg">
                                {/* Rank badge */}
                                <div className="absolute top-4 right-4 w-7 h-7 rounded-full bg-orange-600/20 border border-orange-500/30 flex items-center justify-center text-xs font-black text-orange-300">#{i + 1}</div>

                                {/* Matchup Header */}
                                <div className="mb-4 pr-8">
                                    <div className="text-[11px] text-slate-500 uppercase tracking-wider mb-1">Matchup</div>
                                    <div className="flex items-center gap-2 mb-1">
                                        <span className="text-sm font-semibold text-slate-200">{ev.away_team || '—'}</span>
                                        {ak.rank && <span className="text-[10px] text-slate-500 font-mono">#{ak.rank}</span>}
                                    </div>
                                    <div className="text-xs text-slate-500 mb-1 leading-none">@</div>
                                    <div className="flex items-center gap-2">
                                        <span className="text-sm font-semibold text-slate-200">{ev.home_team || '—'}</span>
                                        {hk.rank && <span className="text-[10px] text-slate-500 font-mono">#{hk.rank}</span>}
                                    </div>
                                </div>

                                {/* Team Profiles (KenPom) */}
                                <div className="grid grid-cols-2 gap-3 mb-4 p-3 rounded-xl bg-slate-900/50 border border-slate-700/30 text-xs">
                                    <div>
                                        <div className="text-[10px] text-slate-500 mb-1 uppercase tracking-wider">{ev.away_team || 'Away'}</div>
                                        <div className="flex justify-between items-center mb-0.5"><span className="text-slate-500">AdjEM</span><span className="font-mono text-slate-300">{ak.adj_em ? `+${ak.adj_em}` : '—'}</span></div>
                                        <div className="flex justify-between items-center mb-0.5"><span className="text-slate-500">AdjO</span><span className="font-mono text-slate-300">{ak.adj_o || '—'}</span></div>
                                        <div className="flex justify-between items-center"><span className="text-slate-500">AdjD</span><span className="font-mono text-slate-300">{ak.adj_d || '—'}</span></div>
                                    </div>
                                    <div className="pl-3 border-l border-slate-700/50">
                                        <div className="text-[10px] text-slate-500 mb-1 uppercase tracking-wider">{ev.home_team || 'Home'}</div>
                                        <div className="flex justify-between items-center mb-0.5"><span className="text-slate-500">AdjEM</span><span className="font-mono text-slate-300">{hk.adj_em ? `+${hk.adj_em}` : '—'}</span></div>
                                        <div className="flex justify-between items-center mb-0.5"><span className="text-slate-500">AdjO</span><span className="font-mono text-slate-300">{hk.adj_o || '—'}</span></div>
                                        <div className="flex justify-between items-center"><span className="text-slate-500">AdjD</span><span className="font-mono text-slate-300">{hk.adj_d || '—'}</span></div>
                                    </div>
                                </div>

                                <div className="flex-1"></div>

                                {/* Pick */}
                                <div className="mb-3 pt-3 border-t border-slate-700/50">
                                    <div className="text-[11px] text-orange-400/80 uppercase tracking-wider mb-1 font-bold">Model Pick</div>
                                    <div className="flex justify-between items-end">
                                        <div>
                                            <div className="text-base font-black text-white">{rec.bet_type}: {rec.selection}</div>
                                            {rec.market_line != null && (
                                                <div className="text-xs text-slate-400 mt-0.5">{rec.price > 0 ? '+' : ''}{rec.price}</div>
                                            )}
                                        </div>
                                    </div>
                                </div>

                                {/* Stats row */}
                                <div className="flex items-center gap-3">
                                    <div className="flex-1">
                                        <div className="text-[10px] text-slate-500 mb-0.5">EV</div>
                                        <div className="text-sm font-black text-emerald-400">+{evPct.toFixed(1)}%</div>
                                    </div>
                                    {rec.win_prob != null && (
                                        <div className="flex-1">
                                            <div className="text-[10px] text-slate-500 mb-0.5">Win Prob</div>
                                            <div className="text-sm font-bold text-slate-200">{(rec.win_prob * 100).toFixed(0)}%</div>
                                        </div>
                                    )}
                                    <div className={`px-2 py-0.5 rounded-lg border text-[10px] font-bold uppercase ${confBg} ${confColor}`}>
                                        {confLabel}
                                    </div>
                                </div>
                            </div>
                        );
                    })}
                </div>
            )}
        </div>
    );
};

export default MarchMadness;
