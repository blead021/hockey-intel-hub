import { withDb } from "@/lib/db";
import { env, siteUrl } from "@/lib/env";
import { currentUser } from "@/lib/session";
import { stripeRequest } from "@/lib/stripe";

// Upgrade button (CLAUDE.md section 2, billing flow step 2): the pricing page's form posts the chosen interval here,
// and the visitor is sent to Stripe Checkout. Prices come from STRIPE_PRICE_ID_MONTHLY / _ANNUAL, never hardcoded.
export async function POST(request: Request) {
  const site = await siteUrl(request);
  const form = await request.formData();
  const interval = form.get("interval") === "monthly" ? "monthly" : "annual";
  const [key, price, tax] = await Promise.all([
    env("STRIPE_SECRET_KEY"),
    env(interval === "monthly" ? "STRIPE_PRICE_ID_MONTHLY" : "STRIPE_PRICE_ID_ANNUAL"),
    env("STRIPE_TAX"),
  ]);
  if (!key || !price) return Response.redirect(`${site}/pricing?status=unavailable`, 303);

  const user = await withDb((sql) => currentUser(sql));
  if (!user) return Response.redirect(`${site}/pricing?status=sign-in`, 303);

  const session = await stripeRequest<{ url: string }>(key, "checkout/sessions", {
    mode: "subscription",
    "line_items[0][price]": price,
    "line_items[0][quantity]": 1,
    client_reference_id: user.auth_provider_id,
    customer: user.stripe_customer_id ?? undefined,
    customer_email: user.stripe_customer_id ? undefined : user.email ?? undefined,
    "subscription_data[metadata][auth_provider_id]": user.auth_provider_id,
    allow_promotion_codes: true,
    "automatic_tax[enabled]": tax === "on" ? true : undefined,
    success_url: `${site}/account?status=welcome`,
    cancel_url: `${site}/pricing`,
  });
  return Response.redirect(session.url, 303);
}
