import React, { useEffect, useState } from 'react';
import { RefreshCw, Target } from 'lucide-react';
import api from '../api/axios';

const fmtOdds = (o) => {
  if (o === null || o === undefined || o === '') return '—';
  const n = Number(o);
  if (!Number.isFinite(n)) return '—';
  return n > 0 ? `+${n}` : `${n}`;
};

const fmtCurrency = (val) =>
  new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Number(val || 0));

export default function ActualsModelReconciliationCard() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const loadReconciliation = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get('/api/actuals/model-reconciliation', {
        params: { lookback_days: 120 },
      });
      setData(res.data || null);
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not load model reconciliation.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadReconciliation();
  }, []);

  const summary = data?.summary || {};
  const matches = Array.isArray(data?.matches) ? data.matches : [];

  return (
    <div className="bg-slate-900 border border-slate-800 p-6 rounded-xl backdrop-blur-sm space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-xl font-bold flex items-center gap-2 text-white">
            <Target className="text-indigo-400" size={20} aria-hidden="true" />
            <span>Model vs. Actual Execution</span>
          </h3>
          <p className="text-xs text-slate-400 mt-0.5">
            Compares synced DraftKings &amp; FanDuel straight bets against Basement Bets model picks and prices (last 120 days).
          </p>
        </div>

        <button
          type="button"
          onClick={loadReconciliation}
          disabled={loading}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-xs font-semibold text-slate-200 disabled:opacity-60"
        >
          <RefreshCw size={13} className={loading ? 'animate-spin' : ''} aria-hidden="true" />
          <span>{loading ? 'Refreshing...' : 'Refresh Comparison'}</span>
        </button>
      </div>

      {error && (
        <div className="p-3 rounded-lg bg-red-950/40 border border-red-500/40 text-xs text-red-200">
          {error}
        </div>
      )}

      {!loading && !error && matches.length === 0 && (
        <div className="p-4 rounded-xl bg-slate-950/50 border border-slate-800 text-xs text-slate-400">
          No recent DraftKings/FanDuel bets matched graded model picks yet. Sync open or settled slips via{' '}
          <strong className="text-slate-200">Add Bet &rarr; Auto-Sync / CSV</strong> to track follow rate, line shopping edge, and realized vs. model ROI.
        </div>
      )}

      {matches.length > 0 && (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            <div className="bg-slate-800/40 border border-slate-700 rounded-xl p-4">
              <div className="text-[10px] uppercase tracking-widest text-slate-400 font-black">Model Follow Rate</div>
              <div className="text-2xl font-black text-white mt-1">
                {summary.follow_rate_pct != null ? `${Number(summary.follow_rate_pct).toFixed(1)}%` : '—'}
              </div>
              <div className="text-xs text-slate-400 mt-1">
                {summary.aligned_count ?? 0} with model &bull; {summary.faded_count ?? 0} opposite
              </div>
            </div>

            <div className="bg-slate-800/40 border border-slate-700 rounded-xl p-4">
              <div className="text-[10px] uppercase tracking-widest text-slate-400 font-black">Line Shopping Edge</div>
              <div
                className={`text-2xl font-black mt-1 ${
                  (summary.avg_price_edge_vs_model_pct ?? 0) >= 0 ? 'text-emerald-400' : 'text-amber-400'
                }`}
              >
                {summary.avg_price_edge_vs_model_pct != null
                  ? `${summary.avg_price_edge_vs_model_pct >= 0 ? '+' : ''}${Number(summary.avg_price_edge_vs_model_pct).toFixed(2)}%`
                  : '—'}
              </div>
              <div className="text-xs text-slate-400 mt-1">
                Avg implied prob vs. model quote
              </div>
            </div>

            <div className="bg-slate-800/40 border border-slate-700 rounded-xl p-4">
              <div className="text-[10px] uppercase tracking-widest text-slate-400 font-black">Your Actual ROI</div>
              <div
                className={`text-2xl font-black mt-1 ${
                  (summary.actual_roi_pct ?? 0) >= 0 ? 'text-emerald-400' : 'text-red-400'
                }`}
              >
                {summary.actual_roi_pct != null ? `${Number(summary.actual_roi_pct).toFixed(1)}%` : '—'}
              </div>
              <div className="text-xs text-slate-400 mt-1">
                {summary.aligned_record || '0-0'} &bull; {fmtCurrency(summary.aligned_profit)} on {fmtCurrency(summary.aligned_wager)}
              </div>
            </div>

            <div className="bg-slate-800/40 border border-slate-700 rounded-xl p-4">
              <div className="text-[10px] uppercase tracking-widest text-slate-400 font-black">Model ROI (Same Picks)</div>
              <div
                className={`text-2xl font-black mt-1 ${
                  (summary.model_roi_on_same_picks_pct ?? 0) >= 0 ? 'text-emerald-400' : 'text-red-400'
                }`}
              >
                {summary.model_roi_on_same_picks_pct != null
                  ? `${Number(summary.model_roi_on_same_picks_pct).toFixed(1)}%`
                  : '—'}
              </div>
              <div className="text-xs text-slate-400 mt-1">
                {summary.execution_gap_roi_pct != null
                  ? `Execution gap: ${summary.execution_gap_roi_pct >= 0 ? '+' : ''}${Number(summary.execution_gap_roi_pct).toFixed(1)}%`
                  : 'Waiting on settled games'}
              </div>
            </div>
          </div>

          <div
            className="overflow-x-auto border border-slate-800 rounded-xl"
            role="region"
            aria-label="Actual placed bets matched against model recommendations"
            tabIndex={0}
          >
            <table className="min-w-full text-left text-xs">
              <caption className="sr-only">
                Comparison of actual placed sportsbook bets versus model picks, odds, and realized profit
              </caption>
              <thead className="bg-slate-950/60 border-b border-slate-800 text-[10px] uppercase tracking-wider text-slate-400">
                <tr>
                  <th scope="col" className="py-2.5 px-3">Date</th>
                  <th scope="col" className="py-2.5 px-3">Game</th>
                  <th scope="col" className="py-2.5 px-3">Your Bet</th>
                  <th scope="col" className="py-2.5 px-3">Model Pick</th>
                  <th scope="col" className="py-2.5 px-3 text-right">Line Edge</th>
                  <th scope="col" className="py-2.5 px-3 text-right">Stake / P&amp;L</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/70">
                {matches.slice(0, 15).map((m, idx) => (
                  <tr key={`${m.bet_id || idx}`} className="hover:bg-slate-800/30">
                    <td className="py-2.5 px-3 text-slate-400 whitespace-nowrap">{m.date}</td>
                    <td className="py-2.5 px-3 text-slate-200 font-medium">{m.matchup}</td>
                    <td className="py-2.5 px-3">
                      <div className="text-slate-100 font-semibold">{m.bet_selection}</div>
                      <div className="text-[11px] text-slate-400">
                        {m.provider} &bull; {fmtOdds(m.bet_odds)} &bull;{' '}
                        <span className={m.aligned ? 'text-emerald-400' : 'text-amber-400'}>
                          {m.aligned ? 'Followed' : 'Opposite Side'}
                        </span>
                      </div>
                    </td>
                    <td className="py-2.5 px-3">
                      <div className="text-slate-200">{m.model_selection}</div>
                      <div className="text-[11px] text-slate-400">
                        Model {fmtOdds(m.model_odds)} &bull; EV +{Number(m.model_ev_pct || 0).toFixed(1)}%
                      </div>
                    </td>
                    <td
                      className={`py-2.5 px-3 text-right font-mono font-semibold ${
                        m.price_edge_vs_model_pct == null
                          ? 'text-slate-500'
                          : m.price_edge_vs_model_pct >= 0
                          ? 'text-emerald-400'
                          : 'text-amber-400'
                      }`}
                    >
                      {m.price_edge_vs_model_pct == null
                        ? '—'
                        : `${m.price_edge_vs_model_pct >= 0 ? '+' : ''}${Number(m.price_edge_vs_model_pct).toFixed(2)}%`}
                    </td>
                    <td className="py-2.5 px-3 text-right font-mono whitespace-nowrap">
                      <div className="text-slate-300">{fmtCurrency(m.wager)}</div>
                      <div
                        className={`text-[11px] font-bold ${
                          m.status === 'PENDING'
                            ? 'text-amber-300'
                            : m.profit >= 0
                            ? 'text-emerald-400'
                            : 'text-red-400'
                        }`}
                      >
                        {m.status === 'PENDING' ? 'OPEN' : fmtCurrency(m.profit)}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
