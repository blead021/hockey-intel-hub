import Link from "next/link";
import { PageTitle } from "@/components/ui";

// A paid page for a visitor without access (CLAUDE.md section 2): a blurred preview and an upgrade prompt. The
// preview is made-up placeholder rows, never real data, so nothing paid reaches the browser.
export function Locked({ eyebrow, title, what }: { eyebrow?: string; title: string; what: string }) {
  const rows = Array.from({ length: 8 }, (_, i) => i);
  return (
    <main className="mx-auto max-w-7xl px-4 py-8">
      <PageTitle eyebrow={eyebrow} title={title} />
      <div className="relative overflow-hidden rounded-lg border border-border bg-surface">
        <div aria-hidden className="pointer-events-none select-none p-5 blur-sm">
          {rows.map((i) => (
            <div key={i} className="flex items-center gap-4 border-b border-border-soft py-3">
              <div className="h-4 w-40 rounded bg-border" />
              <div className="h-4 w-16 rounded bg-border-soft" />
              <div className="h-4 w-24 rounded bg-positive-soft" />
              <div className="ml-auto h-4 w-20 rounded bg-border" />
            </div>
          ))}
        </div>
        <div className="absolute inset-0 flex items-center justify-center p-4">
          <div className="max-w-md rounded-lg border border-border bg-surface p-6 text-center shadow-lg">
            <p className="text-xs font-semibold uppercase tracking-widest text-positive">PuckSleuth Pro</p>
            <h2 className="mt-1 font-heading text-3xl font-semibold uppercase tracking-tight">Unlock {what}</h2>
            <p className="mt-2 text-sm text-muted">
              Pro includes every team and player, Trade Targets, the Trade Builder, and the Rumor Tracker.
            </p>
            <Link href="/pricing" className="mt-4 inline-block rounded-md bg-ink px-5 py-2 font-semibold text-surface hover:bg-ink/90">
              See plans
            </Link>
          </div>
        </div>
      </div>
    </main>
  );
}
