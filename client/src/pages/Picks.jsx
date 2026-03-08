import React, { useEffect, useMemo, useState } from 'react';
import api from '../api/axios';
import { RefreshCw, BarChart3, ArrowUpDown, ChevronUp, ChevronDown } from 'lucide-react';
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
  const [sortConfig, setSortConfig] = useState({ key: 'created_at', direction: 'desc' });


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
  }, [graded, yesterdaySlate]);

  const handleSort = (key) => {
    let direction = 'desc';
    if (sortConfig.key === key && sortConfig.direction === 'desc') {
      direction = 'asc';
    }
    setSortConfig({ key, direction });
  };

  const isRecommendedHistoryItem = (h) => {
    try {
      const mt = String(h?.market_type || h?.market || '').toUpperCase();
      const sel = String(h?.selection || '').trim();
      const pick = String(h?.pick || '').toUpperCase();
      const ev = Number(h?.ev_per_unit ?? h?.ev ?? 0);
      if (!mt || mt === 'AUTO') return false;
      if (!sel || sel === '—') return false;
      if (!pick || pick === 'NONE') return false;
      if (!Number.isFinite(ev) || ev < 0.02) return false;
      return true;
    } catch (e) {
      return false;
    }
  };

  const isTodayET = (ts) => {
    if (!ts) return false;
    try {
      const d = new Date(ts);
      const day = d.toLocaleDateString('en-US', { timeZone: 'America/New_York' });
      const today = new Date().toLocaleDateString('en-US', { timeZone: 'America/New_York' });
      return day === today;
    } catch (e) {
      return false;
    }
  };

  const getSortedHistory = () => {
    return [...history].sort((a, b) => {
      const key = sortConfig.key === 'edge' ? 'created_at' : sortConfig.key;
      let aVal = a[key] || '';
      let bVal = b[key] || '';
      if (aVal < bVal) return sortConfig.direction === 'asc' ? -1 : 1;
      if (aVal > bVal) return sortConfig.direction === 'asc' ? 1 : -1;
      return 0;
    });
  };

  const getRecommendedHistory = () => {
    const sorted = getSortedHistory()
      .filter(isRecommendedHistoryItem)
      .filter(h => {
        // Exclude games that haven't started yet (Strict Date check)
        const st = h?.start_time;
        if (!st) return false;

        try {
          const now = new Date();
          const gameStart = new Date(st);

          const todayStr = now.toLocaleDateString('en-CA', { timeZone: 'America/New_York' });
          const gameDayStr = gameStart.toLocaleDateString('en-CA', { timeZone: 'America/New_York' });

          // Exclude if game is tomorrow or later
          if (gameDayStr > todayStr) return false;

          // If it's today, allow it if it's within 10 mins of starting
          // This keeps the history feed responsive to currently playing/about to start games.
          return gameStart <= new Date(now.getTime() + 10 * 60000);
        } catch (e) {
          return false;
        }
      });
    return sorted;
  };

  const SortIcon = ({ column }) => {
    if (sortConfig.key !== column) return <ArrowUpDown size={12} className="ml-1 opacity-20" />;
    return sortConfig.direction === 'asc' ? <ChevronUp size={12} className="ml-1 text-blue-400" /> : <ChevronDown size={12} className="ml-1 text-blue-400" />;
  };

  return (
    <div className="space-y-6">
      {err && <div className="p-3 rounded-lg bg-red-900/20 border border-red-800 text-red-200 text-sm">{err}</div>}

      {!loading && !err && (!history || history.length === 0) && (
        <div className="p-4 rounded-lg bg-slate-900/40 border border-slate-800 text-slate-400 text-sm">
          No model-performance history returned yet. If it still shows empty, it usually means the backend isn’t returning any stored recommended picks for your user.
        </div>
      )}

      {!loading && !err && history.length > 0 && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden mb-6">
          {(() => {
            const hist = getRecommendedHistory();
            const etDay = (ts) => {
              try {
                return new Date(ts).toLocaleDateString('en-CA', { timeZone: 'America/New_York' });
              } catch (e) {
                return null;
              }
            };
            const normalizeOutcome = (x) => {
              const o = (x?.graded_result || x?.outcome || x?.result || 'PENDING');
              const s = String(o).toUpperCase();
              if (s === 'WON' || s === 'WIN') return 'WON';
              if (s === 'LOST' || s === 'LOSS') return 'LOST';
              if (s === 'PUSH') return 'PUSH';
              return 'PENDING';
            };

            const days = [...new Set(hist.map(h => etDay(h?.start_time) || etDay(h?.analyzed_at || h?.created_at)).filter(Boolean))].sort();

            // Find most recent day with at least one graded TOP 6 pick
            let lastSettledDay = null;
            const reversedDays = [...days].reverse();
            for (const d of reversedDays) {
              const top6ForDay = hist.filter(h => (etDay(h?.start_time) || etDay(h?.analyzed_at || h?.created_at)) === d)
                .sort((a, b) => (Number(b.ev_per_unit || b.ev || 0)) - (Number(a.ev_per_unit || a.ev || 0)))
                .slice(0, 6);
              if (top6ForDay.some(h => ['WON', 'LOST', 'PUSH'].includes(normalizeOutcome(h)))) {
                lastSettledDay = d;
                break;
              }
            }

            const lastDay = lastSettledDay || (days.length ? days[days.length - 1] : null);

            // Only consider the Top 6 picks (by EV) for the summary to avoid grading "noise"
            const dayRows = lastDay
              ? hist.filter(h => (etDay(h?.start_time) || etDay(h?.analyzed_at || h?.created_at)) === lastDay)
                .sort((a, b) => (Number(b.ev_per_unit || b.ev || 0)) - (Number(a.ev_per_unit || a.ev || 0)))
                .slice(0, 6)
              : [];

            const gradedCount = dayRows.filter(h => ['WON', 'LOST', 'PUSH'].includes(normalizeOutcome(h)));
            const w = gradedCount.filter(h => normalizeOutcome(h) === 'WON').length;
            const l = gradedCount.filter(h => normalizeOutcome(h) === 'LOST').length;
            const p = gradedCount.filter(h => normalizeOutcome(h) === 'PUSH').length;
            const winRate = (w + l) ? (w / (w + l) * 100) : 0;

            const confBucket = (h) => {
              const c = Number(h?.confidence_0_100 ?? h?.confidence ?? 0);
              if (c >= 80) return 'High';
              if (c >= 50) return 'Medium';
              return 'Low';
            };

            const byConf = { High: [], Medium: [], Low: [] };
            gradedCount.forEach((h) => {
              byConf[confBucket(h)].push(h);
            });

            const confStats = (arr) => {
              const ww = arr.filter(x => normalizeOutcome(x) === 'WON').length;
              const ll = arr.filter(x => normalizeOutcome(x) === 'LOST').length;
              const pp = arr.filter(x => normalizeOutcome(x) === 'PUSH').length;
              const wr = (ww + ll) ? (ww / (ww + ll) * 100) : null;
              return { w: ww, l: ll, p: pp, wr };
            };

            const hi = confStats(byConf.High);
            const md = confStats(byConf.Medium);
            const lo = confStats(byConf.Low);

            const fmtMDY = (ymd) => {
              try {
                const [yy, mm, dd] = String(ymd || '').split('-');
                if (yy && mm && dd) return `${mm}/${dd}/${yy}`;
              } catch (e) { }
              return ymd || '—';
            };

            return (
              <div className="px-6 py-4 border-b border-slate-700 bg-slate-900/20">
                <div className="flex items-end justify-between gap-4 mb-3">
                  <div>
                    <div className="text-white font-black text-xl">{fmtMDY(lastDay)} Summary</div>
                  </div>
                  <div className="text-[11px] text-slate-500 uppercase tracking-widest font-bold">Most Recent Graded Slate</div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                  <div className="bg-slate-950/20 border border-slate-700/40 rounded-2xl p-4">
                    <div className="text-[11px] text-slate-400 font-semibold uppercase tracking-wider">Bets graded</div>
                    <div className="mt-1 text-slate-100 font-black text-3xl">{gradedCount.length}</div>
                    <div className="text-[11px] text-slate-400">W / L / P only</div>
                    {dayRows.length !== gradedCount.length && (
                      <div className="text-[12px] text-slate-300 mt-1">Pending: {Math.max(0, dayRows.length - gradedCount.length)}</div>
                    )}
                  </div>
                  <div className="bg-slate-950/20 border border-slate-700/40 rounded-2xl p-4">
                    <div className="text-[11px] text-slate-400 font-semibold uppercase tracking-wider">Record</div>
                    <div className="mt-1 text-slate-100 font-black text-3xl">{w}-{l}-{p}</div>
                    <div className="text-[11px] text-slate-400 italic">top-6 ranked plays only</div>
                  </div>
                  <div className="bg-slate-950/20 border border-slate-700/40 rounded-2xl p-4">
                    <div className="text-[11px] text-slate-400 font-semibold uppercase tracking-wider">Win Rate</div>
                    <div className="mt-1 text-slate-100 font-black text-3xl">{winRate.toFixed(1)}%</div>
                    <div className="text-[11px] text-slate-400">weighted avg</div>
                  </div>
                </div>

                <div className="mt-3 grid grid-cols-1 md:grid-cols-3 gap-3">
                  {(() => {
                    const tiles = [
                      { label: 'High', s: hi, cls: 'text-green-300' },
                      { label: 'Medium', s: md, cls: 'text-amber-300' },
                      { label: 'Low', s: lo, cls: 'text-purple-300' },
                    ];
                    return tiles.map(({ label, s, cls }) => (
                      <div key={label} className="bg-slate-950/20 border border-slate-700/40 rounded-2xl p-4">
                        <div className="text-[11px] text-slate-400 font-semibold">{label} confidence</div>
                        <div className={`mt-1 font-black text-xl ${cls}`}>{s.w}-{s.l}{s.p ? `-${s.p}` : ''}</div>
                        <div className="text-[11px] text-slate-400">Win%: <span className="text-slate-200 font-semibold">{s.wr === null ? '—' : `${s.wr.toFixed(1)}%`}</span> • N={(s.w + s.l + s.p)}</div>
                      </div>
                    ));
                  })()}
                </div>
              </div>
            );
          })()}
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

      {/* Full Audit Table (Moved from Today tab) */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden mt-10">
        <div className="px-6 py-4 border-b border-slate-800 bg-slate-900/50 flex items-center justify-between">
          <h3 className="text-white font-black text-lg">Full Recommended Pick History</h3>
          <div className="text-[11px] text-slate-500 uppercase tracking-widest font-bold">Audit & Performance Logs</div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="text-slate-400 border-b border-slate-700 bg-slate-800/50">
                <th className="py-2 px-4 text-xs font-bold uppercase tracking-wider cursor-pointer hover:text-white transition-colors" onClick={() => handleSort('created_at')}>
                  <div className="flex items-center">Date <SortIcon column="created_at" /></div>
                </th>
                <th className="py-2 px-4 text-xs font-bold uppercase tracking-wider">Rec#</th>
                <th className="py-2 px-4 text-xs font-bold uppercase tracking-wider cursor-pointer hover:text-white transition-colors" onClick={() => handleSort('sport')}>
                  <div className="flex items-center">Sport <SortIcon column="sport" /></div>
                </th>
                <th className="py-2 px-4 text-xs font-bold uppercase tracking-wider cursor-pointer hover:text-white transition-colors" onClick={() => handleSort('matchup')}>
                  <div className="flex items-center">Matchup <SortIcon column="matchup" /></div>
                </th>
                <th className="py-2 px-4 text-xs font-bold uppercase tracking-wider cursor-pointer hover:text-white transition-colors" onClick={() => handleSort('bet_on')}>
                  <div className="flex items-center">Pick <SortIcon column="bet_on" /></div>
                </th>
                <th className="py-2 px-4 text-xs font-bold uppercase tracking-wider">Lines</th>
                <th className="py-2 px-4 text-xs font-bold uppercase tracking-wider cursor-pointer hover:text-white transition-colors" onClick={() => handleSort('edge')}>
                  <div className="flex items-center">Edge <SortIcon column="edge" /></div>
                </th>
                <th className="py-2 px-4 text-xs font-bold uppercase tracking-wider cursor-pointer hover:text-white transition-colors" onClick={() => handleSort('result')}>
                  <div className="flex items-center">Result <SortIcon column="result" /></div>
                </th>
                <th className="py-2 px-4 text-xs font-bold uppercase tracking-wider">Score</th>
              </tr>
            </thead>
            <tbody>
              {(() => {
                const histRaw = getRecommendedHistory();
                const etDayForRecap = (ts) => {
                  try {
                    return new Date(ts).toLocaleDateString('en-CA', { timeZone: 'America/New_York' });
                  } catch (e) {
                    return null;
                  }
                };
                const keyFor = (x) => {
                  return String(x?.id || '')
                    || `${x?.event_id || 'evt'}|${x?.market_type || x?.market || ''}|${x?.selection || ''}|${x?.bet_price || ''}|${x?.analyzed_at || x?.created_at || ''}`;
                };

                const rankByKey = {};
                const groups = {};
                histRaw.forEach((h) => {
                  const d = etDayForRecap(h?.start_time || h?.analyzed_at || h?.created_at);
                  if (!d) return;
                  groups[d] = groups[d] || [];
                  groups[d].push(h);
                });
                Object.keys(groups).forEach((d) => {
                  const arr = groups[d];
                  arr.sort((a, b) => {
                    const ae = Number(a?.ev_per_unit ?? a?.ev ?? 0);
                    const be = Number(b?.ev_per_unit ?? b?.ev ?? 0);
                    return be - ae;
                  });
                  arr.forEach((h, i) => {
                    rankByKey[keyFor(h)] = i + 1;
                  });
                });

                // Filter to only Top 6 per day
                const histAll = histRaw.filter(h => rankByKey[keyFor(h)] <= 6);

                return histAll.map((item) => {
                  let recs = [];
                  try {
                    if (item.outputs_json) {
                      const out = JSON.parse(item.outputs_json);
                      if (out.recommendations) recs = out.recommendations;
                    }
                    if (recs.length === 0 && item.recommendation_json) {
                      recs = JSON.parse(item.recommendation_json);
                    }
                    if (recs.length === 0 && item.pick) {
                      recs = [{ side: item.pick, line: item.bet_line, edge: item.ev_per_unit || item.edge }];
                    }
                  } catch (e) { }

                  const recRank = rankByKey[keyFor(item)] || null;
                  const mainRec = recs[0] || {};
                  const resultStatus = item.graded_result || item.outcome || 'Pending';
                  const s = String(resultStatus).toUpperCase();
                  const isWon = s === 'WON' || s === 'WIN';
                  const isLost = s === 'LOST' || s === 'LOSS';
                  const isPush = s === 'PUSH';

                  const formatDateMDY = (ts) => {
                    if (!ts) return '';
                    try {
                      const d = new Date(ts);
                      return d.toLocaleDateString('en-US', { timeZone: 'America/New_York', month: 'numeric', day: 'numeric', year: '2-digit' });
                    } catch (e) { return ts; }
                  };

                  return (
                    <tr key={keyFor(item)} className="border-b border-slate-700/40 hover:bg-slate-800/20 transition-colors text-[13px]">
                      <td className="py-2 px-4 text-slate-400 font-mono whitespace-nowrap">
                        {formatDateMDY(item.start_time || item.analyzed_at || item.created_at)}
                      </td>
                      <td className="py-2 px-4 whitespace-nowrap">
                        {recRank ? (
                          <span className={`inline-flex items-center justify-center w-5 h-5 rounded-full text-[10px] font-bold ${recRank <= 6 ? 'bg-emerald-500/20 text-emerald-300 ring-1 ring-emerald-500/30' : 'bg-slate-700/30 text-slate-400'
                            }`}>
                            {recRank}
                          </span>
                        ) : '—'}
                      </td>
                      <td className="py-2 px-4 text-slate-300 font-bold uppercase text-[11px] whitespace-nowrap">
                        {item.sport || item.league || '—'}
                      </td>
                      <td className="py-2 px-4 text-slate-200 font-semibold whitespace-nowrap">
                        {item.matchup || item.game || '—'}
                      </td>
                      <td className="py-2 px-4 font-black whitespace-nowrap">
                        <span className="text-white">{item.bet_on || mainRec.side || '—'}</span>
                        {mainRec.line && mainRec.line !== 0 && (
                          <span className="text-slate-400 ml-1">({mainRec.line > 0 ? '+' : ''}{mainRec.line})</span>
                        )}
                      </td>
                      <td className="py-2 px-4 text-slate-400 whitespace-nowrap">
                        <span className="font-mono">{item.bet_price || '—'}</span>
                      </td>
                      <td className="py-2 px-4 whitespace-nowrap">
                        <span className={`font-black ${(item.ev_per_unit || item.edge) > 0.05 ? 'text-emerald-400' : 'text-slate-300'}`}>
                          {item.ev_per_unit ? `+${(item.ev_per_unit * 100).toFixed(1)}%` : (item.edge ? `+${item.edge}%` : '—')}
                        </span>
                      </td>
                      <td className="py-2 px-4 whitespace-nowrap">
                        {isWon ? (
                          <span className="px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-400 font-black tracking-tighter ring-1 ring-emerald-500/20">WON</span>
                        ) : isLost ? (
                          <span className="px-2 py-0.5 rounded-full bg-red-500/15 text-red-500 font-black tracking-tighter ring-1 ring-red-500/20">LOST</span>
                        ) : isPush ? (
                          <span className="px-2 py-0.5 rounded-full bg-slate-500/15 text-slate-400 font-black tracking-tighter ring-1 ring-slate-500/20">PUSH</span>
                        ) : (
                          <span className="px-2 py-0.5 rounded-full bg-slate-800/50 text-slate-500 font-bold tracking-tighter">PENDING</span>
                        )}
                      </td>
                      <td className="py-2 px-4 text-slate-400 font-mono text-xs whitespace-nowrap">
                        {item.score || '—'}
                      </td>
                    </tr>
                  );
                });
              })()}
            </tbody>
          </table>
        </div>
        {getRecommendedHistory().length === 0 && (
          <div className="py-12 text-center text-slate-500 italic">No historical recommended picks found in logs.</div>
        )}
      </div>
    </div>
  );
}

