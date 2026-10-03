"""Persistencia en SQLite (libreria estandar). Una sola tabla ancha de eventos."""
import sqlite3
from contextlib import contextmanager

import config
from filters import version_key

# Una tabla ancha: a esta escala es lo mas simple y permite agregar con SQL plano.
# El SQL es estandar (salvo INSERT OR IGNORE y el PRAGMA), asi que migrar a Postgres es directo.
SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    event_id           TEXT PRIMARY KEY,
    event_type         TEXT NOT NULL,
    user_id            TEXT NOT NULL,
    session_id         TEXT,
    app_version        TEXT,
    occurred_at        TEXT NOT NULL,
    received_at        TEXT NOT NULL,
    screen             TEXT,
    component          TEXT,
    exception_type     TEXT,
    load_type          TEXT,
    duration_ms        INTEGER,
    activity_id        TEXT,
    category           TEXT,
    free_time_minutes  INTEGER,
    recommendation_id  TEXT,
    action             TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_type_time ON events (event_type, occurred_at);
CREATE INDEX IF NOT EXISTS idx_events_user_time ON events (user_id, occurred_at);
"""

COLUMNS = (
    "event_id", "event_type", "user_id", "session_id", "app_version", "occurred_at", "received_at",
    "screen", "component", "exception_type", "load_type", "duration_ms", "activity_id", "category",
    "free_time_minutes", "recommendation_id", "action",
)

_initialized: set[str] = set()


@contextmanager
def connect():
    path = config.db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        key = str(path.resolve())
        if key not in _initialized:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)
            _initialized.add(key)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def insert_rows(conn, rows: list[dict]) -> tuple[int, int]:
    """Inserta ignorando los event_id repetidos (reintentos de la app). Devuelve (aceptados, duplicados)."""
    sql = (f"INSERT OR IGNORE INTO events ({','.join(COLUMNS)}) "
           f"VALUES ({','.join(':' + c for c in COLUMNS)})")
    accepted = sum(conn.execute(sql, row).rowcount for row in rows)
    return accepted, len(rows) - accepted


def clear_all(conn) -> int:
    return conn.execute("DELETE FROM events").rowcount


def purge_versions_before(conn, min_version: str) -> int:
    """Borra los eventos de versiones de la app anteriores a min_version. Los sin version no se tocan."""
    minimum = version_key(min_version)
    old = [r[0] for r in conn.execute("SELECT DISTINCT app_version FROM events WHERE app_version IS NOT NULL")
           if version_key(r[0]) < minimum]
    if not old:
        return 0
    return conn.execute(
        f"DELETE FROM events WHERE app_version IN ({','.join('?' * len(old))})", old).rowcount