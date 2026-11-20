import { describe, expect, it } from 'vitest';
import { getRecEv, hasTop6RiskFlag, lookupTopPickForGame, makeMatchupKey } from './todayHelpers';

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
});
