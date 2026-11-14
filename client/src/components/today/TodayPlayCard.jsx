import React from 'react';
import {
  PlusCircle,
  BarChart2,
  ChevronDown,
  ChevronUp,
  Sparkles,
  AlertTriangle,
  TrendingUp,
} from 'lucide-react';
import ModelVisualComparison from './ModelVisualComparison';
import {
  fmtTimeEt,
  fmtOdds,
  fmtPct,
  fmtSigned,
  getConfidenceMeta,
  getRecEv,
  normalizeMovementTag,
  buildWhyPickReasons,
  getProjectedScore,
  explainPickPlainly,
  buildVisualModelData,
  getLiveGameStatus,
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
      ? `${(kellyRaw * 100).toFixed(1)}% bankroll`
      : '0.5u–1.0u';
  const tags = Array.isArray(rec?.movement_tags) ? rec.movement_tags.slice(0, 3) : [];
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
  const liveInfo = getLiveGameStatus(game, rec);

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

      {/* Live / Final In-Game Score & Cover Tracker */}
      {liveInfo.hasScore && (
        <div className="rounded-xl border border-slate-700/80 bg-slate-950/90 px-3 py-2 flex flex-wrap items-center justify-between gap-2 text-xs">
          <div className="flex items-center gap-2 font-mono font-bold text-white">
            <span className="text-[10px] uppercase tracking-wider font-sans text-slate-400">
              {liveInfo.isFinal ? 'Final Score' : 'Live Score'}
            </span>
            <span>
              {game?.away_team} {liveInfo.awayScore} – {game?.home_team} {liveInfo.homeScore}
            </span>
          </div>
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
      )}

      {/* Streamlined 3-column comparison strip (zero duplicated info) */}
      <div className="today-play-metrics">
        <div className="rounded-xl bg-slate-950/75 border border-slate-800/90 px-3 py-2 min-w-0">
          <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Book vs. Model</div>
          <div className="mt-0.5 text-sm font-mono font-bold text-white truncate">
            {marketDisplay} <span className="text-slate-500">→</span>{' '}
            <span className="text-sky-300">{fairDisplay}</span>
          </div>
          <div className="text-[11px] text-slate-400 truncate">
            {rec?.edge_points != null ? `${Math.abs(Number(rec.edge_points)).toFixed(1)} pt cushion` : 'Fair line'} · {rec?.book || 'Consensus'}
          </div>
        </div>

        <div className="rounded-xl bg-slate-950/75 border border-slate-800/90 px-3 py-2 min-w-0">
          <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Expected Value</div>
          <div className="mt-0.5 text-sm font-mono font-bold text-emerald-300 truncate">
            {evDecimal !== null ? `+${(evDecimal * 100).toFixed(1)}% EV` : '—'}
          </div>
          <div className="text-[11px] text-indigo-200 truncate">
            {winProb != null ? `${fmtPct(winProb, 1)} win` : 'Model edge'} · {kellyUnits}
          </div>
        </div>

        <div className="rounded-xl bg-slate-950/75 border border-slate-800/90 px-3 py-2 min-w-0">
          <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Proj. Score</div>
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

      {/* Concise signal tags (max 3 + injury impact) */}
      {(tags.length > 0 || injImpact) && (
        <div className="flex flex-wrap items-center gap-1.5">
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
              Injury {fmtSigned(injImpact.spread_adj || 0, 1)}pt spread
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
            <span>{isExpanded ? 'Hide breakdown' : `More breakdown (${reasons.length - 1})`}</span>
            {isExpanded ? <ChevronUp size={13} aria-hidden="true" /> : <ChevronDown size={13} aria-hidden="true" />}
          </button>
        ) : (
          <span className="text-[11px] text-slate-500">Click Details for matchup tables</span>
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
