// Team-need matching shared by Trade Targets and the Trade Builder (CLAUDE.md sections 6 and 7).
import type { TeamNeed, TradeTarget } from "@/lib/queries";

export const NEED_LABELS: Record<string, string> = {
  goal_scoring: "Goal scoring", playmaking: "Playmaking", physicality: "Physicality", defense_5v5: "5v5 defense",
  power_play: "Power play", penalty_kill: "Penalty kill", goaltending: "Goaltending",
};

// Buy-low (player_buy_low view): strong underlying play, results well behind it, and bad luck (low PDO or fewer
// goals than his chances deserve). Not simply "fans rate him low", which made stars look like bargains.
export function isBuyLow(t: TradeTarget): boolean {
  return t.buy_low;
}

// How likely his team is to move him: sellers most, contenders least, and a contender's core almost never.
export function availability(t: TradeTarget): number {
  if (t.team_status === "Contender") return t.core ? 0.2 : 0.6;
  if (t.team_status === "Bubble") return t.core ? 0.5 : 0.8;
  return 1;
}

export function unlikelyAvailable(t: TradeTarget): boolean {
  return t.team_status === "Contender" && t.core;
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

