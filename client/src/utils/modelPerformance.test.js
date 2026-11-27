import { describe, expect, it } from 'vitest';
import {
  computePerformanceDiagnostics,
  formatLineAndOdds,
  formatMarketLabel,
  getQualityRankScore,
  getSegmentStatusMeta,
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

  it('computes Leak Radar diagnostics, Market-Side Split, Era Comparison, and Feed MAE benchmarks', () => {
    const sampleRows = [
      { day_et: '2026-11-14', market_type: 'TOTAL', selection: 'OVER 144.5', side: 'over', bet_line: 144.5, bet_price: -110, outcome: 'LOST', ev_per_unit: 0.08 },
      { day_et: '2026-11-14', market_type: 'TOTAL', selection: 'OVER 142.5', side: 'over', bet_line: 142.5, bet_price: -110, outcome: 'LOST', ev_per_unit: 0.11 },
      { day_et: '2026-11-15', market_type: 'TOTAL', selection: 'OVER 140.5', side: 'over', bet_line: 140.5, bet_price: -110, outcome: 'LOST', ev_per_unit: 0.06 },
      { day_et: '2026-11-14', market_type: 'TOTAL', selection: 'UNDER 163.5', side: 'under', bet_line: 163.5, bet_price: -105, outcome: 'WON', ev_per_unit: 0.09 },
      { day_et: '2026-11-18', market_type: 'TOTAL', selection: 'UNDER 158.5', side: 'under', bet_line: 158.5, bet_price: -110, outcome: 'WON', ev_per_unit: 0.06 },
      { day_et: '2026-11-25', market_type: 'SPREAD', selection: 'Colorado +9.5', side: 'away', away_team: 'Colorado', home_team: 'Baylor', bet_line: 9.5, bet_price: -105, outcome: 'WON', ev_per_unit: 0.058 },
    ];
    const mockLearning = {
      all_games_summary: {
        n_games: 666,
        feed_accuracy: {
          haslametrics: { n: 521, mae: 10.956, ats_win_rate: 0.474 },
          market: { n: 666, mae: 9.947 },
          kenpom: { n: 575, mae: 10.437, ats_win_rate: 0.4837 },
          torvik: { n: 642, mae: 10.482, ats_win_rate: 0.5035 },
          blended_fair: { n: 642, mae: 10.084, ats_win_rate: 0.5 },
        },
      },
    };

    const diag = computePerformanceDiagnostics(sampleRows, mockLearning);
    expect(diag.settledCount).toBe(6);
    expect(diag.topLeaks[0].key).toBe('total_over');
    expect(diag.topLeaks[0].profitUnits).toBe(-3);
    expect(diag.topLeaks[0].guardrailNote).toContain('v2.4.4');
    expect(diag.topWinners[0].key).toBe('total_under');
    expect(diag.topWinners[0].profitUnits).toBeGreaterThan(1.8);
    expect(diag.headlineSummary).toContain('Totals Over');
    expect(diag.eraComparison).not.toBeNull();
    expect(diag.eraComparison.pre.losses).toBe(3);
    expect(diag.eraComparison.current.wins).toBe(2);
    expect(diag.feedBenchmark.map((f) => f.key)).toEqual([
      'market',
      'blended_fair',
      'kenpom',
      'torvik',
      'haslametrics',
    ]);

    expect(getSegmentStatusMeta(2, 50).key).toBe('small_sample');
    expect(getSegmentStatusMeta(10, -25).label).toBe('Leaking · Guarded');
    expect(getSegmentStatusMeta(10, 15).label).toBe('Outperforming');
  });
});
