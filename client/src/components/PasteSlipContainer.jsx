import React, { useState, useEffect } from 'react';
import api from '../api/axios';
import { AlertCircle, CheckCircle2, Loader2, Save, X } from 'lucide-react';
import SportsbookSyncHub from './SportsbookSyncHub';
import { clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

function cn(...inputs) {
    return twMerge(clsx(inputs));
}

const SPORTSBOOKS = [
    { id: 'DK', name: 'DraftKings' },
    { id: 'FD', name: 'FanDuel' }
];

export function PasteSlipContainer({ onSaveSuccess, onClose }) {
    const [batchResults, setBatchResults] = useState(null);
    const [isSyncing, setIsSyncing] = useState(false);
    const [syncParams, setSyncParams] = useState(null); // { provider: 'DraftKings' } or similar for batch save context

    // On-demand worker UX
    const [queuedSync, setQueuedSync] = useState(null); // { jobId, provider }

    // Core State
    const [sportsbook, setSportsbook] = useState('DK');

    // Entry type: bet slip vs manual transaction line
    const [entryType, setEntryType] = useState('BET'); // BET | TXN
    const [txnType, setTxnType] = useState('Deposit'); // Deposit | Withdrawal
    const [txnAmount, setTxnAmount] = useState('');
    const [txnDate, setTxnDate] = useState('');
    const [txnDesc, setTxnDesc] = useState('');

    const [rawText, setRawText] = useState('');
    const [parsedData, setParsedData] = useState(null);
    const [error, setError] = useState(null);
    const [bankrollAccount, setBankrollAccount] = useState('Main'); // Main | User2
    const [isSaving, setIsSaving] = useState(false);
    const [isParsing, setIsParsing] = useState(false);

    // FanDuel cURL State
    const [showCurlInput, setShowCurlInput] = useState(false);
    const [curlText, setCurlText] = useState('');

    const handleFDSync = async () => {
        setIsSyncing(true);
        setError(null);
        setBatchResults(null);

        try {
            const response = await api.post('/api/sync/fanduel/token', {
                curl_or_token: curlText
            });

            if (response.data.status === 'success') {
                // Since this endpoint AUTO-SAVES (per my previous backend change), we might not have 'bets' to review?
                // Wait, backend returns: {"status": "success", "bets_fetched": len(bets), "bets_saved": saved_count}
                // It does NOT return the bets array.
                // So we should just show success message and close?
                // Or maybe fetch them to show?
                // For now, simple success.
                alert(`Successfully synced ${response.data.bets_fetched} bets!`);
                if (onSaveSuccess) onSaveSuccess();
                onClose();
            } else {
                setError(response.data.message || 'Sync failed');
            }
        } catch (err) {
            setError(err.response?.data?.detail || 'Failed to sync with FanDuel API.');
        } finally {
            setIsSyncing(false);
        }
    };

    const handleSync = async () => {
        setIsSyncing(true);
        setError(null);
        setBatchResults(null);
        setParsedData(null);

        try {
            // Background sync (Mac worker). Queue a job and poll status.
            const provider = sportsbook === 'DK' ? 'draftkings' : 'fanduel';
            const body = { provider };
            if (provider === 'draftkings') {
                // Map UI choice to account_id
                body.account_id = (bankrollAccount === 'Secondary' || bankrollAccount === 'User2') ? 'User2' : 'Main';
            }
            const q = await api.post('/api/sync/request', body);

            const jobId = q.data?.job?.id;
            if (!jobId) {
                throw new Error('Failed to queue sync job');
            }

            setQueuedSync({ jobId, provider });

            // Poll status for up to ~60s
            const start = Date.now();
            while (Date.now() - start < 60000) {
                await new Promise(r => setTimeout(r, 2000));
                const st = await api.get('/api/sync/status');
                const jobs = st.data?.jobs || [];
                const j = jobs.find(x => String(x.id) === String(jobId));
                if (!j) continue;

                if (j.status === 'DONE') {
                    const fetched = j.meta?.bets_fetched ?? null;
                    const saved = j.meta?.bets_saved ?? null;
                    alert(`Sync complete (${provider}).${saved !== null ? ` Saved ${saved} bets.` : ''}${fetched !== null ? ` Fetched ${fetched}.` : ''}`);
                    if (onSaveSuccess) onSaveSuccess();
                    onClose();
                    return;
                }
                if (j.status === 'NEEDS_LOGIN') {
                    setError(`Login required on ${provider}. Open the sportsbook on the Mac worker and log in, then retry.`);
                    return;
                }
                if (j.status === 'ERROR') {
                    setError(j.error || 'Sync failed');
                    return;
                }
            }

            setError('Sync queued but not finished yet. Run the Mac worker command below, then click Re-check status.');
        } catch (err) {
            setError(err.response?.data?.message || 'Failed to sync. Ensure Chrome is installed and you logged in.');
        } finally {
            setIsSyncing(false);
        }
    };

    const handleSaveBatch = async () => {
        if (!batchResults) return;
        setIsSaving(true);
        setError(null);

        const failures = [];
        let successCount = 0;

        for (let i = 0; i < batchResults.length; i++) {
            const bet = batchResults[i];
            try {
                await api.post('/api/bets/manual', {
                    ...bet,
                    // If scraper didn't set provider, use syncParams
                    provider: bet.provider || syncParams?.provider || (sportsbook === 'DK' ? 'DraftKings' : 'FanDuel') || 'Unknown',
                    sportsbook: sportsbook,
                    account_id: bankrollAccount
                });
                successCount++;
            } catch (err) {
                const msg = err?.response?.data?.detail || err?.response?.data?.message || err?.message || 'Save failed';
                failures.push({
                    idx: i + 1,
                    event_name: bet?.event_name || bet?.description || '—',
                    status: bet?.status || '—',
                    odds: bet?.price?.american ?? bet?.odds ?? '—',
                    message: msg,
                });
            }
        }

        if (successCount > 0) {
            if (onSaveSuccess) onSaveSuccess();
        }

        if (failures.length === 0) {
            setBatchResults(null);
            alert(`Successfully saved ${successCount} bets!`);
            onClose();
        } else {
            // Keep batchResults so user can retry; show a helpful summary.
            const preview = failures.slice(0, 6)
                .map(f => `#${f.idx} ${f.event_name} (${f.status}) odds=${f.odds}: ${f.message}`)
                .join('\n');
            setError(`Saved ${successCount}/${batchResults.length} bets. ${failures.length} failed:\n${preview}${failures.length > 6 ? `\n…and ${failures.length - 6} more.` : ''}`);
        }

        setIsSaving(false);
    };

    const handleParse = async () => {
        if (!rawText.trim()) return;

        setIsParsing(true);
        setError(null);
        setParsedData(null);
        setBatchResults(null);

        try {
            // API call to LLM Parser
            const response = await api.post('/api/parse-slip', {
                raw_text: rawText,
                sportsbook,
                account_name: bankrollAccount
            });

            if (response.data?.bets && Array.isArray(response.data.bets)) {
                setBatchResults(response.data.bets);
                setSyncParams({ provider: sportsbook === 'DK' ? 'DraftKings' : 'FanDuel' });
                setParsedData(null);
            } else {
                setParsedData(response.data);
            }
        } catch (err) {
            setError(err.response?.data?.detail || err.response?.data?.message || 'Failed to parse slip. Please check the format.');
        } finally {
            setIsParsing(false);
        }
    };

    const handleSave = async () => {
        setIsSaving(true);
        setError(null);
        try {
            if (entryType === 'TXN') {
                const amt = Number(txnAmount);
                if (!amt || amt <= 0) {
                    throw new Error('Amount must be > 0');
                }
                await api.post('/api/transactions/manual', {
                    provider: sportsbook === 'DK' ? 'DraftKings' : 'FanDuel',
                    // account_id is kept for UI consistency; backend currently ignores it.
                    account_id: bankrollAccount,
                    type: txnType,
                    amount: amt,
                    date: txnDate || undefined,
                    description: txnDesc || undefined,
                });

                // reset
                setTxnAmount('');
                setTxnDate('');
                setTxnDesc('');
                if (onSaveSuccess) onSaveSuccess();
                return;
            }

            // BET
            if (!parsedData) return;

            await api.post('/api/bets/manual', {
                ...parsedData,
                sportsbook,
                account_id: bankrollAccount
            });

            setRawText('');
            setParsedData(null);
            if (onSaveSuccess) onSaveSuccess();
        } catch (err) {
            const msg = err?.response?.data?.detail || err?.message || 'Failed to save entry.';
            setError(msg);
        } finally {
            setIsSaving(false);
        }
    };

    return (
        <div className="bg-slate-900/50 border border-slate-800 rounded-xl p-6 backdrop-blur-sm">
            <div className="flex items-center justify-between mb-6">
                <h2 className="text-xl font-semibold text-white">Add Entry</h2>
                <button
                    onClick={() => { setRawText(''); setParsedData(null); setBatchResults(null); setError(null); onClose(); }}
                    className="text-slate-400 hover:text-white transition-colors"
                >
                    <X className="w-5 h-5" />
                </button>
            </div>

            <div className="space-y-4">
                <div className="grid grid-cols-2 gap-4">
                    <div className="col-span-2">
                        <label className="block text-sm font-medium text-slate-400 mb-1">Entry Type</label>
                        <div className="inline-flex gap-1 p-1 rounded-2xl bg-slate-900/40 border border-slate-700/40">
                            <button
                                type="button"
                                onClick={() => { setEntryType('BET'); setParsedData(null); setBatchResults(null); setError(null); }}
                                className={`px-3 py-2 rounded-xl text-sm font-semibold transition ${entryType === 'BET' ? 'bg-slate-800/70 text-slate-100 shadow-sm ring-1 ring-white/10' : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/40'}`}
                            >
                                Bet
                            </button>
                            <button
                                type="button"
                                onClick={() => { setEntryType('TXN'); setRawText(''); setParsedData(null); setBatchResults(null); setError(null); }}
                                className={`px-3 py-2 rounded-xl text-sm font-semibold transition ${entryType === 'TXN' ? 'bg-slate-800/70 text-slate-100 shadow-sm ring-1 ring-white/10' : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/40'}`}
                            >
                                Deposit / Withdrawal
                            </button>
                            <button
                                type="button"
                                onClick={() => { setEntryType('SYNC'); setRawText(''); setParsedData(null); setBatchResults(null); setError(null); }}
                                className={`px-3 py-2 rounded-xl text-sm font-semibold transition ${entryType === 'SYNC' ? 'bg-indigo-600/80 text-white shadow-sm ring-1 ring-indigo-400/40' : 'text-indigo-300 hover:text-indigo-200 hover:bg-slate-800/40'}`}
                            >
                                Auto-Sync / CSV
                            </button>
                        </div>
                    </div>
                    {entryType !== 'SYNC' && (
                        <>
                            <div>
                                <label className="block text-sm font-medium text-slate-400 mb-1">Sportsbook</label>
                                <select
                                    value={sportsbook}
                                    onChange={(e) => setSportsbook(e.target.value)}
                                    className="w-full bg-slate-800 border border-slate-700 text-white rounded-lg px-3 py-2 focus:ring-2 focus:ring-blue-500 outline-none"
                                >
                                    {SPORTSBOOKS.map(sb => (
                                        <option key={sb.id} value={sb.id}>{sb.name}</option>
                                    ))}
                                </select>
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-slate-400 mb-1">Bankroll Account</label>
                                <select
                                    value={bankrollAccount}
                                    onChange={(e) => setBankrollAccount(e.target.value)}
                                    className="w-full bg-slate-800 border border-slate-700 text-white rounded-lg px-3 py-2 focus:ring-2 focus:ring-blue-500 outline-none"
                                >
                                    <option value="Main">Primary</option>
                                    <option value="User2">Secondary</option>
                                </select>
                            </div>
                        </>
                    )}
                </div>

                {entryType === 'SYNC' && (
                    <div className="pt-2">
                        <SportsbookSyncHub
                            onSyncComplete={() => {
                                if (onSaveSuccess) onSaveSuccess();
                            }}
                        />
                    </div>
                )}

                {entryType === 'BET' && isSyncing && sportsbook === 'FD' && (
                    <div className="space-y-3 animate-in fade-in slide-in-from-top-2">
                        <div className="bg-blue-900/20 border border-blue-500/30 p-3 rounded-lg text-blue-200 text-sm">
                            <p className="font-bold mb-1">FanDuel API Sync</p>
                            <p className="text-xs opacity-80">
                                1. Open DevTools (F12) &gt; Network Tab.<br />
                                2. Refresh "Settled Bets" page.<br />
                                3. Right Click request &gt; Copy as cURL.<br />
                                4. Paste below.
                            </p>
                        </div>
                        <textarea
                            value={curlText}
                            onChange={(e) => setCurlText(e.target.value)}
                            placeholder="Paste cURL command here..."
                            className="w-full h-24 bg-slate-800 border border-slate-700 text-white rounded-lg px-3 py-2 text-xs font-mono focus:ring-2 focus:ring-blue-500 outline-none resize-none"
                        />
                        <div className="flex gap-2">
                            <button
                                onClick={() => setShowCurlInput(false)}
                                className="px-4 py-2 bg-slate-700 hover:bg-slate-600 text-white rounded-lg text-sm"
                            >
                                Cancel
                            </button>
                            <button
                                onClick={handleFDSync}
                                disabled={isSyncing || !curlText.trim()}
                                className="flex-1 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white font-bold py-2 rounded-lg text-sm flex items-center justify-center gap-2"
                            >
                                {isSyncing ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Run Sync'}
                            </button>
                        </div>
                    </div>
                )}

                {entryType === 'BET' && isSyncing && !showCurlInput && sportsbook === 'DK' && (
                    <div className="bg-emerald-900/20 border border-emerald-500/30 p-4 rounded-lg text-emerald-100 text-sm flex items-center gap-3">
                        <Loader2 className="w-5 h-5 animate-spin shrink-0" />
                        <div>
                            <p className="font-bold">DraftKings sync queued</p>
                            <p>
                                A DraftKings window will open on the Mac worker if login/location verification is needed.
                                Please log in there (Primary or Secondary), and we'll ingest your settled bets automatically.
                            </p>
                        </div>
                    </div>
                )}

                {entryType === 'TXN' && (
                    <div className="bg-slate-800/40 border border-slate-700 rounded-lg p-4 space-y-3">
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                            <div>
                                <label className="block text-sm font-medium text-slate-400 mb-1">Type</label>
                                <select
                                    value={txnType}
                                    onChange={(e) => setTxnType(e.target.value)}
                                    className="w-full bg-slate-800 border border-slate-700 text-white rounded-lg px-3 py-2 focus:ring-2 focus:ring-blue-500 outline-none"
                                >
                                    <option value="Deposit">Deposit</option>
                                    <option value="Withdrawal">Withdrawal</option>
                                </select>
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-slate-400 mb-1">Amount ($)</label>
                                <input
                                    value={txnAmount}
                                    onChange={(e) => setTxnAmount(e.target.value)}
                                    placeholder="e.g. 100"
                                    className="w-full bg-slate-800 border border-slate-700 text-white rounded-lg px-3 py-2 focus:ring-2 focus:ring-blue-500 outline-none"
                                />
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-slate-400 mb-1">Date (YYYY-MM-DD)</label>
                                <input
                                    value={txnDate}
                                    onChange={(e) => setTxnDate(e.target.value)}
                                    placeholder="YYYY-MM-DD"
                                    className="w-full bg-slate-800 border border-slate-700 text-white rounded-lg px-3 py-2 focus:ring-2 focus:ring-blue-500 outline-none"
                                />
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-slate-400 mb-1">Description (optional)</label>
                                <input
                                    value={txnDesc}
                                    onChange={(e) => setTxnDesc(e.target.value)}
                                    placeholder={`Manual ${txnType}`}
                                    className="w-full bg-slate-800 border border-slate-700 text-white rounded-lg px-3 py-2 focus:ring-2 focus:ring-blue-500 outline-none"
                                />
                            </div>
                        </div>

                        <button
                            onClick={handleSave}
                            disabled={isSaving}
                            className="w-full bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-700 disabled:text-slate-500 text-white font-semibold py-3 rounded-lg transition-colors flex items-center justify-center gap-2"
                        >
                            {isSaving ? <Loader2 className="w-5 h-5 animate-spin" /> : <Save className="w-5 h-5" />}
                            Add {txnType}
                        </button>

                        <div className="text-[11px] text-slate-500">
                            Note: this records a cashflow line item for reconciliation with sportsbook snapshots.
                        </div>
                    </div>
                )}

                {entryType === 'BET' && (
                    <>
                        <div>
                            {!batchResults && !showCurlInput && (
                                <>
                                    <label className="block text-sm font-medium text-slate-400 mb-1">Or Paste Slip Text</label>
                                    <textarea
                                        value={rawText}
                                        onChange={(e) => setRawText(e.target.value)}
                                        placeholder="Paste your slip here..."
                                        className="w-full h-32 bg-slate-800 border border-slate-700 text-white rounded-lg px-3 py-2 focus:ring-2 focus:ring-blue-500 outline-none resize-none placeholder:text-slate-600"
                                    />
                                </>
                            )}
                        </div>

                        {!parsedData && !batchResults && !showCurlInput && (
                            <button
                                onClick={handleParse}
                                disabled={isParsing || isSyncing || !rawText.trim()}
                                className="w-full bg-blue-600 hover:bg-blue-500 disabled:bg-slate-700 disabled:text-slate-500 text-white font-semibold py-3 rounded-lg transition-colors flex items-center justify-center gap-2"
                            >
                                {isParsing ? <Loader2 className="w-5 h-5 animate-spin" /> : 'Parse Slip'}
                            </button>
                        )}
                    </>
                )}

                {error && (
                    <div className="flex items-start gap-3 p-4 bg-red-900/20 border border-red-900/50 rounded-lg text-red-200 text-sm">
                        <AlertCircle className="w-5 h-5 shrink-0" />
                        <p>{error}</p>
                    </div>
                )}

                {queuedSync && (
                    <div className="p-4 bg-slate-800/60 border border-slate-700 rounded-lg text-slate-200 text-sm space-y-2">
                        <div className="text-xs uppercase tracking-wider text-slate-500 font-black">Run Mac worker (on demand)</div>
                        <div className="text-xs text-slate-400">
                            A sync job is queued for <span className="text-slate-200 font-bold">{queuedSync.provider}</span> (job #{queuedSync.jobId}).
                            Run this on the Mac to process it, then click <span className="font-bold">Re-check status</span>.
                        </div>
                        <pre className="text-[11px] bg-black/30 border border-slate-700 rounded p-3 overflow-x-auto">cd ~/clawd/repos/basement-bets
                            source .venv311/bin/activate
                            python scripts/sync_worker.py --once</pre>
                        <div className="flex gap-2">
                            <button
                                onClick={async () => {
                                    try {
                                        await navigator.clipboard.writeText(`cd ~/clawd/repos/basement-bets\nsource .venv311/bin/activate\npython scripts/sync_worker.py --once\n`);
                                    } catch (e) {
                                        // ignore
                                    }
                                }}
                                className="px-3 py-2 bg-slate-700 hover:bg-slate-600 text-white rounded-lg text-xs font-bold"
                            >
                                Copy command
                            </button>
                            <button
                                onClick={async () => {
                                    try {
                                        const st = await api.get('/api/sync/status');
                                        const jobs = st.data?.jobs || [];
                                        const j = jobs.find(x => String(x.id) === String(queuedSync.jobId));
                                        if (!j) {
                                            setError('Job not found yet. Try again in a few seconds.');
                                            return;
                                        }
                                        if (j.status === 'DONE') {
                                            const fetched = j.meta?.bets_fetched ?? null;
                                            const saved = j.meta?.bets_saved ?? null;
                                            alert(`Sync complete (${queuedSync.provider}).${saved !== null ? ` Saved ${saved} bets.` : ''}${fetched !== null ? ` Fetched ${fetched}.` : ''}`);
                                            if (onSaveSuccess) onSaveSuccess();
                                            onClose();
                                            return;
                                        }
                                        if (j.status === 'NEEDS_LOGIN') {
                                            setError(`Login required on ${queuedSync.provider}. Open the sportsbook on the Mac worker and log in, then retry.`);
                                            return;
                                        }
                                        if (j.status === 'ERROR') {
                                            setError(j.error || 'Sync failed');
                                            return;
                                        }
                                        setError(`Job status: ${j.status}`);
                                    } catch (e) {
                                        setError('Failed to check sync status.');
                                    }
                                }}
                                className="px-3 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-bold"
                            >
                                Re-check status
                            </button>
                            <button
                                onClick={() => setQueuedSync(null)}
                                className="ml-auto px-3 py-2 bg-slate-900/40 hover:bg-slate-900 text-slate-200 border border-slate-700 rounded-lg text-xs font-bold"
                            >
                                Hide
                            </button>
                        </div>
                    </div>
                )}

                {batchResults && (
                    <div className="space-y-4 animate-in fade-in slide-in-from-top-4 duration-300">
                        <div className="bg-slate-800/80 border border-emerald-500/30 rounded-lg p-5">
                            <h3 className="text-lg font-bold text-white mb-2 flex items-center gap-2">
                                <CheckCircle2 className="w-5 h-5 text-emerald-400" />
                                Sync Successful!
                            </h3>
                            <p className="text-slate-300 text-sm mb-4">Found <strong>{batchResults.length}</strong> bets from {syncParams?.provider}. Ready to import.</p>

                            <div className="max-h-64 overflow-y-auto space-y-2 pr-2 mb-4 custom-scrollbar">
                                {batchResults.map((bet, idx) => (
                                    <div key={idx} className="bg-slate-900/50 p-2 rounded border border-slate-700 text-xs">
                                        <div className="flex justify-between font-bold text-slate-300">
                                            <span>{bet.selection}</span>
                                            <span>{bet.wager > 0 ? `$${bet.wager}` : ''}</span>
                                        </div>
                                        <div className="flex justify-between text-slate-500 mt-1">
                                            <span>{bet.description}</span>
                                            <span>{bet.date}</span>
                                        </div>
                                    </div>
                                ))}
                            </div>

                            <div className="flex gap-3">
                                <button
                                    onClick={() => setBatchResults(null)}
                                    className="flex-1 bg-slate-700 hover:bg-slate-600 text-white font-semibold py-3 rounded-lg"
                                >
                                    Cancel
                                </button>
                                <button
                                    onClick={handleSaveBatch}
                                    disabled={isSaving}
                                    className="flex-[2] bg-emerald-600 hover:bg-emerald-500 text-white font-semibold py-3 rounded-lg flex items-center justify-center gap-2"
                                >
                                    {isSaving ? <Loader2 className="w-5 h-5 animate-spin" /> : <Save className="w-5 h-5" />}
                                    Import All {batchResults.length} Bets
                                </button>
                            </div>
                        </div>
                    </div>
                )}

                {parsedData && (
                    <div className="space-y-4 animate-in fade-in slide-in-from-top-4 duration-300">
                        <div className="p-4 bg-slate-800/80 border border-slate-700 rounded-lg space-y-3">
                            <div className="flex items-center justify-between">
                                <span className="text-xs font-bold uppercase tracking-wider text-slate-500">Review Details</span>
                                <div className={cn(
                                    "px-2 py-0.5 rounded text-[10px] font-bold uppercase",
                                    parsedData.confidence > 0.9 ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20" : "bg-amber-500/10 text-amber-400 border border-amber-500/20"
                                )}>
                                    {Math.round(parsedData.confidence * 100)}% Confidence
                                </div>
                            </div>

                            <div className="grid grid-cols-2 gap-x-8 gap-y-3">
                                <DetailItem label="Matchup" value={parsedData.event_name} />
                                <DetailItem label="Sport" value={parsedData.sport || 'Unknown'} />
                                <DetailItem label="Market" value={parsedData.market_type} />
                                <DetailItem label="Selection" value={parsedData.selection} />
                                <DetailItem label="Odds" value={parsedData.price?.american > 0 ? `+${parsedData.price?.american}` : parsedData.price?.american} />
                                <DetailItem label="Stake" value={`$${parsedData.stake}`} />
                                <DetailItem label="Status" value={parsedData.status || 'PENDING'} />
                                <DetailItem label="Date/Time" value={parsedData.placed_at} />
                            </div>
                        </div>

                        {parsedData.possible_duplicate && (
                            <div className="flex items-start gap-3 p-3 bg-amber-900/20 border border-amber-900/50 rounded-lg text-amber-200 text-sm">
                                <AlertCircle className="w-5 h-5 shrink-0" />
                                <div>
                                    <p className="font-semibold">Possible Duplicate</p>
                                    <p className="text-xs text-amber-200/70">A similar bet was found on this date.</p>
                                </div>
                            </div>
                        )}

                        <div className="flex gap-3">
                            <button
                                onClick={() => setParsedData(null)}
                                className="flex-1 bg-slate-800 hover:bg-slate-700 text-white font-semibold py-3 rounded-lg transition-colors"
                                disabled={isSaving}
                            >
                                Edit
                            </button>
                            <button
                                onClick={handleSave}
                                disabled={isSaving}
                                className="flex-[2] bg-emerald-600 hover:bg-emerald-500 text-white font-semibold py-3 rounded-lg transition-colors flex items-center justify-center gap-2"
                            >
                                {isSaving ? <Loader2 className="w-5 h-5 animate-spin" /> : <Save className="w-5 h-5" />}
                                Confirm & Save
                            </button>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}

function DetailItem({ label, value }) {
    return (
        <div>
            <span className="block text-[10px] font-bold uppercase tracking-wider text-slate-500 mb-0.5">{label}</span>
            <span className="block text-sm text-white font-medium truncate">{value}</span>
        </div>
    );
}
