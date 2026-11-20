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
  const labels = {
    rolling: "Provisional picks update until 30 minutes before each tip",
    locked: `Locked at ${time}`,
    no_eligible_picks: `Completed at ${time} · No eligible picks`,
    unpublished: day < getTodayEtStr() ? 'No recorded publication' : 'Awaiting publication',
    locking: 'Locking recommendations',
    unconfirmed: 'Publication unconfirmed',
    unavailable: 'Publication status unavailable',
  };
  return (
    <div className="rounded-xl border border-slate-700 bg-slate-900 p-3 text-sm text-slate-200" aria-live="polite">
      <strong>NCAAM Top 6</strong> · {labels[slate?.status] || 'Checking publication'}
      {slate?.evaluation && (
        <p className="mt-1 text-xs text-slate-400">
          {slate.evaluation.cached_games} cached game records · {slate.evaluation.actionable_games} actionable
          {slate.evaluation.latest_computed_at && ` · Latest cache update ${fmtTimeEt(slate.evaluation.latest_computed_at)} ET`}
        </p>
      )}
      {slate?.status === 'rolling' && slate.provisional?.map(p => (
        <p key={p.event_id}>Provisional · {p.away_team} @ {p.home_team} · {p.selection} ({fmtOdds(p.bet_price)})
          {' · Locks '}{fmtTimeEt(p.locks_at)} ET · Crew {p.referees?.officials?.join(', ') || 'unconfirmed'}</p>
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
