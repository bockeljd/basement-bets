import { describe, expect, it } from 'vitest';
import {
  getConfidenceMeta,
  getLiveGameStatus,
  getRecEv,
  getRecQualityScore,
  hasTop6RiskFlag,
  lookupTopPickForGame,
  makeMatchupKey,
  normalizeMovementTag,
} from './todayHelpers';

describe('Today recommendations', () => {
  it('preserves a zero EV and reads a percentage when EV is absent', () => {
    expect(getRecEv({ ev: 0, edge: '8%' })).toBe(0);
    expect(getRecEv({ edge: '8%' })).toBeCloseTo(.08);
  });

  it('honors a publisher exclusion and flags reverse steam', () => {
    expect(hasTop6RiskFlag({ top6_eligible: false })).toBe(true);
    expect(hasTop6RiskFlag({ movement_tags: ['reverse_steam=2'] })).toBe(true);
    expect(hasTop6RiskFlag({ movement_tags: [] })).toBe(false);
  });

  it('matches neutral-site games across providers with reversed team ordering', () => {
    const game = { day_et: '2026-11-20', home_team: 'Temple', away_team: 'Penn' };
    const key = makeMatchupKey(game.day_et, game.home_team, game.away_team);
    expect(lookupTopPickForGame(game, {}, { [key]: { id: 'pick' } })).toEqual({ id: 'pick' });
  });

  it('labels Smart Risk picks and sharp-line tags in plain language', () => {
    expect(getConfidenceMeta({ is_smart_risk: true, confidence_0_100: 46 }).tier).toBe('SMART_RISK');
    expect(normalizeMovementTag('sharp_price_edge').label).toBe('Better Line Than Sharp Books');
    expect(normalizeMovementTag('smart_risk_high_return').label).toBe('Smart Risk · 0.5u');
  });

  it('ranks competitive spreads and 3-of-3 consensus ahead of blowouts', () => {
    const comp = getRecQualityScore({ bet_type: 'SPREAD', side: 'home', market_line: -8.5, ev: 0.045, win_prob_lb10: 0.53, conviction_sources: 3 });
    const blowout = getRecQualityScore({ bet_type: 'SPREAD', side: 'home', market_line: -23.5, ev: 0.045, win_prob_lb10: 0.53, conviction_sources: 1 });
    expect(comp).toBeGreaterThan(blowout);
  });

  it('tracks 1H bets against the 20-minute first half clock instead of 40-minute full game', () => {
    const game = {
      sport: 'NCAAM',
      status: 'LIVE',
      period: 1,
      clock: '2:36',
      away_team: 'Charlotte 49ers',
      home_team: 'Florida Gulf Coast Eagles',
      away_score: 32,
      home_score: 25,
    };
    const rec = {
      bet_type: 'TOTAL_1H',
      selection: '1H OVER 66.5',
      side: 'over',
      market_line: 66.5,
      fair_line: 69.0,
    };
    const live = getLiveGameStatus(game, rec, { fair_total: 147.0 });
    expect(live.progressPct).toBeGreaterThanOrEqual(85);
    expect(live.liveProjTotal).toBeGreaterThan(60);
    expect(live.liveProjTotal).toBeLessThan(72);
    expect(live.trendDetail).toContain('2.6 min in 1H');
    expect(live.liveWinProb).toBeLessThan(0.75);
  });
});
