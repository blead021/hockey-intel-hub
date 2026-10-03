import Link from "next/link";
import { connection } from "next/server";
import { PageTitle } from "@/components/ui";
import { FREE_INCLUDES, PRO_INCLUDES, priceLabels } from "@/lib/plans";

export const metadata = { title: "Pricing" };

const MESSAGES: Record<string, string> = {
  unavailable: "Subscriptions open soon. Everything is free to explore until then.",
  "sign-in": "Create a free account first, then upgrade from here.",
};

// Pricing (CLAUDE.md section 2). Annual is the default choice: low prices lose a large share to per-charge card fees.
export default async function PricingPage({ searchParams }: PageProps<"/pricing">) {
  await connection();
  const status = (await searchParams).status;
  const { annual, monthly, billingReady } = await priceLabels();
  const message = typeof status === "string" ? MESSAGES[status] : undefined;

  return (
    <main className="mx-auto max-w-5xl px-4 py-8">
      <PageTitle eyebrow="Plans" title="Pricing">
        <p className="mt-2 max-w-2xl text-muted">Start free with the league overview and your favorite team. Go Pro for every team, every player, and the trade tools.</p>
      </PageTitle>
      {message && <p className="mb-6 rounded-lg border border-border bg-positive-soft p-3 text-sm text-positive">{message}</p>}

      <div className="grid gap-6 md:grid-cols-2">
        <section className="rounded-lg border border-border bg-surface p-6">
          <h2 className="font-heading text-3xl font-semibold uppercase tracking-tight">Free</h2>
          <p className="mt-1 font-mono text-2xl">$0</p>
          <ul className="mt-4 space-y-2 text-sm">
            {FREE_INCLUDES.map((f) => <li key={f} className="flex gap-2"><span className="text-positive">✓</span>{f}</li>)}
          </ul>
          <Link href="/league" className="mt-6 inline-block rounded-md border border-border px-5 py-2 font-semibold hover:border-ink">
            Start exploring
          </Link>
        </section>

        <section className="rounded-lg border-2 border-ink bg-surface p-6">
          <div className="flex items-baseline justify-between gap-2">
            <h2 className="font-heading text-3xl font-semibold uppercase tracking-tight">Pro</h2>
            <span className="rounded bg-positive-soft px-2 py-0.5 text-xs font-semibold uppercase text-positive">Best value: annual</span>
          </div>
          <ul className="mt-4 space-y-2 text-sm">
            <li className="flex gap-2"><span className="text-positive">✓</span>Everything in Free</li>
            {PRO_INCLUDES.map((f) => <li key={f} className="flex gap-2"><span className="text-positive">✓</span>{f}</li>)}
          </ul>
          <form action="/api/stripe/checkout" method="post" className="mt-6 space-y-3">
            <fieldset className="space-y-2">
              <legend className="sr-only">Billing</legend>
              <label className="flex cursor-pointer items-center gap-3 rounded-md border border-border p-3 has-[:checked]:border-ink">
                <input type="radio" name="interval" value="annual" defaultChecked />
                <span className="font-semibold">Annual</span>
                <span className="ml-auto font-mono text-sm">{annual ?? "price coming soon"}</span>
              </label>
              <label className="flex cursor-pointer items-center gap-3 rounded-md border border-border p-3 has-[:checked]:border-ink">
                <input type="radio" name="interval" value="monthly" />
                <span className="font-semibold">Monthly</span>
                <span className="ml-auto font-mono text-sm">{monthly ?? "price coming soon"}</span>
              </label>
            </fieldset>
            <button
              type="submit"
              disabled={!billingReady}
              className="w-full rounded-md bg-ink px-5 py-2.5 font-semibold text-surface hover:bg-ink/90 disabled:cursor-not-allowed disabled:bg-muted"
            >
              {billingReady ? "Upgrade to Pro" : "Subscriptions open soon"}
            </button>
            <p className="text-xs text-muted">Cancel anytime from your account page. You keep Pro until the end of the period you paid for.</p>
          </form>
        </section>
      </div>
    </main>
  );
}
