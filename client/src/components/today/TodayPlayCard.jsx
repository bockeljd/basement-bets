import React from 'react';
import {
  PlusCircle,
  BarChart2,
  ChevronDown,
  ChevronUp,
  Sparkles,
  AlertTriangle,
  TrendingUp,
  TrendingDown,
  Activity,
} from 'lucide-react';
import ModelVisualComparison from './ModelVisualComparison';
import {
  fmtTimeEt,
  fmtOdds,
  fmtSigned,
  fmtPct,
  getConfidenceMeta,
  getRecEv,
  normalizeMovementTag,
  buildWhyPickReasons,
  getProjectedScore,
  explainPickPlainly,
  buildVisualModelData,
  getLiveGameStatus,
  getModelSignalData,
} from './todayHelpers';

const TONE_BADGES = {
  emerald: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/35',
  amber: 'bg-amber-500/15 text-amber-300 border-amber-500/35',
  rose: 'bg-rose-500/15 text-rose-300 border-rose-500/35',
  indigo: 'bg-indigo-500/15 text-indigo-300 border-indigo-500/35',
  blue: 'bg-sky-500/15 text-sky-300 border-sky-500/35',
  slate: 'bg-slate-800 text-slate-300 border-slate-700',
};

const TodayPlayCard = ({
  rank,
  game,
  rec,
  context = null,
  isExpanded,
  onToggleExpand,
  onOpenDetails,
  onAddBet,
}) => {
  const conf = getConfidenceMeta(rec);
  const evDecimal = getRecEv(rec);
  const betType = String(rec?.bet_type || rec?.market_type || 'BET').toUpperCase();
  const winProb = rec?.calibrated_win_prob ?? rec?.win_prob;
  const kellyRaw = Number(rec?.kelly ?? rec?.kelly_fraction);
  const kellyUnits =
    Number.isFinite(kellyRaw) && kellyRaw > 0
      ? `Stake ${(kellyRaw * 100).toFixed(1)}%`
      : 'Standard bet';
  const tags = Array.isArray(rec?.movement_tags) ? rec.movement_tags.slice(0, 2) : [];
  const reasons = buildWhyPickReasons(rec, game).filter(
    (r) => r.label !== 'Model vs Market' && r.label !== 'Independent Ratings'
  );
  const primaryReason = reasons[0]?.text || null;
  const extraReasons = reasons.slice(1);
  const injImpact = rec?.signals?.injuries_impact;

  const analysisLike = context ? { context } : null;
  const projectedScore = getProjectedScore(game, analysisLike, rec);
  const plain = explainPickPlainly(rec, game);
  const visualData = buildVisualModelData(rec, game, analysisLike);
  const liveInfo = getLiveGameStatus(game, rec, context);
  const modelSignals = getModelSignalData(rec, context, null, game);
  const cardSignals = modelSignals.pills.slice(0, 2);
  const liveBadgeText = liveInfo.isLive && liveInfo.trendLabel
    ? `${liveInfo.trendLabel}${liveInfo.liveWinProb != null ? ` (${Math.round(liveInfo.liveWinProb * 100)}%)` : ''}`
    : liveInfo.coverText;
  const liveProjLine =
    liveInfo.liveProjAwayScore != null && liveInfo.liveProjHomeScore != null
      ? `Proj. Finish: ${game?.away_team} ${liveInfo.liveProjAwayScore} – ${game?.home_team} ${liveInfo.liveProjHomeScore}`
      : liveInfo.gameTrendText;

  const pickLabel = rec?.selection || rec?.pick || game?.home_team || 'Pick';
  const matchupLabel = `${game?.away_team || 'Away'} at ${game?.home_team || 'Home'}`;

  const marketDisplay =
    betType === 'ML'
      ? fmtOdds(rec?.price)
      : rec?.market_line !== null && rec?.market_line !== undefined
        ? `${betType === 'SPREAD' ? fmtSigned(rec.market_line, 1) : rec.market_line}`
        : '—';

  const fairDisplay =
    betType === 'ML'
      ? fmtPct(winProb, 1)
      : rec?.fair_line !== null && rec?.fair_line !== undefined
        ? `${betType === 'SPREAD' ? fmtSigned(rec.fair_line, 1) : Number(rec.fair_line).toFixed(1)}`
        : '—';

  return (
    <article
      className="today-play-card rounded-2xl border border-slate-700/80 bg-gradient-to-br from-slate-900 via-slate-900/95 to-slate-950 p-4 shadow-lg flex flex-col gap-3 transition-colors hover:border-indigo-500/40"
      aria-label={`Top play ${rank}: ${pickLabel}`}
    >
      {/* Header row */}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
            <span className="inline-flex items-center justify-center px-2 py-0.5 rounded-md bg-indigo-500/20 text-indigo-300 border border-indigo-400/30 font-extrabold">
              #{rank}
            </span>
            <span className="font-semibold uppercase tracking-wide text-slate-300">{betType}</span>
            <span>·</span>
            {liveInfo.isLive ? (
              <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-rose-500/20 border border-rose-500/45 text-rose-200 font-bold text-[11px]">
                <span className="w-1.5 h-1.5 rounded-full bg-rose-400 animate-pulse" aria-hidden="true" />
                LIVE {liveInfo.statusDetail ? `· ${liveInfo.statusDetail}` : ''}
              </span>
            ) : liveInfo.isFinal ? (
              <span className="px-2 py-0.5 rounded-full bg-slate-800 border border-slate-700 text-slate-200 font-bold text-[11px]">
                FINAL
              </span>
            ) : (
              <time dateTime={game?.start_time || ''}>{fmtTimeEt(game?.start_time)} ET</time>
            )}
          </div>
          <h3 className="mt-1 text-base font-bold text-white leading-snug truncate">
            {pickLabel}{' '}
            {rec?.price != null && (
              <span className="font-mono text-sm font-semibold text-emerald-300">({fmtOdds(rec.price)})</span>
            )}
          </h3>
          <p className="text-xs text-slate-400 truncate">
            {game?.away_team} @ {game?.home_team}
            {plain?.shortRule ? ` · ${plain.shortRule}` : ''}
          </p>
        </div>

        <span className={`px-2.5 py-0.5 rounded-full border text-[11px] font-bold tracking-wide shrink-0 ${conf.badgeCls}`}>
          {conf.tier} CONFIDENCE{conf.score !== null ? ` · ${conf.score}` : ''}
        </span>
      </div>

      {/* Live / Final In-Game Score, Pace & Win/Loss Trend Tracker */}
      {liveInfo.hasScore && (
        <div
          className={`rounded-xl border px-3 py-2.5 space-y-2 text-xs ${
            liveInfo.isLive && liveInfo.coverTone === 'win'
              ? 'border-emerald-500/40 bg-emerald-950/20'
              : liveInfo.isLive && liveInfo.coverTone === 'loss'
                ? 'border-rose-500/40 bg-rose-950/20'
                : liveInfo.isLive && liveInfo.coverTone === 'tossup'
                  ? 'border-amber-500/40 bg-amber-950/20'
                  : 'border-slate-700/80 bg-slate-950/90'
          }`}
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap items-center gap-2 font-mono font-bold text-white">
              <span className="text-[10px] uppercase tracking-wider font-sans text-slate-400">
                {liveInfo.isFinal ? 'Final Score' : 'Live Score'}
              </span>
              <span>
                {game?.away_team} {liveInfo.awayScore} – {game?.home_team} {liveInfo.homeScore}
              </span>
              {liveInfo.isLive && liveInfo.progressPct > 0 && (
                <span className="px-1.5 py-0.5 rounded bg-slate-800/90 border border-slate-700 text-[10px] font-sans font-semibold text-slate-300">
                  {liveInfo.periodLabel} · {liveInfo.progressPct}% played
                </span>
              )}
            </div>

            {liveBadgeText && (
              <span
                className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-bold border ${
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
                  <TrendingUp size={11} aria-hidden="true" />
                ) : liveInfo.coverTone === 'loss' ? (
                  <TrendingDown size={11} aria-hidden="true" />
                ) : (
                  <Activity size={11} aria-hidden="true" />
                )}
                <span>{liveBadgeText}</span>
              </span>
            )}
          </div>

          {liveInfo.isLive && (
            <div className="space-y-1.5">
              {liveInfo.trendDetail && (
                <p className="text-[11px] text-slate-200 leading-snug">{liveInfo.trendDetail}</p>
              )}
              <div className="flex flex-wrap items-center justify-between gap-2 text-[10px] text-slate-400">
                <span>{liveProjLine}</span>
                {liveInfo.pointsPerMinute != null && (
                  <span className="font-mono text-slate-300">
                    {liveInfo.pointsPerMinute.toFixed(1)} pts/min
                  </span>
                )}
              </div>
              <div
                className="w-full h-1.5 rounded-full bg-slate-800 overflow-hidden"
                role="progressbar"
                aria-label="Live game progress"
                aria-valuenow={liveInfo.progressPct || 0}
                aria-valuemin={0}
                aria-valuemax={100}
              >
                <div
                  className={`h-full transition-all ${
                    liveInfo.coverTone === 'win'
                      ? 'bg-emerald-400'
                      : liveInfo.coverTone === 'loss'
                        ? 'bg-rose-400'
                        : liveInfo.coverTone === 'tossup'
                          ? 'bg-amber-400'
                          : 'bg-sky-400'
                  }`}
                  style={{ width: `${Math.min(100, Math.max(4, liveInfo.progressPct || 0))}%` }}
                />
              </div>
            </div>
          )}
        </div>
      )}

      {/* Streamlined 3-column comparison strip (zero duplicated info) */}
      <div className="today-play-metrics">
        <div className="rounded-xl bg-slate-950/75 border border-slate-800/90 px-3 py-2 min-w-0">
          <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Sportsbook vs. Our Line</div>
          <div className="mt-0.5 text-sm font-mono font-bold text-white truncate">
            {marketDisplay} <span className="text-slate-500">→</span>{' '}
            <span className="text-sky-300">{fairDisplay}</span>
          </div>
          <div className="text-[11px] text-slate-400 truncate">
            {rec?.edge_points != null ? `${Math.abs(Number(rec.edge_points)).toFixed(1)} pt edge` : 'Fair line'} · {rec?.book || 'Consensus'}
          </div>
        </div>

        <div className="rounded-xl bg-slate-950/75 border border-slate-800/90 px-3 py-2 min-w-0">
          <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Win Chance &amp; Value</div>
          <div className="mt-0.5 text-sm font-mono font-bold text-emerald-300 truncate">
            {winProb != null ? `${fmtPct(winProb, 1)} to win` : evDecimal !== null ? `+${(evDecimal * 100).toFixed(1)}% value` : '—'}
          </div>
          <div className="text-[11px] text-indigo-200 truncate">
            {evDecimal !== null ? `+${(evDecimal * 100).toFixed(1)}% profit edge` : 'Positive edge'} · {kellyUnits}
          </div>
        </div>

        <div className="rounded-xl bg-slate-950/75 border border-slate-800/90 px-3 py-2 min-w-0">
          <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Projected Score</div>
          <div className="mt-0.5 text-sm font-mono font-bold text-sky-200 truncate">
            {projectedScore ? projectedScore.shortText : '—'}
          </div>
          <div className="text-[11px] text-slate-400 truncate">
            {projectedScore
              ? projectedScore.margin === 0
                ? 'Projected toss-up'
                : `${projectedScore.winner} by ~${projectedScore.margin}`
              : 'Model total projection'}
          </div>
        </div>
      </div>

      {/* Compact Visual Sportsbook vs. Model Scale + Inputs */}
      <ModelVisualComparison
        visualData={visualData}
        projectedScore={projectedScore}
        compact
      />

      {/* Non-duplicate qualitative edge note (e.g., sharp move, key driver) */}
      {primaryReason && (
        <div className="rounded-xl border border-indigo-500/20 bg-slate-950/60 px-3 py-2 flex items-start gap-2 text-xs text-slate-200 leading-relaxed">
          <Sparkles size={13} className="text-indigo-400 shrink-0 mt-0.5" aria-hidden="true" />
          <span>{primaryReason}</span>
        </div>
      )}

      {/* Concise plain-English key tags */}
      {(cardSignals.length > 0 || tags.length > 0 || injImpact) && (
        <div className="flex flex-wrap items-center gap-1.5">
          {cardSignals.map((pill) => (
            <span
              key={pill.id}
              className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-[11px] font-semibold ${TONE_BADGES[pill.tone] || TONE_BADGES.slate}`}
            >
              {pill.label}
            </span>
          ))}
          {tags.map((rawTag) => {
            const norm = normalizeMovementTag(rawTag);
            return (
              <span
                key={rawTag}
                className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-[11px] font-semibold ${TONE_BADGES[norm.tone] || TONE_BADGES.slate}`}
              >
                <TrendingUp size={10} aria-hidden="true" />
                {norm.label}
              </span>
            );
          })}
          {injImpact && (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full border border-amber-500/35 bg-amber-500/10 text-amber-300 text-[11px] font-semibold">
              <AlertTriangle size={10} aria-hidden="true" />
              Injury {fmtSigned(injImpact.spread_adj || 0, 1)} pts
            </span>
          )}
        </div>
      )}

      {/* Footer: Optional extra breakdown + disambiguated action buttons */}
      <div className="flex flex-wrap items-center justify-between gap-2 pt-1 border-t border-slate-800/80">
        {reasons.length > 1 ? (
          <button
            type="button"
            aria-expanded={isExpanded}
            onClick={onToggleExpand}
            className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-semibold text-slate-300 hover:text-white hover:bg-slate-800/80 transition cursor-pointer"
          >
            <span>{isExpanded ? 'Hide reasons' : `More reasons (${reasons.length - 1})`}</span>
            {isExpanded ? <ChevronUp size={13} aria-hidden="true" /> : <ChevronDown size={13} aria-hidden="true" />}
          </button>
        ) : (
          <span />
        )}

        <div className="flex items-center gap-2 ml-auto">
          <button
            type="button"
            onClick={() => onOpenDetails(game)}
            aria-label={`Details for ${matchupLabel}`}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-xs font-semibold text-slate-100 transition cursor-pointer"
          >
            <BarChart2 size={13} aria-hidden="true" />
            <span>Details</span>
          </button>

          <button
            type="button"
            onClick={() =>
              onAddBet?.({
                sport: game?.sport || 'NCAAM',
                game: `${game?.away_team} @ ${game?.home_team}`,
                market: rec?.bet_type || rec?.market_type,
                pick: rec?.selection || rec?.pick,
                line: rec?.market_line,
                odds: rec?.price,
                book: rec?.book || 'Consensus',
              })
            }
            aria-label={`Add Bet ${pickLabel}`}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-600/20 hover:bg-emerald-600/30 border border-emerald-500/40 text-xs font-bold text-emerald-300 transition cursor-pointer"
          >
            <PlusCircle size={13} aria-hidden="true" />
            <span>Add Bet</span>
          </button>
        </div>
      </div>

      {isExpanded && extraReasons.length > 0 && (
        <div className="rounded-xl border border-slate-800 bg-slate-950/85 p-3 space-y-2 text-xs">
          {extraReasons.map((item, idx) => (
            <div key={idx} className="flex flex-col gap-0.5">
              <span className="text-[10px] font-bold uppercase tracking-wider text-indigo-300">
                {item.label}
              </span>
              <p className="text-slate-200 leading-relaxed">{item.text}</p>
            </div>
          ))}
        </div>
      )}
    </article>
  );
};

export default TodayPlayCard;
