import React, { useState, useEffect } from 'react';
import api from '../api/axios';
import { Shield, Crosshair, Activity, AlertTriangle, Users, TrendingUp, Cpu, RefreshCw } from 'lucide-react';

const MarchMadness = () => {
    const [loading, setLoading] = useState(true);
    const [teamData, setTeamData] = useState(null);

    useEffect(() => {
        fetchData();
    }, []);

    const fetchData = async () => {
        setLoading(true);
        try {
            const res = await api.get('/api/ncaam/tournament-teams', { params: { limit: 100 } });
            const teams = res.data.teams || [];
            if (teams.length > 0) {
                // Look for UConn explicitly, if they dropped out of the top 68 we'll catch them up to 100
                const uconn = teams.find(t => t.team_name.includes('Connecticut') || t.team_name.includes('UConn'));
                // fallback to the overall #1 seed if UConn is not found at all
                setTeamData(uconn || teams[0]);
            }
        } catch (err) {
            console.error("Failed to load tournament profile", err);
        } finally {
            setLoading(false);
        }
    };

    if (loading) {
        return <div className="p-8 text-center text-slate-400 animate-pulse font-mono flex items-center justify-center min-h-screen">Loading Tournament Profile Engine...</div>;
    }

    if (!teamData) {
        return <div className="p-8 text-center text-red-400 font-mono">Profile generation failed. Target team not found.</div>;
    }

    // Live narrative data from AI Pipeline
    const profile = teamData.profile || {};
    const narrative = profile.narrative || {
        summary: "Profile generating... Check back later.",
        offense: [], defense: [], upsetFlags: "N/A"
    };

    const resumeRecords = profile.resume?.records || { overall: teamData.record || "-", home: "-", away: "-", neutral: "-" };
    const resumeQuads = profile.resume?.quads || { q1: "-", q2: "-", q3: "-", q4: "-" };
    const netRank = profile.net || "-";
    const players = profile.players || [];
    const torvik = teamData.torvik || {};

    // Helper to color grade metrics
    const getEfficiencyColor = (metric, isDefensive = false) => {
        if (!metric) return 'text-slate-400';
        const val = parseFloat(metric);
        if (isDefensive) {
            if (val < 90) return 'text-purple-400'; // Elite
            if (val < 95) return 'text-emerald-400'; // Great
            if (val > 105) return 'text-red-400'; // Bad
            return 'text-slate-300';
        } else {
            if (val > 120) return 'text-purple-400'; // Elite
            if (val > 112) return 'text-emerald-400'; // Great
            if (val < 100) return 'text-red-400'; // Bad
            return 'text-slate-300';
        }
    };

    return (
        <div className="bg-slate-950 min-h-screen text-white pb-20">
            {/* Action Bar */}
            <div className="flex justify-between items-center p-4 border-b border-slate-800 bg-slate-900/50">
                <div className="text-xs font-bold text-slate-500 uppercase tracking-widest flex items-center gap-2">
                    <Cpu size={14} className="text-blue-500" /> Profiler Engine v2.0
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
                            🐺
                        </div>
                        <div className="px-4 py-1.5 rounded-full bg-slate-800 border border-slate-700 text-sm font-black text-slate-200 tracking-wider shadow-lg">
                            KENPOM #{teamData.rank}
                        </div>
                    </div>

                    {/* Team Title & Narrative */}
                    <div className="text-center md:text-left flex-1">
                        <div className="text-blue-400 font-bold tracking-widest uppercase text-sm mb-2">{teamData.conference || 'Big East'}</div>
                        <h1 className="text-4xl md:text-6xl font-black text-white mb-2 tracking-tight">
                            {teamData.team_name}
                        </h1>
                        <div className="flex flex-wrap items-center justify-center md:justify-start gap-4 mb-6">
                            {/* Record Pills */}
                            <div className="flex bg-slate-800/80 rounded-lg border border-slate-700/50 p-1 text-sm font-mono text-slate-300">
                                <span className="px-3 bg-slate-900 rounded font-bold text-white shadow-sm border border-slate-700/50">{resumeRecords.overall} OVR</span>
                                <span className="px-3 border-r border-slate-700/50">{resumeRecords.home} Home</span>
                                <span className="px-3 border-r border-slate-700/50">{resumeRecords.away} Away</span>
                                <span className="px-3">{resumeRecords.neutral} N</span>
                            </div>
                            <span className="text-slate-600">•</span>
                            <div className="flex items-center gap-3 text-sm font-bold tracking-wider uppercase">
                                <span className="text-slate-400">NET <span className="text-blue-400 ml-1">#{netRank}</span></span>
                                <span className="text-slate-600">|</span>
                                <span className="text-slate-400">Torvik Barthag <span className="font-mono text-white ml-1">{torvik.barthag ? (torvik.barthag * 100).toFixed(1) : '—'}%</span></span>
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
                <div className="grid grid-cols-4 md:grid-cols-8 gap-2 mb-2">
                    <div className="col-span-4 md:col-span-8 mb-1 flex items-center justify-between">
                        <span className="text-xs font-bold uppercase tracking-widest text-slate-400">Team Sheet / Resume</span>
                        <span className="text-[10px] text-slate-500 font-mono uppercase">Bracketology Profile</span>
                    </div>
                    {/* Q1 */}
                    <div className="col-span-2 md:col-span-2 bg-emerald-500/10 border border-emerald-500/20 rounded-xl p-3 flex flex-col items-center justify-center">
                        <span className="text-[10px] font-bold text-emerald-500/70 uppercase">Quadrant 1</span>
                        <span className="text-xl font-black text-emerald-400 font-mono">{resumeQuads.q1}</span>
                    </div>
                    {/* Q2 */}
                    <div className="col-span-2 md:col-span-2 bg-emerald-500/5 border border-emerald-500/10 rounded-xl p-3 flex flex-col items-center justify-center">
                        <span className="text-[10px] font-bold text-emerald-500/70 uppercase">Quadrant 2</span>
                        <span className="text-xl font-black text-emerald-400/80 font-mono">{resumeQuads.q2}</span>
                    </div>
                    {/* Q3 */}
                    <div className="col-span-2 md:col-span-2 bg-slate-800/50 border border-slate-700/50 rounded-xl p-3 flex flex-col items-center justify-center">
                        <span className="text-[10px] font-bold text-slate-500 uppercase">Quadrant 3</span>
                        <span className="text-xl font-black text-slate-300 font-mono">{resumeQuads.q3}</span>
                    </div>
                    {/* Q4 */}
                    <div className="col-span-2 md:col-span-2 bg-slate-800/30 border border-slate-800/50 rounded-xl p-3 flex flex-col items-center justify-center">
                        <span className="text-[10px] font-bold text-slate-600 uppercase">Quadrant 4</span>
                        <span className="text-xl font-black text-slate-400 font-mono">{resumeQuads.q4}</span>
                    </div>
                </div>

                {/* METRICS ROW */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div className="bg-slate-900 rounded-2xl p-5 border border-slate-800 shadow-lg relative overflow-hidden group">
                        <div className="absolute top-0 right-0 w-24 h-24 bg-blue-500/5 rounded-full blur-2xl group-hover:bg-blue-500/10 transition duration-500"></div>
                        <div className="flex items-center gap-2 mb-2 text-slate-400">
                            <TrendingUp size={16} />
                            <span className="text-xs font-bold uppercase tracking-wider">AdjEM</span>
                        </div>
                        <div className="text-3xl font-black text-white">+{teamData.adj_em}</div>
                        <div className="text-[10px] text-slate-500 mt-2">Overall Efficiency Margin</div>
                    </div>

                    <div className="bg-slate-900 rounded-2xl p-5 border border-slate-800 shadow-lg relative overflow-hidden group">
                        <div className="absolute top-0 right-0 w-24 h-24 bg-emerald-500/5 rounded-full blur-2xl group-hover:bg-emerald-500/10 transition duration-500"></div>
                        <div className="flex items-center gap-2 mb-2 text-slate-400">
                            <Crosshair size={16} />
                            <span className="text-xs font-bold uppercase tracking-wider">Offense (AdjO)</span>
                        </div>
                        <div className={`text-3xl font-black ${getEfficiencyColor(teamData.adj_o, false)}`}>{teamData.adj_o}</div>
                        <div className="text-[10px] text-slate-500 mt-2">Points per 100 poss</div>
                    </div>

                    <div className="bg-slate-900 rounded-2xl p-5 border border-slate-800 shadow-lg relative overflow-hidden group">
                        <div className="absolute top-0 right-0 w-24 h-24 bg-red-500/5 rounded-full blur-2xl group-hover:bg-red-500/10 transition duration-500"></div>
                        <div className="flex items-center gap-2 mb-2 text-slate-400">
                            <Shield size={16} />
                            <span className="text-xs font-bold uppercase tracking-wider">Defense (AdjD)</span>
                        </div>
                        <div className={`text-3xl font-black ${getEfficiencyColor(teamData.adj_d, true)}`}>{teamData.adj_d}</div>
                        <div className="text-[10px] text-slate-500 mt-2">Points allowed per 100 poss</div>
                    </div>

                    <div className="bg-slate-900 rounded-2xl p-5 border border-slate-800 shadow-lg relative overflow-hidden group">
                        <div className="absolute top-0 right-0 w-24 h-24 bg-purple-500/5 rounded-full blur-2xl group-hover:bg-purple-500/10 transition duration-500"></div>
                        <div className="flex items-center gap-2 mb-2 text-slate-400">
                            <Activity size={16} />
                            <span className="text-xs font-bold uppercase tracking-wider">Tempo</span>
                        </div>
                        <div className="text-3xl font-black text-white">{teamData.adj_t}</div>
                        <div className="text-[10px] text-slate-500 mt-2">Possessions per 40 min</div>
                    </div>
                </div>

                <div className="grid md:grid-cols-3 gap-8">
                    {/* LEFT COLUMN: Narrative & Risk */}
                    <div className="md:col-span-2 space-y-8">
                        {/* Scouting Report */}
                        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl">
                            <h2 className="text-xl font-bold text-white mb-6 flex items-center gap-2">
                                <FileTextIcon className="text-blue-400" /> Style of Play & Matchup Notes
                            </h2>

                            <div className="space-y-8">
                                <div>
                                    <h3 className="text-sm font-bold text-blue-400 uppercase tracking-widest mb-3 flex items-center gap-2 pb-2 border-b border-slate-800">
                                        <TrendingUp size={16} className="text-blue-500" /> Offensive Profile
                                    </h3>
                                    <ul className="space-y-3">
                                        {narrative.offense.map((s, i) => (
                                            <li key={i} className="flex items-start gap-3 text-slate-300">
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
                                            <li key={i} className="flex items-start gap-3 text-slate-300">
                                                <span className="w-1.5 h-1.5 rounded-full bg-purple-500 mt-2 shrink-0"></span>
                                                <span className="leading-relaxed">{w}</span>
                                            </li>
                                        ))}
                                    </ul>
                                </div>
                            </div>
                        </div>

                        {/* Upset Volatility */}
                        <div className="bg-gradient-to-br from-rose-950/40 to-slate-900 border border-rose-900/30 rounded-2xl p-6 shadow-xl">
                            <h2 className="text-xl font-bold text-white mb-4 flex items-center gap-2">
                                <AlertTriangle className="text-rose-500" /> Upset Volatility Profile
                            </h2>
                            <p className="text-slate-300 text-sm leading-relaxed mb-4">
                                {narrative.upsetFlags}
                            </p>

                            <div className="space-y-3 border-t border-slate-800/50 pt-4">
                                <div className="flex justify-between items-center text-sm">
                                    <span className="text-slate-400">3P Reliance Var:</span>
                                    <span className="font-mono text-emerald-400">LOW</span>
                                </div>
                                <div className="flex justify-between items-center text-sm">
                                    <span className="text-slate-400">Tempo Var:</span>
                                    <span className="font-mono text-yellow-400">MED</span>
                                </div>
                                <div className="flex justify-between items-center text-sm">
                                    <span className="text-slate-400">Foul Trouble Risk:</span>
                                    <span className="font-mono text-rose-400 px-2 py-0.5 bg-rose-500/10 rounded">HIGH (Clingan)</span>
                                </div>
                            </div>
                        </div>
                    </div>

                    {/* RIGHT COLUMN: Roster & Advanced Context */}
                    <div className="space-y-8">
                        {/* Roster Block */}
                        <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-xl">
                            <div className="bg-slate-800/50 p-4 border-b border-slate-800 flex justify-between items-center">
                                <h2 className="text-lg font-bold text-white flex items-center gap-2">
                                    <Users className="text-blue-400" /> Rotation (Top 6)
                                </h2>
                                <span className="text-[10px] text-slate-500 uppercase font-bold tracking-widest">KenPom Adv</span>
                            </div>
                            <div className="divide-y divide-slate-800">
                                {players.map((p, i) => (
                                    <div key={i} className="p-4 hover:bg-slate-800/30 transition flex flex-col gap-2">
                                        <div className="flex justify-between items-start">
                                            <div>
                                                <div className="font-bold text-slate-100 flex items-center gap-2">
                                                    {p.name} <span className="text-[10px] bg-slate-800 px-1.5 py-0.5 rounded text-slate-400">{p.pos}</span>
                                                </div>
                                                <div className="text-xs font-mono text-emerald-400 mt-1">{p.stats}</div>
                                            </div>
                                            {/* Advanced Stats Pill Box */}
                                            <div className="grid grid-cols-2 lg:grid-cols-4 gap-px bg-slate-800 border border-slate-700 rounded-lg overflow-hidden shrink-0">
                                                <div className="bg-slate-900 px-2 py-1 text-center" title="Offensive Rating">
                                                    <div className="text-[8px] text-slate-500 uppercase font-bold">ORtg</div>
                                                    <div className="text-[10px] font-mono text-slate-200">{p.adv.ortg}</div>
                                                </div>
                                                <div className="bg-slate-900 px-2 py-1 text-center" title="Usage Rate">
                                                    <div className="text-[8px] text-slate-500 uppercase font-bold">Usg%</div>
                                                    <div className="text-[10px] font-mono text-blue-300">{p.adv.usg}</div>
                                                </div>
                                                <div className="bg-slate-900 px-2 py-1 text-center" title="Effective FG%">
                                                    <div className="text-[8px] text-slate-500 uppercase font-bold">eFG%</div>
                                                    <div className="text-[10px] font-mono text-slate-200">{p.adv.efg}</div>
                                                </div>
                                                <div className="bg-slate-900 px-2 py-1 text-center" title="Minutes %">
                                                    <div className="text-[8px] text-slate-500 uppercase font-bold">Min%</div>
                                                    <div className="text-[10px] font-mono text-slate-400">{p.adv.min}</div>
                                                </div>
                                            </div>
                                        </div>
                                        <p className="text-xs text-slate-400 leading-relaxed italic border-l-2 border-slate-700 pl-2 mt-1">{p.role}</p>
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
