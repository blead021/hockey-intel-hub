import Link from "next/link";
import { connection } from "next/server";
import { PageTitle, Unavailable } from "@/components/ui";
import { withDb } from "@/lib/db";
import { money, season } from "@/lib/format";
import { getContractEvents, getTeams } from "@/lib/queries";

export const metadata = { title: "Contract changes | Hockey Intel Hub" };

const OUTCOMES: Record<string, string> = {
  applied: "Updated",
  no_change: "Already up to date",
  skipped_unconfirmed: "Not applied: not confirmed yet",
  skipped_unmatched: "Not applied: player or team not found",
  skipped_type: "Not applied: no contract change",
};

const FIELDS: Record<string, string> = {
  team_id: "Team",
  cap_hit: "Cap hit",
  aav: "AAV",
  start_season: "First season",
  end_season: "Last season",
  expiry_status: "Expiry",
  clause: "Clause",
  no_trade_list_size: "No-trade list",
  retained_pct: "Retained %",
  retained_by: "Retained by",
  status: "Status",
  contract_type: "Type",
  player_name: "Player",
};

export default async function ContractChangesPage() {
  await connection();
  const [events, teams] = await withDb(async (sql) => Promise.all([getContractEvents(sql), getTeams(sql)]));
  const teamName = new Map(teams.map((t) => [String(t.id), t.abbrev]));

  function show(field: string, value: string | null): string {
    if (value == null) return "unknown";
    if (field === "team_id" || field === "retained_by") return teamName.get(value) ?? value;
    if (field === "cap_hit" || field === "aav") return money(Number(value));
    if (field === "start_season" || field === "end_season") return season(Number(value));
    return value.replaceAll("_", " ");
  }

  return (
    <main className="mx-auto max-w-4xl px-4 py-8">
      <PageTitle eyebrow="Last 30 days" title="Contract changes">
        <p className="mt-2 text-sm text-muted">
          Updated daily from team announcements and news headlines. Every change lists its sources. Details the news does
          not mention keep the value on file.
        </p>
      </PageTitle>
      {events.length === 0 ? (
        <Unavailable>No contract news yet.</Unavailable>
      ) : (
        <ul className="space-y-3">
          {events.map((e) => (
            <li key={e.id} className="rounded-lg border border-border bg-surface p-4">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <p className="font-medium">
                  {e.player_id ? <Link href={`/player/${e.player_id}`} className="hover:underline">{e.player_name}</Link> : e.player_name}
                  <span className="ml-2 text-sm text-muted">{e.event_type.replaceAll("_", " ")}</span>
                </p>
                <p className="font-mono text-xs text-muted">{e.created_at} UTC</p>
              </div>
              <p className={`mt-1 text-sm ${e.outcome === "applied" ? "font-medium text-positive" : "text-muted"}`}>
                {OUTCOMES[e.outcome] ?? e.outcome}
                {e.outcome_note ? ` (${e.outcome_note})` : ""}
              </p>
              {e.changes.length > 0 && (
                <ul className="mt-2 space-y-1 text-sm">
                  {e.changes.map((c, i) => (
                    <li key={i}>
                      <span className="text-muted">{FIELDS[c.field] ?? c.field}:</span>{" "}
                      <span className="font-mono">{show(c.field, c.old)}</span> → <span className="font-mono">{show(c.field, c.new)}</span>
                    </li>
                  ))}
                </ul>
              )}
              {e.source_urls.length > 0 && (
                <p className="mt-2 flex flex-wrap gap-3 text-xs">
                  {e.source_urls.map((url, i) => (
                    <a key={i} href={url} className="text-positive underline" rel="noopener noreferrer" target="_blank">
                      Source {i + 1}
                    </a>
                  ))}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
