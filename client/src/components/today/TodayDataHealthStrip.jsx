import React, { useState } from 'react';
import { CheckCircle2, AlertTriangle, XCircle, Upload, Clock } from 'lucide-react';

const FEED_DEFS = [
  { key: 'torvik', label: 'BartTorvik' },
  { key: 'kenpom', label: 'KenPom' },
  { key: 'haslametrics', label: 'Haslametrics' },
  { key: 'odds', label: 'Sportsbook Odds' },
  { key: 'action_splits', label: 'Public Betting Splits' },
];

const FEED_LABEL_MAP = {
  torvik: 'BartTorvik',
  kenpom: 'KenPom',
  haslametrics: 'Haslametrics',
  odds: 'Sportsbook Odds',
  action_splits: 'Public Betting Splits',
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

const getPillMeta = (row, feedKey) => {
  if (!row) {
    return {
      tone: 'stale',
      statusText: feedKey === 'kenpom' ? 'Off (Not Set Up)' : 'Not Loaded',
      Icon: XCircle,
      cls: 'bg-slate-900/80 border-slate-700/80 text-slate-400',
    };
  }
  const st = String(row.status || '').toLowerCase();
  if (st === 'ok') {
    return {
      tone: 'ok',
      statusText: formatAge(row.updated_at),
      Icon: CheckCircle2,
      cls: 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300',
    };
  }
  if (st === 'alert' || st === 'stale') {
    return {
      tone: 'alert',
      statusText: feedKey === 'kenpom' ? 'Off (Needs 2026-27)' : st === 'alert' ? 'Watch' : 'Needs Update',
      Icon: AlertTriangle,
      cls: 'bg-amber-500/10 border-amber-500/35 text-amber-300',
    };
  }
  return {
    tone: 'error',
    statusText: 'Issue',
    Icon: XCircle,
    cls: 'bg-rose-500/10 border-rose-500/35 text-rose-300',
  };
};

const TodayDataHealthStrip = ({ dataHealth = [], edges = [], leagueFilter = 'NCAAM', onOpenKenpomUpload }) => {
  const [selectedSource, setSelectedSource] = useState(null);

  const bySource = {};
  (dataHealth || []).forEach((item) => {
    if (item?.source) bySource[item.source] = item;
  });

  // Compute live Today coverage directly from loaded board rows
  const leagueGames = (edges || []).filter((e) => !leagueFilter || e.sport === leagueFilter);
  const withOdds = leagueGames.filter(
    (e) =>
      e.home_spread !== null ||
      e.total_line !== null ||
      e.ml_home_odds !== null ||
      e.moneyline_home !== null
  ).length;
  const boardItem = bySource[`board:${leagueFilter}`] || bySource['board:NCAAM'];
  const kenpomRow = bySource.kenpom;
  const kenpomOk = String(kenpomRow?.status || '').toLowerCase() === 'ok';

  const activeDetail = selectedSource ? bySource[selectedSource] : null;
  const activeNotes = selectedSource ? formatFeedNotes(selectedSource, activeDetail) : '';
  const activeCount = activeDetail?.last_row_count ?? activeDetail?.row_count;

  return (
    <section
      aria-label="Live data sources"
      className="rounded-2xl border border-slate-800/90 bg-slate-900/75 px-3.5 py-2.5 space-y-2"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[11px] font-bold uppercase tracking-wider text-slate-400 mr-1">
            Data Sources
          </span>

          {FEED_DEFS.map((feed) => {
            const row = bySource[feed.key];
            const meta = getPillMeta(row, feed.key);
            const Icon = meta.Icon;
            const isSelected = selectedSource === feed.key;
            return (
              <button
                key={feed.key}
                type="button"
                aria-pressed={isSelected}
                onClick={() => setSelectedSource(isSelected ? null : feed.key)}
                className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs font-medium transition cursor-pointer ${meta.cls} ${
                  isSelected ? 'ring-1 ring-white/40' : 'hover:brightness-110'
                }`}
              >
                <Icon size={12} aria-hidden="true" />
                <span>{feed.label}</span>
                <span className="opacity-75 text-[11px]">· {meta.statusText}</span>
              </button>
            );
          })}

          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border border-indigo-500/30 bg-indigo-500/10 text-indigo-200 text-xs font-medium">
            <Clock size={12} aria-hidden="true" />
            <span>
              {leagueFilter} Slate: {withOdds}/{leagueGames.length} games have odds
            </span>
          </span>
        </div>

        <button
          type="button"
          onClick={onOpenKenpomUpload}
          className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-lg border text-xs font-semibold transition cursor-pointer shrink-0 ${
            kenpomOk
              ? 'bg-slate-800 hover:bg-slate-700 border-slate-700 text-slate-200'
              : 'bg-amber-500/15 hover:bg-amber-500/25 border-amber-500/40 text-amber-200'
          }`}
        >
          <Upload size={12} aria-hidden="true" />
          <span>{kenpomOk ? 'Refresh KenPom' : 'Enable KenPom'}</span>
        </button>
      </div>

      {selectedSource && (
        <div className="rounded-xl border border-slate-800 bg-slate-950/80 px-3 py-2 text-xs text-slate-300 flex flex-wrap items-center justify-between gap-2">
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
          {boardItem?.notes && selectedSource === 'odds' && (
            <span className="text-[11px] text-slate-400">Live board pricing connected</span>
          )}
          <button
            type="button"
            onClick={() => setSelectedSource(null)}
            className="text-slate-400 hover:text-white underline text-[11px] cursor-pointer"
          >
            Dismiss
          </button>
        </div>
      )}
    </section>
  );
};

export default TodayDataHealthStrip;
