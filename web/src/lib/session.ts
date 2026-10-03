import { type Access, type AccessUser, getAccess } from "@/lib/access";
import type { Sql } from "@/lib/db";
import { env } from "@/lib/env";

export type DbUser = {
  id: number;
  auth_provider_id: string;
  email: string | null;
  favorite_team_id: number | null;
  plan: "free" | "pro";
  subscription_status: string | null;
  stripe_customer_id: string | null;
  price_interval: "monthly" | "annual" | null;
  current_period_end: string | null;
};

// The signed-in visitor's Clerk user id, or null. Clerk is not connected yet (Phase 6 waits on Brian's Clerk
// account), so everyone is signed out; connecting Clerk means replacing this one function.
export async function currentAuthId(): Promise<string | null> {
  return null;
}

export async function currentUser(sql: Sql): Promise<DbUser | null> {
  const authId = await currentAuthId();
  if (!authId) return null;
  const [user] = await sql<DbUser[]>`
    select id, auth_provider_id, email, favorite_team_id, plan, subscription_status, stripe_customer_id, price_interval,
           to_char(current_period_end at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') as current_period_end
    from users where auth_provider_id = ${authId}`;
  return user ?? null;
}

// What this visitor may see. Gating is off (everyone sees everything, as before Phase 6) until ACCESS_GATING=on,
// which is switched on when sign-up and billing are live.
export async function currentAccess(sql: Sql): Promise<Access> {
  const [user, gating] = await Promise.all([currentUser(sql), env("ACCESS_GATING")]);
  return getAccess(user as AccessUser, { gating: gating === "on" });
}
