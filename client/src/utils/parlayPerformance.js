import {
  formatMarketLabel,
  normalizeMarketType,
  normalizeOutcome,
  toEtDay,
} from './modelPerformance';

const normalizeParlayOutcome = (rawOutcome) => {
  const upper = String(rawOutcome || 'PENDING').trim().toUpperCase();
  if (upper === 'WON (PARTIAL)') return 'WON';
  return normalizeOutcome(upper);
};

export const impliedBreakEvenPctFromAmericanOdds = (price) => {
  const odds = Number(price);
  if (!Number.isFinite(odds) || odds === 0 || Math.abs(odds) < 100) return null;
  if (odds > 0) return (100 / (odds + 100)) * 100;
  return (Math.abs(odds) / (Math.abs(odds) + 100)) * 100;
};

const createBucketStats = (key, label) => ({
  key,
  label,
  total: 0,
  wins: 0,
  losses: 0,
  pushes: 0,
  voids: 0,
  pending: 0,
  profitUnits: 0,
});

const accumulateParlayItem = (acc, item, normOut) => {
  acc.total += 1;
  if (normOut === 'WON') acc.wins += 1;
  else if (normOut === 'LOST') acc.losses += 1;
  else if (normOut === 'PUSH') acc.pushes += 1;
  else if (normOut === 'VOID') acc.voids += 1;
  else acc.pending += 1;

  if (
    (normOut === 'WON' || normOut === 'LOST' || normOut === 'PUSH') &&
    item.roi_per_unit !== null &&
    item.roi_per_unit !== undefined &&
    Number.isFinite(Number(item.roi_per_unit))
  ) {
    acc.profitUnits += Number(item.roi_per_unit);
  }
};

const finalizeParlayBucket = (b) => {
  const decided = b.wins + b.losses;
  const settled = decided + b.pushes;
  return {
    key: b.key,
    label: b.label,
    total: b.total,
    wins: b.wins,
    losses: b.losses,
    pushes: b.pushes,
    voids: b.voids,
    pending: b.pending,
    decided,
    settled,
    recordText: `${b.wins}-${b.losses}${b.pushes > 0 ? `-${b.pushes}` : ''}`,
    winRate: decided > 0 ? (b.wins / decided) * 100 : 0,
    profitUnits: Number(b.profitUnits.toFixed(2)),
    roiPct: settled > 0 ? (b.profitUnits / settled) * 100 : 0,
  };
};

export const computeParlayAnalytics = (
  parlayReport,
  { selectedSeason = 'ALL', windowFilter = 'ALL' } = {}
) => {
  const rawItems = Array.isArray(parlayReport?.items) ? parlayReport.items : [];
  const todayEt = toEtDay(new Date()) || new Date().toISOString().slice(0, 10);
  const daysBack =
    windowFilter === '7' ? 7 : windowFilter === '30' ? 30 : windowFilter === '90' ? 90 : null;
  let cutoffEt = null;
  if (daysBack) {
    const dt = new Date(`${todayEt}T12:00:00Z`);
    dt.setUTCDate(dt.getUTCDate() - daysBack);
    cutoffEt = dt.toISOString().slice(0, 10);
  }

  const items = rawItems.filter((item) => {
    if (!item) return false;
    if (selectedSeason && selectedSeason !== 'ALL' && item.season && item.season !== selectedSeason) {
      return false;
    }
    if (cutoffEt && item.date_et && String(item.date_et).slice(0, 10) < cutoffEt) {
      return false;
    }
    return true;
  });

  const overall = createBucketStats('all', 'Official Daily Parlays');
  const bucketMap = {
    high_confidence: createBucketStats('high_confidence', 'High Confidence'),
    payout_band: createBucketStats('payout_band', 'Value Payout Band'),
  };
  const oddsBandMap = {
    under200: createBucketStats('under200', '< +200'),
    mid200_349: createBucketStats('mid200_349', '+200 to +349'),
    plus350: createBucketStats('plus350', '+350+'),
  };
  const dayMap = new Map();
  const legMarketMap = new Map();

  let oddsSum = 0;
  let oddsCount = 0;
  let breakEvenSum = 0;
  let breakEvenCount = 0;
  let modelWinSum = 0;
  let modelWinCount = 0;
  let projEvSum = 0;
  let projEvCount = 0;

  let legWins = 0;
  let legLosses = 0;
  let legPushes = 0;
  let legPending = 0;

  for (const item of items) {
    const normOut = normalizeParlayOutcome(item.outcome);
    const isSettled = normOut === 'WON' || normOut === 'LOST' || normOut === 'PUSH';
    accumulateParlayItem(overall, item, normOut);

    const bKey = String(item.bucket || '').trim().toLowerCase();
    if (bKey === 'high_confidence') {
      accumulateParlayItem(bucketMap.high_confidence, item, normOut);
    } else if (bKey === 'payout_band') {
      accumulateParlayItem(bucketMap.payout_band, item, normOut);
    }

    const oddsVal = Number(item.american_odds);
    if (Number.isFinite(oddsVal) && oddsVal !== 0 && Math.abs(oddsVal) >= 100) {
      oddsSum += oddsVal;
      oddsCount += 1;
      if (oddsVal < 200) accumulateParlayItem(oddsBandMap.under200, item, normOut);
      else if (oddsVal < 350) accumulateParlayItem(oddsBandMap.mid200_349, item, normOut);
      else accumulateParlayItem(oddsBandMap.plus350, item, normOut);

      if (isSettled) {
        const be = impliedBreakEvenPctFromAmericanOdds(oddsVal);
        if (be !== null) {
          breakEvenSum += be;
          breakEvenCount += 1;
        }
      }
    }

    const pWin = Number(item.p_win);
    if (isSettled && Number.isFinite(pWin) && pWin > 0 && pWin <= 1) {
      modelWinSum += pWin * 100;
      modelWinCount += 1;
    }

    const evVal = item.ev !== null && item.ev !== undefined && item.ev !== '' ? Number(item.ev) : NaN;
    if (Number.isFinite(evVal)) {
      projEvSum += evVal * 100;
      projEvCount += 1;
    }

    if (isSettled) {
      const day = String(item.date_et || '').slice(0, 10);
      if (day) {
        if (!dayMap.has(day)) {
          dayMap.set(day, {
            day,
            shortDay: day.length >= 10 ? day.slice(5) : day,
            wins: 0,
            losses: 0,
            pushes: 0,
            dayUnits: 0,
          });
        }
        const dEntry = dayMap.get(day);
        if (normOut === 'WON') dEntry.wins += 1;
        else if (normOut === 'LOST') dEntry.losses += 1;
        else if (normOut === 'PUSH') dEntry.pushes += 1;
        if (item.roi_per_unit !== null && item.roi_per_unit !== undefined && Number.isFinite(Number(item.roi_per_unit))) {
          dEntry.dayUnits += Number(item.roi_per_unit);
        }
      }
    }

    const legs = Array.isArray(item.legs) ? item.legs : [];
    for (const lg of legs) {
      if (!lg || typeof lg !== 'object') continue;
      const lgNorm = normalizeOutcome(lg.outcome);
      if (lgNorm === 'WON') legWins += 1;
      else if (lgNorm === 'LOST') legLosses += 1;
      else if (lgNorm === 'PUSH') legPushes += 1;
      else if (lgNorm !== 'VOID') legPending += 1;

      const mktKey = normalizeMarketType(lg.market_type || 'MONEYLINE');
      if (!legMarketMap.has(mktKey)) {
        legMarketMap.set(mktKey, {
          marketKey: mktKey,
          label: formatMarketLabel(mktKey),
          wins: 0,
          losses: 0,
          pushes: 0,
          pending: 0,
          expectedWinSum: 0,
          expectedWinCount: 0,
          impliedWinSum: 0,
          impliedWinCount: 0,
        });
      }
      const mEntry = legMarketMap.get(mktKey);
      if (lgNorm === 'WON') mEntry.wins += 1;
      else if (lgNorm === 'LOST') mEntry.losses += 1;
      else if (lgNorm === 'PUSH') mEntry.pushes += 1;
      else if (lgNorm !== 'VOID') mEntry.pending += 1;

      if (lgNorm === 'WON' || lgNorm === 'LOST') {
        const lgWp = Number(lg.win_prob);
        if (Number.isFinite(lgWp) && lgWp > 0 && lgWp <= 1) {
          mEntry.expectedWinSum += lgWp * 100;
          mEntry.expectedWinCount += 1;
        }
        const lgImplied = impliedBreakEvenPctFromAmericanOdds(lg.price);
        if (lgImplied !== null) {
          mEntry.impliedWinSum += lgImplied;
          mEntry.impliedWinCount += 1;
        }
      }
    }
  }

  const finalOverall = finalizeParlayBucket(overall);
  const legDecided = legWins + legLosses;
  const legMarkets = Array.from(legMarketMap.values())
    .map((m) => {
      const decided = m.wins + m.losses;
      const winRate = decided > 0 ? (m.wins / decided) * 100 : 0;
      const avgExpectedWinPct =
        m.expectedWinCount > 0 ? Number((m.expectedWinSum / m.expectedWinCount).toFixed(1)) : null;
      const avgImpliedWinPct =
        m.impliedWinCount > 0 ? Number((m.impliedWinSum / m.impliedWinCount).toFixed(1)) : null;
      return {
        marketKey: m.marketKey,
        label: m.label,
        wins: m.wins,
        losses: m.losses,
        pushes: m.pushes,
        pending: m.pending,
        decided,
        recordText: `${m.wins}-${m.losses}${m.pushes > 0 ? `-${m.pushes}` : ''}`,
        winRate,
        avgExpectedWinPct,
        avgImpliedWinPct,
        calibrationGapPct:
          decided > 0 && avgExpectedWinPct !== null
            ? Number((winRate - avgExpectedWinPct).toFixed(1))
            : null,
        vsImpliedGapPct:
          decided > 0 && avgImpliedWinPct !== null
            ? Number((winRate - avgImpliedWinPct).toFixed(1))
            : null,
      };
    })
    .sort((a, b) => (b.decided + b.pending) - (a.decided + a.pending) || b.winRate - a.winRate);

  const summarizeAuditGroup = (groupMarkets) => {
    let gWins = 0;
    let gLosses = 0;
    let expSum = 0;
    let expCount = 0;
    let impSum = 0;
    let impCount = 0;
    for (const gm of groupMarkets) {
      const raw = legMarketMap.get(gm.marketKey);
      gWins += gm.wins;
      gLosses += gm.losses;
      if (raw) {
        expSum += raw.expectedWinSum;
        expCount += raw.expectedWinCount;
        impSum += raw.impliedWinSum;
        impCount += raw.impliedWinCount;
      }
    }
    const decided = gWins + gLosses;
    const winRate = decided > 0 ? Number(((gWins / decided) * 100).toFixed(1)) : 0;
    const avgExpectedWinPct = expCount > 0 ? Number((expSum / expCount).toFixed(1)) : null;
    const avgImpliedWinPct = impCount > 0 ? Number((impSum / impCount).toFixed(1)) : null;
    const calibrationGapPct =
      decided > 0 && avgExpectedWinPct !== null
        ? Number((winRate - avgExpectedWinPct).toFixed(1))
        : null;
    return {
      decided,
      wins: gWins,
      losses: gLosses,
      recordText: `${gWins}-${gLosses}`,
      winRate,
      avgExpectedWinPct,
      avgImpliedWinPct,
      calibrationGapPct,
    };
  };

  const mlAudit = summarizeAuditGroup(legMarkets.filter((m) => m.marketKey === 'MONEYLINE'));
  const stAudit = summarizeAuditGroup(
    legMarkets.filter((m) => ['SPREAD', 'TOTAL', 'SPREAD_1H', 'TOTAL_1H'].includes(m.marketKey))
  );
  const overconfidentWarning =
    mlAudit.decided >= 3 && mlAudit.calibrationGapPct !== null && mlAudit.calibrationGapPct <= -5.0;

  let auditSummaryText = null;
  if (mlAudit.decided > 0 || stAudit.decided > 0) {
    const parts = [];
    if (mlAudit.decided > 0) {
      const mlCal =
        mlAudit.avgExpectedWinPct !== null
          ? ` vs ${mlAudit.avgExpectedWinPct.toFixed(1)}% model`
          : mlAudit.avgImpliedWinPct !== null
            ? ` vs ${mlAudit.avgImpliedWinPct.toFixed(1)}% implied`
            : '';
      parts.push(`ML ${mlAudit.recordText} (${mlAudit.winRate.toFixed(1)}%${mlCal})`);
    }
    if (stAudit.decided > 0) {
      const stCal =
        stAudit.avgExpectedWinPct !== null
          ? ` vs ${stAudit.avgExpectedWinPct.toFixed(1)}% model`
          : stAudit.avgImpliedWinPct !== null
            ? ` vs ${stAudit.avgImpliedWinPct.toFixed(1)}% implied`
            : '';
      parts.push(`Spread/Total ${stAudit.recordText} (${stAudit.winRate.toFixed(1)}%${stCal})`);
    }
    auditSummaryText = parts.join(' · ');
  }

  const mlVsSpreadAudit = {
    moneyline: mlAudit,
    spreadTotal: stAudit,
    overconfidentWarning,
    summaryText: auditSummaryText,
  };

  let runningUnits = 0;
  const equityCurve = Array.from(dayMap.values())
    .sort((a, b) => a.day.localeCompare(b.day))
    .map((d) => {
      runningUnits += d.dayUnits;
      const settled = d.wins + d.losses + d.pushes;
      return {
        ...d,
        settled,
        dayUnits: Number(d.dayUnits.toFixed(2)),
        cumulativeUnits: Number(runningUnits.toFixed(2)),
        recordText: `${d.wins}-${d.losses}${d.pushes > 0 ? `-${d.pushes}` : ''}`,
      };
    });

  return {
    ...finalOverall,
    items,
    avgOdds: oddsCount > 0 ? Math.round(oddsSum / oddsCount) : null,
    breakEvenWinPct: breakEvenCount > 0 ? Number((breakEvenSum / breakEvenCount).toFixed(1)) : null,
    avgModelWinPct: modelWinCount > 0 ? Number((modelWinSum / modelWinCount).toFixed(1)) : null,
    avgProjectedEvPct: projEvCount > 0 ? Number((projEvSum / projEvCount).toFixed(1)) : null,
    legWins,
    legLosses,
    legPushes,
    legPending,
    legDecided,
    legRecordText: `${legWins}-${legLosses}${legPushes > 0 ? `-${legPushes}` : ''}`,
    legWinRate: legDecided > 0 ? (legWins / legDecided) * 100 : 0,
    legMarkets,
    mlVsSpreadAudit,
    buckets: [
      finalizeParlayBucket(bucketMap.high_confidence),
      finalizeParlayBucket(bucketMap.payout_band),
    ],
    oddsBands: [
      finalizeParlayBucket(oddsBandMap.under200),
      finalizeParlayBucket(oddsBandMap.mid200_349),
      finalizeParlayBucket(oddsBandMap.plus350),
    ],
    equityCurve,
    sparkPoints: equityCurve.map((d) => d.cumulativeUnits),
  };
};
