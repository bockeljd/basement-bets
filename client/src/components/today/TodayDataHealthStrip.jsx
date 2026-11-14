import React, { useState } from 'react';
import { CheckCircle2, AlertTriangle, XCircle, Upload, ClipboardPaste, ChevronDown, ChevronUp } from 'lucide-react';

const FEED_DEFS = [
  { key: 'torvik', label: 'BartTorvik' },
  { key: 'haslametrics', label: 'Haslametrics' },
  { key: 'kenpom', label: 'KenPom' },
  { key: 'odds', label: 'Odds' },
  { key: 'action_splits', label: 'Splits' },
];

const FEED_LABEL_MAP = {
  torvik: 'BartTorvik',
  kenpom: 'KenPom',
  haslametrics: 'Haslametrics',
  odds: 'Sportsbook Odds',
  action_splits: 'Public Betting Money',
  results: 'Game Results',
};

const formatFeedNotes = (source, item) => {
  if (!item) return 'Not imported yet';
  if (item.human_notes) return item.human_notes;
  const raw = String(item.notes || '').trim();
  if (!raw) return '';
  if (source === 'kenpom' && raw.startsWith('{')) {
    try {
      const parsed = JSON.parse(raw);
      const asof = parsed.asof_date || '';
      const teams = parsed.team ? ` — ${parsed.team} teams loaded` : '';
      if (asof) {
        const prior = asof < '2026-11-01' ? ' (prior season — needs 2026-27 update)' : '';
        return `Latest ratings from ${asof}${prior}${teams}`;
      }
    } catch {
      return raw;
    }
  }
  return raw;
};

const formatAge = (iso) => {
  if (!iso) return 'Unknown age';
  try {
    const ms = Date.now() - new Date(iso).getTime();
    if (!Number.isFinite(ms) || ms < 0) return 'Just updated';
    const mins = Math.round(ms / 60000);
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.round(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    return `${Math.round(hrs / 24)}d ago`;
  } catch {
    return 'Unknown age';
  }
};

const getFeedState = (row, feedKey) => {
  if (!row) {
    return {
      ok: false,
      statusText: feedKey === 'kenpom' ? 'Off' : 'Missing',
      dotCls: 'bg-slate-500',
      textCls: 'text-slate-400',
      Icon: XCircle,
    };
  }
  const st = String(row.status || '').toLowerCase();
  if (st === 'ok') {
    return {
      ok: true,
      statusText: formatAge(row.updated_at),
      dotCls: 'bg-emerald-400',
      textCls: 'text-emerald-300',
      Icon: CheckCircle2,
    };
  }
  if (st === 'alert' || st === 'stale') {
    return {
      ok: false,
      statusText: feedKey === 'kenpom' ? 'Needs Update' : st === 'alert' ? 'Watch' : 'Stale',
      dotCls: 'bg-amber-400',
      textCls: 'text-amber-300',
      Icon: AlertTriangle,
    };
  }
  return {
    ok: false,
    statusText: 'Issue',
    dotCls: 'bg-rose-400',
    textCls: 'text-rose-300',
    Icon: XCircle,
  };
};

const TodayDataHealthStrip = ({ dataHealth = [], edges = [], leagueFilter = 'NCAAM', onOpenKenpomUpload, onPasteKenpomClipboard }) => {
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [selectedSource, setSelectedSource] = useState(null);

  const bySource = {};
  (dataHealth || []).forEach((item) => {
    if (item?.source) bySource[item.source] = item;
  });

  const leagueGames = (edges || []).filter((e) => !leagueFilter || e.sport === leagueFilter);
  const withOdds = leagueGames.filter(
    (e) =>
      e.home_spread !== null ||
      e.total_line !== null ||
      e.ml_home_odds !== null ||
      e.moneyline_home !== null
  ).length;

  const activeFeedCount = FEED_DEFS.filter((f) => String(bySource[f.key]?.status || '').toLowerCase() === 'ok').length;
  const feedsHealthy = activeFeedCount >= 4;

  const kenpomRow = bySource.kenpom;
  const kenpomOk = String(kenpomRow?.status || '').toLowerCase() === 'ok';

  const activeDetail = selectedSource ? bySource[selectedSource] : null;
  const activeNotes = selectedSource ? formatFeedNotes(selectedSource, activeDetail) : '';
  const activeCount = activeDetail?.last_row_count ?? activeDetail?.row_count;

  const handleTogglePill = (key) => {
    if (selectedSource === key && detailsOpen) {
      setSelectedSource(null);
      setDetailsOpen(false);
    } else {
      setSelectedSource(key);
      setDetailsOpen(true);
    }
  };

  return (
    <div className="rounded-xl border border-slate-800/80 bg-slate-900/60 px-3 py-2 space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
        <div className="flex flex-wrap items-center gap-2 min-w-0">
          <span
            className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border font-semibold ${
              feedsHealthy
                ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300'
                : 'bg-amber-500/10 border-amber-500/35 text-amber-300'
            }`}
          >
            <span className={`w-1.5 h-1.5 rounded-full ${feedsHealthy ? 'bg-emerald-400' : 'bg-amber-400'}`} aria-hidden="true" />
            <span>Data Sources: {activeFeedCount}/{FEED_DEFS.length} Ready</span>
          </span>

          <span className="text-slate-400 text-[11px] px-1">
            Odds loaded on <strong className="font-mono text-slate-200">{withOdds}/{leagueGames.length}</strong> games
          </span>

          {leagueFilter === 'NCAAM' && !kenpomOk && (
            <span className="px-2 py-0.5 rounded-full bg-amber-500/10 border border-amber-500/30 text-amber-200 text-[11px] font-semibold">
              KenPom Off
            </span>
          )}
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <button
            type="button"
            aria-expanded={detailsOpen}
            onClick={() => {
              setDetailsOpen((v) => !v);
              if (detailsOpen) setSelectedSource(null);
            }}
            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg border border-slate-800 bg-slate-950/70 hover:bg-slate-800 text-[11px] font-semibold text-slate-300 hover:text-white cursor-pointer"
          >
            <span>View Sources</span>
            {detailsOpen ? <ChevronUp size={12} aria-hidden="true" /> : <ChevronDown size={12} aria-hidden="true" />}
          </button>

          {leagueFilter === 'NCAAM' && (
            <>
              <button
                type="button"
                onClick={onPasteKenpomClipboard}
                title="After copying kenpom.com (Cmd+A then Cmd+C), click to import instantly"
                className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg border border-emerald-500/40 bg-emerald-500/15 hover:bg-emerald-500/25 text-emerald-200 text-[11px] font-semibold transition cursor-pointer"
              >
                <ClipboardPaste size={11} aria-hidden="true" />
                <span>Paste KenPom</span>
              </button>
              <button
                type="button"
                onClick={onOpenKenpomUpload}
                className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg border text-[11px] font-semibold transition cursor-pointer ${
                  kenpomOk
                    ? 'bg-slate-800 hover:bg-slate-700 border-slate-700 text-slate-200'
                    : 'bg-amber-500/15 hover:bg-amber-500/25 border-amber-500/40 text-amber-200'
                }`}
              >
                <Upload size={11} aria-hidden="true" />
                <span>{kenpomOk ? 'Update KenPom' : 'Enable KenPom'}</span>
              </button>
            </>
          )}
        </div>
      </div>

      {detailsOpen && (
        <div className="rounded-lg border border-slate-800 bg-slate-950/80 p-3 text-xs space-y-2.5">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-2">
            {FEED_DEFS.map((feed) => {
              const row = bySource[feed.key];
              const state = getFeedState(row, feed.key);
              const Icon = state.Icon;
              const isSelected = selectedSource === feed.key;
              return (
                <button
                  key={feed.key}
                  type="button"
                  onClick={() => setSelectedSource(isSelected ? null : feed.key)}
                  className={`text-left rounded-lg border px-2.5 py-2 transition cursor-pointer ${
                    isSelected
                      ? 'border-indigo-400/50 bg-slate-900'
                      : 'border-slate-800/90 bg-slate-900/50 hover:border-slate-700'
                  }`}
                >
                  <div className="flex items-center justify-between gap-1">
                    <span className="font-semibold text-slate-100">{FEED_LABEL_MAP[feed.key] || feed.label}</span>
                    <Icon size={12} className={state.textCls} aria-hidden="true" />
                  </div>
                  <div className={`mt-0.5 text-[11px] ${state.textCls}`}>{state.statusText}</div>
                </button>
              );
            })}
          </div>

          {selectedSource && (
            <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-slate-800/80 text-slate-300">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span className="font-bold text-white">{FEED_LABEL_MAP[selectedSource] || selectedSource}:</span>
                <span>
                  <strong className="text-slate-100">
                    {String(activeDetail?.status || '').toLowerCase() === 'ok' ? 'Active' : 'Needs Update'}
                  </strong>
                  {activeCount != null ? ` • ${activeCount} records` : ''}
                  {activeDetail?.updated_at ? ` • Checked ${formatAge(activeDetail.updated_at)}` : ''}
                  {activeNotes ? ` • ${activeNotes}` : ''}
                </span>
                {selectedSource === 'kenpom' && !kenpomOk && (
                  <button
                    type="button"
                    onClick={onOpenKenpomUpload}
                    className="text-amber-300 hover:text-amber-200 font-semibold underline cursor-pointer ml-1"
                  >
                    Set up KenPom now →
                  </button>
                )}
              </div>
              <button
                type="button"
                onClick={() => setSelectedSource(null)}
                className="text-slate-400 hover:text-white underline text-[11px] cursor-pointer"
              >
                Clear
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default TodayDataHealthStrip;
