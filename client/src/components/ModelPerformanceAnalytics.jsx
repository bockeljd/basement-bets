import React, { useState } from 'react';

const ModelPerformanceAnalytics = ({ history }) => {
    // Hover state for inline SVG charts
    const [hoverConfIdx, setHoverConfIdx] = useState(null);
    const [hoverTop6Idx, setHoverTop6Idx] = useState(null);

    // Schema Migration: use graded_result (new) or outcome or result
    const getResult = (h) => h.graded_result || h.outcome || h.result;

    const isGradedResult = (res) => {
        if (!res) return false;
        const s = String(res).toUpperCase();
        return s === 'WON' || s === 'WIN' || s === 'LOST' || s === 'LOSS' || s === 'PUSH';
    };

    // --- Top 6 Filtering Logic ---
    // User strategy is only Top 6 (by EV/u). We must filter the entire history prop
    // to strictly include ONLY the Top 6 picks per day to avoid "stale" or "noise" data.
    const filteredToTop6 = (() => {
        const groups = {};
        history.forEach(h => {
            const day = h.analyzed_at ? (new Date(h.analyzed_at).toLocaleDateString('en-CA', { timeZone: 'America/New_York' })) : '—';
            if (!groups[day]) groups[day] = [];
            groups[day].push(h);
        });
        const out = [];
        Object.values(groups).forEach(dayList => {
            const top6 = dayList
                .sort((a, b) => Number(b.ev_per_unit || b.ev || 0) - Number(a.ev_per_unit || a.ev || 0))
                .slice(0, 6);
            out.push(...top6);
        });
        return out;
    })();

    const graded = filteredToTop6.filter(h => isGradedResult(getResult(h)));
    const wins = graded.filter(h => {
        const s = String(getResult(h)).toUpperCase();
        return s === 'WON' || s === 'WIN';
    }).length;
    const losses = graded.filter(h => {
        const s = String(getResult(h)).toUpperCase();
        return s === 'LOST' || s === 'LOSS';
    }).length;
    const pushes = graded.filter(h => String(getResult(h)).toUpperCase() === 'PUSH').length;
    const winRate = graded.length > 0 ? (wins / (wins + losses) * 100) : 0;
    const roi = graded.length > 0 ? ((wins * 9.09 - losses * 10) / (graded.length * 10) * 100) : 0;

    // CLV Metrics
    const clvData = history.filter(h => h.clv_points !== null && h.clv_points !== undefined);
    const avgClv = clvData.length > 0 ? (clvData.reduce((a, b) => a + (b.clv_points || 0), 0) / clvData.length) : 0;
    const posClv = clvData.filter(h => (h.clv_points || 0) > 0).length;
    const posClvRate = clvData.length > 0 ? (posClv / clvData.length * 100) : 0;

    // Performance by edge threshold
    // Data has evolved over time; edge can be stored as:
    // - h.edge (points or % depending on sport/model)
    // - h.edge_points
    // - h.ev_per_unit (decimal EV, e.g. 0.04 = 4%)
    const getEdge = (h) => {
        // For the History analytics, we want EV% bands.
        // Always prefer EV/u (decimal), falling back to edge_points only if EV is missing.
        let ev = Number(h?.ev_per_unit ?? h?.ev);
        if (Number.isFinite(ev)) {
            let n = ev;
            let safety = 0;
            // Use 0.5 (50%) as the threshold for 'this must be a whole number percent'
            while (Math.abs(n) > 0.5 && safety < 3) {
                n /= 100;
                safety++;
            }
            return n;
        }
        const raw = h?.edge ?? h?.edge_points;
        let n = Number(raw);
        if (Number.isFinite(n)) {
            let safety = 0;
            while (Math.abs(n) > 0.5 && safety < 3) {
                n /= 100;
                safety++;
            }
            return n;
        }
        return null;
    };

    const edgeVals = graded.map(getEdge).filter(v => v !== null && v !== undefined && Number.isFinite(v));
    const maxAbs = edgeVals.length ? Math.max(...edgeVals.map(v => Math.abs(v))) : 0;

    // EV% bands only (based on EV/u decimal)
    const edgeMode = 'ev';

    // Show edge performance in *bands* (ranges), not cumulative thresholds.
    // This is easier to interpret and lets us show the right tail.
    const edgeBands = [
        { lo: 0.00, hi: 0.05, label: '0–5%' },
        { lo: 0.05, hi: 0.10, label: '5-10%' },
        { lo: 0.10, hi: 0.15, label: '10-15%' },
        { lo: 0.15, hi: 0.20, label: '15-20%' },
        { lo: 0.20, hi: 0.25, label: '20-25%' },
        { lo: 0.25, hi: 0.30, label: '25-30%' },
        { lo: 0.30, hi: null, label: '30%+' },
    ];

    const inBand = (e, b) => {
        if (!Number.isFinite(e)) return false;
        if (b.hi === null || b.hi === undefined) return e >= b.lo;
        return e >= b.lo && e < b.hi;
    };

    const edgeBandPerformance = edgeBands.map((band) => {
        const filtered = graded.filter(h => inBand(getEdge(h), band));
        const w = filtered.filter(h => {
            const s = String(getResult(h)).toUpperCase();
            return s === 'WON' || s === 'WIN';
        }).length;
        const l = filtered.filter(h => {
            const s = String(getResult(h)).toUpperCase();
            return s === 'LOST' || s === 'LOSS';
        }).length;
        const decided = w + l;
        const wr = decided > 0 ? (w / decided * 100) : 0;
        const roiPct = filtered.length > 0 ? ((w * 9.09 - l * 10) / (filtered.length * 10) * 100) : 0;
        return {
            label: band.label,
            count: filtered.length,
            wins: w,
            losses: l,
            winRate: wr,
            roi: roiPct,
        };
    }).filter(x => x.count > 0);

    // Performance by sport
    const getSport = (h) => h?.sport || h?.league;
    const sports = [...new Set(graded.map(getSport).filter(Boolean))];
    const sportPerformance = sports.map(sport => {
        const filtered = graded.filter(h => getSport(h) === sport);
        const w = filtered.filter(h => getResult(h) === 'WON' || getResult(h) === 'Win').length;
        const l = filtered.filter(h => getResult(h) === 'LOST' || getResult(h) === 'Loss').length;
        const wr = filtered.length > 0 ? (w / (w + l) * 100) : 0;
        const r = filtered.length > 0 ? ((w * 9.09 - l * 10) / (filtered.length * 10) * 100) : 0;
        return { sport, count: filtered.length, wins: w, losses: l, winRate: wr, roi: r };
    });

    // Performance by market type
    const getMarket = (h) => h?.market || h?.market_type;
    const markets = [...new Set(graded.map(getMarket).filter(Boolean))];
    const marketPerformance = markets.map(market => {
        const filtered = graded.filter(h => getMarket(h) === market);
        const w = filtered.filter(h => getResult(h) === 'WON' || getResult(h) === 'Win').length;
        const l = filtered.filter(h => getResult(h) === 'LOST' || getResult(h) === 'Loss').length;
        const wr = filtered.length > 0 ? (w / (w + l) * 100) : 0;
        const r = filtered.length > 0 ? ((w * 9.09 - l * 10) / (filtered.length * 10) * 100) : 0;
        return { market, count: filtered.length, wins: w, losses: l, winRate: wr, roi: r };
    });

    // Performance by confidence level
    // Confidence should always be attached to the *recommended bet*. Depending on schema version,
    // it may live on the row, inside outputs_json, or inside recommendation_json.
    const normalizeConfidence = (val) => {
        // numeric confidence
        const asNum = Number(val);
        if (Number.isFinite(asNum)) {
            if (asNum >= 0.75) return 'High';
            if (asNum >= 0.6) return 'Medium';
            return 'Low';
        }

        const s = String(val ?? '').trim();
        const up = s.toUpperCase();
        if (!up || up === '—') return null;
        if (up === 'H' || up.startsWith('HIGH')) return 'High';
        if (up === 'M' || up.startsWith('MED')) return 'Medium';
        if (up === 'L' || up.startsWith('LOW')) return 'Low';
        return null;
    };

    const inferConfidenceFromEv = (h) => {
        // Bucket by EV/u using the SAME thresholds as the model UI labels:
        // confidence = High if ev*100*5 > 80  => ev > 0.16
        // confidence = Medium if ev*100*5 > 50 => ev > 0.10
        const ev = Number(h?.ev_per_unit ?? h?.ev);
        if (!Number.isFinite(ev)) return 'Low';
        if (ev >= 0.16) return 'High';
        if (ev >= 0.10) return 'Medium';
        return 'Low';
    };

    const getConfidenceLabel = (h) => {
        // 1) explicit row-level fields
        const explicit = h?.confidence_label || h?.confidenceLevel || h?.confidence_level || h?.confidence;
        const n1 = normalizeConfidence(explicit);
        if (n1) return n1;

        // 2) outputs_json: { confidence_label } or { recommendations: [{confidence_level/confidence_label/confidence}] }
        try {
            if (h?.outputs_json) {
                const out = JSON.parse(h.outputs_json);
                const n2 = normalizeConfidence(out?.confidence_label || out?.confidenceLevel || out?.confidence);
                if (n2) return n2;
                const rec = Array.isArray(out?.recommendations) ? out.recommendations[0] : null;
                const n2b = normalizeConfidence(rec?.confidence_level || rec?.confidence_label || rec?.confidence);
                if (n2b) return n2b;
            }
        } catch (e) { }

        // 3) recommendation_json: legacy recommendations array
        try {
            if (h?.recommendation_json) {
                const recs = JSON.parse(h.recommendation_json);
                const rec = Array.isArray(recs) ? recs[0] : recs;
                const n3 = normalizeConfidence(rec?.confidence_level || rec?.confidence_label || rec?.confidence);
                if (n3) return n3;
            }
        } catch (e) { }

        // 4) last resort: infer from EV
        return inferConfidenceFromEv(h);
    };

    const confidenceLevels = ['High', 'Medium', 'Low'];
    const confidencePerformance = confidenceLevels.map(level => {
        const filtered = graded.filter(h => getConfidenceLabel(h) === level);
        const w = filtered.filter(h => getResult(h) === 'WON' || getResult(h) === 'Win').length;
        const l = filtered.filter(h => getResult(h) === 'LOST' || getResult(h) === 'Loss').length;
        const wr = (w + l) > 0 ? (w / (w + l) * 100) : 0;
        const r = filtered.length > 0 ? ((w * 9.09 - l * 10) / (filtered.length * 10) * 100) : 0;
        return { level, count: filtered.length, wins: w, losses: l, winRate: wr, roi: r };
    });

    const toEtDay = (ts) => {
        if (!ts) return null;
        try {
            const d = new Date(ts);
            const s = d.toLocaleDateString('en-US', { timeZone: 'America/New_York' });
            return s || null;
        } catch (e) {
            return null;
        }
    };

    const fmtEtDayShort = (ts) => {
        const day = toEtDay(ts);
        if (!day) return '—';
        // day is like M/D/YYYY
        try {
            const parts = day.split('/');
            if (parts.length === 3) {
                const mm = String(parts[0]).padStart(2, '0');
                const dd = String(parts[1]).padStart(2, '0');
                return `${mm}/${dd}`;
            }
        } catch (e) { }
        return day;
    };

    const isWithinDays = (h, days) => {
        const ts = h?.analyzed_at || h?.created_at;
        if (!ts) return false;
        try {
            const t = new Date(ts).getTime();
            if (!Number.isFinite(t)) return false;
            const cutoff = Date.now() - (days * 24 * 60 * 60 * 1000);
            return t >= cutoff;
        } catch (e) {
            return false;
        }
    };

    const isYesterdayET = (h) => {
        const ts = h?.analyzed_at || h?.created_at;
        const day = toEtDay(ts);
        if (!day) return false;
        const now = new Date();
        const y = new Date(now.getTime() - 24 * 60 * 60 * 1000);
        const yday = y.toLocaleDateString('en-US', { timeZone: 'America/New_York' });
        return day === yday;
    };

    const confidenceTrend = (predicateFn) => confidenceLevels.map(level => {
        const filtered = graded
            .filter(h => getConfidenceLabel(h) === level)
            .filter(predicateFn);
        const w = filtered.filter(h => getResult(h) === 'WON' || getResult(h) === 'Win').length;
        const l = filtered.filter(h => getResult(h) === 'LOST' || getResult(h) === 'Loss').length;
        const p = filtered.filter(h => getResult(h) === 'PUSH' || getResult(h) === 'Push').length;
        const decided = w + l;
        const wr = decided > 0 ? (w / decided * 100) : 0;
        return { level, count: filtered.length, wins: w, losses: l, pushes: p, winRate: wr };
    });

    // --- Top 6 (by EV) subset (used for daily tracking) ---
    const topN = 6;
    const getEv = (h) => {
        const ev = Number(h?.ev_per_unit ?? h?.ev);
        return Number.isFinite(ev) ? ev : 0;
    };

    const dailyTopN = (() => {
        // Group all recommended+graded bets by ET day of analyzed_at.
        const groups = {};
        for (const h of graded) {
            const day = toEtDay(h?.analyzed_at || h?.created_at);
            if (!day) continue;
            if (!groups[day]) groups[day] = [];
            groups[day].push(h);
        }

        const days = Object.keys(groups).sort((a, b) => {
            const da = new Date(a).getTime();
            const db = new Date(b).getTime();
            if (Number.isFinite(da) && Number.isFinite(db)) return db - da;
            return String(b).localeCompare(String(a));
        });

        const out = [];
        for (const day of days) {
            const bets = (groups[day] || [])
                .slice()
                .sort((x, y) => getEv(y) - getEv(x))
                .slice(0, topN);

            const w = bets.filter(h => {
                const s = String(getResult(h)).toUpperCase();
                return s === 'WON' || s === 'WIN';
            }).length;
            const l = bets.filter(h => {
                const s = String(getResult(h)).toUpperCase();
                return s === 'LOST' || s === 'LOSS';
            }).length;
            const p = bets.filter(h => String(getResult(h)).toUpperCase() === 'PUSH').length;
            const decided = w + l;
            const wr = decided > 0 ? (w / decided * 100) : 0;
            const roi = bets.length > 0 ? ((w * 9.09 - l * 10) / (bets.length * 10) * 100) : 0;

            out.push({ day, bets, count: bets.length, wins: w, losses: l, pushes: p, winRate: wr, roi });
        }
        return out;
    })();

    const dailyTopN7 = dailyTopN.slice(0, 7);

    // Trends by confidence (ALL graded recommended bets)
    const trendYday = confidenceTrend((h) => isYesterdayET(h));
    const trend3 = confidenceTrend((h) => isWithinDays(h, 3));
    const trend7 = confidenceTrend((h) => isWithinDays(h, 7));
    const trend30 = confidenceTrend((h) => isWithinDays(h, 30));

    // Daily win% line series by confidence band (last N days)
    const dailyWinSeries = (() => {
        const days = 14;
        const now = new Date();
        const etToday = now.toLocaleDateString('en-US', { timeZone: 'America/New_York' });

        // Build ET date keys for last N days (oldest -> newest), EXCLUDING today
        // because today's slate may be ungraded until the next day.
        const dayKeys = [];
        for (let i = days; i >= 1; i--) {
            const d = new Date(now.getTime() - i * 24 * 60 * 60 * 1000);
            const key = d.toLocaleDateString('en-US', { timeZone: 'America/New_York' });
            if (key === etToday) continue;
            dayKeys.push(key);
        }

        const byDay = {};
        for (const h of graded) {
            const key = toEtDay(h?.analyzed_at || h?.created_at);
            if (!key) continue;
            if (!byDay[key]) byDay[key] = [];
            byDay[key].push(h);
        }

        const bands = ['High', 'Medium', 'Low'];
        const series = {};
        for (const b of bands) series[b] = [];

        for (const key of dayKeys) {
            const rows = byDay[key] || [];
            for (const b of bands) {
                const xs = rows.filter(r => getConfidenceLabel(r) === b);
                const w = xs.filter(r => {
                    const s = String(getResult(r)).toUpperCase();
                    return s === 'WON' || s === 'WIN';
                }).length;
                const l = xs.filter(r => {
                    const s = String(getResult(r)).toUpperCase();
                    return s === 'LOST' || s === 'LOSS';
                }).length;
                const decided = w + l;
                const wr = decided > 0 ? (w / decided * 100) : null;
                series[b].push(wr);
            }
        }

        const seriesTop6 = [];
        for (const key of dayKeys) {
            const rows = byDay[key] || [];
            // Sort by EV/u desc
            const sorted = [...rows].sort((a, b) => getEv(b) - getEv(a));
            const top6 = sorted.slice(0, 6);

            const w = top6.filter(r => {
                const s = String(getResult(r)).toUpperCase();
                return s === 'WON' || s === 'WIN';
            }).length;
            const l = top6.filter(r => {
                const s = String(getResult(r)).toUpperCase();
                return s === 'LOST' || s === 'LOSS';
            }).length;
            const decided = w + l;
            const wr = decided > 0 ? (w / decided * 100) : null;
            seriesTop6.push(wr);
        }

        return { dayKeys, series, seriesTop6 };
    })();

    const renderConfidenceChart = () => {
        const { dayKeys, series } = dailyWinSeries;
        const bands = [
            { k: 'High', color: '#34d399' },
            { k: 'Medium', color: '#60a5fa' },
            { k: 'Low', color: '#f59e0b' },
        ];

        const width = 900;
        const height = 300;
        const padL = 60; // Increased from 46 to prevent label cutoff
        const padR = 30; // Increased from 24
        const padT = 20;
        const padB = 45; // Increased from 40

        const n = dayKeys.length;
        const xAt = (i) => {
            if (n <= 1) return padL;
            return padL + (i * (width - padL - padR)) / (n - 1);
        };
        const yAt = (pct) => {
            const v = (pct === null || pct === undefined) ? 50 : pct;
            const clamped = Math.max(0, Math.min(100, Number(v)));
            return padT + ((100 - clamped) * (height - padT - padB)) / 100.0;
        };

        const pathFor = (arr) => {
            let d = '';
            let first = true;
            for (let i = 0; i < arr.length; i++) {
                if (arr[i] === null || arr[i] === undefined) continue;
                const x = xAt(i);
                const y = yAt(arr[i]);
                d += (first ? `M ${x} ${y}` : ` L ${x} ${y}`);
                first = false;
            }
            return d;
        };

        const tickIdx = [0, Math.floor((n - 1) / 2), n - 1].filter((v, i, a) => a.indexOf(v) === i);

        const hoverIdx = (hoverConfIdx !== null && hoverConfIdx !== undefined) ? Number(hoverConfIdx) : null;
        const hoverX = hoverIdx !== null ? xAt(hoverIdx) : null;

        // Tooltip clamp so it never renders off-canvas
        const tipW = 250;
        const tipH = 92;
        const tipX = hoverX !== null
            ? Math.max(padL, Math.min(hoverX + 8, (width - padR) - tipW))
            : null;
        const tipY = padT + 6;

        return (
            <svg
                viewBox={`0 0 ${width} ${height}`}
                className="w-full h-[420px] sm:h-[460px]"
                onMouseLeave={() => setHoverConfIdx(null)}
            >
                {/* grid */}
                {[0, 25, 50, 75, 100].map((p) => (
                    <g key={p}>
                        <line x1={padL} x2={width - padR} y1={yAt(p)} y2={yAt(p)} stroke="rgba(148,163,184,0.15)" strokeWidth="1" />
                        <text x={2} y={yAt(p) + 4} fontSize="11" fill="rgba(148,163,184,0.92)" fontWeight="700">{p}%</text>
                    </g>
                ))}

                {/* series */}
                {bands.map((b) => (
                    <path key={b.k} d={pathFor(series[b.k] || [])} fill="none" stroke={b.color} strokeWidth="2" />
                ))}

                {/* Hover capture (so you can hover anywhere, not just points) */}
                <rect
                    x={padL}
                    y={padT}
                    width={width - padL - padR}
                    height={height - padT - padB}
                    fill="transparent"
                    onMouseMove={(e) => {
                        try {
                            const svg = e.currentTarget.ownerSVGElement;
                            const pt = svg.createSVGPoint();
                            pt.x = e.clientX;
                            pt.y = e.clientY;
                            const cur = pt.matrixTransform(svg.getScreenCTM().inverse());
                            const x = cur.x;
                            const frac = (x - padL) / (width - padL - padR);
                            const idx = Math.round(frac * (n - 1));
                            const clamped = Math.max(0, Math.min(n - 1, idx));
                            setHoverConfIdx(clamped);
                        } catch (err) {
                            // ignore
                        }
                    }}
                />

                {/* hover points (native tooltip via <title>) */}
                {bands.map((b) => (
                    (series[b.k] || []).map((v, i) => {
                        if (v === null || v === undefined) return null;
                        return (
                            <circle key={`${b.k}-${i}`} cx={xAt(i)} cy={yAt(v)} r="4" fill={b.color} fillOpacity="0.75">
                                <title>{`${dayKeys[i]} • ${b.k} • ${Number(v).toFixed(1)}% win`}</title>
                            </circle>
                        );
                    })
                ))}

                {/* hover indicator + tooltip */}
                {hoverIdx !== null ? (
                    <g>
                        <line x1={hoverX} x2={hoverX} y1={padT} y2={height - padB} stroke="rgba(226,232,240,0.18)" strokeWidth="1" />
                        <rect x={tipX} y={tipY} width={tipW} height={tipH} rx="10" fill="rgba(2,6,23,0.92)" stroke="rgba(148,163,184,0.25)" />
                        <text x={tipX + 8} y={tipY + 28} fontSize="14" fill="rgba(226,232,240,0.98)" fontWeight="800">{dayKeys[hoverIdx] || ''}</text>
                        {bands.map((b, bi) => {
                            const v = (series[b.k] || [])[hoverIdx];
                            if (v === null || v === undefined) return null;
                            return (
                                <text key={b.k} x={tipX + 8} y={tipY + 50 + bi * 18} fontSize="14" fill={b.color} fontWeight="800">
                                    {b.k}: {Number(v).toFixed(1)}%
                                </text>
                            );
                        })}
                    </g>
                ) : null}

                {/* x labels (sparse) */}
                {tickIdx.map((i) => (
                    <text key={i} x={xAt(i)} y={height - 6} fontSize="11" fill="rgba(148,163,184,0.92)" fontWeight="700" textAnchor="middle">
                        {(() => {
                            const parts = String(dayKeys[i] || '').split('/');
                            if (parts.length >= 2) {
                                const mm = String(parts[0]).padStart(2, '0');
                                const dd = String(parts[1]).padStart(2, '0');
                                return `${mm}/${dd}`;
                            }
                            return dayKeys[i] || '';
                        })()}
                    </text>
                ))}
            </svg>
        );
    };

    const renderTop6Chart = () => {
        const { dayKeys, seriesTop6 } = dailyWinSeries;
        const color = '#fbbf24'; // Amber/Gold for top picks

        const width = 900;
        const height = 300;
        const padL = 60;
        const padR = 30;
        const padT = 20;
        const padB = 45;

        const n = dayKeys.length;
        const plotW = (width - padL - padR);
        const bandW = n > 0 ? (plotW / n) : plotW;
        const xBar = (i) => padL + i * bandW;

        const yAt = (pct) => {
            const v = (pct === null || pct === undefined) ? 50 : pct;
            const clamped = Math.max(0, Math.min(100, Number(v)));
            return padT + ((100 - clamped) * (height - padT - padB)) / 100.0;
        };

        const avg = (() => {
            const xs = (seriesTop6 || []).filter(v => v !== null && v !== undefined);
            if (!xs.length) return null;
            return xs.reduce((a, b) => a + Number(b), 0) / xs.length;
        })();

        // Cumulative average trend line
        const cumAvg = (() => {
            const out = [];
            let s = 0;
            let k = 0;
            for (let i = 0; i < n; i++) {
                const v = seriesTop6[i];
                if (v !== null && v !== undefined) {
                    s += Number(v);
                    k += 1;
                }
                out.push(k ? (s / k) : null);
            }
            return out;
        })();

        const pathForBarsAvg = (arr) => {
            let d = '';
            let first = true;
            for (let i = 0; i < arr.length; i++) {
                const v = arr[i];
                if (v === null || v === undefined) continue;
                const x = xBar(i) + bandW / 2;
                const y = yAt(v);
                d += (first ? `M ${x} ${y}` : ` L ${x} ${y}`);
                first = false;
            }
            return d;
        };

        const tickIdx = [0, Math.floor((n - 1) / 2), n - 1].filter((v, i, a) => a.indexOf(v) === i);

        const hoverIdx = (hoverTop6Idx !== null && hoverTop6Idx !== undefined) ? Number(hoverTop6Idx) : null;
        const hoverX = hoverIdx !== null ? (xBar(hoverIdx) + bandW / 2) : null;

        // Tooltip clamp so it never renders off-canvas
        const tipW = 250;
        const tipH = 68;
        const tipX = hoverX !== null
            ? Math.max(padL, Math.min(hoverX + 8, (width - padR) - tipW))
            : null;
        const tipY = padT + 6;

        return (
            <svg
                viewBox={`0 0 ${width} ${height}`}
                className="w-full h-[420px] sm:h-[460px]"
                onMouseLeave={() => setHoverTop6Idx(null)}
            >
                {/* grid */}
                {[0, 25, 50, 75, 100].map((p) => (
                    <g key={p}>
                        <line
                            x1={padL}
                            x2={width - padR}
                            y1={yAt(p)}
                            y2={yAt(p)}
                            stroke={p === 50 ? 'rgba(248,250,252,0.35)' : 'rgba(148,163,184,0.15)'}
                            strokeWidth={p === 50 ? '1.5' : '1'}
                        />
                        <text x={2} y={yAt(p) + 4} fontSize="11" fill="rgba(148,163,184,0.92)" fontWeight="700">{p}%</text>
                    </g>
                ))}

                {/* bars */}
                {(seriesTop6 || []).map((v, i) => {
                    const val = (v === null || v === undefined) ? null : Number(v);
                    const barW = Math.max(4, bandW * 0.72);
                    const x = xBar(i) + (bandW - barW) / 2;
                    const y = yAt(val);
                    const h = (height - padB) - y;
                    const fill = val === null
                        ? 'rgba(100,116,139,0.25)'
                        : (val >= 50 ? 'rgba(34,197,94,0.32)' : 'rgba(248,113,113,0.30)');
                    const stroke = val === null
                        ? 'rgba(100,116,139,0.25)'
                        : (val >= 50 ? 'rgba(34,197,94,0.70)' : 'rgba(248,113,113,0.70)');
                    return (
                        <rect key={i} x={x} y={y} width={barW} height={Math.max(0, h)} rx="4" fill={fill} stroke={stroke}>
                            {val !== null ? <title>{`${dayKeys[i]} • Top 6 • ${val.toFixed(1)}% win`}</title> : null}
                        </rect>
                    );
                })}

                {/* hover capture */}
                <rect
                    x={padL}
                    y={padT}
                    width={width - padL - padR}
                    height={height - padT - padB}
                    fill="transparent"
                    onMouseMove={(e) => {
                        try {
                            const svg = e.currentTarget.ownerSVGElement;
                            const pt = svg.createSVGPoint();
                            pt.x = e.clientX;
                            pt.y = e.clientY;
                            const cur = pt.matrixTransform(svg.getScreenCTM().inverse());
                            const x = cur.x;
                            const frac = (x - padL) / (width - padL - padR);
                            const idx = Math.floor(frac * n);
                            const clamped = Math.max(0, Math.min(n - 1, idx));
                            setHoverTop6Idx(clamped);
                        } catch (err) {
                            // ignore
                        }
                    }}
                />

                {/* average lines */}
                {avg !== null ? (
                    <g>
                        <line x1={padL} x2={width - padR} y1={yAt(avg)} y2={yAt(avg)} stroke="rgba(251,191,36,0.55)" strokeDasharray="4 4" />
                        {/* Avg label placed on the left to avoid colliding with rolling label */}
                        <text x={padL + 6} y={yAt(avg) - 6} fontSize="12" fill="rgba(251,191,36,0.90)" textAnchor="start" fontWeight="800">Avg {avg.toFixed(1)}%</text>
                    </g>
                ) : null}

                {/* cumulative average trend line */}
                <path d={pathForBarsAvg(cumAvg)} fill="none" stroke="rgba(147,197,253,0.85)" strokeWidth="2" strokeLinecap="round" />

                {/* cumulative avg value label (last available point) */}
                {(() => {
                    let lastIdx = -1;
                    for (let i = cumAvg.length - 1; i >= 0; i--) {
                        if (cumAvg[i] !== null && cumAvg[i] !== undefined) { lastIdx = i; break; }
                    }
                    if (lastIdx < 0) return null;
                    const v = Number(cumAvg[lastIdx]);
                    if (!Number.isFinite(v)) return null;
                    const x = xBar(lastIdx) + bandW / 2;
                    const y = yAt(v);
                    const label = `Roll ${v.toFixed(1)}%`;
                    const lx = Math.max(padL, Math.min(x + 8, (width - padR) - 90));
                    // If the rolling label is too close (vertically) to the avg line, bump it down.
                    const avgY = (avg !== null && avg !== undefined) ? yAt(avg) : null;
                    let ly = Math.max(padT + 14, Math.min(y - 8, (height - padB) - 6));
                    if (avgY !== null && Math.abs(ly - avgY) < 16) {
                        ly = Math.min((height - padB) - 6, ly + 18);
                    }
                    return (
                        <g>
                            <circle cx={x} cy={y} r="4" fill="rgba(147,197,253,0.95)" />
                            <text x={lx} y={ly} fontSize="12" fill="rgba(147,197,253,0.95)" fontWeight="800">{label}</text>
                        </g>
                    );
                })()}

                {/* hover indicator + tooltip */}
                {hoverIdx !== null ? (
                    <g>
                        <line x1={hoverX} x2={hoverX} y1={padT} y2={height - padB} stroke="rgba(226,232,240,0.18)" strokeWidth="1" />
                        <rect x={tipX} y={tipY} width={tipW} height={tipH} rx="10" fill="rgba(2,6,23,0.92)" stroke="rgba(148,163,184,0.25)" />
                        <text x={tipX + 8} y={tipY + 28} fontSize="14" fill="rgba(226,232,240,0.98)" fontWeight="800">{dayKeys[hoverIdx] || ''}</text>
                        <text x={tipX + 8} y={tipY + 52} fontSize="14" fill="rgba(226,232,240,0.95)" fontWeight="800">Top 6: {(() => {
                            const v = seriesTop6[hoverIdx];
                            return (v === null || v === undefined) ? '—' : `${Number(v).toFixed(1)}%`;
                        })()}</text>
                    </g>
                ) : null}

                {/* x labels (sparse) */}
                {tickIdx.map((i) => (
                    <text key={i} x={xBar(i) + bandW / 2} y={height - 6} fontSize="11" fill="rgba(148,163,184,0.92)" fontWeight="700" textAnchor="middle">
                        {(() => {
                            const parts = String(dayKeys[i] || '').split('/');
                            if (parts.length >= 2) {
                                const mm = String(parts[0]).padStart(2, '0');
                                const dd = String(parts[1]).padStart(2, '0');
                                return `${mm}/${dd}`;
                            }
                            return dayKeys[i] || '';
                        })()}
                    </text>
                ))}
            </svg>
        );
    };

    const sum = (xs) => (xs || []).reduce((a, b) => a + (Number(b) || 0), 0);

    // Sanity checks: these should add up to graded.length.
    const confidenceCountSum = sum(confidencePerformance.map(x => x.count));
    const sportCountSum = sum(sportPerformance.map(x => x.count));
    const marketCountSum = sum(marketPerformance.map(x => x.count));

    const sanity = {
        graded: graded.length,
        confidence: confidenceCountSum,
        sport: sportCountSum,
        market: marketCountSum,
    };

    if (graded.length === 0) return null;

    return (
        <div className="ui-card p-6 mb-6">
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {/* Overall Stats + CLV */}
                <div className="bg-slate-950/20 rounded-2xl p-4 border border-slate-700/40">
                    <h4 className="text-[11px] font-semibold text-slate-400 mb-3">Overall</h4>
                    <div className="space-y-2">
                        <div className="flex justify-between">
                            <span className="text-slate-400">Record:</span>
                            <span className="text-white font-bold">{wins}-{losses}-{pushes}</span>
                        </div>
                        <div className="flex justify-between">
                            <span className="text-slate-400">Win Rate:</span>
                            <span className={`font-bold ${winRate >= 55 ? 'text-green-400' : winRate >= 50 ? 'text-yellow-400' : 'text-red-400'}`}>
                                {winRate.toFixed(1)}%
                            </span>
                        </div>
                        <div className="flex justify-between">
                            <span className="text-slate-400">ROI:</span>
                            <span className={`font-bold ${roi >= 5 ? 'text-green-400' : roi >= 0 ? 'text-yellow-400' : 'text-red-400'}`}>
                                {roi >= 0 ? '+' : ''}{roi.toFixed(1)}%
                            </span>
                        </div>
                        <div className="flex justify-between">
                            <span className="text-slate-400">Total Bets:</span>
                            <span className="text-white font-bold">{graded.length}</span>
                        </div>
                    </div>

                    <div className="mt-4 pt-3 border-t border-slate-700">
                        <div className="text-[11px] font-semibold text-slate-400 mb-2">CLV</div>
                        <div className="space-y-2">
                            <div className="flex justify-between">
                                <span className="text-slate-400">Avg CLV:</span>
                                <span className={`font-bold ${avgClv > 0 ? 'text-green-400' : avgClv < 0 ? 'text-red-400' : 'text-slate-200'}`}>
                                    {avgClv > 0 ? '+' : ''}{avgClv.toFixed(2)} pts
                                </span>
                            </div>
                            <div className="flex justify-between">
                                <span className="text-slate-400">Positive CLV %:</span>
                                <span className="text-white font-bold">{posClvRate.toFixed(1)}%</span>
                            </div>
                            <div className="text-[10px] text-slate-500 mt-2">
                                *CLV = Closing Line Value (Pts vs Market Close)
                            </div>
                        </div>
                    </div>
                </div>

                {/* Performance by Edge */}
                <div className="bg-slate-950/20 rounded-2xl p-4 border border-slate-700/40">
                    <h4 className="text-[11px] font-semibold text-slate-400 mb-3">Edge bands</h4>

                    <div className="text-[11px] text-slate-400 mb-2">
                        Bands are EV% ranges (not cumulative), based on EV/u.
                    </div>

                    <div className="overflow-x-auto">
                        <table className="w-full text-xs">
                            <thead>
                                <tr className="text-[10px] uppercase tracking-wider text-slate-500 border-b border-slate-700">
                                    <th className="py-1 pr-2 text-left">Edge band</th>
                                    <th className="py-1 px-2 text-right">N</th>
                                    <th className="py-1 px-2 text-right">W-L</th>
                                    <th className="py-1 px-2 text-right">Win%</th>
                                    <th className="py-1 pl-2 text-right">ROI</th>
                                </tr>
                            </thead>
                            <tbody>
                                {edgeBandPerformance.map((b) => (
                                    <tr key={b.label} className="border-b border-slate-800/60 last:border-0">
                                        <td className="py-1 pr-2 text-slate-300 font-bold">{b.label}</td>
                                        <td className="py-1 px-2 text-right text-slate-400 font-mono">{b.count}</td>
                                        <td className="py-1 px-2 text-right text-slate-400 font-mono">{b.wins}-{b.losses}</td>
                                        <td className={`py-1 px-2 text-right font-bold ${b.winRate >= 55 ? 'text-green-400' : b.winRate >= 50 ? 'text-yellow-400' : 'text-red-400'}`}>
                                            {b.winRate.toFixed(1)}%
                                        </td>
                                        <td className={`py-1 pl-2 text-right font-mono ${b.roi >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                            {b.roi >= 0 ? '+' : ''}{b.roi.toFixed(1)}%
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>

                {/* CLV Stats merged into Overall Performance */}

                {/* Performance by Confidence */}
                <div className="bg-slate-900/50 rounded-lg p-4 border border-slate-700">
                    <h4 className="text-sm font-bold text-slate-400 uppercase mb-3">By Confidence</h4>

                    <div className="overflow-x-auto">
                        <table className="w-full text-xs">
                            <thead>
                                <tr className="text-[10px] uppercase tracking-wider text-slate-500 border-b border-slate-700">
                                    <th className="py-1 pr-2 text-left">Level</th>
                                    <th className="py-1 px-2 text-right">N</th>
                                    <th className="py-1 px-2 text-right">W-L</th>
                                    <th className="py-1 px-2 text-right">Win%</th>
                                    <th className="py-1 pl-2 text-right">ROI</th>
                                </tr>
                            </thead>
                            <tbody>
                                {confidencePerformance.map(c => (
                                    <tr key={c.level} className="border-b border-slate-800/60 last:border-0">
                                        <td className="py-1 pr-2 text-slate-300 font-bold">{c.level}</td>
                                        <td className="py-1 px-2 text-right text-slate-400 font-mono">{c.count}</td>
                                        <td className="py-1 px-2 text-right text-slate-400 font-mono">{c.wins}-{c.losses}</td>
                                        <td className={`py-1 px-2 text-right font-bold ${c.winRate >= 55 ? 'text-green-400' : c.winRate >= 50 ? 'text-yellow-400' : 'text-red-400'}`}>
                                            {c.winRate.toFixed(1)}%
                                        </td>
                                        <td className={`py-1 pl-2 text-right font-mono ${c.roi >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                            {c.roi >= 0 ? '+' : ''}{c.roi.toFixed(1)}%
                                        </td>
                                    </tr>
                                ))}
                                <tr className="border-t border-slate-700">
                                    <td className="py-1 pr-2 text-slate-500 font-black">TOTAL</td>
                                    <td className="py-1 px-2 text-right text-slate-200 font-black font-mono">{confidenceCountSum}</td>
                                    <td className="py-1 px-2"></td>
                                    <td className="py-1 px-2"></td>
                                    <td className="py-1 pl-2"></td>
                                </tr>
                            </tbody>
                        </table>
                    </div>

                    <div className="mt-4 pt-3 border-t border-slate-700">
                        <div className="text-[10px] font-black text-slate-500 uppercase tracking-widest mb-2">Recap (graded bets)</div>
                        <div className="rounded-xl border border-slate-800 bg-slate-950/25 p-3 overflow-x-auto">
                            <table className="w-full text-[11px]">
                                <thead>
                                    <tr className="text-[10px] uppercase tracking-wider text-slate-500 border-b border-slate-800">
                                        <th className="py-1 pr-2 text-left">Conf</th>
                                        <th className="py-1 px-2 text-right">Yesterday</th>
                                        <th className="py-1 px-2 text-right">3d</th>
                                        <th className="py-1 px-2 text-right">7d</th>
                                        <th className="py-1 pl-2 text-right">30d</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {confidenceLevels.map((lvl) => {
                                        const y = trendYday.find(t => t.level === lvl) || { wins: 0, losses: 0, pushes: 0, winRate: 0 };
                                        const d3 = trend3.find(t => t.level === lvl) || { wins: 0, losses: 0, pushes: 0, winRate: 0 };
                                        const d7 = trend7.find(t => t.level === lvl) || { wins: 0, losses: 0, pushes: 0, winRate: 0 };
                                        const d30 = trend30.find(t => t.level === lvl) || { wins: 0, losses: 0, pushes: 0, winRate: 0 };

                                        // Condensed: show Win% and N (decided bets)
                                        const cell = (t) => {
                                            const decided = (Number(t.wins) || 0) + (Number(t.losses) || 0);
                                            const wr = Number(t.winRate || 0);
                                            return `${wr.toFixed(0)}% (N=${decided})`;
                                        };

                                        return (
                                            <tr key={lvl} className="border-b border-slate-800/60 last:border-0">
                                                <td className="py-1 pr-2 text-slate-300 font-bold">{lvl}</td>
                                                <td className="py-1 px-2 text-right text-slate-300 font-mono">{cell(y)}</td>
                                                <td className="py-1 px-2 text-right text-slate-300 font-mono">{cell(d3)}</td>
                                                <td className="py-1 px-2 text-right text-slate-300 font-mono">{cell(d7)}</td>
                                                <td className="py-1 pl-2 text-right text-slate-300 font-mono">{cell(d30)}</td>
                                            </tr>
                                        );
                                    })}
                                </tbody>
                            </table>
                        </div>
                        <div className="text-[10px] text-slate-500 mt-2">*Recap includes graded bets only. Format: Win% (decided N).</div>
                    </div>
                </div>

                {/* Performance by Sport & Market */}
                <div className="bg-slate-900/50 rounded-lg p-4 border border-slate-700">
                    <h4 className="text-sm font-bold text-slate-400 uppercase mb-3">By Sport</h4>
                    <div className="overflow-x-auto mb-4">
                        <table className="w-full text-xs">
                            <thead>
                                <tr className="text-[10px] uppercase tracking-wider text-slate-500 border-b border-slate-700">
                                    <th className="py-1 pr-2 text-left">Sport</th>
                                    <th className="py-1 px-2 text-right">N</th>
                                    <th className="py-1 px-2 text-right">W-L</th>
                                    <th className="py-1 px-2 text-right">Win%</th>
                                    <th className="py-1 pl-2 text-right">ROI</th>
                                </tr>
                            </thead>
                            <tbody>
                                {sportPerformance.map(s => (
                                    <tr key={s.sport} className="border-b border-slate-800/60 last:border-0">
                                        <td className="py-1 pr-2 text-slate-300 font-bold">{s.sport}</td>
                                        <td className="py-1 px-2 text-right text-slate-400 font-mono">{s.count}</td>
                                        <td className="py-1 px-2 text-right text-slate-400 font-mono">{s.wins}-{s.losses}</td>
                                        <td className={`py-1 px-2 text-right font-bold ${s.winRate >= 55 ? 'text-green-400' : s.winRate >= 50 ? 'text-yellow-400' : 'text-red-400'}`}>
                                            {s.winRate.toFixed(0)}%
                                        </td>
                                        <td className={`py-1 pl-2 text-right font-mono ${s.roi >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                            {s.roi >= 0 ? '+' : ''}{s.roi.toFixed(0)}%
                                        </td>
                                    </tr>
                                ))}
                                <tr className="border-t border-slate-700">
                                    <td className="py-1 pr-2 text-slate-500 font-black">TOTAL</td>
                                    <td className="py-1 px-2 text-right text-slate-200 font-black font-mono">{sportCountSum}</td>
                                    <td className="py-1 px-2"></td>
                                    <td className="py-1 px-2"></td>
                                    <td className="py-1 pl-2"></td>
                                </tr>
                            </tbody>
                        </table>
                    </div>

                    <h4 className="text-sm font-bold text-slate-400 uppercase mb-3">By Market</h4>
                    <div className="overflow-x-auto">
                        <table className="w-full text-xs">
                            <thead>
                                <tr className="text-[10px] uppercase tracking-wider text-slate-500 border-b border-slate-700">
                                    <th className="py-1 pr-2 text-left">Market</th>
                                    <th className="py-1 px-2 text-right">N</th>
                                    <th className="py-1 px-2 text-right">W-L</th>
                                    <th className="py-1 px-2 text-right">Win%</th>
                                    <th className="py-1 pl-2 text-right">ROI</th>
                                </tr>
                            </thead>
                            <tbody>
                                {marketPerformance.map(m => (
                                    <tr key={m.market} className="border-b border-slate-800/60 last:border-0">
                                        <td className="py-1 pr-2 text-slate-300 font-bold">{m.market}</td>
                                        <td className="py-1 px-2 text-right text-slate-400 font-mono">{m.count}</td>
                                        <td className="py-1 px-2 text-right text-slate-400 font-mono">{m.wins}-{m.losses}</td>
                                        <td className={`py-1 px-2 text-right font-bold ${m.winRate >= 55 ? 'text-green-400' : m.winRate >= 50 ? 'text-yellow-400' : 'text-red-400'}`}>
                                            {m.winRate.toFixed(0)}%
                                        </td>
                                        <td className={`py-1 pl-2 text-right font-mono ${m.roi >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                            {m.roi >= 0 ? '+' : ''}{m.roi.toFixed(0)}%
                                        </td>
                                    </tr>
                                ))}
                                <tr className="border-t border-slate-700">
                                    <td className="py-1 pr-2 text-slate-500 font-black">TOTAL</td>
                                    <td className="py-1 px-2 text-right text-slate-200 font-black font-mono">{marketCountSum}</td>
                                    <td className="py-1 px-2"></td>
                                    <td className="py-1 px-2"></td>
                                    <td className="py-1 pl-2"></td>
                                </tr>
                            </tbody>
                        </table>
                    </div>

                    {/* Sanity check */}
                    <div className="mt-4 text-[10px] text-slate-500">
                        Sanity: graded={sanity.graded} • by confidence={sanity.confidence} • by sport={sanity.sport} • by market={sanity.market}
                        {(sanity.confidence !== sanity.graded || sanity.sport !== sanity.graded || sanity.market !== sanity.graded) ? (
                            <span className="text-amber-300"> (mismatch: some rows missing labels)</span>
                        ) : null}
                    </div>
                </div>

                {/* Top 6 Recommended Win Rate (moved up) */}
                <div className="bg-slate-900/50 rounded-lg p-4 border border-slate-700 lg:col-span-2">
                    <h4 className="text-sm font-bold text-slate-400 uppercase mb-2">Top 6 Recommended Win Rate</h4>
                    <div className="text-[10px] text-slate-500 mb-2">Last 14 days • Win% of the 6 highest EV graded bets each day (includes rolling average line).</div>
                    <div className="rounded-lg border border-slate-800 bg-slate-950/20 p-2">
                        {renderTop6Chart()}
                    </div>
                </div>

                {/* Daily win% by confidence */}
                <div className="bg-slate-900/50 rounded-lg p-4 border border-slate-700 lg:col-span-2">
                    <h4 className="text-sm font-bold text-slate-400 uppercase mb-3">Daily Win% by Confidence</h4>
                    <div className="text-[10px] text-slate-500 mb-2">Last 14 days • Win% computed on decided bets (W/L) per confidence band.</div>
                    <div className="rounded-lg border border-slate-800 bg-slate-950/20 p-2">
                        {renderConfidenceChart()}
                    </div>
                    <div className="mt-2 flex items-center gap-4 text-[11px] text-slate-400">
                        <div className="flex items-center gap-2"><span className="inline-block w-3 h-0.5" style={{ background: '#34d399' }}></span>High</div>
                        <div className="flex items-center gap-2"><span className="inline-block w-3 h-0.5" style={{ background: '#60a5fa' }}></span>Medium</div>
                        <div className="flex items-center gap-2"><span className="inline-block w-3 h-0.5" style={{ background: '#f59e0b' }}></span>Low</div>
                    </div>
                </div>


            </div>
        </div>
    );
};

export default ModelPerformanceAnalytics;
