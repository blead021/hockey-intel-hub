import Link from "next/link";
import type { ReactNode } from "react";
import { definition } from "@/lib/glossary";

// A small "i" next to a label; hovering (or tapping, on a phone) shows what the label means. Pure CSS, so it works
// on server-rendered pages. align says which way the box opens: "right" anchors it to the icon's right edge, for
// labels near the right side of a table.
export function Info({ text, align = "left" }: { text: string; align?: "left" | "right" }) {
  return (
    <span className="group relative ml-1 inline-flex align-middle font-normal normal-case tracking-normal">
      <button
        type="button"
        aria-label={text}
        className="inline-flex h-3.5 w-3.5 cursor-help items-center justify-center rounded-full border border-current text-[9px] font-semibold leading-none text-muted hover:text-ink focus:text-ink focus:outline-none"
      >
        i
      </button>
      <span
        role="tooltip"
        className={`pointer-events-none absolute top-full z-40 mt-1.5 hidden ${text.length > 300 ? "w-96" : "w-60"} max-w-[80vw] whitespace-normal rounded-md bg-ink px-3 py-2 text-left text-xs leading-snug text-surface shadow-lg group-focus-within:block group-hover:block ${
          align === "right" ? "right-0" : "left-0"
        }`}
      >
        {text}
      </span>
    </span>
  );
}

// A label followed by its "i" when the glossary defines it. term picks a different glossary entry than the
// visible text, for labels that mean different things in different tables.
export function Label({ text, term, align }: { text: ReactNode; term?: string; align?: "left" | "right" }) {
  const def = definition(term ?? (typeof text === "string" ? text : undefined));
  return (
    <>
      {text}
      {def && <Info text={def} align={align} />}
    </>
  );
}

export function PageTitle({ eyebrow, title, children }: { eyebrow?: ReactNode; title: ReactNode; children?: ReactNode }) {
  return (
    <div className="mb-6">
      {eyebrow && <p className="text-sm font-medium uppercase tracking-wide text-muted">{eyebrow}</p>}
      <h1 className="font-heading text-4xl font-bold uppercase leading-tight tracking-tight sm:text-5xl">{title}</h1>
      {children}
    </div>
  );
}

export function SectionTitle({ children, note }: { children: ReactNode; note?: ReactNode }) {
  return (
    <div className="mb-3 mt-10 flex flex-wrap items-baseline justify-between gap-2">
      <h2 className="font-heading text-2xl font-semibold uppercase tracking-tight">{children}</h2>
      {note && <p className="text-sm text-muted">{note}</p>}
    </div>
  );
}

export function StatCard({ label, value, detail, term }: { label: string; value: ReactNode; detail?: ReactNode; term?: string }) {
  return (
    <div className="rounded-lg border border-border bg-surface p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-muted"><Label text={label} term={term} /></p>
      <p className="mt-1 font-mono text-2xl font-medium">{value}</p>
      {detail && <p className="mt-1 text-xs text-muted">{detail}</p>}
    </div>
  );
}

export function CardGrid({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">{children}</div>;
}

// Tables scroll sideways inside their own box on phones, so the page itself never scrolls sideways.
export function DataTable({ children }: { children: ReactNode }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-surface">
      <table className="w-full min-w-max border-collapse text-sm">{children}</table>
    </div>
  );
}

export function Th({ children, left, term }: { children?: ReactNode; left?: boolean; term?: string }) {
  return (
    <th
      className={`border-b border-border bg-surface px-3 py-2 text-xs font-semibold uppercase tracking-wide text-muted ${
        left ? "sticky left-0 z-10 text-left" : "text-right"
      }`}
    >
      <Label text={children} term={term} align={left ? "left" : "right"} />
    </th>
  );
}

export function Td({ children, left }: { children?: ReactNode; left?: boolean }) {
  return (
    <td
      className={`border-b border-border-soft px-3 py-2 ${
        left ? "sticky left-0 z-10 bg-surface text-left" : "text-right font-mono"
      }`}
    >
      {children}
    </td>
  );
}

export function Unavailable({ children }: { children: ReactNode }) {
  return <p className="rounded-lg border border-dashed border-border bg-surface p-4 text-sm text-muted">{children}</p>;
}

export function SeasonPicker({ seasons, current, hrefFor }: { seasons: number[]; current: number; hrefFor: (s: number) => string }) {
  if (seasons.length < 2) return null;
  return (
    <div className="mt-3 flex flex-wrap gap-2">
      {seasons.map((s) => {
        const start = Math.floor(s / 10000);
        const label = `${start}-${String((start + 1) % 100).padStart(2, "0")}`;
        return (
          <Link
            key={s}
            href={hrefFor(s)}
            className={`rounded-full border px-3 py-1 font-mono text-xs ${
              s === current ? "border-ink bg-ink text-surface" : "border-border bg-surface text-muted hover:text-ink"
            }`}
          >
            {label}
          </Link>
        );
      })}
    </div>
  );
}

// A white card with an uppercase heading, as used for each section in the Design/ screenshots.
export function Panel({ title, note, children, className = "" }: { title: ReactNode; note?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-lg border border-border bg-surface p-5 ${className}`}>
      <div className="mb-4 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 className="font-heading text-2xl font-semibold uppercase tracking-tight">{title}</h2>
        {note && <p className="text-xs text-muted">{note}</p>}
      </div>
      {children}
    </section>
  );
}
