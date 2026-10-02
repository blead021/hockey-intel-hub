import Link from "next/link";
import { SectionTitle, Unavailable } from "@/components/ui";
import { season as seasonLabel } from "@/lib/format";
import type { PlayStyle } from "@/lib/queries";

const GROUP_NAMES = { C: "centers", W: "wingers", D: "defensemen" } as const;

function ordinal(n: number): string {
  const s = ["th", "st", "nd", "rd"];
  const v = n % 100;
  return `${n}${s[(v - 20) % 10] || s[v] || s[0]}`;
}

export function PlayStyleSection({ style }: { style: PlayStyle | undefined }) {
  if (!style) {
    return (
      <>
        <SectionTitle>Play style</SectionTitle>
        <Unavailable>Play style appears after 100 minutes of ice time in a season.</Unavailable>
      </>
    );
  }
  const group = GROUP_NAMES[style.group];
  const ranked = style.traits.filter((t) => t.pctile != null).map((t) => ({ ...t, rank: Math.round((t.pctile as number) * 100) }));
  // Without the Claude write-up, strengths and watch-outs state the numbers plainly.
  const strengths = style.writeup?.strengths.length
    ? style.writeup.strengths
    : ranked.filter((t) => t.rank >= 70).sort((a, b) => b.rank - a.rank).slice(0, 3)
        .map((t) => `${t.key}: ${ordinal(t.rank)} percentile among ${group}${t.estimate ? " (estimate)" : ""}.`);
  const watchOuts = style.writeup?.watch_outs.length
    ? style.writeup.watch_outs
    : ranked.filter((t) => t.rank <= 30).sort((a, b) => a.rank - b.rank).slice(0, 2)
        .map((t) => `${t.key}: ${ordinal(t.rank)} percentile among ${group}${t.estimate ? " (estimate)" : ""}.`);
  const share = (n: number) => (style.shots.total ? Math.round((n / style.shots.total) * 100) : 0);

  return (
    <>
      <SectionTitle note={`Trait percentiles vs. NHL ${group} · ${seasonLabel(style.season_id)}`}>
        <span className="inline-flex flex-wrap items-center gap-3">
          Play style
          {style.writeup?.archetype && (
            <span className="rounded-full bg-positive-soft px-3 py-1 font-sans text-sm font-semibold normal-case tracking-normal text-positive">
              {style.writeup.archetype}
            </span>
          )}
        </span>
      </SectionTitle>
      <div className="rounded-lg border border-border bg-surface p-4">
        {style.writeup?.summary && <p className="mb-3">{style.writeup.summary}</p>}
        {style.writeup && style.writeup.tags.length > 0 && (
          <div className="mb-4 flex flex-wrap gap-2">
            {style.writeup.tags.map((tag) => (
              <span key={tag} className="rounded border border-border px-2 py-1 text-xs font-semibold">
                {tag}
              </span>
            ))}
          </div>
        )}
        <div className="grid gap-6 md:grid-cols-2">
          <dl className="space-y-2">
            {style.traits.map((t) => {
              const rank = t.pctile == null ? null : Math.round(t.pctile * 100);
              return (
                <div key={t.key} className="grid grid-cols-[8.5rem_1fr_2rem] items-center gap-3">
                  <dt className="text-sm font-semibold">
                    {t.key}
                    {t.estimate && <span className="ml-1 text-xs font-normal text-muted">(est.)</span>}
                  </dt>
                  <dd className="h-2 overflow-hidden rounded-full bg-border-soft" aria-hidden>
                    {rank != null && (
                      <div className={`h-full ${rank >= 50 ? "bg-positive" : "bg-negative"}`} style={{ width: `${Math.max(rank, 2)}%` }} />
                    )}
                  </dd>
                  <dd className="text-right font-mono text-xs text-muted">{rank ?? "—"}</dd>
                </div>
              );
            })}
          </dl>
          <div className="space-y-4">
            <div>
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">Where he shoots from</p>
              {style.shots.total === 0 ? (
                <p className="text-sm text-muted">No unblocked shots yet.</p>
              ) : (
                <>
                  <div className="flex h-3 overflow-hidden rounded-full" aria-hidden>
                    <div className="bg-positive" style={{ width: `${share(style.shots.slot)}%` }} />
                    <div className="bg-positive/60" style={{ width: `${share(style.shots.mid)}%` }} />
                    <div className="bg-positive/30" style={{ width: `${share(style.shots.perimeter)}%` }} />
                  </div>
                  <p className="mt-2 text-xs text-muted">
                    Slot {share(style.shots.slot)}% · Mid-range {share(style.shots.mid)}% · Perimeter {share(style.shots.perimeter)}%
                    <span className="ml-1">({style.shots.total} unblocked shots)</span>
                  </p>
                </>
              )}
            </div>
            {strengths.length > 0 && (
              <div>
                <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-positive">Strengths</p>
                <ul className="space-y-1 text-sm">
                  {strengths.map((s) => <li key={s} className="border-l-2 border-positive pl-3">{s}</li>)}
                </ul>
              </div>
            )}
            {watchOuts.length > 0 && (
              <div>
                <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-negative">Watch-outs</p>
                <ul className="space-y-1 text-sm">
                  {watchOuts.map((s) => <li key={s} className="border-l-2 border-negative pl-3">{s}</li>)}
                </ul>
              </div>
            )}
            {style.similar.length > 0 && (
              <p className="text-sm">
                <span className="font-semibold">Similar style: </span>
                {style.similar.map((p, i) => (
                  <span key={p.id}>
                    {i > 0 && ", "}
                    <Link href={`/player/${p.id}`} className="hover:underline">{p.name}</Link>
                    {p.team ? ` (${p.team})` : ""}
                  </span>
                ))}
              </p>
            )}
          </div>
        </div>
        <p className="mt-4 text-xs text-muted">
          Built from play-by-play, shift data, and NHL EDGE tracking. Zone entries is an estimate (rush chances while he is
          on the ice) until tracking data is added.
          {!style.writeup && " A written scouting summary appears once Claude play-style writing is switched on."}
        </p>
      </div>
    </>
  );
}
