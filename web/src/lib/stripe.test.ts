import assert from "node:assert/strict";
import { test } from "node:test";
import { formEncode, hmacHex, userUpdateFromEvent, verifyStripeSignature } from "./stripe.ts";

const SECRET = "whsec_test_secret";
const BODY = JSON.stringify({ id: "evt_1", type: "customer.subscription.updated" });

test("a correctly signed webhook is accepted; tampered, stale, or unsigned ones are not", async () => {
  const t = 1_790_000_000;
  const good = `t=${t},v1=${await hmacHex(SECRET, `${t}.${BODY}`)}`;
  assert.equal(await verifyStripeSignature(BODY, good, SECRET, t + 10), true);
  assert.equal(await verifyStripeSignature(BODY + " ", good, SECRET, t + 10), false);          // body changed
  assert.equal(await verifyStripeSignature(BODY, good, "whsec_other", t + 10), false);         // wrong secret
  assert.equal(await verifyStripeSignature(BODY, good, SECRET, t + 3600), false);              // replayed an hour later
  assert.equal(await verifyStripeSignature(BODY, null, SECRET, t), false);
  assert.equal(await verifyStripeSignature(BODY, `t=${t},v1=deadbeef,v1=${await hmacHex(SECRET, `${t}.${BODY}`)}`, SECRET, t), true);
});

test("checkout completed links the Stripe customer and turns on Pro", () => {
  const u = userUpdateFromEvent({ id: "evt", type: "checkout.session.completed", data: { object: {
    mode: "subscription", client_reference_id: "user_clerk_1", customer: "cus_1", subscription: "sub_1" } } });
  assert.deepEqual(u, { authProviderId: "user_clerk_1", customerId: "cus_1", set: {
    plan: "pro", subscription_status: "active", stripe_customer_id: "cus_1", stripe_subscription_id: "sub_1" } });
  // One-time payments are not subscriptions.
  assert.equal(userUpdateFromEvent({ id: "e", type: "checkout.session.completed", data: { object: { mode: "payment" } } }), null);
});

test("subscription updates carry status, interval, and period end (new and old Stripe API shapes)", () => {
  const newer = userUpdateFromEvent({ id: "e", type: "customer.subscription.updated", data: { object: {
    id: "sub_1", customer: "cus_1", status: "active", metadata: { auth_provider_id: "user_clerk_1" },
    items: { data: [{ current_period_end: 1_822_000_000, price: { recurring: { interval: "year" } } }] } } } });
  assert.equal(newer!.set.price_interval, "annual");
  assert.equal(newer!.set.current_period_end, new Date(1_822_000_000 * 1000).toISOString());
  assert.equal(newer!.authProviderId, "user_clerk_1");
  const older = userUpdateFromEvent({ id: "e", type: "customer.subscription.updated", data: { object: {
    id: "sub_1", customer: { id: "cus_1" }, status: "past_due", current_period_end: 1_800_000_000,
    items: { data: [{ price: { recurring: { interval: "month" } } }] } } } });
  assert.equal(older!.set.subscription_status, "past_due");
  assert.equal(older!.set.price_interval, "monthly");
  assert.equal(older!.customerId, "cus_1");
});

test("a deleted subscription ends Pro; a failed payment marks the account past due", () => {
  const del = userUpdateFromEvent({ id: "e", type: "customer.subscription.deleted", data: { object: { id: "sub_1", customer: "cus_1", status: "canceled" } } });
  assert.equal(del!.set.plan, "free");
  assert.equal(del!.set.subscription_status, "canceled");
  const failed = userUpdateFromEvent({ id: "e", type: "invoice.payment_failed", data: { object: { customer: "cus_1" } } });
  assert.deepEqual(failed, { authProviderId: null, customerId: "cus_1", set: { subscription_status: "past_due" } });
  assert.equal(userUpdateFromEvent({ id: "e", type: "charge.refunded", data: { object: {} } }), null);
});

test("form encoding for Stripe's API", () => {
  assert.equal(formEncode({ mode: "subscription", "line_items[0][price]": "price_1", empty: "", skip: undefined }),
    "mode=subscription&line_items%5B0%5D%5Bprice%5D=price_1");
});
