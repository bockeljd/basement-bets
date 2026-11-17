import React, { useEffect, useId, useMemo, useState } from 'react';
import {
  Bookmark,
  CheckCircle2,
  Clock,
  Copy,
  FileSpreadsheet,
  KeyRound,
  RefreshCw,
  AlertCircle,
  Loader2,
  Terminal,
} from 'lucide-react';
import api from '../api/axios';
import {
  buildDraftKingsBookmarklet,
  buildFanDuelBookmarklet,
} from '../utils/sportsbookBookmarklets';

/**
 * Unified 3-Layer Sportsbook Sync Hub:
 *  1) 1-Click Chrome Bookmarklets (FanDuel + DraftKings, Open + Settled + Balance)
 *  2) CSV Statement Uploader / Paste (Bets, Deposits, Withdrawals, Closing Balance)
 *  3) FanDuel Token / Mac Background Sync Queue + live status
 */
export default function SportsbookSyncHub({ onSyncComplete, initialMethod = 'bookmarklet' }) {
  const formTitleId = useId();
  const csvBookGroupId = useId();
  const csvFileId = useId();
  const csvPasteId = useId();
  const fdTokenInputId = useId();
  const accountLegendId = useId();

  const [activeMethod, setActiveMethod] = useState(initialMethod);
  const [accountId, setAccountId] = useState('Main');
  const [statusBanner, setStatusBanner] = useState(null); // { tone: 'ok'|'err'|'info', text: string }

  // Bookmarklet DOM refs (React forbids raw javascript: URLs in JSX static warnings cleanly via ref)
  const [fdLinkEl, setFdLinkEl] = useState(null);
  const [dkLinkEl, setDkLinkEl] = useState(null);

  const appOrigin = typeof window !== 'undefined' ? window.location.origin : 'https://basement-bets.vercel.app';
  const fdBookmarklet = useMemo(() => buildFanDuelBookmarklet(appOrigin, accountId), [appOrigin, accountId]);
  const dkBookmarklet = useMemo(() => buildDraftKingsBookmarklet(appOrigin, accountId), [appOrigin, accountId]);

  useEffect(() => {
    if (fdLinkEl && fdBookmarklet) fdLinkEl.setAttribute('href', fdBookmarklet);
  }, [fdLinkEl, fdBookmarklet]);

  useEffect(() => {
    if (dkLinkEl && dkBookmarklet) dkLinkEl.setAttribute('href', dkBookmarklet);
  }, [dkLinkEl, dkBookmarklet]);

  // CSV State
  const [csvSportsbook, setCsvSportsbook] = useState('Auto');
  const [csvFile, setCsvFile] = useState(null);
  const [csvText, setCsvText] = useState('');
  const [isImportingCsv, setIsImportingCsv] = useState(false);

  // FanDuel Token State
  const [fdTokenInput, setFdTokenInput] = useState('');
  const [isSyncingFdToken, setIsSyncingFdToken] = useState(false);

  // Mac Worker Queue State
  const [syncJobs, setSyncJobs] = useState([]);
  const [jobsLoading, setJobsLoading] = useState(false);
  const [queuingProvider, setQueuingProvider] = useState(null);

  const fetchSyncStatus = async () => {
    setJobsLoading(true);
    try {
      const res = await api.get('/api/sync/status');
      setSyncJobs(Array.isArray(res.data?.jobs) ? res.data.jobs : []);
    } catch {
      // ignore quietly on status poll
    } finally {
      setJobsLoading(false);
    }
  };

  useEffect(() => {
    if (activeMethod === 'worker') {
      fetchSyncStatus();
    }
  }, [activeMethod]);

  const copyText = async (val, msg) => {
    try {
      await navigator.clipboard.writeText(val);
      setStatusBanner({ tone: 'ok', text: msg });
    } catch {
      setStatusBanner({ tone: 'err', text: 'Clipboard access blocked. Copy manually from the box.' });
    }
  };

  const handleBookmarkletClick = (e, bookName) => {
    e.preventDefault();
    setStatusBanner({
      tone: 'info',
      text: `Drag "${bookName}" onto your Chrome Bookmarks Bar (Cmd+Shift+B). Open ${bookName} -> My Bets and click it there.`,
    });
  };

  const handleCsvSubmit = async (e) => {
    e.preventDefault();
    if (!csvFile && !csvText.trim()) {
      setStatusBanner({ tone: 'err', text: 'Select a .csv/.tsv file or paste statement rows first.' });
      return;
    }

    setIsImportingCsv(true);
    setStatusBanner(null);
    try {
      const payloadText = csvFile ? await csvFile.text() : csvText;
      if (!String(payloadText || '').trim()) {
        setStatusBanner({ tone: 'err', text: 'The selected CSV file is empty.' });
        return;
      }
      const res = await api.post('/api/bets/import-csv', {
        csv_text: payloadText,
        sportsbook: csvSportsbook,
        account_id: accountId,
      });

      const d = res.data || {};
      const parts = [
        `${d.provider || 'Sportsbook'} CSV imported (${d.account_id === 'User2' ? 'Secondary' : 'Primary'})`,
        `${d.bets_saved ?? 0} bets saved (${d.bets_inserted ?? 0} new, ${d.bets_updated ?? 0} updated)`,
      ];
      if (d.transactions_saved > 0) parts.push(`${d.transactions_saved} deposits/withdrawals`);
      if (d.closing_balance != null) parts.push(`closing balance $${Number(d.closing_balance).toFixed(2)}`);

      setStatusBanner({ tone: 'ok', text: parts.join(' • ') });
      setCsvFile(null);
      setCsvText('');
      if (onSyncComplete) onSyncComplete(d);
    } catch (err) {
      setStatusBanner({
        tone: 'err',
        text: err.response?.data?.detail || err.message || 'CSV import failed.',
      });
    } finally {
      setIsImportingCsv(false);
    }
  };

  const handleFdTokenSubmit = async (e) => {
    e.preventDefault();
    if (!fdTokenInput.trim()) {
      setStatusBanner({ tone: 'err', text: 'Paste a FanDuel X-Auth-Token or Copy as cURL command first.' });
      return;
    }
    setIsSyncingFdToken(true);
    setStatusBanner(null);
    try {
      const res = await api.post('/api/sync/fanduel/token', {
        curl_or_token: fdTokenInput,
        account_id: accountId,
        include_open: true,
      });
      const d = res.data || {};
      setStatusBanner({
        tone: 'ok',
        text: `FanDuel synced: ${d.bets_saved ?? 0} bets saved (${d.bets_inserted ?? 0} new, ${d.bets_updated ?? 0} updated out of ${d.bets_fetched ?? 0} open+settled).`,
      });
      setFdTokenInput('');
      if (onSyncComplete) onSyncComplete(d);
    } catch (err) {
      setStatusBanner({
        tone: 'err',
        text: err.response?.data?.detail || err.message || 'FanDuel token sync failed.',
      });
    } finally {
      setIsSyncingFdToken(false);
    }
  };

  const handleQueueMacSync = async (provider) => {
    setQueuingProvider(provider);
    setStatusBanner(null);
    try {
      const res = await api.post('/api/sync/request', {
        provider,
        account_id: accountId,
      });
      const job = res.data?.job;
      setStatusBanner({
        tone: 'ok',
        text: `${provider === 'draftkings' ? 'DraftKings' : 'FanDuel'} Mac sync queued (Job #${job?.id || '?'}). Your Mac LaunchAgent or sync worker will process it shortly.`,
      });
      await fetchSyncStatus();
    } catch (err) {
      setStatusBanner({
        tone: 'err',
        text: err.response?.data?.detail || 'Could not queue Mac sync job.',
      });
    } finally {
      setQueuingProvider(null);
    }
  };

  const latestNeedsAuth = syncJobs.find((j) => ['NEEDS_LOGIN', 'NEEDS_AUTH'].includes(String(j.status || '').toUpperCase()));

  return (
    <section aria-labelledby={formTitleId} className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 id={formTitleId} className="text-sm font-bold text-slate-100">
            Sync Actual Bets from DraftKings &amp; FanDuel
          </h3>
          <p className="text-xs text-slate-400">
            Pull open and settled slips, deposits/withdrawals, and wallet balances directly into Actuals.
          </p>
        </div>

        <fieldset className="flex items-center gap-2 border border-slate-700/70 rounded-lg px-2.5 py-1.5 bg-slate-950/60">
          <legend id={accountLegendId} className="sr-only">
            Account Profile
          </legend>
          <span className="text-[11px] font-semibold text-slate-400 mr-1" aria-hidden="true">
            Account:
          </span>
          {[
            { id: 'Main', label: 'Primary' },
            { id: 'User2', label: 'Secondary' },
          ].map((opt) => (
            <label
              key={opt.id}
              className={`inline-flex items-center gap-1.5 text-xs font-semibold px-2 py-1 rounded cursor-pointer transition ${
                accountId === opt.id
                  ? 'bg-emerald-600/20 text-emerald-300 border border-emerald-500/40'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <input
                type="radio"
                name="sync_account_id"
                value={opt.id}
                checked={accountId === opt.id}
                onChange={() => setAccountId(opt.id)}
                className="accent-emerald-500"
              />
              <span>{opt.label}</span>
            </label>
          ))}
        </fieldset>
      </div>

      {/* Method Selector */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2" role="tablist" aria-label="Sync Methods">
        {[
          { key: 'bookmarklet', label: '1-Click Chrome Sync', icon: Bookmark },
          { key: 'csv', label: 'CSV Statement', icon: FileSpreadsheet },
          { key: 'fdtoken', label: 'FanDuel Token', icon: KeyRound },
          { key: 'worker', label: 'Mac Auto-Worker', icon: Clock },
        ].map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={activeMethod === key}
            onClick={() => setActiveMethod(key)}
            className={`min-h-[44px] flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-xs font-semibold border transition cursor-pointer ${
              activeMethod === key
                ? 'bg-indigo-600 text-white border-indigo-500 shadow'
                : 'bg-slate-800/70 text-slate-300 border-slate-700 hover:bg-slate-800'
            }`}
          >
            <Icon className="w-3.5 h-3.5 shrink-0" aria-hidden="true" />
            <span>{label}</span>
          </button>
        ))}
      </div>

      {statusBanner && (
        <div
          role="status"
          aria-live="polite"
          className={`flex items-start gap-2.5 p-3 rounded-lg text-xs border ${
            statusBanner.tone === 'ok'
              ? 'bg-emerald-950/40 border-emerald-500/40 text-emerald-200'
              : statusBanner.tone === 'err'
              ? 'bg-red-950/40 border-red-500/40 text-red-200'
              : 'bg-blue-950/40 border-blue-500/40 text-blue-200'
          }`}
        >
          {statusBanner.tone === 'ok' ? (
            <CheckCircle2 className="w-4 h-4 shrink-0 text-emerald-400 mt-0.5" aria-hidden="true" />
          ) : (
            <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" aria-hidden="true" />
          )}
          <span>{statusBanner.text}</span>
        </div>
      )}

      {/* TAB 1: 1-Click Chrome Bookmarklets */}
      {activeMethod === 'bookmarklet' && (
        <div className="bg-slate-800/40 border border-slate-700/80 rounded-xl p-4 space-y-4">
          <div className="text-xs text-slate-300 space-y-1">
            <p className="font-semibold text-white">
              Fastest zero-password method (same 1-click method as KenPom):
            </p>
            <ol className="list-decimal list-inside space-y-1 text-slate-400">
              <li>
                Drag either button below to your Chrome Bookmarks Bar (
                <kbd className="px-1 py-0.5 bg-slate-900 rounded border border-slate-700 text-[10px]">Cmd+Shift+B</kbd>).
              </li>
              <li>Log into DraftKings or FanDuel in Chrome and open <strong>My Bets</strong> (Open or Settled).</li>
              <li>Click the bookmark once &mdash; your bets &amp; current wallet balance sync back here automatically.</li>
            </ol>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="p-3 rounded-lg bg-slate-900/70 border border-blue-500/30 space-y-2">
              <div className="text-xs font-bold text-blue-300">FanDuel Open + Settled + Balance</div>
              <div className="flex flex-wrap gap-2">
                <a
                  ref={setFdLinkEl}
                  draggable
                  onClick={(e) => handleBookmarkletClick(e, 'FanDuel')}
                  className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold cursor-grab active:cursor-grabbing"
                >
                  <Bookmark className="w-3.5 h-3.5" aria-hidden="true" />
                  <span>Sync FanDuel</span>
                </a>
                <button
                  type="button"
                  onClick={() => copyText(fdBookmarklet, 'FanDuel bookmarklet URL copied. Paste it as a new Chrome bookmark URL.')}
                  className="inline-flex items-center gap-1 px-2.5 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs border border-slate-700"
                >
                  <Copy className="w-3.5 h-3.5" aria-hidden="true" />
                  <span>Copy URL</span>
                </button>
              </div>
            </div>

            <div className="p-3 rounded-lg bg-slate-900/70 border border-emerald-500/30 space-y-2">
              <div className="text-xs font-bold text-emerald-300">DraftKings Open + Settled + Balance</div>
              <div className="flex flex-wrap gap-2">
                <a
                  ref={setDkLinkEl}
                  draggable
                  onClick={(e) => handleBookmarkletClick(e, 'DraftKings')}
                  className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold cursor-grab active:cursor-grabbing"
                >
                  <Bookmark className="w-3.5 h-3.5" aria-hidden="true" />
                  <span>Sync DraftKings</span>
                </a>
                <button
                  type="button"
                  onClick={() => copyText(dkBookmarklet, 'DraftKings bookmarklet URL copied. Paste it as a new Chrome bookmark URL.')}
                  className="inline-flex items-center gap-1 px-2.5 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs border border-slate-700"
                >
                  <Copy className="w-3.5 h-3.5" aria-hidden="true" />
                  <span>Copy URL</span>
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* TAB 2: CSV Statement Upload */}
      {activeMethod === 'csv' && (
        <form onSubmit={handleCsvSubmit} className="bg-slate-800/40 border border-slate-700/80 rounded-xl p-4 space-y-4">
          <fieldset className="space-y-1.5">
            <legend id={csvBookGroupId} className="text-xs font-semibold text-slate-300">
              Statement Source
            </legend>
            <div className="flex flex-wrap gap-2" role="radiogroup" aria-labelledby={csvBookGroupId}>
              {[
                { v: 'Auto', label: 'Auto-Detect' },
                { v: 'DraftKings', label: 'DraftKings' },
                { v: 'FanDuel', label: 'FanDuel' },
              ].map((opt) => (
                <label
                  key={opt.v}
                  className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold border cursor-pointer ${
                    csvSportsbook === opt.v
                      ? 'bg-emerald-600/20 border-emerald-500/50 text-emerald-300'
                      : 'bg-slate-900 border-slate-700 text-slate-300'
                  }`}
                >
                  <input
                    type="radio"
                    name="csv_sportsbook"
                    value={opt.v}
                    checked={csvSportsbook === opt.v}
                    onChange={() => setCsvSportsbook(opt.v)}
                    className="accent-emerald-500"
                  />
                  <span>{opt.label}</span>
                </label>
              ))}
            </div>
          </fieldset>

          <div className="flex flex-col gap-1.5">
            <label htmlFor={csvFileId} className="text-xs font-semibold text-slate-300">
              Upload CSV / TSV File (Bet History or Account Financial Statement)
            </label>
            <input
              id={csvFileId}
              name="statement_csv_file"
              type="file"
              accept=".csv,.tsv,.txt,text/csv"
              onChange={(e) => setCsvFile(e.target.files?.[0] || null)}
              className="block w-full min-h-[44px] text-xs text-slate-300 file:mr-3 file:py-2 file:px-3 file:rounded-lg file:border-0 file:text-xs file:font-semibold file:bg-indigo-600 file:text-white hover:file:bg-indigo-500 bg-slate-900 border border-slate-700 rounded-lg p-1.5"
            />
            <span className="text-[11px] text-slate-400">
              Imports settled &amp; open bets, deposits, withdrawals, and ending balance without duplicates.
            </span>
          </div>

          <div className="flex flex-col gap-1.5">
            <label htmlFor={csvPasteId} className="text-xs font-semibold text-slate-300">
              Or Paste CSV Text Directly (Optional)
            </label>
            <textarea
              id={csvPasteId}
              name="statement_csv_text"
              value={csvText}
              onChange={(e) => setCsvText(e.target.value)}
              rows={3}
              autocorrect="off"
              autocapitalize="none"
              spellCheck={false}
              placeholder="Date,Type,Description,Amount,Balance..."
              className="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-xs text-white font-mono focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-500"
            />
          </div>

          <button
            type="submit"
            disabled={isImportingCsv}
            className="w-full min-h-[44px] bg-emerald-600 hover:bg-emerald-500 disabled:opacity-60 text-white font-bold text-xs rounded-lg py-2.5 flex items-center justify-center gap-2 transition"
          >
            {isImportingCsv ? <Loader2 className="w-4 h-4 animate-spin" /> : <FileSpreadsheet className="w-4 h-4" />}
            <span>{isImportingCsv ? 'Importing Statement...' : 'Import Statement CSV'}</span>
          </button>
        </form>
      )}

      {/* TAB 3: FanDuel API Token / cURL */}
      {activeMethod === 'fdtoken' && (
        <form onSubmit={handleFdTokenSubmit} className="bg-slate-800/40 border border-slate-700/80 rounded-xl p-4 space-y-3">
          <div className="flex flex-col gap-1.5">
            <label htmlFor={fdTokenInputId} className="text-xs font-semibold text-slate-300">
              FanDuel X-Auth-Token or Copy as cURL (from Network -&gt; getBetHistory)
            </label>
            <textarea
              id={fdTokenInputId}
              name="fanduel_curl_or_token"
              value={fdTokenInput}
              onChange={(e) => setFdTokenInput(e.target.value)}
              rows={4}
              autocorrect="off"
              autocapitalize="none"
              spellCheck={false}
              placeholder="Paste X-Auth-Token or right-click getBetHistory -> Copy as cURL..."
              className="w-full bg-slate-900 border border-slate-700 rounded-lg p-3 text-xs text-white font-mono focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500"
            />
            <span className="text-[11px] text-slate-400">
              Pulls your last 50 open + 100 settled FanDuel bets and saves the token for Mac auto-sync.
            </span>
          </div>

          <button
            type="submit"
            disabled={isSyncingFdToken}
            className="w-full min-h-[44px] bg-blue-600 hover:bg-blue-500 disabled:opacity-60 text-white font-bold text-xs rounded-lg py-2.5 flex items-center justify-center gap-2 transition"
          >
            {isSyncingFdToken ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
            <span>{isSyncingFdToken ? 'Fetching FanDuel Bets...' : 'Sync Open & Settled FanDuel Bets'}</span>
          </button>
        </form>
      )}

      {/* TAB 4: Mac Background Auto-Worker */}
      {activeMethod === 'worker' && (
        <div className="bg-slate-800/40 border border-slate-700/80 rounded-xl p-4 space-y-4">
          {latestNeedsAuth && (
            <div className="p-3 rounded-lg bg-amber-950/50 border border-amber-500/40 text-xs text-amber-200 flex items-start gap-2">
              <AlertCircle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
              <div>
                <strong>2FA / Login expired ({latestNeedsAuth.provider}):</strong> Run{' '}
                <code className="bg-slate-900 px-1 py-0.5 rounded font-mono">./venv/bin/python scripts/dk_login_helper.py</code>{' '}
                on your Mac once to refresh your Chrome session, or use the 1-Click Bookmarklet tab above.
              </div>
            </div>
          )}

          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={queuingProvider !== null}
              onClick={() => handleQueueMacSync('draftkings')}
              className="flex-1 min-h-[44px] bg-emerald-600 hover:bg-emerald-500 disabled:opacity-60 text-white text-xs font-bold px-3 py-2 rounded-lg"
            >
              {queuingProvider === 'draftkings' ? 'Queuing DK...' : 'Queue DraftKings Sync'}
            </button>
            <button
              type="button"
              disabled={queuingProvider !== null}
              onClick={() => handleQueueMacSync('fanduel')}
              className="flex-1 min-h-[44px] bg-blue-600 hover:bg-blue-500 disabled:opacity-60 text-white text-xs font-bold px-3 py-2 rounded-lg"
            >
              {queuingProvider === 'fanduel' ? 'Queuing FD...' : 'Queue FanDuel Sync'}
            </button>
            <button
              type="button"
              onClick={fetchSyncStatus}
              disabled={jobsLoading}
              className="min-h-[44px] px-3 py-2 bg-slate-900 hover:bg-slate-800 text-slate-300 border border-slate-700 rounded-lg text-xs font-semibold flex items-center gap-1.5"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${jobsLoading ? 'animate-spin' : ''}`} />
              <span>Refresh</span>
            </button>
          </div>

          {/* LaunchAgent 1-time Mac setup */}
          <div className="rounded-lg border border-slate-700 bg-slate-950/60 p-3 space-y-1.5">
            <div className="text-xs font-bold text-slate-200 flex items-center gap-1.5">
              <Terminal className="w-3.5 h-3.5 text-sky-400" />
              <span>One-time Mac Background Auto-Sync Setup:</span>
            </div>
            <div className="flex flex-wrap items-center justify-between gap-2 bg-slate-900 border border-slate-800 rounded px-2.5 py-2">
              <code className="text-[11px] font-mono text-sky-300">./venv/bin/python scripts/install_mac_sync_agent.py install</code>
              <button
                type="button"
                onClick={() =>
                  copyText(
                    './venv/bin/python scripts/install_mac_sync_agent.py install',
                    'LaunchAgent install command copied. Run once in Terminal inside Basement Bets.'
                  )
                }
                className="text-xs px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700"
              >
                Copy
              </button>
            </div>
          </div>

          {syncJobs.length > 0 && (
            <div className="space-y-1.5">
              <div className="text-[11px] uppercase tracking-wider font-bold text-slate-400">Recent Worker Jobs</div>
              <div className="space-y-1 max-h-40 overflow-y-auto pr-1">
                {syncJobs.slice(0, 6).map((j) => (
                  <div key={j.id} className="flex items-center justify-between text-xs bg-slate-900/70 border border-slate-800 rounded px-2.5 py-1.5">
                    <span className="font-semibold text-slate-200">
                      #{j.id} • {String(j.provider || '').toUpperCase()}
                    </span>
                    <span className="text-slate-400 truncate max-w-[160px]" title={j.error || ''}>
                      {j.meta?.bets_saved != null ? `Saved ${j.meta.bets_saved}` : j.error || ''}
                    </span>
                    <span
                      className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                        j.status === 'DONE'
                          ? 'bg-emerald-500/20 text-emerald-300'
                          : ['NEEDS_LOGIN', 'NEEDS_AUTH', 'ERROR'].includes(j.status)
                          ? 'bg-red-500/20 text-red-300'
                          : 'bg-amber-500/20 text-amber-300'
                      }`}
                    >
                      {j.status}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
