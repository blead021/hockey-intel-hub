import { withDb } from "@/lib/db";
import { env, siteUrl } from "@/lib/env";
import { currentUser } from "@/lib/session";
import { stripeRequest } from "@/lib/stripe";

// "Manage subscription" (CLAUDE.md section 2, billing flow step 4): opens the Stripe Customer Portal, where the
// user changes cards or cancels.
export async function POST(request: Request) {
  const site = await siteUrl(request);
  const key = await env("STRIPE_SECRET_KEY");
  if (!key) return Response.redirect(`${site}/account?status=unavailable`, 303);
  const user = await withDb((sql) => currentUser(sql));
  if (!user?.stripe_customer_id) return Response.redirect(`${site}/pricing`, 303);
  const portal = await stripeRequest<{ url: string }>(key, "billing_portal/sessions", {
    customer: user.stripe_customer_id,
    return_url: `${site}/account`,
  });
  return Response.redirect(portal.url, 303);
}
