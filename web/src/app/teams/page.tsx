import Link from "next/link";
import { connection } from "next/server";
import { PageTitle } from "@/components/ui";
import { withDb } from "@/lib/db";
import { getTeams } from "@/lib/queries";

export const metadata = { title: "Teams" };

export default async function TeamsPage() {
  await connection();
  const teams = await withDb((sql) => getTeams(sql));
  const divisions = new Map<string, typeof teams>();
  for (const t of teams) {
    const key = `${t.conference ?? ""}|${t.division ?? "Other"}`;
    divisions.set(key, [...(divisions.get(key) ?? []), t]);
  }

  return (
    <main className="mx-auto max-w-7xl px-4 py-8">
      <PageTitle title="Teams" />
      <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
        {[...divisions.entries()].sort().map(([key, list]) => {
          const [conference, division] = key.split("|");
          return (
            <section key={key}>
              <h2 className="font-heading text-lg font-semibold uppercase tracking-tight">{division}</h2>
              <p className="mb-2 text-xs uppercase tracking-wide text-muted">{conference}</p>
              <ul className="overflow-hidden rounded-lg border border-border bg-surface">
                {list.map((t) => (
                  <li key={t.id} className="border-b border-border-soft last:border-b-0">
                    <Link href={`/team/${t.abbrev}`} className="flex items-center justify-between px-3 py-2 hover:bg-bg">
                      <span>{t.name}</span>
                      <span className="font-mono text-xs text-muted">{t.abbrev}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          );
        })}
      </div>
    </main>
  );
}
