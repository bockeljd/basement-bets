import React, { useState } from 'react';
import { DollarSign } from 'lucide-react';

export default function Bankroll({ financials, bets, formatCurrency }) {
  const [expandedBook, setExpandedBook] = useState(null);

  const normalizedFinancials = financials || {};

  if (!normalizedFinancials?.breakdown) {
    return (
      <div className="space-y-6">
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <h1 className="text-2xl font-black text-white">Bankroll</h1>
          <p className="text-slate-400 text-sm mt-1">Balances, deposits/withdrawals, and reconciliation live here.</p>
        </div>
        <div className="text-slate-500">No bankroll data available.</div>
      </div>
    );
  }

  const rows = normalizedFinancials.breakdown || [];
  const provTop = (name) => rows.find((r) => r.provider === name && r.account_id === null);
  const provAcc = (name, acc) => rows.find((r) => r.provider === name && String(r.account_id || '') === String(acc));

  const providers = ['DraftKings', 'FanDuel', 'Other'];
  const fmt = (x) => (formatCurrency ? formatCurrency(Number(x || 0)) : String(Number(x || 0)));
  const fmtPct = (x) => `${Number(x || 0).toFixed(1)}%`;

  const topRows = providers
    .map((p) => {
      if (p === 'Other') {
        return { p: 'Other', top: provTop('Other'), primary: provAcc('Other', 'Main'), secondary: provAcc('Other', 'User2') };
      }
      return { p, top: provTop(p), primary: provAcc(p, 'Main'), secondary: provAcc(p, 'User2') };
    })
    .filter((x) => x.top);

  return (
    <div className="space-y-6">
      <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-xl">
        <div className="p-6 border-b border-slate-800">
          <div className="flex items-center justify-between">
            <h3 className="text-xl font-bold flex items-center gap-2">
              <DollarSign className="text-green-400" /> Sportsbook Financials
            </h3>
            <div className="text-[11px] text-slate-500">Statement view (click a row to expand)</div>
          </div>
          <div className="mt-2 text-[10px] text-gray-600 uppercase tracking-widest opacity-70">
            Baseline balances from latest snapshots; ledger includes deposits/withdrawals and open/pending wagers.
          </div>
        </div>

        <div className="overflow-x-auto" role="region" aria-label="Sportsbook financials statement" tabIndex={0}>
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Sportsbook current balance, deposits, withdrawals, and realized profit by provider</caption>
            <thead className="bg-slate-950/50">
              <tr className="text-slate-400 border-b border-slate-800">
                <th scope="col" className="py-3 px-4">Sportsbook</th>
                <th scope="col" className="py-3 px-4 text-right">Current</th>
                <th scope="col" className="py-3 px-4 text-right">Deposits</th>
                <th scope="col" className="py-3 px-4 text-right">Withdrawals</th>
                <th scope="col" className="py-3 px-4 text-right">Realized P/L</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {topRows.map(({ p, top, primary, secondary }) => {
                const cur = Number((top.ledger_in_play ?? top.in_play) || 0);
                const isOpen = expandedBook === p;

                return (
                  <React.Fragment key={p}>
                    <tr className={`hover:bg-slate-800/30 ${isOpen ? 'bg-slate-800/20' : ''}`}>
                      <td className="py-3 px-4 font-black text-slate-100">
                        <button
                          type="button"
                          aria-expanded={isOpen}
                          onClick={() => setExpandedBook(isOpen ? null : p)}
                          className="flex items-center gap-2 hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-400 rounded px-1 py-0.5"
                        >
                          <span className="text-slate-400" aria-hidden="true">{isOpen ? '▾' : '▸'}</span>
                          <span>{p}</span>
                        </button>
                      </td>
                      <td className={`py-3 px-4 text-right font-black ${cur >= 0 ? 'text-green-300' : 'text-red-300'}`}>{fmt(cur)}</td>
                      <td className="py-3 px-4 text-right text-slate-300 font-mono">{fmt(top.deposited)}</td>
                      <td className="py-3 px-4 text-right text-slate-300 font-mono">{fmt(top.withdrawn)}</td>
                      <td className={`py-3 px-4 text-right font-mono font-bold ${Number(top.net_profit || 0) >= 0 ? 'text-green-300' : 'text-red-300'}`}>{fmt(top.net_profit)}</td>
                    </tr>

                    {isOpen ? (
                      <tr className="bg-slate-950/20">
                        <td colSpan={6} className="px-4 py-4">
                          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                            <div className="border border-slate-800 rounded-lg p-4 bg-slate-950/20">
                              <div className="text-[10px] uppercase tracking-widest text-slate-500 font-black">Primary</div>
                              <div className="mt-1 text-xl font-black text-white">{fmt(Number((primary?.ledger_in_play ?? primary?.in_play) || 0))}</div>
                              <div className="mt-2 grid grid-cols-2 gap-2 text-[11px] text-slate-400">
                                <div>Dep <span className="font-mono text-slate-200">{fmt(Number(primary?.deposited || 0))}</span></div>
                                <div>Wdr <span className="font-mono text-slate-200">{fmt(Number(primary?.withdrawn || 0))}</span></div>
                              </div>
                            </div>
                            <div className="border border-slate-800 rounded-lg p-4 bg-slate-950/20">
                              <div className="text-[10px] uppercase tracking-widest text-slate-500 font-black">Secondary</div>
                              <div className="mt-1 text-xl font-black text-white">{fmt(Number((secondary?.ledger_in_play ?? secondary?.in_play) || 0))}</div>
                              <div className="mt-2 grid grid-cols-2 gap-2 text-[11px] text-slate-400">
                                <div>Dep <span className="font-mono text-slate-200">{fmt(Number(secondary?.deposited || 0))}</span></div>
                                <div>Wdr <span className="font-mono text-slate-200">{fmt(Number(secondary?.withdrawn || 0))}</span></div>
                              </div>
                            </div>
                          </div>
                        </td>
                      </tr>
                    ) : null}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Scatter plot removed per request */}
    </div>
  );
}
