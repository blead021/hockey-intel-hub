// Display helpers. Every function returns "—" for missing values so tables never show "NaN".

const DASH = "—";

export function toi(seconds: number | null | undefined): string {
  if (seconds == null || Number.isNaN(seconds)) return DASH;
  const s = Math.round(seconds);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export function pct(value: number | null | undefined, digits = 1): string {
  if (value == null || Number.isNaN(value)) return DASH;
  return `${(value * 100).toFixed(digits)}%`;
}

// Save percentage in hockey style: .915
export function svPct(saves: number, shots: number): string {
  if (!shots) return DASH;
  return (saves / shots).toFixed(3).replace(/^0/, "");
}

export function num(value: number | null | undefined, digits = 0): string {
  if (value == null || Number.isNaN(value)) return DASH;
  return value.toFixed(digits);
}

export function signed(value: number | null | undefined): string {
  if (value == null) return DASH;
  return value > 0 ? `+${value}` : String(value);
}

export function money(value: number | null | undefined): string {
  if (value == null) return DASH;
  // $7,850,000 -> $7.85M, $104,000,000 -> $104M, $775,000 -> $775K
  if (Math.abs(value) >= 1_000_000) return `$${(value / 1_000_000).toFixed(3).replace(/\.?0+$/, "")}M`;
  return `$${Math.round(value / 1000)}K`;
}

// 20262027 -> "2026-27"
export function season(id: number): string {
  const start = Math.floor(id / 10000);
  return `${start}-${String((start + 1) % 100).padStart(2, "0")}`;
}

export function heightFt(inches: number | null | undefined): string {
  if (!inches) return DASH;
  return `${Math.floor(inches / 12)}'${inches % 12}"`;
}

export function shortDate(value: Date | string): string {
  const d = typeof value === "string" ? new Date(`${value}T12:00:00Z`) : value;
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
}

// Faceoff % is shown only for players with 50 or more draws (CLAUDE.md section 6).
export const MIN_FACEOFFS = 50;

export function faceoffPct(won: number, lost: number): string {
  const total = won + lost;
  return total >= MIN_FACEOFFS ? pct(won / total) : DASH;
}
