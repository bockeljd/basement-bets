import React, { useEffect, useState } from 'react';
import api from '../../api/axios';
import { fmtOdds, fmtTimeEt, getTodayEtStr } from './todayHelpers';

export default function SlatePublication({ day }) {
  const [result, setResult] = useState(null);
  useEffect(() => {
    let active = true;
    let timer;
    async function refresh() {
      let finished = false;
      try {
        const { data } = await api.get('/api/ncaam/publication-status', { params: { date: day } });
        if (active) setResult(data);
        finished = ['locked', 'no_eligible_picks'].includes(data.status);
      } catch {
        if (active) setResult({ day, status: 'unavailable' });
      }
      if (active && !finished && day === getTodayEtStr()) timer = setTimeout(refresh, 30000);
    }
    refresh();
    return () => { active = false; clearTimeout(timer); };
  }, [day]);

  const slate = result?.day === day ? result : null;
  const time = slate?.locked_at ? fmtTimeEt(slate.locked_at) + ' ET' : '';
  const hasProvisional = (slate?.provisional?.length || 0) > 0;
  const hasLockedPicks = (slate?.picks?.length || 0) > 0;
  const labels = {
    rolling: hasProvisional
      ? `${slate.provisional.length} pick${slate.provisional.length === 1 ? '' : 's'} ready (lock 30–40 min before tip)`
      : hasLockedPicks
        ? `${slate.picks.length} locked · Watching remaining games`
        : "0 Recommended Bets Right Now · Checking live odds until 30 min before each tip",
    locked: `Locked at ${time}`,
    stale_odds: "Paused — odds are older than 90 min, refreshing before lock",
    no_eligible_picks: `Done${time ? ` at ${time}` : ''} · No bets qualified today (all games checked)`,
    unpublished: day < getTodayEtStr() ? 'No picks recorded for this day' : 'Waiting for today’s first check',
    locking: 'Locking picks',
    unconfirmed: 'Status not confirmed yet',
    unavailable: 'Status unavailable',
  };
  const isStale = Boolean(slate?.evaluation?.is_odds_feed_stale);
  const linedEvaluated =
    Number(slate?.evaluation?.actionable_games || 0) + Number(slate?.evaluation?.true_no_bet_games || 0);
  const unlinedGames = Number(slate?.evaluation?.unlined_games ?? slate?.evaluation?.stale_or_missing_odds_games ?? 0);
  const staleGames = Number(slate?.evaluation?.stale_odds_games || 0);
  return (
    <div
      className={`rounded-xl border p-3 text-sm text-slate-200 ${
        isStale ? 'border-amber-500/45 bg-amber-950/20' : 'border-slate-700 bg-slate-900'
      }`}
      aria-live="polite"
    >
      <strong>NCAAM Top 6</strong> · {labels[slate?.status] || 'Checking today’s games'}
      {slate?.evaluation && (
        <p className="mt-1 text-xs text-slate-400">
          {linedEvaluated > 0
            ? `${linedEvaluated} model records evaluated (${slate.evaluation.actionable_games} bets · ${slate.evaluation.true_no_bet_games} passed)`
            : `${slate.evaluation.cached_games} cached model records · ${slate.evaluation.actionable_games} bets`}
          {unlinedGames > 0 && ` · ${unlinedGames} without sportsbook odds`}
          {staleGames > 0 && (
            <span className="text-amber-300 font-semibold">
              { ` · ${staleGames} stale at evaluation` }
            </span>
          )}
          {isStale && <span> · No recent sportsbook prices for upcoming games</span>}
          {slate.evaluation.latest_computed_at && ` · Model ${fmtTimeEt(slate.evaluation.latest_computed_at)} ET`}
          {slate.evaluation.latest_odds_at && ` · Odds ${fmtTimeEt(slate.evaluation.latest_odds_at)} ET`}
        </p>
      )}
      {Object.entries(slate?.stale_holds || {}).map(([event, reason]) => (
        <p key={event} className="text-amber-300 text-xs mt-1">Held at last publication · {reason}</p>
      ))}
      {Object.entries(slate?.passes || {}).map(([event, reason]) => (
        <p key={event} className="text-xs text-slate-400 mt-1">Skipped · {reason}</p>
      ))}
      {slate?.picks?.length > 0 && (
        <ol className="mt-2 list-decimal pl-5 space-y-0.5 text-xs text-slate-300">
          {slate.picks.map(p => (
            <li key={p.rank} value={p.rank}>{p.away_team} @ {p.home_team} · {p.selection}
              {p.bet_line != null && !String(p.selection).includes(String(p.bet_line)) ? ` · Line ${p.bet_line}` : ''}
              {p.bet_price != null ? ` (${fmtOdds(p.bet_price)})` : ''}
              {p.locked_at && ` · Locked ${fmtTimeEt(p.locked_at)} ET`}
              {p.referees?.officials?.length > 0 && ` · Refs ${p.referees.officials.join(', ')}`}</li>
          ))}
        </ol>
      )}
    </div>
  );
}
