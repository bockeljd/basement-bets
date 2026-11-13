import React, { useEffect, useState } from 'react';
import api from '../api/axios';
import { Trash, DollarSign, Activity, Pencil, CheckCircle2 } from 'lucide-react';
import EditBetModal from './EditBetModal';
import SportAuditorModal from './SportAuditorModal';
import ManualAddBetModal from './ManualAddBetModal';
// SevenDayTrendSparkline removed per request.

// Extracted from App.jsx. Keep behavior identical; dependencies are passed as props when needed.

export default function TransactionView({ bets, setBets, financials, reconciliation, loading, formatCurrency, formatDateMDY, showOpenBets = true, showFinancials = true }) {
    const [openBets, setOpenBets] = useState([]);
    const [openBetsLoading, setOpenBetsLoading] = useState(false);
    const [openBetsError, setOpenBetsError] = useState(null);
    // Row selection disabled (checkbox column removed)
    const [isBulkUpdating, setIsBulkUpdating] = useState(false);

    const SkeletonRow = () => (
        <tr className="animate-pulse border-b border-gray-800/20">
            <td className="px-3 py-4 w-[40px]"><div className="h-4 bg-gray-800/50 rounded w-4" /></td>
            <td className="px-3 py-4 w-[84px]"><div className="h-2 bg-gray-800/50 rounded w-16" /></td>
            <td className="px-3 py-4 w-[80px]"><div className="h-4 bg-gray-800/50 rounded w-14" /></td>
            <td className="px-3 py-4 w-[64px]"><div className="h-4 bg-gray-800/50 rounded w-10" /></td>
            <td className="px-3 py-4 w-[70px]"><div className="h-4 bg-gray-800/50 rounded w-12" /></td>
            <td className="px-3 py-4 w-[200px]"><div className="h-4 bg-gray-800/50 rounded w-40" /></td>
            <td className="px-3 py-4 w-[60px] text-right"><div className="h-4 bg-gray-800/50 rounded w-8 ml-auto" /></td>
            <td className="px-3 py-4 w-[70px] text-right"><div className="h-4 bg-gray-800/50 rounded w-12 ml-auto" /></td>
            <td className="px-3 py-4 w-[64px] text-center"><div className="h-5 bg-gray-800/50 rounded w-16 mx-auto" /></td>
            <td className="px-3 py-4 w-[76px] text-right"><div className="h-4 bg-gray-800/50 rounded w-14 ml-auto" /></td>
        </tr>
    );

    const [filters, setFilters] = useState({
        date: "",
        sportsbook: "All",
        account: "All",
        sport: "All",
        type: "All",
        selection: "",
        status: "All"
    });

    // Removed: 7-day profit trend sparkline

    // Bulk selection actions removed (checkbox column removed)


    // Load open bets (pending/open) into a separate section
    useEffect(() => {
        const load = async () => {
            try {
                setOpenBetsLoading(true);
                setOpenBetsError(null);
                const res = await api.get('/api/bets/open');
                setOpenBets(res.data || []);
            } catch (e) {
                setOpenBetsError('Failed to load open bets');
            } finally {
                setOpenBetsLoading(false);
            }
        };
        load();
    }, []);

    // Optional prefill from other charts (e.g., Performance scatter)
    useEffect(() => {
        try {
            const raw = localStorage.getItem('txn_prefill');
            if (!raw) return;
            const p = JSON.parse(raw);
            localStorage.removeItem('txn_prefill');
            setFilters(f => ({
                ...f,
                sport: p?.sport ? String(p.sport).toUpperCase() : f.sport,
                type: p?.type ? String(p.type) : f.type,
                sportsbook: p?.sportsbook ? String(p.sportsbook) : f.sportsbook,
                selection: p?.selection ? String(p.selection) : f.selection,
            }));
        } catch (e) { }
    }, []);

    const [showManualAdd, setShowManualAdd] = useState(false);
    const [expandedBook, setExpandedBook] = useState(null);
    const [showEdit, setShowEdit] = useState(false);
    const [editBet, setEditBet] = useState(null);
    const [editNote, setEditNote] = useState('');

    // Auditor UI (sport mismatches)
    const [showAudit, setShowAudit] = useState(false);
    const [auditLoading, setAuditLoading] = useState(false);
    const [auditItems, setAuditItems] = useState([]);

    const [manualBet, setManualBet] = useState({
        sportsbook: "DraftKings",
        account_id: "Main", // Primary=Main, Secondary=User2
        sport: "NFL",
        market_type: "Straight",
        event_name: "",
        selection: "",
        odds: "",
        stake: "",
        status: "LOST",
        placed_at: new Date().toISOString().slice(0, 10)
    });

    // Extract unique options for dropdowns - keep "All" at top
    const sportsbooks = ["All", ...[...new Set(bets.map(b => b.provider).filter(Boolean))].sort()];
    const sports = ["All", ...[...new Set(bets.map(b => b.sport).filter(Boolean))].sort()];
    const types = ["All", ...[...new Set(bets.map(b => b.bet_type).filter(Boolean))].sort()];
    const [sortConfig, setSortConfig] = useState({ key: 'date', direction: 'descending' });

    const acctLabel = (b) => ((b?.account_id === 'User2' || String(b?.account_id || '').toLowerCase() === 'secondary') ? 'Secondary' : 'Primary');
    const [error, setError] = useState(null);
    const [isUpdating, setIsUpdating] = useState(false);

    const requestSort = (key) => {
        let direction = 'ascending';
        if (sortConfig.key === key && sortConfig.direction === 'ascending') {
            direction = 'descending';
        }
        setSortConfig({ key, direction });
    };

    const getSortIcon = (name) => {
        if (sortConfig.key !== name) return <div className="w-3 h-3 inline-block ml-1 opacity-20">↕</div>;
        return sortConfig.direction === 'ascending' ?
            <div className="w-3 h-3 inline-block ml-1">↑</div> :
            <div className="w-3 h-3 inline-block ml-1">↓</div>;
    };

    const handleSettle = async (betId, status) => {
        setIsUpdating(true);
        try {
            await api.patch(`/api/bets/${betId}/settle`, { status });
            // For now, reload to get fresh stats
            window.location.reload();
        } catch (err) {
            console.error("Settle Error:", err);
            alert("Failed to settle bet.");
        } finally {
            setIsUpdating(false);
        }
    };

    const handleEditSave = async () => {
        if (!editBet?.id) return;
        setIsUpdating(true);
        try {
            const payload = {
                provider: editBet.provider,
                account_id: editBet.account_id,
                date: editBet.date,
                sport: editBet.sport,
                bet_type: editBet.bet_type,
                wager: editBet.wager,
                odds: editBet.odds,
                profit: editBet.profit,
                status: editBet.status,
                description: editBet.description,
                selection: editBet.selection,
                // also persist event_text if we can infer it from the updated fields
                event_text: computeEventText(editBet) || undefined,
                update_note: editNote,
            };

            await api.patch(`/api/bets/${editBet.id}`, payload);

            // Optimistically update the row in-memory so the UI reflects the save immediately.
            if (typeof setBets === 'function') {
                setBets((prev) => (prev || []).map((b) => {
                    if (Number(b.id) !== Number(editBet.id)) return b;
                    const date = String(editBet.date || '').slice(0, 10);
                    const next = {
                        ...b,
                        provider: editBet.provider,
                        date,
                        sort_date: date,
                        sport: editBet.sport,
                        bet_type: editBet.bet_type,
                        wager: editBet.wager === '' ? b.wager : Number(editBet.wager),
                        odds: editBet.odds === '' ? b.odds : Number(editBet.odds),
                        profit: editBet.profit === '' ? b.profit : Number(editBet.profit),
                        status: editBet.status,
                        description: editBet.description,
                        selection: editBet.selection,
                    };
                    try {
                        next.event_text = computeEventText(next) || next.event_text;
                    } catch (e) { }
                    return next;
                }));
            }

            // Reliable way to refresh aggregates (tiles, performance summaries, etc.)
            // without risking stale cached stats.
            // After reload, land back on Actuals → Transactions.
            try { localStorage.setItem('nav_after_save', 'transactions'); } catch (e) { }
            window.location.reload();

            // (below won't run, but keep structure safe if we ever remove reload)
            // setShowEdit(false);
            // setEditBet(null);
            // setEditNote('');
        } catch (err) {
            console.error('Edit save failed', err);
            alert('Failed to update bet.');
        } finally {
            setIsUpdating(false);
        }
    };

    const handleDelete = async (betId) => {
        if (!confirm("Are you sure you want to delete this bet?")) return;
        setIsUpdating(true);
        try {
            await api.delete(`/api/bets/${betId}`);

            // Refresh everything (open bets list + balances/tiles)
            try { localStorage.setItem('nav_after_save', 'transactions'); } catch (e) { }
            window.location.reload();
        } catch (err) {
            console.error("Delete Error:", err);
            alert("Failed to delete bet. " + (err?.response?.data?.detail || err?.response?.data?.message || err?.message || ''));

        } finally {
            setIsUpdating(false);
        }
    };

    const runAudit = async () => {
        setAuditLoading(true);
        try {
            // Audit the full Transactions history (not just a recent slice)
            const { data } = await api.get('/api/audit/bets/sport-mismatches', { params: { days: 3650, limit: 5000 } });
            setAuditItems(data?.items || []);
            setShowAudit(true);
        } catch (err) {
            console.error('Audit failed', err);
            const msg = err?.response?.data?.detail || err?.response?.data?.message || err?.message || '';
            alert(`Audit failed. ${msg}`);
        } finally {
            setAuditLoading(false);
        }
    };

    const applyAuditFix = async (item) => {
        const betId = item?.bet_id;
        const sport = item?.chosen_sport || item?.suggested_sport;
        if (!betId || !sport) return;
        try {
            await api.post(`/api/audit/bets/${betId}/apply-sport`, { sport });

            // Update UI row immediately
            if (typeof setBets === 'function') {
                setBets((prev) => (prev || []).map((b) => {
                    if (Number(b.id) !== Number(betId)) return b;
                    return { ...b, sport };
                }));
            }

            // Remove from audit list
            setAuditItems((prev) => (prev || []).filter((x) => Number(x.bet_id) !== Number(betId)));
        } catch (err) {
            console.error('Apply audit fix failed', err);
            alert('Failed to apply fix.');
        }
    };

    const submitManualBet = async () => {
        setIsUpdating(true);
        try {
            const american = manualBet.odds ? parseInt(manualBet.odds, 10) : null;
            const stake = manualBet.stake ? parseFloat(manualBet.stake) : 0;

            await api.post('/api/bets/manual', {
                sportsbook: manualBet.sportsbook,
                account_id: manualBet.account_id,
                sport: manualBet.sport,
                market_type: manualBet.market_type,
                event_name: manualBet.event_name,
                selection: manualBet.selection,
                price: { american },
                stake,
                status: manualBet.status,
                placed_at: manualBet.placed_at,
                raw_text: 'manual-ui'
            });

            // easiest: refresh to pick up the inserted bet + refreshed analytics
            // After reload, land back on Actuals → Transactions
            try { localStorage.setItem('nav_after_save', 'transactions'); } catch (e) { }
            window.location.reload();
        } catch (err) {
            console.error('Manual bet save failed', err);
            alert('Failed to add bet. Check required fields.');
        } finally {
            setIsUpdating(false);
        }
    };

    const statuses = ['All', 'PENDING', 'WON', 'LOST', 'PUSH'];

    const computeEventText = (bet) => {
        // Compute a clean matchup string ignoring any pre-existing event_text.
        const sources = [bet?.raw_text, bet?.description, bet?.selection].filter(Boolean).map(s => String(s));
        const cleanSide = (x) => {
            let s = String(x || '').trim();
            s = s.replace(/\s+[+\-−–]\d+(?:\.\d+)?\b.*$/, '').trim();
            s = s.replace(/\s+(over|under)\s*\d+(?:\.\d+)?\b.*$/i, '').trim();
            s = s.replace(/\b([A-Za-z]{3,})\s+\1\b/gi, '$1').trim();
            // Strip pipes
            s = s.split('|')[0].trim();
            return s;
        };

        // Prefer explicit matchup line
        for (const src of sources) {
            for (const ln of String(src).split(/\n/).map(l => l.trim()).filter(Boolean)) {
                if (ln.includes('@') || /\b(vs\.?|versus)\b/i.test(ln)) {
                    const mm = ln.match(/(.+?)\s*(?:@|vs\.?|versus)\s*(.+)/i);
                    if (mm) {
                        const a = cleanSide(mm[1]);
                        const b = cleanSide(mm[2]);
                        if (a && b) return `${a} @ ${b}`;
                    }
                }
            }
        }

        // Fallback to combined regex
        const raw = sources.join(' \n ').replace(/\s+/g, ' ').trim();
        if (!raw) return '';
        const m = raw.match(/([A-Za-z0-9\.'\-\s&]+?)\s*(?:@|vs\.?|versus)\s*([A-Za-z0-9\.'\-\s&]+?)(?:\s*\||\s*$)/i);
        if (m) {
            const a = cleanSide(m[1]);
            const b = cleanSide(m[2]);
            if (a && b) return `${a} @ ${b}`;
        }
        return '';
    };

    const extractEvent = (bet) => {
        // UI display function
        if (bet?.event_text) return String(bet.event_text);
        return computeEventText(bet);
    };
    const filtered = bets.filter(b => {
        // Filter out internal Wallet Transfers
        if ((b.description || "").toLowerCase().includes("wallet transfer")) return false;

        const matchDate = b.date.includes(filters.date);
        const matchSportsbook = filters.sportsbook === "All" || b.provider === filters.sportsbook;
        const matchAccount = filters.account === "All" || acctLabel(b) === filters.account;
        const matchSport = filters.sport === "All" || b.sport === filters.sport;
        const matchType = filters.type === "All" || b.bet_type === filters.type;
        const matchSelection = (b.selection || b.description || "").toLowerCase().includes(filters.selection.toLowerCase());
        const matchStatus = filters.status === "All" || b.status === filters.status;
        return matchDate && matchSportsbook && matchAccount && matchSport && matchType && matchSelection && matchStatus;
    });

    const sortedBets = React.useMemo(() => {
        let sortableItems = [...filtered];
        if (sortConfig.key !== null) {
            sortableItems.sort((a, b) => {
                let aValue = a[sortConfig.key];
                let bValue = b[sortConfig.key];

                // Special handling for date: use sort_date for proper chronological sort
                if (sortConfig.key === 'date') {
                    aValue = a.sort_date || a.date || "";
                    bValue = b.sort_date || b.date || "";
                }

                // Special handling for selection fallback
                if (sortConfig.key === 'selection') {
                    aValue = a.selection || a.description || "";
                    bValue = b.selection || b.description || "";
                }

                // Handle string comparisons
                if (typeof aValue === 'string') aValue = aValue.toLowerCase();
                if (typeof bValue === 'string') bValue = bValue.toLowerCase();

                // Handle null/undefined (push to bottom usually, or top? let's standardise)
                if (aValue === null || aValue === undefined) return 1;
                if (bValue === null || bValue === undefined) return -1;

                if (aValue < bValue) {
                    return sortConfig.direction === 'ascending' ? -1 : 1;
                }
                if (aValue > bValue) {
                    return sortConfig.direction === 'ascending' ? 1 : -1;
                }
                return 0;
            });
        }
        return sortableItems;
    }, [filtered, sortConfig]);

    const resetFilters = () => setFilters({ date: "", sportsbook: "All", sport: "All", type: "All", selection: "", status: "All" });

    const normalizedFinancials = React.useMemo(() => {
        const bd = (financials?.breakdown || []).map(x => ({ ...x }));

        const normName = (p) => {
            const v = String(p || '').trim();
            const low = v.toLowerCase();
            if (!v) return 'Other';
            if (low.includes('barstool')) return 'Other';
            if (low === 'other') return 'Other';
            return v;
        };

        const agg = {};
        for (const r of bd) {
            const provName = normName(r.provider);
            const acc = (r.account_id === undefined ? null : r.account_id);
            const key = provName + '|' + (acc === null ? '__TOTAL__' : String(acc));

            if (!agg[key]) {
                agg[key] = {
                    provider: provName,
                    account_id: acc,
                    deposited: 0,
                    withdrawn: 0,
                    net_profit: 0,
                    in_play: 0,
                    ledger_in_play: 0,
                    ledger_delta: 0,
                    computed_in_play: 0,
                    computed_delta: 0,
                };
            }
            agg[key].deposited += Number(r.deposited || 0);
            agg[key].withdrawn += Number(r.withdrawn || 0);
            agg[key].net_profit += Number(r.net_profit || 0);
            agg[key].in_play += Number(r.in_play || 0);
            agg[key].ledger_in_play += Number((r.ledger_in_play ?? r.in_play) || 0);
            agg[key].ledger_delta += Number(r.ledger_delta || 0);
            agg[key].computed_in_play += Number(r.computed_in_play || 0);
            agg[key].computed_delta += Number(r.computed_delta || 0);
        }

        const breakdown = Object.values(agg).sort((a, b) => {
            const pa = String(a.provider || '');
            const pb = String(b.provider || '');
            if (pa !== pb) return pa.localeCompare(pb);
            // Show totals first
            if (a.account_id === null && b.account_id !== null) return -1;
            if (a.account_id !== null && b.account_id === null) return 1;
            return String(a.account_id || '').localeCompare(String(b.account_id || ''));
        });
        return { ...financials, breakdown };
    }, [financials]);

    return (
        <div className="space-y-8">
            <SportAuditorModal
                show={showAudit}
                items={auditItems}
                auditLoading={auditLoading}
                onClose={() => setShowAudit(false)}
                onRerun={runAudit}
                onNormalize={async () => {
                    try {
                        const res = await api.post('/api/audit/bets/normalize-sport?limit=50000');
                        const updated = res?.data?.updated;
                        alert(`Normalized sports in DB. Updated ${updated ?? 0} rows.`);
                        await runAudit();
                    } catch (err) {
                        const msg = err?.response?.data?.detail || err?.message || 'Normalize failed';
                        alert(`Normalize failed: ${msg}`);
                    }
                }}
                onApply={applyAuditFix}
            />

            <EditBetModal
                show={showEdit}
                editBet={editBet}
                setEditBet={setEditBet}
                editNote={editNote}
                setEditNote={setEditNote}
                isUpdating={isUpdating}
                onSave={handleEditSave}
                onDelete={handleDelete}
                onClose={() => {
                    setShowEdit(false);
                    setEditBet(null);
                    setEditNote('');
                }}
            />

            <ManualAddBetModal
                show={showManualAdd}
                manualBet={manualBet}
                setManualBet={setManualBet}
                isUpdating={isUpdating}
                onSave={submitManualBet}
                onClose={() => setShowManualAdd(false)}
            />
            {/* Sportsbook Balance Summary Tiles (Primary + Secondary per book) */}
            {normalizedFinancials?.breakdown && (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-6">
                    {(() => {
                        const bd = normalizedFinancials.breakdown || [];
                        const byProv = (name) => bd.filter(x => x.provider === name);

                        const getAcc = (provName, accId) => {
                            const xs = byProv(provName).filter(x => String(x.account_id || '') === String(accId || ''));
                            // Prefer explicit account row; if missing, return null
                            return xs.length ? xs[0] : null;
                        };

                        const getTotal = (provName) => {
                            const xs = byProv(provName).filter(x => x.account_id === null);
                            return xs.length ? xs[0] : null;
                        };

                        const renderBookTile = (provName) => {
                            const total = getTotal(provName);
                            const primary = getAcc(provName, 'Main');
                            const secondary = getAcc(provName, 'User2');

                            const totalBal = Number((total?.ledger_in_play ?? total?.in_play) || 0);
                            const priBal = Number((primary?.ledger_in_play ?? primary?.in_play) || 0);
                            const secBal = Number((secondary?.ledger_in_play ?? secondary?.in_play) || 0);

                            const borderCls = provName === 'DraftKings' ? 'border-orange-600/30' : 'border-blue-600/30';
                            const textCls = provName === 'DraftKings' ? 'text-orange-400' : 'text-blue-400';
                            const iconCls = provName === 'DraftKings' ? 'text-orange-400' : 'text-blue-400';

                            return (
                                <div key={provName} className={`bg-slate-900 border rounded-xl p-5 ${borderCls}`}>
                                    <div className="flex items-center justify-between mb-3">
                                        <span className={`text-sm font-bold uppercase tracking-wider ${textCls}`}>{provName}</span>
                                        <DollarSign className={`w-5 h-5 ${iconCls}`} />
                                    </div>

                                    <div className="text-3xl font-bold text-white mb-2">
                                        {formatCurrency(totalBal)}
                                    </div>

                                    <div className="grid grid-cols-2 gap-3 text-xs">
                                        <div className="bg-slate-950/30 border border-slate-800 rounded-lg p-2">
                                            <div className="text-[10px] uppercase tracking-widest text-slate-500 font-black">Primary</div>
                                            <div className="text-slate-100 font-mono font-black text-lg">{formatCurrency(priBal)}</div>
                                            
                                        </div>
                                        <div className="bg-slate-950/30 border border-slate-800 rounded-lg p-2">
                                            <div className="text-[10px] uppercase tracking-widest text-slate-500 font-black">Secondary</div>
                                            <div className="text-slate-100 font-mono font-black text-lg">{formatCurrency(secBal)}</div>
                                            
                                        </div>
                                    </div>

                                </div>
                            );
                        };

                        const dk = renderBookTile('DraftKings');
                        const fd = renderBookTile('FanDuel');

                        const calculatedTotal = bd
                            .filter(x => x.account_id === null)
                            .filter(x => x.provider === 'DraftKings' || x.provider === 'FanDuel')
                            .reduce((sum, p) => sum + Number((p.ledger_in_play ?? p.in_play) || 0), 0);

                        const totalTile = (
                            <div className="bg-slate-900 border border-green-600/30 rounded-xl p-5" key="total-in-play">
                                <div className="flex items-center justify-between mb-3">
                                    <span className="text-sm font-bold uppercase tracking-wider text-green-400">Total In Play</span>
                                    <Activity className="w-5 h-5 text-green-400" />
                                </div>
                                <div className="text-3xl font-bold text-white mb-1">
                                    {formatCurrency(calculatedTotal)}
                                </div>
                                <div className="text-xs text-gray-400">DraftKings + FanDuel</div>
                            </div>
                        );

                        return (
                            <>
                                {dk}
                                {fd}
                                {totalTile}
                            </>
                        );
                    })()}
                </div>
            )}

            {/* Open Bets (separate section) */}
            {showOpenBets && (
            <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-xl mb-6">
                <div className="p-4 border-b border-slate-800 flex items-center justify-between">
                    <div>
                        <div className="text-sm font-black text-slate-100 uppercase tracking-wider">Open Bets</div>
                        <div className="text-[11px] text-slate-500">Pending wagers reduce displayed balances immediately.</div>
                    </div>
                    <div className="text-xs text-slate-400">{openBetsLoading ? 'Loading…' : `${(openBets || []).length} open`}</div>
                </div>
                <div className="p-4">
                    {openBetsError && <div className="text-xs text-red-300">{openBetsError}</div>}
                    {!openBetsLoading && (!openBets || openBets.length === 0) && (
                        <div className="text-xs text-slate-500">No open bets.</div>
                    )}
                    {!openBetsLoading && openBets && openBets.length > 0 && (
                        <div className="space-y-2">
                            {openBets.slice(0, 25).map((b) => (
                                <div
                                    key={b.id}
                                    className="flex items-center justify-between gap-3 p-3 rounded-lg border border-slate-800 bg-slate-950/20 hover:bg-slate-950/40 transition cursor-pointer"
                                    onClick={() => {
                                        setEditBet({
                                            ...b,
                                            date: String(b.date_et || b.date || '').slice(0, 10),
                                            wager: b.wager ?? b.stake ?? b.amount,
                                        });
                                        setEditNote('');
                                        setShowEdit(true);
                                    }}
                                >
                                    <div className="min-w-0">
                                        <div className="text-xs font-black text-slate-100 truncate flex items-center gap-2">
                                            <span>{b.provider} • {(b.account_id === 'User2' ? 'Secondary' : 'Primary')}</span>
                                            <span className="inline-flex items-center gap-1 text-[10px] text-slate-400 border border-slate-700/60 rounded px-1.5 py-0.5">
                                                <Pencil size={12} /> Edit
                                            </span>
                                        </div>
                                        <div className="text-xs text-slate-300 truncate" title={b.selection || b.description}>{b.selection || b.description}</div>
                                        <div className="text-[11px] text-slate-500">{formatDateMDY(b.date_et || b.date)} • {String(b.status || 'PENDING').toUpperCase()}</div>
                                    </div>
                                    <div className="text-right shrink-0">
                                        <div className="text-xs font-mono font-black text-slate-200">{formatCurrency(Number(b.wager || 0))}</div>
                                        <div className="text-[11px] text-slate-500 font-mono">{b.odds ? (Number(b.odds) > 0 ? `+${b.odds}` : String(b.odds)) : '—'}</div>
                                    </div>
                                </div>
                            ))}
                            {openBets.length > 25 && <div className="text-[11px] text-slate-500">Showing first 25 open bets.</div>}
                        </div>
                    )}
                </div>
            </div>
            )}

            {/* Sportsbook Financials (statement-style; collapsed by default) */}
            {showFinancials && normalizedFinancials?.breakdown && (() => {
                const rows = normalizedFinancials.breakdown || [];
                const provTop = (name) => rows.find(r => r.provider === name && r.account_id === null);
                const provAcc = (name, acc) => rows.find(r => r.provider === name && String(r.account_id || '') === String(acc));

                const providers = ['DraftKings', 'FanDuel', 'Other'];

                const fmt = (x) => formatCurrency(Number(x || 0));

                const topRows = providers
                    .map((p) => {
                        if (p === 'Other') {
                            // any provider normalized to Other will already be 'Other'
                            return { p: 'Other', top: provTop('Other'), primary: provAcc('Other', 'Main'), secondary: provAcc('Other', 'User2') };
                        }
                        return { p, top: provTop(p), primary: provAcc(p, 'Main'), secondary: provAcc(p, 'User2') };
                    })
                    .filter(x => x.top);

                return (
                    <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-xl mb-8">
                        <div className="p-6 border-b border-slate-800">
                            <div className="flex items-center justify-between">
                                <h3 className="text-xl font-bold flex items-center gap-2">
                                    <DollarSign className="text-green-400" /> Sportsbook Financials
                                </h3>
                                <div className="text-[11px] text-slate-500">Statement view (click a row to expand)</div>
                            </div>
                            <div className="mt-2 text-[10px] text-gray-600 uppercase tracking-widest opacity-70">
                                Baseline balances from latest snapshots; new settled bets apply as ledger delta.
                            </div>
                        </div>

                        <div className="overflow-x-auto">
                            <table className="w-full text-left text-sm">
                                <thead className="bg-slate-950/50">
                                    <tr className="text-slate-400 border-b border-slate-800">
                                        <th className="py-3 px-4">Sportsbook</th>
                                        <th className="py-3 px-4 text-right">Current</th>
                                        
                                        <th className="py-3 px-4 text-right">Deposits</th>
                                        <th className="py-3 px-4 text-right">Withdrawals</th>
                                        <th className="py-3 px-4 text-right">Realized P/L</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-slate-800">
                                    {topRows.map(({ p, top, primary, secondary }) => {
                                        const cur = Number((top.ledger_in_play ?? top.in_play) || 0);
                                        const isOpen = expandedBook === p;

                                        return (
                                            <React.Fragment key={p}>
                                                <tr
                                                    className={`cursor-pointer hover:bg-slate-800/30 ${isOpen ? 'bg-slate-800/20' : ''}`}
                                                    onClick={() => setExpandedBook(isOpen ? null : p)}
                                                >
                                                    <td className="py-3 px-4 font-black text-slate-100">
                                                        <div className="flex items-center gap-2">
                                                            <span className="text-slate-400">{isOpen ? '▾' : '▸'}</span>
                                                            <span>{p}</span>
                                                        </div>
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
                                                                        <div>Deposited <span className="font-mono text-slate-200">{fmt(Number(primary?.deposited || 0))}</span></div>
                                                                        <div>Withdrawn <span className="font-mono text-slate-200">{fmt(Number(primary?.withdrawn || 0))}</span></div>
                                                                    </div>
                                                                </div>
                                                                <div className="border border-slate-800 rounded-lg p-4 bg-slate-950/20">
                                                                    <div className="text-[10px] uppercase tracking-widest text-slate-500 font-black">Secondary</div>
                                                                    <div className="mt-1 text-xl font-black text-white">{fmt(Number((secondary?.ledger_in_play ?? secondary?.in_play) || 0))}</div>
                                                                    <div className="mt-2 grid grid-cols-2 gap-2 text-[11px] text-slate-400">
                                                                        <div>Deposited <span className="font-mono text-slate-200">{fmt(Number(secondary?.deposited || 0))}</span></div>
                                                                        <div>Withdrawn <span className="font-mono text-slate-200">{fmt(Number(secondary?.withdrawn || 0))}</span></div>
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
                );
            })()}




            <div className="glass-card rounded-2xl overflow-hidden shadow-2xl relative">
                {/* Subtle top gradient line */}
                <div className="absolute top-0 left-0 right-0 h-[1px] bg-gradient-to-r from-transparent via-green-500/30 to-transparent" />

                {/* Toolbar / Summary */}
                <div className="p-4 border-b border-gray-800 flex justify-between items-center bg-gray-900/50 backdrop-blur min-h-[72px]">
                    <div className="flex items-center gap-4">
                        <div className="text-gray-400 text-sm">
                            Showing <span className="text-white font-bold">{filtered.length}</span> of {bets.length} transactions
                        </div>
                        {/* 7-day trend sparkline removed */}
                    </div>
                    <div className="flex items-center gap-2">
                        <>
                            <button
                                onClick={() => setShowManualAdd(true)}
                                className="text-xs text-green-300 hover:text-green-200 font-medium px-3 py-1.5 rounded-lg border border-green-900/40 hover:bg-green-900/20 transition"
                            >
                                + Add Bet Slip
                            </button>

                            <button
                                onClick={runAudit}
                                disabled={auditLoading}
                                className={`text-xs font-medium px-3 py-1.5 rounded-lg border transition ${auditLoading ? 'text-gray-500 border-gray-800 bg-gray-900/40 animate-pulse' : 'text-amber-300 hover:text-amber-200 border-amber-900/40 hover:bg-amber-900/20'}`}
                                title="Scan for bets whose sport looks wrong (based on matching teams to events)"
                            >
                                {auditLoading ? 'Auditing…' : 'Audit sport'}
                            </button>

                            <button
                                onClick={resetFilters}
                                className="text-xs text-blue-400 hover:text-blue-300 font-medium px-3 py-1.5 rounded-lg border border-blue-900/30 hover:bg-blue-900/20 transition"
                            >
                                Clear Filters
                            </button>
                        </>
                    </div>
                </div>

                {/* Grid */}

                {(() => {
                    const betRows = (sortedBets || []).filter(b => (b.category || '') !== 'Transaction');
                    const sum = betRows.reduce((acc, b) => acc + (Number(b.profit) || 0), 0);
                    return (
                        <div className="px-4 py-3 border-b border-gray-800 bg-gray-900/40 flex items-center justify-between text-xs backdrop-blur-sm">
                            <div className="text-gray-500 font-medium">Filtered: <span className="text-green-400 font-bold">{betRows.length}</span></div>
                            <div className="text-gray-500 font-medium">Σ Profit/Loss: <span className={`font-mono font-bold ${sum >= 0 ? 'text-green-400' : 'text-red-400'}`}>{formatCurrency(sum)}</span></div>
                        </div>
                    );
                })()}

                {/* Mobile: stacked cards (no horizontal scroll) */}
                <div className="sm:hidden space-y-3 p-3">
                    {loading ? (
                        Array(8).fill(0).map((_, i) => (
                            <div key={i} className="ui-card p-4">
                                <div className="h-3 w-1/2 bg-slate-800/60 rounded" />
                                <div className="mt-3 h-3 w-3/4 bg-slate-800/60 rounded" />
                                <div className="mt-3 h-3 w-2/3 bg-slate-800/60 rounded" />
                            </div>
                        ))
                    ) : (
                        (sortedBets || []).map((bet) => {
                            const isTxn = (bet.category === 'Transaction');
                            const title = isTxn
                                ? (bet.description || bet.type || 'Transaction')
                                : `${extractEvent(bet) || (bet.away_team && bet.home_team ? `${bet.away_team} @ ${bet.home_team}` : 'Bet')}`;

                            const sel = String(bet.display_selection || bet.selection || '').trim();
                            const odds = (bet.odds !== undefined && bet.odds !== null && bet.odds !== '') ? String(bet.odds) : '—';
                            const wager = (bet.wager !== undefined && bet.wager !== null) ? formatCurrency(bet.wager) : '—';
                            const pl = (bet.profit !== undefined && bet.profit !== null) ? formatCurrency(bet.profit) : '—';

                            return (
                                <div
                                    key={bet.id || bet.txn_id}
                                    className="ui-card p-4"
                                    onClick={() => {
                                        if (!bet.id) return;
                                        setEditBet({
                                            id: bet.id,
                                            provider: bet.provider,
                                            date: (bet.sort_date || bet.date || '').slice(0, 10),
                                            sport: bet.sport,
                                            bet_type: bet.bet_type,
                                            wager: bet.wager,
                                            odds: bet.odds,
                                            profit: bet.profit,
                                            status: bet.status,
                                            description: bet.description,
                                            selection: bet.selection,
                                        });
                                        setEditNote('');
                                        setShowEdit(true);
                                    }}
                                >
                                    <div className="flex items-start justify-between gap-3">
                                        <div className="min-w-0">
                                            <div className="text-[11px] text-slate-400 font-semibold">
                                                {formatDateMDY(bet.sort_date || bet.date)}
                                                {bet.provider ? ` • ${bet.provider}` : ''}
                                                {bet.sport ? ` • ${bet.sport}` : ''}
                                            </div>
                                            <div className="mt-1 text-sm font-semibold text-slate-100 whitespace-normal break-words">
                                                {title}
                                            </div>
                                            {sel ? (
                                                <div className="mt-1 text-[12px] text-slate-300 whitespace-normal break-words">
                                                    {sel}
                                                </div>
                                            ) : null}
                                        </div>
                                        <div className="text-right shrink-0">
                                            <div className={`text-sm font-mono font-semibold ${(Number(bet.profit) || 0) >= 0 ? 'text-emerald-300' : 'text-rose-300'}`}>{pl}</div>
                                            <div className="text-[11px] text-slate-400 font-mono">wager {wager}</div>
                                        </div>
                                    </div>

                                    <div className="mt-3 grid grid-cols-3 gap-2 text-[11px]">
                                        <div className="bg-slate-950/20 border border-slate-700/40 rounded-xl p-2">
                                            <div className="ui-label">Type</div>
                                            <div className="text-slate-200 font-semibold whitespace-normal break-words">{bet.bet_type || bet.type || '—'}</div>
                                        </div>
                                        <div className="bg-slate-950/20 border border-slate-700/40 rounded-xl p-2">
                                            <div className="ui-label">Odds</div>
                                            <div className="text-slate-200 font-mono font-semibold">{odds}</div>
                                        </div>
                                        <div className="bg-slate-950/20 border border-slate-700/40 rounded-xl p-2">
                                            <div className="ui-label">Status</div>
                                            <div className="text-slate-200 font-semibold">{isTxn ? (Number(bet.wager) < 0 ? 'DEP' : 'WDR') : (bet.status || '—')}</div>
                                        </div>
                                    </div>
                                </div>
                            );
                        })
                    )}
                </div>

                {/* Desktop/tablet: table */}
                <div className="hidden sm:block scrollbar-refined overflow-x-auto">
                    <table className="w-full text-left text-xs table-fixed border-separate border-spacing-0">
                        <thead className="bg-gray-800 text-gray-400 font-medium uppercase text-xs tracking-wider">
                            {/* Header Labels */}
                            <tr className="bg-gray-900/20 backdrop-blur-sm">
                                <th className="px-3 py-3 border-b border-gray-700/50 cursor-pointer hover:bg-gray-800/50 select-none w-[84px] text-gray-500 font-black uppercase tracking-tighter" onClick={() => requestSort('date')}>Date{getSortIcon('date')}</th>
                                <th className="px-3 py-3 border-b border-gray-700/50 cursor-pointer hover:bg-gray-800/50 select-none w-[80px] text-gray-500 font-black uppercase tracking-tighter" onClick={() => requestSort('provider')}>Book{getSortIcon('provider')}</th>
                                <th className="px-3 py-3 border-b border-gray-700/50 select-none w-[72px] text-gray-500 font-black uppercase tracking-tighter">Acct</th>
                                <th className="px-3 py-3 border-b border-gray-700/50 cursor-pointer hover:bg-gray-800/50 select-none w-[64px] text-gray-500 font-black uppercase tracking-tighter" onClick={() => requestSort('sport')}>Sport{getSortIcon('sport')}</th>
                                <th className="px-3 py-3 border-b border-gray-700/50 cursor-pointer hover:bg-gray-800/50 select-none w-[70px] text-gray-500 font-black uppercase tracking-tighter" onClick={() => requestSort('bet_type')}>Type{getSortIcon('bet_type')}</th>
                                <th className="px-3 py-3 border-b border-gray-700/50 select-none w-[180px] text-gray-500 font-black uppercase tracking-tighter">Event</th>
                                <th className="px-3 py-3 border-b border-gray-700/50 cursor-pointer hover:bg-gray-800/50 select-none w-[200px] text-gray-500 font-black uppercase tracking-tighter" onClick={() => requestSort('selection')}>Selection{getSortIcon('selection')}</th>
                                <th className="px-3 py-3 border-b border-gray-700/50 text-right cursor-pointer hover:bg-gray-800/50 select-none w-[60px] text-gray-500 font-black uppercase tracking-tighter" onClick={() => requestSort('odds')}>Odds{getSortIcon('odds')}</th>
                                <th className="px-3 py-3 border-b border-gray-700/50 text-right cursor-pointer hover:bg-gray-800/50 select-none w-[70px] text-gray-500 font-black uppercase tracking-tighter" onClick={() => requestSort('wager')}>Wager{getSortIcon('wager')}</th>
                                <th className="px-3 py-3 border-b border-gray-700/50 text-center cursor-pointer hover:bg-gray-800/50 select-none w-[64px] text-gray-500 font-black uppercase tracking-tighter" onClick={() => requestSort('status')}>Status{getSortIcon('status')}</th>
                                <th className="px-3 py-3 border-b border-gray-700/50 text-right cursor-pointer hover:bg-gray-800/50 select-none w-[76px] text-gray-500 font-black uppercase tracking-tighter" onClick={() => requestSort('profit')}>P/L{getSortIcon('profit')}</th>
                            </tr>
                            {/* Filter Row */}
                            <tr className="bg-gray-850">
                                <th className="px-1 py-1">
                                    <input
                                        type="text"
                                        placeholder="Date"
                                        className="w-full bg-gray-900 border border-gray-700 rounded px-1 py-0.5 text-[10px] text-white focus:border-blue-500 outline-none"
                                        value={filters.date}
                                        onChange={e => setFilters({ ...filters, date: e.target.value })}
                                    />
                                </th>
                                <th className="px-1 py-1">
                                    <select
                                        className="w-full bg-gray-900 border border-gray-700 rounded px-1 py-0.5 text-[10px] text-white focus:border-blue-500 outline-none"
                                        value={filters.sportsbook}
                                        onChange={e => setFilters({ ...filters, sportsbook: e.target.value })}
                                    >
                                        <option value="All">All</option>
                                        {sportsbooks.filter(s => s !== 'All').map(s => <option key={s} value={s}>{s}</option>)}
                                    </select>
                                </th>
                                <th className="px-1 py-1">
                                    <select
                                        className="w-full bg-gray-900 border border-gray-700 rounded px-1 py-0.5 text-[10px] text-white focus:border-blue-500 outline-none"
                                        value={filters.account}
                                        onChange={e => setFilters({ ...filters, account: e.target.value })}
                                    >
                                        <option value="All">All</option>
                                        <option value="Primary">Primary</option>
                                        <option value="Secondary">Secondary</option>
                                    </select>
                                </th>
                                <th className="px-1 py-1">
                                    <select
                                        className="w-full bg-gray-900 border border-gray-700 rounded px-1 py-0.5 text-[10px] text-white focus:border-blue-500 outline-none"
                                        value={filters.sport}
                                        onChange={e => setFilters({ ...filters, sport: e.target.value })}
                                    >
                                        <option value="All">All</option>
                                        {sports.filter(s => s !== 'All').map(s => <option key={s} value={s}>{s}</option>)}
                                    </select>
                                </th>
                                <th className="px-1 py-1">
                                    <select
                                        className="w-full bg-gray-900 border border-gray-700 rounded px-1 py-0.5 text-[10px] text-white focus:border-blue-500 outline-none"
                                        value={filters.type}
                                        onChange={e => setFilters({ ...filters, type: e.target.value })}
                                    >
                                        {types.map(t => <option key={t} value={t}>{t}</option>)}
                                    </select>
                                </th>
                                <th className="px-1 py-1"></th>
                                <th className="px-1 py-1">
                                    <input
                                        type="text"
                                        placeholder="Search..."
                                        className="w-full bg-gray-900 border border-gray-700 rounded px-1 py-0.5 text-[10px] text-white focus:border-blue-500 outline-none"
                                        value={filters.selection}
                                        onChange={e => setFilters({ ...filters, selection: e.target.value })}
                                    />
                                </th>
                                <th className="px-1 py-1"></th>
                                <th className="px-1 py-1"></th>
                                <th className="px-1 py-1">
                                    <select
                                        className="w-full bg-gray-900 border border-gray-700 rounded px-1 py-0.5 text-[10px] text-white focus:border-blue-500 outline-none"
                                        value={filters.status}
                                        onChange={e => setFilters({ ...filters, status: e.target.value })}
                                    >
                                        {statuses.map(s => <option key={s} value={s}>{s}</option>)}
                                    </select>
                                </th>
                                <th className="px-1 py-1"></th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-800">
                            {loading ? (
                                Array(10).fill(0).map((_, i) => <SkeletonRow key={i} />)
                            ) : sortedBets.map((bet) => {
                                const isTxn = (bet.category === 'Transaction');
                                const isDeposit = isTxn && (Number(bet.wager) < 0 || (bet.description || '').toLowerCase().includes('deposit'));
                                const isSelected = false;
                                return (
                                    <tr
                                        key={bet.id || bet.txn_id}
                                        className={`transition duration-150 cursor-pointer border-b border-gray-800/30 ${isSelected ? 'bg-blue-500/10 hover:bg-blue-500/20' : 'hover:bg-gray-800/40'}`}
                                        onClick={() => {
                                            if (!bet.id) return;
                                            setEditBet({
                                                id: bet.id,
                                                provider: bet.provider,
                                                account_id: bet.account_id || 'Main',
                                                date: (bet.sort_date || bet.date || '').slice(0, 10),
                                                sport: bet.sport,
                                                bet_type: bet.bet_type,
                                                wager: bet.wager,
                                                odds: bet.odds,
                                                profit: bet.profit,
                                                status: bet.status,
                                                description: bet.description,
                                                selection: bet.selection,
                                            });
                                            setEditNote('');
                                            setShowEdit(true);
                                        }}
                                    >
                                        <td
                                            className="px-3 py-3 text-gray-400 font-mono text-[10px] whitespace-nowrap opacity-60"
                                            title={formatDateMDY(bet.sort_date || bet.date)}
                                        >
                                            {formatDateMDY(bet.sort_date || bet.date)}
                                        </td>
                                        <td className="px-3 py-3">
                                            <span className={`text-[10px] px-2 py-0.5 rounded font-black tracking-tighter uppercase border transition-colors duration-200 ${bet.provider === 'DraftKings' ? "bg-green-500/10 text-green-400 border-green-500/20" :
                                                bet.provider === 'FanDuel' ? "bg-blue-500/10 text-blue-400 border-blue-500/20" :
                                                    "bg-gray-800/40 text-gray-400 border-gray-700/50"
                                                }`}>
                                                {bet.provider}
                                            </span>
                                        </td>
                                        <td className="px-3 py-3">
                                            <span className="text-[10px] px-2 py-0.5 rounded font-black tracking-tighter uppercase border border-slate-700/50 bg-slate-800/30 text-slate-300">
                                                {(bet.account_id === 'User2' || String(bet.account_id || '').toLowerCase() === 'secondary') ? 'Secondary' : 'Primary'}
                                            </span>
                                        </td>
                                        <td className="px-3 py-3">
                                            <span className="text-[10px] text-gray-300 uppercase font-black tracking-widest opacity-80">
                                                {bet.sport}
                                            </span>
                                        </td>
                                        <td className="px-3 py-3 text-gray-500 text-[10px] font-medium tracking-tight whitespace-nowrap overflow-hidden">{bet.bet_type}</td>

                                        <td className="px-3 py-3 text-gray-400 text-[11px] font-medium tracking-tight truncate" title={extractEvent(bet)}>
                                            {extractEvent(bet) || '-'}
                                        </td>

                                        <td className="px-3 py-3 truncate text-gray-200 text-xs font-bold tracking-tight" title={bet.selection || bet.description}>
                                            {(() => {
                                                // Keep Selection column concise: just team(s) + bet, not slip metadata.
                                                const raw = bet.display_selection || bet.selection || bet.description || '';
                                                let s = String(raw);
                                                // Strip slip/settlement details that belong in other columns
                                                ['Wager:', 'Paid:', 'Payout:', 'Final Score', 'Cash Out:', 'Potential Payout:'].forEach((tok) => {
                                                    if (s.includes(tok)) s = s.split(tok)[0];
                                                });
                                                s = s.replace(/\s+/g, ' ').trim();
                                                if (s.length > 80) s = s.slice(0, 77) + '...';
                                                return s;
                                            })()}
                                            {bet.is_live && <span className="ml-2 text-[9px] bg-red-900/50 text-red-300 px-1 rounded border border-red-800">LIVE</span>}
                                            {bet.is_bonus && <span className="ml-2 text-[9px] bg-yellow-900/50 text-yellow-300 px-1 rounded border border-yellow-800">BONUS</span>}
                                        </td>
                                        <td className="px-3 py-3 text-right font-mono text-gray-400 text-[11px] whitespace-nowrap">
                                            {!isTxn ? (bet.odds ? (bet.odds > 0 ? `+${bet.odds}` : bet.odds) : '-') : '-'}
                                        </td>
                                        <td className={`px-3 py-3 text-right font-medium text-[11px] whitespace-nowrap ${isTxn ? 'text-gray-400' : 'text-gray-300'}`}>
                                            {formatCurrency(bet.wager)}
                                        </td>
                                        <td className="px-3 py-3 text-center">
                                            <span className={`px-2 py-1 rounded text-[10px] font-black tracking-widest border transition-all duration-300 ${isTxn ? (isDeposit ? 'bg-green-500/10 text-green-400 border-green-500/20' : 'bg-gray-500/10 text-gray-400 border-gray-500/20') :
                                                ['WON', 'WIN'].includes(bet.status) ? 'bg-green-500/10 text-green-400 border-green-500/20 shadow-[0_0_15px_rgba(34,197,94,0.1)]' :
                                                    ['LOST', 'LOSE'].includes(bet.status) ? 'bg-red-500/10 text-red-400 border-red-500/20' :
                                                        bet.status === 'PUSH' ? 'bg-gray-500/10 text-gray-400 border-gray-500/20' :
                                                            'bg-blue-500/10 text-blue-400 border-blue-500/20'
                                                }`}>
                                                {isTxn ? (isDeposit ? 'DEPOSIT' : 'WITHDRAWAL') : bet.status}
                                            </span>
                                        </td>
                                        <td className={`px-3 py-3 text-right font-bold text-[11px] whitespace-nowrap ${bet.profit >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                            {(bet.profit !== undefined && bet.profit !== null) ? (bet.profit >= 0 ? '+' : '') + formatCurrency(bet.profit) : '-'}
                                        </td>

                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                </div>

                {filtered.length === 0 && (
                    <div className="p-8 text-center text-gray-500 text-sm">
                        No transactions found matching criteria.
                    </div>
                )}
            </div>
        </div>
    );
}
