import React, { useEffect, useMemo, useState } from 'react';
import api from '../api/axios';
import { RefreshCw, Activity, BarChart3, TrendingUp, ArrowUpDown, ChevronUp, ChevronDown, CheckCircle } from 'lucide-react';
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid, ReferenceLine, Cell, LabelList, LineChart, Line as ReLine
} from 'recharts';

// ─── Helpers ────────────────────────────────────────────────────────────────

const fmt = (v, def = '—') => (v === null || v === undefined || v === '' ? def : v);
const fmtOdds = (v) => {
  if (!v && v !== 0) return '—';
  const n = Number(v);
  return Number.isFinite(n) ? (n > 0 ? `+${n}` : String(n)) : '—';
};
const fmtPct = (v, digits = 1) => (v === null || v === undefined ? '—' : `${(Number(v) * 100).toFixed(digits)}%`);
const fmtRun = (v, digits = 1) => (v === null || v === undefined ? '—' : Number(v).toFixed(digits));

// ROI Math
const payoutPerUnitFromAmericanOdds = (price) => {
  const p = parseFloat(price);
  if (isNaN(p)) return 0.90909; 
  if (p === 0) return 1.0;
  if (p > 0) return p / 100;
  return 100 / Math.abs(p);
};

const roiPerUnit = (outcome, price) => {
  const o = String(outcome || '').toUpperCase();
  if (o === 'WON' || o === 'WIN') return payoutPerUnitFromAmericanOdds(price);
  if (o === 'LOST' || o === 'LOSS') return -1.0;
  return 0.0;
};

const OUTCOME_STYLE = {
  WON: 'text-emerald-400 font-black',
  WIN: 'text-emerald-400 font-black',
  LOST: 'text-red-400 font-black',
  LOSS: 'text-red-400 font-black',
  PUSH: 'text-slate-300 font-black',
  PENDING: 'text-slate-500',
  VOID: 'text-slate-600',
};
const outcomeText = (r) => {
  const s = String(r || 'PENDING').toUpperCase();
  return { text: s === 'WIN' ? 'WON' : s === 'LOSS' ? 'LOST' : s, cls: OUTCOME_STYLE[s] || 'text-slate-500' };
};

const CONFIDENCE_COLOR = { HIGH: 'text-emerald-400', MEDIUM: 'text-amber-400', LOW: 'text-slate-400' };
const MARKET_COLOR = {
  SPREAD: 'bg-blue-900/30 text-blue-300 border border-blue-800/40',
  TOTAL: 'bg-violet-900/30 text-violet-300 border border-violet-800/40',
  MONEYLINE: 'bg-amber-900/30 text-amber-300 border border-amber-800/40',
  NRFI: 'bg-emerald-900/30 text-emerald-300 border border-emerald-800/40',
};

// ─── Sub-Components ──────────────────────────────────────────────────────────

function StatTile({ label, value, sub, accent }) {
  return (
    <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4 flex flex-col gap-1">
      <div className="text-[10px] uppercase tracking-widest text-slate-500 font-black">{label}</div>
      <div className={`text-2xl font-black ${accent || 'text-slate-100'}`}>{value}</div>
      {sub && <div className="text-xs text-slate-500">{sub}</div>}
    </div>
  );
}

function GameCard({ game }) {
  const hasOdds = game.has_odds;
  const statusLower = (game.status || '').toLowerCase();
  const isLive = statusLower.includes('progress') || statusLower.includes('live');
  const isFinal = statusLower.includes('final') || statusLower.includes('complete');

  const spreadLabel = game.spread_home != null
    ? (game.spread_home > 0 ? `+${game.spread_home}` : String(game.spread_home))
    : null;

  return (
    <div className={`bg-slate-900/60 border rounded-xl p-4 transition-all hover:border-slate-600 ${isLive ? 'border-emerald-700/50' : 'border-slate-800'}`}>
      <div className="flex items-start justify-between gap-2 mb-3">
        <div className="min-w-0 flex-1">
          <div className="text-sm font-black text-white leading-tight truncate">
            {game.away_team} <span className="text-slate-500 font-normal">@</span> {game.home_team}
          </div>
        </div>
        <div className={`text-[10px] uppercase tracking-wider font-black px-2 py-0.5 rounded-full shrink-0 ${
          isLive ? 'bg-emerald-900/40 text-emerald-300 border border-emerald-700/40' :
          isFinal ? 'bg-slate-800 text-slate-500' :
          'bg-slate-800/50 text-slate-500'
        }`}>
          {isFinal ? 'Final' : isLive ? 'Live' : 'Pre-Game'}
        </div>
      </div>

      {/* Pitching */}
      <div className="grid grid-cols-2 gap-2 mb-3">
        {[{ label: game.away_team?.split(' ').pop(), pitcher: game.away_pitcher },
          { label: game.home_team?.split(' ').pop(), pitcher: game.home_pitcher }].map((p, i) => (
          <div key={i} className="bg-slate-800/30 rounded-lg p-2">
            <div className="text-[9px] uppercase tracking-widest text-slate-500 mb-0.5">{p.label} SP</div>
            <div className="text-xs font-bold text-slate-200 truncate">{p.pitcher || 'TBD'}</div>
          </div>
        ))}
      </div>

      {/* Odds */}
      {hasOdds ? (
        <div className="grid grid-cols-3 gap-2 text-center">
          <div className="bg-slate-800/30 rounded-lg p-2">
            <div className="text-[9px] uppercase tracking-widest text-slate-500 mb-1">Spread</div>
            <div className="text-xs font-black text-slate-200">{spreadLabel || '—'}</div>
          </div>
          <div className="bg-slate-800/30 rounded-lg p-2">
            <div className="text-[9px] uppercase tracking-widest text-slate-500 mb-1">O/U</div>
            <div className="text-xs font-black text-slate-200">{fmt(game.total)}</div>
          </div>
          <div className="bg-slate-800/30 rounded-lg p-2">
            <div className="text-[9px] uppercase tracking-widest text-slate-500 mb-1">ML</div>
            <div className="text-xs font-black text-slate-200">{fmtOdds(game.moneyline_home)}</div>
          </div>
        </div>
      ) : (
        <div className="text-xs text-slate-600 text-center py-1">No odds available</div>
      )}
    </div>
  );
}

function PredictionRow({ pred, idx }) {
  const market = (pred.market_type || '').toUpperCase();
  const { text: outcome, cls: outCls } = outcomeText(pred.graded_result || pred.outcome || pred.result);
  const ev = Number(pred.ev_per_unit || pred.ev || 0);
  const conf = Number(pred.confidence_0_100 || 0);
  const confLabel = conf >= 75 ? 'HIGH' : conf >= 50 ? 'MEDIUM' : 'LOW';
  
  const profit = roiPerUnit(pred.graded_result || pred.outcome || pred.result, pred.bet_line || pred.market_line || pred.odds);

  // Parse narrative_json for pitching matchup
  let narrative = {};
  try { narrative = JSON.parse(pred.narrative_json || '{}'); } catch (e) {}
  const homeSP = narrative?.pitching_matchup?.home || null;
  const awaySP = narrative?.pitching_matchup?.away || null;

  // Parse inputs for weather/park context
  let inputs = {};
  try { inputs = JSON.parse(pred.inputs_json || '{}'); } catch (e) {}

  return (
    <tr className="border-b border-slate-800/50 hover:bg-slate-800/20 transition-colors">
      <td className="py-3 px-4 text-xs text-slate-400">{pred.day_et || pred.analyzed_at?.slice(0, 10) || '—'}</td>
      <td className="py-3 px-4">
        <div className="text-xs font-black text-slate-100">
          {pred.matchup || (pred.away_team && pred.home_team ? `${pred.away_team} @ ${pred.home_team}` : '—')}
        </div>
        {(homeSP || awaySP) && (
          <div className="text-[10px] text-slate-500 mt-0.5">
            {awaySP || '?'} vs {homeSP || '?'}
          </div>
        )}
      </td>
      <td className="py-3 px-4">
        <span className={`text-[10px] font-black px-2 py-0.5 rounded-full ${MARKET_COLOR[market] || 'bg-slate-800 text-slate-400'}`}>
          {market}
        </span>
      </td>
      <td className="py-3 px-4 text-xs font-bold text-slate-100">{pred.selection || '—'}</td>
      <td className="py-3 px-4 text-xs text-slate-400">
        {Number.isFinite(ev) ? `${(ev * 100).toFixed(1)}%` : '—'}
      </td>
      <td className="py-3 px-4">
        <span className={`text-xs font-black ${CONFIDENCE_COLOR[confLabel] || 'text-slate-400'}`}>{confLabel}</span>
      </td>
      <td className={`py-3 px-4 text-xs ${outCls}`}>{outcome}</td>
      <td className={`py-3 px-4 text-xs font-mono font-bold ${profit > 0 ? 'text-emerald-400' : profit < 0 ? 'text-red-400' : 'text-slate-500'}`}>
        {outcome === 'PENDING' ? '—' : (profit > 0 ? `+${profit.toFixed(2)}` : profit.toFixed(2))}
      </td>
      <td className="py-3 px-4 text-[10px] text-slate-500 max-w-[200px]">
        {inputs.weather || '—'}
      </td>
    </tr>
  );
}

// ─── Main Component ──────────────────────────────────────────────────────────

export default function MLB() {
  const [slate, setSlate] = useState(null);
  const [predictions, setPredictions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const [isGrading, setIsGrading] = useState(false);
  const [err, setErr] = useState(null);
  const [activeTab, setActiveTab] = useState('today'); // today | history
  const [sortConfig, setSortConfig] = useState({ key: 'analyzed_at', direction: 'desc' });

  const load = async () => {
    setLoading(true);
    setErr(null);
    try {
      const [slateRes, predsRes] = await Promise.allSettled([
        api.get('/api/mlb/slate'),
        api.get('/api/mlb/predictions', { params: { lookback_days: 60 } }),
      ]);

      if (slateRes.status === 'fulfilled') setSlate(slateRes.value.data);
      if (predsRes.status === 'fulfilled') setPredictions(predsRes.value.data.predictions || []);
    } catch (e) {
      setErr(e?.response?.data?.detail || e?.message || 'Failed to load MLB data');
    } finally {
      setLoading(false);
    }
  };

  const runModel = async () => {
    setIsRunning(true);
    try {
      await api.post('/api/jobs/run_mlb_predictions');
      await load();
    } catch (e) {
      setErr(e?.response?.data?.detail || 'Failed to run MLB model');
    } finally {
      setIsRunning(false);
    }
  };

  const gradeResults = async () => {
    setIsGrading(true);
    try {
      await api.post('/api/research/grade');
      await load();
    } catch (e) {
      setErr(e?.response?.data?.detail || 'Failed to grade results');
    } finally {
      setIsGrading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const games = slate?.games || [];
  const totalGames = slate?.total_games || 0;
  const gamesWithOdds = slate?.games_with_odds || 0;

  // Split today's predictions vs history
  const todayEt = new Date().toLocaleDateString('en-CA', { timeZone: 'America/New_York' });

  const todayPreds = useMemo(() =>
    predictions.filter(p => {
      const day = p.day_et || (p.analyzed_at || '').slice(0, 10);
      return day === todayEt;
    }), [predictions, todayEt]);

  const historyPreds = useMemo(() => [...predictions].sort((a, b) => {
    const aVal = a[sortConfig.key] || '';
    const bVal = b[sortConfig.key] || '';
    return sortConfig.direction === 'asc' ? String(aVal).localeCompare(String(bVal)) : String(bVal).localeCompare(String(aVal));
  }), [predictions, sortConfig]);

  // Record stats
  const recordStats = useMemo(() => {
    const graded = predictions.filter(p => {
      const o = String(p.graded_result || p.outcome || p.result || '').toUpperCase();
      return ['WON', 'WIN', 'LOST', 'LOSS', 'PUSH'].includes(o);
    });
    const wins = graded.filter(p => ['WON', 'WIN'].includes(String(p.graded_result || p.outcome || p.result || '').toUpperCase())).length;
    const losses = graded.filter(p => ['LOST', 'LOSS'].includes(String(p.graded_result || p.outcome || p.result || '').toUpperCase())).length;
    const pushes = graded.filter(p => String(p.graded_result || p.outcome || p.result || '').toUpperCase() === 'PUSH').length;
    
    // Calculate total profit
    const netUnits = predictions.reduce((acc, p) => acc + roiPerUnit(p.graded_result || p.outcome || p.result, p.bet_line || p.market_line || p.odds), 0);
    
    const decided = wins + losses;
    const winRate = decided > 0 ? (wins / decided) * 100 : null;
    const roi = decided > 0 ? (netUnits / decided) * 100 : null;
    
    return { wins, losses, pushes, decided, winRate, netUnits, roi, total: predictions.length };
  }, [predictions]);

  // Market breakdown chart
  const marketChart = useMemo(() => {
    const grouped = {};
    predictions.forEach(p => {
      const mt = (p.market_type || 'OTHER').toUpperCase();
      if (!grouped[mt]) grouped[mt] = { market: mt, wins: 0, losses: 0, total: 0 };
      const o = String(p.graded_result || p.outcome || p.result || '').toUpperCase();
      grouped[mt].total += 1;
      if (['WON', 'WIN'].includes(o)) grouped[mt].wins += 1;
      else if (['LOST', 'LOSS'].includes(o)) grouped[mt].losses += 1;
    });
    return Object.values(grouped).map(g => ({
      ...g,
      winRate: (g.wins + g.losses) > 0 ? Number(((g.wins / (g.wins + g.losses)) * 100).toFixed(1)) : null,
    })).filter(g => g.total > 0);
  }, [predictions]);

  const SortIcon = ({ col }) => {
    if (sortConfig.key !== col) return <ArrowUpDown size={11} className="ml-1 opacity-20" />;
    return sortConfig.direction === 'asc' ? <ChevronUp size={11} className="ml-1 text-blue-400" /> : <ChevronDown size={11} className="ml-1 text-blue-400" />;
  };
  const handleSort = (key) => setSortConfig(prev => ({
    key,
    direction: prev.key === key && prev.direction === 'desc' ? 'asc' : 'desc',
  }));

  return (
    <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <span className="text-3xl">⚾</span>
            <div>
              <h2 className="text-2xl font-black text-white">MLB Model</h2>
              <div className="text-sm text-slate-400">
                {slate?.date || todayEt} · {totalGames} games · {gamesWithOdds} with odds
              </div>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={load}
            disabled={loading}
            className="px-4 py-2 rounded-xl bg-slate-800/60 hover:bg-slate-700/60 border border-slate-700/40 text-slate-200 text-sm font-semibold transition flex items-center gap-2"
          >
            <RefreshCw size={15} className={loading ? 'animate-spin' : ''} />
            Refresh
          </button>
          <button
            onClick={gradeResults}
            disabled={isGrading || loading}
            className={`px-4 py-2 rounded-xl text-sm font-semibold transition flex items-center gap-2 ${
              isGrading 
                ? 'bg-slate-800 text-slate-500 border border-slate-700/40' 
                : 'bg-blue-600/20 hover:bg-blue-600/30 border border-blue-600/30 text-blue-300'
            }`}
          >
            <CheckCircle size={15} className={isGrading ? 'animate-pulse' : ''} />
            {isGrading ? 'Grading…' : 'Grade Recent Results'}
          </button>
          <button
            onClick={runModel}
            disabled={isRunning}
            className={`px-4 py-2 rounded-xl text-sm font-bold transition flex items-center gap-2 ${
              isRunning
                ? 'bg-slate-800 text-slate-500 border border-slate-700/40 cursor-not-allowed'
                : 'bg-emerald-600/20 hover:bg-emerald-600/30 border border-emerald-600/30 text-emerald-300'
            }`}
          >
            <Activity size={15} className={isRunning ? 'animate-pulse' : ''} />
            {isRunning ? 'Running…' : 'Run Model Now'}
          </button>
        </div>
      </div>

      {err && (
        <div className="p-3 rounded-lg bg-red-900/20 border border-red-800/40 text-red-300 text-sm">{err}</div>
      )}

      {/* Record tiles */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatTile
          label="Record (All-Time)"
          value={recordStats.decided > 0 ? `${recordStats.wins}-${recordStats.losses}${recordStats.pushes ? `-${recordStats.pushes}` : ''}` : '—'}
          sub={`${recordStats.total} total picks`}
          accent="text-white"
        />
        <StatTile
          label="Win Rate"
          value={recordStats.winRate !== null ? `${recordStats.winRate.toFixed(1)}%` : '—'}
          sub="decided bets only"
          accent={recordStats.winRate !== null ? (recordStats.winRate >= 52.4 ? 'text-emerald-400' : 'text-red-400') : 'text-slate-400'}
        />
        <StatTile
          label="Profit (Units)"
          value={recordStats.decided > 0 ? (recordStats.netUnits > 0 ? `+${recordStats.netUnits.toFixed(2)}` : recordStats.netUnits.toFixed(2)) : '—'}
          sub={`${recordStats.decided} decided picks`}
          accent={recordStats.netUnits > 0 ? 'text-emerald-400' : recordStats.netUnits < 0 ? 'text-red-400' : 'text-slate-400'}
        />
        <StatTile
          label="ROI %"
          value={recordStats.roi !== null ? `${recordStats.roi.toFixed(1)}%` : '—'}
          sub="per unit wagered"
          accent={recordStats.roi > 0 ? 'text-emerald-400' : recordStats.roi < 0 ? 'text-red-400' : 'text-slate-400'}
        />
        <StatTile
          label="Today's Picks"
          value={todayPreds.length}
          sub={loading ? 'Loading…' : 'from model'}
          accent={todayPreds.length > 0 ? 'text-emerald-400' : 'text-slate-400'}
        />
      </div>

      {/* Market breakdown chart */}
      {marketChart.length > 0 && (
        <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-5">
          <div className="text-sm font-black text-slate-100 uppercase tracking-wider mb-4 flex items-center gap-2">
            <BarChart3 size={16} className="text-blue-400" />
            Win Rate by Market Type
          </div>
          <div className="h-[180px]">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={marketChart} margin={{ top: 8, right: 30, left: 0, bottom: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis dataKey="market" tick={{ fill: '#94a3b8', fontSize: 11 }} />
                <YAxis domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} tick={{ fill: '#94a3b8', fontSize: 11 }} />
                <Tooltip
                  contentStyle={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 8 }}
                  formatter={(v, name) => name === 'Win%' ? [`${v}%`, 'Win%'] : [v, name]}
                />
                <ReferenceLine y={50} stroke="#94a3b8" strokeDasharray="4 4" />
                <Bar dataKey="winRate" name="Win%" radius={[6, 6, 0, 0]}>
                  {marketChart.map((entry, i) => (
                    <Cell key={i} fill={entry.winRate !== null && entry.winRate >= 50 ? '#34d399' : '#60a5fa'} />
                  ))}
                  <LabelList dataKey="winRate" position="top" formatter={v => v !== null ? `${v}%` : ''} fill="#94a3b8" fontSize={11} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* Tabs */}
      <div className="inline-flex gap-1 p-1 rounded-xl bg-slate-900/40 border border-slate-700/40">
        {[{ id: 'today', label: "Today's Slate" }, { id: 'picks', label: "Today's Picks" }, { id: 'history', label: 'Pick History' }].map(t => (
          <button
            key={t.id}
            onClick={() => setActiveTab(t.id)}
            className={`px-4 py-2 rounded-lg text-sm font-semibold transition ${
              activeTab === t.id ? 'bg-slate-800/70 text-slate-100 shadow-sm ring-1 ring-white/10' : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/40'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab: Today's Slate */}
      {activeTab === 'today' && (
        <div>
          {loading && <div className="text-slate-500 text-sm animate-pulse py-4">Loading schedule...</div>}
          {!loading && games.length === 0 && (
            <div className="bg-slate-900/40 border border-slate-800 rounded-xl p-8 text-center text-slate-500">
              No games scheduled today or schedule not yet available.
            </div>
          )}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {games.map((g, i) => <GameCard key={i} game={g} />)}
          </div>
        </div>
      )}

      {/* Tab: Today's Picks */}
      {activeTab === 'picks' && (
        <div>
          {todayPreds.length === 0 ? (
            <div className="bg-slate-900/40 border border-slate-800 rounded-xl p-8 text-center">
              <div className="text-slate-400 mb-2">No picks generated yet for today.</div>
              <div className="text-slate-500 text-sm">Click <span className="text-emerald-400 font-bold">Run Model Now</span> to analyze today's slate.</div>
            </div>
          ) : (
            <div className="space-y-3">
              {todayPreds.sort((a, b) => Number(b.ev_per_unit || 0) - Number(a.ev_per_unit || 0)).map((pred, i) => {
                const market = (pred.market_type || '').toUpperCase();
                const ev = Number(pred.ev_per_unit || 0);
                const conf = Number(pred.confidence_0_100 || 0);
                const confLabel = conf >= 75 ? 'HIGH' : conf >= 50 ? 'MEDIUM' : 'LOW';
                let inputs = {}; try { inputs = JSON.parse(pred.inputs_json || '{}'); } catch (e) {}
                let narrative = {}; try { narrative = JSON.parse(pred.narrative_json || '{}'); } catch (e) {}
                return (
                  <div key={i} className="bg-slate-900/60 border border-slate-800 hover:border-slate-700 rounded-xl p-4 transition-all">
                    <div className="flex flex-col md:flex-row md:items-start gap-3">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1 flex-wrap">
                          <span className={`text-[10px] font-black px-2 py-0.5 rounded-full ${MARKET_COLOR[market] || 'bg-slate-800 text-slate-400'}`}>{market}</span>
                          <span className={`text-[10px] font-black ${CONFIDENCE_COLOR[confLabel]}`}>{confLabel}</span>
                          <span className="text-emerald-400 text-[10px] font-mono font-black">EV {(ev * 100).toFixed(1)}%</span>
                        </div>
                        <div className="text-white font-black text-base">{pred.selection || '—'}</div>
                        <div className="text-slate-400 text-xs mt-0.5">
                          {pred.matchup || (pred.away_team && pred.home_team ? `${pred.away_team} @ ${pred.home_team}` : '—')}
                        </div>
                        {(narrative?.pitching_matchup?.away || narrative?.pitching_matchup?.home) && (
                          <div className="text-slate-500 text-[10px] mt-1">
                            ⚾ {narrative.pitching_matchup.away || '?'} vs {narrative.pitching_matchup.home || '?'}
                          </div>
                        )}
                      </div>
                      <div className="shrink-0 text-right">
                        <div className="text-slate-500 text-[10px]">Proj Total</div>
                        <div className="text-slate-200 font-bold text-sm">{inputs.proj_total ? fmtRun(inputs.proj_total) : '—'}</div>
                        <div className="text-slate-600 text-[10px] mt-1">Mkt {inputs.market_total || '—'}</div>
                      </div>
                    </div>
                    {inputs.weather && inputs.weather !== 'Indoor/retractable roof — weather neutralized' && (
                      <div className="mt-2 text-[10px] text-slate-500 bg-slate-800/30 rounded-lg px-3 py-1.5">
                        🌤 {inputs.weather}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* Tab: Pick History */}
      {activeTab === 'history' && (
        <div className="bg-slate-900/60 border border-slate-800 rounded-xl overflow-hidden">
          <div className="px-5 py-4 border-b border-slate-800 flex items-center justify-between">
            <div className="text-sm font-black text-slate-100 uppercase tracking-wider">MLB Pick History</div>
            <div className="text-[11px] text-slate-500">{predictions.length} predictions</div>
          </div>
          {predictions.length === 0 ? (
            <div className="p-8 text-center text-slate-500 text-sm">No MLB prediction history yet. Run the model to get started.</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="border-b border-slate-700/60 bg-slate-800/30">
                    {[
                      { key: 'analyzed_at', label: 'Date' },
                      { key: 'matchup', label: 'Matchup' },
                      { key: 'market_type', label: 'Market' },
                      { key: 'selection', label: 'Pick' },
                      { key: 'ev_per_unit', label: 'EV' },
                      { key: 'confidence_0_100', label: 'Conf' },
                      { key: 'graded_result', label: 'Result' },
                      { key: null, label: 'Profit' },
                      { key: null, label: 'Context' },
                    ].map((col, i) => (
                      <th
                        key={i}
                        className={`py-2 px-4 text-[10px] uppercase tracking-wider text-slate-400 font-black ${col.key ? 'cursor-pointer hover:text-white transition-colors' : ''}`}
                        onClick={() => col.key && handleSort(col.key)}
                      >
                        <div className="flex items-center">
                          {col.label}
                          {col.key && <SortIcon col={col.key} />}
                        </div>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {historyPreds.map((p, i) => <PredictionRow key={i} pred={p} idx={i} />)}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
