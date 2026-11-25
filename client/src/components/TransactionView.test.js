import { describe, expect, it } from 'vitest';
import { dedupeFilterOptions } from './TransactionView';

describe('TransactionView dedupeFilterOptions', () => {
  it('deduplicates Sport options case-insensitively while keeping acronyms uppercase', () => {
    const sports = dedupeFilterOptions(['GOLF', 'Golf', 'TENNIS', 'Tennis', 'ncaam', 'NBA', 'nfl', '', 'All'], 'sport');
    expect(sports).toEqual(['All', 'Golf', 'NBA', 'NCAAM', 'NFL', 'Tennis']);
  });

  it('deduplicates Bet Type options case-insensitively with canonical casing', () => {
    const types = dedupeFilterOptions(['2 leg parlay', '2 Leg Parlay', 'sgp', 'Straight', 'straight'], 'type');
    expect(types).toEqual(['All', '2 Leg Parlay', 'SGP', 'Straight']);
  });
});
