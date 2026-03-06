import React, { useState, useEffect } from 'react';
import api from '../api/axios';
import { Search, Brain, Gavel, FileText, ChevronRight, Activity, Clock, ShieldAlert, RefreshCw, AlertTriangle } from 'lucide-react';

export default function AgentCouncil() {
    const [events, setEvents] = useState([]);
    const [selectedEvent, setSelectedEvent] = useState(null);
    const [councilData, setCouncilData] = useState(null);
    const [memories, setMemories] = useState([]);
    const [loading, setLoading] = useState(true);
    const [loadingCouncil, setLoadingCouncil] = useState(false);
    const [activeTab, setActiveTab] = useState('debate');
    const [isRunningJob, setIsRunningJob] = useState(false);

    useEffect(() => {
        loadData();
    }, []);

    const loadData = async () => {
        setLoading(true);
        try {
            // Re-using the recommendations endpoint to get the days slate.
            // IMPORTANT: load docket even if council memories fail (auth / empty DB / etc.).
            const slateRes = await api.get('/api/ncaam/top-picks', { params: { limit_games: 200 } });

            let memRes = null;
            try {
                memRes = await api.get('/api/v1/council/memories');
            } catch (e) {
                // Keep the docket usable even if memories are unavailable.
                memRes = null;
            }

            const topPicks = slateRes.data.picks || {};
            const allEvents = Object.keys(topPicks)
                .filter(eid => topPicks[eid] && topPicks[eid].event && topPicks[eid].rec)
                .map(eid => {
                    const data = topPicks[eid];
                    return {
                        offer: {
                            event_id: eid,
                            market_type: data.rec ? (data.rec.bet_type || data.rec.market_type || 'Unknown') : 'Analysis Pending',
                            side: data.rec ? (data.rec.selection || 'Unknown Side') : '',
                            line: data.rec ? (data.rec.market_line || data.rec.line || '') : '',
                            odds_american: data.rec ? (data.rec.price || data.rec.odds_american || '') : ''
                        },
                        ...data
                    };
                });

            setEvents(allEvents);
            setMemories(memRes?.data?.data || []);
        } catch (err) {
            console.error("Failed to load council base data", err);
        } finally {
            setLoading(false);
        }
    };

    const handleSelectEvent = async (ev) => {
        setSelectedEvent(ev);
        setLoadingCouncil(true);
        setCouncilData(null);
        try {
            const res = await api.get('/api/v1/council', { params: { event_id: ev.offer.event_id } });
            if (res.data.status === 'success') {
                setCouncilData(res.data.data);
            } else if (res.data.message?.includes('Rate Limit') || res.data.data?.oracle_verdict?.includes('Rate Limit')) {
                setCouncilData({
                    rate_limited: true,
                    error: 'Gemini API Rate Limit Exceeded',
                    verdict: res.data.data?.oracle_verdict || 'The daily API quota has been exhausted. Analysis will resume automatically once the limit resets.'
                });
            } else {
                setCouncilData({ error: res.data.message });
            }
        } catch (err) {
            setCouncilData({ error: 'Debate not found for this event. Click "Refresh" to trigger the Agent Council.' });
        } finally {
            setLoadingCouncil(false);
        }
    };

    const triggerJobs = async () => {
        if (!window.confirm("Trigger the Agent Council to analyze today's slate? This process uses LLM agents to research and debate games, which may take 1-2 minutes.")) return;

        setIsRunningJob(true);
        try {
            // We use the password as the CRON_SECRET which is supported by the backend
            const password = localStorage.getItem('basement_password');
            const headers = { 'Authorization': `Bearer ${password}` };

            // 1. Grade Predictions
            await api.post('/api/jobs/grade_predictions', {}, { headers, params: { backfill_days: 5 } });

            // 2. Run Council with mode=agents to trigger the orchestrator
            await api.post('/api/jobs/run_council_today', {}, { headers, params: { mode: 'agents' } });

            alert("Council analysis complete! Refreshing the docket and memories.");
            await loadData();
        } catch (err) {
            console.error("Job trigger failed", err);
            alert("Failed to trigger jobs. Note: if you are running locally without a GEMINI_API_KEY, the LLM agents will gracefully skip evaluation.");
        } finally {
            setIsRunningJob(false);
        }
    };

    // Agent Avatar Mapping
    const getAgentIcon = (agentName) => {
        const name = agentName.toLowerCase();
        if (name.includes('stat') || name.includes('quant')) return <Activity className="text-blue-400" />;
        if (name.includes('news') || name.includes('injury') || name.includes('qualitative')) return <FileText className="text-orange-400" />;
        if (name.includes('memory') || name.includes('rag')) return <Brain className="text-purple-400" />;
        if (name.includes('executive') || name.includes('summary')) return <Gavel className="text-violet-400" />;
        if (name.includes('contrarian') || name.includes('auditor')) return <AlertTriangle className="text-rose-400" />;
        return <Search className="text-slate-400" />;
    };

    if (loading) {
        return (
            <div className="flex justify-center items-center h-64 text-slate-400 animate-pulse">
                Summoning the Council...
            </div>
        );
    }

    return (
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-6 animate-in fade-in duration-500">
            {/* Left Sidebar: Daily Slate & Global Memories */}
            <div className="lg:col-span-1 space-y-6">
                <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
                    <div className="flex items-center justify-between mb-4">
                        <h2 className="text-lg font-bold text-white flex items-center gap-2">
                            <Gavel className="text-blue-500" /> Today's Docket
                        </h2>
                        <button
                            onClick={triggerJobs}
                            disabled={isRunningJob}
                            className={`p-1.5 rounded-lg border transition-all flex items-center gap-2 text-[10px] font-bold uppercase tracking-wider ${isRunningJob
                                ? 'bg-slate-800 border-slate-700 text-slate-500 cursor-not-allowed'
                                : 'bg-blue-600/10 border-blue-500/30 text-blue-400 hover:bg-blue-600/20 hover:border-blue-500/50'
                                }`}
                            title="Manually trigger backend grading and council runs"
                        >
                            <RefreshCw size={12} className={isRunningJob ? 'animate-spin' : ''} />
                            {isRunningJob ? 'Running...' : 'Refresh'}
                        </button>
                    </div>
                    {events.length === 0 ? (
                        <p className="text-sm text-slate-500 italic">No games on the slate.</p>
                    ) : (
                        <div className="space-y-2 max-h-[400px] overflow-y-auto pr-1">
                            {events.map((ev, idx) => (
                                <button
                                    key={idx}
                                    onClick={() => handleSelectEvent(ev)}
                                    className={`w-full text-left p-3 rounded-lg border transition flex justify-between items-center ${selectedEvent?.offer?.event_id === ev.offer.event_id
                                        ? 'bg-blue-900/40 border-blue-500/50 text-blue-100'
                                        : 'bg-slate-800/40 border-slate-700/50 text-slate-300 hover:bg-slate-800'
                                        }`}
                                >
                                    <div>
                                        <div className="font-semibold text-sm">
                                            {ev.event?.away_team && ev.event?.home_team
                                                ? `${ev.event.away_team} @ ${ev.event.home_team}`
                                                : ev.offer.event_id.replace('NCAAB_', '').replace('action:ncaam:', 'Game ')}
                                        </div>
                                        {ev.rec ? (
                                            <div className="text-xs opacity-70 mt-1">{ev.offer.market_type} • {ev.offer.side}</div>
                                        ) : (
                                            <div className="text-xs opacity-70 mt-1 italic text-slate-500">Awaiting Model Edge</div>
                                        )}
                                    </div>
                                    <ChevronRight size={16} className="opacity-50" />
                                </button>
                            ))}
                        </div>
                    )}
                </div>

                <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
                    <h2 className="text-lg font-bold text-white mb-4 flex items-center gap-2">
                        <Brain className="text-blue-400" /> The Council Members
                    </h2>
                    <div className="space-y-4">
                        <div className="flex gap-3">
                            <Activity className="text-blue-400 shrink-0 mt-1" size={18} />
                            <div>
                                <div className="text-sm font-bold text-slate-200">Stats Agent</div>
                                <div className="text-xs text-slate-500 leading-tight mt-0.5 break-words">Analyzes quantitative Torvik and KenPom efficiency metrics.</div>
                            </div>
                        </div>
                        <div className="flex gap-3">
                            <FileText className="text-orange-400 shrink-0 mt-1" size={18} />
                            <div>
                                <div className="text-sm font-bold text-slate-200">News/Injury Agent</div>
                                <div className="text-xs text-slate-500 leading-tight mt-0.5 break-words">Scours the web for roster updates, fatigue, and situational spots.</div>
                            </div>
                        </div>
                        <div className="flex gap-3">
                            <Brain className="text-purple-400 shrink-0 mt-1" size={18} />
                            <div>
                                <div className="text-sm font-bold text-slate-200">Memory Agent</div>
                                <div className="text-xs text-slate-500 leading-tight mt-0.5 break-words">Recalls lessons learned from past model failures.</div>
                            </div>
                        </div>
                        <div className="flex gap-3">
                            <AlertTriangle className="text-rose-400 shrink-0 mt-1" size={18} />
                            <div>
                                <div className="text-sm font-bold text-slate-200">Contrarian Auditor</div>
                                <div className="text-xs text-slate-500 leading-tight mt-0.5 break-words">Identifies groupthink, stresses model assumptions, and flags ignored risks.</div>
                            </div>
                        </div>
                        <div className="flex gap-3">
                            <Gavel className="text-slate-200 shrink-0 mt-1" size={18} />
                            <div>
                                <div className="text-sm font-bold text-slate-200">The Oracle</div>
                                <div className="text-xs text-slate-500 leading-tight mt-0.5 break-words">Synthesizes debate to provide final spread/total adjustments.</div>
                            </div>
                        </div>
                    </div>
                </div>

                <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
                    <h2 className="text-lg font-bold text-white mb-4 flex items-center gap-2">
                        <Brain className="text-purple-400" /> Recent Post-Mortems
                    </h2>
                    {memories.length === 0 ? (
                        <p className="text-sm text-slate-500 italic">No memories yet. The system learns after games complete.</p>
                    ) : (
                        <div className="space-y-3 max-h-[300px] overflow-y-auto pr-1">
                            {memories.map((m, idx) => (
                                <div key={idx} className="p-3 bg-slate-800/40 rounded-lg border border-slate-700/50 text-sm break-words relative">
                                    <div className="flex justify-between items-start mb-1">
                                        <div className="text-xs font-bold text-purple-400">
                                            {m.team_a} vs {m.team_b}
                                            <div className="text-[10px] text-slate-500 font-normal mt-0.5">
                                                {m.timestamp ? new Date(m.timestamp).toLocaleDateString() : 'Historical'}
                                            </div>
                                        </div>
                                        {(() => {
                                            let res = "UNKNOWN";
                                            try {
                                                if (m.context && m.context.startsWith('{')) {
                                                    const parsed = JSON.parse(m.context);
                                                    res = parsed.result || "UNKNOWN";
                                                } else if (m.lesson && m.lesson.includes('[WON]')) res = "WON";
                                                else if (m.lesson && m.lesson.includes('[LOST]')) res = "LOST";
                                                else if (m.lesson && m.lesson.includes('[PUSH]')) res = "PUSH";
                                                else if (m.lesson && m.lesson.includes('[VOID]')) res = "VOID";
                                            } catch (e) { }

                                            const colors = {
                                                "WON": "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
                                                "LOST": "bg-rose-500/20 text-rose-400 border-rose-500/30",
                                                "PUSH": "bg-amber-500/20 text-amber-400 border-amber-500/30",
                                                "VOID": "bg-slate-500/20 text-slate-400 border-slate-500/30",
                                                "UNKNOWN": "bg-slate-700/50 text-slate-400 border-slate-600/50"
                                            };

                                            return (
                                                <span className={`text-[10px] px-1.5 py-0.5 rounded border font-bold uppercase ${colors[res] || colors.UNKNOWN}`}>
                                                    {res}
                                                </span>
                                            );
                                        })()}
                                    </div>
                                    <div className="text-slate-300 italic whitespace-pre-wrap">
                                        "{(() => {
                                            try {
                                                let displayLesson = m.lesson || "";
                                                // ONLY strip the status tag, leave everything else (date, bet, lesson)
                                                displayLesson = displayLesson.replace(/^\[(WON|LOST|PUSH|VOID|UNKNOWN|CORRECT|INCORRECT)\]\s*/i, '');

                                                if (displayLesson && (displayLesson.startsWith('{') || displayLesson.startsWith('['))) {
                                                    const parsed = JSON.parse(displayLesson);
                                                    return parsed.lesson || JSON.stringify(parsed, null, 2);
                                                }
                                                return displayLesson;
                                            } catch (e) {
                                                return m.lesson;
                                            }
                                        })()}"
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            </div>

            {/* Main Content: The Debate */}
            <div className="lg:col-span-3">
                {!selectedEvent ? (
                    <div className="h-full min-h-[400px] flex flex-col justify-center items-center border border-slate-800 border-dashed rounded-xl bg-slate-900/20 text-slate-500">
                        <Gavel size={48} className="mb-4 opacity-50 text-blue-500" />
                        <p>Select a game from the docket to view the Council's debate.</p>
                    </div>
                ) : (
                    <div className="bg-slate-900 border border-slate-800 rounded-xl flex flex-col h-full min-h-[600px] overflow-hidden">
                        {/* Debate Header */}
                        <div className="p-6 border-b border-slate-800 bg-slate-900/80">
                            <div className="flex justify-between items-start">
                                <div>
                                    <h2 className="text-2xl font-black text-white">
                                        {selectedEvent.event?.away_team && selectedEvent.event?.home_team
                                            ? `${selectedEvent.event.away_team} @ ${selectedEvent.event.home_team}`
                                            : selectedEvent.offer.event_id.replace('NCAAB_', '').replace('action:ncaam:', 'Game ')}
                                    </h2>
                                    <div className="flex gap-4 mt-2 text-sm text-slate-400">
                                        <span><strong className="text-slate-300">Market:</strong> {selectedEvent.offer.market_type}</span>
                                        <span><strong className="text-slate-300">Target Side:</strong> {selectedEvent.offer.side}</span>
                                        <span><strong className="text-slate-300">Line:</strong> {selectedEvent.offer.line}</span>
                                    </div>
                                </div>
                                <div className="flex bg-slate-950 p-1 rounded-lg border border-slate-800">
                                    <button
                                        onClick={() => setActiveTab('debate')}
                                        className={`px-4 py-1.5 rounded-md text-xs font-bold transition ${activeTab === 'debate' ? 'bg-blue-600 text-white shadow-lg' : 'text-slate-500 hover:text-slate-300'}`}
                                    >
                                        DEBATE
                                    </button>
                                    <button
                                        onClick={() => setActiveTab('activity')}
                                        className={`px-4 py-1.5 rounded-md text-xs font-bold transition flex items-center gap-2 ${activeTab === 'activity' ? 'bg-blue-600 text-white shadow-lg' : 'text-slate-500 hover:text-slate-300'}`}
                                    >
                                        ACTIVITY LOG {councilData?.traces?.length > 0 && <span className="bg-slate-900/50 px-1 rounded text-[10px]">{councilData.traces.length}</span>}
                                    </button>
                                </div>
                            </div>
                        </div>

                        {/* Debate Body */}
                        <div className="p-6 flex-1 bg-slate-950 overflow-y-auto">
                            {loadingCouncil ? (
                                <div className="flex flex-col justify-center items-center h-64 text-blue-500 animate-pulse">
                                    <Clock className="animate-spin mb-4" size={32} />
                                    <p className="text-slate-400">The Council is convening...</p>
                                </div>
                            ) : councilData?.rate_limited ? (
                                <div className="p-8 bg-blue-900/10 border border-blue-900/40 rounded-2xl text-center max-w-2xl mx-auto mt-12">
                                    <Clock className="mx-auto text-blue-400 mb-4 opacity-80" size={48} />
                                    <h3 className="text-xl font-bold text-white mb-2">Council on Standby</h3>
                                    <p className="text-slate-400 leading-relaxed">
                                        The daily Gemini API quota is currently exhausted. To ensure accuracy and prevent model degradation, the Council has paused active game analysis.
                                    </p>
                                    <div className="mt-6 p-4 bg-slate-900/80 rounded-xl border border-blue-500/20 text-blue-300 font-serif italic">
                                        "{councilData.verdict}"
                                    </div>
                                </div>
                            ) : councilData?.error ? (
                                <div className="p-6 bg-red-900/20 border border-red-900/50 rounded-xl text-center">
                                    <ShieldAlert className="mx-auto text-red-500 mb-2" size={32} />
                                    <p className="text-red-400 font-semibold">{councilData.error}</p>
                                    <p className="text-xs text-red-500/70 mt-2">The orchestrator must run `mode=agents` to generate debates.</p>
                                </div>
                            ) : activeTab === 'debate' ? (
                                <div className="space-y-6">
                                    {/* The Debate Transcript */}
                                    <div className="space-y-6">
                                        {(councilData?.narrative?.debate || councilData?.debate)?.map((msg, idx) => (
                                            <div key={idx} className="flex gap-4">
                                                <div className="w-10 h-10 rounded-full bg-slate-800 flex items-center justify-center border border-slate-700 shrink-0">
                                                    {getAgentIcon(msg.agent)}
                                                </div>
                                                <div className="flex-1 bg-slate-900 border border-slate-800 rounded-2xl rounded-tl-sm p-4">
                                                    <div className="font-bold text-sm text-slate-300 mb-1">{msg.agent}</div>
                                                    <div className="text-slate-400 text-sm leading-relaxed whitespace-pre-wrap">{msg.message}</div>
                                                </div>
                                            </div>
                                        ))}
                                    </div>

                                    {/* The Oracle's Verdict */}
                                    <div className="mt-8">
                                        <div className="relative">
                                            <div className="absolute inset-0 bg-gradient-to-r from-blue-600 to-purple-600 rounded-xl blur opacity-30"></div>
                                            <div className="relative bg-slate-900 border border-blue-500/30 rounded-xl p-6 shadow-2xl">
                                                <div className="flex items-center gap-3 mb-4">
                                                    <div className="bg-blue-500 p-2 rounded-lg">
                                                        <Gavel className="text-white" size={20} />
                                                    </div>
                                                    <h3 className="text-xl font-black text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-purple-400 uppercase tracking-widest">
                                                        The Oracle's Verdict
                                                    </h3>
                                                </div>
                                                <p className="text-lg text-slate-200 leading-relaxed font-serif italic">
                                                    "{councilData?.narrative?.oracle_verdict || councilData?.oracle_verdict}"
                                                </p>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            ) : (
                                <div className="space-y-4">
                                    {councilData?.traces?.length === 0 ? (
                                        <div className="text-center py-12 text-slate-500">
                                            No granular activity logs found for this run.
                                        </div>
                                    ) : (
                                        <div className="relative pl-8 space-y-6 before:absolute before:left-[11px] before:top-2 before:bottom-2 before:w-0.5 before:bg-slate-800">
                                            {councilData.traces.map((t, idx) => (
                                                <div key={idx} className="relative">
                                                    <div className="absolute -left-[31px] top-1 w-6 h-6 rounded-full bg-slate-950 border-2 border-slate-800 flex items-center justify-center z-10">
                                                        <div className="w-2 h-2 rounded-full bg-blue-500 shadow-[0_0_8px_rgba(59,130,246,0.5)]"></div>
                                                    </div>
                                                    <div className="bg-slate-900/50 border border-slate-800/50 rounded-xl p-4">
                                                        <div className="flex justify-between items-start mb-2">
                                                            <div>
                                                                <span className="text-[10px] font-black text-blue-500 uppercase tracking-tighter mr-2">{t.agent_name}</span>
                                                                <span className="text-sm font-bold text-slate-200">{t.task_description}</span>
                                                            </div>
                                                            <span className="text-[10px] text-slate-500 font-mono">
                                                                {new Date(t.timestamp).toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                                                            </span>
                                                        </div>
                                                        {t.details && (
                                                            <div className="mt-2 text-xs text-slate-400 bg-slate-950/50 p-3 rounded-lg border border-slate-800/30 overflow-x-auto">
                                                                {t.details.url ? (
                                                                    <a href={t.details.url} target="_blank" rel="noreferrer" className="text-blue-400 hover:underline flex items-center gap-1">
                                                                        <Search size={12} /> {t.details.url}
                                                                    </a>
                                                                ) : (
                                                                    <pre className="whitespace-pre-wrap font-mono text-[11px] text-slate-500">
                                                                        {JSON.stringify(t.details, null, 2)}
                                                                    </pre>
                                                                )}
                                                            </div>
                                                        )}
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                    )}
                                </div>
                            )}
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}
