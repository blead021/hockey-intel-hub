// NHL seasons start in the fall: September 2026 onward is 20262027 (same rule as the Python pipeline).
export function currentSeason(today = new Date()): number {
  const start = today.getUTCMonth() >= 8 ? today.getUTCFullYear() : today.getUTCFullYear() - 1;
  return start * 10000 + start + 1;
}

export function parseSeason(value: string | string[] | undefined): number | null {
  if (typeof value !== "string" || !/^\d{8}$/.test(value)) return null;
  const start = Number(value.slice(0, 4));
  return Number(value.slice(4)) === start + 1 ? Number(value) : null;
}
