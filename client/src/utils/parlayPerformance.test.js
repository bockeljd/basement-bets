import { describe, expect, it } from 'vitest';
import {
  computeParlayAnalytics,
  impliedBreakEvenPctFromAmericanOdds,
} from './parlayPerformance';

describe('parlayPerformance analytics helper', () => {
  const sampleReport = {
    items: [
      {
        id: 'p1',
        date_et: '2026-11-20',
        season: '2026-27',
        bucket: 'high_confidence',
        american_odds: 150,
        p_win: 0.44,
        ev: 0.1,
        outcome: 'WON',
        roi_per_unit: 1.5,
        legs: [
          { event_id: 'e1', market_type: 'MONEYLINE', team_pick: 'Duke ML', price: -160, outcome: 'WON' },
          { event_id: 'e2', market_type: 'SPREAD', team_pick: 'Kansas -3.5', price: -110, outcome: 'WON' },
        ],
      },
      {
        id: 'p2',
        date_et: '2026-11-21',
        season: '2026-27',
        bucket: 'payout_band',
        american_odds: 260,
        p_win: 0.34,
        ev: 0.08,
        outcome: 'LOST',
        roi_per_unit: -1.0,
        legs: [
          { event_id: 'e3', market_type: 'TOTAL', team_pick: 'UNDER 144.5', price: -110, outcome: 'LOST' },
          { event_id: 'e4', market_type: 'SPREAD_1H', team_pick: 'Vermont 1H +2.5', price: -110, outcome: 'WON' },
        ],
      },
      {
        id: 'p3',
        date_et: '2026-11-22',
        season: '2026-27',
        bucket: 'high_confidence',
        american_odds: 380,
        p_win: 0.25,
        ev: 0.12,
        outcome: 'WON (partial)',
        roi_per_unit: 0.8333,
        legs: [
          { event_id: 'e5', market_type: 'MONEYLINE', team_pick: 'Baylor ML', price: -120, outcome: 'WON' },
          { event_id: 'e6', market_type: 'SPREAD', team_pick: 'Arizona -4.0', price: -110, outcome: 'PUSH' },
        ],
      },
      {
        id: 'p_old',
        date_et: '2025-11-20',
        season: '2025-26',
        bucket: 'high_confidence',
        american_odds: 180,
        p_win: 0.4,
        ev: 0.05,
        outcome: 'LOST',
        roi_per_unit: -1.0,
        legs: [
          { event_id: 'e7', market_type: 'MONEYLINE', team_pick: 'Old ML', price: -130, outcome: 'LOST' },
        ],
      },
    ],
  };

  it('computes implied break-even probabilities accurately', () => {
    expect(impliedBreakEvenPctFromAmericanOdds(100)).toBeCloseTo(50.0, 2);
    expect(impliedBreakEvenPctFromAmericanOdds(200)).toBeCloseTo(33.33, 2);
    expect(impliedBreakEvenPctFromAmericanOdds(-200)).toBeCloseTo(66.67, 2);
    expect(impliedBreakEvenPctFromAmericanOdds(0)).toBeNull();
  });

  it('filters by season and computes KPIs, calibration, legs, buckets, odds bands, and curve', () => {
    const res = computeParlayAnalytics(sampleReport, {
      selectedSeason: '2026-27',
      windowFilter: 'ALL',
    });

    expect(res.items).toHaveLength(3);
    expect(res.wins).toBe(2);
    expect(res.losses).toBe(1);
    expect(res.recordText).toBe('2-1');
    expect(res.winRate).toBeCloseTo(66.7, 1);
    // 1.5 - 1.0 + 0.8333 = 1.3333 -> 1.33
    expect(res.profitUnits).toBe(1.33);
    expect(res.roiPct).toBeCloseTo(44.4, 1);

    // Calibration metrics
    // avgOdds: (150 + 260 + 380) / 3 = 263
    expect(res.avgOdds).toBe(263);
    // breakEven across +150 (40.0%), +260 (27.78%), +380 (20.83%) => ~29.5%
    expect(res.breakEvenWinPct).toBeCloseTo(29.5, 1);
    // avgModelWinPct: (44 + 34 + 25) / 3 = 34.3%
    expect(res.avgModelWinPct).toBeCloseTo(34.3, 1);
    expect(res.avgProjectedEvPct).toBeCloseTo(10.0, 1);

    // Individual leg hit rates: 4 WON, 1 LOST, 1 PUSH
    expect(res.legWins).toBe(4);
    expect(res.legLosses).toBe(1);
    expect(res.legPushes).toBe(1);
    expect(res.legDecided).toBe(5);
    expect(res.legWinRate).toBeCloseTo(80.0, 1);

    const mktByKey = Object.fromEntries(res.legMarkets.map((m) => [m.marketKey, m]));
    expect(mktByKey.MONEYLINE.wins).toBe(2);
    expect(mktByKey.SPREAD.wins).toBe(1);
    expect(mktByKey.SPREAD.pushes).toBe(1);
    expect(mktByKey.TOTAL.losses).toBe(1);
    expect(mktByKey.SPREAD_1H.wins).toBe(1);

    // Strategy buckets
    const bucketByKey = Object.fromEntries(res.buckets.map((b) => [b.key, b]));
    expect(bucketByKey.high_confidence.recordText).toBe('2-0');
    expect(bucketByKey.high_confidence.profitUnits).toBe(2.33);
    expect(bucketByKey.payout_band.recordText).toBe('0-1');
    expect(bucketByKey.payout_band.profitUnits).toBe(-1.0);

    // Odds bands
    const bandByKey = Object.fromEntries(res.oddsBands.map((b) => [b.key, b]));
    expect(bandByKey.under200.recordText).toBe('1-0');
    expect(bandByKey.mid200_349.recordText).toBe('0-1');
    expect(bandByKey.plus350.recordText).toBe('1-0');

    // Chronological cumulative equity curve
    expect(res.equityCurve.map((d) => d.day)).toEqual(['2026-11-20', '2026-11-21', '2026-11-22']);
    expect(res.equityCurve.map((d) => d.cumulativeUnits)).toEqual([1.5, 0.5, 1.33]);
    expect(res.sparkPoints).toEqual([1.5, 0.5, 1.33]);
  });

  it('filters by time window relative to today ET', () => {
    const todayStr = new Date().toLocaleDateString('en-CA', { timeZone: 'America/New_York' });
    const recentReport = {
      items: [
        { id: 'r1', date_et: todayStr, season: '2026-27', american_odds: 150, outcome: 'PENDING', legs: [] },
        { id: 'r2', date_et: '2020-01-01', season: '2026-27', american_odds: 150, outcome: 'WON', roi_per_unit: 1.5, legs: [] },
      ],
    };
    const res = computeParlayAnalytics(recentReport, { selectedSeason: '2026-27', windowFilter: '7' });
    expect(res.items.map((x) => x.id)).toEqual(['r1']);
    expect(res.pending).toBe(1);
    expect(res.settled).toBe(0);
  });

  it('audits Moneyline vs Spread/Total leg calibration and overconfidence gaps', () => {
    const auditReport = {
      items: [
        {
          id: 'a1',
          date_et: '2026-11-20',
          season: '2026-27',
          american_odds: 150,
          outcome: 'LOST',
          roi_per_unit: -1.0,
          legs: [
            { event_id: 'e1', market_type: 'MONEYLINE', price: -200, win_prob: 0.72, outcome: 'LOST' },
            { event_id: 'e2', market_type: 'SPREAD', price: -110, win_prob: 0.56, outcome: 'WON' },
          ],
        },
        {
          id: 'a2',
          date_et: '2026-11-21',
          season: '2026-27',
          american_odds: 160,
          outcome: 'LOST',
          roi_per_unit: -1.0,
          legs: [
            { event_id: 'e3', market_type: 'MONEYLINE', price: -180, win_prob: 0.70, outcome: 'LOST' },
            { event_id: 'e4', market_type: 'TOTAL', price: -110, win_prob: 0.56, outcome: 'WON' },
          ],
        },
        {
          id: 'a3',
          date_et: '2026-11-22',
          season: '2026-27',
          american_odds: 155,
          outcome: 'WON',
          roi_per_unit: 1.55,
          legs: [
            { event_id: 'e5', market_type: 'MONEYLINE', price: -190, win_prob: 0.71, outcome: 'WON' },
            { event_id: 'e6', market_type: 'SPREAD', price: -110, win_prob: 0.58, outcome: 'WON' },
          ],
        },
      ],
    };

    const res = computeParlayAnalytics(auditReport, { selectedSeason: '2026-27', windowFilter: 'ALL' });
    const mlMkt = res.legMarkets.find((m) => m.marketKey === 'MONEYLINE');
    expect(mlMkt.winRate).toBeCloseTo(33.3, 1);
    expect(mlMkt.avgExpectedWinPct).toBeCloseTo(71.0, 1);
    expect(mlMkt.calibrationGapPct).toBeCloseTo(-37.7, 1);
    expect(mlMkt.avgImpliedWinPct).toBeGreaterThan(64);

    expect(res.mlVsSpreadAudit.moneyline.recordText).toBe('1-2');
    expect(res.mlVsSpreadAudit.spreadTotal.recordText).toBe('3-0');
    expect(res.mlVsSpreadAudit.overconfidentWarning).toBe(true);
    expect(res.mlVsSpreadAudit.summaryText).toContain('ML 1-2');
    expect(res.mlVsSpreadAudit.summaryText).toContain('Spread/Total 3-0');
  });
});
