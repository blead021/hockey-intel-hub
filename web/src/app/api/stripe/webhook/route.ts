import { withDb } from "@/lib/db";
import { env } from "@/lib/env";
import { HANDLED_EVENTS, type StripeEvent, userUpdateFromEvent, verifyStripeSignature } from "@/lib/stripe";

// Stripe webhook (CLAUDE.md section 2, billing flow step 3). Verifies the signature, records the event id so a
// retried delivery is applied once, and updates the user's plan and subscription fields.
export async function POST(request: Request) {
  const secret = await env("STRIPE_WEBHOOK_SECRET");
  if (!secret) return Response.json({ error: "billing is not set up yet" }, { status: 503 });

  const body = await request.text();
  if (!(await verifyStripeSignature(body, request.headers.get("stripe-signature"), secret))) {
    return Response.json({ error: "invalid signature" }, { status: 400 });
  }
  const event = JSON.parse(body) as StripeEvent;
  if (!HANDLED_EVENTS.has(event.type)) return Response.json({ received: true, handled: false });

  const result = await withDb((sql) =>
    sql.begin(async (tx) => {
      const [fresh] = await tx`
        insert into stripe_events (event_id, type) values (${event.id}, ${event.type})
        on conflict (event_id) do nothing returning event_id`;
      if (!fresh) return "duplicate";
      const update = userUpdateFromEvent(event);
      if (!update) return "ignored";
      const set = Object.fromEntries(Object.entries(update.set).filter(([, v]) => v !== undefined));
      const keys = Object.keys(set);
      if (!keys.length) return "ignored";
      const rows = await tx`
        update users set ${tx(set, keys)}, updated_at = now()
        where (${update.authProviderId}::text is not null and auth_provider_id = ${update.authProviderId})
           or (${update.customerId}::text is not null and stripe_customer_id = ${update.customerId})
        returning id`;
      return rows.length ? "applied" : "no_user";
    }),
  );
  if (result === "no_user") console.warn(`stripe webhook ${event.id} (${event.type}): no matching user`);
  return Response.json({ received: true, result });
}
