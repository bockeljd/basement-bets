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
