import assert from 'node:assert';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const utilsPath = path.resolve(__dirname, '../client/src/utils/bracketTableUtils.js');
const { determineMatchFavorite } = await import(`file://${utilsPath}`);

const cases = [
  { match: { team_a: 'Duke', team_b: 'Siena', win_prob_a: 0.8, win_prob_b: 0.2 }, favorite: 'Duke', pct: 0.8 },
  { match: { team_a: 'UConn', team_b: 'Furman', win_prob_a: 0.3, win_prob_b: 0.7 }, favorite: 'Furman', pct: 0.7 }
];

for (const { match, favorite, pct } of cases) {
  const result = determineMatchFavorite(match);
  assert.strictEqual(result.favoriteTeam, favorite, `Expected ${favorite} to be favorite`);
  assert.strictEqual(result.favoritePct, pct, `Expected favorite pct to be ${pct}`);
}

console.log('Quick Table favorite helper tests passed.');
