// Gating tests (CLAUDE.md section 9): free users cannot reach paid data. Run with `npm test`.
import assert from "node:assert/strict";
import { test } from "node:test";
import { type AccessUser, can, canViewPlayer, canViewTeam, getAccess, isPro } from "./access.ts";

const NOW = new Date("2026-10-03T12:00:00Z");
const free: AccessUser = { plan: "free", subscription_status: null, current_period_end: null, favorite_team_id: 6 };
const pro: AccessUser = { plan: "pro", subscription_status: "active", current_period_end: "2027-10-03T00:00:00Z", favorite_team_id: 6 };

test("a free user sees the League page and My Team, nothing paid", () => {
  const a = getAccess(free, { gating: true, now: NOW });
  assert.equal(a.plan, "free");
  assert.ok(can(a, "league") && can(a, "my_team") && can(a, "weekly_email"));
  for (const f of ["all_teams", "all_players", "trade_targets", "trade_builder", "rumors", "watchlists", "alerts"] as const) {
    assert.equal(can(a, f), false, f);
  }
  assert.ok(canViewTeam(a, 6));
  assert.equal(canViewTeam(a, 10), false);
  assert.ok(canViewPlayer(a, 6));
  assert.equal(canViewPlayer(a, 10), false);
  assert.equal(canViewPlayer(a, null), false);
});

test("a signed-out visitor gets the free pages only, with no team of his own", () => {
  const a = getAccess(null, { gating: true, now: NOW });
  assert.equal(a.signedIn, false);
  assert.ok(can(a, "league"));
  assert.equal(canViewTeam(a, 6), false);
  assert.equal(can(a, "trade_builder"), false);
});

test("Pro unlocks everything", () => {
  const a = getAccess(pro, { gating: true, now: NOW });
  assert.equal(a.plan, "pro");
  assert.ok(can(a, "trade_builder") && can(a, "rumors") && canViewTeam(a, 10) && canViewPlayer(a, 22));
});

test("a canceled subscription keeps Pro until the paid period ends, then loses it", () => {
  const canceled = { ...pro!, subscription_status: "canceled", current_period_end: "2026-10-10T00:00:00Z" };
  assert.ok(isPro(canceled, NOW));
  assert.equal(isPro(canceled, new Date("2026-10-11T00:00:00Z")), false);
  assert.equal(can(getAccess(canceled, { gating: true, now: new Date("2026-10-11T00:00:00Z") }), "trade_builder"), false);
});

test("plan pro without a paying status is not Pro", () => {
  assert.equal(isPro({ ...pro!, subscription_status: "incomplete" }, NOW), false);
  assert.equal(isPro({ ...pro!, subscription_status: null }, NOW), false);
});

test("with gating off (before accounts launch) everyone sees everything", () => {
  const a = getAccess(null, { gating: false, now: NOW });
  assert.equal(a.gating, false);
  assert.ok(can(a, "trade_builder") && canViewTeam(a, 10) && canViewPlayer(a, 22));
});
