import React, { useEffect, useMemo, useState } from 'react';
import api from '../api/axios';
import { RefreshCw, Activity, BarChart3, ArrowUpDown, ChevronUp, ChevronDown, CheckCircle } from 'lucide-react';
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid, ReferenceLine, Cell, LabelList
} from 'recharts';
import {
  roiPerUnit,
  getConfidenceBucket,
  getEffectivePrice,
  formatMatchup,
  normalizeOutcome,
  isWinOutcome,
  isLossOutcome,
} from '../utils/modelPerformance';

// ─── Helpers ────────────────────────────────────────────────────────────────

const fmt = (v, def = '—') => (v === null || v === undefined || v === '' ? def : v);
const fmtOdds = (v) => {
  if (!v && v !== 0) return '—';
  const n = Number(v);
  return Number.isFinite(n) ? (n > 0 ? `+${n}` : String(n)) : '—';
};
const fmtRun = (v, digits = 1) => (v === null || v === undefined ? '—' : Number(v).toFixed(digits));

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
    <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4 flex flex-col gap-1 min-w-0">
      <div className="text-[10px] uppercase tracking-widest text-slate-500 font-black">{label}</div>
      <div className={`text-xl sm:text-2xl font-black tabular-nums whitespace-nowrap ${accent || 'text-slate-100'}`}>{value}</div>
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
    <article className={`bg-slate-900/60 border rounded-xl p-4 transition-all hover:border-slate-600 ${isLive ? 'border-emerald-700/50' : 'border-slate-800'}`}>
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
    </article>
  );
}

function PredictionRow({ pred }) {
  const market = (pred.market_type || '').toUpperCase();
  const rawOutcome = pred.graded_result || pred.outcome || pred.result;
  const { text: outcome, cls: outCls } = outcomeText(rawOutcome);
  const ev = Number(pred.ev_per_unit || pred.ev || 0);
  const confLabel = getConfidenceBucket(pred.confidence_0_100).toUpperCase();
  const effectivePrice = getEffectivePrice(pred);
  const profit = roiPerUnit(rawOutcome, effectivePrice ?? -110);

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
      <td className="py-2.5 px-2.5 sm:px-3 text-xs text-slate-400 whitespace-nowrap font-mono tabular-nums">{pred.day_et || pred.analyzed_at?.slice(0, 10) || '—'}</td>
      <td className="py-2.5 px-2.5 sm:px-3 min-w-[140px]">
        <div className="text-xs font-black text-slate-100">
          {formatMatchup(pred) || pred.matchup || (pred.away_team && pred.home_team ? `${pred.away_team} @ ${pred.home_team}` : '—')}
        </div>
        {(homeSP || awaySP) && (
          <div className="text-[10px] text-slate-500 mt-0.5">
            {awaySP || '?'} vs {homeSP || '?'}
          </div>
        )}
      </td>
      <td className="py-2.5 px-2.5 sm:px-3 whitespace-nowrap">
        <span className={`text-[10px] font-black px-2 py-0.5 rounded-full ${MARKET_COLOR[market] || 'bg-slate-800 text-slate-400'}`}>
          {market}
        </span>
      </td>
      <td className="py-2.5 px-2.5 sm:px-3 text-xs font-bold text-slate-100">
        {pred.selection || '—'}
        {effectivePrice != null && (
          <span className="ml-1.5 text-[10px] font-mono font-normal text-slate-400">({fmtOdds(effectivePrice)})</span>
        )}
      </td>
      <td className="py-2.5 px-2.5 sm:px-3 text-xs text-slate-300 font-mono tabular-nums whitespace-nowrap">
        {Number.isFinite(ev) ? `${ev >= 0 ? '+' : ''}${(ev * 100).toFixed(1)}%` : '—'}
      </td>
      <td className="py-2.5 px-2.5 sm:px-3 whitespace-nowrap">
        <span className={`text-xs font-black ${CONFIDENCE_COLOR[confLabel] || 'text-slate-400'}`}>{confLabel}</span>
      </td>
      <td className={`py-2.5 px-2.5 sm:px-3 text-xs whitespace-nowrap ${outCls}`}>{outcome}</td>
      <td className={`py-2.5 px-2.5 sm:px-3 text-xs font-mono tabular-nums font-bold whitespace-nowrap ${profit > 0 ? 'text-emerald-400' : profit < 0 ? 'text-red-400' : 'text-slate-500'}`}>
        {outcome === 'PENDING' ? '—' : (profit > 0 ? `+${profit.toFixed(2)}u` : `${profit.toFixed(2)}u`)}
      </td>
      <td className="py-2.5 px-2.5 sm:px-3 text-[10px] text-slate-400 max-w-[160px]">
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
  const [lookbackDays, setLookbackDays] = useState(400);
  const [gradeStatus, setGradeStatus] = useState(null);
  const [err, setErr] = useState(null);
  const [activeTab, setActiveTab] = useState('today'); // today | picks | history
  const [sortConfig, setSortConfig] = useState({ key: 'analyzed_at', direction: 'desc' });

  const load = async (daysOverride = lookbackDays) => {
    setLoading(true);
    setErr(null);
    try {
      const [slateRes, predsRes] = await Promise.allSettled([
        api.get('/api/mlb/slate'),
        api.get('/api/mlb/predictions', { params: { lookback_days: daysOverride } }),
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
    setErr(null);
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
    setErr(null);
    setGradeStatus(null);
    try {
      const res = await api.post('/api/research/grade', {
        backfill_pending: true,
        max_grade_rows: 5000,
      });
      const data = res?.data || {};
      const g = Number(data.graded_predictions ?? data.predictions_graded ?? 0);
      const checked = Number(data.ingested_games ?? data.games_checked ?? 0);
      setGradeStatus(`Checked ${checked.toLocaleString()} game finals and graded ${g.toLocaleString()} pending pick(s).`);
      await load();
    } catch (e) {
      setErr(e?.response?.data?.detail || 'Failed to grade results');
    } finally {
      setIsGrading(false);
    }
  };

  useEffect(() => { load(lookbackDays); }, [lookbackDays]);

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
    const k = sortConfig.key;
    const dir = sortConfig.direction === 'asc' ? 1 : -1;
    if (k === 'ev_per_unit' || k === 'confidence_0_100') {
      const av = Number(a?.[k] ?? -Infinity);
      const bv = Number(b?.[k] ?? -Infinity);
      return (av - bv) * dir;
    }
    if (k === 'matchup') {
      const am = formatMatchup(a) || a?.matchup || '';
      const bm = formatMatchup(b) || b?.matchup || '';
      return am.localeCompare(bm) * dir;
    }
    const aVal = String(a?.[k] ?? '');
    const bVal = String(b?.[k] ?? '');
    return aVal.localeCompare(bVal) * dir;
  }), [predictions, sortConfig]);

  // Record stats
  const recordStats = useMemo(() => {
    let wins = 0;
    let losses = 0;
    let pushes = 0;
    let pending = 0;
    let pastPending = 0;
    let netUnits = 0;

    predictions.forEach(p => {
      const rawOut = p.graded_result || p.outcome || p.result;
      const norm = normalizeOutcome(rawOut);
      if (isWinOutcome(rawOut)) {
        wins += 1;
        netUnits += roiPerUnit(rawOut, getEffectivePrice(p) ?? -110);
      } else if (isLossOutcome(rawOut)) {
        losses += 1;
        netUnits += roiPerUnit(rawOut, getEffectivePrice(p) ?? -110);
      } else if (norm === 'PUSH') {
        pushes += 1;
      } else if (!norm || norm === 'PENDING') {
        pending += 1;
        const day = p.day_et || (p.analyzed_at || '').slice(0, 10);
        if (day && day < todayEt) pastPending += 1;
      }
    });

    const decided = wins + losses;
    const settled = decided + pushes;
    const winRate = decided > 0 ? (wins / decided) * 100 : null;
    const roi = settled > 0 ? (netUnits / settled) * 100 : null;

    return { wins, losses, pushes, decided, settled, pending, pastPending, winRate, netUnits, roi, total: predictions.length };
  }, [predictions, todayEt]);

  // Market breakdown chart
  const marketChart = useMemo(() => {
    const grouped = {};
    predictions.forEach(p => {
      const mt = (p.market_type || 'OTHER').toUpperCase();
      if (!grouped[mt]) grouped[mt] = { market: mt, wins: 0, losses: 0, total: 0 };
      const rawOut = p.graded_result || p.outcome || p.result;
      grouped[mt].total += 1;
      if (isWinOutcome(rawOut)) grouped[mt].wins += 1;
      else if (isLossOutcome(rawOut)) grouped[mt].losses += 1;
    });
    return Object.values(grouped).map(g => ({
      ...g,
      winRate: (g.wins + g.losses) > 0 ? Number(((g.wins / (g.wins + g.losses)) * 100).toFixed(1)) : null,
    })).filter(g => g.total > 0);
  }, [predictions]);

  const SortIcon = ({ col }) => {
    if (sortConfig.key !== col) return <ArrowUpDown size={11} className="ml-1 opacity-25" />;
    return sortConfig.direction === 'asc' ? <ChevronUp size={11} className="ml-1 text-blue-400" /> : <ChevronDown size={11} className="ml-1 text-blue-400" />;
  };
  const handleSort = (key) => setSortConfig(prev => ({
    key,
    direction: prev.key === key && prev.direction === 'desc' ? 'asc' : 'desc',
  }));

  const tabItems = [
    { id: 'today', label: "Today's Slate" },
    { id: 'picks', label: `Today's Picks (${todayPreds.length})` },
    { id: 'history', label: `Pick History (${predictions.length.toLocaleString()})` },
  ];

  return (
    <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
      {/* Header */}
      <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
        <div className="flex items-center gap-3">
          <span className="text-3xl" aria-hidden="true">⚾</span>
          <div>
            <h1 className="text-2xl font-black text-white">MLB Model</h1>
            <div className="text-sm text-slate-400">
              {slate?.date || todayEt} · {totalGames} games scheduled · {gamesWithOdds} with live odds
            </div>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2.5">
          <label className="text-xs text-slate-400 flex items-center gap-1.5 bg-slate-900/60 border border-slate-800 rounded-xl px-3 py-2">
            <span>Window</span>
            <select
              value={lookbackDays}
              onChange={(e) => setLookbackDays(Number(e.target.value))}
              aria-label="MLB history lookback window"
              className="bg-transparent text-slate-100 font-semibold focus:outline-none cursor-pointer"
            >
              <option value={60} className="bg-slate-900">Last 60 days</option>
              <option value={180} className="bg-slate-900">Last 180 days</option>
              <option value={400} className="bg-slate-900">Full season (400d)</option>
            </select>
          </label>
          <button
            type="button"
            onClick={() => load()}
            disabled={loading}
            className="px-4 py-2 rounded-xl bg-slate-800/60 hover:bg-slate-700/60 border border-slate-700/40 text-slate-200 text-sm font-semibold transition flex items-center gap-2"
          >
            <RefreshCw size={15} className={loading ? 'animate-spin' : ''} />
            Refresh
          </button>
          <button
            type="button"
            onClick={gradeResults}
            disabled={isGrading || loading}
            className={`px-4 py-2 rounded-xl text-sm font-semibold transition flex items-center gap-2 ${
              isGrading 
                ? 'bg-slate-800 text-slate-500 border border-slate-700/40' 
                : 'bg-blue-600/20 hover:bg-blue-600/30 border border-blue-600/30 text-blue-300'
            }`}
          >
            <CheckCircle size={15} className={isGrading ? 'animate-pulse' : ''} />
            {isGrading ? 'Grading Past Picks…' : 'Grade Past Picks'}
          </button>
          <button
            type="button"
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
        <div role="alert" className="p-3 rounded-lg bg-red-900/20 border border-red-800/40 text-red-300 text-sm">{err}</div>
      )}

      {gradeStatus && (
        <div role="status" className="p-3 rounded-lg bg-emerald-900/20 border border-emerald-800/40 text-emerald-200 text-sm">{gradeStatus}</div>
      )}

      {recordStats.pastPending > 0 && !isGrading && (
        <div className="p-3 rounded-xl bg-amber-900/20 border border-amber-700/40 text-amber-200 text-xs flex flex-wrap items-center justify-between gap-2">
          <span>{recordStats.pastPending.toLocaleString()} past MLB pick(s) from previous days are still marked Pending. Click Grade Past Picks to settle final scores.</span>
          <button
            type="button"
            onClick={gradeResults}
            className="px-3 py-1 rounded-lg bg-amber-500/20 hover:bg-amber-500/30 border border-amber-500/40 text-amber-100 font-semibold transition"
          >
            Settle Now
          </button>
        </div>
      )}

      {/* Record tiles */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <StatTile
          label="Graded Record"
          value={recordStats.settled > 0 ? `${recordStats.wins}-${recordStats.losses}${recordStats.pushes ? `-${recordStats.pushes}` : ''}` : '—'}
          sub={`${recordStats.total.toLocaleString()} picks · ${recordStats.pending} pending`}
          accent="text-white"
        />
        <StatTile
          label="Win Rate"
          value={recordStats.winRate !== null ? `${recordStats.winRate.toFixed(1)}%` : '—'}
          sub="settled bets (excl. pushes)"
          accent={
            recordStats.winRate !== null
              ? ((recordStats.roi > 0 || recordStats.winRate >= 52.4)
                  ? 'text-emerald-400'
                  : recordStats.winRate >= 50.0
                    ? 'text-amber-300'
                    : 'text-red-400')
              : 'text-slate-400'
          }
        />
        <StatTile
          label="Profit (Units)"
          value={recordStats.settled > 0 ? (recordStats.netUnits > 0 ? `+${recordStats.netUnits.toFixed(2)}u` : `${recordStats.netUnits.toFixed(2)}u`) : '—'}
          sub={`${recordStats.settled.toLocaleString()} settled picks`}
          accent={recordStats.netUnits > 0 ? 'text-emerald-400' : recordStats.netUnits < 0 ? 'text-red-400' : 'text-slate-400'}
        />
        <StatTile
          label="Return (ROI)"
          value={recordStats.roi !== null ? `${recordStats.roi > 0 ? '+' : ''}${recordStats.roi.toFixed(1)}%` : '—'}
          sub="average return per bet"
          accent={recordStats.roi > 0 ? 'text-emerald-400' : recordStats.roi < 0 ? 'text-red-400' : 'text-slate-400'}
        />
        <StatTile
          label="Today's Picks"
          value={todayPreds.length}
          sub={loading ? 'Loading…' : 'on today’s card'}
          accent={todayPreds.length > 0 ? 'text-emerald-400' : 'text-slate-400'}
        />
      </div>

      {/* Market breakdown chart */}
      {marketChart.length > 0 && (
        <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-5">
          <h2 className="text-sm font-black text-slate-100 uppercase tracking-wider mb-4 flex items-center gap-2">
            <BarChart3 size={16} className="text-blue-400" />
            Win Rate by Bet Type
          </h2>
          <div className="h-[180px]" role="img" aria-label="MLB win rate by bet type bar chart">
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
      <div role="tablist" aria-label="MLB views" className="inline-flex gap-1 p-1 rounded-xl bg-slate-900/40 border border-slate-700/40">
        {tabItems.map(t => (
          <button
            key={t.id}
            type="button"
            role="tab"
            id={`mlb-tab-${t.id}`}
            aria-selected={activeTab === t.id}
            aria-controls={`mlb-panel-${t.id}`}
            onClick={() => setActiveTab(t.id)}
            className={`px-4 py-2 rounded-lg text-sm font-semibold transition border-b-2 ${
              activeTab === t.id
                ? 'bg-slate-800/80 text-slate-100 border-sky-400 shadow-sm'
                : 'text-slate-400 border-transparent hover:text-slate-200 hover:bg-slate-800/40'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab: Today's Slate */}
      {activeTab === 'today' && (
        <div role="tabpanel" id="mlb-panel-today" aria-labelledby="mlb-tab-today">
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
        <div role="tabpanel" id="mlb-panel-picks" aria-labelledby="mlb-tab-picks">
          {todayPreds.length === 0 ? (
            <div className="bg-slate-900/40 border border-slate-800 rounded-xl p-8 text-center">
              <div className="text-slate-400 mb-2">No picks generated yet for today.</div>
              <div className="text-slate-500 text-sm">Click <span className="text-emerald-400 font-bold">Run Model Now</span> to analyze today's slate.</div>
            </div>
          ) : (
            <div className="space-y-3">
              {todayPreds.slice().sort((a, b) => Number(b.ev_per_unit || 0) - Number(a.ev_per_unit || 0)).map((pred, i) => {
                const market = (pred.market_type || '').toUpperCase();
                const ev = Number(pred.ev_per_unit || 0);
                const confLabel = getConfidenceBucket(pred.confidence_0_100).toUpperCase();
                let inputs = {}; try { inputs = JSON.parse(pred.inputs_json || '{}'); } catch (e) {}
                let narrative = {}; try { narrative = JSON.parse(pred.narrative_json || '{}'); } catch (e) {}
                return (
                  <article key={i} className="bg-slate-900/60 border border-slate-800 hover:border-slate-700 rounded-xl p-4 transition-all">
                    <div className="flex flex-col md:flex-row md:items-start gap-3">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1 flex-wrap">
                          <span className={`text-[10px] font-black px-2 py-0.5 rounded-full ${MARKET_COLOR[market] || 'bg-slate-800 text-slate-400'}`}>{market}</span>
                          <span className={`text-[10px] font-black ${CONFIDENCE_COLOR[confLabel]}`}>{confLabel} CONFIDENCE</span>
                          <span className="text-emerald-400 text-[10px] font-mono font-black">Edge {(ev * 100).toFixed(1)}%</span>
                        </div>
                        <div className="text-white font-black text-base">{pred.selection || '—'}</div>
                        <div className="text-slate-400 text-xs mt-0.5">
                          {formatMatchup(pred) || pred.matchup || (pred.away_team && pred.home_team ? `${pred.away_team} @ ${pred.home_team}` : '—')}
                        </div>
                        {(narrative?.pitching_matchup?.away || narrative?.pitching_matchup?.home) && (
                          <div className="text-slate-500 text-[10px] mt-1">
                            ⚾ {narrative.pitching_matchup.away || '?'} vs {narrative.pitching_matchup.home || '?'}
                          </div>
                        )}
                      </div>
                      <div className="shrink-0 text-right">
                        <div className="text-slate-500 text-[10px]">Projected Total</div>
                        <div className="text-slate-200 font-bold text-sm">{inputs.proj_total ? fmtRun(inputs.proj_total) : '—'}</div>
                        <div className="text-slate-600 text-[10px] mt-1">Market {inputs.market_total || '—'}</div>
                      </div>
                    </div>
                    {inputs.weather && inputs.weather !== 'Indoor/retractable roof — weather neutralized' && (
                      <div className="mt-2 text-[10px] text-slate-400 bg-slate-800/30 rounded-lg px-3 py-1.5">
                        🌤 {inputs.weather}
                      </div>
                    )}
                  </article>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* Tab: Pick History */}
      {activeTab === 'history' && (
        <div role="tabpanel" id="mlb-panel-history" aria-labelledby="mlb-tab-history" className="bg-slate-900/60 border border-slate-800 rounded-xl overflow-hidden">
          <div className="px-5 py-4 border-b border-slate-800 flex items-center justify-between gap-2">
            <h2 id="mlb-history-title" className="text-sm font-black text-slate-100 uppercase tracking-wider">MLB Pick History</h2>
            <div className="text-[11px] text-slate-400 tabular-nums">{predictions.length.toLocaleString()} predictions</div>
          </div>
          {predictions.length === 0 ? (
            <div className="p-8 text-center text-slate-500 text-sm">No MLB prediction history in this lookback window yet. Try switching to Full season (400d) or running the model.</div>
          ) : (
            <div className="overflow-x-auto" role="region" aria-labelledby="mlb-history-title" tabIndex={0}>
              <table className="w-full text-left border-collapse">
                <caption className="sr-only">MLB pick history showing date, matchup, market, pick, expected edge, confidence level, result, unit profit, and weather context</caption>
                <thead>
                  <tr className="border-b border-slate-700/60 bg-slate-800/30">
                    {[
                      { key: 'analyzed_at', label: 'Date' },
                      { key: 'matchup', label: 'Matchup' },
                      { key: 'market_type', label: 'Bet Type' },
                      { key: 'selection', label: 'Pick' },
                      { key: 'ev_per_unit', label: 'Expected Edge' },
                      { key: 'confidence_0_100', label: 'Confidence' },
                      { key: 'graded_result', label: 'Result' },
                      { key: null, label: 'Profit' },
                      { key: null, label: 'Context' },
                    ].map((col, i) => {
                      const isSorted = col.key && sortConfig.key === col.key;
                      return (
                        <th
                          key={i}
                          scope="col"
                          aria-sort={isSorted ? (sortConfig.direction === 'asc' ? 'ascending' : 'descending') : undefined}
                          className="py-2 px-2.5 sm:px-3 text-[10px] uppercase tracking-wider text-slate-400 font-black whitespace-nowrap"
                        >
                          {col.key ? (
                            <button
                              type="button"
                              onClick={() => handleSort(col.key)}
                              className="flex items-center hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-400 rounded py-1"
                            >
                              {col.label}
                              <SortIcon col={col.key} />
                            </button>
                          ) : (
                            <span>{col.label}</span>
                          )}
                        </th>
                      );
                    })}
                  </tr>
                </thead>
                <tbody>
                  {historyPreds.map((p, i) => <PredictionRow key={p.id || p.event_id || i} pred={p} />)}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
