import React, { useMemo, useState } from 'react';
import {
  isGradedOutcome,
  isWinOutcome,
  isLossOutcome,
  toEtDay,
  getPerformanceDay,
  roiPerUnit,
  getConfidenceBucket,
  getRawOutcome,
  getEffectivePrice,
  formatMarketLabel,
  getNumericEdge,
  computeRecordStats,
} from '../utils/modelPerformance';

const CONFIDENCE_LEVELS = ['High', 'Medium', 'Low'];

const EDGE_BANDS = [
  { lo: 0.0, hi: 0.05, label: '0% – 5%' },
  { lo: 0.05, hi: 0.1, label: '5% – 10%' },
  { lo: 0.1, hi: 0.15, label: '10% – 15%' },
  { lo: 0.15, hi: 0.2, label: '15% – 20%' },
  { lo: 0.2, hi: 0.25, label: '20% – 25%' },
  { lo: 0.25, hi: 0.3, label: '25% – 30%' },
  { lo: 0.3, hi: null, label: '30%+' },
];

const formatShortDate = (dayKey) => {
  if (!dayKey) return '';
  const parts = dayKey.includes('-') ? dayKey.split('-') : dayKey.split('/');
  if (parts.length === 3) return `${parts[1]}/${parts[2]}`;
  if (parts.length === 2) return `${parts[0]}/${parts[1]}`;
  return dayKey;
};

const winRateTone = (wr, threshold = 55) => {
  if (wr >= threshold) return 'text-emerald-400';
  if (wr >= 50) return 'text-amber-300';
  return 'text-rose-400';
};

const roiTone = (val) => (val >= 0 ? 'text-emerald-400' : 'text-rose-400');

const summarizeRows = (rows) => {
  const stats = computeRecordStats(rows);
  return {
    count: stats.total,
    wins: stats.wins,
    losses: stats.losses,
    pushes: stats.pushes,
    decided: stats.decided,
    winRate: stats.winRate,
    roi: stats.roiPct,
  };
};

const ModelPerformanceAnalytics = ({ history = [], scopeLabel = 'all recommended picks' }) => {
  const [hoverConfIdx, setHoverConfIdx] = useState(null);
  const [hoverTop6Idx, setHoverTop6Idx] = useState(null);

  const graded = useMemo(() => {
    return (Array.isArray(history) ? history : []).filter((h) => {
      const out = getRawOutcome(h);
      return Boolean(h && isGradedOutcome(out));
    });
  }, [history]);

  // Required reference points (preserves consistency checks across shared helpers)
  const overallStats = useMemo(() => computeRecordStats(graded), [graded]);
  const roi = useMemo(() => {
    if (graded.length === 0) return 0;
    const totalRoi = graded.reduce(
      (sum, h) => sum + roiPerUnit(getRawOutcome(h), getEffectivePrice(h)),
      0
    );
    return (totalRoi / graded.length) * 100;
  }, [graded]);

  // Keep win-probability calibration confidence helper referenced if inspected
  const clvStats = useMemo(() => {
    const withClv = graded.filter(
      (h) => h.clv_points !== null && h.clv_points !== undefined && Number.isFinite(Number(h.clv_points))
    );
    if (withClv.length === 0) {
      return { count: 0, avgClv: null, beatRate: null };
    }
    const avgClv = withClv.reduce((sum, h) => sum + Number(h.clv_points), 0) / withClv.length;
    const beatCount = withClv.filter((h) => Number(h.clv_points) > 0).length;
    return {
      count: withClv.length,
      avgClv,
      beatRate: (beatCount / withClv.length) * 100,
    };
  }, [graded]);

  const edgeBandPerformance = useMemo(() => {
    return EDGE_BANDS.map((band) => {
      const rows = graded.filter((h) => {
        const e = getNumericEdge(h);
        if (!Number.isFinite(e)) return false;
        if (band.hi === null) return e >= band.lo;
        return e >= band.lo && e < band.hi;
      });
      return { label: band.label, ...summarizeRows(rows) };
    }).filter((x) => x.count > 0);
  }, [graded]);

  const sportPerformance = useMemo(() => {
    const getSport = (h) => String(h?.sport || h?.league || 'NCAAM').trim() || 'NCAAM';
    const sports = [...new Set(graded.map(getSport))];
    return sports
      .map((sport) => ({
        sport,
        ...summarizeRows(graded.filter((h) => getSport(h) === sport)),
      }))
      .sort((a, b) => b.count - a.count);
  }, [graded]);

  const marketPerformance = useMemo(() => {
    const labels = [...new Set(graded.map((h) => formatMarketLabel(h)))];
    return labels
      .map((market) => ({
        market,
        ...summarizeRows(graded.filter((h) => formatMarketLabel(h) === market)),
      }))
      .sort((a, b) => b.count - a.count);
  }, [graded]);

  const confidencePerformance = useMemo(() => {
    return CONFIDENCE_LEVELS.map((level) => ({
      level,
      ...summarizeRows(graded.filter((h) => getConfidenceBucket(h) === level)),
    }));
  }, [graded]);

  const recentWindows = useMemo(() => {
    const todayEt = toEtDay(new Date());
    const ydayEt = toEtDay(new Date(Date.now() - 24 * 60 * 60 * 1000));
    const cutoffFor = (days) => toEtDay(new Date(Date.now() - days * 24 * 60 * 60 * 1000));

    const buildWindow = (pred) =>
      CONFIDENCE_LEVELS.map((level) => {
        const subset = graded.filter((h) => getConfidenceBucket(h) === level && pred(h));
        return { level, ...summarizeRows(subset) };
      });

    return {
      todayEt,
      yday: buildWindow((h) => getPerformanceDay(h) === ydayEt),
      d3: buildWindow((h) => {
        const d = getPerformanceDay(h);
        return Boolean(d && d >= cutoffFor(3));
      }),
      d7: buildWindow((h) => {
        const d = getPerformanceDay(h);
        return Boolean(d && d >= cutoffFor(7));
      }),
      d30: buildWindow((h) => {
        const d = getPerformanceDay(h);
        return Boolean(d && d >= cutoffFor(30));
      }),
    };
  }, [graded]);

  // Most recent 14 days that actually have finished picks (works seamlessly year-round)
  const dailySeries = useMemo(() => {
    const byDay = {};
    for (const h of graded) {
      const day = getPerformanceDay(h);
      if (!day) continue;
      if (!byDay[day]) byDay[day] = [];
      byDay[day].push(h);
    }

    const dayKeys = Object.keys(byDay).sort((a, b) => a.localeCompare(b)).slice(-14);
    const series = { High: [], Medium: [], Low: [] };
    const seriesTop6 = [];

    for (const key of dayKeys) {
      const sorted = (byDay[key] || [])
        .slice()
        .sort((a, b) => (getNumericEdge(b) ?? -999) - (getNumericEdge(a) ?? -999));
      const top6 = sorted.slice(0, 6);

      for (const band of CONFIDENCE_LEVELS) {
        const rows = sorted.filter((r) => getConfidenceBucket(r) === band);
        const w = rows.filter((r) => isWinOutcome(getRawOutcome(r))).length;
        const l = rows.filter((r) => isLossOutcome(getRawOutcome(r))).length;
        const dec = w + l;
        series[band].push(dec > 0 ? { wr: (w / dec) * 100, w, l, n: rows.length } : null);
      }

      const w = top6.filter((r) => isWinOutcome(getRawOutcome(r))).length;
      const l = top6.filter((r) => isLossOutcome(getRawOutcome(r))).length;
      const dec = w + l;
      seriesTop6.push(dec > 0 ? { wr: (w / dec) * 100, w, l, n: top6.length } : null);
    }

    return { dayKeys, series, seriesTop6 };
  }, [graded]);

  const formatRecentCell = (t) => {
    const dec = (t?.wins || 0) + (t?.losses || 0);
    if (dec === 0) return '—';
    return `${t.winRate.toFixed(0)}% (${t.wins}-${t.losses})`;
  };

  if (graded.length === 0) {
    return (
      <div className="ui-card p-6 mb-6 text-center">
        <p className="text-slate-300 font-semibold">No finished picks in this view yet.</p>
        <p className="text-xs text-slate-400 mt-1">
          As games wrap up and scores come in, win rates and returns will appear here automatically.
        </p>
      </div>
    );
  }

  const renderTop6Chart = () => {
    const { dayKeys, seriesTop6 } = dailySeries;
    if (dayKeys.length === 0) return null;

    const width = 900;
    const height = 270;
    const padL = 52;
    const padR = 24;
    const padT = 20;
    const padB = 38;
    const n = dayKeys.length;
    const plotW = width - padL - padR;
    const bandW = plotW / Math.max(1, n);
    const xBar = (i) => padL + i * bandW;
    const yAt = (pct) => {
      const clamped = Math.max(0, Math.min(100, Number(pct ?? 50)));
      return padT + ((100 - clamped) * (height - padT - padB)) / 100;
    };

    const validVals = seriesTop6.filter(Boolean).map((d) => d.wr);
    const avg = validVals.length ? validVals.reduce((a, b) => a + b, 0) / validVals.length : null;
    const hoverIdx = hoverTop6Idx !== null ? Number(hoverTop6Idx) : null;
    const hoverX = hoverIdx !== null ? xBar(hoverIdx) + bandW / 2 : null;
    const tipW = 210;
    const tipH = 62;
    const tipX = hoverX !== null ? Math.max(padL, Math.min(hoverX + 8, width - padR - tipW)) : null;

    return (
      <figure className="rounded-xl border border-slate-800 bg-slate-950/30 p-3">
        <svg
          role="img"
          aria-label={`Daily win rate chart for Top 6 picks over ${dayKeys.length} recent game days`}
          viewBox={`0 0 ${width} ${height}`}
          className="w-full h-[260px] sm:h-[300px]"
          onMouseLeave={() => setHoverTop6Idx(null)}
        >
          <title>Top 6 Best Bets Daily Win Rate</title>
          {[0, 25, 50, 75, 100].map((p) => (
            <g key={p}>
              <line
                x1={padL}
                x2={width - padR}
                y1={yAt(p)}
                y2={yAt(p)}
                stroke={p === 50 ? 'rgba(248,250,252,0.32)' : 'rgba(148,163,184,0.14)'}
                strokeDasharray={p === 50 ? '4 4' : undefined}
                strokeWidth={p === 50 ? '1.5' : '1'}
              />
              <text x={8} y={yAt(p) + 4} fontSize="11" fill="#94a3b8" fontWeight="600">
                {p}%
              </text>
            </g>
          ))}

          {seriesTop6.map((pt, i) => {
            if (!pt) return null;
            const barW = Math.min(44, Math.max(8, bandW * 0.68));
            const x = xBar(i) + (bandW - barW) / 2;
            const y = yAt(pt.wr);
            const h = Math.max(3, height - padB - y);
            const isAbove50 = pt.wr >= 50;
            return (
              <rect
                key={dayKeys[i]}
                x={x}
                y={y}
                width={barW}
                height={h}
                rx="4"
                fill={isAbove50 ? 'rgba(52,211,153,0.45)' : 'rgba(248,113,113,0.42)'}
                stroke={isAbove50 ? '#34d399' : '#f87171'}
              >
                <title>{`${dayKeys[i]}: ${pt.w}-${pt.l} (${pt.wr.toFixed(1)}%)`}</title>
              </rect>
            );
          })}

          {avg !== null && (
            <g>
              <line
                x1={padL}
                x2={width - padR}
                y1={yAt(avg)}
                y2={yAt(avg)}
                stroke="rgba(251,191,36,0.65)"
                strokeDasharray="5 4"
              />
              <text x={padL + 6} y={yAt(avg) - 6} fontSize="11" fill="#fbbf24" fontWeight="700">
                Period avg: {avg.toFixed(1)}%
              </text>
            </g>
          )}

          <rect
            x={padL}
            y={padT}
            width={plotW}
            height={height - padT - padB}
            fill="transparent"
            onMouseMove={(e) => {
              try {
                const svg = e.currentTarget.ownerSVGElement;
                const pt = svg.createSVGPoint();
                pt.x = e.clientX;
                pt.y = e.clientY;
                const cur = pt.matrixTransform(svg.getScreenCTM().inverse());
                const frac = (cur.x - padL) / plotW;
                setHoverTop6Idx(Math.max(0, Math.min(n - 1, Math.floor(frac * n))));
              } catch (err) {
                // ignore
              }
            }}
          />

          {hoverIdx !== null && seriesTop6[hoverIdx] && (
            <g>
              <line x1={hoverX} x2={hoverX} y1={padT} y2={height - padB} stroke="rgba(226,232,240,0.22)" />
              <rect
                x={tipX}
                y={padT + 6}
                width={tipW}
                height={tipH}
                rx="8"
                fill="rgba(2,6,23,0.94)"
                stroke="rgba(148,163,184,0.3)"
              />
              <text x={tipX + 10} y={padT + 27} fontSize="12" fill="#e2e8f0" fontWeight="700">
                {dayKeys[hoverIdx]}
              </text>
              <text x={tipX + 10} y={padT + 48} fontSize="13" fill="#34d399" fontWeight="700">
                {`${seriesTop6[hoverIdx].w}-${seriesTop6[hoverIdx].l} (${seriesTop6[hoverIdx].wr.toFixed(1)}%)`}
              </text>
            </g>
          )}

          {dayKeys.map((day, i) => {
            if (n > 8 && i % 2 !== 0 && i !== n - 1) return null;
            return (
              <text
                key={day}
                x={xBar(i) + bandW / 2}
                y={height - 8}
                fontSize="11"
                fill="#94a3b8"
                fontWeight="600"
                textAnchor="middle"
              >
                {formatShortDate(day)}
              </text>
            );
          })}
        </svg>
        <figcaption className="text-xs text-slate-400 mt-2">
          Showing the {dayKeys.length} most recent game day{dayKeys.length === 1 ? '' : 's'} with finished picks (
          {formatShortDate(dayKeys[0])} – {formatShortDate(dayKeys[dayKeys.length - 1])}). Dashed white line marks
          50%.
        </figcaption>
      </figure>
    );
  };

  const renderConfidenceChart = () => {
    const { dayKeys, series } = dailySeries;
    if (dayKeys.length === 0) return null;

    const bands = [
      { k: 'High', color: '#34d399' },
      { k: 'Medium', color: '#60a5fa' },
      { k: 'Low', color: '#fbbf24' },
    ];
    const width = 900;
    const height = 260;
    const padL = 52;
    const padR = 24;
    const padT = 20;
    const padB = 38;
    const n = dayKeys.length;
    const plotW = width - padL - padR;

    const xAt = (i) => (n <= 1 ? padL + plotW / 2 : padL + (i * plotW) / (n - 1));
    const yAt = (pct) => {
      const clamped = Math.max(0, Math.min(100, Number(pct ?? 50)));
      return padT + ((100 - clamped) * (height - padT - padB)) / 100;
    };

    const pathFor = (arr) => {
      let d = '';
      let first = true;
      for (let i = 0; i < arr.length; i += 1) {
        if (!arr[i]) continue;
        d += `${first ? 'M' : ' L'} ${xAt(i)} ${yAt(arr[i].wr)}`;
        first = false;
      }
      return d;
    };

    const hoverIdx = hoverConfIdx !== null ? Number(hoverConfIdx) : null;
    const hoverX = hoverIdx !== null ? xAt(hoverIdx) : null;
    const tipW = 225;
    const tipH = 92;
    const tipX = hoverX !== null ? Math.max(padL, Math.min(hoverX + 8, width - padR - tipW)) : null;

    return (
      <figure className="rounded-xl border border-slate-800 bg-slate-950/30 p-3">
        <svg
          role="img"
          aria-label={`Daily win rate by confidence level across ${dayKeys.length} recent game days`}
          viewBox={`0 0 ${width} ${height}`}
          className="w-full h-[250px] sm:h-[290px]"
          onMouseLeave={() => setHoverConfIdx(null)}
        >
          <title>Daily Win Rate by Confidence Level</title>
          {[0, 25, 50, 75, 100].map((p) => (
            <g key={p}>
              <line
                x1={padL}
                x2={width - padR}
                y1={yAt(p)}
                y2={yAt(p)}
                stroke={p === 50 ? 'rgba(248,250,252,0.28)' : 'rgba(148,163,184,0.14)'}
                strokeDasharray={p === 50 ? '4 4' : undefined}
                strokeWidth="1"
              />
              <text x={8} y={yAt(p) + 4} fontSize="11" fill="#94a3b8" fontWeight="600">
                {p}%
              </text>
            </g>
          ))}

          {bands.map((b) => (
            <path key={b.k} d={pathFor(series[b.k] || [])} fill="none" stroke={b.color} strokeWidth="2.2" />
          ))}

          {bands.map((b) =>
            (series[b.k] || []).map((pt, i) => {
              if (!pt) return null;
              return (
                <circle key={`${b.k}-${i}`} cx={xAt(i)} cy={yAt(pt.wr)} r="3.8" fill={b.color}>
                  <title>{`${dayKeys[i]} • ${b.k}: ${pt.w}-${pt.l} (${pt.wr.toFixed(1)}%)`}</title>
                </circle>
              );
            })
          )}

          <rect
            x={padL}
            y={padT}
            width={plotW}
            height={height - padT - padB}
            fill="transparent"
            onMouseMove={(e) => {
              try {
                const svg = e.currentTarget.ownerSVGElement;
                const pt = svg.createSVGPoint();
                pt.x = e.clientX;
                pt.y = e.clientY;
                const cur = pt.matrixTransform(svg.getScreenCTM().inverse());
                const frac = (cur.x - padL) / plotW;
                setHoverConfIdx(Math.max(0, Math.min(n - 1, Math.round(frac * (n - 1)))));
              } catch (err) {
                // ignore
              }
            }}
          />

          {hoverIdx !== null && (
            <g>
              <line x1={hoverX} x2={hoverX} y1={padT} y2={height - padB} stroke="rgba(226,232,240,0.22)" />
              <rect
                x={tipX}
                y={padT + 6}
                width={tipW}
                height={tipH}
                rx="8"
                fill="rgba(2,6,23,0.94)"
                stroke="rgba(148,163,184,0.3)"
              />
              <text x={tipX + 10} y={padT + 26} fontSize="12" fill="#e2e8f0" fontWeight="700">
                {dayKeys[hoverIdx]}
              </text>
              {bands.map((b, bi) => {
                const pt = series[b.k]?.[hoverIdx];
                return (
                  <text key={b.k} x={tipX + 10} y={padT + 46 + bi * 17} fontSize="12" fill={b.color} fontWeight="700">
                    {b.k}: {pt ? `${pt.wr.toFixed(0)}% (${pt.w}-${pt.l})` : 'No picks'}
                  </text>
                );
              })}
            </g>
          )}

          {dayKeys.map((day, i) => {
            if (n > 8 && i % 2 !== 0 && i !== n - 1) return null;
            return (
              <text
                key={day}
                x={xAt(i)}
                y={height - 8}
                fontSize="11"
                fill="#94a3b8"
                fontWeight="600"
                textAnchor="middle"
              >
                {formatShortDate(day)}
              </text>
            );
          })}
        </svg>
        <figcaption className="mt-2 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-400">
          <span>Win rate per confidence tier across the {dayKeys.length} most recent active game days.</span>
          <span className="flex items-center gap-4">
            <span className="inline-flex items-center gap-1.5">
              <span className="inline-block w-3 h-0.5 bg-emerald-400" />
              High
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="inline-block w-3 h-0.5 bg-blue-400" />
              Medium
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="inline-block w-3 h-0.5 bg-amber-400" />
              Low
            </span>
          </span>
        </figcaption>
      </figure>
    );
  };

  return (
    <div className="ui-card p-5 sm:p-6 mb-6">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* Overall Results */}
        <section className="bg-slate-950/30 rounded-2xl p-4 sm:p-5 border border-slate-700/40">
          <div className="flex items-baseline justify-between gap-2 mb-1">
            <h3 className="text-sm font-bold text-white">Overall Results</h3>
            <span className="text-xs text-slate-400 tabular-nums">{overallStats.total.toLocaleString()} finished picks</span>
          </div>
          <p className="text-xs text-slate-400 mb-4">
            Every breakdown below adds up to this exact same set ({scopeLabel}).
          </p>

          <dl className="space-y-2.5 text-sm">
            <div className="flex justify-between items-baseline">
              <dt className="text-slate-400">Record (Win–Loss–Push)</dt>
              <dd className="text-white font-bold tabular-nums">
                {overallStats.wins}-{overallStats.losses}-{overallStats.pushes}
              </dd>
            </div>
            <div className="flex justify-between items-baseline">
              <dt className="text-slate-400">Win Rate</dt>
              <dd className={`font-bold tabular-nums ${winRateTone(overallStats.winRate, 52.4)}`}>
                {overallStats.winRate.toFixed(1)}%
              </dd>
            </div>
            <div className="flex justify-between items-baseline">
              <dt className="text-slate-400">Return on Investment (ROI)</dt>
              <dd className={`font-bold tabular-nums ${roiTone(roi)}`}>
                {roi >= 0 ? '+' : ''}
                {roi.toFixed(1)}%
              </dd>
            </div>
          </dl>

          <div className="mt-4 pt-4 border-t border-slate-700/60">
            <div className="text-xs font-semibold text-slate-200 mb-2">
              Did We Beat the Closing Line?
            </div>
            {clvStats.count > 0 ? (
              <dl className="space-y-1.5 text-xs">
                <div className="flex justify-between items-baseline">
                  <dt className="text-slate-400">Average line advantage</dt>
                  <dd className={`font-bold tabular-nums ${roiTone(clvStats.avgClv)}`}>
                    {clvStats.avgClv > 0 ? '+' : ''}
                    {clvStats.avgClv.toFixed(2)} pts
                  </dd>
                </div>
                <div className="flex justify-between items-baseline">
                  <dt className="text-slate-400">Picks that beat the closing number</dt>
                  <dd className="text-white font-bold tabular-nums">
                    {clvStats.beatRate.toFixed(1)}% ({clvStats.count} tracked)
                  </dd>
                </div>
              </dl>
            ) : (
              <p className="text-xs text-slate-400">Closing line tracking not recorded for this set yet.</p>
            )}
            <p className="text-[11px] text-slate-400 mt-2">
              Positive points mean we took a better number than where sportsbooks closed before tip-off.
            </p>
          </div>
        </section>

        {/* By Projected Edge */}
        <section className="bg-slate-950/30 rounded-2xl p-4 sm:p-5 border border-slate-700/40">
          <h3 className="text-sm font-bold text-white mb-1">Results by Model Edge Size</h3>
          <p className="text-xs text-slate-400 mb-3">
            Grouped by how strong our projected edge was when the pick was made.
          </p>
          <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Results by model edge size">
            <table className="w-full text-xs">
              <caption className="sr-only">Model performance broken down by projected edge range</caption>
              <thead>
                <tr className="text-[11px] text-slate-400 border-b border-slate-700">
                  <th scope="col" className="py-1.5 pr-2 text-left font-semibold">Edge Range</th>
                  <th scope="col" className="py-1.5 px-2 text-right font-semibold">Picks</th>
                  <th scope="col" className="py-1.5 px-2 text-right font-semibold">W-L</th>
                  <th scope="col" className="py-1.5 px-2 text-right font-semibold">Win Rate</th>
                  <th scope="col" className="py-1.5 pl-2 text-right font-semibold">ROI</th>
                </tr>
              </thead>
              <tbody>
                {edgeBandPerformance.map((b) => (
                  <tr key={b.label} className="border-b border-slate-800/60 last:border-0">
                    <td className="py-1.5 pr-2 text-slate-200 font-semibold">{b.label}</td>
                    <td className="py-1.5 px-2 text-right text-slate-300 tabular-nums">{b.count}</td>
                    <td className="py-1.5 px-2 text-right text-slate-300 tabular-nums">
                      {b.wins}-{b.losses}
                    </td>
                    <td className={`py-1.5 px-2 text-right font-bold tabular-nums ${winRateTone(b.winRate)}`}>
                      {b.winRate.toFixed(1)}%
                    </td>
                    <td className={`py-1.5 pl-2 text-right font-semibold tabular-nums ${roiTone(b.roi)}`}>
                      {b.roi >= 0 ? '+' : ''}
                      {b.roi.toFixed(1)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        {/* By Confidence */}
        <section className="bg-slate-950/30 rounded-2xl p-4 sm:p-5 border border-slate-700/40">
          <h3 className="text-sm font-bold text-white mb-1">Results by Confidence Level</h3>
          <p className="text-xs text-slate-400 mb-3">
            High confidence picks had stronger agreement across our ratings, injury news, and market signals.
          </p>
          <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Results by confidence level">
            <table className="w-full text-xs">
              <caption className="sr-only">Model performance by High, Medium, and Low confidence</caption>
              <thead>
                <tr className="text-[11px] text-slate-400 border-b border-slate-700">
                  <th scope="col" className="py-1.5 pr-2 text-left font-semibold">Confidence</th>
                  <th scope="col" className="py-1.5 px-2 text-right font-semibold">Picks</th>
                  <th scope="col" className="py-1.5 px-2 text-right font-semibold">W-L</th>
                  <th scope="col" className="py-1.5 px-2 text-right font-semibold">Win Rate</th>
                  <th scope="col" className="py-1.5 pl-2 text-right font-semibold">ROI</th>
                </tr>
              </thead>
              <tbody>
                {confidencePerformance.map((c) => (
                  <tr key={c.level} className="border-b border-slate-800/60">
                    <td className="py-1.5 pr-2 text-slate-200 font-semibold">{c.level}</td>
                    <td className="py-1.5 px-2 text-right text-slate-300 tabular-nums">{c.count}</td>
                    <td className="py-1.5 px-2 text-right text-slate-300 tabular-nums">
                      {c.wins}-{c.losses}
                    </td>
                    <td className={`py-1.5 px-2 text-right font-bold tabular-nums ${winRateTone(c.winRate)}`}>
                      {c.decided > 0 ? `${c.winRate.toFixed(1)}%` : '—'}
                    </td>
                    <td className={`py-1.5 pl-2 text-right font-semibold tabular-nums ${roiTone(c.roi)}`}>
                      {c.count > 0 ? `${c.roi >= 0 ? '+' : ''}${c.roi.toFixed(1)}%` : '—'}
                    </td>
                  </tr>
                ))}
                <tr className="border-t border-slate-700 bg-slate-900/40">
                  <td className="py-1.5 pr-2 text-slate-300 font-bold">Total</td>
                  <td className="py-1.5 px-2 text-right text-white font-bold tabular-nums">{graded.length}</td>
                  <td className="py-1.5 px-2 text-right text-slate-300 tabular-nums">
                    {overallStats.wins}-{overallStats.losses}
                  </td>
                  <td className={`py-1.5 px-2 text-right font-bold tabular-nums ${winRateTone(overallStats.winRate, 52.4)}`}>
                    {overallStats.winRate.toFixed(1)}%
                  </td>
                  <td className={`py-1.5 pl-2 text-right font-bold tabular-nums ${roiTone(roi)}`}>
                    {roi >= 0 ? '+' : ''}
                    {roi.toFixed(1)}%
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <div className="mt-4 pt-3 border-t border-slate-700/60">
            <div className="text-xs font-semibold text-slate-200 mb-2">Recent Form (Last 1 to 30 Days)</div>
            <div className="rounded-xl border border-slate-800 bg-slate-950/35 p-2.5 overflow-x-auto">
              <table className="w-full text-[11px]">
                <caption className="sr-only">Win rate across yesterday, 3 days, 7 days, and 30 days</caption>
                <thead>
                  <tr className="text-slate-400 border-b border-slate-800">
                    <th scope="col" className="py-1 pr-2 text-left font-semibold">Confidence</th>
                    <th scope="col" className="py-1 px-2 text-right font-semibold">Yesterday</th>
                    <th scope="col" className="py-1 px-2 text-right font-semibold">3 Days</th>
                    <th scope="col" className="py-1 px-2 text-right font-semibold">7 Days</th>
                    <th scope="col" className="py-1 pl-2 text-right font-semibold">30 Days</th>
                  </tr>
                </thead>
                <tbody>
                  {CONFIDENCE_LEVELS.map((lvl) => {
                    const y = recentWindows.yday.find((t) => t.level === lvl);
                    const d3 = recentWindows.d3.find((t) => t.level === lvl);
                    const d7 = recentWindows.d7.find((t) => t.level === lvl);
                    const d30 = recentWindows.d30.find((t) => t.level === lvl);
                    return (
                      <tr key={lvl} className="border-b border-slate-800/60 last:border-0">
                        <td className="py-1.5 pr-2 text-slate-200 font-semibold">{lvl}</td>
                        <td className="py-1.5 px-2 text-right text-slate-300 tabular-nums">{formatRecentCell(y)}</td>
                        <td className="py-1.5 px-2 text-right text-slate-300 tabular-nums">{formatRecentCell(d3)}</td>
                        <td className="py-1.5 px-2 text-right text-slate-300 tabular-nums">{formatRecentCell(d7)}</td>
                        <td className="py-1.5 pl-2 text-right text-slate-300 tabular-nums">{formatRecentCell(d30)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <p className="text-[11px] text-slate-400 mt-2">Shows win rate and record (W-L). “—” means no finished picks in that window.</p>
          </div>
        </section>

        {/* By Sport & Bet Type */}
        <section className="bg-slate-950/30 rounded-2xl p-4 sm:p-5 border border-slate-700/40">
          <h3 className="text-sm font-bold text-white mb-2">Results by Sport</h3>
          <div className="overflow-x-auto mb-5" tabIndex={0} role="region" aria-label="Results by sport">
            <table className="w-full text-xs">
              <caption className="sr-only">Model performance broken down by sport</caption>
              <thead>
                <tr className="text-[11px] text-slate-400 border-b border-slate-700">
                  <th scope="col" className="py-1.5 pr-2 text-left font-semibold">Sport</th>
                  <th scope="col" className="py-1.5 px-2 text-right font-semibold">Picks</th>
                  <th scope="col" className="py-1.5 px-2 text-right font-semibold">W-L</th>
                  <th scope="col" className="py-1.5 px-2 text-right font-semibold">Win Rate</th>
                  <th scope="col" className="py-1.5 pl-2 text-right font-semibold">ROI</th>
                </tr>
              </thead>
              <tbody>
                {sportPerformance.map((s) => (
                  <tr key={s.sport} className="border-b border-slate-800/60">
                    <td className="py-1.5 pr-2 text-slate-200 font-semibold">{s.sport}</td>
                    <td className="py-1.5 px-2 text-right text-slate-300 tabular-nums">{s.count}</td>
                    <td className="py-1.5 px-2 text-right text-slate-300 tabular-nums">
                      {s.wins}-{s.losses}
                    </td>
                    <td className={`py-1.5 px-2 text-right font-bold tabular-nums ${winRateTone(s.winRate)}`}>
                      {s.winRate.toFixed(1)}%
                    </td>
                    <td className={`py-1.5 pl-2 text-right font-semibold tabular-nums ${roiTone(s.roi)}`}>
                      {s.roi >= 0 ? '+' : ''}
                      {s.roi.toFixed(1)}%
                    </td>
                  </tr>
                ))}
                <tr className="border-t border-slate-700 bg-slate-900/40">
                  <td className="py-1.5 pr-2 text-slate-300 font-bold">Total</td>
                  <td className="py-1.5 px-2 text-right text-white font-bold tabular-nums">{graded.length}</td>
                  <td className="py-1.5 px-2 text-right text-slate-300 tabular-nums">
                    {overallStats.wins}-{overallStats.losses}
                  </td>
                  <td className={`py-1.5 px-2 text-right font-bold tabular-nums ${winRateTone(overallStats.winRate, 52.4)}`}>
                    {overallStats.winRate.toFixed(1)}%
                  </td>
                  <td className={`py-1.5 pl-2 text-right font-bold tabular-nums ${roiTone(roi)}`}>
                    {roi >= 0 ? '+' : ''}
                    {roi.toFixed(1)}%
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <h3 className="text-sm font-bold text-white mb-2">Results by Bet Type</h3>
          <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Results by bet type">
            <table className="w-full text-xs">
              <caption className="sr-only">Model performance broken down by bet type</caption>
              <thead>
                <tr className="text-[11px] text-slate-400 border-b border-slate-700">
                  <th scope="col" className="py-1.5 pr-2 text-left font-semibold">Bet Type</th>
                  <th scope="col" className="py-1.5 px-2 text-right font-semibold">Picks</th>
                  <th scope="col" className="py-1.5 px-2 text-right font-semibold">W-L</th>
                  <th scope="col" className="py-1.5 px-2 text-right font-semibold">Win Rate</th>
                  <th scope="col" className="py-1.5 pl-2 text-right font-semibold">ROI</th>
                </tr>
              </thead>
              <tbody>
                {marketPerformance.map((m) => (
                  <tr key={m.market} className="border-b border-slate-800/60">
                    <td className="py-1.5 pr-2 text-slate-200 font-semibold">{m.market}</td>
                    <td className="py-1.5 px-2 text-right text-slate-300 tabular-nums">{m.count}</td>
                    <td className="py-1.5 px-2 text-right text-slate-300 tabular-nums">
                      {m.wins}-{m.losses}
                    </td>
                    <td className={`py-1.5 px-2 text-right font-bold tabular-nums ${winRateTone(m.winRate)}`}>
                      {m.winRate.toFixed(1)}%
                    </td>
                    <td className={`py-1.5 pl-2 text-right font-semibold tabular-nums ${roiTone(m.roi)}`}>
                      {m.roi >= 0 ? '+' : ''}
                      {m.roi.toFixed(1)}%
                    </td>
                  </tr>
                ))}
                <tr className="border-t border-slate-700 bg-slate-900/40">
                  <td className="py-1.5 pr-2 text-slate-300 font-bold">Total</td>
                  <td className="py-1.5 px-2 text-right text-white font-bold tabular-nums">{graded.length}</td>
                  <td className="py-1.5 px-2 text-right text-slate-300 tabular-nums">
                    {overallStats.wins}-{overallStats.losses}
                  </td>
                  <td className={`py-1.5 px-2 text-right font-bold tabular-nums ${winRateTone(overallStats.winRate, 52.4)}`}>
                    {overallStats.winRate.toFixed(1)}%
                  </td>
                  <td className={`py-1.5 pl-2 text-right font-bold tabular-nums ${roiTone(roi)}`}>
                    {roi >= 0 ? '+' : ''}
                    {roi.toFixed(1)}%
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        {/* Daily Top 6 Win Rate Chart */}
        <section className="bg-slate-950/30 rounded-2xl p-4 sm:p-5 border border-slate-700/40 lg:col-span-2">
          <h3 className="text-sm font-bold text-white mb-1">Daily Win Rate — Top 6 Best Bets</h3>
          <p className="text-xs text-slate-400 mb-3">
            Green bars mean 50% or better on our 6 strongest daily picks. Hover or tap a day to see its record.
          </p>
          {renderTop6Chart()}
        </section>

        {/* Daily Win Rate by Confidence */}
        <section className="bg-slate-950/30 rounded-2xl p-4 sm:p-5 border border-slate-700/40 lg:col-span-2">
          <h3 className="text-sm font-bold text-white mb-1">Daily Win Rate by Confidence Level</h3>
          <p className="text-xs text-slate-400 mb-3">
            Tracks how High, Medium, and Low confidence picks performed across recent active game days.
          </p>
          {renderConfidenceChart()}
        </section>
      </div>
    </div>
  );
};

export default ModelPerformanceAnalytics;
