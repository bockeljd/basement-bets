/**
 * Shared utility functions for Model Performance analytics across the frontend.
 */

/**
 * Normalizes outcome string to standard uppercase WON, LOST, PUSH or null.
 */
export const normalizeOutcome = (value) => {
  if (!value) return null;
  const v = String(value).trim().toUpperCase();
  if (v === 'WON' || v === 'WIN') return 'WON';
  if (v === 'LOST' || v === 'LOSS') return 'LOST';
  if (v === 'PUSH') return 'PUSH';
  if (v === 'VOID') return 'VOID';
  return null;
};

export const isGradedOutcome = (value) => {
  const norm = normalizeOutcome(value);
  return norm === 'WON' || norm === 'LOST' || norm === 'PUSH';
};

export const isWinOutcome = (value) => normalizeOutcome(value) === 'WON';
export const isLossOutcome = (value) => normalizeOutcome(value) === 'LOST';

/**
 * Converts a timestamp or date string to a YYYY-MM-DD string in ET.
 */
export const toEtDay = (value) => {
  if (!value) return null;
  try {
    const d = new Date(value);
    return d.toLocaleDateString('en-CA', { timeZone: 'America/New_York' });
  } catch (e) {
    return null;
  }
};

/**
 * Priority logic for determining which day a pick belongs to for performance charts.
 */
export const getPerformanceDay = (row) => {
  if (!row) return null;
  // 1. Explicit day from canonical backend
  if (row.day_et) return row.day_et;
  // 2. Scheduled start time
  if (row.start_time) return toEtDay(row.start_time);
  // 3. Analysis time
  if (row.analyzed_at) return toEtDay(row.analyzed_at);
  // 4. Creation time
  if (row.created_at) return toEtDay(row.created_at);
  return null;
};

/**
 * Calculates payout multiplier from American odds.
 * e.g. -110 -> 0.909, +120 -> 1.2
 */
export const payoutPerUnitFromAmericanOdds = (price) => {
  const p = parseFloat(price);
  if (isNaN(p)) return 0.90909; // fallback to -110
  if (p === 0) return 1.0;
  if (p > 0) return p / 100;
  return 100 / Math.abs(p);
};

/**
 * Calculates ROI (units won/lost) for a given outcome and price.
 */
export const roiPerUnit = (outcome, price) => {
  const norm = normalizeOutcome(outcome);
  if (norm === 'WON') return payoutPerUnitFromAmericanOdds(price);
  if (norm === 'LOST') return -1.0;
  return 0.0;
};

/**
 * Normalizes confidence to a 0-100 scale.
 * Supports row.confidence_0_100 (0-100) or historical 0-1 range.
 */
export const getNumericConfidence = (row) => {
  if (!row) return 0;
  
  // 1. Explicit clean field
  let c = row.confidence_0_100;
  if (c != null) {
     const val = parseFloat(c);
     if (val <= 1.0 && val > 0) return val * 100; // was 0.85
     return val;
  }
  
  // 2. Generic confidence field
  if (row.confidence != null) {
      const val = parseFloat(row.confidence);
      if (val <= 1.0 && val > 0) return val * 100;
      return val;
  }

  // 3. Last resort: infer from EV if it's a recommendation
  if (row.ev_per_unit != null) {
      const ev = parseFloat(row.ev_per_unit);
      if (ev >= 0.08) return 85;
      if (ev >= 0.05) return 65;
      if (ev >= 0.02) return 50;
  }
  
  return 0;
};

/**
 * Buckets numeric confidence into display categories.
 */
export const getConfidenceBucket = (row) => {
  // Legacy support for explicit string fields
  if (row.confidence_label) return row.confidence_label;

  const n = getNumericConfidence(row);
  if (n >= 80) return 'High';
  if (n >= 50) return 'Medium';
  return 'Low';
};


export const getRawOutcome = (row) => row?.graded_result || row?.outcome || row?.result;

export const getEffectivePrice = (row) => {
  const p = row?.bet_price ?? row?.price ?? row?.odds;
  if (p === null || p === undefined || p === '') return null;
  const n = Number(p);
  return Number.isFinite(n) && n !== 0 ? n : null;
};

export const normalizeMarketType = (rowOrType) => {
  if (rowOrType && typeof rowOrType === 'object') {
    const isParlay =
      Boolean(rowOrType?.is_parlay) ||
      String(rowOrType?.bet_type || '').toLowerCase().includes('parlay') ||
      String(rowOrType?.market_type || '').toLowerCase().includes('parlay');
    if (isParlay) return 'PARLAY';
    rowOrType = rowOrType?.market_type || rowOrType?.market || rowOrType?.bet_type || '';
  }
  const raw = String(rowOrType || '').trim().toUpperCase();
  if (!raw || raw === 'AUTO' || raw === 'NONE' || raw === 'UNKNOWN') return 'OTHER';
  if (raw === 'H2H' || raw === 'ML' || raw === 'MONEYLINE' || raw === 'MONEY LINE' || raw.includes('MONEYLINE')) {
    return 'MONEYLINE';
  }
  if (raw.includes('SPREAD')) return 'SPREAD';
  if (raw.includes('TOTAL') || raw === 'OVER' || raw === 'UNDER' || raw === 'OU' || raw === 'O/U') {
    return 'TOTAL';
  }
  if (raw.includes('PARLAY')) return 'PARLAY';
  return raw;
};

export const formatMarketLabel = (rowOrType) => {
  const norm = normalizeMarketType(rowOrType);
  if (norm === 'SPREAD') return 'Spread';
  if (norm === 'TOTAL') return 'Over / Under';
  if (norm === 'MONEYLINE') return 'Moneyline';
  if (norm === 'PARLAY') return 'Parlay';
  if (norm === 'OTHER') return 'Other';
  return norm.charAt(0) + norm.slice(1).toLowerCase();
};

export const formatMatchup = (row) => {
  const direct = String(row?.matchup || row?.game || '').trim();
  if (direct && direct !== '—' && direct !== '-') return direct;
  const away = String(row?.away_team || '').trim();
  const home = String(row?.home_team || '').trim();
  if (away && home) return `${away} @ ${home}`;
  return away || home || '—';
};

export const formatPickLabel = (row) => {
  let recSide = '';
  try {
    if (row?.outputs_json) {
      const parsed = typeof row.outputs_json === 'string' ? JSON.parse(row.outputs_json) : row.outputs_json;
      recSide = parsed?.recommendations?.[0]?.side || '';
    }
  } catch (e) {
    recSide = '';
  }
  const candidates = [row?.selection, row?.bet_on, recSide, row?.pick];
  for (const c of candidates) {
    const s = String(c || '').trim();
    if (!s) continue;
    const upper = s.toUpperCase();
    if (upper === 'NONE' || upper === 'NULL' || s === '-' || s === '—') continue;
    if (upper === 'HOME' && row?.home_team) return String(row.home_team).trim();
    if (upper === 'AWAY' && row?.away_team) return String(row.away_team).trim();
    if (upper === 'OVER') return 'Over';
    if (upper === 'UNDER') return 'Under';
    return s;
  }
  return '—';
};

export const formatAmericanOdds = (price) => {
  const n = Number(price);
  if (!Number.isFinite(n) || n === 0) return '';
  return n > 0 ? `+${Math.round(n)}` : `${Math.round(n)}`;
};

export const formatLineAndOdds = (row) => {
  const rawLine = row?.bet_line ?? row?.line;
  const mt = normalizeMarketType(row);
  const priceStr = formatAmericanOdds(getEffectivePrice(row));

  let lineStr = '';
  if (rawLine !== null && rawLine !== undefined && rawLine !== '') {
    const n = Number(rawLine);
    if (Number.isFinite(n)) {
      if (mt === 'SPREAD') lineStr = n > 0 ? `+${n}` : `${n}`;
      else if (mt === 'TOTAL') lineStr = `${n}`;
      else lineStr = `${n}`;
    } else {
      lineStr = String(rawLine).trim();
    }
  }

  if (lineStr && priceStr) return `${lineStr} (${priceStr})`;
  if (lineStr) return lineStr;
  if (priceStr) return priceStr;
  return '—';
};

export const getNumericEdge = (row) => {
  const raw = row?.ev_per_unit ?? row?.ev ?? row?.edge ?? row?.edge_points;
  if (raw === null || raw === undefined || raw === '') return null;
  let n = Number(raw);
  if (!Number.isFinite(n)) return null;
  let safety = 0;
  while (Math.abs(n) > 0.5 && safety < 3) {
    n /= 100;
    safety += 1;
  }
  return n;
};

export const computeRecordStats = (rows) => {
  const list = Array.isArray(rows) ? rows : [];
  let wins = 0;
  let losses = 0;
  let pushes = 0;
  let roiSum = 0;

  for (const h of list) {
    const out = getRawOutcome(h);
    const norm = normalizeOutcome(out);
    if (norm === 'WON') wins += 1;
    else if (norm === 'LOST') losses += 1;
    else if (norm === 'PUSH') pushes += 1;
    roiSum += roiPerUnit(out, getEffectivePrice(h));
  }

  const decided = wins + losses;
  const winRate = decided > 0 ? (wins / decided) * 100 : 0;
  const roiPct = list.length > 0 ? (roiSum / list.length) * 100 : 0;

  return {
    total: list.length,
    wins,
    losses,
    pushes,
    decided,
    winRate,
    roiPct,
  };
};

export const selectTopPicksPerDay = (rows, topN = 6) => {
  const list = Array.isArray(rows) ? rows : [];
  const groups = {};
  for (const h of list) {
    const day = getPerformanceDay(h) || 'unknown';
    if (!groups[day]) groups[day] = [];
    groups[day].push(h);
  }
  const out = [];
  const sortedDays = Object.keys(groups).sort((a, b) => b.localeCompare(a));
  for (const day of sortedDays) {
    const sorted = groups[day].slice().sort((a, b) => {
      const evA = getNumericEdge(a) ?? -999;
      const evB = getNumericEdge(b) ?? -999;
      if (evB !== evA) return evB - evA;
      const rkA = Number(a?.rank) || 999;
      const rkB = Number(b?.rank) || 999;
      return rkA - rkB;
    });
    out.push(...sorted.slice(0, topN));
  }
  return out;
};
