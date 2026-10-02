"use client";

import { useRouter } from "next/navigation";

export function TeamSelect({ teams, current, season }: { teams: { abbrev: string; name: string }[]; current: string; season: number }) {
  const router = useRouter();
  return (
    <label className="flex items-center gap-3 text-sm text-muted">
      Team
      <select
        className="rounded-md border border-border bg-surface px-3 py-2 font-semibold text-ink"
        value={current}
        onChange={(e) => router.push(`/team/${e.target.value}?season=${season}`)}
      >
        {teams.map((t) => (
          <option key={t.abbrev} value={t.abbrev}>
            {t.name}
          </option>
        ))}
      </select>
    </label>
  );
}
