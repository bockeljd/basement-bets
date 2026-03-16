import React, { useState, useEffect, useMemo, useCallback } from 'react';
import api from '../api/axios';
import {
    Shield, Crosshair, Activity, AlertTriangle, Users, TrendingUp,
    Cpu, RefreshCw, Swords, Search, Target, Award, Star, Zap, Layout, ChevronDown, ChevronUp
} from 'lucide-react';

/* ─── Helpers ─── */
const getColorEff = (v, isDefensive = false) => {
    if (v == null) return 'text-slate-400';
    const n = parseFloat(v);
    if (isDefensive) {
        if (n < 90) return 'text-purple-400'; if (n < 95) return 'text-emerald-400';
        if (n > 105) return 'text-red-400'; return 'text-slate-300';
    } else {
        if (n > 120) return 'text-purple-400'; if (n > 112) return 'text-emerald-400';
        if (n < 100) return 'text-red-400'; return 'text-slate-300';
    }
};

// Logistic win-probability from AdjEM diff
function emToWinPct(emA, emB) {
    const diff = (parseFloat(emA) || 0) - (parseFloat(emB) || 0);
    return Math.round((1 / (1 + Math.exp(-diff / 10))) * 100);
}

// Circular gauge
function Gauge({ score = 0, label, color = '#f97316', subLabel }) {
    const radius = 36; const circ = 2 * Math.PI * radius;
    const pct = Math.max(0, Math.min(100, score));
    const dash = (pct / 100) * circ;
    const riskColor = pct < 30 ? '#22c55e' : pct < 60 ? '#f59e0b' : '#ef4444';
    const fillColor = label === 'Dark Horse' ? '#f59e0b' : riskColor;
    return (
        <div className="flex flex-col items-center gap-1">
            <svg width="90" height="90" viewBox="0 0 90 90">
                <circle cx="45" cy="45" r={radius} fill="none" stroke="#1e293b" strokeWidth="7" />
                <circle cx="45" cy="45" r={radius} fill="none" stroke={fillColor} strokeWidth="7"
                    strokeDasharray={`${dash} ${circ}`} strokeLinecap="round"
                    transform="rotate(-90 45 45)" className="transition-all duration-700" />
                <text x="45" y="49" textAnchor="middle" fontSize="16" fontWeight="900" fill="white">{pct}</text>
            </svg>
            <div className="text-xs font-black uppercase tracking-widest" style={{ color: fillColor }}>{label}</div>
            {subLabel && <div className="text-[10px] text-slate-500 text-center">{subLabel}</div>}
        </div>
    );
}

// Stat bar with two teams
function StatBar({ label, valA, valB, lowerIsBetter = false, fmtA, fmtB }) {
    const a = parseFloat(valA) || 0; const b = parseFloat(valB) || 0;
    const aWins = lowerIsBetter ? a < b : a > b; const bWins = lowerIsBetter ? b < a : b > a;
    const max = Math.max(Math.abs(a), Math.abs(b), 1);
    const pA = Math.min(100, (Math.abs(a) / max) * 100);
    const pB = Math.min(100, (Math.abs(b) / max) * 100);
    return (
        <div className="grid grid-cols-[1fr_72px_1fr] gap-2 items-center py-2 border-b border-slate-800/40 last:border-0">
            <div className="flex items-center justify-end gap-2">
                <span className={`text-sm font-black tabular-nums ${aWins ? 'text-emerald-400' : 'text-slate-300'}`}>{fmtA ?? (a ? a.toFixed(1) : '—')}</span>
                <div className="w-20 h-2 bg-slate-800 rounded-full overflow-hidden flex justify-end">
                    <div className={`h-full rounded-full ${aWins ? 'bg-blue-500' : 'bg-slate-600'}`} style={{ width: `${pA}%` }} />
                </div>
            </div>
            <div className="text-center text-[10px] font-bold text-slate-500 uppercase tracking-wider leading-tight">{label}</div>
            <div className="flex items-center gap-2">
                <div className="w-20 h-2 bg-slate-800 rounded-full overflow-hidden">
                    <div className={`h-full rounded-full ${bWins ? 'bg-rose-500' : 'bg-slate-600'}`} style={{ width: `${pB}%` }} />
                </div>
                <span className={`text-sm font-black tabular-nums ${bWins ? 'text-emerald-400' : 'text-slate-300'}`}>{fmtB ?? (b ? b.toFixed(1) : '—')}</span>
            </div>
        </div>
    );
}

// Player stats table
function PlayerStatsTable({ players = [] }) {
    if (!players.length) return (
        <div className="p-6 text-center text-slate-500 text-sm">
            <Cpu size={20} className="mx-auto mb-2 text-slate-600 animate-pulse" />
            Player data loading…
        </div>
    );
    const fmt = (v) => v != null ? v.toFixed(1) : '—';
    return (
        <div className="overflow-x-auto">
            <table className="w-full text-xs">
                <thead>
                    <tr className="border-b border-slate-800 text-slate-500 uppercase tracking-wider">
                        <th className="text-left py-2 px-3 font-bold">Player</th>
                        <th className="text-center py-2 px-2 font-bold">PPG</th>
                        <th className="text-center py-2 px-2 font-bold">APG</th>
                        <th className="text-center py-2 px-2 font-bold">RPG</th>
                        <th className="text-center py-2 px-2 font-bold">ORtg</th>
                        <th className="text-center py-2 px-2 font-bold">Usg%</th>
                        <th className="text-center py-2 px-2 font-bold">eFG%</th>
                        <th className="text-center py-2 px-2 font-bold">Min%</th>
                    </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/50">
                    {players.map((p, i) => (
                        <tr key={i} className="hover:bg-slate-800/30 transition">
                            <td className="py-2 px-3 font-bold text-slate-100">{p.name}</td>
                            <td className="py-2 px-2 text-center text-emerald-400 font-black">{fmt(p.ppg)}</td>
                            <td className="py-2 px-2 text-center text-blue-400">{fmt(p.apg)}</td>
                            <td className="py-2 px-2 text-center text-purple-400">{fmt(p.rpg)}</td>
                            <td className="py-2 px-2 text-center tabular-nums">{fmt(p.ortg)}</td>
                            <td className="py-2 px-2 text-center text-orange-400">{fmt(p.usg)}%</td>
                            <td className="py-2 px-2 text-center">{fmt(p.efg)}%</td>
                            <td className="py-2 px-2 text-center text-slate-400">{fmt(p.min_pct)}%</td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    );
}

/* ─── Main Component ─── */
const MarchMadness = () => {
    const TABS = ['profile', 'matchup', 'darkhorse', 'bracket'];
    const [activeTab, setActiveTab] = useState('profile');
    const [loading, setLoading] = useState(true);
    const [teams, setTeams] = useState([]);
    const [search, setSearch] = useState('');
    const [selectedTeam, setSelectedTeam] = useState(null);
    const [selectedTeamB, setSelectedTeamB] = useState(null);

    // Deep profile data (fetched on demand)
    const [deepA, setDeepA] = useState(null);
    const [deepB, setDeepB] = useState(null);
    const [loadingDeepA, setLoadingDeepA] = useState(false);
    const [loadingDeepB, setLoadingDeepB] = useState(false);

    // AI matchup data
    const [matchupData, setMatchupData] = useState(null);
    const [loadingMatchup, setLoadingMatchup] = useState(false);

    // Dark horse sorted list
    const [dhLoading, setDhLoading] = useState(false);
    const [dhProfiles, setDhProfiles] = useState([]);

    // Bracket data
    const [bracketData, setBracketData] = useState(null);
    const [loadingBracket, setLoadingBracket] = useState(false);

    useEffect(() => { fetchTeams(); }, []);

    const fetchTeams = async () => {
        setLoading(true);
        try {
            const res = await api.get('/api/ncaam/tournament-teams', { params: { limit: 80 } });
            const all = res.data.teams || [];
            if (all.length > 0) {
                setTeams(all);
                const def = all.find(t => t.team_name.includes('Connecticut') || t.team_name.includes('UConn')) || all[0];
                const def2 = all.find(t => t.team_name.includes('North Carolina')) || all[1];
                setSelectedTeam(v => v || def);
                setSelectedTeamB(v => v || def2);
            }
        } catch (e) { console.error(e); } finally { setLoading(false); }
    };

    const fetchDeepProfile = useCallback(async (teamName, setter, setLoading) => {
        if (!teamName) return;
        setLoading(true);
        try {
            const res = await api.get('/api/ncaam/team-deep-profile', { params: { team: teamName } });
            setter(res.data);
        } catch (e) { console.error('Deep profile error', e); setter(null); }
        finally { setLoading(false); }
    }, []);

    // Fetch deep profile whenever selected team changes
    useEffect(() => {
        if (selectedTeam) fetchDeepProfile(selectedTeam.team_name, setDeepA, setLoadingDeepA);
    }, [selectedTeam?.team_name]);

    useEffect(() => {
        if (selectedTeamB && activeTab === 'matchup') fetchDeepProfile(selectedTeamB.team_name, setDeepB, setLoadingDeepB);
    }, [selectedTeamB?.team_name, activeTab]);

    // AI matchup
    const fetchMatchup = async () => {
        if (!selectedTeam || !selectedTeamB || selectedTeam.team_name === selectedTeamB.team_name) return;
        setLoadingMatchup(true); setMatchupData(null);
        try {
            const res = await api.get('/api/ncaam/matchup', {
                params: { team_a: selectedTeam.team_name, team_b: selectedTeamB.team_name }
            });
            setMatchupData(res.data.analysis);
        } catch (e) { setMatchupData({ summary: 'Analysis failed.', confidence: 'N/A', predicted_winner: 'Error' }); }
        finally { setLoadingMatchup(false); }
    };

    useEffect(() => {
        if (activeTab === 'matchup' && selectedTeam && selectedTeamB) fetchMatchup();
    }, [activeTab, selectedTeam?.team_name, selectedTeamB?.team_name]);

    // Dark Horse Explorer: fetch all 80 teams' dark horse scores
    const fetchDarkHorse = async () => {
        setDhLoading(true);
        try {
            const subset = teams.slice(0, 40); // top 40 by KenPom to keep latency manageable
            const results = await Promise.allSettled(
                subset.map(t =>
                    api.get('/api/ncaam/team-deep-profile', { params: { team: t.team_name } })
                       .then(r => ({ ...r.data, kp_rank: t.rank, conference: t.conference }))
                )
            );
            const data = results
                .filter(r => r.status === 'fulfilled')
                .map(r => r.value)
                .sort((a, b) => (b.dark_horse?.score || 0) - (a.dark_horse?.score || 0));
            setDhProfiles(data);
        } catch (e) { console.error(e); }
        finally { setDhLoading(false); }
    };

    useEffect(() => {
        if (activeTab === 'darkhorse' && dhProfiles.length === 0) fetchDarkHorse();
    }, [activeTab]);

    const fetchBracket = async () => {
        setLoadingBracket(true);
        try {
            const res = await api.get('/api/ncaam/bracket/2026');
            setBracketData(res.data);
        } catch (e) {
            console.error('Bracket fetch error', e);
        } finally {
            setLoadingBracket(false);
        }
    };

    useEffect(() => {
        if (activeTab === 'bracket' && !bracketData) fetchBracket();
    }, [activeTab]);

    const handleMatchupClick = (teamA, teamB) => {
        const tA = teams.find(t => t.team_name === teamA || teamA.includes(t.team_name) || t.team_name.includes(teamA));
        const tB = teams.find(t => t.team_name === teamB || teamB.includes(t.team_name) || t.team_name.includes(teamB));
        if (tA) setSelectedTeam(tA);
        if (tB) setSelectedTeamB(tB);
        setActiveTab('matchup');
        window.scrollTo({ top: 0, behavior: 'smooth' });
    };

    const filteredTeams = useMemo(() => {
        if (!search.trim()) return teams;
        const q = search.toLowerCase();
        return teams.filter(t => t.team_name.toLowerCase().includes(q));
    }, [teams, search]);

    const edgeScore = useMemo(() =>
        (selectedTeam && selectedTeamB) ? emToWinPct(selectedTeam.adj_em, selectedTeamB.adj_em) : null,
        [selectedTeam, selectedTeamB]);

    if (loading && !teams.length) return (
        <div className="p-8 flex flex-col items-center justify-center min-h-[400px] gap-3 text-slate-400 animate-pulse">
            <Cpu size={32} className="text-orange-500 animate-bounce" />
            Loading Tournament Profile Engine…
        </div>
    );
    if (!selectedTeam) return <div className="p-8 text-center text-red-400 font-mono">No team data found.</div>;

    const teamSelect = (side) => (
        <select
            className={`bg-slate-800 border border-slate-700 rounded px-3 py-1.5 text-sm font-bold focus:outline-none focus:ring-1 max-w-[180px] ${side === 'A' ? 'text-blue-400 focus:ring-blue-500' : 'text-rose-400 focus:ring-rose-500'}`}
            value={side === 'A' ? selectedTeam.team_name : (selectedTeamB?.team_name || '')}
            onChange={e => {
                const t = teams.find(x => x.team_name === e.target.value);
                if (t) side === 'A' ? setSelectedTeam(t) : setSelectedTeamB(t);
            }}
        >
            {(search ? filteredTeams : teams).map(t => (
                <option key={t.team_name} value={t.team_name}
                    disabled={side === 'B' && t.team_name === selectedTeam.team_name}>
                    {t.seed ? `[#${t.seed}] ` : `[KP #${t.rank}] `} {t.team_name}
                </option>
            ))}
        </select>
    );

    return (
        <div className="bg-slate-950 text-white pb-20 rounded-2xl overflow-hidden">
            {/* Action Bar */}
            <div className="flex items-center justify-between p-4 border-b border-slate-800 bg-slate-900/50 backdrop-blur-md flex-wrap gap-3">
                <div className="flex items-center gap-3 flex-wrap">
                    <div className="hidden md:flex items-center gap-2 text-xs font-bold text-slate-500 uppercase tracking-widest">
                        <Cpu size={14} className="text-orange-500" /> Profiler v2.3
                    </div>
                    {/* Main tab toggle */}
                    <div className="flex bg-slate-800 p-1 rounded-lg border border-slate-700">
                        <button onClick={() => setActiveTab('profile')}
                            className={`px-3 py-1.5 rounded-md text-xs font-bold transition ${activeTab === 'profile' ? 'bg-blue-600 text-white shadow-md' : 'text-slate-400 hover:text-white'}`}>
                            Team Profile
                        </button>
                        <button onClick={() => setActiveTab('matchup')}
                            className={`px-3 py-1.5 rounded-md text-xs font-bold flex items-center gap-1 transition ${activeTab === 'matchup' ? 'bg-purple-600 text-white shadow-md' : 'text-slate-400 hover:text-white'}`}>
                            <Swords size={12} /> Matchup
                        </button>
                        <button onClick={() => setActiveTab('darkhorse')}
                            className={`px-3 py-1.5 rounded-md text-xs font-bold flex items-center gap-1 transition ${activeTab === 'darkhorse' ? 'bg-yellow-500 text-black shadow-md' : 'text-slate-400 hover:text-white'}`}>
                            <Star size={12} /> Dark Horses
                        </button>
                        <button onClick={() => setActiveTab('bracket')}
                            className={`px-3 py-1.5 rounded-md text-xs font-bold flex items-center gap-1 transition ${activeTab === 'bracket' ? 'bg-orange-600 text-white shadow-md' : 'text-slate-400 hover:text-white'}`}>
                            <Layout size={12} /> Bracket 2026
                        </button>
                    </div>

                    {/* Team search + selectors */}
                    <div className="flex items-center gap-2 flex-wrap">
                        <div className="relative">
                            <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-slate-500" />
                            <input
                                type="text" placeholder="Search…" value={search}
                                onChange={e => { setSearch(e.target.value); }}
                                className="pl-6 pr-2 py-1.5 bg-slate-800 border border-slate-700 rounded text-sm text-white placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-blue-500 w-32"
                            />
                        </div>
                        {teamSelect('A')}
                        {activeTab === 'matchup' && (
                            <><span className="text-slate-500 text-xs font-bold italic">VS</span>{teamSelect('B')}</>
                        )}
                    </div>
                </div>
                <button
                    onClick={() => {
                        if (activeTab === 'darkhorse') fetchDarkHorse();
                        else if (activeTab === 'bracket') fetchBracket();
                        else if (activeTab === 'matchup') { fetchMatchup(); fetchDeepProfile(selectedTeam.team_name, setDeepA, setLoadingDeepA); fetchDeepProfile(selectedTeamB?.team_name, setDeepB, setLoadingDeepB); }
                        else fetchDeepProfile(selectedTeam.team_name, setDeepA, setLoadingDeepA);
                    }}
                    className="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-white transition"
                    title="Refresh">
                    <RefreshCw size={14} className={(loading || loadingDeepA || loadingMatchup || dhLoading || loadingBracket) ? 'animate-spin' : ''} />
                </button>
            </div>

            {/* ════ TEAM PROFILE TAB ════ */}
            {activeTab === 'profile' && (
                <>
                    {/* Hero */}
                    <div className="relative overflow-hidden border-b border-slate-800">
                        <div className="absolute inset-0 bg-gradient-to-br from-blue-900/40 via-slate-900 to-slate-950 opacity-80" />
                        <div className="absolute top-0 right-0 w-96 h-96 bg-blue-600/10 rounded-full blur-[100px] pointer-events-none" />
                        <div className="relative px-6 py-10 md:px-12 max-w-7xl mx-auto flex flex-col md:flex-row items-center md:items-start gap-8">
                            <div className="flex flex-col items-center shrink-0">
                                <div className="w-28 h-28 bg-slate-900 rounded-3xl border border-slate-700 shadow-2xl flex items-center justify-center text-6xl relative">
                                    <div className="absolute inset-0 bg-gradient-to-tr from-blue-500/10 to-transparent rounded-3xl" />🏀
                                </div>
                                <div className="mt-3 px-4 py-1.5 rounded-full bg-slate-800 border border-slate-700 text-sm font-black text-slate-200 flex items-center gap-1.5">
                                    {selectedTeam.seed ? (
                                        <><Layout size={12} className="text-orange-500" /> Seed #{selectedTeam.seed}</>
                                    ) : (
                                        <>KP #{selectedTeam.rank}</>
                                    )}
                                </div>
                                {selectedTeam.region && (
                                    <div className="mt-1.5 px-4 py-1 rounded-full bg-blue-900/40 border border-blue-600/30 text-xs font-bold text-blue-300 italic">
                                        {selectedTeam.region} Region
                                    </div>
                                )}
                                {(deepA?.net?.net_rank || selectedTeam.net_rank) && (
                                    <div className="mt-1.5 px-4 py-1 rounded-full bg-orange-900/30 border border-orange-600/30 text-xs font-bold text-orange-300">
                                        NET #{deepA?.net?.net_rank || selectedTeam.net_rank}
                                    </div>
                                )}
                            </div>
                            <div className="text-center md:text-left flex-1">
                                <div className="text-blue-400 font-bold tracking-widest uppercase text-sm mb-2">{selectedTeam.conference}</div>
                                <h1 className="text-4xl md:text-5xl font-black text-white mb-3 tracking-tight">{selectedTeam.team_name}</h1>
                                <div className="flex flex-wrap items-center justify-center md:justify-start gap-3 mb-4">
                                    <div className="flex bg-slate-800/80 rounded-lg border border-slate-700/50 p-1 text-sm font-mono text-slate-300">
                                        <span className="px-3 bg-slate-900 rounded font-bold text-white border border-slate-700/50">
                                            {deepA?.net?.record || selectedTeam.net_record || selectedTeam.record || '—'} OVR
                                        </span>
                                        {selectedTeam.home_record && <span className="px-3 border-r border-slate-700/50">{selectedTeam.home_record} H</span>}
                                        {selectedTeam.road_record && <span className="px-3 border-r border-slate-700/50">{selectedTeam.road_record} A</span>}
                                        {selectedTeam.neutral_record && <span className="px-3">{selectedTeam.neutral_record} N</span>}
                                    </div>
                                    <span className="text-slate-400 text-sm font-bold">
                                        Barthag <span className="text-white ml-1">
                                            {deepA?.torvik?.barthag ? `${(parseFloat(deepA.torvik.barthag) * 100).toFixed(1)}%` : (selectedTeam.torvik?.barthag ? `${(selectedTeam.torvik.barthag * 100).toFixed(1)}%` : '—')}
                                        </span>
                                    </span>
                                </div>
                            </div>
                        </div>
                    </div>

                    <div className="max-w-7xl mx-auto px-4 md:px-8 py-8 space-y-8">
                        {/* Upset Risk + Dark Horse gauges */}
                        {(deepA?.upset_risk || deepA?.dark_horse) && (
                            <div className="grid md:grid-cols-2 gap-6">
                                {deepA.upset_risk && (
                                    <div className="bg-gradient-to-br from-red-950/40 to-slate-900 border border-red-900/30 rounded-2xl p-6 flex gap-6 items-start">
                                        <Gauge score={deepA.upset_risk.score} label="Upset Risk" />
                                        <div className="flex-1">
                                            <div className="text-sm font-bold text-red-400 uppercase tracking-widest mb-3">Upset Risk Factors</div>
                                            <ul className="space-y-2">
                                                {deepA.upset_risk.factors.map((f, i) => (
                                                    <li key={i} className="flex items-start gap-2 text-xs text-slate-300">
                                                        <AlertTriangle size={10} className="text-red-400 mt-0.5 shrink-0" />
                                                        <span className="leading-relaxed">{f}</span>
                                                    </li>
                                                ))}
                                            </ul>
                                        </div>
                                    </div>
                                )}
                                {deepA.dark_horse && (
                                    <div className="bg-gradient-to-br from-yellow-950/40 to-slate-900 border border-yellow-900/30 rounded-2xl p-6 flex gap-6 items-start">
                                        <Gauge score={deepA.dark_horse.score} label="Dark Horse" />
                                        <div className="flex-1">
                                            <div className="text-sm font-bold text-yellow-400 uppercase tracking-widest mb-3">Dark Horse Signals</div>
                                            <ul className="space-y-2">
                                                {deepA.dark_horse.factors.map((f, i) => (
                                                    <li key={i} className="flex items-start gap-2 text-xs text-slate-300">
                                                        <Star size={10} className="text-yellow-400 mt-0.5 shrink-0" />
                                                        <span className="leading-relaxed">{f}</span>
                                                    </li>
                                                ))}
                                            </ul>
                                        </div>
                                    </div>
                                )}
                            </div>
                        )}

                        {/* Quad records */}
                        {(selectedTeam.quad1 || deepA?.net?.quad1) && (
                            <div className="grid grid-cols-4 gap-4">
                                {[
                                    { label: 'Quad 1', val: deepA?.net?.quad1 || selectedTeam.quad1, cls: 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400' },
                                    { label: 'Quad 2', val: deepA?.net?.quad2 || selectedTeam.quad2, cls: 'bg-emerald-500/5 border-emerald-500/10 text-emerald-400/80' },
                                    { label: 'Quad 3', val: deepA?.net?.quad3 || selectedTeam.quad3, cls: 'bg-slate-800/50 border-slate-700/50 text-slate-300' },
                                    { label: 'Quad 4', val: deepA?.net?.quad4 || selectedTeam.quad4, cls: 'bg-slate-800/30 border-slate-800/50 text-slate-400' },
                                ].map(({ label, val, cls }) => (
                                    <div key={label} className={`${cls} border rounded-xl p-4 flex flex-col items-center`}>
                                        <span className="text-[10px] font-bold uppercase mb-1 opacity-70">{label}</span>
                                        <span className="text-2xl font-black font-mono">{val || '—'}</span>
                                    </div>
                                ))}
                            </div>
                        )}

                        {/* Efficiency metrics */}
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                            {[
                                { icon: <TrendingUp size={16} />, label: 'AdjEM', val: selectedTeam.adj_em, fmt: `${selectedTeam.adj_em > 0 ? '+' : ''}${selectedTeam.adj_em}`, color: 'text-white' },
                                { icon: <Crosshair size={16} />, label: 'Adj Offense', val: selectedTeam.adj_o, fmt: selectedTeam.adj_o, color: getColorEff(selectedTeam.adj_o) },
                                { icon: <Shield size={16} />, label: 'Adj Defense', val: selectedTeam.adj_d, fmt: selectedTeam.adj_d, color: getColorEff(selectedTeam.adj_d, true) },
                                { icon: <Activity size={16} />, label: 'Tempo', val: selectedTeam.adj_t, fmt: selectedTeam.adj_t, color: 'text-white' },
                            ].map(({ icon, label, fmt, color }) => (
                                <div key={label} className="bg-slate-900 rounded-2xl p-5 border border-slate-800 shadow-lg">
                                    <div className="flex items-center gap-2 mb-2 text-slate-400">{icon}<span className="text-xs font-bold uppercase tracking-wider">{label}</span></div>
                                    <div className={`text-3xl font-black ${color}`}>{fmt}</div>
                                </div>
                            ))}
                        </div>

                        {/* Torvik deep metrics */}
                        {deepA?.torvik && Object.keys(deepA.torvik).length > 0 && (
                            <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6">
                                <h3 className="text-sm font-bold text-slate-300 uppercase tracking-widest mb-4 flex items-center gap-2">
                                    <Zap size={14} className="text-blue-400" /> Torvik Deep Metrics
                                </h3>
                                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                                    {[
                                        { label: 'Adj Off', val: deepA.torvik.adj_off, color: getColorEff(deepA.torvik.adj_off) },
                                        { label: 'Adj Def', val: deepA.torvik.adj_def, color: getColorEff(deepA.torvik.adj_def, true) },
                                        { label: 'Luck', val: deepA.torvik.luck, fmt: (v) => v != null ? `${parseFloat(v) >= 0 ? '+' : ''}${parseFloat(v).toFixed(3)}` : '—', color: (v) => parseFloat(v) > 0 ? 'text-red-400' : 'text-emerald-400' },
                                        { label: 'Continuity', val: deepA.torvik.continuity, fmt: (v) => v != null ? `${parseFloat(v).toFixed(0)}%` : '—', color: (v) => parseFloat(v) >= 75 ? 'text-emerald-400' : parseFloat(v) < 60 ? 'text-red-400' : 'text-slate-300' },
                                    ].map(({ label, val, fmt, color }) => (
                                        <div key={label} className="bg-slate-800/40 rounded-xl p-4 border border-slate-700/50">
                                            <div className="text-[10px] font-bold uppercase text-slate-500 mb-1">{label}</div>
                                            <div className={`text-xl font-black ${typeof color === 'function' ? color(val) : color}`}>
                                                {fmt ? fmt(val) : (val != null ? parseFloat(val).toFixed(1) : '—')}
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}

                        {/* Player Stats Table */}
                        <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-xl">
                            <div className="bg-slate-800/50 p-4 border-b border-slate-800">
                                <h2 className="text-lg font-bold text-white flex items-center gap-2">
                                    <Users className="text-blue-400" /> Player Stats (KenPom — by mins played)
                                </h2>
                            </div>
                            {loadingDeepA ? (
                                <div className="p-8 text-center text-slate-500 animate-pulse text-sm">Loading player data…</div>
                            ) : (
                                <PlayerStatsTable players={deepA?.players || []} />
                            )}
                        </div>
                    </div>
                </>
            )}

            {/* ════ MATCHUP TAB ════ */}
            {activeTab === 'matchup' && (
                <div className="max-w-7xl mx-auto px-4 md:px-8 py-8 space-y-6 animate-in fade-in duration-500">
                    {/* Win probability gauge */}
                    {edgeScore != null && (
                        <div className="bg-gradient-to-r from-purple-950/50 to-slate-900 border border-purple-500/20 rounded-2xl p-6">
                            <div className="flex flex-col md:flex-row items-center gap-6">
                                <div className="flex-1">
                                    <div className="text-xs font-bold uppercase tracking-widest text-purple-400 mb-1 flex items-center gap-1"><Target size={12} /> Quantitative Edge (AdjEM)</div>
                                    <div className="flex items-center gap-4 mt-2">
                                        <span className="text-2xl font-black text-blue-400">{selectedTeam.team_name} {edgeScore}%</span>
                                        <span className="text-slate-500">vs</span>
                                        <span className="text-2xl font-black text-rose-400">{selectedTeamB?.team_name} {100 - edgeScore}%</span>
                                    </div>
                                </div>
                                <div className="w-full md:w-72">
                                    <div className="flex justify-between text-[10px] font-bold mb-1 text-slate-400">
                                        <span className="text-blue-400">{selectedTeam.team_name}</span>
                                        <span className="text-rose-400">{selectedTeamB?.team_name}</span>
                                    </div>
                                    <div className="h-4 w-full bg-slate-800 rounded-full overflow-hidden flex">
                                        <div className="h-full bg-gradient-to-r from-blue-600 to-blue-400" style={{ width: `${edgeScore}%` }} />
                                        <div className="h-full bg-gradient-to-r from-rose-400 to-rose-600 flex-1" />
                                    </div>
                                    <div className="flex justify-between text-xs font-black mt-1">
                                        <span className="text-blue-400">{edgeScore}%</span>
                                        <span className="text-rose-400">{100 - edgeScore}%</span>
                                    </div>
                                </div>
                            </div>
                        </div>
                    )}

                    {/* Team cards */}
                    <div className="grid md:grid-cols-2 gap-6">
                        {[{ team: selectedTeam, deep: deepA, loading: loadingDeepA, color: 'blue' }, { team: selectedTeamB, deep: deepB, loading: loadingDeepB, color: 'rose' }].map(({ team, deep, loading: ld, color }) => team && (
                            <div key={team.team_name} className={`bg-slate-900 border border-${color}-500/30 rounded-2xl p-6 shadow-xl relative overflow-hidden`}>
                                <div className={`absolute top-0 right-0 w-32 h-32 bg-${color}-500/10 rounded-full blur-3xl pointer-events-none`} />
                                <div className={`text-xs font-bold text-${color}-400 uppercase tracking-widest mb-1`}>{team.conference}</div>
                                <h2 className="text-2xl font-black text-white mb-1">{team.team_name}</h2>
                                <div className="text-xs text-slate-400 mb-4">
                                    {team.net_record || team.record} • KP #{team.rank}
                                    {(deep?.net?.net_rank || team.net_rank) && ` • NET #${deep?.net?.net_rank || team.net_rank}`}
                                </div>
                                {/* Upset risk + dark horse inline */}
                                {deep && (
                                    <div className="flex gap-4 mb-4">
                                        <div className="flex items-center gap-2">
                                            <AlertTriangle size={12} className="text-red-400" />
                                            <span className="text-xs text-slate-400">Upset Risk</span>
                                            <span className={`text-sm font-black ${deep.upset_risk?.score > 60 ? 'text-red-400' : deep.upset_risk?.score > 30 ? 'text-yellow-400' : 'text-emerald-400'}`}>
                                                {deep.upset_risk?.score ?? '—'}
                                            </span>
                                        </div>
                                        <div className="flex items-center gap-2">
                                            <Star size={12} className="text-yellow-400" />
                                            <span className="text-xs text-slate-400">Dark Horse</span>
                                            <span className={`text-sm font-black ${deep.dark_horse?.score > 50 ? 'text-yellow-400' : 'text-slate-300'}`}>
                                                {deep.dark_horse?.score ?? '—'}
                                            </span>
                                        </div>
                                    </div>
                                )}
                                <div className="grid grid-cols-3 gap-2 text-center mb-4">
                                    {[
                                        { label: 'OFF', val: team.adj_o, color: getColorEff(team.adj_o) },
                                        { label: 'DEF', val: team.adj_d, color: getColorEff(team.adj_d, true) },
                                        { label: 'TEMPO', val: team.adj_t, color: 'text-white' },
                                    ].map(({ label, val, color: c }) => (
                                        <div key={label} className="bg-slate-950 p-2 rounded-lg border border-slate-800">
                                            <div className="text-[10px] text-slate-500 font-bold mb-1">{label}</div>
                                            <div className={`text-lg font-black ${c}`}>{val}</div>
                                        </div>
                                    ))}
                                </div>
                                {/* Player stats mini */}
                                {ld ? <div className="text-xs text-slate-500 text-center py-2 animate-pulse">Loading players…</div> : deep?.players?.length > 0 && (
                                    <div className="text-[10px]">
                                        <div className="text-slate-500 font-bold uppercase mb-1">Key Players</div>
                                        <div className="space-y-1">
                                            {deep.players.slice(0, 4).map((p, i) => (
                                                <div key={i} className="flex justify-between text-slate-300">
                                                    <span className="font-bold truncate pr-2">{p.name}</span>
                                                    <span className="text-emerald-400 shrink-0">
                                                        {p.ppg != null ? `${p.ppg.toFixed(1)}pts` : ''}
                                                        {p.usg != null ? ` · ${p.usg.toFixed(0)}%usg` : ''}
                                                    </span>
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                )}
                            </div>
                        ))}
                    </div>

                    {/* Stat comparison bars */}
                    <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6">
                        <h3 className="text-sm font-bold text-slate-300 uppercase tracking-widest mb-4 flex items-center gap-2">
                            <Swords size={14} className="text-purple-400" /> Head-to-Head Stat Comparison
                        </h3>
                        <div className="grid grid-cols-[1fr_72px_1fr] gap-1 text-center text-[10px] font-bold text-slate-500 uppercase mb-2">
                            <div className="text-right text-blue-400">{selectedTeam.team_name}</div>
                            <div>Metric</div>
                            <div className="text-left text-rose-400">{selectedTeamB?.team_name}</div>
                        </div>
                        <StatBar label="AdjEM" valA={selectedTeam.adj_em} valB={selectedTeamB?.adj_em} />
                        <StatBar label="Offense" valA={selectedTeam.adj_o} valB={selectedTeamB?.adj_o} />
                        <StatBar label="Defense" valA={selectedTeam.adj_d} valB={selectedTeamB?.adj_d} lowerIsBetter />
                        <StatBar label="Tempo" valA={selectedTeam.adj_t} valB={selectedTeamB?.adj_t} />
                        {(deepA?.torvik?.barthag || deepB?.torvik?.barthag) && (
                            <StatBar label="Barthag"
                                valA={(parseFloat(deepA?.torvik?.barthag) || 0) * 100}
                                valB={(parseFloat(deepB?.torvik?.barthag) || 0) * 100}
                                fmtA={deepA?.torvik?.barthag ? `${(parseFloat(deepA.torvik.barthag) * 100).toFixed(1)}%` : '—'}
                                fmtB={deepB?.torvik?.barthag ? `${(parseFloat(deepB.torvik.barthag) * 100).toFixed(1)}%` : '—'} />
                        )}
                        {(deepA?.torvik?.luck != null || deepB?.torvik?.luck != null) && (
                            <StatBar label="Luck" lowerIsBetter
                                valA={parseFloat(deepA?.torvik?.luck) || 0}
                                valB={parseFloat(deepB?.torvik?.luck) || 0}
                                fmtA={deepA?.torvik?.luck != null ? `${parseFloat(deepA.torvik.luck).toFixed(3)}` : '—'}
                                fmtB={deepB?.torvik?.luck != null ? `${parseFloat(deepB.torvik.luck).toFixed(3)}` : '—'} />
                        )}
                        {(deepA?.torvik?.continuity || deepB?.torvik?.continuity) && (
                            <StatBar label="Continuity"
                                valA={parseFloat(deepA?.torvik?.continuity) || 0}
                                valB={parseFloat(deepB?.torvik?.continuity) || 0}
                                fmtA={deepA?.torvik?.continuity ? `${parseFloat(deepA.torvik.continuity).toFixed(0)}%` : '—'}
                                fmtB={deepB?.torvik?.continuity ? `${parseFloat(deepB.torvik.continuity).toFixed(0)}%` : '—'} />
                        )}
                        <StatBar label="Net Rank" lowerIsBetter
                            valA={deepA?.net?.net_rank || selectedTeam.net_rank || 99}
                            valB={deepB?.net?.net_rank || selectedTeamB?.net_rank || 99}
                            fmtA={`#${deepA?.net?.net_rank || selectedTeam.net_rank || '—'}`}
                            fmtB={`#${deepB?.net?.net_rank || selectedTeamB?.net_rank || '—'}`} />
                    </div>

                    {/* AI Analysis */}
                    <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 md:p-8">
                        <h3 className="text-sm font-bold text-slate-300 uppercase tracking-widest mb-4 flex items-center gap-2">
                            <Cpu size={14} className="text-purple-400" /> AI Tactical Analysis
                        </h3>
                        {loadingMatchup ? (
                            <div className="flex flex-col items-center justify-center py-10 text-slate-400 animate-pulse gap-2">
                                <Cpu size={28} className="text-purple-500" />
                                <span className="text-sm">Generating tactical synthesis…</span>
                            </div>
                        ) : matchupData ? (
                            <div className="space-y-6">
                                <div className="text-center pb-6 border-b border-slate-800">
                                    <div className="inline-block px-4 py-1 rounded-full bg-purple-500/10 border border-purple-500/30 text-purple-400 font-bold text-xs uppercase mb-3">AI Predicted Winner</div>
                                    <h3 className="text-4xl font-black text-white mb-2">{matchupData.predicted_winner}</h3>
                                    <div className="text-sm text-slate-500 font-bold uppercase">Confidence: <span className={matchupData.confidence === 'High' ? 'text-emerald-400' : matchupData.confidence === 'Medium' ? 'text-blue-400' : 'text-rose-400'}>{matchupData.confidence}</span></div>
                                    <p className="mt-4 text-slate-300 italic max-w-2xl mx-auto leading-relaxed">"{matchupData.summary}"</p>
                                </div>
                                <div className="grid md:grid-cols-2 gap-6">
                                    {[
                                        { team: selectedTeam.team_name, advs: matchupData.team_a_advantages, color: 'text-blue-400', dot: 'bg-blue-500' },
                                        { team: selectedTeamB?.team_name, advs: matchupData.team_b_advantages, color: 'text-rose-400', dot: 'bg-rose-500' },
                                    ].map(({ team, advs, color, dot }) => (
                                        <div key={team} className="bg-slate-950/50 p-5 rounded-xl border border-slate-800">
                                            <h4 className={`text-xs font-bold ${color} uppercase tracking-widest mb-3 flex items-center gap-2`}><TrendingUp size={12} /> {team} Advantages</h4>
                                            <ul className="space-y-2">{(advs || []).map((a, i) => (
                                                <li key={i} className="flex gap-2 text-sm text-slate-300 items-start">
                                                    <div className={`w-1.5 h-1.5 rounded-full ${dot} shrink-0 mt-1.5`} />{a}
                                                </li>
                                            ))}</ul>
                                        </div>
                                    ))}
                                </div>
                                {matchupData.key_matchup && (
                                    <div className="bg-purple-900/10 border border-purple-500/20 rounded-xl p-5">
                                        <h4 className="text-xs font-bold text-purple-400 uppercase tracking-widest mb-2 flex items-center gap-2"><Swords size={12} /> Key Matchup</h4>
                                        <p className="text-slate-300 text-sm leading-relaxed">{matchupData.key_matchup}</p>
                                    </div>
                                )}
                            </div>
                        ) : (
                            <div className="text-center py-10 text-slate-500 text-sm">Select two teams to generate tactical analysis.</div>
                        )}
                    </div>
                </div>
            )}

            {/* ════ DARK HORSE EXPLORER TAB ════ */}
            {activeTab === 'darkhorse' && (
                <div className="max-w-7xl mx-auto px-4 md:px-8 py-8 space-y-6 animate-in fade-in duration-500">
                    <div className="bg-gradient-to-r from-yellow-950/40 to-slate-900 border border-yellow-700/30 rounded-2xl p-6">
                        <h2 className="text-xl font-bold text-white mb-2 flex items-center gap-2">
                            <Star className="text-yellow-400" /> Dark Horse Explorer
                        </h2>
                        <p className="text-slate-400 text-sm">Teams ranked by Dark Horse Index — identifies sleepers with elite underlying metrics, unlucky season records, and experienced rosters primed to make a deep March run.</p>
                    </div>

                    {dhLoading ? (
                        <div className="flex flex-col items-center justify-center py-16 gap-4 text-slate-400 animate-pulse">
                            <Star size={32} className="text-yellow-500" />
                            <span className="text-sm">Analyzing {teams.length > 0 ? 'top 40' : ''} teams for tournament potential…</span>
                        </div>
                    ) : dhProfiles.length > 0 ? (
                        <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden">
                            <div className="overflow-x-auto">
                                <table className="w-full text-sm">
                                    <thead>
                                        <tr className="border-b border-slate-800 text-slate-500 uppercase tracking-wider text-xs">
                                            <th className="text-left py-3 px-4">#</th>
                                            <th className="text-left py-3 px-4 font-bold">Team</th>
                                            <th className="text-center py-3 px-3">KP</th>
                                            <th className="text-center py-3 px-3">NET</th>
                                            <th className="text-center py-3 px-3">AdjEM</th>
                                            <th className="text-center py-3 px-3">Barthag</th>
                                            <th className="text-center py-3 px-3">Luck</th>
                                            <th className="text-center py-3 px-3">Cont.</th>
                                            <th className="text-center py-3 px-3">Q1</th>
                                            <th className="text-center py-3 px-3">Upset Risk</th>
                                            <th className="text-center py-3 px-3 font-black text-yellow-400">🐴 Score</th>
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y divide-slate-800/50">
                                        {dhProfiles.map((d, i) => {
                                            const dhScore = d.dark_horse?.score || 0;
                                            const upScore = d.upset_risk?.score || 0;
                                            const bn = parseFloat(d.torvik?.barthag);
                                            const luck = parseFloat(d.torvik?.luck);
                                            const cont = parseFloat(d.torvik?.continuity);
                                            return (
                                                <tr key={d.team_name} className="hover:bg-slate-800/30 transition cursor-pointer"
                                                    onClick={() => { const t = teams.find(x => x.team_name === d.team_name); if (t) { setSelectedTeam(t); setActiveTab('profile'); } }}>
                                                    <td className="py-3 px-4 text-slate-500 font-mono">{i + 1}</td>
                                                    <td className="py-3 px-4">
                                                        <div className="font-bold text-white">{d.team_name}</div>
                                                        <div className="text-[10px] text-slate-500">{d.conference || d.kenpom?.conference}</div>
                                                    </td>
                                                    <td className="py-3 px-3 text-center text-slate-300">#{d.kp_rank || d.kenpom?.rank}</td>
                                                    <td className="py-3 px-3 text-center text-orange-400">#{d.net?.net_rank || '—'}</td>
                                                    <td className="py-3 px-3 text-center font-black text-white">
                                                        {d.kenpom?.adj_em ? `+${parseFloat(d.kenpom.adj_em).toFixed(1)}` : '—'}
                                                    </td>
                                                    <td className="py-3 px-3 text-center text-blue-400">
                                                        {!isNaN(bn) ? `${(bn * 100).toFixed(1)}%` : '—'}
                                                    </td>
                                                    <td className={`py-3 px-3 text-center font-bold ${!isNaN(luck) ? (luck < 0 ? 'text-emerald-400' : 'text-red-400') : 'text-slate-500'}`}>
                                                        {!isNaN(luck) ? `${luck >= 0 ? '+' : ''}${luck.toFixed(3)}` : '—'}
                                                    </td>
                                                    <td className={`py-3 px-3 text-center ${!isNaN(cont) ? (cont >= 75 ? 'text-emerald-400' : cont < 60 ? 'text-red-400' : 'text-slate-300') : 'text-slate-500'}`}>
                                                        {!isNaN(cont) ? `${cont.toFixed(0)}%` : '—'}
                                                    </td>
                                                    <td className="py-3 px-3 text-center text-slate-300">
                                                        {d.net?.quad1 || '—'}
                                                    </td>
                                                    <td className="py-3 px-3 text-center">
                                                        <span className={`px-2 py-0.5 rounded text-xs font-black ${upScore > 60 ? 'bg-red-500/20 text-red-400' : upScore > 30 ? 'bg-yellow-500/20 text-yellow-400' : 'bg-emerald-500/20 text-emerald-400'}`}>
                                                            {upScore}
                                                        </span>
                                                    </td>
                                                    <td className="py-3 px-3 text-center">
                                                        <div className="flex items-center justify-center gap-1">
                                                            {dhScore >= 60 && <Star size={10} className="text-yellow-400 fill-yellow-400" />}
                                                            <span className={`font-black text-base ${dhScore >= 60 ? 'text-yellow-400' : dhScore >= 40 ? 'text-slate-200' : 'text-slate-500'}`}>{dhScore}</span>
                                                        </div>
                                                    </td>
                                                </tr>
                                            );
                                        })}
                                    </tbody>
                                </table>
                            </div>
                            <div className="p-4 border-t border-slate-800 text-[10px] text-slate-600 text-center">
                                Click any row to open Team Profile • Sorted by Dark Horse Index ↓ • Luck: negative = unlucky (regression expected) • Continuity: roster experience %
                            </div>
                        </div>
                    ) : (
                        <div className="text-center py-12 text-slate-500 text-sm">
                            Click Refresh to analyze teams for Dark Horse potential.
                        </div>
                    )}
                </div>
            )}

            {/* ════ BRACKET TAB ════ */}
            {activeTab === 'bracket' && (
                <BracketView
                    data={bracketData}
                    loading={loadingBracket}
                    onMatchupClick={handleMatchupClick}
                />
            )}
        </div>
    );
};

/* ─── Matchup Card ─── */
function MatchupCard({ m, onMatchupClick }) {
    if (!m) return null;
    return (
        <div
            onClick={() => onMatchupClick && onMatchupClick(m.team_a, m.team_b)}
            className="bg-slate-900/40 border border-slate-800/80 rounded-xl p-3 hover:border-blue-500/50 hover:bg-slate-800/40 transition cursor-pointer group relative overflow-hidden"
        >
            <div className="absolute top-0 right-0 p-1.5 opacity-0 group-hover:opacity-100 transition">
                <Swords size={10} className="text-blue-400" />
            </div>
            <div className="flex justify-between items-center mb-1">
                <div className="flex items-center gap-2">
                    {m.seed_a && <span className="text-[9px] font-black text-slate-600 w-4">{m.seed_a}</span>}
                    <span className={`text-xs font-bold ${m.winner === m.team_a ? 'text-white' : 'text-slate-500'}`}>{m.team_a}</span>
                </div>
                <span className="text-[9px] font-mono text-slate-500">{m.win_prob_a}%</span>
            </div>
            <div className="flex justify-between items-center">
                <div className="flex items-center gap-2">
                    {m.seed_b && <span className="text-[9px] font-black text-slate-600 w-4">{m.seed_b}</span>}
                    <span className={`text-xs font-bold ${m.winner === m.team_b ? 'text-white' : 'text-slate-500'}`}>{m.team_b}</span>
                </div>
                <span className="text-[9px] font-mono text-slate-500">{m.win_prob_b}%</span>
            </div>
            {m.spread != null && (
                <div className="mt-1.5 pt-1.5 border-t border-slate-800/50 flex justify-between items-center">
                    <span className="text-[8px] font-black text-slate-700 uppercase tracking-widest">MC Proj</span>
                    <span className="text-[9px] font-black text-blue-500">
                        {m.spread < 0 ? m.team_a : m.team_b} {m.spread < 0 ? '' : '+'}{Math.abs(m.spread).toFixed(1)}
                        <span className="text-slate-700 ml-1">O/U {m.total?.toFixed(1)}</span>
                    </span>
                </div>
            )}
        </div>
    );
}

/* ─── Round Section ─── */
function RoundSection({ title, badge, badgeColor, matchups, onMatchupClick, defaultOpen = false }) {
    const [open, setOpen] = React.useState(defaultOpen);
    if (!matchups || matchups.length === 0) return null;
    return (
        <div>
            <button onClick={() => setOpen(o => !o)} className="flex items-center gap-2 mb-2 w-full text-left">
                <span className="text-xs font-black text-slate-300 uppercase tracking-widest">{title}</span>
                <span className={`px-2 py-0.5 rounded text-[9px] font-bold uppercase tracking-tighter ${badgeColor}`}>{badge}</span>
                <span className="ml-auto text-slate-600">{open ? <ChevronUp size={12} /> : <ChevronDown size={12} />}</span>
            </button>
            {open && (
                <div className="grid gap-2">
                    {matchups.map((m, i) => <MatchupCard key={i} m={m} onMatchupClick={onMatchupClick} />)}
                </div>
            )}
        </div>
    );
}

const BracketView = ({ data, loading, onMatchupClick }) => {
    if (loading) return (
        <div className="p-12 flex flex-col items-center justify-center min-h-[400px] gap-3 text-slate-400">
            <RefreshCw size={32} className="text-orange-500 animate-spin" />
            <span className="font-bold tracking-widest uppercase text-xs">Computing Tournament Projections…</span>
        </div>
    );
    if (!data || !data.regions) return <div className="p-12 text-center text-red-400 font-mono">Bracket data unavailable. Check back soon.</div>;

    const regions = ['East', 'South', 'West', 'Midwest'];
    const champ = data.championship;
    const champion = data.champion;

    return (
        <div className="max-w-7xl mx-auto px-4 md:px-8 py-8 space-y-10 animate-in fade-in slide-in-from-bottom-4 duration-700">

            {/* Champion Banner */}
            {champion && (
                <div className="relative overflow-hidden rounded-2xl border border-yellow-500/40 bg-gradient-to-br from-yellow-950/60 via-slate-900 to-slate-950 p-6 text-center shadow-2xl">
                    <div className="absolute top-0 left-1/2 -translate-x-1/2 w-64 h-64 bg-yellow-500/10 rounded-full blur-[80px] pointer-events-none" />
                    <div className="relative">
                        <div className="text-4xl mb-2">🏆</div>
                        <div className="text-[10px] font-black text-yellow-400 uppercase tracking-[0.3em] mb-1">2026 Predicted National Champion</div>
                        <div className="text-3xl md:text-4xl font-black text-white mb-3 tracking-tight">{champion}</div>
                        {champ && (
                            <div className="flex flex-wrap justify-center gap-4 text-xs text-slate-400">
                                <span>Win Prob: <span className="font-black text-yellow-400">{Math.max(champ.win_prob_a, champ.win_prob_b)}%</span></span>
                                <span>Spread: <span className="font-black text-white">{champ.spread > 0 ? '+' : ''}{champ.spread}</span></span>
                                <span>O/U: <span className="font-black text-white">{champ.total?.toFixed(1)}</span></span>
                            </div>
                        )}
                    </div>
                </div>
            )}

            {/* Final Four */}
            {data.final_four?.length > 0 && (
                <div>
                    <div className="flex items-center gap-3 border-b border-slate-800 pb-2 mb-4">
                        <span className="text-xl font-black text-white italic">Final Four</span>
                        <span className="px-2 py-0.5 rounded bg-yellow-900/40 text-[10px] font-bold text-yellow-400 uppercase tracking-tighter">National Semifinals</span>
                    </div>
                    <div className="grid md:grid-cols-2 gap-3">
                        {data.final_four.map((m, i) => <MatchupCard key={i} m={m} onMatchupClick={onMatchupClick} />)}
                    </div>
                </div>
            )}

            {/* Regional Brackets */}
            <div className="grid lg:grid-cols-2 gap-10">
                {regions.map(name => {
                    const region = data.regions[name];
                    if (!region) return null;
                    return (
                        <div key={name} className="space-y-4">
                            <div className="flex items-center gap-3 border-b border-slate-800 pb-2">
                                <span className="text-xl font-black text-white italic">{name} Region</span>
                            </div>
                            <RoundSection title="Elite 8" badge="Regional Final" badgeColor="bg-rose-900/40 text-rose-400" matchups={region.elite_8} onMatchupClick={onMatchupClick} defaultOpen={true} />
                            <RoundSection title="Sweet 16" badge="Round of 16" badgeColor="bg-purple-900/40 text-purple-400" matchups={region.sweet_16} onMatchupClick={onMatchupClick} defaultOpen={true} />
                            <RoundSection title="Round of 32" badge="Second Round" badgeColor="bg-blue-900/40 text-blue-400" matchups={region.round_of_32} onMatchupClick={onMatchupClick} defaultOpen={false} />
                            <RoundSection title="Round of 64" badge="First Round" badgeColor="bg-slate-800 text-slate-400" matchups={region.round_of_64} onMatchupClick={onMatchupClick} defaultOpen={false} />
                        </div>
                    );
                })}
            </div>
        </div>
    );
};

export default MarchMadness;



