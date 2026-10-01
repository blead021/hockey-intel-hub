"""Applies the numbered SQL files in /db, in order, each one exactly once.

Usage:
    python -m pipeline.migrate            apply pending migrations
    python -m pipeline.migrate --status   list applied and pending migrations
"""

import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from pipeline.config import REPO_ROOT
from pipeline.db import connect

MIGRATIONS_DIR = REPO_ROOT / "db"
NAME_PATTERN = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


@dataclass(frozen=True)
class Migration:
    name: str
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode()).hexdigest()


def load_migrations(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    """Reads migration files, rejecting bad names and duplicate numbers."""
    migrations = []
    seen = {}
    for path in sorted(directory.glob("*.sql")):
        match = NAME_PATTERN.match(path.name)
        if not match:
            raise ValueError(f"{path.name}: migration names must look like 0001_short_name.sql")
        number = match.group(1)
        if number in seen:
            raise ValueError(f"{path.name} and {seen[number]} share the number {number}")
        seen[number] = path.name
        migrations.append(Migration(path.name, path.read_text(encoding="utf-8")))
    return migrations


def pending(migrations: list[Migration], applied: dict[str, str]) -> list[Migration]:
    """Returns migrations not yet applied. Fails if an applied file was edited afterwards."""
    for m in migrations:
        if m.name in applied and applied[m.name] != m.checksum:
            raise ValueError(f"{m.name} changed after it was applied. Write a new migration instead.")
    return [m for m in migrations if m.name not in applied]


def main(argv: list[str]) -> int:
    migrations = load_migrations()
    with connect() as conn:
        conn.execute(
            """create table if not exists schema_migrations (
                 name text primary key,
                 checksum text not null,
                 applied_at timestamptz not null default now())"""
        )
        conn.commit()
        applied = dict(conn.execute("select name, checksum from schema_migrations").fetchall())
        todo = pending(migrations, applied)

        if "--status" in argv:
            for m in migrations:
                print(f"{'applied' if m.name in applied else 'pending'}  {m.name}")
            return 0

        if not todo:
            print("Database is up to date.")
            return 0

        for m in todo:
            # Each file runs in its own transaction, so a failure leaves nothing half applied.
            with conn.transaction():
                conn.execute(m.sql)
                conn.execute(
                    "insert into schema_migrations (name, checksum) values (%s, %s)",
                    (m.name, m.checksum),
                )
            print(f"applied  {m.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
