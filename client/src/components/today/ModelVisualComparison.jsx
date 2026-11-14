import React from 'react';
import { Target, Layers } from 'lucide-react';

/**
 * Visual Sportsbook vs. Basement Model comparison bar + projected final score.
 * Highlights the point cushion between the sportsbook line and independent ratings.
 */
const ModelVisualComparison = ({ visualData, projectedScore, compact = false }) => {
  if (!visualData && !projectedScore) return null;

  const leftPct = visualData ? Math.min(visualData.bookPct, visualData.fairPct) : 0;
  const widthPct = visualData ? Math.max(2, Math.abs(visualData.fairPct - visualData.bookPct)) : 0;

  return (
    <div
      className={`rounded-xl border border-slate-800/90 bg-slate-950/75 ${
        compact ? 'p-3 space-y-2.5' : 'p-4 space-y-3'
      }`}
    >
      {/* Projected Final Score (full mode only; compact tiles show it in the metric strip) */}
      {!compact && projectedScore && (
        <div className="flex flex-wrap items-center justify-between gap-2 pb-2 border-b border-slate-800/80">
          <div className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wider text-slate-400">
            <Target size={12} className="text-sky-400" aria-hidden="true" />
            <span>Model Projected Score</span>
          </div>
          <div className="text-xs font-bold text-white flex flex-wrap items-center gap-1.5">
            <span className="font-mono text-sky-200">{projectedScore.text}</span>
            <span className="text-[11px] font-normal text-slate-400">
              ({projectedScore.margin === 0 ? 'toss-up' : `${projectedScore.winner} by ~${projectedScore.margin}`})
            </span>
          </div>
        </div>
      )}

      {/* Visual Line Comparison Bar */}
      {visualData && (
        <div className={compact ? 'space-y-1.5' : 'space-y-2'}>
          {!compact && (
            <div className="flex flex-wrap items-center justify-between gap-2 text-[11px]">
              <span className="font-semibold text-slate-300">
                {visualData.sideLabel} Scale
              </span>
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-emerald-500/15 border border-emerald-500/35 text-emerald-300 font-mono font-bold">
                {visualData.cushionPts.toFixed(1)} pt cushion vs. books
              </span>
            </div>
          )}

          {/* Horizontal tug-of-war scale */}
          <div className="relative pt-5 pb-4 px-1" aria-hidden="true">
            <div className="relative h-2.5 rounded-full bg-slate-800 border border-slate-700/80">
              {/* Highlighted edge cushion between Book and Fair line */}
              <div
                className="absolute top-0 bottom-0 rounded-full bg-gradient-to-r from-emerald-500/60 to-sky-400/70"
                style={{ left: `${leftPct}%`, width: `${widthPct}%` }}
              />

              {/* Independent rating dots */}
              {visualData.sources.map((src) => (
                <div
                  key={src.id}
                  title={`${src.label}: ${src.displayLine}`}
                  className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-2.5 h-2.5 rounded-full border border-slate-950"
                  style={{ left: `${src.pct}%`, backgroundColor: src.color }}
                />
              ))}

              {/* Sportsbook marker */}
              <div
                className="absolute -top-5 -translate-x-1/2 flex flex-col items-center"
                style={{ left: `${visualData.bookPct}%` }}
              >
                <span className="px-1.5 py-0.5 rounded bg-amber-500/20 border border-amber-400/50 text-[10px] font-mono font-bold text-amber-200 whitespace-nowrap">
                  Book {visualData.bookLabel}
                </span>
                <span className="w-0.5 h-2 bg-amber-400" />
              </div>

              {/* Model Fair marker */}
              <div
                className="absolute -bottom-5 -translate-x-1/2 flex flex-col items-center"
                style={{ left: `${visualData.fairPct}%` }}
              >
                <span className="w-0.5 h-2 bg-sky-400" />
                <span className="px-1.5 py-0.5 rounded bg-sky-500/20 border border-sky-400/60 text-[10px] font-mono font-bold text-sky-200 whitespace-nowrap">
                  Model {visualData.fairLabel}
                </span>
              </div>
            </div>
          </div>

          {/* Independent source chips */}
          {visualData.sources.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5 pt-2 text-[11px]">
              <span className="inline-flex items-center gap-1 text-slate-400 font-semibold mr-0.5">
                <Layers size={11} aria-hidden="true" />
                Inputs:
              </span>
              {visualData.sources.map((src) => (
                <span
                  key={src.id}
                  className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md bg-slate-900 border border-slate-700/80 text-slate-200 font-mono"
                >
                  <span
                    className="w-2 h-2 rounded-full shrink-0"
                    style={{ backgroundColor: src.color }}
                    aria-hidden="true"
                  />
                  <span className="font-sans text-slate-400">{src.label}</span>
                  <strong className="text-white">{src.displayLine}</strong>
                </span>
              ))}
            </div>
          )}

          {!compact && visualData.summary && (
            <p className="text-[11px] text-slate-300 leading-relaxed">
              {visualData.summary}
            </p>
          )}
        </div>
      )}
    </div>
  );
};

export default ModelVisualComparison;
