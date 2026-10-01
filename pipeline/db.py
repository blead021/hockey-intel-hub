"""Database connections for pipeline jobs."""

import psycopg

from pipeline.config import database_url


def connect(autocommit: bool = False) -> psycopg.Connection:
    return psycopg.connect(database_url(), autocommit=autocommit)
