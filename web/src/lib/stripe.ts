// Stripe billing without the Stripe SDK: webhook signature checks with Web Crypto (built into Cloudflare Workers)
// and plain HTTPS calls to Stripe's API. No imports, so the tests run with plain Node (`npm test`).

// Stripe-Signature header: "t=<unix seconds>,v1=<hex HMAC-SHA256 of `${t}.${body}`>" (several v1 values can appear
// while a secret is being rolled). Rejects signatures older than `toleranceSec`, so a captured request cannot be
// replayed later.
export async function verifyStripeSignature(
  body: string, header: string | null, secret: string, nowSec: number = Math.floor(Date.now() / 1000), toleranceSec = 300,
): Promise<boolean> {
  if (!header || !secret) return false;
  const parts = header.split(",").map((p) => p.split("=", 2) as [string, string]);
  const t = Number(parts.find(([k]) => k === "t")?.[1]);
  const signatures = parts.filter(([k]) => k === "v1").map(([, v]) => v);
  if (!Number.isFinite(t) || signatures.length === 0 || Math.abs(nowSec - t) > toleranceSec) return false;
  const expected = await hmacHex(secret, `${t}.${body}`);
  return signatures.some((s) => timingSafeEqual(s, expected));
}

export async function hmacHex(secret: string, message: string): Promise<string> {
  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey("raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = await crypto.subtle.sign("HMAC", key, enc.encode(message));
  return [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

// The handled events (CLAUDE.md section 2, billing flow step 5) and what each changes on the user.
export const HANDLED_EVENTS = new Set([
  "checkout.session.completed",
  "customer.subscription.created",
  "customer.subscription.updated",
  "customer.subscription.deleted",
  "invoice.payment_failed",
]);

export type StripeEvent = { id: string; type: string; data: { object: Record<string, unknown> } };

// Which user an event is about, and the fields to set. The user is found by Clerk id (sent to Stripe as
// client_reference_id and subscription metadata when Checkout starts) or, failing that, by Stripe customer id.
export type UserUpdate = {
  authProviderId: string | null;
  customerId: string | null;
  set: {
    plan?: "free" | "pro";
    subscription_status?: string;
    stripe_customer_id?: string;
    stripe_subscription_id?: string;
    price_interval?: "monthly" | "annual" | null;
    current_period_end?: string | null;
  };
};

const str = (v: unknown): string | null => (typeof v === "string" && v ? v : null);
const idOf = (v: unknown): string | null => str(v) ?? str((v as { id?: unknown } | null)?.id);

export function userUpdateFromEvent(event: StripeEvent): UserUpdate | null {
  const o = event.data.object;
  switch (event.type) {
    case "checkout.session.completed": {
      if (o.mode !== "subscription") return null;
      const customer = idOf(o.customer);
      const subscription = idOf(o.subscription);
      return {
        authProviderId: str(o.client_reference_id),
        customerId: customer,
        set: {
          plan: "pro",
          subscription_status: "active",
          ...(customer ? { stripe_customer_id: customer } : {}),
          ...(subscription ? { stripe_subscription_id: subscription } : {}),
        },
      };
    }
    case "customer.subscription.created":
    case "customer.subscription.updated":
    case "customer.subscription.deleted": {
      const items = ((o.items as { data?: unknown[] } | undefined)?.data ?? []) as Record<string, unknown>[];
      const item = items[0] ?? {};
      // Newer Stripe API versions keep the period end on the subscription item, older ones on the subscription.
      const periodEnd = Number(item.current_period_end ?? o.current_period_end);
      const interval = ((item.price as { recurring?: { interval?: string } } | undefined)?.recurring?.interval) ?? null;
      const deleted = event.type === "customer.subscription.deleted";
      return {
        authProviderId: str((o.metadata as Record<string, unknown> | undefined)?.auth_provider_id),
        customerId: idOf(o.customer),
        set: {
          plan: deleted ? "free" : "pro",
          subscription_status: deleted ? "canceled" : str(o.status) ?? "incomplete",
          stripe_subscription_id: str(o.id) ?? undefined,
          ...(idOf(o.customer) ? { stripe_customer_id: idOf(o.customer)! } : {}),
          price_interval: interval === "year" ? "annual" : interval === "month" ? "monthly" : null,
          current_period_end: Number.isFinite(periodEnd) && periodEnd > 0 ? new Date(periodEnd * 1000).toISOString() : null,
        },
      };
    }
    case "invoice.payment_failed":
      // Stripe retries the card; the subscription's own update event will follow. Mark it so the account page can
      // ask the user to update the card. Access continues until the paid period ends (see access.ts).
      return { authProviderId: null, customerId: idOf(o.customer), set: { subscription_status: "past_due" } };
    default:
      return null;
  }
}

// Form encoding for Stripe's API, which takes nested keys like line_items[0][price].
export function formEncode(params: Record<string, string | number | boolean | undefined | null>): string {
  return Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null && v !== "")
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
    .join("&");
}

export async function stripeRequest<T>(secretKey: string, path: string, params: Record<string, string | number | boolean | undefined | null>): Promise<T> {
  const res = await fetch(`https://api.stripe.com/v1/${path}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${secretKey}`, "Content-Type": "application/x-www-form-urlencoded" },
    body: formEncode(params),
  });
  const json = (await res.json()) as T & { error?: { message?: string } };
  if (!res.ok) throw new Error(`Stripe ${path}: ${json.error?.message ?? res.status}`);
  return json;
}
