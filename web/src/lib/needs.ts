// Team-need matching shared by Trade Targets and the Trade Builder (CLAUDE.md sections 6 and 7).
import type { TeamNeed, TradeTarget } from "@/lib/queries";

export const NEED_LABELS: Record<string, string> = {
  goal_scoring: "Goal scoring", playmaking: "Playmaking", physicality: "Physicality", defense_5v5: "5v5 defense",
  power_play: "Power play", penalty_kill: "Penalty kill", goaltending: "Goaltending",
};

// Buy-low: he performs far better than fans rate him. Both as percentiles (fan scores cluster near the middle),
// in his position's top 30% for performance, at least 40 points above where fans rank him.
export function isBuyLow(t: TradeTarget): boolean {
  return t.fans_pctile != null && t.perf_vs_fans != null && t.perf_vs_fans >= 70 && t.perf_vs_fans - t.fans_pctile >= 40;
}

// How well he fills the team's needs: his best percentile among its Need (full weight) and Thin (85%) categories.
export function needFit(t: TradeTarget, needs: TeamNeed[]): { score: number; category: string; pctile: number } | null {
  let best: { score: number; category: string; pctile: number } | null = null;
  for (const n of needs) {
    const p = t.need?.[n.category];
    if (p == null) continue;
    const score = p * (n.grade <= -2 ? 1 : 0.85);
    if (!best || score > best.score) best = { score, category: n.category, pctile: p };
  }
  return best;
}

