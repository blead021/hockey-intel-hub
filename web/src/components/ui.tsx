import Link from "next/link";
import type { ReactNode } from "react";

export function SiteHeader() {
  return (
    <header className="border-b border-border bg-surface">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3">
        <Link href="/" className="font-heading text-xl font-bold uppercase tracking-tight">
          Hockey Intel Hub
        </Link>
        <nav className="flex gap-4 text-sm font-medium">
          <Link href="/teams" className="text-muted hover:text-ink">
            Teams
          </Link>
        </nav>
      </div>
    </header>
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

export function StatCard({ label, value, detail }: { label: string; value: ReactNode; detail?: ReactNode }) {
  return (
    <div className="rounded-lg border border-border bg-surface p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-muted">{label}</p>
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

export function Th({ children, left }: { children?: ReactNode; left?: boolean }) {
  return (
    <th
      className={`border-b border-border bg-surface px-3 py-2 text-xs font-semibold uppercase tracking-wide text-muted ${
        left ? "sticky left-0 z-10 text-left" : "text-right"
      }`}
    >
      {children}
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
