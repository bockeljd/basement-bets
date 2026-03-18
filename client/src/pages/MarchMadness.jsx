import React, { useState, useEffect, useMemo, useCallback } from 'react';
import api from '../api/axios';
import { resolveBracketFavorite } from '../utils/bracketTableRows';
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

// Smart Name Shortening for high-density bracket view
const shortenTeamName = (name) => {
    if (!name) return "";
    let n = name;
    // Common long names
    const mapping = {
        "North Carolina": "UNC",
        "South Carolina": "S Car",
        "Mississippi State": "Miss St",
        "Mississippi": "Ole Miss",
        "Connecticut": "UConn",
        "Saint Mary's": "St Mary's",
        "Michigan State": "Mich St",
        "Ohio State": "Ohio St",
        "Florida State": "FSU",
        "Kansas State": "K-State",
        "West Virginia": "W Virginia",
        "New Mexico State": "NMSU",
        "South Dakota": "S Dakota",
        "North Dakota": "N Dakota",
        "Loyola Chicago": "Loyola CHI",
        "St. John's": "St John's",
        "South Florida": "USF",
        "Virginia Tech": "VT",
        "Georgia Tech": "GT",
        "Texas A&M": "TAMU",
        "Texas Southern": "TX Southern",
        "Long Beach State": "LBSU",
        "Middle Tennessee": "MTSU",
        "Southwestern": "SW",
        "Grambling State": "Grambling",
        "Prairie View A&M": "Prairie View",
        "Fairleigh Dickinson": "FDU",
        "Arkansas-Little Rock": "UALR",
        "Cal State": "CSU",
        "Florida International": "FIU",
        "Northern Colorado": "N Colorado",
    };
    
    // Check if name contains any of the keys
    for (const key in mapping) {
        if (n.includes(key)) return mapping[key];
    }

    // Generic replacements
    n = n.replace("State", "St")
         .replace("University", "Univ")
         .replace("College", "Coll")
         .replace("A&M", "AM")
         .replace("Saint", "St")
         .replace("Northwestern", "NW");

    // Remove common mascots to save space if it's still long
    if (n.length > 12) {
        const mascots = ["Huskies", "Tar Heels", "Tigers", "Bulldogs", "Wildcats", "Eagles", "Cougars", "Panthers", "Spartans", "Gators", "Ducks", "Volunteers", "Jayhawks", "Fighting Irish", "Aggies", "Longhorns", "Badgers", "Cardinals", "Commodores", "Gamecocks", "Mountaineers", "Wolfpack", "Wolverines", "Hoosiers", "Sooners", "Cowboys", "Rebels", "Lions", "Blue Devils"];
        mascots.forEach(m => {
            n = n.replace(new RegExp(` ${m}$`, 'i'), "");
        });
    }

    return n.trim();
};

const formatProbability = (value) => {
    if (value == null) return '—';
    return `${Math.round(value)}%`;
};

const shouldShowChampion = (data) => {
    if (!data?.champion) return false;
    if (!data.degraded_simulation) return true;
    return !(data.champion_trust_low ?? false);
};

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
    const [activeTab, setActiveTab] = useState('bracket');
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

    const [bracketMode, setBracketMode] = useState('theater');

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

    const bracketInsights = useMemo(() => {
        if (!bracketData || !bracketData.regions) {
            return { upsetMatches: [], darkHorseTeams: [] };
        }
        const roundLabels = {
            round_of_64: 'Round of 64',
            round_of_32: 'Round of 32',
            sweet_16: 'Sweet 16',
            elite_8: 'Elite 8'
        };
        const matches = [];
        Object.entries(bracketData.regions).forEach(([regionName, rounds = {}]) => {
            Object.entries(rounds).forEach(([roundKey, matchups = []]) => {
                matchups.forEach((match, index) => {
                    if (!match.team_a || !match.team_b) return;
                    const winA = parseFloat(match.win_prob_a) || 0;
                    const winB = parseFloat(match.win_prob_b) || 0;
                    const favoriteSide = winA >= winB ? 'a' : 'b';
                    const favoriteName = favoriteSide === 'a' ? match.team_a : match.team_b;
                    const underdogName = favoriteSide === 'a' ? match.team_b : match.team_a;
                    const favoriteSeed = Number(favoriteSide === 'a' ? match.seed_a : match.seed_b) || 0;
                    const underdogSeed = Number(favoriteSide === 'a' ? match.seed_b : match.seed_a) || 0;
                    const favoriteWinProb = favoriteSide === 'a' ? winA : winB;
                    const underdogWinProb = favoriteSide === 'a' ? winB : winA;
                    const seedDelta = Math.max(0, underdogSeed - favoriteSeed);
                    const diff = Math.abs(winA - winB);
                    const riskScore = (100 - favoriteWinProb) + seedDelta * 2 + (100 - diff) * 0.3;
                    matches.push({
                        id: `${regionName}-${roundKey}-${index}-${match.team_a}-${match.team_b}`,
                        region: regionName,
                        roundLabel: roundLabels[roundKey] || roundKey.replace(/_/g, ' '),
                        favorite: favoriteName,
                        underdog: underdogName,
                        favoriteSeed,
                        underdogSeed,
                        favoriteWinProb: Math.round(favoriteWinProb),
                        underdogWinProb: Math.round(underdogWinProb),
                        seedDelta,
                        winner: match.predicted_winner || match.winner,
                        riskScore
                    });
                });
            });
        });
        const filtered = matches.filter(m => m.favoriteWinProb >= 55);
        filtered.sort((a, b) => b.riskScore - a.riskScore);
        const upsetMatches = filtered.slice(0, 4);

        const darkHorseTeams = (bracketData.round_advancement_probs || [])
            .filter(team => (team.seed || 0) >= 5 && (team.champion_prob || 0) > 0)
            .sort((a, b) => (b.champion_prob || 0) - (a.champion_prob || 0))
            .slice(0, 3)
            .map(team => {
                const championProb = Number(team.champion_prob) || 0;
                const finalFourProb = Number(team.final_four_prob) || 0;
                return {
                    team_name: team.team_name,
                    seed: team.seed,
                    region: team.region,
                    champion_prob: championProb,
                    final_four_prob: finalFourProb,
                    note: `${finalFourProb.toFixed(1)}% Final Four · ${championProb.toFixed(1)}% Champion`
                };
            });

        return { upsetMatches, darkHorseTeams };
    }, [bracketData]);

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
        <>
            {bracketData && (
                <div className="flex justify-center gap-2 py-2">
                    {['theater', 'table'].map(option => (
                        <button
                            key={option}
                            onClick={() => setBracketMode(option)}
                            className={`px-3 py-1 text-xs font-semibold rounded-full border transition ${bracketMode === option ? 'bg-orange-500 text-slate-900 border-orange-500' : 'bg-slate-900 border-slate-700 text-slate-400 hover:border-slate-500 hover:text-white'}`}
                        >
                            {option === 'theater' ? 'Bracket' : 'Quick Table'}
                        </button>
                    ))}
                </div>
            )}
            <div className={`overflow-x-auto no-scrollbar ${bracketMode === 'table' ? 'min-w-full' : ''}`}>
                <div className={bracketMode === 'table' ? '' : 'min-w-[1200px]'}>
                    <BracketView
                        data={bracketData}
                        loading={loadingBracket}
                        onMatchupClick={handleMatchupClick}
                        insights={bracketInsights}
                        mode={bracketMode}
                    />
                </div>
            </div>
        </>
    )}
        </div>
    );
};

/* ─── Matchup Card (Bracket Pod Style) ─── */
function MatchupCard({ m, onMatchupClick, mirrored = false }) {
    if (!m) return null;
    const displayWinner = m.display_winner || m.winner;
    const winnerSource = m.winner_source || 'projection';
    const isWinnerA = displayWinner === m.team_a;
    const isWinnerB = displayWinner === m.team_b;

    return (
        <div
            onClick={() => onMatchupClick && onMatchupClick(m.team_a, m.team_b)}
            className="group cursor-pointer relative"
        >
            {m.fallback_used && (
                <div className="absolute -top-2 -right-2 z-20 bg-amber-500 text-black rounded-full p-0.5 shadow-lg border border-amber-300 animate-pulse" title="Degraded Data: Seed-based fallback used">
                    <AlertTriangle size={12} fill="currentColor" />
                </div>
            )}
            <div className={`
                bg-slate-900 border border-slate-800 rounded shadow-md 
                hover:border-blue-500/50 hover:bg-slate-800/80 transition-all duration-300
                flex flex-col overflow-hidden w-[180px]
            `}>
                {/* Team A Pod */}
                <div className={`flex items-center gap-1.5 p-1.5 border-b border-slate-800/50 ${isWinnerA ? 'bg-blue-500/5' : ''}`}>
                    {mirrored ? (
                        <>
                            <span className={`text-[10px] font-mono shrink-0 ${isWinnerA ? 'text-emerald-400' : 'text-slate-600'}`}>
                                {m.win_prob_a}%
                            </span>
                            <span className={`text-[11px] font-black truncate flex-1 text-right ${isWinnerA ? 'text-white' : 'text-slate-500'}`} title={m.team_a}>
                                {shortenTeamName(m.team_a)}
                            </span>
                            {m.seed_a && <span className="text-[9px] font-black text-slate-500 w-4.5 text-center bg-slate-800/50 rounded shrink-0">{m.seed_a}</span>}
                        </>
                    ) : (
                        <>
                            {m.seed_a && <span className="text-[9px] font-black text-slate-500 w-4.5 text-center bg-slate-800/50 rounded shrink-0">{m.seed_a}</span>}
                            <span className={`text-[11px] font-black truncate flex-1 ${isWinnerA ? 'text-white' : 'text-slate-500'}`} title={m.team_a}>
                                {shortenTeamName(m.team_a)}
                            </span>
                            <span className={`text-[10px] font-mono shrink-0 ${isWinnerA ? 'text-emerald-400' : 'text-slate-600'}`}>
                                {m.win_prob_a}%
                            </span>
                        </>
                    )}
                </div>

                {/* Team B Pod */}
                <div className={`flex items-center gap-1.5 p-1.5 ${isWinnerB ? 'bg-blue-500/5' : ''}`}>
                    {mirrored ? (
                        <>
                            <span className={`text-[10px] font-mono shrink-0 ${isWinnerB ? 'text-emerald-400' : 'text-slate-600'}`}>
                                {m.win_prob_b}%
                            </span>
                            <span className={`text-[11px] font-black truncate flex-1 text-right ${isWinnerB ? 'text-white' : 'text-slate-500'}`} title={m.team_b}>
                                {shortenTeamName(m.team_b)}
                            </span>
                            {m.seed_b && <span className="text-[9px] font-black text-slate-500 w-4.5 text-center bg-slate-800/50 rounded shrink-0">{m.seed_b}</span>}
                        </>
                    ) : (
                        <>
                            {m.seed_b && <span className="text-[9px] font-black text-slate-500 w-4.5 text-center bg-slate-800/50 rounded shrink-0">{m.seed_b}</span>}
                            <span className={`text-[11px] font-black truncate flex-1 ${isWinnerB ? 'text-white' : 'text-slate-500'}`} title={m.team_b}>
                                {shortenTeamName(m.team_b)}
                            </span>
                            <span className={`text-[10px] font-mono shrink-0 ${isWinnerB ? 'text-emerald-400' : 'text-slate-600'}`}>
                                {m.win_prob_b}%
                            </span>
                        </>
                    )}
                </div>
            </div>
            {/* Projected Winner Glow */}
            <div className={`absolute -inset-0.5 rounded blur-[2px] opacity-0 group-hover:opacity-30 transition pointer-events-none bg-blue-500`} />
            
            {/* Tooltip Hover Info */}
            <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 transition duration-300 pointer-events-none z-50 mt-4 shadow-2xl scale-95 group-hover:scale-100 bg-slate-950/95 backdrop-blur-md border border-blue-500/30 w-[240px] p-3 rounded-lg flex flex-col gap-2">
                <div className="flex justify-between items-center text-[10px] font-bold uppercase text-slate-500 border-b border-slate-800 pb-1">
                    <span>{m.team_a}</span>
                    <span className="text-blue-400 font-mono">{(m.projected_spread_a > 0 ? '+' : '') + parseFloat(m.projected_spread_a).toFixed(1)}</span>
                </div>
                <div className="flex justify-between items-center text-xs font-black">
                    <span className="text-slate-400">Total: <span className="text-white">{parseFloat(m.projected_total).toFixed(1)}</span></span>
                    <span className="text-slate-400">Conf: <span className="text-blue-400">{parseFloat(m.confidence_0_100).toFixed(0)}</span></span>
                </div>
                {m.fallback_used && (
                    <div className="bg-amber-500/10 border border-amber-500/30 rounded p-1.5 text-[9px] text-amber-200 flex items-start gap-1.5">
                        <AlertTriangle size={10} className="shrink-0 mt-0.5" />
                        <span><strong>Data Issue:</strong> Missing core metrics. Model reverted to seed-based prior.</span>
                    </div>
                )}
                {m.reason_codes && m.reason_codes.length > 0 && (
                    <div className="text-[9px] text-slate-300 space-y-1 mt-1">
                        {m.reason_codes.slice(0, 3).map((r, i) => (
                            <div key={i} className="flex gap-1.5 items-start">
                                <div className="w-1 h-1 bg-blue-500 rounded-full mt-1.5 shrink-0" />
                                <span className="leading-tight">{r}</span>
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
}

/* ─── Region Tree ─── */
function RegionTree({ name, region, onMatchupClick, mirrored = false }) {
    if (!region) return null;

    const rounds = [
        { key: 'round_of_64', label: 'R64' },
        { key: 'round_of_32', label: 'R32' },
        { key: 'sweet_16', label: 'S16' },
        { key: 'elite_8', label: 'E8' }
    ];

    if (mirrored) rounds.reverse();

    return (
        <div className={`flex items-stretch gap-0 ${mirrored ? 'flex-row-reverse' : 'flex-row'}`}>
            {rounds.map((round, rIndex) => {
                const matchups = region[round.key] || [];
                // Dynamic spacing based on round
                // spacing tuned to mimic a traditional bracket: tight outer round, progressively larger gaps inward
                const verticalGapClass = 
                    round.key === 'round_of_64' ? 'gap-3' :
                    round.key === 'round_of_32' ? 'gap-10' :
                    round.key === 'sweet_16' ? 'gap-24' : 
                    'gap-0';
                
                const paddingTop = 
                    round.key === 'round_of_32' ? 'pt-6' :
                    round.key === 'sweet_16' ? 'pt-14' :
                    round.key === 'elite_8' ? 'pt-32' :
                    'pt-0';

                return (
                    <div key={round.key} className={`flex flex-col ${verticalGapClass} ${paddingTop} relative min-w-[180px]`}>
                        {matchups.map((m, mIndex) => (
                            <div key={mIndex} className="relative flex items-center">
                                {/* Connector Lines Logic (Conceptual for now, using borders for the Tree look) */}
                                <MatchupCard m={m} onMatchupClick={onMatchupClick} mirrored={mirrored} />
                                
                                {/* Horizontal connector towards next round */}
                                {((!mirrored && round.key !== 'elite_8') || (mirrored && round.key !== 'elite_8')) && (
                                    <div className={`absolute top-1/2 -translate-y-1/2 w-5 h-px bg-slate-700 ${mirrored ? '-left-5' : '-right-5'}`} />
                                )}
                            </div>
                        ))}
                    </div>
                );
            })}
        </div>
    );
}

const UpsetWatchlist = ({ items = [] }) => {
    if (!items.length) return null;
    return (
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4 space-y-3 shadow-lg">
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-[0.4em] text-purple-400">
                    <AlertTriangle size={12} />
                    Upset Watchlist
                </div>
                <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide">Model picks</span>
            </div>
            <div className="space-y-2">
                {items.map(item => (
                    <div key={item.id} className="bg-slate-950 border border-slate-800 rounded-2xl p-3 space-y-2">
                        <div className="flex items-center justify-between gap-3">
                            <div>
                                <p className="text-sm font-black text-white">{item.underdog}</p>
                                <p className="text-[11px] text-slate-500">{item.region} · {item.roundLabel}</p>
                            </div>
                            <div className="text-right text-sm font-black text-emerald-300">
                                {item.underdogWinProb}% upset
                                <div className="text-[10px] text-slate-500">Fav: #{item.favoriteSeed}</div>
                            </div>
                        </div>
                        <div className="flex items-center justify-between text-[12px] text-slate-400">
                            <span>Fav: {item.favorite} (#{item.favoriteSeed}) · {item.favoriteWinProb}%</span>
                            <span>Seed gap: {item.seedDelta}</span>
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
};

const DarkHorseWatchlist = ({ items = [] }) => {
    if (!items.length) return null;
    return (
        <div className="bg-slate-900 border border-yellow-500/30 rounded-2xl p-4 space-y-3">
            <div className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-[0.4em] text-yellow-400">
                <Star size={12} />
                Dark Horse Watch
            </div>
            <div className="space-y-2">
                {items.map(item => {
                    const champLabel = typeof item.champion_prob === 'number' ? `${item.champion_prob.toFixed(1)}%` : `${item.champion_prob}%`;
                    return (
                        <div key={item.team_name} className="bg-slate-950 border border-slate-800 rounded-2xl p-3 flex items-center justify-between gap-3">
                            <div>
                                <p className="text-sm font-black text-white">{item.team_name}</p>
                                <p className="text-xs text-slate-400">Seed #{item.seed} · {item.region}</p>
                                <p className="text-[11px] text-slate-500">{item.note}</p>
                            </div>
                            <div className="text-right">
                                <div className="text-lg font-black text-yellow-300">{champLabel}</div>
                                <p className="text-[10px] text-slate-500">champion</p>
                            </div>
                        </div>
                    );
                })}
            </div>
        </div>
    );
};

const ROUND_LABELS = {
    round_of_64: 'Round of 64',
    round_of_32: 'Round of 32',
    sweet_16: 'Sweet 16',
    elite_8: 'Elite 8'
};

const BracketTable = ({ data, roundLabels }) => {
    if (!data) return null;
    const rows = [];
    Object.entries(data.regions || {}).forEach(([region, rounds = {}]) => {
        Object.entries(roundLabels).forEach(([roundKey, label]) => {
            (rounds[roundKey] || []).forEach((match, idx) => {
                const resolvedFavorite = resolveBracketFavorite(match);
                rows.push({
                    region,
                    round: label,
                    teamA: match.team_a,
                    teamB: match.team_b,
                    favorite: resolvedFavorite.favoriteTeam,
                    favoritePct: resolvedFavorite.favoritePct,
                    dogPct: resolvedFavorite.dogPct,
                    winProbA: Number(match.win_prob_a) || 0,
                    winProbB: Number(match.win_prob_b) || 0,
                    key: `${region}-${roundKey}-${idx}-${match.team_a}-${match.team_b}`
                });
            });
        });
    });
    (data.final_four || []).forEach((match, idx) => {
        const resolvedFavorite = resolveBracketFavorite(match);
        rows.push({
            region: 'Final Four',
            round: 'Final Four',
            teamA: match.team_a,
            teamB: match.team_b,
            favorite: resolvedFavorite.favoriteTeam,
            favoritePct: resolvedFavorite.favoritePct,
            dogPct: resolvedFavorite.dogPct,
            winProbA: Number(match.win_prob_a) || 0,
            winProbB: Number(match.win_prob_b) || 0,
            key: `ff-${idx}-${match.team_a}-${match.team_b}`
        });
    });
    if (data.championship) {
        const match = data.championship;
        const resolvedFavorite = resolveBracketFavorite(match);
        rows.push({
            region: 'Championship',
            round: 'Championship',
            teamA: match.team_a,
            teamB: match.team_b,
            favorite: resolvedFavorite.favoriteTeam,
            favoritePct: resolvedFavorite.favoritePct,
            dogPct: resolvedFavorite.dogPct,
            winProbA: Number(match.win_prob_a) || 0,
            winProbB: Number(match.win_prob_b) || 0,
            key: `champ-${match.team_a}-${match.team_b}`
        });
        if (data.champion) {
            rows.push({
                region: 'Champion',
                round: 'Outcome',
                teamA: data.champion,
                teamB: '',
                favorite: data.champion,
                favoritePct: resolvedFavorite.favoritePct,
                dogPct: resolvedFavorite.dogPct,
                winProbA: Number(match.win_prob_a) || 0,
                winProbB: 0,
                key: `champ-text-${data.champion}`
            });
        }
    }
    const formatPercent = (value) => value ? `${value.toFixed(1)}%` : '—';
    if (!rows.length) return <div className="text-center text-slate-500 text-sm py-6">Bracket table not available yet.</div>;
    return (
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4 shadow-lg text-xs text-slate-300">
            <div className="flex items-center justify-between mb-3">
                <div className="text-[11px] uppercase tracking-[0.4em] text-slate-500">Bracket Table</div>
                <div className="text-[10px] text-slate-400">Sorted by region & round</div>
            </div>
            <div className="overflow-x-auto">
                <table className="w-full text-left">
                    <thead>
                        <tr className="text-[10px] uppercase text-slate-500 tracking-[0.4em] border-b border-slate-800">
                            <th className="pb-2 pr-3">Region</th>
                            <th className="pb-2 pr-3">Round</th>
                            <th className="pb-2 pr-3">Team A</th>
                            <th className="pb-2 pr-3">Team B</th>
                            <th className="pb-2 pr-3">Favorite</th>
                            <th className="pb-2 pr-3 text-right">Fav %</th>
                            <th className="pb-2 pr-3 text-right">Dog %</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800">
                        {rows.map((row) => (
                            <tr key={row.key} className="hover:bg-slate-800/40 transition">
                                <td className="py-2 pr-3 font-bold text-white">{row.region}</td>
                                <td className="py-2 pr-3 text-slate-400">{row.round}</td>
                                <td className="py-2 pr-3">{row.teamA}</td>
                                <td className="py-2 pr-3">{row.teamB}</td>
                                <td className="py-2 pr-3 text-emerald-400">{row.favorite}</td>
                                <td className="py-2 pr-3 text-right text-slate-200">{formatPercent(row.favoritePct)}</td>
                                <td className="py-2 pr-3 text-right text-slate-400">{formatPercent(row.dogPct)}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
};

const BracketView = ({ data, loading, onMatchupClick, insights = {}, mode = 'theater' }) => {
    const { upsetMatches = [], darkHorseTeams = [] } = insights;
    if (mode === 'table') return <BracketTable data={data} roundLabels={ROUND_LABELS} />;
    if (loading) return (
        <div className="p-12 flex flex-col items-center justify-center min-h-[400px] gap-3 text-slate-400">
            <RefreshCw size={32} className="text-orange-500 animate-spin" />
            <span className="font-bold tracking-widest uppercase text-xs">Computing Tournament Projections…</span>
        </div>
    );
    if (!data || !data.regions) return <div className="p-12 text-center text-red-400 font-mono">Bracket data unavailable. Check back soon.</div>;

    const champ = data.championship;
    const champion = data.champion;
    const showChampion = shouldShowChampion(data);

    return (
        <div className="py-8 space-y-12 animate-in fade-in slide-in-from-bottom-4 duration-700 px-4">
            
            {data.degraded_simulation && (
                <div className="max-w-4xl mx-auto bg-amber-500/10 border border-amber-500/30 rounded-2xl p-4 flex items-center gap-4 text-amber-200">
                    <AlertTriangle size={24} className="shrink-0 text-amber-500" />
                    <div>
                        <div className="text-sm font-bold uppercase tracking-tight">Degraded Simulation Mode</div>
                        <p className="text-xs opacity-80">This bracket contains matchups with missing performance data (e.g. invalid team mappings or new D1 teams). Seed-based priors were used for those specific games. Look for the <AlertTriangle size={10} className="inline mx-0.5" /> icon on affected matchups.</p>
                    </div>
                    {data.data_issues && data.data_issues.length > 0 && (
                        <div className="ml-auto text-[10px] font-mono bg-amber-500/20 px-2 py-1 rounded">
                            {data.data_issues.length} Issues
                        </div>
                    )}
                </div>
            )}

            {(upsetMatches.length > 0 || darkHorseTeams.length > 0) && (
                <div className="max-w-5xl mx-auto px-4 space-y-4">
                    <div className="grid md:grid-cols-2 gap-4">
                        <UpsetWatchlist items={upsetMatches} />
                        <DarkHorseWatchlist items={darkHorseTeams} />
                    </div>
                </div>
            )}

            {/* Bracket Layout (2x2 regions + center Final Four) */}
            <div className="max-w-[1800px] mx-auto">
                <div className="grid grid-cols-[1fr_auto_1fr] grid-rows-2 gap-x-10 gap-y-14 items-start">

                    {/* Top-left: East */}
                    <div className="space-y-3">
                        <h2 className="text-base md:text-lg font-black italic text-blue-500 border-l-4 border-blue-500 pl-3 tracking-wide">EAST</h2>
                        <RegionTree name="East" region={data.regions['East']} onMatchupClick={onMatchupClick} mirrored={false} />
                    </div>

                    {/* Center: Final Four + Champion (spans both rows) */}
                    <div className="row-span-2 flex flex-col items-center justify-center min-w-[280px] gap-10 pt-2">
                        {showChampion && (
                            <div className="relative overflow-hidden rounded-3xl border-2 border-yellow-500/40 bg-gradient-to-br from-yellow-950/80 via-slate-900 to-slate-950 p-8 text-center shadow-[0_0_60px_-15px_rgba(234,179,8,0.5)] z-10">
                                <div className="absolute top-0 left-1/2 -translate-x-1/2 w-72 h-72 bg-yellow-500/20 rounded-full blur-[90px] pointer-events-none" />
                                <div className="relative">
                                    <Award className="mx-auto mb-3 text-yellow-500" size={40} />
                                    <div className="text-[10px] font-black text-yellow-500 uppercase tracking-[0.45em] mb-2 text-center">Champion</div>
                                    <div className="text-3xl font-black text-white mb-3 tracking-tighter drop-shadow-2xl">{champion}</div>
                                    {champ && (
                                        <div className="flex items-center justify-center gap-3 text-[11px] font-bold text-slate-400">
                                            <span className="bg-slate-800/80 px-3 py-1 rounded-full">{Math.max(champ.win_prob_a, champ.win_prob_b)}% Win</span>
                                            <span className="bg-slate-800/80 px-3 py-1 rounded-full">{champ.projected_spread_a > 0 ? '+' : ''}{champ.projected_spread_a}</span>
                                        </div>
                                    )}
                                </div>
                            </div>
                        )}

                        {data.final_four?.length > 0 && (
                            <div className="space-y-5 w-full">
                                <div className="flex flex-col items-center gap-2">
                                    <span className="text-2xl font-black text-white italic tracking-tight uppercase">Final Four</span>
                                    <div className="h-0.5 w-28 bg-gradient-to-r from-transparent via-yellow-500 to-transparent" />
                                </div>
                                <div className="flex flex-col gap-4">
                                    {data.final_four.map((m, i) => (
                                        <div key={i} className="relative flex items-center justify-center">
                                            <div className="absolute top-1/2 -left-10 w-10 h-px bg-slate-700" />
                                            <div className="absolute top-1/2 -right-10 w-10 h-px bg-slate-700" />
                                            <MatchupCard m={m} onMatchupClick={onMatchupClick} />
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}

                        <div className="text-center text-[10px] text-slate-600 font-bold uppercase tracking-widest">
                            Model Output • 2026
                        </div>
                    </div>

                    {/* Top-right: West */}
                    <div className="space-y-3">
                        <h2 className="text-base md:text-lg font-black italic text-rose-500 border-r-4 border-rose-500 pr-3 text-right tracking-wide">WEST</h2>
                        <RegionTree name="West" region={data.regions['West']} onMatchupClick={onMatchupClick} mirrored={true} />
                    </div>

                    {/* Bottom-left: South */}
                    <div className="space-y-3">
                        <h2 className="text-base md:text-lg font-black italic text-emerald-500 border-l-4 border-emerald-500 pl-3 tracking-wide">SOUTH</h2>
                        <RegionTree name="South" region={data.regions['South']} onMatchupClick={onMatchupClick} mirrored={false} />
                    </div>

                    {/* Bottom-right: Midwest */}
                    <div className="space-y-3">
                        <h2 className="text-base md:text-lg font-black italic text-purple-500 border-r-4 border-purple-500 pr-3 text-right tracking-wide">MIDWEST</h2>
                        <RegionTree name="Midwest" region={data.regions['Midwest']} onMatchupClick={onMatchupClick} mirrored={true} />
                    </div>

                </div>
            </div>
            
        </div>
    );
};

export default MarchMadness;



