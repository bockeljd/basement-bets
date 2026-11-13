import React, { useMemo, useState } from 'react';
import { ArrowUpDown, ChevronUp, ChevronDown, BarChart2, PlusCircle, Search, Filter } from 'lucide-react';
import {
  fmtTimeEt,
  fmtOdds,
  fmtSigned,
  getConfidenceMeta,
  lookupTopPickForGame,
  safeReasonText,
} from './todayHelpers';

const SortHeaderButton = ({ label, column, sortConfig, onSort, align = 'left' }) => {
  const isActive = sortConfig.key === column;
  const Icon = !isActive ? ArrowUpDown : sortConfig.direction === 'asc' ? ChevronUp : ChevronDown;
  return (
    <button
      type="button"
      onClick={() => onSort(column)}
      className={`inline-flex items-center gap-1 text-[11px] font-bold uppercase tracking-wider text-slate-400 hover:text-white cursor-pointer ${
        align === 'right' ? 'justify-end w-full' : ''
      }`}
    >
      <span>{label}</span>
      <Icon size={12} className={isActive ? 'text-indigo-400' : 'opacity-40'} aria-hidden="true" />
    </button>
  );
};

const TodayFullBoardTable = ({
  edges = [],
  leagueFilter = 'NCAAM',
  rowTopPicks = {},
  rowTopPicksByKey = {},
  onOpenDetails,
  onAddBet,
}) => {
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('all'); // all | picks | nobet | final
  const [sortConfig, setSortConfig] = useState({ key: 'edge', direction: 'desc' });

  const handleSort = (key) => {
    setSortConfig((prev) => ({
      key,
      direction: prev.key === key && prev.direction === 'desc' ? 'asc' : 'desc',
    }));
  };

  const rows = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    const list = (edges || [])
      .filter((g) => !leagueFilter || g.sport === leagueFilter)
      .map((game) => {
        const meta = lookupTopPickForGame(game, rowTopPicks, rowTopPicksByKey);
        const rec = meta?.rec || null;
        const isActionable = Boolean(meta?.isActionable && rec);
        const isFinal = Boolean(game.final || String(game.status || '').toUpperCase().includes('FINAL'));
        const evVal = rec?.ev !== null && rec?.ev !== undefined ? Number(rec.ev) : -999;
        const confVal = Number(rec?.confidence_0_100 ?? rec?.confidence ?? -1);
        return {
          game,
          meta,
          rec,
          isActionable,
          isFinal,
          evVal: Number.isFinite(evVal) ? evVal : -999,
          confVal: Number.isFinite(confVal) ? confVal : -1,
        };
      })
      .filter((row) => {
        if (q) {
          const hay = `${row.game.away_team || ''} ${row.game.home_team || ''} ${row.rec?.selection || ''}`.toLowerCase();
          if (!hay.includes(q)) return false;
        }
        if (statusFilter === 'picks') return row.isActionable;
        if (statusFilter === 'nobet') return !row.isActionable && !row.isFinal;
        if (statusFilter === 'final') return row.isFinal;
        return true;
      });

    list.sort((a, b) => {
      const dir = sortConfig.direction === 'asc' ? 1 : -1;
      if (sortConfig.key === 'time') {
        const ta = new Date(a.game.start_time || 0).getTime();
        const tb = new Date(b.game.start_time || 0).getTime();
        return (ta - tb) * dir;
      }
      if (sortConfig.key === 'team') {
        return String(a.game.away_team || '').localeCompare(String(b.game.away_team || '')) * dir;
      }
      if (sortConfig.key === 'conf') {
        return (a.confVal - b.confVal) * dir;
      }
      // Default sort by actionable first, then EV descending
      if (a.isActionable !== b.isActionable) return a.isActionable ? -1 : 1;
      if (a.evVal !== b.evVal) return (a.evVal - b.evVal) * dir;
      return new Date(a.game.start_time || 0).getTime() - new Date(b.game.start_time || 0).getTime();
    });

    return list;
  }, [edges, leagueFilter, rowTopPicks, rowTopPicksByKey, searchQuery, statusFilter, sortConfig]);

  return (
    <div className="space-y-4">
      {/* Search & Status Filter Toolbar */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 rounded-2xl border border-slate-800 bg-slate-900/75 p-3.5">
        <div className="relative flex-1 max-w-md">
          <label htmlFor="board-team-search" className="sr-only">
            Filter board by team or pick
          </label>
          <Search
            size={15}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none"
            aria-hidden="true"
          />
          <input
            id="board-team-search"
            type="search"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search team or pick (e.g., Duke, Kansas, Over)..."
            className="w-full pl-9 pr-3 py-2 rounded-xl bg-slate-950/90 border border-slate-700/80 text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/50"
          />
        </div>

        <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Filter games by pick status">
          {[
            { id: 'all', label: 'All Games' },
            { id: 'picks', label: 'Actionable Picks' },
            { id: 'nobet', label: 'No Bet' },
            { id: 'final', label: 'Final Scores' },
          ].map((opt) => {
            const active = statusFilter === opt.id;
            return (
              <button
                key={opt.id}
                type="button"
                aria-pressed={active}
                onClick={() => setStatusFilter(opt.id)}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold border transition cursor-pointer ${
                  active
                    ? 'bg-indigo-500/20 border-indigo-400/50 text-indigo-200'
                    : 'bg-slate-950/60 border-slate-800 text-slate-400 hover:text-slate-200 hover:border-slate-700'
                }`}
              >
                {opt.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Responsive Container-Query Table */}
      <div
        className="today-board-container rounded-2xl border border-slate-800 bg-slate-900/65 p-2 sm:p-0 overflow-x-auto focus:outline-none focus:ring-2 focus:ring-indigo-500/40"
        tabIndex={0}
        role="region"
        aria-label="Full daily odds and model board"
      >
        <table className="today-board-table text-left text-xs">
          <thead>
            <tr className="border-b border-slate-800 bg-slate-950/70">
              <th scope="col" className="py-3 pl-4 pr-2 w-20" aria-sort={sortConfig.key === 'time' ? (sortConfig.direction === 'asc' ? 'ascending' : 'descending') : 'none'}>
                <SortHeaderButton label="Tip (ET)" column="time" sortConfig={sortConfig} onSort={handleSort} />
              </th>
              <th scope="col" className="py-3 px-2" aria-sort={sortConfig.key === 'team' ? (sortConfig.direction === 'asc' ? 'ascending' : 'descending') : 'none'}>
                <SortHeaderButton label="Matchup" column="team" sortConfig={sortConfig} onSort={handleSort} />
              </th>
              <th scope="col" className="py-3 px-2">
                <span className="text-[11px] font-bold uppercase tracking-wider text-slate-400">Market Lines</span>
              </th>
              <th scope="col" className="py-3 px-2" aria-sort={sortConfig.key === 'edge' ? (sortConfig.direction === 'asc' ? 'ascending' : 'descending') : 'none'}>
                <SortHeaderButton label="Model Pick" column="edge" sortConfig={sortConfig} onSort={handleSort} />
              </th>
              <th scope="col" className="py-3 px-2 text-right" aria-sort={sortConfig.key === 'conf' ? (sortConfig.direction === 'asc' ? 'ascending' : 'descending') : 'none'}>
                <SortHeaderButton label="EV / Conf" column="conf" sortConfig={sortConfig} onSort={handleSort} align="right" />
              </th>
              <th scope="col" className="py-3 pl-2 pr-4 text-right w-36">
                <span className="text-[11px] font-bold uppercase tracking-wider text-slate-400">Action</span>
              </th>
            </tr>
          </thead>

          <tbody className="divide-y divide-slate-800/75">
            {rows.length === 0 ? (
              <tr>
                <td colSpan={6} className="py-12 text-center text-slate-400">
                  <div className="flex flex-col items-center gap-2">
                    <Filter size={26} className="opacity-30" aria-hidden="true" />
                    <p className="text-sm font-medium text-slate-300">No games match this filter.</p>
                    <p className="text-xs text-slate-500">Try clearing search text or switching the status pill above.</p>
                  </div>
                </td>
              </tr>
            ) : (
              rows.map(({ game, meta, rec, isActionable, isFinal }) => {
                const conf = getConfidenceMeta(rec);
                const cleanReason = safeReasonText(meta?.reason);
                const homeSpread = game.home_spread ?? game.spread_home;
                const totalLine = game.total_line ?? game.total;
                const mlHome = game.ml_home_odds ?? game.moneyline_home;
                const mlAway = game.ml_away_odds ?? game.moneyline_away;

                return (
                  <tr
                    key={game.id}
                    className="hover:bg-slate-800/40 transition-colors"
                  >
                    <td data-label="Tip (ET)" className="py-3 pl-4 pr-2 font-mono text-slate-300 whitespace-nowrap">
                      {isFinal ? (
                        <span className="inline-flex px-2 py-0.5 rounded bg-slate-800 text-slate-300 text-[10px] font-bold">
                          FINAL
                        </span>
                      ) : (
                        fmtTimeEt(game.start_time)
                      )}
                    </td>

                    <td data-primary="true" className="py-3 px-2 min-w-0">
                      <div className="flex flex-col gap-0.5 min-w-0">
                        <div className="flex items-center gap-2 min-w-0">
                          <span className="font-semibold text-slate-100 truncate">{game.away_team}</span>
                          {game.away_score != null && (
                            <span className="font-mono font-bold text-slate-200">{game.away_score}</span>
                          )}
                        </div>
                        <div className="flex items-center gap-2 min-w-0 text-slate-300">
                          <span className="text-[10px] uppercase tracking-wide text-slate-500">@</span>
                          <span className="font-semibold text-slate-200 truncate">{game.home_team}</span>
                          {game.home_score != null && (
                            <span className="font-mono font-bold text-white">{game.home_score}</span>
                          )}
                        </div>
                      </div>
                    </td>

                    <td data-label="Market" className="py-3 px-2 font-mono text-slate-300 whitespace-nowrap">
                      <div className="flex flex-col gap-0.5 text-[11px]">
                        <span>
                          Spread:{' '}
                          <strong className="text-slate-100">
                            {homeSpread !== null && homeSpread !== undefined ? fmtSigned(homeSpread, 1) : '—'}
                          </strong>{' '}
                          <span className="text-slate-500">·</span> Total{' '}
                          <strong className="text-slate-100">
                            {totalLine !== null && totalLine !== undefined ? Number(totalLine).toFixed(1) : '—'}
                          </strong>
                        </span>
                        <span className="text-slate-400">
                          Moneyline: {fmtOdds(mlAway)} / {fmtOdds(mlHome)}
                        </span>
                      </div>
                    </td>

                    <td data-label="Model Pick" className="py-3 px-2 min-w-0 max-w-[240px]">
                      {isActionable && rec ? (
                        <div className="flex flex-col gap-0.5">
                          <div className="flex items-center gap-1.5 flex-wrap">
                            <span className="px-1.5 py-0.5 rounded bg-emerald-500/15 border border-emerald-500/35 text-emerald-300 text-[10px] font-bold uppercase">
                              {rec.bet_type || rec.market_type || 'BET'}
                            </span>
                            <span className="font-bold text-white truncate">
                              {rec.selection || rec.pick}
                            </span>
                          </div>
                          <span className="text-[11px] font-mono text-slate-400">
                            {fmtOdds(rec.price)} · {rec.book || 'Consensus'}
                          </span>
                        </div>
                      ) : (
                        <div className="flex flex-col gap-0.5">
                          <span className="inline-flex w-fit px-2 py-0.5 rounded bg-slate-800/90 border border-slate-700 text-slate-400 text-[10px] font-bold uppercase">
                            NO BET
                          </span>
                          {cleanReason && (
                            <span className="text-[11px] text-slate-400 line-clamp-2">{cleanReason}</span>
                          )}
                        </div>
                      )}
                    </td>

                    <td data-label="EV / Conf" className="py-3 px-2 text-right whitespace-nowrap">
                      {isActionable && rec ? (
                        <div className="flex flex-col items-end gap-1">
                          <span className="font-mono font-bold text-emerald-300">
                            {rec.ev !== null && rec.ev !== undefined ? `+${(Number(rec.ev) * 100).toFixed(1)}%` : '—'}
                          </span>
                          <span className={`px-2 py-0.5 rounded-full border text-[10px] font-bold ${conf.badgeCls}`}>
                            {conf.tier}
                          </span>
                        </div>
                      ) : (
                        <span className="text-slate-600">—</span>
                      )}
                    </td>

                    <td data-label="Action" className="py-3 pl-2 pr-4 text-right whitespace-nowrap">
                      <div className="inline-flex items-center justify-end gap-1.5">
                        <button
                          type="button"
                          onClick={() => onOpenDetails(game)}
                          className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-xs font-semibold text-slate-100 transition cursor-pointer"
                        >
                          <BarChart2 size={12} aria-hidden="true" />
                          <span>Details</span>
                        </button>
                        {isActionable && rec && (
                          <button
                            type="button"
                            onClick={() =>
                              onAddBet?.({
                                sport: game.sport || leagueFilter,
                                game: `${game.away_team} @ ${game.home_team}`,
                                market: rec.bet_type || rec.market_type,
                                pick: rec.selection || rec.pick,
                                line: rec.market_line,
                                odds: rec.price,
                                book: rec.book || 'Consensus',
                              })
                            }
                            aria-label={`Add bet ${rec.selection || rec.pick}`}
                            title="Add bet to tracker"
                            className="inline-flex items-center justify-center p-1.5 rounded-lg bg-emerald-600/20 hover:bg-emerald-600/35 border border-emerald-500/40 text-emerald-300 transition cursor-pointer"
                          >
                            <PlusCircle size={14} aria-hidden="true" />
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default TodayFullBoardTable;
