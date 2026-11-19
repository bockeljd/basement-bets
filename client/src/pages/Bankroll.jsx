import React, { useState } from 'react';
import { DollarSign, CheckCircle2, AlertCircle, PlusCircle, X, RotateCcw } from 'lucide-react';
import api from '../api/axios';
import { formatSyncDateLabel, getAccountLastSync } from '../components/TransactionView';

export default function Bankroll({ financials, bets, formatCurrency }) {
  const [expandedBook, setExpandedBook] = useState('DraftKings');
  const [editingAcc, setEditingAcc] = useState(null); // { provider, accountId, value }
  const [savingBalance, setSavingBalance] = useState(false);
  const [balanceMsg, setBalanceMsg] = useState(null);
  const [showTxnForm, setShowTxnForm] = useState(false);
  const [savingTxn, setSavingTxn] = useState(false);
  const [cleaningSync, setCleaningSync] = useState(false);
  const [txnForm, setTxnForm] = useState(() => ({
    type: 'Deposit',
    provider: 'DraftKings',
    account_id: 'Main',
    amount: '',
    date: new Date().toISOString().slice(0, 10),
    description: '',
  }));

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
    return formatSyncDateLabel(ts);
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

  const handleSaveTxn = async (e) => {
    e.preventDefault();
    const amt = Number(txnForm.amount);
    if (!Number.isFinite(amt) || amt <= 0) {
      setBalanceMsg({ tone: 'err', text: 'Enter a valid positive amount.' });
      return;
    }
    setSavingTxn(true);
    setBalanceMsg(null);
    try {
      await api.post('/api/transactions/manual', {
        provider: txnForm.provider,
        account_id: txnForm.account_id,
        type: txnForm.type,
        amount: amt,
        date: txnForm.date || new Date().toISOString().slice(0, 10),
        description: txnForm.description.trim() || `Manual ${txnForm.type}`,
      });
      setBalanceMsg({
        tone: 'ok',
        text: `Logged ${txnForm.type} of ${fmt(amt)} on ${txnForm.provider} (${txnForm.account_id === 'User2' ? 'Secondary' : 'Primary'}).`,
      });
      setTxnForm((prev) => ({ ...prev, amount: '', description: '' }));
      setShowTxnForm(false);
      if (typeof window !== 'undefined' && typeof window.__BB_RELOAD_DASHBOARD__ === 'function') {
        await window.__BB_RELOAD_DASHBOARD__();
      }
    } catch (err) {
      setBalanceMsg({
        tone: 'err',
        text: err.response?.data?.detail || err.message || 'Failed to log transaction.',
      });
    } finally {
      setSavingTxn(false);
    }
  };

  const handleCleanupSync = async () => {
    setCleaningSync(true);
    setBalanceMsg(null);
    try {
      const res = await api.post('/api/transactions/cleanup-sync', { remove_browser_txns: true });
      const d = res.data || {};
      const parts = [];
      if (d.reverted_snapshots > 0) parts.push(`restored ${d.reverted_snapshots} overwritten balance snapshot${d.reverted_snapshots === 1 ? '' : 's'}`);
      if (d.browser_txns_removed > 0) parts.push(`removed ${d.browser_txns_removed} browser-sync txn${d.browser_txns_removed === 1 ? '' : 's'}`);
      if (d.deduped_txns > 0) parts.push(`removed ${d.deduped_txns} duplicate txn${d.deduped_txns === 1 ? '' : 's'}`);
      setBalanceMsg({
        tone: 'ok',
        text: parts.length ? `Cleanup complete: ${parts.join(' · ')}.` : 'No duplicate transactions or recent bookmarklet balance overwrites found.',
      });
      if (typeof window !== 'undefined' && typeof window.__BB_RELOAD_DASHBOARD__ === 'function') {
        await window.__BB_RELOAD_DASHBOARD__();
      }
    } catch (err) {
      setBalanceMsg({
        tone: 'err',
        text: err.response?.data?.detail || err.message || 'Cleanup failed.',
      });
    } finally {
      setCleaningSync(false);
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
        <div className="p-5 border-b border-slate-800 flex flex-wrap items-center justify-between gap-3">
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
              Net:{' '}
              {(() => {
                const netCash = Number(normalizedFinancials.total_withdrawn || 0) - Number(normalizedFinancials.total_deposited || 0);
                return (
                  <strong className={netCash >= 0 ? 'text-emerald-300' : 'text-rose-300'}>
                    {netCash >= 0 ? '+' : ''}{fmt(netCash)}
                  </strong>
                );
              })()}
            </span>
            <button
              type="button"
              onClick={() => setShowTxnForm((v) => !v)}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-600/20 hover:bg-emerald-600/30 border border-emerald-500/40 text-emerald-200 font-sans font-semibold text-xs cursor-pointer transition-colors"
            >
              {showTxnForm ? <X size={14} aria-hidden="true" /> : <PlusCircle size={14} aria-hidden="true" />}
              <span>{showTxnForm ? 'Close' : 'Log Deposit / Withdrawal'}</span>
            </button>
            <button
              type="button"
              onClick={handleCleanupSync}
              disabled={cleaningSync}
              title="Restore overwritten bookmarklet balance snapshot and remove duplicate transactions"
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-amber-500/15 hover:bg-amber-500/25 border border-amber-500/35 text-amber-200 font-sans font-semibold text-xs cursor-pointer transition-colors disabled:opacity-50"
            >
              <RotateCcw size={13} aria-hidden="true" />
              <span>{cleaningSync ? 'Restoring…' : 'Revert Bad Sync'}</span>
            </button>
          </div>
        </div>

        {showTxnForm && (
          <form onSubmit={handleSaveTxn} className="p-4 border-b border-slate-800 bg-slate-950/70 space-y-3">
            <div className="flex flex-wrap items-center gap-3 text-xs">
              <div className="inline-flex rounded-lg border border-slate-700 bg-slate-900 p-0.5">
                {['Deposit', 'Withdrawal'].map((t) => (
                  <button
                    key={t}
                    type="button"
                    onClick={() => setTxnForm((f) => ({ ...f, type: t }))}
                    className={`px-3 py-1 rounded-md font-semibold cursor-pointer transition-colors ${
                      txnForm.type === t
                        ? t === 'Withdrawal'
                          ? 'bg-emerald-600 text-white'
                          : 'bg-sky-600 text-white'
                        : 'text-slate-400 hover:text-white'
                    }`}
                  >
                    {t}
                  </button>
                ))}
              </div>

              <div className="inline-flex rounded-lg border border-slate-700 bg-slate-900 p-0.5">
                {['DraftKings', 'FanDuel', 'Other'].map((bk) => (
                  <button
                    key={bk}
                    type="button"
                    onClick={() => setTxnForm((f) => ({ ...f, provider: bk }))}
                    className={`px-3 py-1 rounded-md font-semibold cursor-pointer transition-colors ${
                      txnForm.provider === bk ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-white'
                    }`}
                  >
                    {bk}
                  </button>
                ))}
              </div>

              <div className="inline-flex rounded-lg border border-slate-700 bg-slate-900 p-0.5">
                {[
                  { id: 'Main', label: 'Primary' },
                  { id: 'User2', label: 'Secondary' },
                ].map((acc) => (
                  <button
                    key={acc.id}
                    type="button"
                    onClick={() => setTxnForm((f) => ({ ...f, account_id: acc.id }))}
                    className={`px-3 py-1 rounded-md font-semibold cursor-pointer transition-colors ${
                      txnForm.account_id === acc.id ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-white'
                    }`}
                  >
                    {acc.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-4 gap-2.5 text-xs">
              <div>
                <label htmlFor="txn-amount" className="block text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-1">
                  Amount ($)
                </label>
                <input
                  id="txn-amount"
                  type="number"
                  step="0.01"
                  min="0.01"
                  required
                  placeholder="250.00"
                  value={txnForm.amount}
                  onChange={(e) => setTxnForm((f) => ({ ...f, amount: e.target.value }))}
                  className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-700 text-white font-mono focus:outline-none focus:border-emerald-500"
                />
              </div>
              <div>
                <label htmlFor="txn-date" className="block text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-1">
                  Date
                </label>
                <input
                  id="txn-date"
                  type="date"
                  value={txnForm.date}
                  onChange={(e) => setTxnForm((f) => ({ ...f, date: e.target.value }))}
                  className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-700 text-white font-mono focus:outline-none focus:border-emerald-500"
                />
              </div>
              <div>
                <label htmlFor="txn-note" className="block text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-1">
                  Note (optional)
                </label>
                <input
                  id="txn-note"
                  type="text"
                  placeholder="e.g. PayPal cashout"
                  value={txnForm.description}
                  onChange={(e) => setTxnForm((f) => ({ ...f, description: e.target.value }))}
                  className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-700 text-white focus:outline-none focus:border-emerald-500"
                />
              </div>
              <div className="flex items-end">
                <button
                  type="submit"
                  disabled={savingTxn}
                  className="w-full px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white font-semibold cursor-pointer transition-colors"
                >
                  {savingTxn ? 'Saving…' : `Save ${txnForm.type}`}
                </button>
              </div>
            </div>
          </form>
        )}

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
                                  {data?.computed_in_play != null && (() => {
                                    const expCash = Number(data.computed_in_play || 0);
                                    const diffCash = Number(data.computed_delta ?? (currentVal - expCash));
                                    const inSync = Math.abs(diffCash) <= 1.0;
                                    const betPl = Number(data.bet_profit || 0);
                                    const openSt = Number(data.open_stake || 0);
                                    return (
                                      <div className="pt-2 mt-1 border-t border-slate-800/80 flex flex-wrap items-center justify-between gap-2 text-[11px]">
                                        <span className="text-slate-400">
                                          Audit: Bet P/L{' '}
                                          <strong className={`font-mono ${betPl >= 0 ? 'text-emerald-300' : 'text-rose-300'}`}>
                                            {betPl >= 0 ? '+' : ''}{fmt(betPl)}
                                          </strong>
                                          {openSt > 0 ? <> · Open <span className="font-mono text-sky-300">{fmt(openSt)}</span></> : null}
                                          {' · '}Expected <strong className="font-mono text-slate-200">{fmt(expCash)}</strong>
                                        </span>
                                        <span
                                          title="Actual Cash Balance minus Expected Cash (Deposits - Withdrawals + Bet P/L - Open Stakes)"
                                          className={`px-2 py-0.5 rounded-full font-mono font-bold text-[10px] border cursor-help ${
                                            inSync
                                              ? 'bg-emerald-500/15 border-emerald-500/35 text-emerald-300'
                                              : 'bg-amber-500/15 border-amber-500/35 text-amber-200'
                                          }`}
                                        >
                                          {inSync ? 'In Sync' : `Diff ${diffCash >= 0 ? '+' : ''}${fmt(diffCash)}`}
                                        </span>
                                      </div>
                                    );
                                  })()}
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
