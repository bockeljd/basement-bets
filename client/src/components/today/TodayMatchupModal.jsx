import React, { useEffect, useRef, useState } from 'react';
import {
  X,
  PlusCircle,
  Loader2,
  AlertTriangle,
  TrendingUp,
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
} from './todayHelpers';

const TodayMatchupModal = ({
  game,
  analysisResult,
  correlationResult,
  matchupProfile,
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
  const liveInfo = getLiveGameStatus(game, topRec);
  const fmtStat = (v) => (v != null && Number.isFinite(Number(v)) ? Number(v).toFixed(1) : '—');

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
                {liveInfo.coverText && (
                  <span
                    className={`px-2 py-0.5 rounded-full text-[11px] font-bold border ${
                      liveInfo.coverTone === 'win'
                        ? 'bg-emerald-500/15 border-emerald-500/40 text-emerald-300'
                        : liveInfo.coverTone === 'loss'
                          ? 'bg-rose-500/15 border-rose-500/40 text-rose-300'
                          : 'bg-slate-800 border-slate-700 text-slate-200'
                    }`}
                  >
                    {liveInfo.coverText}
                  </span>
                )}
              </div>
              <h2 id="matchup-dialog-title" className="mt-1 text-lg sm:text-xl font-bold text-white truncate">
                {game.away_team} @ {game.home_team}
              </h2>
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
                {/* 1. Primary Recommendation / Pass Status */}
                {topRec ? (
                  <section className="rounded-xl border border-indigo-500/35 bg-gradient-to-br from-indigo-950/45 to-slate-950 p-4 space-y-3">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <span className="text-[10px] font-bold uppercase tracking-widest text-indigo-300">
                          Recommended Play
                        </span>
                        <h3 className="text-lg font-extrabold text-white mt-0.5">
                          {topRec.selection || topRec.pick}{' '}
                          <span className="font-mono text-emerald-300 text-base">({fmtOdds(topRec.price)})</span>
                        </h3>
                        <p className="text-xs text-slate-300 mt-0.5">
                          {topRec.book || 'Consensus'} · Fair Line {topRec.fair_line ?? '—'} vs Market {topRec.market_line ?? '—'} ·{' '}
                          <strong className="text-emerald-300">
                            +{Number((topEv || 0) * 100).toFixed(1)}% expected value
                          </strong>{' '}
                          · Win Chance {fmtPct(topRec.calibrated_win_prob ?? topRec.win_prob, 1)}
                        </p>
                      </div>

                      <div className="flex items-center gap-2">
                        <span className={`px-2.5 py-1 rounded-full border text-xs font-bold ${conf.badgeCls}`}>
                          {conf.tier} CONFIDENCE
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
                            })
                          }
                          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold cursor-pointer"
                        >
                          <PlusCircle size={14} aria-hidden="true" />
                          <span>Add Bet</span>
                        </button>
                      </div>
                    </div>

                    {Array.isArray(topRec.movement_tags) && topRec.movement_tags.length > 0 && (
                      <div className="flex flex-wrap gap-1.5">
                        {topRec.movement_tags.map((t) => {
                          const meta = normalizeMovementTag(t);
                          return (
                            <span
                              key={t}
                              className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-slate-900 border border-slate-700 text-[11px] font-semibold text-slate-200"
                            >
                              <TrendingUp size={10} className="text-emerald-400" aria-hidden="true" />
                              {meta.label}
                            </span>
                          );
                        })}
                      </div>
                    )}

                    {(analysisResult.headline || topRec.narrative) && (
                      <p className="text-xs text-slate-300 leading-relaxed border-t border-slate-800/80 pt-2.5">
                        {topRec.narrative || analysisResult.headline}
                      </p>
                    )}
                  </section>
                ) : (
                  <section className="rounded-xl border border-slate-700/80 bg-slate-950/75 p-4 space-y-1">
                    <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">
                      No Bet Recommended Right Now
                    </h3>
                    <p className="text-xs text-slate-200">
                      {safeReasonText(analysisResult.block_reason || analysisResult.headline) ||
                        'Current market lines and safety guardrails do not meet our +2.0% EV / 1.5-point edge publish threshold.'}
                    </p>
                  </section>
                )}

                {/* Visual Sportsbook vs. Model Comparison + Projected Final Score */}
                <ModelVisualComparison
                  visualData={visualData}
                  projectedScore={projectedScore}
                />

                {/* 2. Source Projections & Team Efficiency */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <section className="rounded-xl border border-slate-800 bg-slate-950/65 p-4 space-y-2.5">
                    <h3 className="text-xs font-bold uppercase tracking-wider text-sky-400">
                      Model Projections vs Market
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
                          emptyNote: 'Off — needs 2026-27 KenPom data',
                        },
                        {
                          label: 'Final Model Blend',
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

                  <section className="rounded-xl border border-slate-800 bg-slate-950/65 p-4 space-y-2.5">
                    <h3 className="text-xs font-bold uppercase tracking-wider text-emerald-400">
                      Team Strength Comparison
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
                          <td className="py-1.5 font-sans text-slate-300">Offense (Pts / 100 poss.)</td>
                          <td className="py-1.5 text-right">{fmtStat(awayStats.adj_off)}</td>
                          <td className="py-1.5 text-right">{fmtStat(homeStats.adj_off)}</td>
                        </tr>
                        <tr>
                          <td className="py-1.5 font-sans text-slate-300">Defense (Allowed / 100 poss.)</td>
                          <td className="py-1.5 text-right">{fmtStat(awayStats.adj_def)}</td>
                          <td className="py-1.5 text-right">{fmtStat(homeStats.adj_def)}</td>
                        </tr>
                        <tr>
                          <td className="py-1.5 font-sans text-slate-300">Game Pace (Poss. / 40m)</td>
                          <td className="py-1.5 text-right">{fmtStat(awayStats.adj_tempo ?? torvikStats.game_tempo)}</td>
                          <td className="py-1.5 text-right">{fmtStat(homeStats.adj_tempo ?? torvikStats.game_tempo)}</td>
                        </tr>
                      </tbody>
                    </table>
                  </section>
                </div>

                {/* 3. Injuries & Public Splits */}
                {(injImpact || rawInjuries.length > 0 || splits) && (
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
                      <section className="rounded-xl border border-slate-800 bg-slate-950/65 p-4 space-y-2">
                        <h3 className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-indigo-300">
                          <Users size={13} aria-hidden="true" />
                          <span>Public Bets vs. Big Money</span>
                        </h3>
                        <div className="space-y-2 text-xs">
                          {['SPREAD', 'TOTAL'].map((mkt) => {
                            const row = splits[mkt];
                            if (!row) return null;
                            return (
                              <div key={mkt} className="rounded-lg bg-slate-900/90 p-2 space-y-1">
                                <div className="font-bold text-slate-400 text-[10px] uppercase">{mkt}</div>
                                {Object.entries(row).map(([side, vals]) =>
                                  vals && typeof vals === 'object' && vals.bet_pct != null ? (
                                    <div key={side} className="flex items-center justify-between text-slate-200">
                                      <span>{side}</span>
                                      <span className="font-mono">
                                        {vals.bet_pct}% bets / <strong>{vals.handle_pct ?? '—'}% money</strong>
                                      </span>
                                    </div>
                                  ) : null
                                )}
                              </div>
                            );
                          })}
                        </div>
                      </section>
                    )}
                  </div>
                )}

                {/* 4. Historical Correlations & Referees */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <section className="rounded-xl border border-slate-800 bg-slate-950/65 p-4 space-y-2">
                    <h3 className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-purple-300">
                      <ShieldCheck size={13} aria-hidden="true" />
                      <span>Similar Matchup History</span>
                    </h3>
                    {correlationResult ? (() => {
                      const archObj = correlationResult.archetype;
                      const archLabel = typeof archObj === 'string'
                        ? archObj
                        : archObj?.key || [archObj?.pace_bin, archObj?.eff_bin, archObj?.spread_bucket].filter(Boolean).join(' · ') || 'Standard';
                      const corrData = correlationResult.correlations || correlationResult;
                      const overHome = corrData?.pairs?.over_home_cover;
                      return (
                        <div className="text-xs text-slate-300 space-y-1">
                          <p>
                            Matchup style: <strong className="text-white">{archLabel}</strong>
                            {corrData?.n != null ? ` (based on ${corrData.n} past games)` : ''}
                          </p>
                          {corrData?.status === 'valid' && overHome ? (
                            <p className="text-emerald-300">
                              Over + Home Cover hit rate:{' '}
                              <strong>{fmtPct(overHome.p_joint ?? overHome.p_ab, 1)}</strong>
                              {overHome.lift != null ? ` (${Number(overHome.lift).toFixed(2)}x more likely than average)` : ''}
                            </p>
                          ) : (
                            <p className="text-slate-400">
                              {correlationResult.status === 'no_spread'
                                ? 'Waiting on a live sportsbook spread to match similar past games.'
                                : 'Building sample size — not enough similar past games yet for parlay trends.'}
                            </p>
                          )}
                        </div>
                      );
                    })() : (
                      <p className="text-xs text-slate-400">
                        Not enough past games with a similar style to show historical trends yet.
                      </p>
                    )}
                  </section>

                  <section className="rounded-xl border border-slate-800 bg-slate-950/65 p-4 space-y-2.5">
                    <h3 className="text-xs font-bold uppercase tracking-wider text-slate-300">
                      Referee Crew Override
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
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </dialog>
  );
};

export default TodayMatchupModal;
