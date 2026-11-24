import React, { useEffect, useState } from 'react';
import api from '../api/axios';
import { Zap, Target, Home, TrendingUp, Percent, RefreshCw, PlusCircle, Lock, Clock } from 'lucide-react';
import { getRecommendedBetSize, getOutcomeOutlineClasses } from './today/todayHelpers';

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

function ComboCard({ c, color = 'amber', bankroll = null, onAddBet = null }) {
  const legs = c?.legs || [];
  const ac = ACCENT[color] || ACCENT.amber;
  const sizeInfo = getRecommendedBetSize(
    {
      suggested_units: c?.suggested_units ?? 0.5,
      bankroll_pct: c?.bankroll_pct ?? c?.suggested_units ?? 0.5,
      sizing_tier: c?.sizing_tier,
      kelly: c?.kelly,
      ev: c?.ev,
      confidence_tier: Number(c?.ev) >= 0.08 ? 'MEDIUM' : 'LOW',
    },
    bankroll
  );

  const out = c?.outcome;
  const surface = getOutcomeOutlineClasses(out, 'bet');

  return (
    <div className={`relative overflow-hidden p-4 rounded-xl shadow-lg flex flex-col gap-3 transition-colors ${surface.cardCls}`}>
      {/* Header row */}
      <div className="flex items-center justify-between border-b border-slate-800/60 pb-3">
        <div className="flex items-baseline gap-2">
          <span className="text-2xl font-black text-white">{fmtOdds(c?.american_odds)}</span>
          <span className="text-xs font-bold text-slate-500">Parlay Odds</span>
        </div>
        <div className="flex items-center gap-2">
          {out && out !== 'PENDING' && (
            <div className={`flex items-center gap-1 px-2 py-1 rounded-md border font-black text-[10px] uppercase tracking-wider ${surface.badgeCls}`}>
              {out}
            </div>
          )}
          <div className={`flex items-center gap-1 px-2 py-1 rounded-md border ${ac.bg} ${ac.border}`}>
            <TrendingUp size={13} className={ac.text} />
            <span className={`text-xs font-bold ${ac.text}`}>+{fmtPct(c?.ev)} Edge</span>
          </div>
          <div className="flex items-center gap-1 bg-blue-500/10 px-2 py-1 rounded-md border border-blue-500/20 hidden sm:flex">
            <Percent size={13} className="text-blue-400" />
            <span className="text-xs font-bold text-blue-400">{fmtPct(c?.p_win)} Win Chance</span>
          </div>
        </div>
      </div>

      {/* Legs */}
      <div className="flex flex-col gap-3">
        {legs.map((leg, li) => {
          const lOut = leg.outcome ? String(leg.outcome).toUpperCase() : 'PENDING';
          const legSurface = getOutcomeOutlineClasses(lOut, 'bet');
          const lWon = legSurface.outcome === 'WON';
          const lLoss = legSurface.outcome === 'LOST';

          return (
            <div
              key={li}
              className={`flex items-start justify-between gap-3 ${legSurface.outcome ? `${legSurface.stripeCls} pl-2` : ''}`}
            >
              <div className="flex flex-col min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-[10px] text-slate-500 font-bold uppercase">{fmtTime(leg.start_time)}</span>
                  <span className="text-xs text-slate-400 font-medium">{leg.matchup}</span>
                  {leg.home_spread != null && (
                    <span className="text-[9px] font-mono font-bold text-sky-300 bg-sky-500/10 border border-sky-400/25 px-1.5 py-0.5 rounded-full">
                      Home Spread {Number(leg.home_spread) > 0 ? `+${Number(leg.home_spread).toFixed(1)}` : Number(leg.home_spread).toFixed(1)}
                    </span>
                  )}
                  {(leg.is_sweet_spot_7pt || (color === 'orange' && leg.is_home_pick)) && (
                    <span className="text-[9px] font-bold text-orange-300 bg-orange-400/10 border border-orange-400/25 px-1.5 py-0.5 rounded-full uppercase tracking-wider">
                      {leg.is_sweet_spot_7pt ? 'Sweet-Spot ~7pt Home Fav' : 'Home Favorite'}
                    </span>
                  )}
                  {(leg.is_smart_risk || String(leg.risk_tier || '').toUpperCase() === 'SMART_RISK') && (
                    <span className="text-[9px] font-bold text-indigo-200 bg-indigo-500/15 border border-indigo-400/35 px-1.5 py-0.5 rounded-full uppercase tracking-wider">
                      Smart Risk
                    </span>
                  )}
                  {leg.is_value_underdog && (
                    <span className="text-[9px] font-bold text-emerald-200 bg-emerald-500/15 border border-emerald-400/35 px-1.5 py-0.5 rounded-full uppercase tracking-wider">
                      Value Dog
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <span className={`text-sm font-bold leading-tight ${lWon ? 'text-emerald-300' : lLoss ? 'text-rose-300' : 'text-slate-200'}`}>{leg.team_pick}</span>
                </div>
              </div>
              <div className="flex items-center gap-1.5 shrink-0">
                {legSurface.outcome && (
                  <span className={`px-1.5 py-0.5 rounded border text-[9px] font-black uppercase tracking-wider ${legSurface.badgeCls}`}>
                    {legSurface.outcome}
                  </span>
                )}
                <span className="text-sm font-mono font-bold text-slate-400">{fmtOdds(leg.price)}</span>
              </div>
            </div>
          );
        })}
      </div>

      {/* Bet sizing & Add Bet footer */}
      <div className="flex flex-wrap items-center justify-between gap-2 pt-2.5 border-t border-slate-800/70">
        {sizeInfo ? (
          <div className="inline-flex items-center gap-1.5 text-xs text-indigo-200 font-medium">
            <span className="text-slate-400">Suggested Bet:</span>
            <span className="font-mono font-bold text-white">{sizeInfo.detailedLabel}</span>
          </div>
        ) : (
          <span />
        )}
        {onAddBet && legs.length >= 2 && (
          <button
            type="button"
            onClick={() =>
              onAddBet({
                sport: 'NCAAM',
                market: 'Parlay',
                game: legs.map((l) => l.matchup).filter(Boolean).join(' + '),
                pick: legs.map((l) => l.team_pick).filter(Boolean).join(' + '),
                odds: c?.american_odds,
                units: sizeInfo?.units,
                stake: sizeInfo?.dollarStake,
              })
            }
            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-emerald-600/20 hover:bg-emerald-600/35 border border-emerald-500/40 text-xs font-bold text-emerald-300 cursor-pointer transition"
          >
            <PlusCircle size={12} aria-hidden="true" />
            <span>Add Bet</span>
          </button>
        )}
      </div>
    </div>
  );
}

function ParlayColumn({ title, icon: Icon, color, combos, loading, bankroll = null, onAddBet = null }) {
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
          No matching parlays right now
        </div>
      ) : (
        combos.map((c, i) => <ComboCard key={i} c={c} color={color} bankroll={bankroll} onAddBet={onAddBet} />)
      )}
    </div>
  );
}

export default function ParlayRecommendations({ date, onSelectDate, bankroll = null, onAddBet = null }) {
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(null);
  const [allData, setAllData] = useState(null);
  const [homeFavData, setHomeFavData] = useState(null);

  const load = async () => {
    setLoading(true);
    setErr(null);
    try {
      const dateParams = date ? { date } : {};
      const [main, homeFav] = await Promise.all([
        api.get('/api/ncaam/parlays/today', {
          params: { ...dateParams, min_ev_per_unit: 0.02, parlay_odds_lo: -120, parlay_odds_hi: 500 },
        }),
        api.get('/api/ncaam/parlays/today', {
          params: { ...dateParams, strategy: 'home_fav', parlay_odds_lo: -165, parlay_odds_hi: 140 },
        }).catch(() => ({ data: null })),
      ]);
      setAllData(main.data);
      setHomeFavData(homeFav?.data || null);
    } catch (e) {
      setErr(e?.response?.data?.detail || e?.message || 'Failed to load parlays');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [date]);

  const officialParlay = allData?.official_daily_parlay || null;
  const highConf = (allData?.high_confidence || []).slice(0, 5);
  const valuePick = (allData?.payout_band || []).slice(0, 5);
  const threeLeg = (allData?.three_leg_high_payout || []).slice(0, 3);
  const homeFav = (homeFavData?.high_confidence || []).slice(0, 5);
  const legsConsidered = Number(allData?.legs_considered ?? 0);
  const hasAnyCombos =
    Boolean(officialParlay) ||
    highConf.length > 0 ||
    valuePick.length > 0 ||
    threeLeg.length > 0 ||
    homeFav.length > 0;
  const displayDate = allData?.date_et || date || '';

  return (
    <div className="mb-6 space-y-5">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-base font-bold text-slate-100">
            Recommended Parlays{displayDate ? ` (${displayDate})` : ''}
          </h3>
          <p className="text-xs text-slate-400">
            Combines our strongest DraftKings &amp; FanDuel picks — including home favorites around -4.5 to -9.5 on the moneyline so late fouls don’t ruin a spread cover.
          </p>
        </div>
        <button
          type="button"
          onClick={load}
          disabled={loading}
          className="flex items-center gap-2 text-xs font-semibold px-3 py-1.5 rounded-lg border border-slate-700 text-slate-200 bg-slate-800/40 hover:bg-slate-700/60 disabled:opacity-50 transition cursor-pointer"
        >
          <RefreshCw size={13} className={loading ? 'animate-spin' : ''} aria-hidden="true" />
          <span>{loading ? 'Loading…' : 'Refresh'}</span>
        </button>
      </div>

      {err && (
        <div className="text-xs text-red-400 bg-red-900/20 border border-red-900/50 p-3 rounded-xl">
          {err}
        </div>
      )}

      {!loading && !err && !hasAnyCombos ? (
        <div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-6 space-y-4">
          <div className="space-y-1">
            <h4 className="text-sm font-bold text-white">
              No Parlays Qualified for {displayDate || 'Today'}
            </h4>
            <p className="text-xs text-slate-300 leading-relaxed">
              {legsConsidered === 0
                ? 'No picks met our parlay rules today.'
                : `Only ${legsConsidered} pick qualified — at least 2 from separate games are needed to build a parlay.`}
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
            <div className="rounded-xl border border-slate-800/90 bg-slate-950/60 p-3.5 space-y-1">
              <div className="font-semibold text-indigo-300">Why we require strict Moneyline legs</div>
              <p className="text-slate-400 leading-relaxed">
                Each leg must have <strong className="text-slate-200">52%+ win probability</strong>,{' '}
                <strong className="text-slate-200">+5.0%+ profit edge</strong>, and odds between{' '}
                <strong className="text-slate-200">-250 and +105</strong> (longshot underdogs are filtered out).
              </p>
            </div>
            <div className="rounded-xl border border-slate-800/90 bg-slate-950/60 p-3.5 space-y-1">
              <div className="font-semibold text-emerald-300">~7-Point Home Favorite ML Parlays</div>
              <p className="text-slate-400 leading-relaxed">
                Non-neutral home favorites in the <strong className="text-slate-200">-4.5 to -9.5 spread band</strong> win outright at high rates even when late fouls spoil ATS covers. Qualifying pairs combine into <strong className="text-slate-200">-165 to +140</strong> parlays automatically.
              </p>
            </div>
          </div>

          {onSelectDate && displayDate && (
            <div className="pt-1 flex flex-wrap items-center gap-3 text-xs">
              <button
                type="button"
                onClick={() => {
                  const dt = new Date(`${displayDate}T12:00:00Z`);
                  dt.setUTCDate(dt.getUTCDate() - 1);
                  onSelectDate(dt.toISOString().slice(0, 10));
                }}
                className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 font-semibold text-indigo-200 cursor-pointer"
              >
                Check Previous Day&apos;s Parlays
              </button>
              <span className="text-slate-500">Use the date switcher above to inspect earlier days&apos; parlays.</span>
            </div>
          )}
        </div>
      ) : (
        <div className="space-y-5">
          {officialParlay && (() => {
            const officialSurface = getOutcomeOutlineClasses(officialParlay.outcome, 'bet');
            const officialSectionCls =
              officialSurface.outcome === 'LOST'
                ? 'border-rose-500/45 bg-rose-950/15'
                : officialSurface.outcome === 'PUSH'
                  ? 'border-slate-500/45 bg-slate-900/35'
                  : 'border-emerald-500/35 bg-emerald-950/15';
            return (
              <section className={`rounded-2xl border p-4 space-y-3 ${officialSectionCls}`}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span
                      className={`text-xs font-black uppercase tracking-wider ${
                        officialSurface.outcome === 'LOST'
                          ? 'text-rose-300'
                          : officialSurface.outcome === 'PUSH'
                            ? 'text-slate-300'
                            : 'text-emerald-300'
                      }`}
                    >
                      Official Daily Parlay
                    </span>
                    {officialParlay.is_locked ? (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-emerald-500/20 border border-emerald-400/40 text-emerald-200 text-[10px] font-bold">
                        <Lock size={10} aria-hidden="true" />
                        <span>
                          LOCKED{officialParlay.locked_at ? ` · ${fmtTime(officialParlay.locked_at)} ET` : ''}
                        </span>
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-amber-500/15 border border-amber-400/35 text-amber-200 text-[10px] font-bold">
                        <Clock size={10} aria-hidden="true" />
                        <span>
                          Locks 10m before tip{officialParlay.locks_at ? ` (${fmtTime(officialParlay.locks_at)} ET)` : ''}
                        </span>
                      </span>
                    )}
                  </div>
                  <span className="text-[11px] text-slate-400">
                    Pinned daily pick graded in Model Performance · All other qualifying parlays shown below
                  </span>
                </div>
                <ComboCard c={officialParlay} color="amber" bankroll={bankroll} onAddBet={onAddBet} />
              </section>
            );
          })()}

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
            <ParlayColumn
              title="Highest Win Chance"
              icon={Zap}
              color="amber"
              combos={highConf}
              loading={loading}
              bankroll={bankroll}
              onAddBet={onAddBet}
            />
            <ParlayColumn
              title="Best Payout Value"
              icon={Target}
              color="purple"
              combos={valuePick}
              loading={loading}
              bankroll={bankroll}
              onAddBet={onAddBet}
            />
            <ParlayColumn
              title="Home Favorites (~7pt ML)"
              icon={Home}
              color="orange"
              combos={homeFav}
              loading={loading}
              bankroll={bankroll}
              onAddBet={onAddBet}
            />
          </div>

          {threeLeg.length > 0 && (
            <section className="rounded-2xl border border-purple-500/30 bg-purple-950/10 p-4 space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <TrendingUp size={14} className="text-purple-300" aria-hidden="true" />
                  <span className="text-xs font-black uppercase tracking-wider text-purple-300">
                    3-Leg High-Payout Parlays (+300 to +1000)
                  </span>
                </div>
                <span className="text-[11px] text-slate-400">
                  Higher-upside 3-leg mixes from separate games · Sized smaller (0.25u–0.5u)
                </span>
              </div>
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                {threeLeg.map((c, i) => (
                  <ComboCard key={`3leg-${i}`} c={c} color="purple" bankroll={bankroll} onAddBet={onAddBet} />
                ))}
              </div>
            </section>
          )}
        </div>
      )}
    </div>
  );
}
