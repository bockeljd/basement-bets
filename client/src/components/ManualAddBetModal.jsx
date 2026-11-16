import React from 'react';

// Extracted from TransactionView.jsx. Keep behavior identical.
export default function ManualAddBetModal({
  show,
  manualBet,
  setManualBet,
  isUpdating,
  onSave,
  onClose,
  embedded = false,
}) {
  if (!show) return null;

  const Card = (
    <div className="w-full max-w-2xl bg-slate-900 border border-slate-700 rounded-xl shadow-2xl p-5">
        <div className="flex items-center justify-between mb-4">
          <div className="text-white font-bold">Add Bet (Manual)</div>
          <button type="button" className="text-gray-400 hover:text-white" onClick={() => onClose?.()}>
            ✕
          </button>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div>
            <label className="text-xs text-gray-400">Sportsbook</label>
            <select
              className="w-full bg-slate-950 border border-slate-700 rounded px-2 py-2 text-sm text-white"
              value={manualBet.sportsbook}
              onChange={(e) => setManualBet({ ...manualBet, sportsbook: e.target.value })}
            >
              <option>DraftKings</option>
              <option>FanDuel</option>
              <option>BetMGM</option>
              <option>Caesars</option>
              <option>bet365</option>
              <option>BetRivers</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-400">Account</label>
            <select
              className="w-full bg-slate-950 border border-slate-700 rounded px-2 py-2 text-sm text-white"
              value={manualBet.account_id || 'Main'}
              onChange={(e) => setManualBet({ ...manualBet, account_id: e.target.value })}
            >
              <option value="Main">Primary</option>
              <option value="User2">Secondary</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-400">Date (YYYY-MM-DD)</label>
            <input
              className="w-full bg-slate-950 border border-slate-700 rounded px-2 py-2 text-sm text-white"
              value={manualBet.placed_at}
              onChange={(e) => setManualBet({ ...manualBet, placed_at: e.target.value })}
            />
          </div>
          <div>
            <label className="text-xs text-gray-400">Sport</label>
            <input
              className="w-full bg-slate-950 border border-slate-700 rounded px-2 py-2 text-sm text-white"
              placeholder="NFL, NBA, NCAAM..."
              value={manualBet.sport}
              onChange={(e) => setManualBet({ ...manualBet, sport: e.target.value })}
            />
          </div>
          <div>
            <label className="text-xs text-gray-400">Type</label>
            <input
              className="w-full bg-slate-950 border border-slate-700 rounded px-2 py-2 text-sm text-white"
              placeholder="Straight, SGP, Parlay..."
              value={manualBet.market_type}
              onChange={(e) => setManualBet({ ...manualBet, market_type: e.target.value })}
            />
          </div>
          <div className="md:col-span-2">
            <label className="text-xs text-gray-400">Event / Game</label>
            <input
              className="w-full bg-slate-950 border border-slate-700 rounded px-2 py-2 text-sm text-white"
              placeholder="e.g., Patriots vs Broncos"
              value={manualBet.event_name}
              onChange={(e) => setManualBet({ ...manualBet, event_name: e.target.value })}
            />
          </div>
          <div className="md:col-span-2">
            <label className="text-xs text-gray-400">Selection</label>
            <input
              className="w-full bg-slate-950 border border-slate-700 rounded px-2 py-2 text-sm text-white"
              placeholder="e.g., Under 28.5"
              value={manualBet.selection}
              onChange={(e) => setManualBet({ ...manualBet, selection: e.target.value })}
            />
          </div>
          <div>
            <label className="text-xs text-gray-400">Odds (American)</label>
            <input
              className="w-full bg-slate-950 border border-slate-700 rounded px-2 py-2 text-sm text-white"
              placeholder="e.g., -110 or 254"
              value={manualBet.odds}
              onChange={(e) => setManualBet({ ...manualBet, odds: e.target.value })}
            />
          </div>
          <div>
            <label className="text-xs text-gray-400">Wager ($)</label>
            <input
              className="w-full bg-slate-950 border border-slate-700 rounded px-2 py-2 text-sm text-white"
              placeholder="e.g., 10"
              value={manualBet.stake}
              onChange={(e) => setManualBet({ ...manualBet, stake: e.target.value })}
            />
          </div>
          <div>
            <label className="text-xs text-gray-400">Status</label>
            <select
              className="w-full bg-slate-950 border border-slate-700 rounded px-2 py-2 text-sm text-white"
              value={manualBet.status}
              onChange={(e) => setManualBet({ ...manualBet, status: e.target.value })}
            >
              <option value="WON">WON</option>
              <option value="LOST">LOST</option>
              <option value="PENDING">PENDING</option>
              <option value="PUSH">PUSH</option>
            </select>
          </div>
          <div className="md:col-span-1 flex items-end justify-end gap-2">
            <button
              type="button"
              className="px-3 py-2 rounded-lg border border-slate-700 text-gray-200 hover:bg-slate-800"
              onClick={() => onClose?.()}
            >
              Cancel
            </button>
            <button
              type="button"
              className="px-3 py-2 rounded-lg bg-green-600 hover:bg-green-500 text-white font-bold"
              onClick={() => onSave?.()}
              disabled={isUpdating}
            >
              Save
            </button>
          </div>
        </div>

        <div className="mt-3 text-[11px] text-gray-500">
          This creates a bet row directly in your Transactions table (manual tracking).
        </div>
      </div>
  );

  if (embedded) return Card;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      {Card}
    </div>
  );
}
