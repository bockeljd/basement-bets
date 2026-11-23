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

  it('applies learned 47/53 CBB curve, late fouling surge, blowout drag, and OT bump dynamically', () => {
    // 1. Halftime 47/53 curve projects higher than naive 50/50
    const half47 = getLiveGameStatus(
      {
        sport: 'NCAAM',
        status: 'HALFTIME',
        home_team: 'Duke',
        away_team: 'UNC',
        home_score: 35,
        away_score: 33,
        live_trend: { first_half_share: 0.47 },
      },
      { bet_type: 'TOTAL', selection: 'OVER 143.5', side: 'over', market_line: 143.5 },
      { fair_total: 144.0 }
    );
    const half50 = getLiveGameStatus(
      {
        sport: 'NCAAM',
        status: 'HALFTIME',
        home_team: 'Duke',
        away_team: 'UNC',
        home_score: 35,
        away_score: 33,
        live_trend: { first_half_share: 0.5 },
      },
      { bet_type: 'TOTAL', selection: 'OVER 143.5', side: 'over', market_line: 143.5 },
      { fair_total: 144.0 }
    );
    expect(half47.liveProjTotal).toBeGreaterThan(half50.liveProjTotal + 3);

    // 2. Tight game with 2:00 left gets late-foul surge + OT chance; blowout gets negative drag
    const tightLate = getLiveGameStatus(
      {
        sport: 'NCAAM',
        status: 'LIVE',
        period: 2,
        clock: '2:00',
        home_team: 'Duke',
        away_team: 'UNC',
        home_score: 70,
        away_score: 68,
        live_trend: { late_foul_boost_pts: 4.0, ot_prob_scale: 1.0, ot_extra_pts: 15.5 },
      },
      { bet_type: 'TOTAL', selection: 'OVER 144.5', side: 'over', market_line: 144.5 },
      { fair_total: 144.0 }
    );
    const blowoutLate = getLiveGameStatus(
      {
        sport: 'NCAAM',
        status: 'LIVE',
        period: 2,
        clock: '2:00',
        home_team: 'Duke',
        away_team: 'UNC',
        home_score: 82,
        away_score: 56,
        live_trend: { late_blowout_drag_pts: 3.0, ot_prob_scale: 1.0 },
      },
      { bet_type: 'TOTAL', selection: 'OVER 144.5', side: 'over', market_line: 144.5 },
      { fair_total: 144.0 }
    );
    expect(tightLate.latePaceAdj).toBeGreaterThan(0.5);
    expect(tightLate.otProb).toBeGreaterThan(0.05);
    expect(blowoutLate.latePaceAdj).toBeLessThan(-0.5);
    expect(tightLate.liveProjTotal).toBeGreaterThan(blowoutLate.liveProjTotal + 3);

    // 3. 1H bet automatically grades as WON at Halftime
    const half1H = getLiveGameStatus(
      {
        sport: 'NCAAM',
        status: 'HALFTIME',
        home_team: 'FGCU',
        away_team: 'Charlotte',
        home_score: 30,
        away_score: 38,
      },
      { bet_type: 'TOTAL_1H', selection: '1H OVER 66.5', side: 'over', market_line: 66.5 }
    );
    expect(half1H.trendVerdict).toBe('WON');
    expect(half1H.liveWinProb).toBe(1);

    // 4. 1H bet in 2nd half settles immediately when home_score_1h/away_score_1h exist (LOST case -> 34+28=62 < 66.5)
    const half1HIn2HLoss = getLiveGameStatus(
      {
        sport: 'NCAAM',
        status: 'IN_PROGRESS',
        period: 2,
        clock: '19:39',
        home_team: 'Florida Gulf Coast Eagles',
        away_team: 'Charlotte 49ers',
        home_score: 31,
        away_score: 37,
        home_score_1h: 28,
        away_score_1h: 34,
      },
      { bet_type: 'TOTAL_1H', selection: '1H OVER 66.5', side: 'over', market_line: 66.5 }
    );
    expect(half1HIn2HLoss.trendVerdict).toBe('LOST');
    expect(half1HIn2HLoss.isBetSettled).toBe(true);
    expect(half1HIn2HLoss.coverTone).toBe('loss');

    // 5. 1H bet in 2nd half WITHOUT 1H scores enters PENDING_1H and never renders "null"
    const half1HNo1HScores = getLiveGameStatus(
      {
        sport: 'NCAAM',
        status: 'IN_PROGRESS',
        period: 2,
        clock: '19:39',
        home_team: 'Florida Gulf Coast Eagles',
        away_team: 'Charlotte 49ers',
        home_score: 31,
        away_score: 37,
      },
      { bet_type: 'TOTAL_1H', selection: '1H OVER 66.5', side: 'over', market_line: 66.5 }
    );
    expect(half1HNo1HScores.trendVerdict).toBe('PENDING_1H');
    expect(half1HNo1HScores.trendDetail).not.toContain('null');
  });
});
