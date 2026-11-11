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
