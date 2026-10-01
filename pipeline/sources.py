"""Data source on/off switches, stored in the data_sources table."""

import psycopg


class SourceDisabled(Exception):
    """Raised when a job tries to use a source that is switched off."""


def is_enabled(conn: psycopg.Connection, key: str) -> bool:
    row = conn.execute("select enabled from data_sources where key = %s", (key,)).fetchone()
    if row is None:
        raise KeyError(f"Unknown data source {key!r}. Add it to data_sources first.")
    return bool(row[0])


def require_enabled(conn: psycopg.Connection, key: str) -> None:
    if not is_enabled(conn, key):
        raise SourceDisabled(f"Data source {key!r} is switched off.")
