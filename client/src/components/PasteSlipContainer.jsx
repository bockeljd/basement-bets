import React, { useState, useEffect } from 'react';
import { supabase } from '../api/supabase';
import api from '../api/axios';
import { AlertCircle, CheckCircle2, Loader2, Save, X } from 'lucide-react';
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

    // Core State
    const [sportsbook, setSportsbook] = useState('DK');
    const [rawText, setRawText] = useState('');
    const [parsedData, setParsedData] = useState(null);
    const [error, setError] = useState(null);
    const [bankrollAccount, setBankrollAccount] = useState('Main');
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
            // Determine endpoint based on selected sportsbook
            // Note: User selects DK/FD in dropdown. We use that.
            const provider = sportsbook === 'DK' ? 'draftkings' : 'fanduel';
            const endpoint = `/api/sync/${provider}`;

            const response = await api.post(endpoint, {
                account_name: bankrollAccount
            });

            if (response.data.status === 'success') {
                setBatchResults(response.data.bets);
                setSyncParams({ provider: response.data.source });
            } else {
                setError(response.data.message || 'Sync failed');
            }
        } catch (err) {
            setError(err.response?.data?.message || 'Failed to sync. Ensure Chrome is installed and you logged in.');
        } finally {
            setIsSyncing(false);
        }
    };

    const handleSaveBatch = async () => {
        if (!batchResults) return;
        setIsSaving(true);

        try {
            // Loop and save
            let successCount = 0;
            for (const bet of batchResults) {
                await api.post('/api/bets/manual', {
                    ...bet,
                    // If scraper didn't set provider, use syncParams
                    provider: bet.provider || syncParams?.provider || 'Unknown',
                    sportsbook: sportsbook, // Use UI selection? Scraper usually sets provider text.
                    account_id: bankrollAccount
                });
                successCount++;
            }

            setBatchResults(null);
            if (onSaveSuccess) onSaveSuccess();
            alert(`Successfully saved ${successCount} bets!`);
            onClose();

        } catch (err) {
            setError('Failed to save some bets. Please try again.');
        } finally {
            setIsSaving(false);
        }
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

            setParsedData(response.data);
        } catch (err) {
            setError(err.response?.data?.detail || err.response?.data?.message || 'Failed to parse slip. Please check the format.');
        } finally {
            setIsParsing(false);
        }
    };

    const handleSave = async () => {
        if (!parsedData) return;

        setIsSaving(true);
        try {
            await api.post('/api/bets/manual', {
                ...parsedData,
                sportsbook,
                account_id: bankrollAccount // UI uses 'Main'/'Test' for now
            });

            setRawText('');
            setParsedData(null);
            if (onSaveSuccess) onSaveSuccess();
        } catch (err) {
            setError(err.response?.data?.detail || 'Failed to save bet.');
        } finally {
            setIsSaving(false);
        }
    };

    return (
        <div className="bg-slate-900/50 border border-slate-800 rounded-xl p-6 backdrop-blur-sm">
            <div className="flex items-center justify-between mb-6">
                <h2 className="text-xl font-semibold text-white">Paste or Sync Bet Slip</h2>
                <button
                    onClick={() => { setRawText(''); setParsedData(null); setBatchResults(null); setError(null); onClose(); }}
                    className="text-slate-400 hover:text-white transition-colors"
                >
                    <X className="w-5 h-5" />
                </button>
            </div>

            <div className="space-y-4">
                <div className="grid grid-cols-2 gap-4">
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
                            <option value="Main">Main Bankroll</option>
                            <option value="Test">Testing Account</option>
                        </select>
                    </div>
                </div>

                {!parsedData && !batchResults && (
                    <div className="flex gap-3 mb-2">
                        <button
                            onClick={handleSync}
                            disabled={isSyncing || isParsing}
                            className="flex-1 bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 disabled:opacity-50 text-white font-bold py-3 rounded-lg transition-all flex items-center justify-center gap-2 shadow-lg"
                        >
                            {isSyncing ? <Loader2 className="w-5 h-5 animate-spin" /> : <Save className="w-5 h-5" />}
                            {isSyncing ? 'Waiting for Login...' : `Sync from ${sportsbook === 'DK' ? 'DraftKings' : 'FanDuel'}`}
                        </button>
                    </div>
                )}

                {isSyncing && (
                    <div className="space-y-3 animate-in fade-in slide-in-from-top-2">
                        <div className="bg-blue-900/20 border border-blue-500/30 p-3 rounded-lg text-blue-200 text-sm">
                            <p className="font-bold mb-1">FanDuel API Sync</p>
                            <p className="text-xs opacity-80">
                                1. Open DevTools (F12) > Network Tab.<br />
                                2. Refresh "Settled Bets" page.<br />
                                3. Right Click request > Copy as cURL.<br />
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

                {isSyncing && !showCurlInput && (
                    <div className="bg-blue-900/20 border border-blue-500/30 p-4 rounded-lg text-blue-200 text-sm flex items-center gap-3">
                        <Loader2 className="w-5 h-5 animate-spin shrink-0" />
                        <div>
                            <p className="font-bold">Browser Opened!</p>
                            <p>Please log in to the betting site in the new window. We'll scrape the history automatically once you're in.</p>
                        </div>
                    </div>
                )}

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

                {error && (
                    <div className="flex items-start gap-3 p-4 bg-red-900/20 border border-red-900/50 rounded-lg text-red-200 text-sm">
                        <AlertCircle className="w-5 h-5 shrink-0" />
                        <p>{error}</p>
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
