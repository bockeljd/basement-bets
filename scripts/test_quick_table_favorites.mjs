import assert from 'node:assert';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const helperPath = path.resolve(__dirname, '../client/src/utils/bracketTableUtils.js');
const { determineMatchFavorite } = await import(`file://${helperPath}`);

const cases = [
  {
    match: { team_a: 'Duke', team_b: 'Siena', win_prob_a: 0.8, win_prob_b: 0.2 },
    expectedFavorite: 'Duke',
    expectedFavoritePct: 0.8
  },
  {
    match: { team_a: 'UCLA', team_b: 'UCF', win_prob_a: 0.35, win_prob_b: 0.65 },
    expectedFavorite: 'UCF',
    expectedFavoritePct: 0.65
  }
];

for (const { match, expectedFavorite, expectedFavoritePct } of cases) {
  const favorite = determineMatchFavorite(match);
  assert.strictEqual(favorite.favoriteTeam, expectedFavorite, `Expected ${expectedFavorite} to be favorite`);
  assert.strictEqual(favorite.favoritePct, expectedFavoritePct, `Expected favorite % to equal ${expectedFavoritePct}`);
}

console.log('Bracket table favorite helper tests passed.');
