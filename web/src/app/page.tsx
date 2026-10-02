// Placeholder until the landing page is built in Phase 6.
import { SITE_NAME } from "@/lib/site";

export default function Home() {
  return (
    <main className="mx-auto max-w-2xl px-4 py-16">
      <h1 className="text-5xl font-bold uppercase tracking-tight">{SITE_NAME}</h1>
      <p className="mt-4 text-lg text-muted">
        Front office tools for hockey fans: stats, analytics, sentiment, trade chatter, and contracts.
      </p>
      <div className="mt-8 rounded-lg border border-border bg-surface p-4">
        <p className="text-sm text-muted">Setup check</p>
        <a className="font-mono text-positive underline" href="/api/health">
          /api/health
        </a>
      </div>
    </main>
  );
}
