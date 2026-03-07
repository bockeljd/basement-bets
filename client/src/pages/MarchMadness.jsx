import React, { useState, useEffect } from 'react';
import api from '../api/axios';
import { Shield, Crosshair, Activity, AlertTriangle, Users, TrendingUp, Cpu, RefreshCw } from 'lucide-react';

const MarchMadness = () => {
    const [loading, setLoading] = useState(true);
    const [teams, setTeams] = useState([]);
    const [selectedTeam, setSelectedTeam] = useState(null);

    useEffect(() => {
        fetchData();
    }, []);

    const fetchData = async () => {
        setLoading(true);
        try {
            const res = await api.get('/api/ncaam/tournament-teams', { params: { limit: 68 } });
            const allTeams = res.data.teams || [];
            if (allTeams.length > 0) {
                setTeams(allTeams);

                // If we already have a selection, try to keep it, otherwise find UConn or default to #1
                if (!selectedTeam) {
                    const uconn = allTeams.find(t => t.team_name.includes('Connecticut') || t.team_name.includes('UConn'));
                    setSelectedTeam(uconn || allTeams[0]);
                } else {
                    const refreshed = allTeams.find(t => t.team_name === selectedTeam.team_name);
                    setSelectedTeam(refreshed || allTeams[0]);
                }
            }
        } catch (err) {
            console.error("Failed to load tournament profiles", err);
        } finally {
            setLoading(false);
        }
    };

    if (loading && teams.length === 0) {
        return <div className="p-8 text-center text-slate-400 animate-pulse font-mono flex items-center justify-center min-h-screen">Loading Tournament Profile Engine...</div>;
    }

    if (!selectedTeam) {
        return <div className="p-8 text-center text-red-400 font-mono">Profile generation failed. Target team not found.</div>;
    }

    // Live narrative data from AI Pipeline
    const profile = selectedTeam.profile || {};
    const narrative = profile.narrative || {
        summary: "Profile generating... Check back later.",
        offense: [], defense: [], upsetFlags: "N/A"
    };

    const resumeRecords = profile.resume?.records || { overall: selectedTeam.record || "-", home: "-", away: "-", neutral: "-" };
    const resumeQuads = profile.resume?.quads || { q1: "-", q2: "-", q3: "-", q4: "-" };
    const netRank = profile.net || "-";
    const players = profile.players || [];
    const torvik = selectedTeam.torvik || {};

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

    return (
        <div className="bg-slate-950 min-h-screen text-white pb-20">
            {/* Action Bar */}
            <div className="flex justify-between items-center p-4 border-b border-slate-800 bg-slate-900/50 sticky top-0 z-50 backdrop-blur-md">
                <div className="flex items-center gap-4">
                    <div className="text-xs font-bold text-slate-500 uppercase tracking-widest flex items-center gap-2">
                        <Cpu size={14} className="text-blue-500" /> Profiler Engine v2.1
                    </div>

                    {/* Team Selector */}
                    <select
                        className="bg-slate-800 border border-slate-700 rounded px-3 py-1 text-sm font-bold text-blue-400 focus:outline-none focus:ring-1 focus:ring-blue-500"
                        value={selectedTeam.team_name}
                        onChange={(e) => {
                            const team = teams.find(t => t.team_name === e.target.value);
                            if (team) setSelectedTeam(team);
                        }}
                    >
                        {teams.map(t => (
                            <option key={t.team_name} value={t.team_name}>
                                #{t.rank} {t.team_name}
                            </option>
                        ))}
                    </select>
                </div>

                <button
                    onClick={fetchData}
                    className="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-white transition"
                    title="Refresh Data"
                >
                    <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
                </button>
            </div>

            {/* HEADER HERO */}
            <div className="relative overflow-hidden border-b border-slate-800">
                <div className="absolute inset-0 bg-gradient-to-br from-blue-900/40 via-slate-900 to-slate-950 opacity-80" />
                <div className="absolute top-0 right-0 w-96 h-96 bg-blue-600/10 rounded-full blur-[100px] pointer-events-none" />

                <div className="relative px-6 py-12 md:px-12 md:py-16 max-w-7xl mx-auto flex flex-col md:flex-row items-center md:items-start gap-8">
                    {/* Rank / Logo Block */}
                    <div className="flex flex-col items-center shrink-0">
                        <div className="w-32 h-32 md:w-40 md:h-40 bg-slate-900 rounded-3xl border border-slate-700 shadow-2xl flex items-center justify-center text-7xl mb-4 relative overflow-hidden">
                            <div className="absolute inset-0 bg-gradient-to-tr from-blue-500/10 to-transparent"></div>
                            🏀
                        </div>
                        <div className="px-4 py-1.5 rounded-full bg-slate-800 border border-slate-700 text-sm font-black text-slate-200 tracking-wider shadow-lg">
                            KENPOM #{selectedTeam.rank}
                        </div>
                    </div>

                    {/* Team Title & Narrative */}
                    <div className="text-center md:text-left flex-1">
                        <div className="text-blue-400 font-bold tracking-widest uppercase text-sm mb-2">{selectedTeam.conference || 'N/A'}</div>
                        <h1 className="text-4xl md:text-6xl font-black text-white mb-2 tracking-tight">
                            {selectedTeam.team_name}
                        </h1>
                        <div className="flex flex-wrap items-center justify-center md:justify-start gap-4 mb-6">
                            <div className="flex bg-slate-800/80 rounded-lg border border-slate-700/50 p-1 text-sm font-mono text-slate-300">
                                <span className="px-3 bg-slate-900 rounded font-bold text-white shadow-sm border border-slate-700/50">{resumeRecords.overall} OVR</span>
                                <span className="px-3 border-r border-slate-700/50">{resumeRecords.home} H</span>
                                <span className="px-3 border-r border-slate-700/50">{resumeRecords.away} A</span>
                                <span className="px-3">{resumeRecords.neutral} N</span>
                            </div>
                            <span className="text-slate-600">•</span>
                            <div className="flex items-center gap-3 text-sm font-bold tracking-wider uppercase">
                                <span className="text-slate-400">NET <span className="text-blue-400 ml-1">#{netRank}</span></span>
                                <span className="text-slate-600">|</span>
                                <span className="text-slate-400">Torvik <span className="font-mono text-white ml-1">{torvik.barthag ? (torvik.barthag * 100).toFixed(1) : '—'}%</span></span>
                            </div>
                        </div>
                        <p className="text-slate-300 leading-relaxed max-w-3xl text-sm md:text-base border-l-2 border-blue-500 pl-4 italic">
                            {narrative.summary}
                        </p>
                    </div>
                </div>
            </div>

            <div className="max-w-7xl mx-auto px-4 md:px-8 py-8 space-y-8">
                {/* RESUME QUADRANTS */}
                <div className="grid grid-cols-4 md:grid-cols-4 gap-4 mb-2">
                    <div className="bg-emerald-500/10 border border-emerald-500/20 rounded-xl p-4 flex flex-col items-center justify-center">
                        <span className="text-[10px] font-bold text-emerald-500/70 uppercase mb-1">Quadrant 1</span>
                        <span className="text-2xl font-black text-emerald-400 font-mono">{resumeQuads.q1}</span>
                    </div>
                    <div className="bg-emerald-500/5 border border-emerald-500/10 rounded-xl p-4 flex flex-col items-center justify-center">
                        <span className="text-[10px] font-bold text-emerald-500/70 uppercase mb-1">Quadrant 2</span>
                        <span className="text-2xl font-black text-emerald-400/80 font-mono">{resumeQuads.q2}</span>
                    </div>
                    <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-4 flex flex-col items-center justify-center">
                        <span className="text-[10px] font-bold text-slate-500 uppercase mb-1">Quadrant 3</span>
                        <span className="text-2xl font-black text-slate-300 font-mono">{resumeQuads.q3}</span>
                    </div>
                    <div className="bg-slate-800/30 border border-slate-800/50 rounded-xl p-4 flex flex-col items-center justify-center">
                        <span className="text-[10px] font-bold text-slate-600 uppercase mb-1">Quadrant 4</span>
                        <span className="text-2xl font-black text-slate-400 font-mono">{resumeQuads.q4}</span>
                    </div>
                </div>

                {/* METRICS ROW */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div className="bg-slate-900 rounded-2xl p-5 border border-slate-800 shadow-lg">
                        <div className="flex items-center gap-2 mb-2 text-slate-400">
                            <TrendingUp size={16} />
                            <span className="text-xs font-bold uppercase tracking-wider">AdjEM</span>
                        </div>
                        <div className="text-3xl font-black text-white">+{selectedTeam.adj_em}</div>
                    </div>
                    <div className="bg-slate-900 rounded-2xl p-5 border border-slate-800 shadow-lg">
                        <div className="flex items-center gap-2 mb-2 text-slate-400">
                            <Crosshair size={16} />
                            <span className="text-xs font-bold uppercase tracking-wider">Offense</span>
                        </div>
                        <div className={`text-3xl font-black ${getEfficiencyColor(selectedTeam.adj_o, false)}`}>{selectedTeam.adj_o}</div>
                    </div>
                    <div className="bg-slate-900 rounded-2xl p-5 border border-slate-800 shadow-lg">
                        <div className="flex items-center gap-2 mb-2 text-slate-400">
                            <Shield size={16} />
                            <span className="text-xs font-bold uppercase tracking-wider">Defense</span>
                        </div>
                        <div className={`text-3xl font-black ${getEfficiencyColor(selectedTeam.adj_d, true)}`}>{selectedTeam.adj_d}</div>
                    </div>
                    <div className="bg-slate-900 rounded-2xl p-5 border border-slate-800 shadow-lg">
                        <div className="flex items-center gap-2 mb-2 text-slate-400">
                            <Activity size={16} />
                            <span className="text-xs font-bold uppercase tracking-wider">Tempo</span>
                        </div>
                        <div className="text-3xl font-black text-white">{selectedTeam.adj_t}</div>
                    </div>
                </div>

                <div className="grid md:grid-cols-3 gap-8">
                    <div className="md:col-span-2 space-y-8">
                        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl">
                            <h2 className="text-xl font-bold text-white mb-6 flex items-center gap-2">
                                <FileTextIcon className="text-blue-400" /> Scouting Report (2025-26)
                            </h2>
                            <div className="space-y-8">
                                <div>
                                    <h3 className="text-sm font-bold text-blue-400 uppercase tracking-widest mb-3 flex items-center gap-2 pb-2 border-b border-slate-800">
                                        <TrendingUp size={16} className="text-blue-500" /> Offensive Profile
                                    </h3>
                                    <ul className="space-y-3">
                                        {narrative.offense.map((s, i) => (
                                            <li key={i} className="flex items-start gap-3 text-slate-300 text-sm">
                                                <span className="w-1.5 h-1.5 rounded-full bg-blue-500 mt-2 shrink-0"></span>
                                                <span className="leading-relaxed">{s}</span>
                                            </li>
                                        ))}
                                    </ul>
                                </div>
                                <div>
                                    <h3 className="text-sm font-bold text-purple-400 uppercase tracking-widest mb-3 flex items-center gap-2 pb-2 border-b border-slate-800">
                                        <Shield size={16} className="text-purple-500" /> Defensive Profile
                                    </h3>
                                    <ul className="space-y-3">
                                        {narrative.defense.map((w, i) => (
                                            <li key={i} className="flex items-start gap-3 text-slate-300 text-sm">
                                                <span className="w-1.5 h-1.5 rounded-full bg-purple-500 mt-2 shrink-0"></span>
                                                <span className="leading-relaxed">{w}</span>
                                            </li>
                                        ))}
                                    </ul>
                                </div>
                            </div>
                        </div>

                        <div className="bg-gradient-to-br from-rose-950/40 to-slate-900 border border-rose-900/30 rounded-2xl p-6 shadow-xl">
                            <h2 className="text-xl font-bold text-white mb-4 flex items-center gap-2">
                                <AlertTriangle className="text-rose-500" /> Volatility & Upset Risk
                            </h2>
                            <p className="text-slate-300 text-sm leading-relaxed">
                                {narrative.upsetFlags}
                            </p>
                        </div>
                    </div>

                    <div className="space-y-8">
                        <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-xl">
                            <div className="bg-slate-800/50 p-4 border-b border-slate-800 flex justify-between items-center">
                                <h2 className="text-lg font-bold text-white flex items-center gap-2">
                                    <Users className="text-blue-400" /> Key Personnel
                                </h2>
                            </div>
                            <div className="divide-y divide-slate-800">
                                {players.map((p, i) => (
                                    <div key={i} className="p-4 hover:bg-slate-800/30 transition flex flex-col gap-2">
                                        <div className="flex justify-between items-start">
                                            <div>
                                                <div className="font-bold text-slate-100 text-sm">
                                                    {p.name} <span className="text-[10px] text-slate-500 ml-1">{p.pos}</span>
                                                </div>
                                                <div className="text-xs font-mono text-emerald-400 mt-1">{p.stats}</div>
                                            </div>
                                            <div className="grid grid-cols-2 gap-1 shrink-0">
                                                <div className="bg-slate-950 px-2 py-0.5 rounded text-[9px] border border-slate-800 text-slate-400">
                                                    ORtg <span className="text-slate-100">{p.adv.ortg}</span>
                                                </div>
                                                <div className="bg-slate-950 px-2 py-0.5 rounded text-[9px] border border-slate-800 text-slate-400">
                                                    Usg% <span className="text-blue-300">{p.adv.usg}</span>
                                                </div>
                                            </div>
                                        </div>
                                        <p className="text-[11px] text-slate-400 leading-tight italic border-l border-slate-700 pl-2">{p.role}</p>
                                    </div>
                                ))}
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
};

// Simple Icon Helpers
const FileTextIcon = (props) => (
    <svg {...props} xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg>
);
const CheckCircleIcon = (props) => (
    <svg {...props} xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>
);
const XCircleIcon = (props) => (
    <svg {...props} xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>
);

export default MarchMadness;
