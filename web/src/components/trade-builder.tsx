"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import type { AgePoint, BuilderPick, BuilderPlayer, BuilderTeam } from "@/lib/queries";

const NEED_LABELS: Record<string, string> = {
  goal_scoring: "Goal scoring", playmaking: "Playmaking", physicality: "Physicality", defense_5v5: "5v5 defense",
  power_play: "Power play", penalty_kill: "Penalty kill", goaltending: "Goaltending",
};
const MAX_RETAINED_SLOTS = 3;
const MAX_ROSTER = 23;
const MAX_CONTRACTS = 50;
// Rough value of a draft pick in projected WAR per season once developed, by round (a planning guide only).
const PICK_WAR = { 1: 1.0, 2: 0.4, 3: 0.2, 4: 0.1, 5: 0.05, 6: 0.03, 7: 0.02 } as Record<number, number>;

export type Suggestion = {
  id: number; name: string; team: string; position: string; age: number | null; cap_hit: number; years: number;
  war_proj: number | null; category: string; pctile: number; team_status: string | null; chatter: number;
};

type Deal = { a: string; b: string; in: number[]; out: number[]; pin: number[]; pout: number[]; r: Record<number, number> };

function money(v: number | null | undefined): string {
  if (v == null) return "—";
  const a = Math.abs(v);
  const s = a >= 1_000_000 ? `$${(a / 1_000_000).toFixed(a % 1_000_000 === 0 ? 0 : 3).replace(/0+$/, "").replace(/\.$/, "")}M` : `$${Math.round(a / 1000)}K`;
  return v < 0 ? `−${s}` : s;
}

const charged = (p: BuilderPlayer) => p.cap_hit * (1 - p.retained_pct / 100);
const pickLabel = (k: BuilderPick) => `${k.draft_year} ${["", "1st", "2nd", "3rd", "4th", "5th", "6th", "7th"][k.round]}-round pick`;
const curveGroup = (pos: string) => (pos === "G" ? "G" : pos === "D" ? "D" : "F");

export function TradeBuilder(props: {
  teams: { abbrev: string; name: string }[];
  teamA: BuilderTeam | undefined;
  teamB: BuilderTeam | undefined;
  curves: Record<"F" | "D" | "G", AgePoint[]>;
  suggestions: Suggestion[];
  season: number;
  initial: Deal;
}) {
  const { teams, teamA, teamB, curves, suggestions } = props;
  const router = useRouter();
  const [deal, setDeal] = useState<Deal>(props.initial);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [copied, setCopied] = useState(false);

  const href = (d: Deal) => {
    const q = new URLSearchParams();
    if (d.a) q.set("a", d.a);
    if (d.b) q.set("b", d.b);
    if (d.in.length) q.set("in", d.in.join(","));
    if (d.out.length) q.set("out", d.out.join(","));
    if (d.pin.length) q.set("pin", d.pin.join(","));
    if (d.pout.length) q.set("pout", d.pout.join(","));
    const r = Object.entries(d.r).filter(([, v]) => v > 0).map(([k, v]) => `${k}:${v}`);
    if (r.length) q.set("r", r.join(","));
    return `/trade-builder?${q.toString()}`;
  };
  // Team changes need new data from the server; item changes only update the address so the deal can be shared.
  const go = (d: Deal) => router.push(href(d), { scroll: false });
  const update = (d: Deal, slow = false) => {
    setDeal(d);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => window.history.replaceState(null, "", href(d)), slow ? 400 : 0);
  };
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  const byId = (team: BuilderTeam | undefined, id: number) => team?.players.find((p) => p.id === id);
  const pickById = (team: BuilderTeam | undefined, id: number) => team?.picks.find((k) => k.id === id);
  const incoming = deal.in.map((id) => byId(teamB, id)).filter(Boolean) as BuilderPlayer[];
  const outgoing = deal.out.map((id) => byId(teamA, id)).filter(Boolean) as BuilderPlayer[];
  const picksIn = deal.pin.map((id) => pickById(teamB, id)).filter(Boolean) as BuilderPick[];
  const picksOut = deal.pout.map((id) => pickById(teamA, id)).filter(Boolean) as BuilderPick[];
  const ret = (id: number) => deal.r[id] ?? 0;

  const math = useMemo(() => {
    // Each traded player's charge moves to the new team, minus what his old team retains.
    const inCost = incoming.reduce((s, p) => s + charged(p) * (1 - ret(p.id) / 100), 0);
    const outCost = outgoing.reduce((s, p) => s + charged(p) * (1 - ret(p.id) / 100), 0);
    const aRetains = outgoing.filter((p) => ret(p.id) > 0);
    const bRetains = incoming.filter((p) => ret(p.id) > 0);
    return {
      inCost, outCost,
      aAfter: teamA?.space == null ? null : teamA.space - inCost + outCost,
      bAfter: teamB?.space == null ? null : teamB.space - outCost + inCost,
      aRetains, bRetains,
      aRetained: aRetains.reduce((s, p) => s + charged(p) * ret(p.id) / 100, 0),
      bRetained: bRetains.reduce((s, p) => s + charged(p) * ret(p.id) / 100, 0),
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deal, teamA, teamB]);

  type Check = { ok: boolean | null; title: string; text: string };
  const checks: Check[] = [];
  if (teamA && teamB && (incoming.length || outgoing.length || picksIn.length || picksOut.length)) {
    const capOk = (math.aAfter ?? 0) >= 0 && (math.bAfter ?? 0) >= 0;
    checks.push({
      ok: capOk, title: capOk ? "Cap compliant, both teams" : "Over the cap",
      text: capOk
        ? `Both teams stay under the ${money(teamA.ceiling)} ceiling after the deal.`
        : `${(math.aAfter ?? 0) < 0 ? teamA.name : teamB.name} would be ${money(-Math.min(math.aAfter ?? 0, math.bAfter ?? 0))} over the ceiling.`,
    });
    const clauses = [...incoming, ...outgoing].filter((p) => p.clause && p.clause !== "none");
    const nmc = clauses.filter((p) => p.clause === "NMC");
    checks.push({
      ok: clauses.length === 0 ? true : nmc.length ? false : null,
      title: clauses.length === 0 ? "No trade clauses" : nmc.length ? "No-movement clause" : "Trade protection",
      text: clauses.length === 0 ? "No player in the deal has trade protection."
        : clauses.map((p) => `${p.name}: ${p.clause}${p.no_trade_list_size ? ` (${p.no_trade_list_size}-team list)` : ""}${p.clause === "NMC" ? ", must approve" : ", may need to approve"}`).join("; ") + ".",
    });
    const overRet = [...incoming, ...outgoing].filter((p) => ret(p.id) > 50);
    const aSlots = teamA.retained_slots_used + math.aRetains.length;
    const bSlots = teamB.retained_slots_used + math.bRetains.length;
    const retOk = overRet.length === 0 && aSlots <= MAX_RETAINED_SLOTS && bSlots <= MAX_RETAINED_SLOTS;
    if (math.aRetains.length || math.bRetains.length || overRet.length) {
      checks.push({
        ok: retOk, title: retOk ? "Retention allowed" : "Retention not allowed",
        text: `${teamA.abbrev} would use ${aSlots} of ${MAX_RETAINED_SLOTS} retained-salary slots and ${teamB.abbrev} ${bSlots} of ${MAX_RETAINED_SLOTS}; the limit is 50% per contract.`,
      });
    }
    const aRoster = teamA.roster_count - outgoing.filter((p) => p.on_roster).length + incoming.length;
    const bRoster = teamB.roster_count - incoming.filter((p) => p.on_roster).length + outgoing.length;
    const rosterOk = aRoster <= MAX_ROSTER && bRoster <= MAX_ROSTER;
    checks.push({
      ok: rosterOk ? true : null, title: "Roster count",
      text: `${teamA.abbrev} goes to ${aRoster} and ${teamB.abbrev} to ${bRoster} NHL roster players (limit ${MAX_ROSTER}).${rosterOk ? "" : " A move to the minors would be needed."}`,
    });
    const aContracts = teamA.contract_count - outgoing.length + incoming.length;
    const bContracts = teamB.contract_count - incoming.length + outgoing.length;
    if (aContracts > MAX_CONTRACTS || bContracts > MAX_CONTRACTS) {
      checks.push({ ok: false, title: "Contract limit", text: `A team would hold more than ${MAX_CONTRACTS} contracts.` });
    }
    for (const p of incoming) {
      if (p.age == null) continue;
      const endAge = p.age + p.years - 1;
      const level = curves[curveGroup(p.position)].find((x) => x.age === endAge)?.index;
      if (level != null && level < 85) {
        checks.push({ ok: null, title: "Term beyond peak", text: `${p.name}'s final contract year is his age-${endAge} season, when ${curveGroup(p.position) === "D" ? "defensemen" : curveGroup(p.position) === "G" ? "goalies" : "forwards"} typically produce ${Math.round(level)}% of their peak.` });
      }
    }
  }

  const warIn = incoming.reduce((s, p) => s + (p.war_proj ?? 0), 0) + picksIn.reduce((s, k) => s + (PICK_WAR[k.round] ?? 0), 0);
  const warOut = outgoing.reduce((s, p) => s + (p.war_proj ?? 0), 0) + picksOut.reduce((s, k) => s + (PICK_WAR[k.round] ?? 0), 0);
  const surplusIn = incoming.reduce((s, p) => s + (p.surplus ?? 0), 0);
  const surplusOut = outgoing.reduce((s, p) => s + (p.surplus ?? 0), 0);
  const market: string[] = [];
  for (const p of incoming) {
    if ((p.fans_trend ?? 0) <= -5 && p.chatter >= 3) market.push(`Falling fan sentiment and steady trade chatter around ${p.name} suggest ${teamB?.name ?? "his team"}'s asking price may soften.`);
    else if ((p.surplus ?? 0) >= 2_000_000) market.push(`${p.name} carries strong surplus value (${money(p.surplus)}), so expect a high asking price.`);
    else if ((p.surplus ?? 0) <= -2_000_000) market.push(`${p.name}'s contract costs more than his projected value (${money(p.surplus)}); ${teamB?.name ?? "his team"} may accept less to move it.`);
  }
  if (teamB?.status === "Seller") market.push(`${teamB.name} rate as a seller in our power rating, so they are more likely to deal veterans for futures.`);
  if (teamB?.status === "Contender") market.push(`${teamB.name} rate as a contender, so expect them to want roster help back rather than picks.`);

  const addItem = (side: "in" | "out", value: string) => {
    if (!value) return;
    const [kind, id] = value.split(":");
    const n = Number(id);
    const key = kind === "pick" ? (side === "in" ? "pin" : "pout") : side;
    if ((deal[key] as number[]).includes(n)) return;
    update({ ...deal, [key]: [...(deal[key] as number[]), n] });
  };
  const removeItem = (key: "in" | "out" | "pin" | "pout", id: number) => {
    const r = { ...deal.r };
    delete r[id];
    update({ ...deal, [key]: (deal[key] as number[]).filter((x) => x !== id), r });
  };

  const scenario = teamA && teamB && (incoming.length || outgoing.length)
    ? [
        incoming.length ? `${incoming.map((p) => p.name).join(", ")} to ${teamA.name}` : "",
        outgoing.length ? `${outgoing.map((p) => p.name).join(", ")} to ${teamB.name}` : "",
        ...math.bRetains.map((p) => `${teamB.abbrev} retains ${ret(p.id)}% of ${p.name}`),
        ...math.aRetains.map((p) => `${teamA.abbrev} retains ${ret(p.id)}% of ${p.name}`),
      ].filter(Boolean).join("; ")
    : "Pick your team and a trade partner, then add players, prospects, or picks.";

  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-heading text-4xl font-bold uppercase leading-tight tracking-tight sm:text-5xl">Trade builder</h1>
          <p className="text-sm text-muted">Scenario: {scenario}</p>
        </div>
        <button
          type="button"
          onClick={() => { navigator.clipboard.writeText(window.location.origin + href(deal)); setCopied(true); setTimeout(() => setCopied(false), 2000); }}
          className="rounded-md bg-positive px-4 py-2 font-semibold text-surface"
        >
          {copied ? "Link copied" : "Copy link to this deal"}
        </button>
      </div>

      <div className="flex flex-wrap gap-4 rounded-lg border border-border bg-surface p-4 text-sm">
        <TeamPicker label="Your team" value={deal.a} teams={teams} onChange={(v) => go({ ...deal, a: v, out: [], pout: [], r: {}, b: v === deal.b ? "" : deal.b })} />
        <TeamPicker label="Trading with" value={deal.b} teams={teams.filter((t) => t.abbrev !== deal.a)} onChange={(v) => go({ ...deal, b: v, in: [], pin: [], r: {} })} />
      </div>

      {teamA && suggestions.length > 0 && (
        <section className="rounded-lg border border-border bg-surface p-5">
          <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="font-heading text-2xl font-semibold uppercase tracking-tight">Suggested targets for {teamA.name}</h2>
            <p className="text-xs text-muted">Fill your weakest graded areas · weighted by how likely their team is to trade them</p>
          </div>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            {suggestions.map((s) => (
              <div key={s.id} className="rounded-lg border border-border p-3 text-sm">
                <div className="flex items-baseline justify-between gap-2">
                  <Link href={`/player/${s.id}`} className="font-semibold hover:underline">{s.name}</Link>
                  <span className="font-mono text-xs text-muted">{s.team}</span>
                </div>
                <p className="text-xs text-muted">{s.position} · {s.age ?? "—"} · {money(s.cap_hit)} × {s.years} · {s.team_status ?? "—"}</p>
                <p className="mt-1 text-xs font-semibold text-positive">{NEED_LABELS[s.category] ?? s.category} · {Math.round(s.pctile)}th pct · {s.war_proj?.toFixed(1) ?? "—"} WAR</p>
                <button
                  type="button"
                  onClick={() => go({ ...deal, b: s.team, in: deal.b === s.team ? [...new Set([...deal.in, s.id])] : [s.id], pin: deal.b === s.team ? deal.pin : [], r: deal.b === s.team ? deal.r : {} })}
                  className="mt-2 w-full rounded-md border border-positive px-2 py-1 text-xs font-semibold text-positive hover:bg-positive-soft"
                >
                  + Add to deal
                </button>
              </div>
            ))}
          </div>
        </section>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <Side
          title={`${teamA?.name ?? "Your team"} receives`}
          giver={teamB} players={incoming} picks={picksIn} ret={ret}
          onRetain={(id, v) => update({ ...deal, r: { ...deal.r, [id]: v } }, true)}
          onRemove={(id, pick) => removeItem(pick ? "pin" : "in", id)}
          onAdd={(v) => addItem("in", v)} added={math.inCost}
        />
        <Side
          title={`${teamB?.name ?? "Trade partner"} receives`}
          giver={teamA} players={outgoing} picks={picksOut} ret={ret}
          onRetain={(id, v) => update({ ...deal, r: { ...deal.r, [id]: v } }, true)}
          onRemove={(id, pick) => removeItem(pick ? "pout" : "out", id)}
          onAdd={(v) => addItem("out", v)} added={math.outCost}
        />
      </div>

      {teamA && teamB && (
        <div className="grid gap-6 lg:grid-cols-3">
          <section className="rounded-lg border border-border bg-surface p-5">
            <h2 className="mb-3 font-heading text-2xl font-semibold uppercase tracking-tight">Cap impact</h2>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-xs font-semibold uppercase text-muted">
                  <th className="py-2 text-left" /><th className="py-2 text-right">{teamA.abbrev}</th><th className="py-2 text-right">{teamB.abbrev}</th>
                </tr>
              </thead>
              <tbody className="font-mono">
                <Row label="Space before" a={money(teamA.space)} b={money(teamB.space)} />
                <Row label="Incoming" a={`+${money(math.inCost)}`} b={`+${money(math.outCost)}`} />
                <Row label="Outgoing" a={`−${money(math.outCost)}`} b={`−${money(math.inCost)}`} />
                <Row label="Space after" a={money(math.aAfter)} b={money(math.bAfter)} bold neg={[(math.aAfter ?? 0) < 0, (math.bAfter ?? 0) < 0]} />
              </tbody>
            </table>
            {(math.aRetained > 0 || math.bRetained > 0) && (
              <p className="mt-3 text-xs text-muted">
                Retained salary stays on the giving team&apos;s cap:
                {math.bRetained > 0 && ` ${teamB.abbrev} keeps ${money(math.bRetained)}.`}
                {math.aRetained > 0 && ` ${teamA.abbrev} keeps ${money(math.aRetained)}.`}
              </p>
            )}
          </section>

          <section className="rounded-lg border border-border bg-surface p-5">
            <h2 className="mb-3 font-heading text-2xl font-semibold uppercase tracking-tight">Deal checks</h2>
            {checks.length === 0 ? <p className="text-sm text-muted">Add players or picks to see the checks.</p> : (
              <ul className="space-y-3 text-sm">
                {checks.map((c, i) => (
                  <li key={i} className="flex gap-3">
                    <span className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-xs font-bold ${c.ok === true ? "bg-positive-soft text-positive" : c.ok === false ? "bg-negative text-surface" : "bg-negative-soft text-negative"}`}>
                      {c.ok === true ? "✓" : "!"}
                    </span>
                    <div><p className="font-semibold">{c.title}</p><p className="text-xs text-muted">{c.text}</p></div>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="rounded-lg border border-border bg-surface p-5">
            <h2 className="mb-3 font-heading text-2xl font-semibold uppercase tracking-tight">Value &amp; market read</h2>
            <div className="flex justify-between text-sm font-semibold">
              <span>Projected WAR in / out</span>
              <span className="font-mono">{warIn >= 0 ? "+" : ""}{warIn.toFixed(1)} / {warOut >= 0 ? "+" : ""}{warOut.toFixed(1)}</span>
            </div>
            <div className="mt-2 flex h-2 overflow-hidden rounded-full bg-border-soft" aria-hidden>
              <div className="bg-positive" style={{ width: `${(Math.max(warIn, 0) / Math.max(Math.max(warIn, 0) + Math.max(warOut, 0), 0.01)) * 100}%` }} />
              <div className="bg-negative" style={{ width: `${(Math.max(warOut, 0) / Math.max(Math.max(warIn, 0) + Math.max(warOut, 0), 0.01)) * 100}%` }} />
            </div>
            <p className="mt-3 text-sm">Surplus value in / out: <span className="font-mono">{money(surplusIn)} / {money(surplusOut)}</span></p>
            {(picksIn.length > 0 || picksOut.length > 0) && (
              <p className="mt-1 text-xs text-muted">Picks are counted at a rough WAR guide by round (a 1st about 1.0 per season once developed).</p>
            )}
            {market.length > 0 && (
              <div className="mt-4 space-y-2 rounded-lg bg-positive-soft p-3 text-sm text-positive">
                {market.map((m) => <p key={m}>{m}</p>)}
              </div>
            )}
            <p className="mt-3 text-xs text-muted">Comparable past trades arrive in a later update.</p>
          </section>
        </div>
      )}
    </>
  );
}

function Side({ title, giver, players, picks, ret, onRetain, onRemove, onAdd, added }: {
  title: string; giver: BuilderTeam | undefined; players: BuilderPlayer[]; picks: BuilderPick[]; ret: (id: number) => number;
  onRetain: (id: number, v: number) => void; onRemove: (id: number, pick: boolean) => void; onAdd: (v: string) => void; added: number;
}) {
  return (
    <section className="rounded-lg border border-border bg-surface p-5">
      <div className="mb-3 flex items-baseline justify-between gap-2">
        <h2 className="font-heading text-2xl font-semibold uppercase tracking-tight">{title}</h2>
        {giver && <p className="text-xs text-muted">Adds {money(added)}{players.some((p) => ret(p.id) > 0) ? " after retention" : ""}</p>}
      </div>
      <div className="space-y-2">
        {players.map((p) => (
          <div key={p.id} className="rounded-lg border border-border p-3">
            <div className="flex items-start justify-between gap-2">
              <div>
                <Link href={`/player/${p.id}`} className="font-semibold hover:underline">{p.name}</Link>
                <p className="text-xs text-muted">
                  {p.position} · {p.age ?? "—"} · {p.years} yr{p.years === 1 ? "" : "s"} · {p.clause && p.clause !== "none" ? p.clause : "no clause"}
                  {ret(p.id) > 0 ? ` · retained ${ret(p.id)}%` : ""}{p.on_roster ? "" : " · reserve list"}
                </p>
              </div>
              <div className="text-right">
                <p className="font-mono">{money(charged(p) * (1 - ret(p.id) / 100))}</p>
                <button type="button" onClick={() => onRemove(p.id, false)} className="text-xs text-muted hover:text-negative">Remove</button>
              </div>
            </div>
            <label className="mt-2 flex items-center gap-3 text-xs text-muted">
              {giver?.abbrev ?? "Seller"} retains
              <input type="range" min={0} max={50} step={5} value={ret(p.id)} onChange={(e) => onRetain(p.id, Number(e.target.value))} className="flex-1 accent-[var(--color-positive)]" />
              <span className="w-10 text-right font-mono">{ret(p.id)}%</span>
            </label>
          </div>
        ))}
        {picks.map((k) => (
          <div key={k.id} className="flex items-start justify-between gap-2 rounded-lg border border-border p-3">
            <div>
              <p className="font-semibold">{pickLabel(k)}</p>
              <p className="text-xs text-muted">{k.original === giver?.abbrev ? "Own pick" : `Originally ${k.original}'s`}{k.condition ? ` · ${k.condition}` : ""}</p>
            </div>
            <button type="button" onClick={() => onRemove(k.id, true)} className="text-xs text-muted hover:text-negative">Remove</button>
          </div>
        ))}
        {giver ? (
          <select value="" onChange={(e) => onAdd(e.target.value)} className="w-full rounded-lg border border-dashed border-border bg-surface px-3 py-3 text-center font-semibold text-positive">
            <option value="">+ Add player, prospect, or pick from {giver.name}</option>
            <optgroup label="NHL roster">
              {giver.players.filter((p) => p.on_roster).map((p) => <option key={p.id} value={`player:${p.id}`}>{p.name} · {p.position} · {money(charged(p))} × {p.years}</option>)}
            </optgroup>
            <optgroup label="Reserve list and prospects">
              {giver.players.filter((p) => !p.on_roster).map((p) => <option key={p.id} value={`player:${p.id}`}>{p.name} · {p.position} · {money(charged(p))} × {p.years}</option>)}
            </optgroup>
            <optgroup label="Draft picks">
              {giver.picks.map((k) => <option key={k.id} value={`pick:${k.id}`}>{pickLabel(k)}{k.original !== giver.abbrev ? ` (from ${k.original})` : ""}</option>)}
            </optgroup>
          </select>
        ) : (
          <p className="rounded-lg border border-dashed border-border p-3 text-center text-sm text-muted">Pick a team above to add players.</p>
        )}
      </div>
    </section>
  );
}

function TeamPicker({ label, value, teams, onChange }: { label: string; value: string; teams: { abbrev: string; name: string }[]; onChange: (v: string) => void }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs font-semibold uppercase tracking-wide text-muted">{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)} className="rounded-md border border-border bg-surface px-3 py-2 font-semibold">
        <option value="">Choose a team</option>
        {teams.map((t) => <option key={t.abbrev} value={t.abbrev}>{t.name}</option>)}
      </select>
    </label>
  );
}

function Row({ label, a, b, bold, neg }: { label: string; a: string; b: string; bold?: boolean; neg?: [boolean, boolean] }) {
  return (
    <tr className="border-b border-border-soft">
      <td className={`py-2 font-sans ${bold ? "font-semibold" : ""}`}>{label}</td>
      <td className={`py-2 text-right ${bold ? "font-semibold" : ""} ${neg?.[0] ? "text-negative" : ""}`}>{a}</td>
      <td className={`py-2 text-right ${bold ? "font-semibold" : ""} ${neg?.[1] ? "text-negative" : ""}`}>{b}</td>
    </tr>
  );
}
