import React, { useEffect, useRef, useState } from 'react';
import {
  X,
  PlusCircle,
  Loader2,
  AlertTriangle,
  TrendingUp,
  TrendingDown,
  Activity,
  Users,
  ShieldCheck,
  RefreshCw,
} from 'lucide-react';
import api from '../../api/axios';
import ModelVisualComparison from './ModelVisualComparison';
import {
  fmtTimeEt,
  fmtOdds,
  fmtPct,
  fmtSigned,
  getConfidenceMeta,
  getRecEv,
  normalizeMovementTag,
  safeReasonText,
  getProjectedScore,
  buildVisualModelData,
  getLiveGameStatus,
  getModelSignalData,
  getRecommendedBetSize,
} from './todayHelpers';

const TodayMatchupModal = ({
  game,
  analysisResult,
  correlationResult,
  matchupProfile,
  cachedMeta = null,
  bankroll = null,
  isAnalyzing,
  onClose,
  onAddBet,
  onAnalysisUpdated,
}) => {
  const dialogRef = useRef(null);
  const [ref1, setRef1] = useState('');
  const [ref2, setRef2] = useState('');
  const [ref3, setRef3] = useState('');
  const [refsSaving, setRefsSaving] = useState(false);
  const [refsMessage, setRefsMessage] = useState(null);
  const [outPlayers, setOutPlayers] = useState({});
  const [modalTab, setModalTab] = useState('overview'); // 'overview' | 'stats' | 'lineup'

  useEffect(() => {
    setOutPlayers({});
    setModalTab('overview');
  }, [game?.id]);

  const togglePlayerOut = (side, name) => {
    const key = `${side}:${name}`;
    setOutPlayers((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (game) {
      if (!dialog.open && typeof dialog.showModal === 'function') {
        dialog.showModal();
      }
      setRefsMessage(null);
    } else if (dialog.open) {
      dialog.close();
    }
  }, [game]);

  useEffect(() => {
    const refs = analysisResult?.referees?.crew || analysisResult?.recommendations?.[0]?.signals?.referees?.crew;
    if (Array.isArray(refs) && refs.length > 0) {
      setRef1(refs[0] || '');
      setRef2(refs[1] || '');
      setRef3(refs[2] || '');
    } else {
      setRef1('');
      setRef2('');
      setRef3('');
    }
  }, [analysisResult]);

  // Native backdrop pointer-position test (never event.target check)
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

  const handleSaveRefs = async (e) => {
    e.preventDefault();
    if (!game?.id) return;
    setRefsSaving(true);
    setRefsMessage(null);
    try {
      await api.post('/api/ncaam/referees', {
        event_id: game.id,
        referee_1: ref1.trim() || null,
        referee_2: ref2.trim() || null,
        referee_3: ref3.trim() || null,
      });
      const res = await api.post('/api/ncaam/analyze', { event_id: game.id });
      onAnalysisUpdated?.(res.data);
      setRefsMessage({ type: 'ok', text: 'Referee crew saved and matchup re-analyzed.' });
    } catch (err) {
      setRefsMessage({
        type: 'err',
        text: err?.response?.data?.detail || err?.message || 'Failed to save referees.',
      });
    } finally {
      setRefsSaving(false);
    }
  };

  const topRec = (analysisResult?.recommendations || [])[0] || null;
  const conf = getConfidenceMeta(topRec);
  const topEv = getRecEv(topRec);
  const sizeInfo = getRecommendedBetSize(topRec, bankroll);
  const sig = topRec?.signals || analysisResult?.signals || {};
  const dbg = analysisResult?.debug || {};
  const torvikStats = analysisResult?.torvik_team_stats || {};
  const homeStats = torvikStats.home || matchupProfile?.home_torvik || {};
  const awayStats = torvikStats.away || matchupProfile?.away_torvik || {};
  const injImpact =
    sig.injuries_impact ||
    dbg.injuries_impact ||
    null;
  const rawInjuries = sig.injuries || analysisResult?.injuries || [];
  const splits = sig.public_splits || analysisResult?.action_splits || null;
  const projectedScore = getProjectedScore(game, analysisResult, topRec);
  const visualData = buildVisualModelData(topRec, game, analysisResult);
  const effectiveContext = analysisResult?.context || cachedMeta?.context || null;
  const liveTargetPick = topRec || cachedMeta?.rec || effectiveContext?.closest_lean || null;
  const liveInfo = getLiveGameStatus(game, liveTargetPick, effectiveContext);
  const modelSignals = getModelSignalData(topRec, analysisResult?.context, dbg, game);
  const fmtStat = (v) => (v != null && Number.isFinite(Number(v)) ? Number(v).toFixed(1) : '—');
  const rotationHome = analysisResult?.rotation_players?.home || [];
  const rotationAway = analysisResult?.rotation_players?.away || [];
  const ffDetail = analysisResult?.kenpom_data?.four_factors_detail || null;
  const homeOutPts = rotationHome.reduce(
    (acc, p) => acc + (outPlayers[`home:${p.name}`] ? Number(p.est_impact_pts || 0) : 0),
    0
  );
  const awayOutPts = rotationAway.reduce(
    (acc, p) => acc + (outPlayers[`away:${p.name}`] ? Number(p.est_impact_pts || 0) : 0),
    0
  );
  // Positive netOutShift hurts home (moves home spread higher / less negative); negative hurts away
  const netOutShiftHome = Number((homeOutPts - awayOutPts).toFixed(1));
  const baseFairHome =
    dbg.mu_spread_final ?? dbg.mu_spread_power ?? effectiveContext?.fair_spread_home ?? null;
  const adjustedFairHome =
    baseFairHome != null && Number.isFinite(Number(baseFairHome))
      ? Number((Number(baseFairHome) + netOutShiftHome).toFixed(1))
      : null;

  return (
    <dialog
      ref={dialogRef}
      closedby="any"
      aria-labelledby="matchup-dialog-title"
      onCancel={(e) => {
        e.preventDefault();
        onClose?.();
      }}
      onClick={handleBackdropClick}
      className="today-modal w-[94dvw] bg-slate-900 text-slate-100 border border-slate-700/80 rounded-2xl shadow-2xl p-0 overflow-hidden m-auto"
    >
      {game && (
        <div className="flex flex-col min-h-0 max-h-[90dvh]">
          {/* Header */}
          <div className="flex items-start justify-between gap-4 px-5 py-4 bg-slate-950/90 border-b border-slate-800 shrink-0">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
                <span className="px-2 py-0.5 rounded bg-indigo-500/20 border border-indigo-400/30 text-indigo-300 font-bold uppercase">
                  {game.sport || 'NCAAM'}
                </span>
                {liveInfo.isLive ? (
                  <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-rose-500/20 border border-rose-500/45 text-rose-200 font-bold text-[11px]">
                    <span className="w-1.5 h-1.5 rounded-full bg-rose-400 animate-pulse" aria-hidden="true" />
                    LIVE {liveInfo.statusDetail ? `· ${liveInfo.statusDetail}` : ''}
                  </span>
                ) : liveInfo.isFinal ? (
                  <span className="px-2 py-0.5 rounded bg-slate-800 border border-slate-700 text-slate-200 font-bold text-[11px]">
                    FINAL
                  </span>
                ) : (
                  <time dateTime={game.start_time || ''}>{fmtTimeEt(game.start_time)} ET</time>
                )}
                {liveInfo.hasScore && (
                  <span className="font-mono font-bold text-white">
                    {game.away_team} {liveInfo.awayScore} – {game.home_team} {liveInfo.homeScore}
                  </span>
                )}
                {(liveInfo.trendLabel || liveInfo.coverText) && (
                  <span
                    className={`px-2 py-0.5 rounded-full text-[11px] font-bold border ${
                      liveInfo.coverTone === 'win'
                        ? 'bg-emerald-500/15 border-emerald-500/40 text-emerald-300'
                        : liveInfo.coverTone === 'loss'
                          ? 'bg-rose-500/15 border-rose-500/40 text-rose-300'
                          : liveInfo.coverTone === 'tossup'
                            ? 'bg-amber-500/15 border-amber-500/40 text-amber-200'
                            : 'bg-slate-800 border-slate-700 text-slate-200'
                    }`}
                  >
                    {liveInfo.trendLabel
                      ? `${liveInfo.trendLabel}${liveInfo.liveWinProb != null ? ` (${fmtPct(liveInfo.liveWinProb, 0)})` : ''}`
                      : liveInfo.coverText}
                  </span>
                )}
              </div>
              <h2 id="matchup-dialog-title" className="mt-1 text-lg sm:text-xl font-bold text-white truncate">
                {game.away_team} {Boolean(game?.neutral_site || analysisResult?.neutral_site) ? 'vs' : '@'} {game.home_team}
              </h2>
              {Boolean(game?.neutral_site || analysisResult?.neutral_site || game?.venue || analysisResult?.venue) && (
                <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-400">
                  {Boolean(game?.neutral_site || analysisResult?.neutral_site) && (
                    <span className="px-2 py-0.5 rounded-full bg-sky-500/15 border border-sky-400/35 text-sky-200 font-semibold text-[11px]">
                      Neutral Court (No Home-Court Edge)
                    </span>
                  )}
                  {(game?.venue || analysisResult?.venue) && (
                    <span>
                      {[
                        game?.venue || analysisResult?.venue,
                        game?.venue_city || analysisResult?.venue_city,
                        game?.venue_state || analysisResult?.venue_state,
                      ]
                        .filter(Boolean)
                        .join(', ')}
                    </span>
                  )}
                </div>
              )}
            </div>

            <form method="dialog">
              <button
                type="submit"
                onClick={onClose}
                aria-label="Close matchup details"
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-xs font-semibold text-slate-200 cursor-pointer"
              >
                <X size={14} aria-hidden="true" />
                <span>Close</span>
              </button>
            </form>
          </div>

          {/* Scrollable Body */}
          <div className="p-5 overflow-y-auto space-y-5 text-sm">
            {/* 0. Live In-Game Bet Trend & Pace Tracker (always visible immediately when score exists) */}
            {liveInfo.hasScore && (
              <section
                className={`rounded-xl border p-4 space-y-3 ${
                  liveInfo.coverTone === 'win'
                    ? 'border-emerald-500/40 bg-emerald-950/20'
                    : liveInfo.coverTone === 'loss'
                      ? 'border-rose-500/40 bg-rose-950/20'
                      : liveInfo.coverTone === 'tossup'
                        ? 'border-amber-500/40 bg-amber-950/20'
                        : 'border-slate-700/80 bg-slate-950/75'
                }`}
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] font-bold uppercase tracking-widest text-slate-400">
                      {liveInfo.isFinal ? 'Final Score & Result' : 'Live Score & Bet Trend'}
                    </span>
                    <span className="px-2 py-0.5 rounded bg-slate-800 border border-slate-700 text-[11px] font-mono text-slate-200">
                      {liveInfo.periodLabel} · {liveInfo.progressPct}% played
                    </span>
                  </div>

                  {liveInfo.trendLabel && (
                    <span
                      className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs font-bold ${
                        liveInfo.coverTone === 'win'
                          ? 'bg-emerald-500/15 border-emerald-500/40 text-emerald-300'
                          : liveInfo.coverTone === 'loss'
                            ? 'bg-rose-500/15 border-rose-500/40 text-rose-300'
                            : liveInfo.coverTone === 'tossup'
                              ? 'bg-amber-500/15 border-amber-500/40 text-amber-200'
                              : 'bg-slate-800 border-slate-700 text-slate-200'
                      }`}
                    >
                      {liveInfo.coverTone === 'win' ? (
                        <TrendingUp size={13} aria-hidden="true" />
                      ) : liveInfo.coverTone === 'loss' ? (
                        <TrendingDown size={13} aria-hidden="true" />
                      ) : (
                        <Activity size={13} aria-hidden="true" />
                      )}
                      <span>
                        {liveInfo.trendLabel}
                        {liveInfo.liveWinProb != null ? ` (${fmtPct(liveInfo.liveWinProb, 0)} Live Win Chance)` : ''}
                      </span>
                    </span>
                  )}
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5 text-xs">
                  <div className="rounded-lg bg-slate-900/90 border border-slate-800 px-3 py-2">
                    <div className="text-[10px] uppercase tracking-wider text-slate-400 font-bold">
                      Current Score
                    </div>
                    <div className="mt-0.5 font-mono font-bold text-white text-sm">
                      {game.away_team} {liveInfo.awayScore} – {game.home_team} {liveInfo.homeScore}
                    </div>
                    <div className="text-[11px] text-slate-400">
                      {liveInfo.pointsPerMinute != null
                        ? `${liveInfo.pointsPerMinute.toFixed(1)} pts/min (${liveInfo.awayScore + liveInfo.homeScore} total)`
                        : `${liveInfo.awayScore + liveInfo.homeScore} combined pts`}
                    </div>
                  </div>

                  <div className="rounded-lg bg-slate-900/90 border border-slate-800 px-3 py-2">
                    <div className="text-[10px] uppercase tracking-wider text-slate-400 font-bold">
                      Live Projected Final
                    </div>
                    <div className="mt-0.5 font-mono font-bold text-sky-200 text-sm">
                      {liveInfo.liveProjAwayScore != null && liveInfo.liveProjHomeScore != null
                        ? `${game.away_team} ${liveInfo.liveProjAwayScore} – ${game.home_team} ${liveInfo.liveProjHomeScore}`
                        : '—'}
                    </div>
                    <div className="text-[11px] text-slate-400">
                      {liveInfo.liveProjTotal != null ? `Pace ~${liveInfo.liveProjTotal.toFixed(1)} total pts` : ''}
                    </div>
                  </div>

                  <div className="rounded-lg bg-slate-900/90 border border-slate-800 px-3 py-2">
                    <div className="text-[10px] uppercase tracking-wider text-slate-400 font-bold">
                      Projected vs. Bet Line
                    </div>
                    <div
                      className={`mt-0.5 font-mono font-bold text-sm ${
                        liveInfo.coverTone === 'win'
                          ? 'text-emerald-300'
                          : liveInfo.coverTone === 'loss'
                            ? 'text-rose-300'
                            : liveInfo.coverTone === 'tossup'
                              ? 'text-amber-200'
                              : 'text-slate-200'
                      }`}
                    >
                      {liveInfo.projectedBetMargin != null
                        ? `${fmtSigned(liveInfo.projectedBetMargin, 1)} pts cushion`
                        : liveTargetPick?.selection || liveInfo.trendLabel || 'Track live margin'}
                    </div>
                    <div className="text-[11px] text-slate-400 truncate">
                      {liveTargetPick?.selection || `${game.away_team} @ ${game.home_team}`}
                    </div>
                  </div>
                </div>

                {liveInfo.trendDetail && (
                  <p className="text-xs text-slate-200 leading-relaxed">{liveInfo.trendDetail}</p>
                )}
              </section>
            )}

            {isAnalyzing ? (
              <div className="py-14 flex flex-col items-center justify-center gap-3 text-slate-300">
                <Loader2 size={28} className="animate-spin text-indigo-400" aria-hidden="true" />
                <p className="text-sm font-medium">Running multi-source matchup analysis...</p>
                <p className="text-xs text-slate-500">Combining sportsbook lines, BartTorvik, Haslametrics, KenPom, injuries &amp; betting splits.</p>
              </div>
            ) : !analysisResult ? (
              <div className="rounded-xl border border-rose-500/30 bg-rose-950/30 p-4 text-xs text-rose-200">
                Could not load live matchup analysis for this game.
              </div>
            ) : (
              <>
                {/* Clean visual tab bar inside Details modal (replaces long scroll & dropdowns) */}
                <div className="flex flex-wrap items-center gap-1.5 border-b border-slate-800 pb-3" role="tablist" aria-label="Matchup details sections">
                  {[
                    { id: 'overview', label: 'Overview & Lines' },
                    { id: 'stats', label: 'Stats & Four Factors' },
                    { id: 'lineup', label: 'Lineup, Splits & Refs' },
                  ].map((tab) => {
                    const active = modalTab === tab.id;
                    return (
                      <button
                        key={tab.id}
                        type="button"
                        role="tab"
                        aria-selected={active}
                        onClick={() => setModalTab(tab.id)}
                        className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-colors cursor-pointer ${
                          active
                            ? 'bg-indigo-600 text-white'
                            : 'bg-slate-900 text-slate-400 hover:text-slate-200 border border-slate-800'
                        }`}
                      >
                        {tab.label}
                      </button>
                    );
                  })}
                </div>

                {/* 1. Primary Recommendation / Pass Status (Overview) */}
                {modalTab === 'overview' && (topRec ? (
                  <section className="rounded-xl border border-indigo-500/35 bg-gradient-to-br from-indigo-950/45 to-slate-950 p-4 space-y-3">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <span className="text-[10px] font-bold uppercase tracking-widest text-indigo-300">
                          Recommended Bet
                        </span>
                        <h3 className="text-lg font-extrabold text-white mt-0.5">
                          {topRec.selection || topRec.pick}{' '}
                          <span className="font-mono text-emerald-300 text-base">({fmtOdds(topRec.price)})</span>
                        </h3>
                        <p className="text-xs text-slate-300 mt-0.5">
                          {topRec.book || 'Consensus'} · Our Line {topRec.fair_line ?? '—'} vs Sportsbook {topRec.market_line ?? '—'} ·{' '}
                          <strong className="text-emerald-300">
                            {fmtPct(topRec.calibrated_win_prob ?? topRec.win_prob, 1)} Win
                          </strong>{' '}
                          (+{Number((topEv || 0) * 100).toFixed(1)}% EV)
                        </p>
                        {sizeInfo && (
                          <div className="mt-2 inline-flex flex-wrap items-center gap-1.5 px-2.5 py-1 rounded-lg bg-indigo-500/15 border border-indigo-400/35 text-xs text-indigo-100">
                            <span className="font-bold text-indigo-300">Size:</span>
                            <span className="font-mono font-bold text-white">{sizeInfo.detailedLabel}</span>
                          </div>
                        )}
                      </div>

                      <div className="flex items-center gap-2">
                        <span className={`px-2.5 py-1 rounded-full border text-xs font-bold ${conf.badgeCls}`}>
                          {conf.tier}
                        </span>
                        <button
                          type="button"
                          onClick={() =>
                            onAddBet?.({
                              sport: game.sport || 'NCAAM',
                              game: `${game.away_team} @ ${game.home_team}`,
                              market: topRec.bet_type || topRec.market_type,
                              pick: topRec.selection || topRec.pick,
                              line: topRec.market_line,
                              odds: topRec.price,
                              book: topRec.book || 'Consensus',
                              units: sizeInfo?.units,
                              stake: sizeInfo?.dollarStake,
                            })
                          }
                          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold cursor-pointer"
                        >
                          <PlusCircle size={14} aria-hidden="true" />
                          <span>Add Bet</span>
                        </button>
                      </div>
                    </div>
                  </section>
                ) : (
                  <section className="rounded-xl border border-slate-700/80 bg-slate-950/75 p-4 space-y-1">
                    <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">
                      No Bet Recommended
                    </h3>
                    <p className="text-xs text-slate-300">
                      {safeReasonText(analysisResult.block_reason || analysisResult.headline) ||
                        'Sportsbook line matches fair value.'}
                    </p>
                  </section>
                ))}

                {/* Visual Sportsbook vs. Model Comparison + Projected Final Score (Overview) */}
                {modalTab === 'overview' && (
                  <ModelVisualComparison
                    visualData={visualData}
                    projectedScore={projectedScore}
                  />
                )}

                {/* 2. Source Projections (Overview) & Team Efficiency (Stats) */}
                {modalTab === 'overview' && (
                  <section className="rounded-xl border border-slate-800 bg-slate-950/65 p-4 space-y-2.5">
                    <h3 className="text-xs font-bold uppercase tracking-wider text-sky-400">
                      Model Breakdown
                    </h3>
                    <div className="space-y-1.5 text-xs">
                      {[
                        {
                          label: 'BartTorvik',
                          spread: analysisResult.torvik_view?.fair_spread_home ?? sig.torvik?.fair_spread_home,
                          total: analysisResult.torvik_view?.fair_total ?? sig.torvik?.fair_total,
                          score: analysisResult.torvik_view?.projected_score,
                        },
                        {
                          label: 'Haslametrics',
                          spread: analysisResult.haslametrics_view?.fair_spread_home ?? sig.haslametrics?.fair_spread_home,
                          total: analysisResult.haslametrics_view?.fair_total ?? sig.haslametrics?.fair_total,
                          score: analysisResult.haslametrics_view?.projected_score,
                        },
                        {
                          label: 'KenPom',
                          spread: sig.kenpom?.fair_spread_home,
                          total: sig.kenpom?.fair_total,
                          score: null,
                          emptyNote: 'Updating',
                        },
                        {
                          label: 'Basement Bets Final',
                          spread: dbg.mu_spread_final ?? dbg.mu_spread_power ?? analysisResult.outputs?.mu_spread ?? topRec?.fair_line,
                          total: dbg.mu_total_final ?? dbg.mu_total_power ?? analysisResult.outputs?.mu_total,
                          score: null,
                          highlight: true,
                        },
                      ].map((row) => (
                        <div
                          key={row.label}
                          className={`flex items-center justify-between px-2.5 py-1.5 rounded-lg ${
                            row.highlight ? 'bg-indigo-500/15 border border-indigo-500/30 font-semibold' : 'bg-slate-900/80'
                          }`}
                        >
                          <span className="text-slate-200">{row.label}</span>
                          {row.spread == null && row.total == null && row.emptyNote ? (
                            <span className="text-[11px] text-amber-300/90">{row.emptyNote}</span>
                          ) : (
                            <span className="font-mono text-slate-300">
                              Home {row.spread != null ? fmtSigned(row.spread, 1) : '—'} · Total{' '}
                              {row.total != null ? Number(row.total).toFixed(1) : '—'}
                              {row.score ? ` (${row.score})` : ''}
                            </span>
                          )}
                        </div>
                      ))}
                    </div>
                  </section>
                )}

                {modalTab === 'stats' && (
                  <section className="rounded-xl border border-slate-800 bg-slate-950/65 p-4 space-y-2.5">
                    <h3 className="text-xs font-bold uppercase tracking-wider text-emerald-400">
                      Team Efficiency
                    </h3>
                    <table className="w-full text-xs border-collapse">
                      <thead>
                        <tr className="border-b border-slate-800 text-slate-400">
                          <th scope="col" className="py-1 text-left font-medium">Metric</th>
                          <th scope="col" className="py-1 text-right font-medium">{game.away_team}</th>
                          <th scope="col" className="py-1 text-right font-medium">{game.home_team}</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-800/70 font-mono">
                        <tr>
                          <td className="py-1.5 font-sans text-slate-300">Adj. Offense</td>
                          <td className="py-1.5 text-right">{fmtStat(awayStats.adj_off)}</td>
                          <td className="py-1.5 text-right">{fmtStat(homeStats.adj_off)}</td>
                        </tr>
                        <tr>
                          <td className="py-1.5 font-sans text-slate-300">Adj. Defense</td>
                          <td className="py-1.5 text-right">{fmtStat(awayStats.adj_def)}</td>
                          <td className="py-1.5 text-right">{fmtStat(homeStats.adj_def)}</td>
                        </tr>
                        <tr>
                          <td className="py-1.5 font-sans text-slate-300">Tempo</td>
                          <td className="py-1.5 text-right">{fmtStat(awayStats.adj_tempo ?? torvikStats.game_tempo)}</td>
                          <td className="py-1.5 text-right">{fmtStat(homeStats.adj_tempo ?? torvikStats.game_tempo)}</td>
                        </tr>
                      </tbody>
                    </table>
                  </section>
                )}

                {/* 2b. Backend Model Weighting & Situational Adjustments (Overview) */}
                {modalTab === 'overview' && (modelSignals.modelPct != null ||
                  modelSignals.sosMomShift ||
                  modelSignals.restSpotShift ||
                  modelSignals.shootingShift ||
                  modelSignals.blowoutSigmaAdd ||
                  modelSignals.spreadMove ||
                  modelSignals.totalMove) && (
                  <section className="rounded-xl border border-slate-800 bg-slate-950/65 p-4 space-y-2.5">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <h3 className="text-xs font-bold uppercase tracking-wider text-indigo-300">
                        What Moved Our Line
                      </h3>
                      {modelSignals.modelPct != null && (
                        <span className="px-2 py-0.5 rounded-full bg-indigo-500/15 border border-indigo-400/30 text-[11px] font-semibold text-indigo-200">
                          {modelSignals.modelPct}% Team Ratings / {modelSignals.marketPct}% Sportsbook Anchor
                          {modelSignals.convCount >= 2 ? ` · ${modelSignals.convCount} Sources Agree` : ''}
                        </span>
                      )}
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2 text-xs">
                      {modelSignals.modelPct != null && (
                        <div className="rounded-lg bg-slate-900/90 border border-slate-800/80 px-3 py-2">
                          <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
                            Rating Weights
                          </div>
                          <div className="mt-0.5 font-mono text-slate-200">
                            Torvik {Math.round(modelSignals.weights.torvik * 100)}%
                            {modelSignals.weights.haslametrics > 0
                              ? ` · Hasla ${Math.round(modelSignals.weights.haslametrics * 100)}%`
                              : ''}
                            {modelSignals.weights.kenpom > 0
                              ? ` · KenPom ${Math.round(modelSignals.weights.kenpom * 100)}%`
                              : ''}
                          </div>
                        </div>
                      )}

                      {modelSignals.sosMomShift && (
                        <div className="rounded-lg bg-slate-900/90 border border-slate-800/80 px-3 py-2">
                          <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
                            Schedule &amp; Recent Form
                          </div>
                          <div className="mt-0.5 font-mono text-emerald-300">{modelSignals.sosMomShift.text}</div>
                        </div>
                      )}

                      {modelSignals.restSpotShift && (
                        <div className="rounded-lg bg-slate-900/90 border border-slate-800/80 px-3 py-2">
                          <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
                            Rest &amp; Travel Spot
                          </div>
                          <div className="mt-0.5 font-mono text-amber-300">{modelSignals.restSpotShift.text}</div>
                        </div>
                      )}

                      {modelSignals.shootingShift && (
                        <div className="rounded-lg bg-slate-900/90 border border-slate-800/80 px-3 py-2">
                          <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
                            3-Point Shooting Luck
                          </div>
                          <div className="mt-0.5 font-mono text-sky-300">{modelSignals.shootingShift.text}</div>
                        </div>
                      )}

                      {modelSignals.blowoutSigmaAdd && (
                        <div className="rounded-lg bg-slate-900/90 border border-slate-800/80 px-3 py-2">
                          <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
                            Blowout Risk Warning
                          </div>
                          <div className="mt-0.5 text-amber-300">Higher score swing risk (+{modelSignals.blowoutSigmaAdd} pt range)</div>
                        </div>
                      )}

                      {(modelSignals.spreadMove || modelSignals.totalMove) && (
                        <div className="rounded-lg bg-slate-900/90 border border-slate-800/80 px-3 py-2">
                          <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
                            Sportsbook Line Movement
                          </div>
                          <div className="mt-0.5 font-mono text-slate-200">
                            {modelSignals.spreadMove ? `Spread ${modelSignals.spreadMove.text}` : ''}
                            {modelSignals.spreadMove && modelSignals.totalMove ? ' · ' : ''}
                            {modelSignals.totalMove ? `Total ${modelSignals.totalMove.text}` : ''}
                          </div>
                        </div>
                      )}
                    </div>
                  </section>
                )}

                {/* 2c. Four-Factors Visual Edge Breakdown (Stats tab, no dropdowns) */}
                {modalTab === 'stats' && ffDetail?.home && ffDetail?.away && (
                  <section className="rounded-xl border border-slate-800 bg-slate-950/65 p-4 space-y-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <h3 className="text-xs font-bold uppercase tracking-wider text-sky-300">
                        Four-Factors Style Matchup
                      </h3>
                      <span className="text-[11px] text-slate-400">
                        {game.away_team} (left) vs. {game.home_team} (right)
                      </span>
                    </div>
                    <div className="space-y-2.5 text-xs">
                      {[
                        {
                          label: 'Shooting (eFG%)',
                          awayVal: ffDetail.away.off_efg,
                          homeVal: ffDetail.home.off_efg,
                          higherBetter: true,
                          unit: '%',
                        },
                        {
                          label: 'Ball Security (TO%)',
                          awayVal: ffDetail.away.off_to,
                          homeVal: ffDetail.home.off_to,
                          higherBetter: false,
                          unit: '%',
                        },
                        {
                          label: 'Off. Rebounding (OR%)',
                          awayVal: ffDetail.away.off_or,
                          homeVal: ffDetail.home.off_or,
                          higherBetter: true,
                          unit: '%',
                        },
                        {
                          label: 'Free-Throw Rate (FTR)',
                          awayVal: ffDetail.away.off_ftr,
                          homeVal: ffDetail.home.off_ftr,
                          higherBetter: true,
                          unit: '',
                        },
                      ]
                        .filter((r) => r.awayVal != null && r.homeVal != null)
                        .map((row) => {
                          const aNum = Number(row.awayVal);
                          const hNum = Number(row.homeVal);
                          const diff = row.higherBetter ? hNum - aNum : aNum - hNum;
                          const edgeLeader = Math.abs(diff) < 0.4 ? 'Even' : diff > 0 ? game.home_team : game.away_team;
                          const barPct = Math.min(48, Math.max(4, Math.abs(diff) * 4));
                          return (
                            <div key={row.label} className="space-y-1">
                              <div className="flex items-center justify-between text-[11px]">
                                <span className="font-mono text-slate-200">
                                  {aNum.toFixed(1)}{row.unit}
                                </span>
                                <span className="font-semibold text-slate-300">
                                  {row.label}{' '}
                                  <span className="text-[10px] text-slate-400 font-normal">
                                    ({edgeLeader === 'Even' ? 'Even' : `Edge: ${edgeLeader}`})
                                  </span>
                                </span>
                                <span className="font-mono text-slate-200">
                                  {hNum.toFixed(1)}{row.unit}
                                </span>
                              </div>
                              <div className="relative h-2 rounded-full bg-slate-800 overflow-hidden">
                                <div className="absolute inset-y-0 left-1/2 w-px bg-slate-600" aria-hidden="true" />
                                {Math.abs(diff) >= 0.4 && (
                                  <div
                                    className={`absolute inset-y-0 rounded-full ${
                                      diff > 0 ? 'bg-emerald-400/80' : 'bg-sky-400/80'
                                    }`}
                                    style={
                                      diff > 0
                                        ? { left: '50%', width: `${barPct}%` }
                                        : { right: '50%', width: `${barPct}%` }
                                    }
                                  />
                                )}
                              </div>
                            </div>
                          );
                        })}
                    </div>
                  </section>
                )}

                {/* 2d. 1-Click Player Availability Simulator (Lineup tab) */}
                {modalTab === 'lineup' && (rotationAway.length > 0 || rotationHome.length > 0) && (
                  <section className="rounded-xl border border-slate-800 bg-slate-950/65 p-4 space-y-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div>
                        <h3 className="text-xs font-bold uppercase tracking-wider text-amber-300">
                          Player Availability Simulator
                        </h3>
                        <p className="text-[11px] text-slate-400">
                          Check any late scratch OUT to recalculate the fair spread live.
                        </p>
                      </div>
                      {(homeOutPts > 0 || awayOutPts > 0) && (
                        <div className="flex items-center gap-2">
                          <span className="px-2.5 py-1 rounded-full bg-amber-500/15 border border-amber-400/35 text-[11px] font-mono font-bold text-amber-200">
                            Adj Fair Home: {adjustedFairHome != null ? fmtSigned(adjustedFairHome, 1) : '—'} (
                            {fmtSigned(netOutShiftHome, 1)} pts)
                          </span>
                          <button
                            type="button"
                            onClick={() => setOutPlayers({})}
                            className="px-2 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-[11px] font-semibold text-slate-200 cursor-pointer"
                          >
                            Reset
                          </button>
                        </div>
                      )}
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
                      {[
                        { side: 'away', team: game.away_team, players: rotationAway },
                        { side: 'home', team: game.home_team, players: rotationHome },
                      ].map((grp) => (
                        <div key={grp.side} className="rounded-lg border border-slate-800/80 bg-slate-900/60 p-2.5 space-y-1">
                          <div className="text-[11px] font-bold text-slate-300 pb-1 border-b border-slate-800">
                            {grp.team}
                          </div>
                          {grp.players.length === 0 ? (
                            <p className="text-[11px] text-slate-500 py-1">No rotation data yet.</p>
                          ) : (
                            grp.players.map((p) => {
                              const checked = Boolean(outPlayers[`${grp.side}:${p.name}`]);
                              return (
                                <label
                                  key={p.name}
                                  className={`flex items-center justify-between gap-2 min-h-[44px] px-2 rounded-lg cursor-pointer transition-colors ${
                                    checked ? 'bg-rose-950/40 text-rose-200 line-through' : 'hover:bg-slate-800/60 text-slate-200'
                                  }`}
                                >
                                  <span className="flex items-center gap-2.5 min-w-0">
                                    <input
                                      type="checkbox"
                                      checked={checked}
                                      onChange={() => togglePlayerOut(grp.side, p.name)}
                                      className="w-4 h-4 accent-rose-500 cursor-pointer focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-400 shrink-0"
                                    />
                                    <span className="truncate font-medium">{p.name}</span>
                                  </span>
                                  <span className="font-mono text-[11px] text-slate-400 shrink-0">
                                    {p.min_pct != null ? `${p.min_pct}% min · ` : ''}
                                    -{p.est_impact_pts}pt
                                  </span>
                                </label>
                              );
                            })
                          )}
                        </div>
                      ))}
                    </div>
                  </section>
                )}

                {/* 3. Injuries & Public Splits (Lineup tab) */}
                {modalTab === 'lineup' && (injImpact || rawInjuries.length > 0 || splits) && (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {(injImpact || rawInjuries.length > 0) && (
                      <section className="rounded-xl border border-amber-500/30 bg-amber-950/15 p-4 space-y-2">
                        <h3 className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-amber-300">
                          <AlertTriangle size={13} aria-hidden="true" />
                          <span>Player Injury Pricing</span>
                        </h3>
                        {injImpact && (
                          <p className="text-xs text-slate-200">
                            Model adjustment: <strong className="font-mono">{fmtSigned(injImpact.spread_adj || 0, 1)} pts</strong>{' '}
                            spread · <strong className="font-mono">{fmtSigned(injImpact.total_adj || 0, 1)} pts</strong> total.
                          </p>
                        )}
                        <ul className="space-y-1 text-xs text-slate-300">
                          {(injImpact?.impact_players || rawInjuries).slice(0, 6).map((p, idx) => (
                            <li key={idx} className="flex items-center justify-between gap-2 bg-slate-950/60 rounded px-2 py-1">
                              <span>
                                <strong>{p.player}</strong> ({p.team || p.side}) — {p.status}
                              </span>
                              {p.est_pts != null && (
                                <span className="font-mono text-amber-300">~{Number(p.est_pts).toFixed(1)} pts</span>
                              )}
                            </li>
                          ))}
                        </ul>
                      </section>
                    )}

                    {splits && (
                      <section className="rounded-xl border border-slate-800 bg-slate-950/65 p-4 space-y-2.5">
                        <h3 className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-indigo-300">
                          <Users size={13} aria-hidden="true" />
                          <span>Public Bets vs. Big Money</span>
                        </h3>
                        <div className="space-y-2.5 text-xs">
                          {['SPREAD', 'TOTAL'].map((mkt) => {
                            const row = splits[mkt];
                            if (!row) return null;
                            const mktLabel = mkt === 'SPREAD' ? 'Point Spread' : 'Over / Under';
                            return (
                              <div key={mkt} className="rounded-lg bg-slate-900/90 p-2.5 space-y-2">
                                <div className="font-bold text-slate-400 text-[10px] uppercase tracking-wider">{mktLabel}</div>
                                {Object.entries(row).map(([side, vals]) => {
                                  if (!vals || typeof vals !== 'object' || vals.bet_pct == null) return null;
                                  const betPct = Math.max(0, Math.min(100, Number(vals.bet_pct) || 0));
                                  const handlePctRaw = vals.handle_pct != null ? Number(vals.handle_pct) : null;
                                  const handlePct = handlePctRaw != null ? Math.max(0, Math.min(100, handlePctRaw)) : null;
                                  const isSharp = handlePct != null && handlePct - betPct >= 10;
                                  return (
                                    <div key={side} className="space-y-1">
                                      <div className="flex items-center justify-between gap-2 text-slate-200">
                                        <span className="font-semibold">{side}</span>
                                        <span className="font-mono text-[11px]">
                                          {betPct}% bets /{' '}
                                          <strong className={isSharp ? 'text-emerald-300' : 'text-slate-100'}>
                                            {handlePct != null ? `${handlePct}% money` : '—'}
                                          </strong>
                                        </span>
                                      </div>
                                      <div className="space-y-1" aria-hidden="true">
                                        <div className="h-1.5 w-full rounded-full bg-slate-800 overflow-hidden">
                                          <div className="h-full rounded-full bg-indigo-400/75" style={{ width: `${betPct}%` }} />
                                        </div>
                                        {handlePct != null && (
                                          <div className="h-1.5 w-full rounded-full bg-slate-800 overflow-hidden">
                                            <div
                                              className={`h-full rounded-full ${isSharp ? 'bg-emerald-400' : 'bg-amber-400/80'}`}
                                              style={{ width: `${handlePct}%` }}
                                            />
                                          </div>
                                        )}
                                      </div>
                                    </div>
                                  );
                                })}
                              </div>
                            );
                          })}
                        </div>
                      </section>
                    )}
                  </div>
                )}

                {/* 4. Referee Crew Override (Lineup tab, no dropdown) */}
                {modalTab === 'lineup' && (
                  <section className="rounded-xl border border-slate-800 bg-slate-950/65 p-4 space-y-2.5">
                    <h3 className="text-xs font-bold uppercase tracking-wider text-slate-300">
                      Referee Crew
                    </h3>
                    <form onSubmit={handleSaveRefs} className="space-y-2">
                      <div className="grid grid-cols-3 gap-2">
                        {[
                          { id: 'ref-input-1', label: 'Ref 1', value: ref1, setter: setRef1 },
                          { id: 'ref-input-2', label: 'Ref 2', value: ref2, setter: setRef2 },
                          { id: 'ref-input-3', label: 'Ref 3', value: ref3, setter: setRef3 },
                        ].map((f) => (
                          <div key={f.id}>
                            <label htmlFor={f.id} className="block text-[10px] text-slate-400 mb-1">
                              {f.label}
                            </label>
                            <input
                              id={f.id}
                              type="text"
                              value={f.value}
                              onChange={(e) => f.setter(e.target.value)}
                              placeholder="Name"
                              className="w-full px-2 py-1 rounded-lg bg-slate-900 border border-slate-700 text-xs text-slate-100"
                            />
                          </div>
                        ))}
                      </div>
                      <div className="flex items-center justify-between gap-2">
                        <button
                          type="submit"
                          disabled={refsSaving}
                          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-xs font-semibold text-slate-100 cursor-pointer disabled:opacity-50"
                        >
                          <RefreshCw size={12} className={refsSaving ? 'animate-spin' : ''} aria-hidden="true" />
                          <span>{refsSaving ? 'Re-running...' : 'Save & Re-run'}</span>
                        </button>
                        {refsMessage && (
                          <span
                            className={`text-xs ${refsMessage.type === 'ok' ? 'text-emerald-300' : 'text-rose-300'}`}
                          >
                            {refsMessage.text}
                          </span>
                        )}
                      </div>
                    </form>
                  </section>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </dialog>
  );
};

export default TodayMatchupModal;
