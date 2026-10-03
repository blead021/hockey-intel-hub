import Link from "next/link";
import { connection } from "next/server";
import { PageTitle, Unavailable } from "@/components/ui";
import { withDb } from "@/lib/db";
import { getTeams } from "@/lib/queries";
import { currentUser } from "@/lib/session";

export const metadata = { title: "Account" };

const STATUS: Record<string, string> = {
  welcome: "Welcome to PuckSleuth Pro. Your subscription is active.",
  unavailable: "Billing is not set up yet.",
};

// Account (CLAUDE.md section 2): plan, manage billing, favorite team, email preferences. Sign-in arrives with
// Clerk; until then everyone is signed out and the page says so.
export default async function AccountPage({ searchParams }: PageProps<"/account">) {
  await connection();
  const status = (await searchParams).status;
  const { user, teams } = await withDb(async (sql) => ({ user: await currentUser(sql), teams: await getTeams(sql) }));
  const message = typeof status === "string" ? STATUS[status] : undefined;

  if (!user) {
    return (
      <main className="mx-auto max-w-3xl px-4 py-8">
        <PageTitle eyebrow="Your account" title="Account" />
        <Unavailable>
          Accounts open soon. You will be able to sign up with email or Google, pick your favorite team, and manage your
          subscription here. Until then every page is free to explore.
        </Unavailable>
        <p className="mt-4 text-sm"><Link href="/pricing" className="underline">See plans</Link></p>
      </main>
    );
  }

  const team = teams.find((t) => t.id === user.favorite_team_id);
  const pro = user.plan === "pro";
  const renews = user.current_period_end ? new Date(user.current_period_end).toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" }) : null;
  return (
    <main className="mx-auto max-w-3xl space-y-6 px-4 py-8">
      <PageTitle eyebrow="Your account" title="Account">
        {user.email && <p className="mt-1 text-muted">{user.email}</p>}
      </PageTitle>
      {message && <p className="rounded-lg border border-border bg-positive-soft p-3 text-sm text-positive">{message}</p>}
      {user.subscription_status === "past_due" && (
        <p className="rounded-lg border border-border bg-negative-soft p-3 text-sm text-negative">
          Your last payment did not go through. Update your card under Manage subscription to keep Pro.
        </p>
      )}

      <section className="rounded-lg border border-border bg-surface p-5">
        <h2 className="font-heading text-2xl font-semibold uppercase tracking-tight">Plan</h2>
        <p className="mt-2 text-lg font-semibold">{pro ? `Pro (${user.price_interval ?? "subscription"})` : "Free"}</p>
        {pro && renews && (
          <p className="text-sm text-muted">{user.subscription_status === "canceled" ? `Pro until ${renews}` : `Renews ${renews}`}</p>
        )}
        <div className="mt-4 flex flex-wrap gap-3">
          {user.stripe_customer_id && (
            <form action="/api/stripe/portal" method="post">
              <button type="submit" className="rounded-md border border-border px-4 py-2 font-semibold hover:border-ink">Manage subscription</button>
            </form>
          )}
          {!pro && <Link href="/pricing" className="rounded-md bg-ink px-4 py-2 font-semibold text-surface">Upgrade to Pro</Link>}
        </div>
      </section>

      <section className="rounded-lg border border-border bg-surface p-5">
        <h2 className="font-heading text-2xl font-semibold uppercase tracking-tight">My Team</h2>
        <p className="mt-2">{team ? team.name : "No favorite team picked yet."}</p>
        {team && <Link href={`/team/${team.abbrev}`} className="mt-2 inline-block text-sm underline">Go to {team.name}</Link>}
      </section>

      <section className="rounded-lg border border-border bg-surface p-5">
        <h2 className="font-heading text-2xl font-semibold uppercase tracking-tight">Email</h2>
        <p className="mt-2 text-sm text-muted">The weekly email preferences arrive with the newsletter.</p>
      </section>
    </main>
  );
}
