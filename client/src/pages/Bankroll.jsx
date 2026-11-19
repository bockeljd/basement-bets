import React, { useState } from 'react';
import { DollarSign, CheckCircle2, AlertCircle } from 'lucide-react';
import api from '../api/axios';
import { formatSyncDateLabel, getAccountLastSync } from '../components/TransactionView';

export default function Bankroll({ financials, bets, formatCurrency }) {
  const [expandedBook, setExpandedBook] = useState('DraftKings');
  const [editingAcc, setEditingAcc] = useState(null); // { provider, accountId, value }
  const [savingBalance, setSavingBalance] = useState(false);
  const [balanceMsg, setBalanceMsg] = useState(null);

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

  const fmtCaptured = (ts) => {
    if (!ts) return 'none';
    const d = new Date(ts);
    if (isNaN(d.getTime())) return String(ts).slice(0, 10);
    return d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
  };

  const handleSaveSnapshot = async (e) => {
    e.preventDefault();
    if (!editingAcc) return;
    const val = Number(editingAcc.value);
    if (!Number.isFinite(val) || val < 0) {
      setBalanceMsg({ tone: 'err', text: 'Enter a valid non-negative balance.' });
      return;
    }
    setSavingBalance(true);
    setBalanceMsg(null);
    try {
      await api.post('/api/balances/snapshots', {
        provider: editingAcc.provider,
        account_id: editingAcc.accountId,
        balance: val,
        source: 'manual_bankroll_fix',
        note: 'Set cash balance directly in Bankroll view',
      });
      setBalanceMsg({
        tone: 'ok',
        text: `Updated ${editingAcc.provider} ${editingAcc.accountId === 'User2' ? 'Secondary' : 'Primary'} cash balance to ${fmt(val)}.`,
      });
      setEditingAcc(null);
      if (typeof window !== 'undefined' && typeof window.__BB_RELOAD_DASHBOARD__ === 'function') {
        await window.__BB_RELOAD_DASHBOARD__();
      }
    } catch (err) {
      setBalanceMsg({
        tone: 'err',
        text: err.response?.data?.detail || err.message || 'Failed to update balance snapshot.',
      });
    } finally {
      setSavingBalance(false);
    }
  };

  return (
    <div className="space-y-6">
      {balanceMsg && (
        <div
          role="status"
          aria-live="polite"
          className={`flex items-center gap-2 p-3 rounded-xl border text-xs font-semibold ${
            balanceMsg.tone === 'ok'
              ? 'bg-emerald-950/50 border-emerald-500/40 text-emerald-200'
              : 'bg-red-950/50 border-red-500/40 text-red-200'
          }`}
        >
          {balanceMsg.tone === 'ok' ? <CheckCircle2 className="w-4 h-4 text-emerald-400" /> : <AlertCircle className="w-4 h-4 text-red-400" />}
          <span>{balanceMsg.text}</span>
        </div>
      )}
      <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-xl">
        <div className="p-5 border-b border-slate-800 flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 className="text-lg font-bold flex items-center gap-2 text-white">
              <DollarSign className="text-emerald-400" size={18} /> Bankroll, Deposits &amp; Withdrawals
            </h3>
            <p className="text-xs text-slate-400 mt-0.5">
              Click any sportsbook to view accounts or update cash balance.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3 text-xs font-mono">
            <span className="text-slate-300">
              Deposited: <strong className="text-white">{fmt(normalizedFinancials.total_deposited)}</strong>
            </span>
            <span className="text-slate-300">
              Withdrawn: <strong className="text-white">{fmt(normalizedFinancials.total_withdrawn)}</strong>
            </span>
            <span className="text-slate-300">
              Net In:{' '}
              <strong className="text-sky-300">
                {fmt(Number(normalizedFinancials.total_deposited || 0) - Number(normalizedFinancials.total_withdrawn || 0))}
              </strong>
            </span>
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
                            {[
                              { accId: 'Main', label: 'Primary', data: primary },
                              { accId: 'User2', label: 'Secondary', data: secondary },
                            ].map(({ accId, label, data }) => {
                              const currentVal = Number((data?.ledger_in_play ?? data?.in_play) || 0);
                              const baseVal = Number(data?.in_play || 0);
                              const deltaVal = Number(data?.ledger_delta || 0);
                              const isEditing = editingAcc?.provider === p && editingAcc?.accountId === accId;
                              return (
                                <div key={accId} className="border border-slate-800 rounded-lg p-4 bg-slate-950/20 space-y-2">
                                  <div className="flex items-center justify-between">
                                    <span className="text-[10px] uppercase tracking-widest text-slate-500 font-black">{label}</span>
                                    {p !== 'Other' && (
                                      <button
                                        type="button"
                                        onClick={() =>
                                          setEditingAcc(
                                            isEditing ? null : { provider: p, accountId: accId, value: currentVal.toFixed(2) }
                                          )
                                        }
                                        className="text-[11px] font-semibold text-indigo-300 hover:text-indigo-200 px-2 py-0.5 rounded border border-indigo-500/30 bg-indigo-950/30"
                                      >
                                        {isEditing ? 'Cancel' : 'Set Cash Balance'}
                                      </button>
                                    )}
                                  </div>
                                  <div className="text-xl font-black text-white">{fmt(currentVal)}</div>
                                  <div className="text-[11px] text-slate-400">
                                    Last sync: <span className="font-mono text-slate-200">{formatSyncDateLabel(getAccountLastSync(p, accId, data, bets))}</span>
                                  </div>
                                  <div className="text-[11px] text-slate-400">
                                    Base snapshot: <span className="font-mono text-slate-200">{fmt(baseVal)}</span>
                                    {data?.captured_at ? ` (${fmtCaptured(data.captured_at)})` : ''} &bull;{' '}
                                    Post-snapshot delta:{' '}
                                    <span className={`font-mono ${deltaVal >= 0 ? 'text-emerald-300' : 'text-red-300'}`}>
                                      {deltaVal >= 0 ? '+' : ''}{fmt(deltaVal)}
                                    </span>
                                  </div>
                                  {isEditing && (
                                    <form onSubmit={handleSaveSnapshot} className="flex items-center gap-2 pt-1">
                                      <label htmlFor={`bal-${p}-${accId}`} className="sr-only">
                                        {p} {label} Cash Balance
                                      </label>
                                      <input
                                        id={`bal-${p}-${accId}`}
                                        type="number"
                                        step="0.01"
                                        min="0"
                                        value={editingAcc.value}
                                        onChange={(e) => setEditingAcc({ ...editingAcc, value: e.target.value })}
                                        className="w-28 bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs text-white font-mono"
                                        required
                                      />
                                      <button
                                        type="submit"
                                        disabled={savingBalance}
                                        className="px-2.5 py-1 rounded bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold"
                                      >
                                        {savingBalance ? 'Saving...' : 'Save'}
                                      </button>
                                    </form>
                                  )}
                                  <div className="pt-1 grid grid-cols-2 gap-2 text-[11px] text-slate-400">
                                    <div>Deposited <span className="font-mono text-slate-200">{fmt(Number(data?.deposited || 0))}</span></div>
                                    <div>Withdrawn <span className="font-mono text-slate-200">{fmt(Number(data?.withdrawn || 0))}</span></div>
                                  </div>
                                </div>
                              );
                            })}
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
