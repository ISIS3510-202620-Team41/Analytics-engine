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
    feature            TEXT,
    component          TEXT,
    exception_type     TEXT,
    load_type          TEXT,
    duration_ms        INTEGER,
    activity_id        TEXT,
    category           TEXT,
    free_time_minutes  INTEGER,
    recommendation_id  TEXT,
    action             TEXT,
    network_quality    TEXT,
    title              TEXT,
    price              TEXT,
    activity_duration_minutes INTEGER,
    benchmark_id       TEXT,
    optimization_stage TEXT,
    jank_frames        INTEGER,
    total_frames       INTEGER,
    heap_memory_mb     REAL
    activity_duration_minutes  INTEGER,
    enrollment_id      TEXT,
    scheduled_start_time TEXT,
    attempt_id TEXT,
    preferences TEXT,
    location_name TEXT,
    latitude REAL,
    longitude REAL,
    available_friends_count INTEGER,
    selected_available_friends_count INTEGER,
    creation_status TEXT,
    plan_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_type_time ON events (event_type, occurred_at);
CREATE INDEX IF NOT EXISTS idx_events_user_time ON events (user_id, occurred_at);
"""

COLUMNS = (
    "event_id", "event_type", "user_id", "session_id",
    "app_version", "occurred_at", "received_at",
    "screen", "component", "exception_type", "load_type",
    "duration_ms", "activity_id", "category",
    "free_time_minutes", "recommendation_id", "action",
    "network_quality", "title", "price",
    "activity_duration_minutes",
    "benchmark_id", "optimization_stage",
    "jank_frames", "total_frames", "heap_memory_mb",
    "event_id",
    "event_type",
    "user_id",
    "session_id",
    "app_version",
    "occurred_at",
    "received_at",
    "screen",
    "feature",
    "component",
    "exception_type",
    "load_type",
    "duration_ms",
    "activity_id",
    "category",
    "free_time_minutes",
    "recommendation_id",
    "action",
    "network_quality",
    "title",
    "price",
    "activity_duration_minutes",
    "enrollment_id",
    "scheduled_start_time",
    "attempt_id",
    "preferences",
    "location_name",
    "latitude",
    "longitude",
    "available_friends_count",
    "selected_available_friends_count",
    "creation_status",
    "plan_id",
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
            # Serializa la migracion si dos peticiones abren la base al mismo tiempo.
            conn.execute("BEGIN IMMEDIATE")
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(events)")}
            if "network_quality" not in columns:
                conn.execute( "ALTER TABLE events ADD COLUMN network_quality TEXT" )
            # Asegura compatibilidad si la base ya existia con menos columnas
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(events)")
            existing = {row["name"] for row in cursor.fetchall()}
            if "title" not in existing:
                conn.execute("ALTER TABLE events ADD COLUMN title TEXT")
            if "price" not in existing:
                conn.execute("ALTER TABLE events ADD COLUMN price TEXT")
            if "activity_duration_minutes" not in existing:
                conn.execute("ALTER TABLE events ADD COLUMN activity_duration_minutes INTEGER")
            if "feature" not in existing:
                conn.execute("ALTER TABLE events ADD COLUMN feature TEXT")
            bq15_columns = {
                "benchmark_id": "TEXT",
                "optimization_stage": "TEXT",
                "jank_frames": "INTEGER",
                "total_frames": "INTEGER",
                "heap_memory_mb": "REAL",
            }

            for column_name, column_type in bq15_columns.items():
            # Los eventos guardados antes de BQ12 conservan valores NULL.
            if "enrollment_id" not in existing:
                conn.execute("ALTER TABLE events ADD COLUMN enrollment_id TEXT")
            if "scheduled_start_time" not in existing:
                conn.execute("ALTER TABLE events ADD COLUMN scheduled_start_time TEXT")
            
            bq14_columns = {
                "attempt_id": "TEXT",
                "preferences": "TEXT",
                "location_name": "TEXT",
                "latitude": "REAL",
                "longitude": "REAL",
                "available_friends_count": "INTEGER",
                "selected_available_friends_count": "INTEGER",
                "creation_status": "TEXT",
                "plan_id": "TEXT",
                }

            for column_name, column_type in bq14_columns.items():
                if column_name not in existing:
                    conn.execute(
                        f"ALTER TABLE events ADD COLUMN "
                        f"{column_name} {column_type}"
                    )

            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_attempt_id "
                "ON events (attempt_id)"
            )

            conn.commit()
            _initialized.add(key)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()



def insert_rows(conn, rows: list[dict]) -> tuple[int, int]:
    """Inserta ignorando event_id repetidos."""
    sql = (
        f"INSERT OR IGNORE INTO events ({','.join(COLUMNS)}) "
        f"VALUES ({','.join(':' + c for c in COLUMNS)})"
    )

    defaults = {
        column: None
        for column in COLUMNS
    }

    accepted = sum(
        conn.execute(sql, {**defaults, **row}).rowcount
        for row in rows
    )
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