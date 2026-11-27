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
  // Mirror src/utils/model_performance.py payout_per_unit(): missing/zero/non-numeric price => -110
  const p = parseInt(price, 10);
  if (!Number.isFinite(p) || p === 0) return 100 / 110;
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

  const normalizeValue = (raw) => {
    const val = parseFloat(raw);
    if (!Number.isFinite(val) || val <= 0) return 0;
    const scaled = val <= 1.0 ? val * 100 : val;
    return Math.min(100, Math.max(0, scaled));
  };

  if (row.confidence_0_100 != null) return normalizeValue(row.confidence_0_100);
  if (row.confidence != null) return normalizeValue(row.confidence);

  // Last resort: infer from EV if it's a recommendation
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
  const rawLbl = String(row?.confidence_label || '').trim().toUpperCase();
  if (rawLbl === 'HIGH') return 'High';
  if (rawLbl === 'MEDIUM' || rawLbl === 'MED') return 'Medium';
  if (rawLbl === 'LOW') return 'Low';

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
  if (raw.includes('1H')) {
    if (raw.includes('SPREAD')) return 'SPREAD_1H';
    if (raw.includes('TOTAL') || raw.includes('OVER') || raw.includes('UNDER')) return 'TOTAL_1H';
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
  if (norm === 'SPREAD_1H') return '1H Spread';
  if (norm === 'TOTAL') return 'Over / Under';
  if (norm === 'TOTAL_1H') return '1H Over / Under';
  if (norm === 'MONEYLINE') return 'Moneyline';
  if (norm === 'PARLAY') return 'Parlay';
  if (norm === 'NRFI') return 'NRFI';
  if (norm === 'YRFI') return 'YRFI';
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
      if (mt === 'SPREAD' || mt === 'SPREAD_1H') lineStr = n > 0 ? `+${n}` : `${n}`;
      else if (mt === 'TOTAL' || mt === 'TOTAL_1H') lineStr = `${n}`;
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
  if (typeof raw === 'string') {
    const trimmed = raw.trim();
    if (trimmed.endsWith('%')) {
      const pct = parseFloat(trimmed.slice(0, -1).trim());
      return Number.isFinite(pct) ? pct / 100 : null;
    }
  }
  let n = Number(raw);
  if (!Number.isFinite(n)) return null;
  let safety = 0;
  while (Math.abs(n) > 0.5 && safety < 3) {
    n /= 100;
    safety += 1;
  }
  return n;
};

const SPORT_ALIAS_MAP = {
  BASKETBALL_NCAAB: 'NCAAM',
  NCAAB: 'NCAAM',
  NCAAM: 'NCAAM',
  CBB: 'NCAAM',
  BASEBALL_MLB: 'MLB',
  MLB: 'MLB',
  AMERICANFOOTBALL_NFL: 'NFL',
  NFL: 'NFL',
  AMERICANFOOTBALL_NCAAF: 'NCAAF',
  NCAAF: 'NCAAF',
  CFB: 'NCAAF',
  SOCCER_EPL: 'EPL',
  EPL: 'EPL',
  'ENG.1': 'EPL',
};

export const normalizeSport = (rowOrSport) => {
  const isObj = rowOrSport && typeof rowOrSport === 'object';
  const rawSport = isObj
    ? (rowOrSport?.sport || rowOrSport?.league || '')
    : (rowOrSport || '');
  const upper = String(rawSport).trim().toUpperCase();
  if (SPORT_ALIAS_MAP[upper]) return SPORT_ALIAS_MAP[upper];
  if (upper && upper !== 'NONE' && upper !== 'NULL' && upper !== 'UNKNOWN') {
    return upper;
  }

  const eid = isObj ? String(rowOrSport?.event_id || '').trim().toLowerCase() : '';
  for (const slug of ['mlb', 'nfl', 'ncaaf', 'epl']) {
    if (eid.startsWith(`${slug}:`) || eid.startsWith(`action:${slug}:`)) {
      return slug.toUpperCase();
    }
  }
  return 'NCAAM';
};

export const getRowSeason = (row) => {
  const direct = String(row?.season || '').trim();
  if (direct) return direct;

  const day = getPerformanceDay(row);
  if (!day || day.length < 7) return null;
  const year = Number(day.slice(0, 4));
  const month = Number(day.slice(5, 7));
  if (!Number.isFinite(year) || !Number.isFinite(month)) return null;

  const sport = normalizeSport(row);
  if (sport === 'NCAAM') {
    const endYear = month >= 7 ? year + 1 : year;
    return `${endYear - 1}-${String(endYear).slice(-2)}`;
  }
  return String(year);
};

export const computeRowProfitUnits = (row) => {
  if (!row) return 0;
  return roiPerUnit(getRawOutcome(row), getEffectivePrice(row));
};

export const computeRecordStats = (rows) => {
  const list = Array.isArray(rows) ? rows : [];
  let wins = 0;
  let losses = 0;
  let pushes = 0;
  let voids = 0;
  let pending = 0;
  let roiSum = 0;

  for (const h of list) {
    const out = getRawOutcome(h);
    const norm = normalizeOutcome(out);
    if (norm === 'WON') wins += 1;
    else if (norm === 'LOST') losses += 1;
    else if (norm === 'PUSH') pushes += 1;
    else if (norm === 'VOID') voids += 1;
    else pending += 1;
    roiSum += roiPerUnit(out, getEffectivePrice(h));
  }

  const decided = wins + losses;
  const settled = decided + pushes;
  const winRate = decided > 0 ? (wins / decided) * 100 : 0;
  const roiPct = settled > 0 ? (roiSum / settled) * 100 : 0;

  return {
    total: list.length,
    settled,
    wins,
    losses,
    pushes,
    voids,
    pending,
    decided,
    winRate,
    profitUnits: roiSum,
    roiPct,
  };
};

export const getConfidenceTierWeightUnits = (row) => {
  const explicitUnits = parseFloat(row?.suggested_units ?? row?.recommended_units);
  if (Number.isFinite(explicitUnits) && explicitUnits > 0) {
    return Math.max(0.25, Math.min(2.0, explicitUnits));
  }
  const rawKelly = parseFloat(row?.kelly ?? row?.kelly_fraction);
  if (Number.isFinite(rawKelly) && rawKelly > 0) {
    const kPct = rawKelly <= 1 ? rawKelly * 100 : rawKelly;
    return Math.max(0.5, Math.min(2.0, Math.round(kPct * 4) / 4));
  }
  const tier = getConfidenceBucket(row);
  if (tier === 'High') return 1.5;
  if (tier === 'Medium') return 1.0;
  return 0.5;
};

export const getEventDedupeKey = (row) => {
  if (!row) return null;
  const eid = String(row.event_id || '').trim();
  if (eid) return eid;
  const day = getPerformanceDay(row) || '';
  const matchup = formatMatchup(row).trim().toLowerCase();
  return matchup && matchup !== '—' ? `${day}|${matchup}` : null;
};

const isLockedRecommendedSlateRow = (row) => {
  if (!row) return false;
  const rk = Number(row.rank);
  const hasRank = Number.isFinite(rk) && rk > 0;
  if (row.canonical_source === 'daily_top_picks') {
    const day = getPerformanceDay(row);
    // Pre-2026-11-16 daily_top_picks dates keep their historical tip-off EV rank locked.
    return Boolean(day && day < '2026-11-16' && hasRank);
  }
  if (row.source_type === 'canonical_slate') return true;
  return hasRank && row.top6_eligible === undefined && !row.movement_tags;
};

export const hasTop6RiskFlag = (row) => {
  if (!row) return false;
  if (row.top6_eligible === false) return true;
  const rawTags = row.movement_tags || row.sanity_reasons;
  const tags = Array.isArray(rawTags)
    ? rawTags
    : typeof rawTags === 'string'
      ? rawTags.split(',')
      : [];
  return tags.some((t) => {
    const low = String(t || '').trim().toLowerCase();
    return low === 'contra_sharp_money' || low === 'contra_sharp_line' || low.startsWith('reverse_steam=');
  });
};

export const performanceGroup = (row) => {
  if (normalizeMarketType(row) === 'PARLAY') return 'parlays';
  const flag = String(row?.is_smart_risk ?? '').toLowerCase();
  const tags = row?.movement_tags || row?.sanity_reasons || [];
  const smart = flag === 'true' || flag === '1' ||
    String(row?.risk_tier || '').trim().toUpperCase() === 'SMART_RISK' ||
    String(tags).split(',').some(tag => tag.trim().toLowerCase() === 'smart_risk_high_return');
  return smart ? 'smart' : 'core';
};

export const getQualityRankScore = (row) => {
  if (!row) return -999;

  if (
    row.quality_score !== null &&
    row.quality_score !== undefined &&
    row.quality_score !== '' &&
    Number.isFinite(Number(row.quality_score))
  ) {
    return Number(row.quality_score);
  }

  const evRaw = getNumericEdge(row);
  const ev = evRaw !== null && Number.isFinite(evRaw) ? evRaw : 0;
  const effEv =
    ev <= 0.085
      ? ev
      : ev <= 0.105
        ? 0.085 + (ev - 0.085) * 0.30
        : 0.085 + 0.020 * 0.30 - (ev - 0.105) * 0.20;
  let score = effEv;

  const lb10 = row.win_prob_lb10 === null || row.win_prob_lb10 === undefined || row.win_prob_lb10 === ''
    ? NaN
    : Number(row.win_prob_lb10);
  if (Number.isFinite(lb10)) {
    score += Math.max(0, lb10 - 0.52) * 0.35;
  } else {
    const conf = getNumericConfidence(row);
    if (conf > 0) score += Math.max(0, conf - 55) * 0.0004;
  }

  const mkt = normalizeMarketType(row);
  const sideText = `${row.side || ''} ${row.selection || ''} ${row.pick || ''}`.toUpperCase();
  const rawLine = row.market_line ?? row.bet_line ?? row.line;
  const parsedLine = rawLine !== null && rawLine !== undefined && rawLine !== '' ? Number(rawLine) : NaN;
  if (mkt === 'TOTAL' || mkt === 'TOTAL_1H') {
    if (sideText.includes('UNDER')) score += 0.003;
    if (Number.isFinite(parsedLine)) {
      const totLine = Math.abs(parsedLine);
      if (totLine >= 138 && totLine <= 156) score += 0.004;
    }
  } else if (mkt === 'SPREAD' || mkt === 'SPREAD_1H') {
    if (Number.isFinite(parsedLine)) {
      const absLine = Math.abs(parsedLine);
      if (absLine < 6) score += 0.005;
      else if (absLine >= 6 && absLine < 14) score += 0.003;
      else if (absLine >= 14 && absLine < 22) score -= 0.018;
      else if (absLine >= 22) score -= 0.03;

      const sideHint = String(row.side || '').trim().toLowerCase();
      let isAway = null;
      if (sideHint === 'away' || sideHint === 'home') {
        isAway = sideHint === 'away';
      } else {
        const selLow = String(row.selection || row.pick || '').trim().toLowerCase();
        let awayTeam = String(row.away_team || '').trim().toLowerCase();
        let homeTeam = String(row.home_team || '').trim().toLowerCase();
        if (!awayTeam && !homeTeam) {
          const mTxt = String(row.matchup || '').trim().toLowerCase();
          if (mTxt.includes(' @ ')) [awayTeam, homeTeam] = mTxt.split(' @ ').map((s) => s.trim());
          else if (mTxt.includes(' vs ')) [awayTeam, homeTeam] = mTxt.split(' vs ').map((s) => s.trim());
        }
        if (awayTeam && selLow.startsWith(awayTeam)) isAway = true;
        else if (homeTeam && selLow.startsWith(homeTeam)) isAway = false;
      }

      if (parsedLine > 0) score += isAway ? 0.007 : 0.005;
      else if (parsedLine < 0 && isAway) score -= 0.016;
    }
  }

  const rawAgree =
    mkt === 'TOTAL' || mkt === 'TOTAL_1H'
      ? (row.conviction_sources_total ?? row.context?.conviction_sources_total)
      : (row.conviction_sources ?? row.context?.conviction_sources);
  const agreeN = rawAgree !== null && rawAgree !== undefined && rawAgree !== '' ? Number(rawAgree) : NaN;
  if (Number.isFinite(agreeN)) {
    if (agreeN >= 3) score += 0.012;
    else if (agreeN === 2) score += 0.006;
  }

  const rawTags = row.movement_tags || row.sanity_reasons;
  const tagList = Array.isArray(rawTags)
    ? rawTags
    : typeof rawTags === 'string'
      ? rawTags.split(',')
      : [];
  const tags = tagList.map((t) => String(t || '').trim().toLowerCase()).filter(Boolean);
  if (tags.includes('sharp_backing')) score += 0.012;
  if (tags.includes('rlm_confirmed')) score += 0.006;
  if (tags.includes('sharp_price_edge')) score += 0.008;
  if (tags.includes('contra_sharp_money')) score -= 0.03;
  if (tags.includes('contra_sharp_line')) score -= 0.018;
  if (tags.some((t) => t.startsWith('reverse_steam='))) score -= 0.02;

  const isSmartRisk =
    Boolean(row.is_smart_risk) ||
    String(row.risk_tier || '').trim().toUpperCase() === 'SMART_RISK' ||
    tags.includes('smart_risk_high_return');
  if (isSmartRisk) score -= 0.015;

  return Number(score.toFixed(6));
};

const isCanonicalSlateRow = (row) => {
  if (!row) return false;
  if (row.canonical_source === 'daily_top_picks' || row.source_type === 'canonical_slate') return true;
  const rk = Number(row.rank);
  return Number.isFinite(rk) && rk > 0;
};

const compareDailySlateRows = (a, b) => {
  const lockedA = isLockedRecommendedSlateRow(a);
  const lockedB = isLockedRecommendedSlateRow(b);
  if (lockedA !== lockedB) return lockedA ? -1 : 1;

  if (lockedA && lockedB) {
    const rkA = Number(a?.rank);
    const rkB = Number(b?.rank);
    const hasRkA = Number.isFinite(rkA) && rkA > 0;
    const hasRkB = Number.isFinite(rkB) && rkB > 0;
    if (hasRkA && hasRkB && rkA !== rkB) return rkA - rkB;
  }

  const canonA = isCanonicalSlateRow(a) ? 0 : 1;
  const canonB = isCanonicalSlateRow(b) ? 0 : 1;
  if (canonA !== canonB) return canonA - canonB;

  const riskA = hasTop6RiskFlag(a) ? 1 : 0;
  const riskB = hasTop6RiskFlag(b) ? 1 : 0;
  if (riskA !== riskB) return riskA - riskB;

  const qA = getQualityRankScore(a);
  const qB = getQualityRankScore(b);
  if (qB !== qA) return qB - qA;

  const evA = getNumericEdge(a) ?? -999;
  const evB = getNumericEdge(b) ?? -999;
  if (evB !== evA) return evB - evA;

  const rkA = Number(a?.rank);
  const rkB = Number(b?.rank);
  const hasRkA = Number.isFinite(rkA) && rkA > 0;
  const hasRkB = Number.isFinite(rkB) && rkB > 0;
  if (hasRkA || hasRkB) {
    return (hasRkA ? rkA : 999) - (hasRkB ? rkB : 999);
  }
  return 0;
};

export const dedupeDayRowsByEvent = (dayRows) => {
  const sorted = dayRows.slice().sort(compareDailySlateRows);
  const seenEvents = new Set();
  const unique = [];
  for (const row of sorted) {
    const key = getEventDedupeKey(row);
    if (key && seenEvents.has(key)) continue;
    if (key) seenEvents.add(key);
    unique.push(row);
  }
  return unique;
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
    const uniqueDay = dedupeDayRowsByEvent(groups[day]).filter((r) => isLockedRecommendedSlateRow(r) || !hasTop6RiskFlag(r));
    out.push(...uniqueDay.slice(0, topN));
  }
  return out;
};

export const computeRankBreakdown = (rows, maxRank = 6, rowFilter = null) => {
  const list = Array.isArray(rows) ? rows : [];
  const groups = {};
  for (const h of list) {
    const day = getPerformanceDay(h) || 'unknown';
    if (!groups[day]) groups[day] = [];
    groups[day].push(h);
  }

  const buckets = Array.from({ length: maxRank }, (_, idx) => ({
    rank: idx + 1,
    label: `#${idx + 1}`,
    total: 0,
    wins: 0,
    losses: 0,
    pushes: 0,
    roiSum: 0,
  }));

  for (const day of Object.keys(groups)) {
    const uniqueDay = dedupeDayRowsByEvent(groups[day]).filter((r) => isLockedRecommendedSlateRow(r) || !hasTop6RiskFlag(r));
    uniqueDay.slice(0, maxRank).forEach((row, idx) => {
      if (typeof rowFilter === 'function' && !rowFilter(row)) return;
      const bucket = buckets[idx];
      const out = getRawOutcome(row);
      const norm = normalizeOutcome(out);
      bucket.total += 1;
      if (norm === 'WON') bucket.wins += 1;
      else if (norm === 'LOST') bucket.losses += 1;
      else if (norm === 'PUSH') bucket.pushes += 1;
      bucket.roiSum += roiPerUnit(out, getEffectivePrice(row));
    });
  }

  return buckets.map((b) => {
    const decided = b.wins + b.losses;
    const settled = decided + b.pushes;
    return {
      rank: b.rank,
      label: b.label,
      total: b.total,
      settled,
      wins: b.wins,
      losses: b.losses,
      pushes: b.pushes,
      decided,
      winRate: decided > 0 ? (b.wins / decided) * 100 : 0,
      profitUnits: b.roiSum,
      roiPct: settled > 0 ? (b.roiSum / settled) * 100 : 0,
    };
  });
};

export const getSegmentStatusMeta = (settled, roiPct) => {
  const n = Number(settled || 0);
  const roi = Number(roiPct || 0);
  if (n < 3) {
    return { key: 'small_sample', label: 'Small Sample', tone: 'slate' };
  }
  if (roi >= 12) {
    return { key: 'outperforming', label: 'Outperforming', tone: 'emerald' };
  }
  if (roi >= 2) {
    return { key: 'profitable', label: 'Profitable', tone: 'emerald' };
  }
  if (roi >= -3) {
    return { key: 'break_even', label: 'Break-Even', tone: 'sky' };
  }
  if (roi >= -12) {
    return { key: 'watch', label: 'Soft / Watch', tone: 'amber' };
  }
  return { key: 'leaking', label: 'Leaking · Guarded', tone: 'rose' };
};

const inferSpreadSideIsAway = (row) => {
  const sideHint = String(row?.side || '').trim().toLowerCase();
  if (sideHint === 'away' || sideHint === 'home') return sideHint === 'away';
  const selLow = String(row?.selection || row?.pick || '').trim().toLowerCase();
  let awayTeam = String(row?.away_team || '').trim().toLowerCase();
  let homeTeam = String(row?.home_team || '').trim().toLowerCase();
  if (!awayTeam && !homeTeam) {
    const mTxt = String(row?.matchup || '').trim().toLowerCase();
    if (mTxt.includes(' @ ')) [awayTeam, homeTeam] = mTxt.split(' @ ').map((s) => s.trim());
    else if (mTxt.includes(' vs ')) [awayTeam, homeTeam] = mTxt.split(' vs ').map((s) => s.trim());
  }
  if (awayTeam && selLow.startsWith(awayTeam)) return true;
  if (homeTeam && selLow.startsWith(homeTeam)) return false;
  return null;
};

const GUARDRAIL_NOTES_BY_KEY = {
  total_over: 'Guarded in v2.4.4: stricter Over damping, 2–3 model consensus & +1.8% early EV gate',
  total_under: 'Strength zone: high totals & pace ceiling Unders remain favored',
  spread_dogs: 'Underdog points edge protected from favorite chalk penalties',
  spread_favs: 'Early-season favorites face higher EV hurdles to curb upset chalk losses',
  role_home_fav: 'Guarded in v2.4.4: 0.80x early-season chalk damp + role-specific EV gate',
  role_away_fav: 'Road favorite gate (+2.4%/+3.2% EV hurdle & 0.60x/0.75x damping)',
  role_away_dog: 'Profitable underdog role protected by role-aware adaptive learning',
  role_home_dog: 'Protected from Spread:Home chalk penalty via role-aware learning',
  edge_10plus: 'Guarded: unconfirmed >10.5% EV outliers require sharp-book or 3/3 consensus',
};

const finalizeDiagnosticSegment = (acc, key, group) => {
  const decided = acc.wins + acc.losses;
  const settled = decided + acc.pushes;
  const winRate = decided > 0 ? (acc.wins / decided) * 100 : 0;
  const roiPct = settled > 0 ? (acc.profitUnits / settled) * 100 : 0;
  return {
    key,
    group,
    label: acc.label,
    settled,
    decided,
    wins: acc.wins,
    losses: acc.losses,
    pushes: acc.pushes,
    recordText: `${acc.wins}-${acc.losses}${acc.pushes > 0 ? `-${acc.pushes}` : ''}`,
    winRate,
    profitUnits: Number(acc.profitUnits.toFixed(2)),
    roiPct: Number(roiPct.toFixed(1)),
    status: getSegmentStatusMeta(settled, roiPct),
    guardrailNote: GUARDRAIL_NOTES_BY_KEY[key] || null,
  };
};

/**
 * Computes actionable Leak Radar, Market-Side Split, Regime Era Comparison, and
 * 666-game Feed Accuracy Benchmark for Model Performance.
 */
export const computePerformanceDiagnostics = (rows = [], modelLearning = null) => {
  const safeRows = Array.isArray(rows) ? rows : [];
  const graded = safeRows.filter((h) => {
    const n = normalizeOutcome(getRawOutcome(h));
    return n === 'WON' || n === 'LOST' || n === 'PUSH';
  });

  const segAcc = {
    total_under: { label: 'Totals Under', group: 'Market × Side', wins: 0, losses: 0, pushes: 0, profitUnits: 0 },
    total_over: { label: 'Totals Over', group: 'Market × Side', wins: 0, losses: 0, pushes: 0, profitUnits: 0 },
    spread_dogs: { label: 'Spread Underdogs (+)', group: 'Market × Side', wins: 0, losses: 0, pushes: 0, profitUnits: 0 },
    spread_favs: { label: 'Spread Favorites (-)', group: 'Market × Side', wins: 0, losses: 0, pushes: 0, profitUnits: 0 },
    first_half: { label: '1H Markets', group: 'Market × Side', wins: 0, losses: 0, pushes: 0, profitUnits: 0 },
    moneyline: { label: 'Moneylines', group: 'Market × Side', wins: 0, losses: 0, pushes: 0, profitUnits: 0 },
    role_away_dog: { label: 'Away Underdog (+)', group: 'Spread Role', wins: 0, losses: 0, pushes: 0, profitUnits: 0 },
    role_home_dog: { label: 'Home Underdog (+)', group: 'Spread Role', wins: 0, losses: 0, pushes: 0, profitUnits: 0 },
    role_home_fav: { label: 'Home Favorite (-)', group: 'Spread Role', wins: 0, losses: 0, pushes: 0, profitUnits: 0 },
    role_away_fav: { label: 'Away Favorite (-)', group: 'Spread Role', wins: 0, losses: 0, pushes: 0, profitUnits: 0 },
    edge_2to5: { label: 'Edge 2% – 5%', group: 'Edge Band', wins: 0, losses: 0, pushes: 0, profitUnits: 0 },
    edge_5to10: { label: 'Edge 5% – 10%', group: 'Edge Band', wins: 0, losses: 0, pushes: 0, profitUnits: 0 },
    edge_10plus: { label: 'Edge 10%+', group: 'Edge Band', wins: 0, losses: 0, pushes: 0, profitUnits: 0 },
  };

  const addSeg = (key, norm, pl) => {
    const a = segAcc[key];
    if (!a) return;
    if (norm === 'WON') a.wins += 1;
    else if (norm === 'LOST') a.losses += 1;
    else if (norm === 'PUSH') a.pushes += 1;
    a.profitUnits += pl;
  };

  const preEraRows = [];
  const currEraRows = [];

  for (const h of graded) {
    const out = getRawOutcome(h);
    const norm = normalizeOutcome(out);
    const pl = roiPerUnit(out, getEffectivePrice(h));
    const day = getPerformanceDay(h);
    if (day) {
      if (day < '2026-11-16') preEraRows.push(h);
      else currEraRows.push(h);
    }

    const mkt = normalizeMarketType(h);
    const sideText = `${h?.side || ''} ${h?.selection || ''} ${h?.pick || ''}`.toUpperCase();
    const rawLine = h?.bet_line ?? h?.market_line ?? h?.line;
    const numLine = rawLine !== null && rawLine !== undefined && rawLine !== '' ? Number(rawLine) : NaN;

    if (mkt === 'TOTAL') {
      if (sideText.includes('UNDER')) addSeg('total_under', norm, pl);
      else if (sideText.includes('OVER')) addSeg('total_over', norm, pl);
    } else if (mkt === 'SPREAD' && Number.isFinite(numLine)) {
      if (numLine > 0) addSeg('spread_dogs', norm, pl);
      else if (numLine < 0) addSeg('spread_favs', norm, pl);

      const isAway = inferSpreadSideIsAway(h);
      if (numLine > 0 && isAway === true) addSeg('role_away_dog', norm, pl);
      else if (numLine > 0 && isAway === false) addSeg('role_home_dog', norm, pl);
      else if (numLine < 0 && isAway === false) addSeg('role_home_fav', norm, pl);
      else if (numLine < 0 && isAway === true) addSeg('role_away_fav', norm, pl);
    } else if (mkt === 'TOTAL_1H' || mkt === 'SPREAD_1H') {
      addSeg('first_half', norm, pl);
    } else if (mkt === 'MONEYLINE') {
      addSeg('moneyline', norm, pl);
    }

    const evDec = getNumericEdge(h);
    if (evDec !== null) {
      const evPct = evDec * 100;
      if (evPct < 5) addSeg('edge_2to5', norm, pl);
      else if (evPct < 10) addSeg('edge_5to10', norm, pl);
      else addSeg('edge_10plus', norm, pl);
    }
  }

  const segments = Object.entries(segAcc)
    .map(([key, acc]) => finalizeDiagnosticSegment(acc, key, acc.group))
    .filter((s) => s.settled > 0);

  const marketSideKeys = ['total_under', 'total_over', 'spread_dogs', 'spread_favs'];
  const marketSideSplit = marketSideKeys
    .map((k) => segments.find((s) => s.key === k))
    .filter(Boolean);

  const primaryPool = segments.filter(
    (s) => (s.group === 'Market × Side' || s.group === 'Spread Role') && s.settled >= 2
  );
  const poolForRanking = primaryPool.length > 0 ? primaryPool : segments.filter((s) => s.settled >= 2);

  const topWinners = poolForRanking
    .filter((s) => s.profitUnits > 0.05)
    .slice()
    .sort((a, b) => b.profitUnits - a.profitUnits || b.roiPct - a.roiPct)
    .slice(0, 3);

  const topLeaks = poolForRanking
    .filter((s) => s.profitUnits < -0.05)
    .slice()
    .sort((a, b) => a.profitUnits - b.profitUnits || a.roiPct - b.roiPct)
    .slice(0, 3);

  const totalNet = graded.reduce((acc, h) => acc + roiPerUnit(getRawOutcome(h), getEffectivePrice(h)), 0);
  const topLeak = topLeaks[0] || null;
  const topWin = topWinners[0] || null;

  let headlineSummary = 'Not enough settled picks in the active filter to isolate drivers.';
  if (graded.length > 0) {
    if (topLeak && totalNet < 0) {
      const lossShare = Math.min(100, Math.round((Math.abs(topLeak.profitUnits) / Math.max(0.1, Math.abs(totalNet))) * 100));
      headlineSummary = `${topLeak.label} (${topLeak.recordText}, ${topLeak.profitUnits.toFixed(2)}u) drove ${lossShare}% of the net drawdown${topWin ? `, while ${topWin.label} led winners at +${topWin.profitUnits.toFixed(2)}u (${topWin.winRate.toFixed(1)}% WR)` : ''}.`;
    } else if (topWin) {
      headlineSummary = `${topWin.label} leads profitability at ${topWin.recordText} (+${topWin.profitUnits.toFixed(2)}u, ${topWin.roiPct >= 0 ? '+' : ''}${topWin.roiPct.toFixed(1)}% ROI)${topLeak ? `; biggest drag is ${topLeak.label} (${topLeak.profitUnits.toFixed(2)}u)` : ''}.`;
    }
  }

  const FEED_LABELS = {
    market: 'Sportsbook Consensus',
    blended_fair: 'Blended Model Fair',
    kenpom: 'KenPom Ratings',
    torvik: 'BartTorvik Ratings',
    haslametrics: 'Haslametrics',
  };
  const rawFeedAcc = modelLearning?.all_games_summary?.feed_accuracy || null;
  const marketMae = rawFeedAcc?.market?.mae != null ? Number(rawFeedAcc.market.mae) : null;
  const feedBenchmark = rawFeedAcc
    ? Object.entries(rawFeedAcc)
        .filter(([, v]) => v && v.mae != null && Number(v.n || 0) > 0)
        .map(([key, v]) => ({
          key,
          label: FEED_LABELS[key] || key,
          mae: Number(v.mae),
          n: Number(v.n),
          atsWinRate: v.ats_win_rate != null ? Number(v.ats_win_rate) * 100 : null,
          deltaVsMarket: marketMae != null && key !== 'market' ? Number((Number(v.mae) - marketMae).toFixed(3)) : null,
        }))
        .sort((a, b) => a.mae - b.mae)
    : [];

  const eraComparison =
    preEraRows.length > 0 && currEraRows.length > 0
      ? {
          pre: computeRecordStats(preEraRows),
          current: computeRecordStats(currEraRows),
        }
      : null;

  return {
    settledCount: graded.length,
    segments,
    marketSideSplit,
    topWinners,
    topLeaks,
    headlineSummary,
    feedBenchmark,
    eraComparison,
    allGamesCount: Number(modelLearning?.all_games_summary?.n_games || 0),
  };
};
