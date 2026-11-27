import { describe, expect, it } from 'vitest';
import {
  buildCachedAnalysisResult,
  dedupeBoardGames,
  fetchWithRetry,
  getBetTimingGuidance,
  getConfidenceMeta,
  getLiveGameStatus,
  getOutcomeOutlineClasses,
  getParlayTimingGuidance,
  getRecEv,
  getRecQualityScore,
  hasTop6RiskFlag,
  lookupTopPickForGame,
  makeMatchupKey,
  mapTopPicksPayload,
  normalizeBoardTeamKey,
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

    const coreConsensus = getRecQualityScore({
      bet_type: 'SPREAD',
      side: 'away',
      market_line: 1.5,
      ev: 0.05,
      win_prob_lb10: 0.523,
      conviction_sources: 3,
      is_smart_risk: false,
      risk_tier: 'CORE',
    });
    const smartRiskLow = getRecQualityScore({
      bet_type: 'SPREAD',
      side: 'home',
      market_line: -1.5,
      ev: 0.0736,
      win_prob_lb10: 0.513,
      conviction_sources: 0,
      is_smart_risk: true,
      risk_tier: 'SMART_RISK',
      movement_tags: ['smart_risk_high_return', 'sharp_price_edge'],
    });
    expect(coreConsensus).toBeGreaterThan(smartRiskLow);
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

  it('computes pre-game When to Bet guidance from sharp-book edge, injuries, public splits, and clock', () => {
    const nowMs = Date.parse('2026-11-23T17:00:00Z');
    const tipIn = (mins) => new Date(nowMs + mins * 60000).toISOString();

    // 1. Sharp-book advantage -> Bet Now
    const sharpTiming = getBetTimingGuidance(
      {
        bet_type: 'TOTAL',
        selection: 'UNDER 154.5',
        side: 'under',
        book: 'DraftKings',
        sharp_edge_pts: 1.5,
        movement_tags: ['sharp_price_edge'],
      },
      { start_time: tipIn(180), status: 'SCHEDULED' },
      null,
      nowMs
    );
    expect(sharpTiming.action).toBe('BET_NOW');
    expect(sharpTiming.label).toBe('Bet Now');
    expect(sharpTiming.reason).toContain('1.5 pts');

    // 2. Questionable injury > 60m out -> Wait · Check Lineups (OUT does not block)
    const waitTiming = getBetTimingGuidance(
      {
        bet_type: 'SPREAD',
        selection: 'Duke -4.5',
        side: 'home',
        sharp_edge_pts: 1.0,
        signals: { injuries: [{ player: 'Caleb Foster', status: 'Questionable' }] },
      },
      { start_time: tipIn(180), status: 'SCHEDULED' },
      null,
      nowMs
    );
    expect(waitTiming.action).toBe('WAIT_LINEUPS');
    expect(waitTiming.reason).toContain('Caleb Foster');

    const outTiming = getBetTimingGuidance(
      {
        bet_type: 'SPREAD',
        selection: 'Duke -4.5',
        side: 'home',
        sharp_edge_pts: 1.0,
        signals: { injuries: [{ player: 'Bench Guard', status: 'Out' }] },
      },
      { start_time: tipIn(180), status: 'SCHEDULED' },
      null,
      nowMs
    );
    expect(outTiming.action).toBe('BET_NOW');

    // 3. Auto-flips backend MONITOR / WAIT_LINEUPS to BET_NOW when tipoff <= 60m
    const flippedTiming = getBetTimingGuidance(
      {
        bet_type: 'TOTAL',
        selection: 'OVER 141.5',
        side: 'over',
        bet_timing: {
          action: 'MONITOR',
          label: 'Monitor · May Improve',
          short_label: 'Monitor',
          tone: 'blue',
          reason: 'Early no rush',
        },
      },
      { start_time: tipIn(35), status: 'SCHEDULED' },
      null,
      nowMs
    );
    expect(flippedTiming.action).toBe('BET_NOW');
    expect(flippedTiming.drivers).toContain('tipoff_imminent');

    // 4. Opposite public ticket wave -> Monitor
    const monitorTiming = getBetTimingGuidance(
      {
        bet_type: 'SPREAD',
        selection: 'Seton Hall +6.5',
        signals: {
          public_splits: { SPREAD: { HOME: { bet_pct: 70 }, AWAY: { bet_pct: 30 } } },
        },
      },
      { start_time: tipIn(150), home_team: 'Villanova', away_team: 'Seton Hall', status: 'SCHEDULED' },
      null,
      nowMs
    );
    expect(monitorTiming.action).toBe('MONITOR');
    expect(monitorTiming.reason).toContain('70%');

    // 5. 3-of-3 conviction -> Bet Now; live / final / started -> null
    const convTiming = getBetTimingGuidance(
      { bet_type: 'TOTAL', selection: 'UNDER 144.5', side: 'under', conviction_sources_total: 3 },
      { start_time: tipIn(260), status: 'SCHEDULED' },
      null,
      nowMs
    );
    expect(convTiming.action).toBe('BET_NOW');
    expect(getBetTimingGuidance({ bet_type: 'TOTAL' }, { start_time: tipIn(30), status: 'LIVE' }, null, nowMs)).toBeNull();
    expect(getBetTimingGuidance({ bet_type: 'TOTAL' }, { start_time: tipIn(-5), status: 'SCHEDULED' }, null, nowMs)).toBeNull();
  });

  it('builds consistent red/green/push outline classes across official bets and Close Call leans', () => {
    const betWin = getOutcomeOutlineClasses('WON', 'bet');
    expect(betWin.outcome).toBe('WON');
    expect(betWin.cardCls).toContain('border-emerald-500/80');
    expect(betWin.cardCls).not.toContain('border-dashed');
    expect(betWin.rowCls).toContain('bg-emerald-950/40');
    expect(betWin.stripeCls).toContain('border-l-emerald-400');

    expect(getOutcomeOutlineClasses('WIN', 'bet').outcome).toBe('WON');
    expect(getOutcomeOutlineClasses('WON (partial)', 'bet').outcome).toBe('WON');

    const betLoss = getOutcomeOutlineClasses('LOST', 'bet');
    expect(betLoss.outcome).toBe('LOST');
    expect(betLoss.cardCls).toContain('border-rose-500/80');
    expect(betLoss.stripeCls).toContain('border-l-rose-400');
    expect(getOutcomeOutlineClasses('LOSE', 'bet').outcome).toBe('LOST');

    const betPush = getOutcomeOutlineClasses('PUSH', 'bet');
    expect(betPush.outcome).toBe('PUSH');
    expect(betPush.cardCls).toContain('border-slate-500/75');

    const betPending = getOutcomeOutlineClasses('PENDING', 'bet');
    expect(betPending.outcome).toBeNull();
    expect(betPending.stripeCls).toBe('');

    const leanWin = getOutcomeOutlineClasses('WON', 'lean');
    expect(leanWin.outcome).toBe('WON');
    expect(leanWin.cardCls).toContain('border-dashed');
    expect(leanWin.cardCls).toContain('border-emerald-400/75');
    expect(leanWin.badgeCls).toContain('border-dashed');

    const leanLoss = getOutcomeOutlineClasses('LOST', 'lean');
    expect(leanLoss.outcome).toBe('LOST');
    expect(leanLoss.cardCls).toContain('border-dashed');
    expect(leanLoss.cardCls).toContain('border-rose-400/75');

    const leanPending = getOutcomeOutlineClasses(null, 'lean');
    expect(leanPending.outcome).toBeNull();
    expect(leanPending.cardCls).toContain('border-slate-800');
  });

  it('resolves When-to-Bet guidance for multi-leg parlays', () => {
    const nowMs = Date.parse('2026-11-24T17:00:00Z');
    const tipIn = (mins) => new Date(nowMs + mins * 60000).toISOString();

    // 1. Honors backend MONITOR outside imminent window, escalates <= 60m to BET_NOW
    const backendMon = getParlayTimingGuidance(
      {
        outcome: 'PENDING',
        bet_timing: {
          action: 'MONITOR',
          label: 'Monitor · May Improve',
          short_label: 'Monitor',
          tone: 'blue',
          reason: 'No rush yet.',
          drivers: ['early_no_rush'],
        },
        legs: [{ start_time: tipIn(240) }, { start_time: tipIn(300) }],
      },
      nowMs
    );
    expect(backendMon.action).toBe('MONITOR');

    const flippedSoon = getParlayTimingGuidance(
      {
        outcome: 'PENDING',
        bet_timing: {
          action: 'MONITOR',
          label: 'Monitor · May Improve',
          reason: 'Old monitor reason',
        },
        legs: [{ start_time: tipIn(40) }, { start_time: tipIn(180) }],
      },
      nowMs
    );
    expect(flippedSoon.action).toBe('BET_NOW');
    expect(flippedSoon.drivers).toContain('tipoff_imminent');

    // 2. Fallback leg aggregation follows WAIT_LINEUPS > BET_NOW > MONITOR precedence
    const aggWait = getParlayTimingGuidance(
      {
        outcome: 'PENDING',
        legs: [
          {
            team_pick: 'Duke -4.5',
            bet_type: 'SPREAD',
            start_time: tipIn(200),
            sharp_edge_pts: 1.0,
            movement_tags: ['sharp_price_edge'],
          },
          {
            team_pick: 'UNC ML',
            bet_type: 'MONEYLINE',
            start_time: tipIn(250),
            signals: { injuries: [{ player: 'Center', status: 'Questionable' }] },
          },
        ],
      },
      nowMs
    );
    expect(aggWait.action).toBe('WAIT_LINEUPS');
    expect(aggWait.reason).toContain('UNC ML');

    const aggNow = getParlayTimingGuidance(
      {
        outcome: 'PENDING',
        legs: [
          { team_pick: 'UConn ML', bet_type: 'MONEYLINE', start_time: tipIn(300) },
          {
            team_pick: 'Kansas ML',
            bet_type: 'MONEYLINE',
            start_time: tipIn(300),
            sharp_edge_pts: 0.8,
            movement_tags: ['sharp_price_edge'],
          },
        ],
      },
      nowMs
    );
    expect(aggNow.action).toBe('BET_NOW');
    expect(aggNow.reason).toContain('Kansas ML');

    // 3. Returns null when any leg already started or parlay is decided
    expect(
      getParlayTimingGuidance(
        { outcome: 'PENDING', legs: [{ start_time: tipIn(-5) }, { start_time: tipIn(120) }] },
        nowMs
      )
    ).toBeNull();
    expect(
      getParlayTimingGuidance(
        { outcome: 'LOST', legs: [{ start_time: tipIn(120) }, { start_time: tipIn(180) }] },
        nowMs
      )
    ).toBeNull();
  });

  it('deduplicates Action Network vs ESPN NCAAM team variants and preserves richer priced rows', () => {
    expect(normalizeBoardTeamKey("St. Peter's")).toBe(normalizeBoardTeamKey("Saint Peter's"));
    expect(normalizeBoardTeamKey('SE Louisiana')).toBe(normalizeBoardTeamKey('Southeastern Louisiana'));
    expect(normalizeBoardTeamKey('Grambling State')).toBe(normalizeBoardTeamKey('Grambling'));
    expect(normalizeBoardTeamKey('Warner Southern')).toBe(normalizeBoardTeamKey('Warner Royals'));
    expect(normalizeBoardTeamKey("Michigan St.")).not.toBe(normalizeBoardTeamKey("Michigan Saint"));

    const deduped = dedupeBoardGames([
      { id: 'espn:ncaam:1', sport: 'NCAAM', day_et: '2026-11-25', away_team: "Saint Peter's", home_team: 'SE Louisiana' },
      { id: 'action:ncaam:1', sport: 'NCAAM', day_et: '2026-11-25', away_team: "St. Peter's", home_team: 'Southeastern Louisiana', home_spread: -4.5 },
      { id: 'espn:ncaam:2', sport: 'NCAAM', day_et: '2026-11-25', away_team: 'Warner Southern', home_team: 'Grambling State' },
      { id: 'action:ncaam:2', sport: 'NCAAM', day_et: '2026-11-25', away_team: 'Warner Royals', home_team: 'Grambling', total_line: 141.5 },
    ]);
    expect(deduped).toHaveLength(2);
    expect(deduped.map((g) => g.id)).toEqual(['action:ncaam:1', 'action:ncaam:2']);
  });

  it('builds a cached Details snapshot immediately from daily_top_picks metadata', () => {
    const game = {
      id: 'action:ncaam:99',
      home_team: 'Colorado',
      away_team: 'Grand Canyon',
      neutral_site: false,
      venue: 'CU Events Center',
    };
    const actionSnap = buildCachedAnalysisResult(game, {
      isActionable: true,
      rec: { selection: 'Colorado -4.5', bet_type: 'SPREAD', price: -110 },
      context: { fair_spread_home: -6.5, fair_total: 144.0 },
      analyzedAt: '2026-11-25T15:00:00Z',
    });
    expect(actionSnap._fromCache).toBe(true);
    expect(actionSnap.recommendations).toHaveLength(1);
    expect(actionSnap.outputs.mu_spread).toBe(-6.5);
    expect(actionSnap.venue).toBe('CU Events Center');

    const passSnap = buildCachedAnalysisResult(game, {
      isActionable: false,
      reason: 'Line matches fair value',
      context: { fair_spread_home: -4.5 },
    });
    expect(passSnap._fromCache).toBe(true);
    expect(passSnap.recommendations).toEqual([]);
    expect(passSnap.block_reason).toBe('Line matches fair value');
  });

  it('retries transient 504/network failures once and does not retry 403 or aborted requests', async () => {
    let calls = 0;
    const recovered = await fetchWithRetry(
      async () => {
        calls += 1;
        if (calls === 1) {
          const err = new Error('Gateway Timeout');
          err.response = { status: 504 };
          throw err;
        }
        return { data: { ok: true } };
      },
      { retries: 1, delayMs: 0 }
    );
    expect(calls).toBe(2);
    expect(recovered.data.ok).toBe(true);

    let netCalls = 0;
    const recoveredNet = await fetchWithRetry(
      async () => {
        netCalls += 1;
        if (netCalls === 1) {
          throw new Error('Network Error');
        }
        return 'ok';
      },
      { retries: 1, delayMs: 0 }
    );
    expect(netCalls).toBe(2);
    expect(recoveredNet).toBe('ok');

    let forbiddenCalls = 0;
    await expect(
      fetchWithRetry(
        async () => {
          forbiddenCalls += 1;
          const err = new Error('Forbidden');
          err.response = { status: 403 };
          throw err;
        },
        { retries: 1, delayMs: 0 }
      )
    ).rejects.toThrow('Forbidden');
    expect(forbiddenCalls).toBe(1);

    let abortCalls = 0;
    await expect(
      fetchWithRetry(
        async () => {
          abortCalls += 1;
          const err = new Error('Canceled');
          err.name = 'CanceledError';
          err.code = 'ERR_CANCELED';
          throw err;
        },
        { retries: 1, delayMs: 0 }
      )
    ).rejects.toThrow('Canceled');
    expect(abortCalls).toBe(1);
  });

  it('maps top-picks payloads by event_id and neutral/reversed matchup key', () => {
    const { mapped, mappedByKey } = mapTopPicksPayload({
      'action:ncaam:123': {
        is_actionable: false,
        reason: 'Line matches fair value',
        analyzed_at: '2026-11-26T16:44:00Z',
        model_version: '2.4.3-november-spread',
        event: {
          day_et: '2026-11-26',
          home_team: 'Texas Longhorns',
          away_team: 'Georgetown Hoyas',
        },
        context: {
          closest_lean: { selection: 'OVER 154.5', ev: 0.012, edge_points: 1.1 },
        },
      },
    });
    expect(mapped['action:ncaam:123'].context.closest_lean.selection).toBe('OVER 154.5');
    const directKey = makeMatchupKey('2026-11-26', 'Georgetown Hoyas', 'Texas Longhorns');
    expect(mappedByKey[directKey]).toBe(mapped['action:ncaam:123']);
    const swappedBoardRow = {
      id: 'espn:ncaam:999',
      day_et: '2026-11-26',
      home_team: 'Georgetown Hoyas',
      away_team: 'Texas Longhorns',
    };
    expect(lookupTopPickForGame(swappedBoardRow, mapped, mappedByKey)).toBe(mapped['action:ncaam:123']);
  });
});
