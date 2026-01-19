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
    const [sportsbook, setSportsbook] = useState('DK');
    const [bankrollAccount, setBankrollAccount] = useState('Main');
    const [rawText, setRawText] = useState('');
    const [isParsing, setIsParsing] = useState(false);
    const [parsedData, setParsedData] = useState(null);
    const [error, setError] = useState(null);
    const [isSaving, setIsSaving] = useState(false);

    const handleParse = async () => {
        if (!rawText.trim()) return;

        setIsParsing(true);
        setError(null);
        setParsedData(null);

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
                <h2 className="text-xl font-semibold text-white">Paste Bet Slip</h2>
                <button
                    onClick={() => { setRawText(''); setParsedData(null); setError(null); onClose(); }}
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

                <div>
                    <label className="block text-sm font-medium text-slate-400 mb-1">Paste Slip Text</label>
                    <textarea
                        value={rawText}
                        onChange={(e) => setRawText(e.target.value)}
                        placeholder="Paste your slip here..."
                        className="w-full h-32 bg-slate-800 border border-slate-700 text-white rounded-lg px-3 py-2 focus:ring-2 focus:ring-blue-500 outline-none resize-none placeholder:text-slate-600"
                    />
                </div>

                {!parsedData && (
                    <button
                        onClick={handleParse}
                        disabled={isParsing || !rawText.trim()}
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
