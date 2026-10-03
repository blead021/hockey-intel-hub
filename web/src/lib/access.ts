// Plans and gating (CLAUDE.md section 2). Every gated page and API route asks getAccess what the visitor may see,
// and the answer is enforced on the server, never by hiding things in the browser.
//
// This file has no imports so its tests run with plain Node (`npm test`).

export type Plan = "free" | "pro";

export type Feature =
  | "league"          // League page (needs grid, Top 10 trade targets, Top 10 undervalued)
  | "my_team"         // the favorite team's roster and its players' profiles
  | "weekly_email"
  | "all_teams"
  | "all_players"
  | "trade_targets"
  | "trade_builder"
  | "rumors"
  | "watchlists"
  | "alerts";

export const FREE_FEATURES: readonly Feature[] = ["league", "my_team", "weekly_email"];
export const PRO_FEATURES: readonly Feature[] = [
  ...FREE_FEATURES, "all_teams", "all_players", "trade_targets", "trade_builder", "rumors", "watchlists", "alerts",
];

// What the database knows about a signed-in user (null when signed out).
export type AccessUser = {
  plan: Plan;
  subscription_status: string | null;
  current_period_end: string | Date | null;
  favorite_team_id: number | null;
} | null;

export type Access = {
  signedIn: boolean;
  plan: Plan;
  features: ReadonlySet<Feature>;
  favoriteTeamId: number | null;
  // False until accounts are switched on (ACCESS_GATING=on): then every visitor sees everything, as before Phase 6.
  gating: boolean;
};

// Stripe statuses that keep Pro. A canceled or unpaid subscription keeps Pro until the paid period ends, so a user
// who cancels in the portal loses access at period end, not at once.
const PAID_STATUSES = new Set(["active", "trialing"]);
const GRACE_STATUSES = new Set(["past_due", "canceled", "unpaid"]);

export function isPro(user: AccessUser, now: Date = new Date()): boolean {
  if (!user || user.plan !== "pro") return false;
  const status = user.subscription_status ?? "";
  if (PAID_STATUSES.has(status)) return true;
  if (GRACE_STATUSES.has(status) && user.current_period_end) return new Date(user.current_period_end) > now;
  return false;
}

export function getAccess(user: AccessUser, options: { gating: boolean; now?: Date }): Access {
  const pro = isPro(user, options.now);
  const plan: Plan = pro ? "pro" : "free";
  const features = new Set<Feature>(!options.gating || pro ? PRO_FEATURES : FREE_FEATURES);
  return { signedIn: user != null, plan, features, favoriteTeamId: user?.favorite_team_id ?? null, gating: options.gating };
}

export function can(access: Access, feature: Feature): boolean {
  return access.features.has(feature);
}

// Team Roster: every team for Pro; free users get their favorite team ("My Team").
export function canViewTeam(access: Access, teamId: number): boolean {
  return can(access, "all_teams") || (access.favoriteTeamId != null && access.favoriteTeamId === teamId);
}

// Player Profile: every player for Pro; free users get players on their favorite team.
export function canViewPlayer(access: Access, playerTeamId: number | null): boolean {
  return can(access, "all_players") || (playerTeamId != null && access.favoriteTeamId === playerTeamId);
}
