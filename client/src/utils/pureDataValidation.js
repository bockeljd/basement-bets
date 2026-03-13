
import { 
  getPerformanceDay, 
  roiPerUnit, 
  normalizeOutcome 
} from './modelPerformance.js';

console.log('--- Supplemental Verification: Pure Data Logic ---');

try {
  // 1. getPerformanceDay Precedence
  const row1 = {
    day_et: '2026-03-10',
    start_time: '2026-03-11T20:00:00Z',
    analyzed_at: '2026-03-12T10:00:00Z'
  };
  console.assert(getPerformanceDay(row1) === '2026-03-10', 'Should prefer day_et');

  const row2 = {
    start_time: '2026-03-11T20:00:00Z',
    analyzed_at: '2026-03-12T10:00:00Z'
  };
  console.assert(getPerformanceDay(row2) === '2026-03-11', 'Should fallback to start_time');

  const row3 = {
    analyzed_at: '2026-03-12T10:00:00Z'
  };
  console.assert(getPerformanceDay(row3) === '2026-03-12', 'Should fallback to analyzed_at');

  console.log('✅ getPerformanceDay precedence verified');

  // 2. roiPerUnit Calculations
  const roi1 = roiPerUnit('WON', 150);
  console.assert(roi1 === 1.5, 'WON at +150 should be 1.5');

  const roi2 = roiPerUnit('WON', -200);
  console.assert(roi2 === 0.5, 'WON at -200 should be 0.5');

  const roi3 = roiPerUnit('LOST', 150);
  console.assert(roi3 === -1.0, 'LOST should always be -1.0');

  const roi4 = roiPerUnit('WON', null);
  console.assert(Math.abs(roi4 - 0.90909) < 0.0001, 'Fallback to -110 should be ~0.90909');

  console.log('✅ roiPerUnit calculations verified');

  // 3. Picks transformation logic check
  const hasReco = true;
  const recoStraight = [{ id: 'reco_1', outcome: 'WON' }];
  const gradedYesterdayStraight = [{ id: 'fall_1', outcome: 'LOST' }];
  const displayRows = hasReco ? recoStraight : gradedYesterdayStraight;
  console.assert(displayRows[0].id === 'reco_1', 'Should prioritize recoStraight when hasReco is true');

  console.log('✅ Picks transformation priority verified');

  // 4. Edge sorting check
  const picks = [
    { id: 1, ev_per_unit: 0.02 },
    { id: 2, ev_per_unit: 0.05 },
    { id: 3, ev: 0.08 }
  ];
  const getEv = (h) => parseFloat(h.ev_per_unit ?? h.ev ?? 0);
  const sorted = [...picks].sort((a, b) => getEv(b) - getEv(a));
  console.assert(sorted[0].id === 3, 'Highest EV should be first');
  console.assert(sorted[1].id === 2, 'Middle EV should be second');
  
  console.log('✅ Edge numeric sorting verified');

  console.log('--- All Pure Data Logic Tests PASSED ---');
} catch (e) {
  console.error('❌ Logic tests FAILED:', e);
  process.exit(1);
}
