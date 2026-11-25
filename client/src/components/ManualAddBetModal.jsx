import React, { useEffect, useRef } from 'react';

// Extracted from TransactionView.jsx. Keep behavior identical.
export default function ManualAddBetModal({
  show,
  manualBet,
  setManualBet,
  isUpdating,
  onSave,
  onClose,
  embedded = false,
  titleId = 'manual-add-bet-title',
}) {
  const dialogRef = useRef(null);
  const pressedOutsideRef = useRef(false);

  useEffect(() => {
    if (embedded) return;
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (show) {
      if (!dialog.open && typeof dialog.showModal === 'function') {
        dialog.showModal();
      }
    } else if (dialog.open) {
      dialog.close();
    }
  }, [show, embedded]);

  const isOutsideDialog = (event, dialog) => {
    const r = dialog.getBoundingClientRect();
    return event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom;
  };

  if (!show) return null;

  const Card = (
    <div className="w-full max-w-2xl bg-slate-900 border border-slate-700 rounded-xl shadow-2xl p-5">
        <div className="flex items-center justify-between mb-4">
          <h1 id={titleId} className="text-base text-white font-bold">Add Bet (Manual)</h1>
          <button
            type="button"
            aria-label="Close add bet dialog"
            className="text-gray-400 hover:text-white px-2 py-1 rounded-lg hover:bg-slate-800 cursor-pointer"
            onClick={() => onClose?.()}
          >
            ✕
          </button>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div>
            <label htmlFor="manual-bet-sportsbook" className="text-xs text-gray-400">Sportsbook</label>
            <select
              id="manual-bet-sportsbook"
              autoFocus
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
            <label htmlFor="manual-bet-account" className="text-xs text-gray-400">Account</label>
            <select
              id="manual-bet-account"
              className="w-full bg-slate-950 border border-slate-700 rounded px-2 py-2 text-sm text-white"
              value={manualBet.account_id || 'Main'}
              onChange={(e) => setManualBet({ ...manualBet, account_id: e.target.value })}
            >
              <option value="Main">Primary</option>
              <option value="User2">Secondary</option>
            </select>
          </div>
          <div>
            <label htmlFor="manual-bet-date" className="text-xs text-gray-400">Date (YYYY-MM-DD)</label>
            <input
              id="manual-bet-date"
              className="w-full bg-slate-950 border border-slate-700 rounded px-2 py-2 text-sm text-white"
              value={manualBet.placed_at}
              onChange={(e) => setManualBet({ ...manualBet, placed_at: e.target.value })}
            />
          </div>
          <div>
            <label htmlFor="manual-bet-sport" className="text-xs text-gray-400">Sport</label>
            <input
              id="manual-bet-sport"
              className="w-full bg-slate-950 border border-slate-700 rounded px-2 py-2 text-sm text-white"
              placeholder="NFL, NBA, NCAAM..."
              value={manualBet.sport}
              onChange={(e) => setManualBet({ ...manualBet, sport: e.target.value })}
            />
          </div>
          <div>
            <label htmlFor="manual-bet-type" className="text-xs text-gray-400">Type</label>
            <input
              id="manual-bet-type"
              className="w-full bg-slate-950 border border-slate-700 rounded px-2 py-2 text-sm text-white"
              placeholder="Straight, SGP, Parlay..."
              value={manualBet.market_type}
              onChange={(e) => setManualBet({ ...manualBet, market_type: e.target.value })}
            />
          </div>
          <div className="md:col-span-2">
            <label htmlFor="manual-bet-event" className="text-xs text-gray-400">Event / Game</label>
            <input
              id="manual-bet-event"
              className="w-full bg-slate-950 border border-slate-700 rounded px-2 py-2 text-sm text-white"
              placeholder="e.g., Patriots vs Broncos"
              value={manualBet.event_name}
              onChange={(e) => setManualBet({ ...manualBet, event_name: e.target.value })}
            />
          </div>
          <div className="md:col-span-2">
            <label htmlFor="manual-bet-selection" className="text-xs text-gray-400">Selection</label>
            <input
              id="manual-bet-selection"
              className="w-full bg-slate-950 border border-slate-700 rounded px-2 py-2 text-sm text-white"
              placeholder="e.g., Under 28.5"
              value={manualBet.selection}
              onChange={(e) => setManualBet({ ...manualBet, selection: e.target.value })}
            />
          </div>
          <div>
            <label htmlFor="manual-bet-odds" className="text-xs text-gray-400">Odds (American)</label>
            <input
              id="manual-bet-odds"
              className="w-full bg-slate-950 border border-slate-700 rounded px-2 py-2 text-sm text-white"
              placeholder="e.g., -110 or 254"
              value={manualBet.odds}
              onChange={(e) => setManualBet({ ...manualBet, odds: e.target.value })}
            />
          </div>
          <div>
            <label htmlFor="manual-bet-wager" className="text-xs text-gray-400">Wager ($)</label>
            <input
              id="manual-bet-wager"
              className="w-full bg-slate-950 border border-slate-700 rounded px-2 py-2 text-sm text-white"
              placeholder="e.g., 10"
              value={manualBet.stake}
              onChange={(e) => setManualBet({ ...manualBet, stake: e.target.value })}
            />
          </div>
          <div>
            <label htmlFor="manual-bet-status" className="text-xs text-gray-400">Status</label>
            <select
              id="manual-bet-status"
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
              className="px-3 py-2 rounded-lg border border-slate-700 text-gray-200 hover:bg-slate-800 cursor-pointer"
              onClick={() => onClose?.()}
            >
              Cancel
            </button>
            <button
              type="button"
              className="px-3 py-2 rounded-lg bg-green-600 hover:bg-green-500 text-white font-bold cursor-pointer disabled:opacity-50"
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
    <dialog
      ref={dialogRef}
      closedby="any"
      aria-labelledby={titleId}
      onCancel={(e) => {
        e.preventDefault();
        onClose?.();
      }}
      onPointerDown={(e) => {
        const d = dialogRef.current;
        if (d) pressedOutsideRef.current = isOutsideDialog(e, d);
      }}
      onPointerUp={(e) => {
        const d = dialogRef.current;
        if (!('closedBy' in HTMLDialogElement.prototype) && pressedOutsideRef.current && d && isOutsideDialog(e, d)) {
          onClose?.();
        }
        pressedOutsideRef.current = false;
      }}
      className="bg-transparent p-0 m-auto max-w-2xl w-[94dvw] backdrop:bg-black/75 backdrop:backdrop-blur-sm"
    >
      {Card}
    </dialog>
  );
}
