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
      ? `${slate.provisional.length} provisional pick${slate.provisional.length === 1 ? '' : 's'} (lock 30m before tip)`
      : hasLockedPicks
        ? `${slate.picks.length} locked · Monitoring remaining pre-cutoff games`
        : "0 Recommended Bets Right Now · Monitoring line movement until 30m before tip",
    locked: `Locked at ${time}`,
    stale_odds: "Held — odds or model cache stale (>90m old), awaiting refresh (not a true no-bet)",
    no_eligible_picks: `Completed${time ? ` at ${time}` : ''} · True No-Bet (all fresh lines evaluated, zero eligible edges)`,
    unpublished: day < getTodayEtStr() ? 'No recorded publication' : 'Awaiting publication',
    locking: 'Locking recommendations',
    unconfirmed: 'Publication unconfirmed',
    unavailable: 'Publication status unavailable',
  };
  const isStale =
    slate?.status === 'stale_odds' ||
    Boolean(slate?.evaluation?.is_odds_feed_stale) ||
    Object.keys(slate?.stale_holds || {}).length > 0;
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
      <strong>NCAAM Top 6</strong> · {labels[slate?.status] || 'Checking publication'}
      {slate?.evaluation && (
        <p className="mt-1 text-xs text-slate-400">
          {linedEvaluated > 0
            ? `${linedEvaluated} lined games evaluated (${slate.evaluation.actionable_games} actionable · ${slate.evaluation.true_no_bet_games} true no-bet)`
            : `${slate.evaluation.cached_games} cached game records · ${slate.evaluation.actionable_games} actionable`}
          {unlinedGames > 0 && ` · ${unlinedGames} unlined (non-D1 / no book odds)`}
          {(staleGames > 0 || isStale) && (
            <span className="text-amber-300 font-semibold">
              {staleGames > 0 ? ` · ${staleGames} held on stale odds (>90m)` : ' · Odds feed >90m old'}
            </span>
          )}
          {slate.evaluation.latest_computed_at && ` · Latest cache ${fmtTimeEt(slate.evaluation.latest_computed_at)} ET`}
          {slate.evaluation.latest_odds_at && ` · Latest odds ${fmtTimeEt(slate.evaluation.latest_odds_at)} ET`}
        </p>
      )}
      {slate?.status === 'rolling' && slate.provisional?.map(p => (
        <p key={p.event_id}>Provisional · {p.away_team} @ {p.home_team} · {p.selection} ({fmtOdds(p.bet_price)})
          {' · Locks '}{fmtTimeEt(p.locks_at)} ET · Crew {p.referees?.officials?.join(', ') || 'unconfirmed'}</p>
      ))}
      {Object.entries(slate?.stale_holds || {}).map(([event, reason]) => (
        <p key={event} className="text-amber-300 text-xs mt-1">Stale Hold · {reason}</p>
      ))}
      {Object.entries(slate?.passes || {}).map(([event, reason]) => <p key={event}>Pass · {event} · {reason}</p>)}
      {slate?.picks?.length > 0 && (
        <ol className="mt-2 list-decimal pl-5">
          {slate.picks.map(p => (
            <li key={p.rank} value={p.rank}>{p.away_team} @ {p.home_team} · {p.selection}
              {p.bet_line != null && !String(p.selection).includes(String(p.bet_line)) ? ` · Line ${p.bet_line}` : ''}
              {p.bet_price != null ? ` (${fmtOdds(p.bet_price)})` : ''}
              {p.locked_at && ` · Locked ${fmtTimeEt(p.locked_at)} ET · Crew ${p.referees?.officials?.join(', ') || 'unconfirmed'}`}
              {p.computed_at && ` · Model ${fmtTimeEt(p.computed_at)} ET · Quote ${fmtTimeEt(p.quote_captured_at)} ET`}</li>
          ))}
        </ol>
      )}
    </div>
  );
}
