import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Info, Upload, ClipboardPaste, X, CheckCircle2, AlertCircle, Bookmark, Copy, ExternalLink } from 'lucide-react';
import api from '../../api/axios';
import { buildKenpomBookmarklet } from './todayHelpers';

const FEED_LABELS = {
  torvik: 'BartTorvik',
  kenpom: 'KenPom',
  haslametrics: 'Haslametrics',
  odds: 'Sportsbook Odds',
  action_splits: 'Public Betting Splits',
};

const ModelLogicDialog = ({ open, onClose, dataHealth = [], onKenpomUploaded, onPasteKenpomClipboard }) => {
  const dialogRef = useRef(null);
  const fileInputRef = useRef(null);
  const [selectedFile, setSelectedFile] = useState(null);
  const [pastedText, setPastedText] = useState('');
  const [kenpomStatus, setKenpomStatus] = useState(null);
  const [statusLoading, setStatusLoading] = useState(false);
  const [uploadState, setUploadState] = useState({ uploading: false, status: 'idle', message: '' });

  const bookmarkletCode = useMemo(() => {
    const origin = typeof window !== 'undefined' ? window.location.origin : '';
    return origin ? buildKenpomBookmarklet(origin) : '';
  }, []);

  const setBookmarkletEl = useCallback(
    (el) => {
      if (el && bookmarkletCode) {
        // Set href imperatively via callback ref without a JSX href prop so Chrome drag-to-bar always gets javascript:
        el.setAttribute('href', bookmarkletCode);
      }
    },
    [bookmarkletCode]
  );

  const handleCopyBookmarklet = async () => {
    if (!bookmarkletCode) return;
    try {
      await navigator.clipboard.writeText(bookmarkletCode);
      setUploadState({
        uploading: false,
        status: 'success',
        message: 'Bookmarklet code copied. Create a new browser bookmark, paste this as its URL, open kenpom.com while logged in, and click the bookmark.',
      });
    } catch {
      setUploadState({
        uploading: false,
        status: 'error',
        message: 'Could not access clipboard — drag the "Sync KenPom to Basement Bets" button directly to your bookmarks bar instead.',
      });
    }
  };

  const handleBookmarkletClick = (e) => {
    e.preventDefault();
    handleCopyBookmarklet();
  };

  const fetchKenpomStatus = async () => {
    setStatusLoading(true);
    try {
      const res = await api.get('/api/admin/kenpom/status');
      setKenpomStatus(res.data || null);
    } catch {
      setKenpomStatus(null);
    } finally {
      setStatusLoading(false);
    }
  };

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open) {
      if (!dialog.open && typeof dialog.showModal === 'function') {
        dialog.showModal();
      }
      fetchKenpomStatus();
    } else if (dialog.open) {
      dialog.close();
    }
  }, [open]);

  const handleBackdropClick = (event) => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const rect = dialog.getBoundingClientRect();
    const inside =
      rect.left <= event.clientX &&
      event.clientX <= rect.right &&
      rect.top <= event.clientY &&
      event.clientY <= rect.bottom;
    if (!inside) {
      onClose?.();
    }
  };

  const handleKenpomUpload = async (e) => {
    e.preventDefault();
    const trimmedPaste = pastedText.trim();
    if (!trimmedPaste && !selectedFile) {
      setUploadState({
        uploading: false,
        status: 'error',
        message: 'Paste the ratings table from kenpom.com OR choose a CSV/TSV file first.',
      });
      return;
    }
    setUploadState({ uploading: true, status: 'uploading', message: '' });
    try {
      let res;
      if (trimmedPaste) {
        res = await api.post('/api/admin/kenpom/upload-csv', { csv_text: trimmedPaste });
      } else {
        const formData = new FormData();
        formData.append('file', selectedFile);
        res = await api.post('/api/admin/kenpom/upload-csv', formData);
      }
      const rowsCount = res?.data?.rows ?? 'all';
      const asof = res?.data?.asof_date ? ` for ${res.data.asof_date}` : '';
      setUploadState({
        uploading: false,
        status: 'success',
        message: `Imported ${rowsCount} teams${asof}. Updating today's predictions...`,
      });
      setSelectedFile(null);
      setPastedText('');
      if (fileInputRef.current) fileInputRef.current.value = '';
      await fetchKenpomStatus();
      onKenpomUploaded?.();
    } catch (err) {
      const detail = err?.response?.data?.detail || err?.message || 'Import failed';
      setUploadState({ uploading: false, status: 'error', message: String(detail) });
    }
  };

  const bySource = {};
  (dataHealth || []).forEach((item) => {
    if (item?.source) bySource[item.source] = item;
  });

  const kpActive = kenpomStatus ? Boolean(kenpomStatus.active) : String(bySource.kenpom?.status || '').toLowerCase() === 'ok';
  const kpMethods = kenpomStatus?.configured_methods || {};

  return (
    <dialog
      ref={dialogRef}
      closedby="any"
      aria-labelledby="modelInfoDialogTitle"
      onCancel={(e) => {
        e.preventDefault();
        onClose?.();
      }}
      onClick={handleBackdropClick}
      className="today-modal w-[94dvw] bg-slate-900 text-slate-100 border border-slate-700/80 rounded-2xl shadow-2xl p-0 overflow-hidden m-auto"
    >
      <div className="flex flex-col min-h-0 max-h-[90dvh]">
        <div className="flex items-center justify-between px-5 py-4 bg-slate-950/90 border-b border-slate-800 shrink-0">
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-lg bg-blue-500/15 border border-blue-400/30 text-blue-400">
              <Info size={18} aria-hidden="true" />
            </div>
            <div>
              <h2 id="modelInfoDialogTitle" className="text-lg font-bold text-white">
                How Picks Are Built &amp; KenPom Setup
              </h2>
              <p className="text-xs text-slate-400">
                Plain-English guide to our projections, injury pricing, and turning KenPom on
              </p>
            </div>
          </div>

          <form method="dialog">
            <button
              type="submit"
              onClick={onClose}
              aria-label="Close model guide and KenPom setup"
              className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold border border-slate-700 cursor-pointer"
            >
              <X size={14} aria-hidden="true" />
              <span>Close</span>
            </button>
          </form>
        </div>

        <div className="p-5 overflow-y-auto space-y-5 text-xs leading-relaxed">
          {/* KenPom Setup & Import prioritized first when currently inactive */}
          <section className={`rounded-xl border p-4 space-y-4 ${
            kpActive ? 'border-emerald-500/30 bg-emerald-950/15' : 'border-amber-500/40 bg-amber-950/15'
          }`}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className={`font-bold uppercase tracking-wider ${kpActive ? 'text-emerald-300' : 'text-amber-300'}`}>
                1. KenPom Status &amp; Quick Activation
              </h3>
              <span className={`px-2.5 py-0.5 rounded-full text-[11px] font-bold border ${
                kpActive
                  ? 'bg-emerald-500/15 border-emerald-500/35 text-emerald-200'
                  : 'bg-amber-500/15 border-amber-500/35 text-amber-200'
              }`}>
                {statusLoading ? 'Checking...' : kpActive ? 'Active for 2026-27' : 'Off (Needs 2026-27 Data)'}
              </span>
            </div>

            {kenpomStatus && (
              <div className="rounded-lg border border-slate-800 bg-slate-950/75 p-3 space-y-1.5">
                <p className="text-slate-200 font-medium">{kenpomStatus.human_summary}</p>
                <p className="text-slate-400">{kenpomStatus.next_step}</p>
                <div className="flex flex-wrap gap-2 pt-1 text-[11px]">
                  <span className={`px-2 py-0.5 rounded border ${kpMethods.credentials || kpMethods.cookie ? 'border-emerald-500/35 bg-emerald-500/10 text-emerald-200' : 'border-slate-700 bg-slate-900 text-slate-400'}`}>
                    Web Login / Cookie: {kpMethods.credentials || kpMethods.cookie ? 'Set' : 'Not set'}
                  </span>
                </div>
                <p className="text-[11px] text-amber-200/80 pt-1">
                  Note on automation: GitHub Actions runs on shared cloud (Azure) IPs, which KenPom&apos;s Cloudflare firewall blocks with HTTP 403 even when email/password secrets are set. Click your Chrome bookmark while viewing kenpom.com, or paste/upload the table below.
                </p>
              </div>
            )}

            {/* Way 1: Using a normal kenpom.com Chrome bookmark (Cmd+A -> Cmd+C -> 1 click here) */}
            <div className="rounded-lg border border-emerald-500/35 bg-slate-950/60 p-3 space-y-2.5">
              <div className="font-semibold text-slate-100 flex items-center gap-1.5">
                <ClipboardPaste size={13} className="text-emerald-300" aria-hidden="true" />
                <span>Way 1: Sync Using Your Normal kenpom.com Chrome Bookmark (10 Seconds)</span>
              </div>
              <ol className="list-decimal list-inside space-y-1 text-[11px] text-slate-300">
                <li>
                  Open your{' '}
                  <a
                    href="https://kenpom.com/"
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-0.5 text-emerald-300 underline hover:text-emerald-200 font-semibold"
                  >
                    kenpom.com <ExternalLink size={10} aria-hidden="true" />
                  </a>{' '}
                  bookmark in Chrome and make sure you are logged in with the rankings table showing.
                </li>
                <li>
                  Press <kbd className="px-1.5 py-0.5 rounded bg-slate-800 border border-slate-700 text-slate-100 font-mono text-[10px]">Cmd + A</kbd> (select whole page), then{' '}
                  <kbd className="px-1.5 py-0.5 rounded bg-slate-800 border border-slate-700 text-slate-100 font-mono text-[10px]">Cmd + C</kbd> (copy).
                </li>
                <li>
                  Come back to this tab and click <strong>Paste &amp; Sync From Clipboard</strong> below:
                </li>
              </ol>
              <div className="flex flex-wrap items-center gap-2 pt-0.5">
                <a
                  href="https://kenpom.com/"
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-100 font-semibold text-xs"
                >
                  <ExternalLink size={12} aria-hidden="true" />
                  <span>1. Open kenpom.com</span>
                </a>
                {onPasteKenpomClipboard && (
                  <button
                    type="button"
                    onClick={async () => {
                      const ok = await onPasteKenpomClipboard();
                      if (ok) {
                        await fetchKenpomStatus();
                        onClose?.();
                      }
                    }}
                    className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-semibold text-xs cursor-pointer"
                  >
                    <ClipboardPaste size={13} aria-hidden="true" />
                    <span>2. Paste &amp; Sync From Clipboard</span>
                  </button>
                )}
              </div>
            </div>

            {/* Way 2: 1-Click Chrome Bookmarklet (zero copy/paste) */}
            <div className="rounded-lg border border-indigo-500/30 bg-slate-950/60 p-3 space-y-2.5">
              <div className="font-semibold text-slate-100 flex items-center gap-1.5">
                <Bookmark size={13} className="text-indigo-300" aria-hidden="true" />
                <span>Way 2: Automated 1-Click Chrome Bookmarklet (No Copy/Paste)</span>
              </div>
              <p className="text-[11px] text-amber-200/90">
                Note: A regular Chrome bookmark only saves a webpage address. To make a bookmark run the sync script automatically, drag the purple button below onto your Chrome Bookmarks Bar (<kbd className="px-1 py-0.5 rounded bg-slate-800 text-slate-200 font-mono text-[10px]">Cmd+Shift+B</kbd> to show it).
              </p>
              <ol id="kenpom-bookmarklet-hint" className="list-decimal list-inside space-y-1 text-[11px] text-slate-300">
                <li>
                  <strong>Drag</strong> the button <strong>Send KenPom to Basement Bets</strong> below up to your Chrome Bookmarks Bar (don&apos;t just click it here).
                </li>
                <li>Open <strong>kenpom.com</strong> in Chrome and log in.</li>
                <li>
                  <strong>While looking at kenpom.com</strong>, click that bookmark in your bar &mdash; it pulls the table and opens right back here.
                </li>
              </ol>
              <div className="flex flex-wrap items-center gap-2">
                <a
                  ref={setBookmarkletEl}
                  draggable
                  onClick={handleBookmarkletClick}
                  aria-describedby="kenpom-bookmarklet-hint"
                  className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-semibold text-xs cursor-grab active:cursor-grabbing"
                >
                  <Bookmark size={13} aria-hidden="true" />
                  <span>Send KenPom to Basement Bets</span>
                </a>
                <button
                  type="button"
                  onClick={handleCopyBookmarklet}
                  className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 font-semibold text-xs cursor-pointer"
                >
                  <Copy size={13} aria-hidden="true" />
                  <span>Copy Script URL Manually</span>
                </button>
              </div>
            </div>

            {/* Manual Fallback: Paste box or file upload */}
            <form onSubmit={handleKenpomUpload} className="rounded-lg border border-slate-800 bg-slate-950/60 p-3 space-y-3">
              <div className="font-semibold text-slate-200 flex items-center gap-1.5">
                <Upload size={13} className="text-slate-400" aria-hidden="true" />
                <span>Manual Paste Box or File Upload (.html / .csv / .tsv)</span>
              </div>
              <p id="kenpom-paste-hint" className="text-[11px] text-slate-400">
                Or paste with <kbd className="px-1 py-0.5 rounded bg-slate-800 text-slate-200 font-mono text-[10px]">Cmd+V</kbd> right here (or upload a saved <code className="text-slate-300">.html</code> / <code className="text-slate-300">.csv</code> file) and click Import KenPom.
              </p>

              <div>
                <label htmlFor="kenpom-paste-input" className="block text-[11px] font-semibold text-slate-300 mb-1">
                  Paste KenPom Ratings Table
                </label>
                <textarea
                  id="kenpom-paste-input"
                  rows={4}
                  value={pastedText}
                  onChange={(e) => setPastedText(e.target.value)}
                  aria-describedby="kenpom-paste-hint"
                  placeholder={"Rk\tTeam\tConf\tW-L\tNetRtg\tORtg\tDRtg\tAdjT\n1\tDuke\tACC\t3-0\t+31.4\t124.2\t92.8\t68.9"}
                  className="w-full rounded-lg bg-slate-900 border border-slate-700 p-2.5 text-[11px] font-mono text-slate-100 placeholder:text-slate-600"
                />
              </div>

              <div className="flex flex-wrap items-end justify-between gap-3">
                <div>
                  <label htmlFor="kenpom-csv-file" className="block text-[11px] font-semibold text-slate-300 mb-1">
                    Or Upload CSV / TSV / Saved KenPom .html File
                  </label>
                  <input
                    id="kenpom-csv-file"
                    ref={fileInputRef}
                    type="file"
                    accept=".csv,.tsv,.txt,.html,.htm"
                    onChange={(e) => setSelectedFile(e.target.files?.[0] || null)}
                    className="text-xs text-slate-300 file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border-0 file:bg-slate-800 file:text-slate-100 file:font-semibold hover:file:bg-slate-700"
                  />
                </div>
                <button
                  type="submit"
                  disabled={uploadState.uploading || (!pastedText.trim() && !selectedFile)}
                  className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white font-semibold text-xs cursor-pointer"
                >
                  <Upload size={13} aria-hidden="true" />
                  <span>{uploadState.uploading ? 'Importing...' : 'Import KenPom'}</span>
                </button>
              </div>
            </form>

            <div aria-live="polite">
              {uploadState.message && (
                <div
                  className={`flex items-center gap-2 rounded-lg px-3 py-2 text-xs ${
                    uploadState.status === 'success'
                      ? 'bg-emerald-500/15 border border-emerald-500/30 text-emerald-200'
                      : 'bg-rose-500/15 border border-rose-500/30 text-rose-200'
                  }`}
                >
                  {uploadState.status === 'success' ? (
                    <CheckCircle2 size={14} aria-hidden="true" />
                  ) : (
                    <AlertCircle size={14} aria-hidden="true" />
                  )}
                  <span>{uploadState.message}</span>
                </div>
              )}
            </div>
          </section>

          <section className="rounded-xl border border-slate-800 bg-slate-950/70 p-4 space-y-2">
            <h3 className="font-bold uppercase tracking-wider text-indigo-300">
              2. How Each Pick Is Built
            </h3>
            <p className="text-slate-300">
              Our independent projection engine blends team efficiency ratings from{' '}
              <strong>BartTorvik</strong>, <strong>KenPom</strong>, and <strong>Haslametrics</strong> alongside live
              sportsbook odds. Instead of just echoing Vegas, whenever multiple independent systems agree the line is
              off, Basement Bets boosts efficiency projection weight up to <strong>40%&ndash;60%</strong>.
            </p>
            <p className="text-slate-400">
              KenPom contributes pace-adjusted efficiency margins, true scoring-efficiency fair totals,{' '}
              <strong>Strength of Schedule (SOS / non-conference cupcake filters)</strong>, and{' '}
              <strong>Luck regression</strong>; Haslametrics adds recent <strong>momentum</strong> and game-to-game{' '}
              <strong>consistency</strong>. Plays are published when a side clears <strong>+2.0% EV</strong> (or{' '}
              <strong>1.1+ pts / +2.5% EV</strong> high-conviction override) with clean safety checks.
            </p>
          </section>

          <section className="rounded-xl border border-slate-800 bg-slate-950/70 p-4 space-y-2.5">
            <h3 className="font-bold uppercase tracking-wider text-sky-300">
              3. How Confidence Level Is Calculated (0&ndash;100 Score &amp; Tier)
            </h3>
            <p className="text-slate-300">
              Confidence does <strong>not</strong> measure raw payout size &mdash; it measures how likely the bet still
              wins after stressing our projection for real-game variance and model uncertainty:
            </p>
            <div className="space-y-2 text-slate-300">
              <div className="rounded-lg border border-slate-800 bg-slate-900/75 p-2.5">
                <span className="font-semibold text-white">Step 1 &mdash; Variance-Adjusted &amp; Calibrated Win Probability:</span>{' '}
                We compute the probability of covering or clearing the total using our fair line (&mu;) and game-specific
                standard deviation (&sigma;, widened for fast tempo, heavy roster turnover, 18+ point blowouts, injuries,
                and line-movement uncertainty), subtract whole-number push odds, and apply PAVA probability calibration.
                When projection-uncertainty bounds are enabled, we use a conservative{' '}
                <strong>10th-percentile lower bound</strong> from 600 Monte Carlo trials instead of the midpoint.
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                <div className="rounded-lg border border-emerald-500/30 bg-emerald-950/20 p-2.5">
                  <div className="font-bold text-emerald-300">HIGH (Score 80&ndash;95)</div>
                  <div className="text-[11px] text-slate-300 mt-0.5">
                    Calibrated win chance <strong>&ge; 55.0%</strong> with positive expected value (+EV). Comfortably
                    clears the 52.4% break-even bar at -110 odds (scales from 80 at 55% up to 95 at 65%+).
                  </div>
                </div>
                <div className="rounded-lg border border-amber-500/30 bg-amber-950/20 p-2.5">
                  <div className="font-bold text-amber-300">MEDIUM (Score 55&ndash;78)</div>
                  <div className="text-[11px] text-slate-300 mt-0.5">
                    Calibrated win chance between <strong>52.0% and 54.9%</strong> with positive +EV. Solid playable
                    edge, scaled linearly from 55 to 78.
                  </div>
                </div>
                <div className="rounded-lg border border-slate-700 bg-slate-900/80 p-2.5">
                  <div className="font-bold text-slate-300">LOW (Score 15&ndash;49)</div>
                  <div className="text-[11px] text-slate-400 mt-0.5">
                    Win chance <strong>&lt; 52.0%</strong> (or non-positive EV). Prevents risky longshots with big payout
                    odds from being labeled High Confidence.
                  </div>
                </div>
              </div>
              <p className="text-[11px] text-slate-400">
                Any adverse steam move, book-to-book outlier, 18+ pt blowout variance guard, or unpriced key injury
                widens uncertainty (&sigma;), which compresses win probability toward 50% and automatically lowers the
                confidence score.
              </p>
            </div>
          </section>

          <section className="rounded-xl border border-slate-800 bg-slate-950/70 p-4 space-y-3">
            <h3 className="font-bold uppercase tracking-wider text-emerald-300">
              4. Data Sources Overview
            </h3>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
              {['torvik', 'kenpom', 'haslametrics', 'odds', 'action_splits'].map((src) => {
                const row = bySource[src];
                const ok = String(row?.status || '').toLowerCase() === 'ok';
                const cnt = row?.last_row_count ?? row?.row_count;
                return (
                  <div key={src} className="rounded-lg border border-slate-800 bg-slate-900/90 px-3 py-2">
                    <div className="font-bold text-[11px] text-slate-300">{FEED_LABELS[src] || src}</div>
                    <div className={`mt-0.5 font-semibold ${ok ? 'text-emerald-300' : 'text-amber-300'}`}>
                      {ok ? 'Active' : src === 'kenpom' ? 'Needs 2026-27 Update' : 'Needs Refresh'}
                      {cnt != null ? ` (${cnt} rows)` : ''}
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
        </div>
      </div>
    </dialog>
  );
};

export default ModelLogicDialog;
