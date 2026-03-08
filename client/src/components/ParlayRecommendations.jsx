import React, { useEffect, useState } from 'react';
import api from '../api/axios';
import { Zap, Target, Home, TrendingUp, Percent, RefreshCw } from 'lucide-react';

const fmtPct = (x) => {
  const n = Number(x);
  if (!Number.isFinite(n)) return '—';
  return `${(n * 100).toFixed(1)}%`;
};

const fmtOdds = (a) => {
  const n = Number(a);
  if (!Number.isFinite(n) || n === 0) return '—';
  return n > 0 ? `+${n}` : `${n}`;
};

const fmtTime = (ts) => {
  if (!ts) return '';
  try {
    return new Date(ts).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', timeZone: 'America/New_York' });
  } catch { return ''; }
};

const ACCENT = {
  amber: { text: 'text-amber-400', bg: 'bg-amber-500/10', border: 'border-amber-500/20', head: 'border-amber-500/30 text-amber-300' },
  purple: { text: 'text-purple-400', bg: 'bg-purple-500/10', border: 'border-purple-500/20', head: 'border-purple-500/30 text-purple-300' },
  orange: { text: 'text-orange-400', bg: 'bg-orange-500/10', border: 'border-orange-500/20', head: 'border-orange-500/30 text-orange-300' },
};

function ComboCard({ c, color = 'amber' }) {
  const legs = c?.legs || [];
  const ac = ACCENT[color] || ACCENT.amber;

  const out = c?.outcome;
  const isWon = out === 'WON' || out === 'WON (partial)';
  const isLoss = out === 'LOST';
  const isPush = out === 'PUSH';

  let borderCls = 'border-slate-700/60';
  if (isWon) borderCls = 'border-green-500/50 bg-green-950/20';
  else if (isLoss) borderCls = 'border-red-500/50 bg-red-950/20';
  else if (isPush) borderCls = 'border-slate-500/50 bg-slate-900/40';

  return (
    <div className={`relative overflow-hidden p-4 rounded-xl border bg-gradient-to-br from-slate-900 to-slate-950 shadow-lg flex flex-col gap-3 transition hover:border-slate-500/50 ${borderCls}`}>
      {/* Header row */}
      <div className="flex items-center justify-between border-b border-slate-800/60 pb-3">
        <div className="flex items-baseline gap-2">
          <span className="text-2xl font-black text-white">{fmtOdds(c?.american_odds)}</span>
          <span className="text-xs font-bold text-slate-500">Parlay Odds</span>
        </div>
        <div className="flex items-center gap-2">
          {out && out !== 'PENDING' && (
            <div className={`flex items-center gap-1 px-2 py-1 rounded-md border font-black text-[10px] uppercase tracking-wider ${isWon ? 'text-green-300 border-green-500/30 bg-green-500/10' : isLoss ? 'text-red-300 border-red-500/30 bg-red-500/10' : 'text-slate-300 border-slate-500/30 bg-slate-500/10'}`}>
              {out}
            </div>
          )}
          <div className={`flex items-center gap-1 px-2 py-1 rounded-md border ${ac.bg} ${ac.border}`}>
            <TrendingUp size={13} className={ac.text} />
            <span className={`text-xs font-bold ${ac.text}`}>+{fmtPct(c?.ev)} EV</span>
          </div>
          <div className="flex items-center gap-1 bg-blue-500/10 px-2 py-1 rounded-md border border-blue-500/20 hidden sm:flex">
            <Percent size={13} className="text-blue-400" />
            <span className="text-xs font-bold text-blue-400">{fmtPct(c?.p_win)} Win</span>
          </div>
        </div>
      </div>

      {/* Legs */}
      <div className="flex flex-col gap-3">
        {legs.map((leg, li) => {
          const lOut = leg.outcome ? String(leg.outcome).toUpperCase() : 'PENDING';
          const lWon = lOut === 'WON';
          const lLoss = lOut === 'LOST';

          return (
            <div key={li} className="flex items-start justify-between gap-3">
              <div className="flex flex-col min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-[10px] text-slate-500 font-bold uppercase">{fmtTime(leg.start_time)}</span>
                  <span className="text-xs text-slate-400 font-medium">{leg.matchup}</span>
                  {color === 'orange' && leg.is_home_pick && (
                    <span className="text-[9px] font-bold text-orange-400 bg-orange-400/10 border border-orange-400/20 px-1.5 py-0.5 rounded-full uppercase tracking-wider">Home Fav</span>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <span className={`text-sm font-bold leading-tight ${lWon ? 'text-green-300' : lLoss ? 'text-red-300' : 'text-slate-200'}`}>{leg.team_pick}</span>
                </div>
              </div>
              <span className="text-sm font-mono font-bold text-slate-500 shrink-0">{fmtOdds(leg.price)}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ParlayColumn({ title, icon: Icon, color, combos, loading }) {
  const ac = ACCENT[color] || ACCENT.amber;
  return (
    <div className="flex flex-col gap-3">
      {/* Column header */}
      <div className={`flex items-center gap-2 px-1 pb-2 border-b ${ac.head}`}>
        <Icon size={14} className={ac.text} />
        <span className={`text-xs font-black uppercase tracking-wider ${ac.text}`}>{title}</span>
      </div>
      {/* Cards */}
      {loading ? (
        <div className="text-xs text-slate-500 p-4 text-center">Loading…</div>
      ) : combos.length === 0 ? (
        <div className="text-xs text-slate-500 bg-slate-950/50 rounded-xl p-4 text-center border border-slate-800/50 font-medium">
          No combos
        </div>
      ) : (
        combos.map((c, i) => <ComboCard key={i} c={c} color={color} />)
      )}
    </div>
  );
}

export default function ParlayRecommendations() {
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(null);
  const [allData, setAllData] = useState(null);
  const [homeFavData, setHomeFavData] = useState(null);

  const [ydAllData, setYdAllData] = useState(null);
  const [ydHomeFavData, setYdHomeFavData] = useState(null);

  const load = async () => {
    setLoading(true);
    setErr(null);
    try {
      const [main, homeFav, yMain, yHomeFav] = await Promise.all([
        api.get('/api/ncaam/parlays/today', { params: { min_ev_per_unit: 0.02, parlay_odds_lo: -120, parlay_odds_hi: 300 } }),
        api.get('/api/ncaam/parlays/today', { params: { strategy: 'home_fav', parlay_odds_lo: -200, parlay_odds_hi: 120, min_ev_per_unit: -0.2 } }).catch(() => ({ data: null })),
        api.get('/api/ncaam/parlays/today', { params: { days_ago: 1, min_ev_per_unit: 0.02, parlay_odds_lo: -120, parlay_odds_hi: 300 } }).catch(() => ({ data: null })),
        api.get('/api/ncaam/parlays/today', { params: { days_ago: 1, strategy: 'home_fav', parlay_odds_lo: -200, parlay_odds_hi: 120, min_ev_per_unit: -0.2 } }).catch(() => ({ data: null })),
      ]);
      setAllData(main.data);
      setHomeFavData(homeFav.data);
      setYdAllData(yMain?.data);
      setYdHomeFavData(yHomeFav?.data);
    } catch (e) {
      setErr(e?.response?.data?.detail || e?.message || 'Failed to load parlays');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const highConf = (allData?.high_confidence || []).slice(0, 2);
  const valuePick = (allData?.payout_band || []).slice(0, 2);
  const homeFav = (homeFavData?.high_confidence || []).slice(0, 2);

  const yHighConf = (ydAllData?.high_confidence || []).slice(0, 2);
  const yValuePick = (ydAllData?.payout_band || []).slice(0, 2);
  const yHomeFav = (ydHomeFavData?.high_confidence || []).slice(0, 2);

  return (
    <div className="mb-6 space-y-10">

      {/* TODAY section */}
      <div>
        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <div>
            <div className="text-sm font-black text-slate-100 uppercase tracking-wider">Today's 2-Leg ML Parlays</div>
            <div className="text-[11px] text-slate-500">Model-sourced combinations</div>
          </div>
          <button
            onClick={load}
            disabled={loading}
            className="flex items-center gap-2 text-xs font-semibold px-3 py-1.5 rounded-lg border border-slate-700 text-slate-200 bg-slate-800/40 hover:bg-slate-700/60 disabled:opacity-50 transition"
          >
            <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
            {loading ? 'Loading…' : 'Refresh'}
          </button>
        </div>

        {err && <div className="text-xs text-red-400 bg-red-900/20 border border-red-900/50 p-3 rounded-xl mb-3">{err}</div>}

        {/* 3-column layout */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
          <ParlayColumn
            title="Highest Confidence"
            icon={Zap}
            color="amber"
            combos={highConf}
            loading={loading}
          />
          <ParlayColumn
            title="Value Matchups"
            icon={Target}
            color="purple"
            combos={valuePick}
            loading={loading}
          />
          <ParlayColumn
            title="Home Favorites"
            icon={Home}
            color="orange"
            combos={homeFav}
            loading={loading}
          />
        </div>
      </div>



    </div>
  );
}
