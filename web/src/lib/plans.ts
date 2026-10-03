import { env } from "@/lib/env";

// What each plan includes (CLAUDE.md section 2), shown on the pricing and landing pages.
export const FREE_INCLUDES = [
  "League overview: all 32 teams' needs and strengths, with cap space",
  "Top 10 trade targets and Top 10 undervalued players",
  "Your favorite team (My Team): roster, contracts, and player profiles",
  "The weekly email",
];

export const PRO_INCLUDES = [
  "Every team's roster, contracts, and cap by season",
  "Every Player Profile: play style, advanced metrics, Game Score, sentiment",
  "Trade Targets with filters, cap fit, and buy-low signals",
  "Trade Builder with cap math, checks, and comparable past trades",
  "Rumor Tracker: trade chatter by player, rising or fading",
  "Watchlists and alerts",
];

// Prices are set in Stripe; the labels shown here come from PRICE_LABEL_ANNUAL / PRICE_LABEL_MONTHLY (for example
// "$24 per year") so nothing is hardcoded before Brian picks final prices.
export async function priceLabels(): Promise<{ annual: string | null; monthly: string | null; billingReady: boolean }> {
  const [annual, monthly, key, a, m] = await Promise.all([
    env("PRICE_LABEL_ANNUAL"), env("PRICE_LABEL_MONTHLY"), env("STRIPE_SECRET_KEY"),
    env("STRIPE_PRICE_ID_ANNUAL"), env("STRIPE_PRICE_ID_MONTHLY"),
  ]);
  return { annual: annual ?? null, monthly: monthly ?? null, billingReady: Boolean(key && (a || m)) };
}
