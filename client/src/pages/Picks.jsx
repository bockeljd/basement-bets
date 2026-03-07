import React, { useEffect, useMemo, useState } from 'react';
import api from '../api/axios';
import { RefreshCw, BarChart3 } from 'lucide-react';
import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid, Legend, ReferenceLine, ComposedChart, Line, Cell, LabelList } from 'recharts';
import ModelPerformanceAnalytics from '../components/ModelPerformanceAnalytics';

const etDay = (dt) => {
  if (!dt) return null;
  try {
    const d = new Date(dt);
    return d.toLocaleDateString('en-CA', { timeZone: 'America/New_York' });
  } catch (e) {
    return null;
  }
};

const isGraded = (x) => {
  const s = String(x || '').toUpperCase();
  return s === 'WON' || s === 'WIN' || s === 'LOST' || s === 'LOSS' || s === 'PUSH';
};

export default function Picks() {
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(null);
  const [isGrading, setIsGrading] = useState(false);
  const [yesterdayReco, setYesterdayReco] = useState(null);

  const gradeNow = async () => {
    try {
      setIsGrading(true);
      await api.post('/api/research/grade');
    } catch (e) {
      // ignore
    } finally {
      setIsGrading(false);
    }
  };

  const load = async () => {
    setLoading(true);
    setErr(null);
    try {
      // Primary source: recommended model history (all leagues)
      // Pull enough lookback to include all 2026 YTD.
      const res = await api.get('/api/research/history', { params: { limit: 20000, lookback_days: 400 } });
      let rows = res.data || [];

      // Also load the exact slate that was recommended yesterday (so "graded" matches "recommended").
      try {
        const ys = await api.get('/api/ncaam/recommended-slate/yesterday');
        setYesterdayReco(ys.data || null);
      } catch (e) {
        // ignore; fallback to history-derived view
        setYesterdayReco(null);
      }
      if (!(Array.isArray(rows) && rows.length > 0)) {
        // Fallback (UI-only): NCAAM history endpoint
        const n = await api.get('/api/ncaam/history', { params: { limit: 2000 } }).catch(() => ({ data: [] }));
        rows = n.data || [];
      }

      // Ensure yesterday is always settled: if any yesterday-slate picks are pending, trigger grading once.
      try {
        const yesterdayEt = (() => {
          const d = new Date();
          d.setDate(d.getDate() - 1);
          return d.toLocaleDateString('en-CA', { timeZone: 'America/New_York' });
        })();
        const etDay = (dt) => {
          if (!dt) return null;
          try { return new Date(dt).toLocaleDateString('en-CA', { timeZone: 'America/New_York' }); } catch (e) { return null; }
        };
        const isGraded = (x) => {
          const s = String(x || '').toUpperCase();
          return s === 'WON' || s === 'WIN' || s === 'LOST' || s === 'LOSS' || s === 'PUSH';
        };
        const dayKey = (h) => etDay(h?.start_time) || etDay(h?.analyzed_at);
        const pendingYesterday = (rows || []).filter((h) => dayKey(h) === yesterdayEt && !isGraded(h.graded_result || h.outcome || h.result)).length;
        const k = `grade_yesterday_attempt_${yesterdayEt}`;
        if (pendingYesterday > 0 && !localStorage.getItem(k)) {
          localStorage.setItem(k, '1');
          await api.post('/api/research/grade');
          const res2 = await api.get('/api/research/history', { params: { limit: 20000, lookback_days: 400 } });
          rows = res2.data || rows;
        }
      } catch (e) { }

      setHistory(rows);
    } catch (e) {
      // Match other pages: if auth fails, prompt for Basement password.
      if (e?.response?.status === 403) {
        const pass = prompt('Authentication failed. Please enter the Basement Password:');
        if (pass) {
          try { localStorage.setItem('basement_password', pass); } catch (err) { }
          window.location.reload();
          return;
        }
      }
      setErr(e?.response?.data?.detail || e?.response?.data?.message || e?.message || 'Failed to load model performance');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const yesterdayEt = useMemo(() => {
    const d = new Date();
    // Convert to ET day string by forcing timezone formatting after subtracting 1 day
    d.setDate(d.getDate() - 1);
    return d.toLocaleDateString('en-CA', { timeZone: 'America/New_York' });
  }, []);

  const graded = useMemo(() => {
    return (history || []).filter((h) => isGraded(h.graded_result || h.outcome || h.result));
  }, [history]);

  const yesterdaySlate = useMemo(() => {
    // Use slate day (event start_time in ET) when available.
    const dayKey = (h) => etDay(h?.start_time) || etDay(h?.analyzed_at);
    return (history || []).filter((h) => dayKey(h) === yesterdayEt);
  }, [history, yesterdayEt]);

  const classify = (h) => {
    const mt = String(h?.market_type || h?.market || h?.bet_type || '').toUpperCase();
    const isParlay = Boolean(h?.is_parlay) || String(h?.bet_type || '').toLowerCase().includes('parlay');
    if (isParlay) return 'PARLAY';
    if (mt.includes('SPREAD')) return 'SPREAD';
    if (mt.includes('TOTAL')) return 'TOTAL';
    if (mt.includes('MONEYLINE') || mt === 'ML') return 'MONEYLINE';
    return mt || 'OTHER';
  };

  const top5Yesterday = useMemo(() => {
    const getEv = (h) => {
      const ev = Number(h?.ev_per_unit ?? h?.ev);
      return Number.isFinite(ev) ? ev : 0;
    };
    return (yesterdaySlate || [])
      .slice()
      .sort((a, b) => getEv(b) - getEv(a))
      .slice(0, 5);
  }, [yesterdaySlate]);

  const gradedYesterday = useMemo(() => {
    const res = (h) => String(h.graded_result || h.outcome || h.result || '').toUpperCase();
    return top5Yesterday.filter((h) => isGraded(res(h)));
  }, [top5Yesterday]);

  const gradedYesterdayStraight = useMemo(() => {
    return (gradedYesterday || []).filter((h) => {
      const c = classify(h);
      return c === 'SPREAD' || c === 'TOTAL';
    });
  }, [gradedYesterday]);

  const gradedYesterdayMlParlay = useMemo(() => {
    return (gradedYesterday || []).filter((h) => {
      const c = classify(h);
      return c === 'MONEYLINE' || c === 'PARLAY';
    });
  }, [gradedYesterday]);

  const pendingYesterday = useMemo(() => {
    const res = (h) => String(h.graded_result || h.outcome || h.result || '').toUpperCase();
    return top5Yesterday.filter((h) => !isGraded(res(h))).length;
  }, [top5Yesterday]);

  const recordFor = (rows) => {
    const res = (h) => String(h.graded_result || h.outcome || h.result || '').toUpperCase();
    const w = (rows || []).filter((h) => res(h) === 'WON' || res(h) === 'WIN').length;
    const l = (rows || []).filter((h) => res(h) === 'LOST' || res(h) === 'LOSS').length;
    const p = (rows || []).filter((h) => res(h) === 'PUSH').length;
    const decided = w + l;
    const winRate = decided > 0 ? (w / decided) * 100 : 0;
    return { w, l, p, decided, winRate };
  };

  const yRecord = useMemo(() => recordFor(gradedYesterday), [gradedYesterday]);
  const yRecordStraight = useMemo(() => recordFor(gradedYesterdayStraight), [gradedYesterdayStraight]);
  const yRecordMlParlay = useMemo(() => recordFor(gradedYesterdayMlParlay), [gradedYesterdayMlParlay]);

  // Preferred: use the exact recommended slate for yesterday when available.
  const recoStraight = useMemo(() => (yesterdayReco?.straight || []), [yesterdayReco]);
  const recoMlParlay = useMemo(() => (yesterdayReco?.ml_parlay || []), [yesterdayReco]);
  const hasReco = useMemo(() => Boolean(yesterdayReco?.slate?.id), [yesterdayReco]);

  const recordForReco = (rows) => {
    const res = (h) => String(h?.outcome || '').toUpperCase();
    const norm = (r) => (r === 'WIN') ? 'WON' : (r === 'LOSS') ? 'LOST' : r;
    const decided = (rows || []).filter((h) => isGraded(res(h)));
    const w = decided.filter((h) => norm(res(h)) === 'WON').length;
    const l = decided.filter((h) => norm(res(h)) === 'LOST').length;
    const p = decided.filter((h) => norm(res(h)) === 'PUSH').length;
    const wl = w + l;
    const winRate = wl > 0 ? (w / wl) * 100.0 : 0.0;
    return { w, l, p, decided: decided.length, winRate };
  };

  const yRecoRecordStraight = useMemo(() => recordForReco(recoStraight), [recoStraight]);
  const yRecoRecordMlParlay = useMemo(() => recordForReco(recoMlParlay), [recoMlParlay]);

  const top6RankPerformance = useMemo(() => {
    // Compute win% by rank for the daily Top 6 recommended picks (ranked by EV/u).
    // Only include 2026 YTD.
    const res = (h) => String(h.graded_result || h.outcome || h.result || '').toUpperCase();
    const isW = (r) => r === 'WON' || r === 'WIN';
    const isL = (r) => r === 'LOST' || r === 'LOSS';

    const ev = (h) => {
      const n = Number(h?.ev_per_unit ?? h?.ev);
      return Number.isFinite(n) ? n : null;
    };

    const ymd = (h) => etDay(h.analyzed_at);

    // group graded picks by day
    const byDay = {};
    (graded || []).forEach((h) => {
      const day = ymd(h);
      if (!day) return;
      if (!String(day).startsWith('2026-')) return;
      const r = res(h);
      if (!(isW(r) || isL(r) || r === 'PUSH')) return;
      const e = ev(h);
      if (!Number.isFinite(e)) return;
      byDay[day] = byDay[day] || [];
      byDay[day].push(h);
    });

    const agg = {
      1: { w: 0, l: 0 },
      2: { w: 0, l: 0 },
      3: { w: 0, l: 0 },
      4: { w: 0, l: 0 },
      5: { w: 0, l: 0 },
      6: { w: 0, l: 0 },
    };

    // Yesterday: determine W/L/P by rank (Top-6 by EV/u).
    const yByRank = { 1: null, 2: null, 3: null, 4: null, 5: null, 6: null };
    try {
      const yRows = (yesterdaySlate || [])
        .slice()
        .sort((a, b) => (ev(b) ?? -999) - (ev(a) ?? -999))
        .slice(0, 6);
      yRows.forEach((h, idx) => {
        const rank = idx + 1;
        const r = res(h);
        if (rank < 1 || rank > 6) return;
        if (isW(r)) yByRank[rank] = 'W';
        else if (isL(r)) yByRank[rank] = 'L';
        else if (r == 'PUSH') yByRank[rank] = 'P';
        else yByRank[rank] = null;
      });
    } catch (e) { }

    Object.keys(byDay).forEach((day) => {
      const rows = (byDay[day] || [])
        .slice()
        .sort((a, b) => (ev(b) ?? -999) - (ev(a) ?? -999));
      const top6 = rows.slice(0, 6);
      top6.forEach((h, idx) => {
        const rank = idx + 1;
        const r = res(h);
        if (isW(r)) agg[rank].w += 1;
        else if (isL(r)) agg[rank].l += 1;
      });
    });

    const out = [1, 2, 3, 4, 5, 6].map((rank) => {
      const w = agg[rank].w;
      const l = agg[rank].l;
      const decided = w + l;
      const winRate = decided ? (w / decided) * 100 : null;
      return {
        rank: `#${rank}`,
        winRate: winRate === null ? null : Number(winRate.toFixed(1)),
        n: decided,
        _fill: (winRate !== null && winRate >= 50) ? '#34d399' : '#60a5fa',
        yesterday: yByRank[rank] || '—',
        _yFill: (yByRank[rank] === 'W') ? '#34d399' : (yByRank[rank] === 'L') ? '#fb7185' : (yByRank[rank] === 'P') ? '#e2e8f0' : '#64748b',
      };
    });

    const vals = out.map((x) => x.winRate).filter((x) => Number.isFinite(x));
    const avg = vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null;

    return { rows: out, avg: avg === null ? null : Number(avg.toFixed(1)) };
  }, [graded, yesterdaySlate]);

  const top6DailyWinRate30 = useMemo(() => {
    // For each ET day (last 30 days), compute win% of that day's Top 6 recommended picks (ranked by EV/u).
    const res = (h) => String(h.graded_result || h.outcome || h.result || '').toUpperCase();
    const isW = (r) => r === 'WON' || r === 'WIN';
    const isL = (r) => r === 'LOST' || r === 'LOSS';
    const ev = (h) => {
      const n = Number(h?.ev_per_unit ?? h?.ev);
      return Number.isFinite(n) ? n : null;
    };

    const now = new Date();
    const days = [];
    for (let i = 29; i >= 0; i--) {
      const d = new Date(now);
      d.setDate(d.getDate() - i);
      const ymd = d.toLocaleDateString('en-CA', { timeZone: 'America/New_York' });
      days.push(ymd);
    }

    const byDay = {};
    (graded || []).forEach((h) => {
      const day = etDay(h.analyzed_at);
      if (!day) return;
      if (!days.includes(day)) return;
      const e = ev(h);
      if (!Number.isFinite(e)) return;
      byDay[day] = byDay[day] || [];
      byDay[day].push(h);
    });

    const rows = days.map((day) => {
      const picks = (byDay[day] || []).slice().sort((a, b) => (ev(b) ?? -999) - (ev(a) ?? -999)).slice(0, 6);
      let w = 0;
      let l = 0;
      picks.forEach((h) => {
        const r = res(h);
        if (isW(r)) w += 1;
        else if (isL(r)) l += 1;
      });
      const decided = w + l;
      const winRate = decided ? (w / decided) * 100 : null;
      return {
        day,
        winRate: winRate === null ? null : Number(winRate.toFixed(1)),
        n: decided,
        _fill: (winRate !== null && winRate >= 50) ? '#34d399' : '#fb7185',
      };
    }).filter((x) => x.winRate !== null);

    const vals = rows.map((x) => x.winRate).filter((x) => Number.isFinite(x));
    const avg = vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
    return { rows, avg: avg === null ? null : Number(avg.toFixed(1)) };
  }, [graded, yesterdaySlate]);

  const dailyPerformance = useMemo(() => {
    // Daily net units based on graded recommended picks.
    // Convention: +1u for win, -1u for loss, 0u for push.
    const res = (h) => String(h.graded_result || h.outcome || h.result || '').toUpperCase();
    const unit = (h) => {
      const r = res(h);
      if (r === 'WON' || r === 'WIN') return 1;
      if (r === 'LOST' || r === 'LOSS') return -1;
      return 0;
    };

    const byDay = {};
    graded.forEach((h) => {
      const day = etDay(h.analyzed_at) || '—';
      byDay[day] = byDay[day] || { day, units: 0, wins: 0, losses: 0, pushes: 0, picks: 0 };
      const r = res(h);
      byDay[day].picks += 1;
      byDay[day].units += unit(h);
      if (r === 'WON' || r === 'WIN') byDay[day].wins += 1;
      else if (r === 'LOST' || r === 'LOSS') byDay[day].losses += 1;
      else if (r === 'PUSH') byDay[day].pushes += 1;
    });

    return Object.values(byDay)
      .filter((x) => x.day && x.day !== '—')
      .sort((a, b) => String(a.day).localeCompare(String(b.day)))
      .slice(-30);
  }, [graded, yesterdayEt]);

  const confidenceBreakdown = useMemo(() => {
    const normRes = (h) => String(h.graded_result || h.outcome || h.result || '').toUpperCase();
    const isW = (r) => r === 'WON' || r === 'WIN';
    const isL = (r) => r === 'LOST' || r === 'LOSS';

    const bucket = (h) => {
      const c = Number(h?.confidence_0_100 ?? h?.confidence ?? 0);
      if (c >= 80) return 'High';
      if (c >= 50) return 'Medium';
      return 'Low';
    };

    const base = { High: [], Medium: [], Low: [] };
    graded.forEach((h) => {
      base[bucket(h)].push(h);
    });

    const calc = (rows) => {
      const w = rows.filter((h) => isW(normRes(h))).length;
      const l = rows.filter((h) => isL(normRes(h))).length;
      const p = rows.filter((h) => normRes(h) === 'PUSH').length;
      const decided = w + l;
      const winRate = decided > 0 ? (w / decided) * 100 : null;
      // Same simplifying assumption used elsewhere in UI: $10 stake, -110 style
      const roi = rows.length > 0 ? ((w * 9.09 - l * 10) / (rows.length * 10)) * 100 : null;
      return { w, l, p, decided, winRate, roi, n: rows.length };
    };

    const out = ['High', 'Medium', 'Low'].map((k) => {
      const s = calc(base[k]);
      return {
        bucket: k,
        picks: s.n,
        wins: s.w,
        losses: s.l,
        pushes: s.p,
        winRate: s.winRate === null ? null : Number(s.winRate.toFixed(1)),
        roi: s.roi === null ? null : Number(s.roi.toFixed(1)),
      };
    }).filter((x) => x.picks > 0);

    return out;
  }, [graded, yesterdaySlate]);

  const edgeBandChart = useMemo(() => {
    // EV/u decimal bands
    const bands = [
      { lo: 0.0, hi: 0.05, label: '0–5%' },
      { lo: 0.05, hi: 0.1, label: '5–10%' },
      { lo: 0.1, hi: 0.15, label: '10–15%' },
      { lo: 0.15, hi: 0.2, label: '15–20%' },
      { lo: 0.2, hi: 0.25, label: '20–25%' },
      { lo: 0.25, hi: 0.3, label: '25–30%' },
      { lo: 0.3, hi: null, label: '30%+' },
    ];

    const res = (h) => String(h.graded_result || h.outcome || h.result || '').toUpperCase();
    const ev = (h) => {
      const n = Number(h?.ev_per_unit ?? h?.ev);
      return Number.isFinite(n) ? n : null;
    };

    return bands
      .map((b) => {
        const rows = graded.filter((h) => {
          const e = ev(h);
          if (!Number.isFinite(e)) return false;
          if (b.hi == null) return e >= b.lo;
          return e >= b.lo && e < b.hi;
        });
        const w = rows.filter((h) => res(h) === 'WON' || res(h) === 'WIN').length;
        const l = rows.filter((h) => res(h) === 'LOST' || res(h) === 'LOSS').length;
        const decided = w + l;
        const winRate = decided > 0 ? (w / decided) * 100 : 0;
        return {
          band: b.label,
          picks: rows.length,
          wins: w,
          losses: l,
          winRate: Number(winRate.toFixed(1)),
        };
      })
      .filter((x) => x.picks > 0);
  }, [graded, yesterdaySlate]);

  return (
    <div className="space-y-6">
      {err && <div className="p-3 rounded-lg bg-red-900/20 border border-red-800 text-red-200 text-sm">{err}</div>}

      {!loading && !err && (!history || history.length === 0) && (
        <div className="p-4 rounded-lg bg-slate-900/40 border border-slate-800 text-slate-400 text-sm">
          No model-performance history returned yet. If it still shows empty, it usually means the backend isn’t returning any stored recommended picks for your user.
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Yesterday graded results — Straight bets (Spreads/Totals) */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <div className="flex items-center gap-2 mb-2">
            <BarChart3 size={18} className="text-emerald-300" />
            <div className="text-sm font-black text-slate-100 uppercase tracking-wider">Yesterday (graded) — Top 5 Recommended Spreads & Totals</div>
            <div className="ml-auto flex items-center gap-2">
              <div className="text-xs text-slate-500">{yesterdayEt}</div>
              {pendingYesterday > 0 && (
                <button
                  onClick={async () => { await gradeNow(); await load(); }}
                  disabled={isGrading}
                  className={`px-2 py-1 rounded-lg text-xs font-bold border transition ${isGrading ? 'text-slate-500 border-slate-800 bg-slate-900/40' : 'text-amber-200 border-amber-900/40 bg-amber-900/20 hover:bg-amber-900/30'}`}
                  title="Run grading now"
                >
                  {isGrading ? 'Grading…' : 'Grade now'}
                </button>
              )}
            </div>
          </div>
          <div className="flex flex-wrap gap-6 text-sm">
            {hasReco && (
              <div>
                <div className="text-slate-400 text-xs">Source</div>
                <div className="text-white font-black">{String(yesterdayReco?.slate?.source || '—').toUpperCase()}</div>
              </div>
            )}
            <div>
              <div className="text-slate-400 text-xs">Record</div>
              <div className="text-white font-black">{(hasReco ? yRecoRecordStraight.w : yRecordStraight.w)}-{(hasReco ? yRecoRecordStraight.l : yRecordStraight.l)}-{(hasReco ? yRecoRecordStraight.p : yRecordStraight.p)}</div>
            </div>
            <div>
              <div className="text-slate-400 text-xs">Win rate</div>
              <div className="text-white font-black">{(hasReco ? yRecoRecordStraight.decided : yRecordStraight.decided) ? `${(hasReco ? yRecoRecordStraight.winRate : yRecordStraight.winRate).toFixed(1)}%` : '—'}</div>
            </div>
            <div>
              <div className="text-slate-400 text-xs">Graded picks</div>
              <div className="text-white font-black">{hasReco ? recoStraight.length : gradedYesterdayStraight.length}</div>
            </div>
          </div>

          {/* Breakdown by confidence (yesterday only) */}
          {(() => {
            const bucket = (h) => {
              const c = Number(h?.confidence_0_100 ?? h?.confidence ?? 0);
              if (c >= 80) return 'High';
              if (c >= 50) return 'Medium';
              return 'Low';
            };
            const res = (h) => String(h.graded_result || h.outcome || h.result || '').toUpperCase();
            const norm = (r) => (r === 'WIN') ? 'WON' : (r === 'LOSS') ? 'LOST' : r;
            const rows = (gradedYesterdayStraight || []).map((h) => ({ b: bucket(h), r: norm(res(h)) }));
            const by = { High: { w: 0, l: 0, p: 0 }, Medium: { w: 0, l: 0, p: 0 }, Low: { w: 0, l: 0, p: 0 } };
            rows.forEach(({ b, r }) => {
              if (r === 'WON') by[b].w += 1;
              else if (r === 'LOST') by[b].l += 1;
              else if (r === 'PUSH') by[b].p += 1;
            });
            const tiles = ['High', 'Medium', 'Low'].map((k) => ({ k, ...by[k] }));
            if (!gradedYesterdayStraight || gradedYesterdayStraight.length === 0) return null;
            return (
              <div className="mt-4 grid grid-cols-1 md:grid-cols-3 gap-3">
                {tiles.map((t) => (
                  <div key={t.k} className="bg-slate-950/20 border border-slate-800 rounded-xl p-4">
                    <div className="text-[10px] uppercase tracking-widest text-slate-500 font-black">{t.k} confidence</div>
                    <div className="mt-1 text-slate-100 font-black text-xl">{t.w}-{t.l}{t.p ? `-${t.p}` : ''}</div>
                  </div>
                ))}
              </div>
            );
          })()}
          {(() => {
            const pending = pendingYesterday;
            if ((yesterdaySlate || []).length === 0) {
              return <div className="mt-3 text-xs text-slate-500">No recommended picks found for yesterday.</div>;
            }
            if (gradedYesterdayStraight.length === 0 && pending > 0) {
              return <div className="mt-3 text-xs text-slate-500">Yesterday has {pending} pick(s) still pending / ungraded. Click “Grade now”.</div>;
            }
            if (gradedYesterdayStraight.length === 0) {
              return <div className="mt-3 text-xs text-slate-500">No graded spreads/totals found for yesterday yet.</div>;
            }
            if (pending > 0) {
              return <div className="mt-3 text-xs text-slate-500">Also pending: {pending}</div>;
            }
            return null;
          })()}

          {/* Quick list (yesterday slate) — spreads & totals only */}
          {(hasReco ? (recoStraight.length > 0) : (gradedYesterdayStraight.length > 0)) && (
            <div className="mt-4 space-y-2">
              {(() => {
                const getEv = (h) => {
                  const ev = Number(h?.ev_per_unit ?? h?.ev);
                  return Number.isFinite(ev) ? ev : 0;
                };
                const base = (hasReco ? (recoStraight || []) : (gradedYesterdayStraight || []));
                const rows = base.slice().sort((a, b) => getEv(b) - getEv(a));
                return rows.slice(0, 6).map((h, idx) => {
                  const out = String(h.graded_result || h.outcome || h.result || 'PENDING').toUpperCase();
                  const cls = out === 'WON' || out === 'WIN' ? 'text-green-300' : out === 'LOST' || out === 'LOSS' ? 'text-red-300' : out === 'PUSH' ? 'text-slate-300' : 'text-slate-500';
                  return (
                    <div key={idx} className="flex items-center justify-between gap-3 p-3 rounded-lg border border-slate-800 bg-slate-950/20">
                      <div className="min-w-0">
                        <div className="text-xs font-black text-slate-100 whitespace-normal break-words leading-snug">
                          <span className="text-slate-400 mr-2">#{idx + 1}</span>
                          {h.sport || '—'} • {(h.away_team && h.home_team) ? `${h.away_team} @ ${h.home_team}` : (h.matchup || '—')}
                        </div>
                        <div className="text-xs text-slate-400 whitespace-normal break-words leading-snug">{h.market_type || h.bet_type || '—'} • {h.selection || '—'}</div>
                      </div>
                      <div className={`text-xs font-mono font-black ${cls}`}>{out}</div>
                    </div>
                  );
                });
              })()}
              {((hasReco ? recoStraight.length : gradedYesterdayStraight.length) > 6) && <div className="text-[11px] text-slate-500">Showing first 6.</div>}
            </div>
          )}
        </div>

        {/* Yesterday graded results — Moneyline & Parlays */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <div className="flex items-center gap-2 mb-2">
            <BarChart3 size={18} className="text-blue-300" />
            <div className="text-sm font-black text-slate-100 uppercase tracking-wider">Yesterday (graded) — Moneyline & Parlays</div>
            <div className="ml-auto flex items-center gap-2">
              <div className="text-xs text-slate-500">{yesterdayEt}</div>
            </div>
          </div>
          <div className="flex flex-wrap gap-6 text-sm">
            <div>
              <div className="text-slate-400 text-xs">Record</div>
              <div className="text-white font-black">{(hasReco ? yRecoRecordMlParlay.w : yRecordMlParlay.w)}-{(hasReco ? yRecoRecordMlParlay.l : yRecordMlParlay.l)}-{(hasReco ? yRecoRecordMlParlay.p : yRecordMlParlay.p)}</div>
            </div>
            <div>
              <div className="text-slate-400 text-xs">Win rate</div>
              <div className="text-white font-black">{(hasReco ? yRecoRecordMlParlay.decided : yRecordMlParlay.decided) ? `${(hasReco ? yRecoRecordMlParlay.winRate : yRecordMlParlay.winRate).toFixed(1)}%` : '—'}</div>
            </div>
            <div>
              <div className="text-slate-400 text-xs">Graded picks</div>
              <div className="text-white font-black">{hasReco ? recoMlParlay.length : gradedYesterdayMlParlay.length}</div>
            </div>
          </div>

          {gradedYesterdayMlParlay.length > 0 && (
            <div className="mt-4 space-y-2">
              {(() => {
                const getEv = (h) => {
                  const ev = Number(h?.ev_per_unit ?? h?.ev);
                  return Number.isFinite(ev) ? ev : 0;
                };
                const base = (hasReco ? (recoMlParlay || []) : (gradedYesterdayMlParlay || []));
                const rows = base.slice().sort((a, b) => getEv(b) - getEv(a));
                return rows.slice(0, 6).map((h, idx) => {
                  const out = String(h.graded_result || h.outcome || h.result || 'PENDING').toUpperCase();
                  const cls = out === 'WON' || out === 'WIN' ? 'text-green-300' : out === 'LOST' || out === 'LOSS' ? 'text-red-300' : out === 'PUSH' ? 'text-slate-300' : 'text-slate-500';
                  return (
                    <div key={idx} className="flex items-center justify-between gap-3 p-3 rounded-lg border border-slate-800 bg-slate-950/20">
                      <div className="min-w-0">
                        <div className="text-xs font-black text-slate-100 whitespace-normal break-words leading-snug">
                          <span className="text-slate-400 mr-2">#{idx + 1}</span>
                          {h.sport || '—'} • {(h.away_team && h.home_team) ? `${h.away_team} @ ${h.home_team}` : (h.matchup || '—')}
                        </div>
                        <div className="text-xs text-slate-400 whitespace-normal break-words leading-snug">{h.market_type || h.bet_type || '—'} • {h.selection || '—'}</div>
                      </div>
                      <div className={`text-xs font-mono font-black ${cls}`}>{out}</div>
                    </div>
                  );
                });
              })()}
              {((hasReco ? recoMlParlay.length : gradedYesterdayMlParlay.length) > 6) && <div className="text-[11px] text-slate-500">Showing first 6.</div>}
            </div>
          )}
        </div>

        {/* Top 6 recommended: win% by rank */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <div className="flex items-end justify-between gap-3 mb-2">
            <div className="text-sm font-black text-slate-100 uppercase tracking-wider">Top 6 recommended (2026 YTD) — win% by rank</div>
            <div className="text-[11px] text-slate-500">Avg: {top6RankPerformance?.avg !== null && top6RankPerformance?.avg !== undefined ? `${top6RankPerformance.avg.toFixed(1)}%` : '—'}</div>
          </div>
          <div className="h-[220px]">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={top6RankPerformance.rows} layout="vertical" margin={{ top: 8, right: 34, left: 10, bottom: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                <XAxis type="number" domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} interval={0} tick={{ fill: '#94a3b8', fontSize: 11 }} />
                <YAxis
                  type="category"
                  dataKey="rank"
                  interval={0}
                  width={58}
                  tick={(props) => {
                    const { x, y, payload } = props;
                    // payload.value is already "#1", "#2" etc.
                    const label = String(payload?.value || '');
                    const row = (top6RankPerformance.rows || []).find((r) => String(r.rank) === label);
                    const v = String(row?.yesterday || '—');
                    const fill = row?._yFill || '#64748b';
                    const cx = (x || 0);
                    const cy = (y || 0);
                    return (
                      <g>
                        <text x={cx} y={cy + 4} textAnchor="end" fontSize={11} fontWeight={900} fill="#e2e8f0" transform={`translate(-36,0)`}>{label}</text>
                        <rect x={cx - 30} y={cy - 8} rx={6} ry={6} width={22} height={16} fill={fill} opacity={0.20} />
                        <text x={cx - 19} y={cy + 3.5} textAnchor="middle" fontSize={11} fontWeight={900} fill={fill}>{v}</text>
                      </g>
                    );
                  }}
                />
                <Tooltip
                  contentStyle={{ background: '#0b1220', border: '1px solid #334155', borderRadius: 8 }}
                  labelStyle={{ color: '#e2e8f0' }}
                  formatter={(v, name) => (name === 'Win%' ? [`${Number(v).toFixed(1)}%`, 'Win%'] : [v, name])}
                />
                <ReferenceLine x={50} stroke="#94a3b8" strokeDasharray="4 4" />
                <Bar dataKey="winRate" name="Win%" radius={[6, 6, 6, 6]}>
                  {(top6RankPerformance.rows || []).map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry._fill || '#60a5fa'} />
                  ))}
                  <LabelList dataKey="winRate" position="right" formatter={(v) => (v === null || v === undefined ? '' : `${v}%`)} fill="#94a3b8" fontSize={11} />
                  <LabelList dataKey="n" position="insideRight" formatter={(v) => (v ? `N=${v}` : '')} fill="#0b1220" fontSize={10} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* Existing analytics (kept) */}
      <ModelPerformanceAnalytics history={history || []} />
    </div>
  );
}

