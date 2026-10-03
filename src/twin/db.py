from contextlib import contextmanager

import psycopg

from twin.config import settings


@contextmanager
def connect(autocommit: bool = False):
    """Connection whose session time zone is the study's, so `interval 'N days'`
    arithmetic and `time_bucket(..., 'America/Chicago')` agree with Python."""
    cfg = settings()
    with psycopg.connect(
        cfg.database_url, autocommit=autocommit, options=f"-c timezone={cfg.source_tz}"
    ) as conn:
        yield conn


def ref_ids(conn, table: str, key: str, value: str) -> dict[str, int]:
    """Lookup map from a ref table, e.g. ref_ids(conn, 'ref.tag', 'code', 'tag_id')."""
    rows = conn.execute(f"SELECT {key}, {value} FROM {table}").fetchall()
    return {k: v for k, v in rows}
