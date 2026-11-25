import { describe, expect, it } from 'vitest';
import {
  formatLineAndOdds,
  formatMarketLabel,
  getQualityRankScore,
  normalizeMarketType,
  performanceGroup,
} from './modelPerformance';

describe('modelPerformance helpers', () => {
  it('keeps parlay tickets separate from risk-tiered straight picks', () => {
    expect(performanceGroup({ market_type: 'ML', is_smart_risk: 'false' })).toBe('core');
    expect(performanceGroup({ market_type: 'ML', risk_tier: 'SMART_RISK' })).toBe('smart');
    expect(performanceGroup({ movement_tags: ['smart_risk_high_return'] })).toBe('smart');
    expect(performanceGroup({ market_type: 'Parlay', is_smart_risk: true })).toBe('parlays');
  });

  it('keeps 1H spread and total markets distinct and formats their labels and lines', () => {
    expect(normalizeMarketType('SPREAD_1H')).toBe('SPREAD_1H');
    expect(normalizeMarketType('TOTAL_1H')).toBe('TOTAL_1H');
    expect(normalizeMarketType('spreads')).toBe('SPREAD');
    expect(normalizeMarketType('totals')).toBe('TOTAL');

    expect(formatMarketLabel('SPREAD_1H')).toBe('1H Spread');
    expect(formatMarketLabel('TOTAL_1H')).toBe('1H Over / Under');
    expect(formatMarketLabel('NRFI')).toBe('NRFI');
    expect(formatMarketLabel('nrfi')).toBe('NRFI');
    expect(formatMarketLabel('yrfi')).toBe('YRFI');

    expect(
      formatLineAndOdds({
        market_type: 'SPREAD_1H',
        bet_line: -2.5,
        bet_price: -110,
      })
    ).toBe('-2.5 (-110)');

    expect(
      formatLineAndOdds({
        market_type: 'TOTAL_1H',
        bet_line: 66.5,
        bet_price: -108,
      })
    ).toBe('66.5 (-108)');
  });

  it('honors backend quality_score and applies the -0.015 Smart Risk penalty consistently', () => {
    expect(getQualityRankScore({ quality_score: 0.1234, ev_per_unit: 0.02 })).toBe(0.1234);

    const base = {
      market_type: 'SPREAD',
      side: 'home',
      selection: 'Home -3.5',
      home_team: 'Home',
      away_team: 'Away',
      market_line: -3.5,
      ev_per_unit: 0.05,
      win_prob_lb10: 0.56,
    };
    const coreScore = getQualityRankScore({ ...base, risk_tier: 'CORE' });
    const smartRiskScore = getQualityRankScore({ ...base, is_smart_risk: true, risk_tier: 'SMART_RISK' });

    expect(coreScore - smartRiskScore).toBeCloseTo(0.015, 5);
  });
});
