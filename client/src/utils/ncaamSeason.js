const etYearMonthFormatter = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/New_York',
  year: 'numeric',
  month: 'numeric',
});

export function getCurrentEtYear(date = new Date()) {
  const parts = etYearMonthFormatter.formatToParts(date);
  return Number(parts.find((p) => p.type === 'year')?.value || date.getFullYear());
}

export function getCurrentNcaamBracketYear(date = new Date()) {
  const parts = etYearMonthFormatter.formatToParts(date);
  const year = Number(parts.find((p) => p.type === 'year')?.value || date.getFullYear());
  const month = Number(parts.find((p) => p.type === 'month')?.value || date.getMonth() + 1);
  return month >= 7 ? year + 1 : year;
}

export function getCurrentNcaamSeasonShort(date = new Date()) {
  const endYear = getCurrentNcaamBracketYear(date);
  return `${endYear - 1}-${String(endYear).slice(-2)}`;
}

export function formatSeasonLabel(season) {
  const raw = String(season || '').trim();
  if (!raw || raw.toUpperCase() === 'ALL') return 'All Seasons';
  const spanMatch = raw.match(/^(\d{4})-(\d{2})$/);
  if (spanMatch) {
    const startYear = spanMatch[1];
    const endFullYear = `${startYear.slice(0, 2)}${spanMatch[2]}`;
    return `${startYear}-${endFullYear} Season`;
  }
  if (/^\d{4}$/.test(raw)) {
    return `${raw} Season`;
  }
  return `${raw} Season`;
}
