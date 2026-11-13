import React, { useEffect, useState } from 'react';
import api from '../api/axios';
import { RefreshCw, Activity, TrendingUp } from 'lucide-react';
import PerformanceReportNCAAM from '../components/PerformanceReportNCAAM';

const formatCurrency = (val) => {
  try {
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(val || 0);
  } catch (e) {
    return `$${Number(val || 0).toFixed(2)}`;
  }
};

export default function Dashboard({ financials, periodStats }) {
  const [modelPerf, setModelPerf] = useState(null);
  const [loadingPerf, setLoadingPerf] = useState(false);

  const loadPerf = async () => {
    setLoadingPerf(true);
    try {
      const res = await api.get('/api/ncaam/performance-report', { params: { days: 30 } });
      setModelPerf(res.data || null);
    } catch (e) {
      setModelPerf(null);
    } finally {
      setLoadingPerf(false);
    }
  };

  useEffect(() => { loadPerf(); }, []);

  const dk = (financials?.breakdown || []).find(x => x.provider === 'DraftKings');
  const fd = (financials?.breakdown || []).find(x => x.provider === 'FanDuel');
  const totalInPlay = (financials?.breakdown || [])
    .filter(p => p.provider === 'DraftKings' || p.provider === 'FanDuel')
    .reduce((s, p) => s + (p.in_play || 0), 0);

  const p7 = periodStats?.['7d'];
  const p30 = periodStats?.['30d'];

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <div>
          <h1 className="text-2xl font-black text-white">Dashboard</h1>
          <p className="text-slate-400 text-sm mt-1">Balances and high-level performance KPIs.</p>
        </div>
        <button
          onClick={loadPerf}
          className="ml-auto px-3 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg text-sm font-bold flex items-center gap-2"
        >
          <RefreshCw size={16} className={loadingPerf ? 'animate-spin' : ''} /> Refresh KPIs
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
          <div className="text-[10px] uppercase tracking-widest text-slate-500 font-black">Total In Play</div>
          <div className="mt-1 text-2xl font-black text-white">{formatCurrency(totalInPlay)}</div>
          <div className="mt-2 text-xs text-slate-500">DK {formatCurrency(dk?.in_play || 0)} • FD {formatCurrency(fd?.in_play || 0)}</div>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
          <div className="flex items-center gap-2 text-[10px] uppercase tracking-widest text-slate-500 font-black">
            <TrendingUp size={14} /> Last 7 days
          </div>
          <div className={`mt-1 text-2xl font-black ${((p7?.roi || 0) >= 0) ? 'text-green-400' : 'text-red-400'}`}>{(p7?.roi ?? 0).toFixed(1)}% ROI</div>
          <div className="mt-2 text-xs text-slate-500">{p7?.wins ?? 0}W-{p7?.losses ?? 0}L • {p7?.total_bets ?? 0} bets</div>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
          <div className="flex items-center gap-2 text-[10px] uppercase tracking-widest text-slate-500 font-black">
            <Activity size={14} /> Last 30 days
          </div>
          <div className={`mt-1 text-2xl font-black ${((p30?.roi || 0) >= 0) ? 'text-green-400' : 'text-red-400'}`}>{(p30?.roi ?? 0).toFixed(1)}% ROI</div>
          <div className="mt-2 text-xs text-slate-500">{p30?.wins ?? 0}W-{p30?.losses ?? 0}L • {p30?.total_bets ?? 0} bets</div>
        </div>
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-bold text-slate-200 uppercase tracking-wider">College Basketball Model Summary</h2>
          <div className="text-xs text-slate-500">last 7d / 30d</div>
        </div>

        {(!modelPerf || !modelPerf.windows) ? (
          <div className="mt-3 text-slate-500 text-sm">{loadingPerf ? 'Loading KPIs…' : 'No model KPI data yet.'}</div>
        ) : (
          <div className="mt-4 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
            {(() => {
              const w7 = modelPerf.windows?.['7d'];
              const w30 = modelPerf.windows?.['30d'];
              const kpis = [
                { label: '7d Win Rate', value: `${(w7?.win_rate ?? 0).toFixed(1)}%` },
                { label: '7d Return (ROI)', value: `${(w7?.roi_pct ?? 0).toFixed(1)}%` },
                { label: '30d Win Rate', value: `${(w30?.win_rate ?? 0).toFixed(1)}%` },
                { label: '30d Return (ROI)', value: `${(w30?.roi_pct ?? 0).toFixed(1)}%` },
                { label: '30d Expected Edge', value: `${(((w30?.avg_ev_per_unit ?? 0) * 100)).toFixed(1)}%` },
                { label: '30d Beat Close (pts)', value: (w30?.avg_clv_points ?? null) === null ? '—' : `${Number(w30.avg_clv_points).toFixed(2)}` },
                { label: '30d Beat Close %', value: (w30?.pos_clv_rate ?? null) === null ? '—' : `${Number(w30.pos_clv_rate).toFixed(1)}%` },
                { label: '30d Settled Picks', value: `${w30?.decided ?? 0}` },
              ];
              return kpis;
            })().map((k, i) => (
              <div key={i} className="bg-slate-950/30 border border-slate-800 rounded-xl p-4">
                <div className="text-[10px] uppercase tracking-widest text-slate-500 font-black">{k.label}</div>
                <div className="mt-1 text-xl font-black text-white">{k.value}</div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Full daily graded picks table */}
      <PerformanceReportNCAAM />
    </div>
  );
}
