import assert from 'node:assert';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const utilsPath = path.resolve(__dirname, '../client/src/utils/bracketTableRows.js');
const { resolveBracketFavorite } = await import(`file://${utilsPath}`);

const scheduledMatch = {
  team_a: 'Duke',
  team_b: 'Siena',
  win_prob_a: 0.8,
  win_prob_b: 0.2,
  status: 'scheduled'
};
const scheduledResult = resolveBracketFavorite(scheduledMatch);
assert.strictEqual(scheduledResult.favoriteTeam, 'Duke', 'Scheduled favorite should match highest win probability');
assert.strictEqual(scheduledResult.favoritePct, 0.8, 'Scheduled favorite pct should be 0.8');
assert.strictEqual(scheduledResult.dogPct, 0.2, 'Scheduled dog pct should be 0.2');

const finalMatch = {
  team_a: 'Duke',
  team_b: 'Siena',
  win_prob_a: 0.3,
  win_prob_b: 0.7,
  status: 'final',
  display_winner: 'Duke'
};
const finalResult = resolveBracketFavorite(finalMatch);
assert.strictEqual(finalResult.favoriteTeam, 'Duke', 'Final favorite should use display_winner');
assert.strictEqual(finalResult.favoritePct, 0.3, 'Final favorite pct should reflect actual win_prob');
assert.strictEqual(finalResult.dogPct, 0.7, 'Final dog pct should reflect opponent win_prob');

console.log('Quick Table favorite helper tests passed.');
