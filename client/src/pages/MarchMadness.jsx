import React, { useState, useEffect, useMemo } from 'react';
import api from '../api/axios';
import { Shield, Crosshair, Activity, AlertTriangle, Users, TrendingUp, Cpu, RefreshCw, Swords, Search, Target, Award } from 'lucide-react';

/* ─────────────────── helpers ─────────────────── */
const getEfficiencyColor = (metric, isDefensive = false) => {
    if (!metric) return 'text-slate-400';
    const val = parseFloat(metric);
    if (isDefensive) {
        if (val < 90) return 'text-purple-400';
        if (val < 95) return 'text-emerald-400';
        if (val > 105) return 'text-red-400';
        return 'text-slate-300';
    } else {
        if (val > 120) return 'text-purple-400';
        if (val > 112) return 'text-emerald-400';
        if (val < 100) return 'text-red-400';
        return 'text-slate-300';
    }
};

/** Logistic-style win probability from AdjEM differential */
function emToWinPct(emA, emB) {
    const diff = (parseFloat(emA) || 0) - (parseFloat(emB) || 0);
    // KenPom empirical: ~3.0 EM ≈ 10% win prob shift per unit of diff
    const logit = diff / 10;
    return Math.round((1 / (1 + Math.exp(-logit))) * 100);
}

/** Side-by-side stat bar: highlight the better team */
function StatBar({ label, valA, valB, lowerIsBetter = false, fmtA, fmtB }) {
    const a = parseFloat(valA) || 0;
    const b = parseFloat(valB) || 0;
    const aWins = lowerIsBetter ? a < b : a > b;
    const bWins = lowerIsBetter ? b < a : b > a;
    const maxVal = Math.max(Math.abs(a), Math.abs(b), 1);
    const pctA = Math.min(100, (Math.abs(a) / maxVal) * 100);
    const pctB = Math.min(100, (Math.abs(b) / maxVal) * 100);
    return (
        <div className="grid grid-cols-[1fr_80px_1fr] gap-2 items-center py-2 border-b border-slate-800/40 last:border-0">
            {/* Team A bar (right-aligned) */}
            <div className="flex items-center justify-end gap-2">
                <span className={`text-sm font-black tabular-nums ${aWins ? 'text-emerald-400' : 'text-slate-300'}`}>
                    {fmtA !== undefined ? fmtA : (a !== 0 ? a.toFixed(1) : '—')}
                </span>
                <div className="w-24 h-2.5 bg-slate-800 rounded-full overflow-hidden flex justify-end">
                    <div
                        className={`h-full rounded-full transition-all ${aWins ? 'bg-blue-500' : 'bg-slate-600'}`}
                        style={{ width: `${pctA}%` }}
                    />
                </div>
            </div>
            {/* Label */}
            <div className="text-center text-[10px] font-bold text-slate-500 uppercase tracking-wider">{label}</div>
            {/* Team B bar (left-aligned) */}
            <div className="flex items-center gap-2">
                <div className="w-24 h-2.5 bg-slate-800 rounded-full overflow-hidden">
                    <div
                        className={`h-full rounded-full transition-all ${bWins ? 'bg-rose-500' : 'bg-slate-600'}`}
                        style={{ width: `${pctB}%` }}
                    />
                </div>
                <span className={`text-sm font-black tabular-nums ${bWins ? 'text-emerald-400' : 'text-slate-300'}`}>
                    {fmtB !== undefined ? fmtB : (b !== 0 ? b.toFixed(1) : '—')}
                </span>
            </div>
        </div>
    );
}

/* ─────────────────── main component ─────────────────── */
const MarchMadness = () => {
    const [loading, setLoading] = useState(true);
    const [teams, setTeams] = useState([]);
    const [search, setSearch] = useState('');
    const [selectedTeam, setSelectedTeam] = useState(null);
    const [selectedTeamB, setSelectedTeamB] = useState(null);
    const [isMatchupMode, setIsMatchupMode] = useState(false);
    const [matchupData, setMatchupData] = useState(null);
    const [loadingMatchup, setLoadingMatchup] = useState(false);

    useEffect(() => { fetchData(); }, []);

    const fetchData = async () => {
        setLoading(true);
        try {
            const res = await api.get('/api/ncaam/tournament-teams', { params: { limit: 80 } });
            const allTeams = res.data.teams || [];
            if (allTeams.length > 0) {
                setTeams(allTeams);
                if (!selectedTeam) {
                    const uconn = allTeams.find(t => t.team_name.includes('Connecticut') || t.team_name.includes('UConn'));
                    setSelectedTeam(uconn || allTeams[0]);
                } else {
                    setSelectedTeam(allTeams.find(t => t.team_name === selectedTeam.team_name) || allTeams[0]);
                }
                if (!selectedTeamB) {
                    setSelectedTeamB(allTeams.find(t => t.team_name.includes('North Carolina') || t.team_name === 'North Carolina') || allTeams[1]);
                }
            }
        } catch (err) {
            console.error('Failed to load tournament profiles', err);
        } finally {
            setLoading(false);
        }
    };

    const fetchMatchup = async () => {
        if (!selectedTeam || !selectedTeamB || selectedTeam.team_name === selectedTeamB.team_name) return;
        setLoadingMatchup(true);
        setMatchupData(null);
        try {
            const res = await api.get('/api/ncaam/matchup', {
                params: { team_a: selectedTeam.team_name, team_b: selectedTeamB.team_name }
            });
            setMatchupData(res.data.analysis);
        } catch (err) {
            console.error('Failed to load matchup analysis', err);
            setMatchupData({ summary: 'Analysis failed to load.', confidence: 'N/A', predicted_winner: 'Error' });
        } finally {
            setLoadingMatchup(false);
        }
    };

    useEffect(() => {
        if (isMatchupMode && selectedTeam && selectedTeamB) fetchMatchup();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [isMatchupMode, selectedTeam?.team_name, selectedTeamB?.team_name]);

    /* Filtered teams for search */
    const filteredTeams = useMemo(() => {
        if (!search.trim()) return teams;
        const q = search.toLowerCase();
        return teams.filter(t => t.team_name.toLowerCase().includes(q));
    }, [teams, search]);

    /* Quantitative edge score */
    const edgeScore = useMemo(() => {
        if (!selectedTeam || !selectedTeamB) return null;
        return emToWinPct(selectedTeam.adj_em, selectedTeamB.adj_em);
    }, [selectedTeam, selectedTeamB]);

    if (loading && teams.length === 0) {
        return (
            <div className="p-8 text-center text-slate-400 animate-pulse font-mono flex flex-col items-center justify-center min-h-[400px] gap-3">
                <Cpu size={32} className="text-orange-500 animate-bounce" />
                Loading Tournament Profile Engine...
            </div>
        );
    }

    if (!selectedTeam) {
        return <div className="p-8 text-center text-red-400 font-mono">Profile generation failed. Target team not found.</div>;
    }

    const profile = selectedTeam.profile || {};
    const narrative = profile.narrative || {
        summary: 'Profile generating… Check back later.',
        offense: [], defense: [], upsetFlags: 'N/A'
    };
    const players = profile.players || [];
    const torvik = selectedTeam.torvik || {};

    return (
        <div className="bg-slate-950 text-white pb-20 rounded-2xl overflow-hidden">
            {/* ── Action Bar ── */}
            <div className="flex items-center justify-between p-4 border-b border-slate-800 bg-slate-900/50 backdrop-blur-md flex-wrap gap-3">
                <div className="flex items-center gap-3 flex-wrap">
                    <div className="hidden md:flex items-center gap-2 text-xs font-bold text-slate-500 uppercase tracking-widest">
                        <Cpu size={14} className="text-orange-500" /> Profiler Engine v2.2
                    </div>

                    {/* Mode toggle */}
                    <div className="flex bg-slate-800 p-1 rounded-lg border border-slate-700">
                        <button
                            onClick={() => setIsMatchupMode(false)}
                            className={`px-3 py-1.5 rounded-md text-sm font-bold transition ${!isMatchupMode ? 'bg-blue-600 text-white shadow-md' : 'text-slate-400 hover:text-white'}`}
                        >
                            Team Profile
                        </button>
                        <button
                            onClick={() => setIsMatchupMode(true)}
                            className={`px-3 py-1.5 rounded-md text-sm font-bold flex items-center gap-1 transition ${isMatchupMode ? 'bg-purple-600 text-white shadow-md' : 'text-slate-400 hover:text-white'}`}
                        >
                            <Swords size={14} /> Matchup
                        </button>
                    </div>

                    {/* Team search + selectors */}
                    <div className="flex items-center gap-2 flex-wrap">
                        <div className="relative">
                            <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-slate-500" />
                            <input
                                type="text"
                                placeholder="Search team…"
                                value={search}
                                onChange={e => setSearch(e.target.value)}
                                className="pl-6 pr-2 py-1.5 bg-slate-800 border border-slate-700 rounded text-sm text-white placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-blue-500 w-40"
                            />
                        </div>

                        <select
                            className="bg-slate-800 border border-slate-700 rounded px-3 py-1.5 text-sm font-bold text-blue-400 focus:outline-none focus:ring-1 focus:ring-blue-500 max-w-[180px]"
                            value={selectedTeam.team_name}
                            onChange={e => {
                                const t = teams.find(x => x.team_name === e.target.value);
                                if (t) { setSelectedTeam(t); setSearch(''); }
                            }}
                        >
                            {(search ? filteredTeams : teams).map(t => (
                                <option key={t.team_name} value={t.team_name}>#{t.rank} {t.team_name}</option>
                            ))}
                        </select>

                        {isMatchupMode && (
                            <>
                                <span className="text-slate-500 text-xs font-bold italic">VS</span>
                                <select
                                    className="bg-slate-800 border border-slate-700 rounded px-3 py-1.5 text-sm font-bold text-rose-400 focus:outline-none focus:ring-1 focus:ring-rose-500 max-w-[180px]"
                                    value={selectedTeamB?.team_name || ''}
                                    onChange={e => {
                                        const t = teams.find(x => x.team_name === e.target.value);
                                        if (t) setSelectedTeamB(t);
                                    }}
                                >
                                    {teams.map(t => (
                                        <option key={t.team_name} value={t.team_name} disabled={t.team_name === selectedTeam.team_name}>
                                            #{t.rank} {t.team_name}
                                        </option>
                                    ))}
                                </select>
                            </>
                        )}
                    </div>
                </div>

                <button
                    onClick={isMatchupMode ? fetchMatchup : fetchData}
                    className="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-white transition"
                    title="Refresh Data"
                >
                    <RefreshCw size={14} className={(loading || loadingMatchup) ? 'animate-spin' : ''} />
                </button>
            </div>

            {/* ───── TEAM PROFILE MODE ───── */}
            {!isMatchupMode ? (
                <>
                    {/* Hero Header */}
                    <div className="relative overflow-hidden border-b border-slate-800">
                        <div className="absolute inset-0 bg-gradient-to-br from-blue-900/40 via-slate-900 to-slate-950 opacity-80" />
                        <div className="absolute top-0 right-0 w-96 h-96 bg-blue-600/10 rounded-full blur-[100px] pointer-events-none" />
                        <div className="relative px-6 py-10 md:px-12 md:py-14 max-w-7xl mx-auto flex flex-col md:flex-row items-center md:items-start gap-8">
                            {/* Badge */}
                            <div className="flex flex-col items-center shrink-0">
                                <div className="w-28 h-28 md:w-36 md:h-36 bg-slate-900 rounded-3xl border border-slate-700 shadow-2xl flex items-center justify-center text-6xl relative overflow-hidden">
                                    <div className="absolute inset-0 bg-gradient-to-tr from-blue-500/10 to-transparent" />
                                    🏀
                                </div>
                                <div className="mt-3 px-4 py-1.5 rounded-full bg-slate-800 border border-slate-700 text-sm font-black text-slate-200 tracking-wider shadow-lg">
                                    KP #{selectedTeam.rank}
                                </div>
                                {selectedTeam.net_rank && (
                                    <div className="mt-1.5 px-4 py-1 rounded-full bg-orange-900/30 border border-orange-600/30 text-xs font-bold text-orange-300">
                                        NET #{selectedTeam.net_rank}
                                    </div>
                                )}
                            </div>

                            {/* Title */}
                            <div className="text-center md:text-left flex-1">
                                <div className="text-blue-400 font-bold tracking-widest uppercase text-sm mb-2">{selectedTeam.conference || 'N/A'}</div>
                                <h1 className="text-4xl md:text-5xl font-black text-white mb-2 tracking-tight">{selectedTeam.team_name}</h1>
                                {/* Record pills */}
                                <div className="flex flex-wrap items-center justify-center md:justify-start gap-3 mb-5">
                                    <div className="flex bg-slate-800/80 rounded-lg border border-slate-700/50 p-1 text-sm font-mono text-slate-300">
                                        <span className="px-3 bg-slate-900 rounded font-bold text-white shadow-sm border border-slate-700/50">{selectedTeam.net_record || selectedTeam.record || '—'} OVR</span>
                                        {selectedTeam.home_record && <span className="px-3 border-r border-slate-700/50">{selectedTeam.home_record} H</span>}
                                        {selectedTeam.road_record && <span className="px-3 border-r border-slate-700/50">{selectedTeam.road_record} A</span>}
                                        {selectedTeam.neutral_record && <span className="px-3">{selectedTeam.neutral_record} N</span>}
                                    </div>
                                    <span className="text-slate-600">•</span>
                                    <span className="text-slate-400 text-sm font-bold">
                                        Torvik Barthag <span className="text-white ml-1">{torvik.barthag ? (torvik.barthag * 100).toFixed(1) : '—'}%</span>
                                    </span>
                                </div>
                                <p className="text-slate-300 leading-relaxed max-w-3xl text-sm md:text-base border-l-2 border-blue-500 pl-4 italic">
                                    {narrative.summary}
                                </p>
                            </div>
                        </div>
                    </div>

                    <div className="max-w-7xl mx-auto px-4 md:px-8 py-8 space-y-8">
                        {/* Quad Records */}
                        {(selectedTeam.quad1 || selectedTeam.quad2 || selectedTeam.quad3 || selectedTeam.quad4) && (
                            <div className="grid grid-cols-4 gap-4">
                                {[
                                    { label: 'Quad 1', val: selectedTeam.quad1, cls: 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400' },
                                    { label: 'Quad 2', val: selectedTeam.quad2, cls: 'bg-emerald-500/5 border-emerald-500/10 text-emerald-400/80' },
                                    { label: 'Quad 3', val: selectedTeam.quad3, cls: 'bg-slate-800/50 border-slate-700/50 text-slate-300' },
                                    { label: 'Quad 4', val: selectedTeam.quad4, cls: 'bg-slate-800/30 border-slate-800/50 text-slate-400' },
                                ].map(({ label, val, cls }) => (
                                    <div key={label} className={`${cls} border rounded-xl p-4 flex flex-col items-center justify-center`}>
                                        <span className="text-[10px] font-bold uppercase mb-1 opacity-70">{label}</span>
                                        <span className="text-2xl font-black font-mono">{val || '—'}</span>
                                    </div>
                                ))}
                            </div>
                        )}

                        {/* Metrics Row */}
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                            {[
                                { icon: <TrendingUp size={16} />, label: 'AdjEM', val: selectedTeam.adj_em, fmt: `${selectedTeam.adj_em > 0 ? '+' : ''}${selectedTeam.adj_em}`, color: 'text-white' },
                                { icon: <Crosshair size={16} />, label: 'Adj Offense', val: selectedTeam.adj_o, fmt: selectedTeam.adj_o, color: getEfficiencyColor(selectedTeam.adj_o, false) },
                                { icon: <Shield size={16} />, label: 'Adj Defense', val: selectedTeam.adj_d, fmt: selectedTeam.adj_d, color: getEfficiencyColor(selectedTeam.adj_d, true) },
                                { icon: <Activity size={16} />, label: 'Tempo', val: selectedTeam.adj_t, fmt: selectedTeam.adj_t, color: 'text-white' },
                            ].map(({ icon, label, val, fmt, color }) => (
                                <div key={label} className="bg-slate-900 rounded-2xl p-5 border border-slate-800 shadow-lg">
                                    <div className="flex items-center gap-2 mb-2 text-slate-400">{icon}<span className="text-xs font-bold uppercase tracking-wider">{label}</span></div>
                                    <div className={`text-3xl font-black ${color}`}>{fmt}</div>
                                </div>
                            ))}
                        </div>

                        {/* Scouting + Roster */}
                        <div className="grid md:grid-cols-3 gap-8">
                            <div className="md:col-span-2 space-y-8">
                                {/* Scouting Report */}
                                <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl">
                                    <h2 className="text-xl font-bold text-white mb-6 flex items-center gap-2">
                                        <FileTextIcon className="text-blue-400" /> Scouting Report (2025-26)
                                    </h2>
                                    <div className="space-y-8">
                                        {[
                                            { heading: 'Offensive Profile', items: narrative.offense, color: 'text-blue-400', dotColor: 'bg-blue-500' },
                                            { heading: 'Defensive Profile', items: narrative.defense, color: 'text-purple-400', dotColor: 'bg-purple-500' },
                                        ].map(({ heading, items, color, dotColor }) => (
                                            <div key={heading}>
                                                <h3 className={`text-sm font-bold ${color} uppercase tracking-widest mb-3 flex items-center gap-2 pb-2 border-b border-slate-800`}>{heading}</h3>
                                                <ul className="space-y-3">
                                                    {(items || []).map((s, i) => (
                                                        <li key={i} className="flex items-start gap-3 text-slate-300 text-sm">
                                                            <span className={`w-1.5 h-1.5 rounded-full ${dotColor} mt-2 shrink-0`} />
                                                            <span className="leading-relaxed">{s}</span>
                                                        </li>
                                                    ))}
                                                </ul>
                                            </div>
                                        ))}
                                    </div>
                                </div>

                                {/* Upset Risk */}
                                <div className="bg-gradient-to-br from-rose-950/40 to-slate-900 border border-rose-900/30 rounded-2xl p-6 shadow-xl">
                                    <h2 className="text-xl font-bold text-white mb-4 flex items-center gap-2">
                                        <AlertTriangle className="text-rose-500" /> Volatility &amp; Upset Risk
                                    </h2>
                                    <p className="text-slate-300 text-sm leading-relaxed">{narrative.upsetFlags}</p>
                                </div>
                            </div>

                            {/* Key Personnel */}
                            <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-xl self-start">
                                <div className="bg-slate-800/50 p-4 border-b border-slate-800 flex justify-between items-center">
                                    <h2 className="text-lg font-bold text-white flex items-center gap-2">
                                        <Users className="text-blue-400" /> Key Personnel
                                    </h2>
                                </div>
                                <div className="divide-y divide-slate-800">
                                    {players.length > 0 ? players.map((p, i) => (
                                        <div key={i} className="p-4 hover:bg-slate-800/30 transition flex flex-col gap-2">
                                            <div className="flex justify-between items-start">
                                                <div>
                                                    <div className="font-bold text-slate-100 text-sm">{p.name} <span className="text-[10px] text-slate-500 ml-1">{p.pos}</span></div>
                                                    <div className="text-xs font-mono text-emerald-400 mt-1">{p.stats}</div>
                                                </div>
                                                <div className="grid grid-cols-2 gap-1 shrink-0">
                                                    <div className="bg-slate-950 px-2 py-0.5 rounded text-[9px] border border-slate-800 text-slate-400">ORtg <span className="text-slate-100">{p.adv?.ortg || 0}</span></div>
                                                    <div className="bg-slate-950 px-2 py-0.5 rounded text-[9px] border border-slate-800 text-slate-400">Usg% <span className="text-blue-300">{p.adv?.usg || 0}</span></div>
                                                </div>
                                            </div>
                                            <p className="text-[11px] text-slate-400 leading-tight italic border-l border-slate-700 pl-2">{p.role}</p>
                                        </div>
                                    )) : (
                                        <div className="p-6 text-center text-slate-500 text-sm">
                                            <Cpu size={20} className="mx-auto mb-2 text-slate-600" />
                                            Roster profiles generating…<br />
                                            <span className="text-xs">Click Refresh to trigger generation.</span>
                                        </div>
                                    )}
                                </div>
                            </div>
                        </div>
                    </div>
                </>
            ) : (
                /* ───── MATCHUP PREDICTOR MODE ───── */
                <div className="max-w-7xl mx-auto px-4 md:px-8 py-8 space-y-6 animate-in fade-in duration-500">

                    {/* Quantitative Edge Score (deterministic — no LLM) */}
                    {edgeScore !== null && (
                        <div className="bg-gradient-to-r from-purple-950/50 to-slate-900 border border-purple-500/20 rounded-2xl p-6">
                            <div className="flex flex-col md:flex-row items-center gap-6">
                                <div className="flex-1 text-center md:text-left">
                                    <div className="text-xs font-bold uppercase tracking-widest text-purple-400 mb-1 flex items-center gap-1 justify-center md:justify-start">
                                        <Target size={12} /> Quantitative Edge Score
                                    </div>
                                    <div className="text-xs text-slate-500 mb-3">Based on KenPom AdjEM differential — no LLM, deterministic model</div>
                                    <div className="flex items-center gap-4">
                                        <span className="text-2xl font-black text-blue-400">{selectedTeam.team_name} {edgeScore}%</span>
                                        <span className="text-slate-500">vs</span>
                                        <span className="text-2xl font-black text-rose-400">{selectedTeamB?.team_name} {100 - edgeScore}%</span>
                                    </div>
                                </div>
                                {/* Win probability gauge */}
                                <div className="w-full md:w-80">
                                    <div className="flex justify-between text-[10px] font-bold mb-1 text-slate-400">
                                        <span className="text-blue-400">{selectedTeam.team_name}</span>
                                        <span className="text-rose-400">{selectedTeamB?.team_name}</span>
                                    </div>
                                    <div className="h-4 w-full bg-slate-800 rounded-full overflow-hidden flex">
                                        <div className="h-full bg-gradient-to-r from-blue-600 to-blue-400 transition-all" style={{ width: `${edgeScore}%` }} />
                                        <div className="h-full bg-gradient-to-r from-rose-400 to-rose-600 flex-1 transition-all" />
                                    </div>
                                    <div className="flex justify-between text-xs font-black mt-1">
                                        <span className="text-blue-400">{edgeScore}%</span>
                                        <span className="text-rose-400">{100 - edgeScore}%</span>
                                    </div>
                                </div>
                            </div>
                        </div>
                    )}

                    {/* Team cards + Stat Comparison */}
                    <div className="grid md:grid-cols-5 gap-6 items-start">
                        {/* Team A */}
                        <div className="md:col-span-2 bg-slate-900 border border-blue-500/30 rounded-2xl p-6 shadow-xl relative overflow-hidden">
                            <div className="absolute top-0 right-0 w-32 h-32 bg-blue-500/10 rounded-full blur-3xl pointer-events-none" />
                            <div className="text-xs font-bold text-blue-400 uppercase tracking-widest mb-1 flex items-center gap-1">
                                <Award size={12} /> {selectedTeam.conference}
                            </div>
                            <h2 className="text-2xl font-black text-white mb-1">{selectedTeam.team_name}</h2>
                            <div className="text-xs text-slate-400 mb-4">
                                {selectedTeam.net_record || selectedTeam.record} • KP #{selectedTeam.rank}
                                {selectedTeam.net_rank && <span> • NET #{selectedTeam.net_rank}</span>}
                            </div>
                            <div className="grid grid-cols-2 gap-2 text-center text-sm">
                                {[
                                    { label: 'AdjEM', val: `${selectedTeam.adj_em > 0 ? '+' : ''}${selectedTeam.adj_em}`, color: 'text-white' },
                                    { label: 'Offense', val: selectedTeam.adj_o, color: getEfficiencyColor(selectedTeam.adj_o) },
                                    { label: 'Defense', val: selectedTeam.adj_d, color: getEfficiencyColor(selectedTeam.adj_d, true) },
                                    { label: 'Tempo', val: selectedTeam.adj_t, color: 'text-white' },
                                ].map(({ label, val, color }) => (
                                    <div key={label} className="bg-slate-950 p-2 rounded-lg border border-slate-800">
                                        <div className="text-[10px] text-slate-500 font-bold mb-1">{label}</div>
                                        <div className={`text-lg font-black ${color}`}>{val}</div>
                                    </div>
                                ))}
                            </div>
                            {/* Quad glance */}
                            {selectedTeam.quad1 && (
                                <div className="mt-3 grid grid-cols-4 gap-1 text-center text-[10px]">
                                    {['quad1', 'quad2', 'quad3', 'quad4'].map((q, i) => (
                                        <div key={q} className="bg-slate-800/50 rounded px-1 py-1">
                                            <div className="text-slate-600 font-bold">Q{i + 1}</div>
                                            <div className="text-slate-300 font-black">{selectedTeam[q] || '—'}</div>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>

                        {/* Stat Comparison Bars (center column) */}
                        <div className="md:col-span-1 flex items-center justify-center">
                            <div className="text-4xl font-black text-slate-700">VS</div>
                        </div>

                        {/* Team B */}
                        <div className="md:col-span-2 bg-slate-900 border border-rose-500/30 rounded-2xl p-6 shadow-xl relative overflow-hidden">
                            <div className="absolute top-0 right-0 w-32 h-32 bg-rose-500/10 rounded-full blur-3xl pointer-events-none" />
                            <div className="text-xs font-bold text-rose-400 uppercase tracking-widest mb-1 flex items-center gap-1">
                                <Award size={12} /> {selectedTeamB?.conference}
                            </div>
                            <h2 className="text-2xl font-black text-white mb-1">{selectedTeamB?.team_name}</h2>
                            <div className="text-xs text-slate-400 mb-4">
                                {selectedTeamB?.net_record || selectedTeamB?.record} • KP #{selectedTeamB?.rank}
                                {selectedTeamB?.net_rank && <span> • NET #{selectedTeamB?.net_rank}</span>}
                            </div>
                            <div className="grid grid-cols-2 gap-2 text-center text-sm">
                                {[
                                    { label: 'AdjEM', val: `${selectedTeamB?.adj_em > 0 ? '+' : ''}${selectedTeamB?.adj_em}`, color: 'text-white' },
                                    { label: 'Offense', val: selectedTeamB?.adj_o, color: getEfficiencyColor(selectedTeamB?.adj_o) },
                                    { label: 'Defense', val: selectedTeamB?.adj_d, color: getEfficiencyColor(selectedTeamB?.adj_d, true) },
                                    { label: 'Tempo', val: selectedTeamB?.adj_t, color: 'text-white' },
                                ].map(({ label, val, color }) => (
                                    <div key={label} className="bg-slate-950 p-2 rounded-lg border border-slate-800">
                                        <div className="text-[10px] text-slate-500 font-bold mb-1">{label}</div>
                                        <div className={`text-lg font-black ${color}`}>{val}</div>
                                    </div>
                                ))}
                            </div>
                            {selectedTeamB?.quad1 && (
                                <div className="mt-3 grid grid-cols-4 gap-1 text-center text-[10px]">
                                    {['quad1', 'quad2', 'quad3', 'quad4'].map((q, i) => (
                                        <div key={q} className="bg-slate-800/50 rounded px-1 py-1">
                                            <div className="text-slate-600 font-bold">Q{i + 1}</div>
                                            <div className="text-slate-300 font-black">{selectedTeamB[q] || '—'}</div>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>
                    </div>

                    {/* Side-by-side Stat Bars */}
                    <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl">
                        <h3 className="text-sm font-bold text-slate-300 uppercase tracking-widest mb-4 flex items-center gap-2">
                            <Swords size={14} className="text-purple-400" /> Head-to-Head Stat Comparison
                        </h3>
                        <div className="grid grid-cols-[1fr_80px_1fr] gap-1 text-center text-[10px] font-bold text-slate-500 uppercase mb-2">
                            <div className="text-right text-blue-400">{selectedTeam.team_name}</div>
                            <div>Metric</div>
                            <div className="text-left text-rose-400">{selectedTeamB?.team_name}</div>
                        </div>
                        <StatBar label="AdjEM" valA={selectedTeam.adj_em} valB={selectedTeamB?.adj_em} />
                        <StatBar label="Adj Offense" valA={selectedTeam.adj_o} valB={selectedTeamB?.adj_o} />
                        <StatBar label="Adj Defense" valA={selectedTeam.adj_d} valB={selectedTeamB?.adj_d} lowerIsBetter />
                        <StatBar label="Tempo" valA={selectedTeam.adj_t} valB={selectedTeamB?.adj_t} />
                        {(selectedTeam.torvik?.barthag || selectedTeamB?.torvik?.barthag) && (
                            <StatBar
                                label="Barthag"
                                valA={selectedTeam.torvik?.barthag ? (selectedTeam.torvik.barthag * 100) : 0}
                                valB={selectedTeamB?.torvik?.barthag ? (selectedTeamB.torvik.barthag * 100) : 0}
                                fmtA={selectedTeam.torvik?.barthag ? `${(selectedTeam.torvik.barthag * 100).toFixed(1)}%` : '—'}
                                fmtB={selectedTeamB?.torvik?.barthag ? `${(selectedTeamB.torvik.barthag * 100).toFixed(1)}%` : '—'}
                            />
                        )}
                        {(selectedTeam.net_rank || selectedTeamB?.net_rank) && (
                            <StatBar
                                label="NET Rank"
                                valA={selectedTeam.net_rank || 999}
                                valB={selectedTeamB?.net_rank || 999}
                                lowerIsBetter
                                fmtA={selectedTeam.net_rank ? `#${selectedTeam.net_rank}` : '—'}
                                fmtB={selectedTeamB?.net_rank ? `#${selectedTeamB.net_rank}` : '—'}
                            />
                        )}
                    </div>

                    {/* AI Tactical Analysis */}
                    <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 md:p-8 shadow-2xl relative">
                        <h3 className="text-sm font-bold text-slate-300 uppercase tracking-widest mb-6 flex items-center gap-2">
                            <Cpu size={14} className="text-purple-400" /> AI Tactical Analysis
                        </h3>
                        {loadingMatchup ? (
                            <div className="flex flex-col items-center justify-center py-12 text-slate-400 font-mono gap-4 animate-pulse">
                                <Cpu size={32} className="text-purple-500" />
                                <span>Generating tactical synthesis…</span>
                            </div>
                        ) : matchupData ? (
                            <div className="space-y-8">
                                <div className="text-center pb-8 border-b border-slate-800">
                                    <div className="inline-block px-4 py-1 rounded-full bg-purple-500/10 border border-purple-500/30 text-purple-400 font-bold text-xs uppercase tracking-widest mb-4">
                                        AI Predicted Winner
                                    </div>
                                    <h3 className="text-4xl md:text-5xl font-black text-white mb-2">{matchupData.predicted_winner}</h3>
                                    <div className="text-slate-500 text-sm font-bold uppercase tracking-wider">
                                        Confidence: <span className={matchupData.confidence === 'High' ? 'text-emerald-400' : matchupData.confidence === 'Medium' ? 'text-blue-400' : 'text-rose-400'}>{matchupData.confidence}</span>
                                    </div>
                                    <p className="mt-6 text-slate-300 italic text-lg max-w-2xl mx-auto leading-relaxed">"{matchupData.summary}"</p>
                                </div>
                                <div className="grid md:grid-cols-2 gap-8">
                                    {[
                                        { team: selectedTeam.team_name, advantages: matchupData.team_a_advantages, color: 'text-blue-400', dot: 'bg-blue-500' },
                                        { team: selectedTeamB?.team_name, advantages: matchupData.team_b_advantages, color: 'text-rose-400', dot: 'bg-rose-500' },
                                    ].map(({ team, advantages, color, dot }) => (
                                        <div key={team} className="bg-slate-950/50 p-6 rounded-xl border border-slate-800">
                                            <h4 className={`text-sm font-bold ${color} uppercase tracking-widest mb-4 flex items-center gap-2`}>
                                                <TrendingUp size={16} /> {team} Advantages
                                            </h4>
                                            <ul className="space-y-3">
                                                {(advantages || []).map((adv, i) => (
                                                    <li key={i} className="flex gap-3 text-sm text-slate-300 items-start">
                                                        <div className={`w-1.5 h-1.5 rounded-full ${dot} shrink-0 mt-1.5`} />
                                                        <span className="leading-relaxed">{adv}</span>
                                                    </li>
                                                ))}
                                            </ul>
                                        </div>
                                    ))}
                                </div>
                                {matchupData.key_matchup && (
                                    <div className="bg-purple-900/10 border border-purple-500/20 rounded-xl p-6">
                                        <h4 className="text-sm font-bold text-purple-400 uppercase tracking-widest mb-3 flex items-center gap-2">
                                            <Swords size={16} /> Key Matchup to Watch
                                        </h4>
                                        <p className="text-slate-300 text-sm leading-relaxed">{matchupData.key_matchup}</p>
                                    </div>
                                )}
                            </div>
                        ) : (
                            <div className="text-center py-12 text-slate-500 font-mono">
                                Select two teams and click the Matchup tab to generate AI analysis.
                            </div>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
};

/* ── Inline icon helpers ── */
const FileTextIcon = (props) => (
    <svg {...props} xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" /><line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" /><polyline points="10 9 9 9 8 9" />
    </svg>
);

export default MarchMadness;
