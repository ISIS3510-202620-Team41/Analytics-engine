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
    activity_duration_minutes  INTEGER,
    -- BQ11: cupones comerciales durante los descansos entre clases.
    deal_id            TEXT,
    deal_category      TEXT,
    -- Cuantos cupones se mostraron de una vez. Un evento por pantalla y no uno por
    -- cupon: diez tarjetas producen diez impresiones, y mandarlas sueltas triplicaria
    -- el volumen de eventos para alimentar un denominador.
    deal_count         INTEGER,
    -- NULL a proposito, y es la decision mas importante de BQ11: son tres estados, no
    -- dos. 1 en descanso, 0 fuera, NULL cuando el estudiante no importo su horario.
    -- Guardar 0 en el tercer caso lo meteria en el grupo de control y sesgaria la
    -- comparacion sin que nada lo avisara.
    during_break       INTEGER,
    break_minutes_left INTEGER
    activity_duration_minutes INTEGER,
    benchmark_id       TEXT,
    optimization_stage TEXT,
    jank_frames        INTEGER,
    total_frames       INTEGER,
    heap_memory_mb     REAL,
    enrollment_id      TEXT,
    scheduled_start_time TEXT,
    attempt_id         TEXT,
    preferences        TEXT,
    location_name      TEXT,
    latitude           REAL,
    longitude          REAL,
    available_friends_count INTEGER,
    selected_available_friends_count INTEGER,
    creation_status    TEXT,
    plan_id            TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_type_time
ON events (event_type, occurred_at);

CREATE INDEX IF NOT EXISTS idx_events_user_time
ON events (user_id, occurred_at);
"""


COLUMNS = (
    "event_id", "event_type", "user_id", "session_id", "app_version", "occurred_at", "received_at",
    "screen", "component", "exception_type", "load_type", "duration_ms", "activity_id", "category",
    "free_time_minutes", "recommendation_id", "action", "network_quality", "title", "price", "activity_duration_minutes",
    "deal_id", "deal_category", "deal_count", "during_break", "break_minutes_left"
    "event_id", "event_type", "user_id", "session_id",
    "app_version", "occurred_at", "received_at",
    "screen", "component", "exception_type", "load_type",
    "duration_ms", "activity_id", "category",
    "free_time_minutes", "recommendation_id", "action",
    "network_quality", "title", "price",
    "activity_duration_minutes",
    "benchmark_id", "optimization_stage",
    "jank_frames", "total_frames", "heap_memory_mb",
    "feature", "enrollment_id",
    "scheduled_start_time", "attempt_id",
    "preferences", "location_name",
    "latitude", "longitude",
    "available_friends_count",
    "selected_available_friends_count",
    "creation_status", "plan_id",
)


# Columnas que se agregan a bases de datos creadas con versiones anteriores.
MIGRATIONS = {
    # Compatibilidad con versiones anteriores
    "network_quality": "TEXT",
    "title": "TEXT",
    "price": "TEXT",
    "activity_duration_minutes": "INTEGER",
    "feature": "TEXT",

    # BQ12
    "enrollment_id": "TEXT",
    "scheduled_start_time": "TEXT",

    # BQ14
    "attempt_id": "TEXT",
    "preferences": "TEXT",
    "location_name": "TEXT",
    "latitude": "REAL",
    "longitude": "REAL",
    "available_friends_count": "INTEGER",
    "selected_available_friends_count": "INTEGER",
    "creation_status": "TEXT",
    "plan_id": "TEXT",

    # BQ15
    "benchmark_id": "TEXT",
    "optimization_stage": "TEXT",
    "jank_frames": "INTEGER",
    "total_frames": "INTEGER",
    "heap_memory_mb": "REAL",
}


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

            # Consultar las columnas que ya existen.
            existing = {
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
            # BQ11. Van con ALTER y no solo en el CREATE porque las bases que ya existen
            # no se recrean: sin esto, un despliegue en marcha fallaria en cada insert.
            for column, kind in (
                ("deal_id", "TEXT"),
                ("deal_category", "TEXT"),
                ("deal_count", "INTEGER"),
                ("during_break", "INTEGER"),
                ("break_minutes_left", "INTEGER"),
            ):
                if column not in existing:
                    conn.execute(f"ALTER TABLE events ADD COLUMN {column} {kind}")
                for row in conn.execute("PRAGMA table_info(events)")
            }

            # Agregar las columnas faltantes sin duplicarlas.
            for column_name, column_type in MIGRATIONS.items():
                if column_name not in existing:
                    conn.execute(
                        f"ALTER TABLE events ADD COLUMN "
                        f"{column_name} {column_type}"
                    )
                    existing.add(column_name)

            # Indice para consultar eventos por intento.
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
    """Borra los eventos de versiones de la app anteriores a min_version.
    Los eventos sin version no se tocan.
    """
    minimum = version_key(min_version)

    old = [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT app_version FROM events "
            "WHERE app_version IS NOT NULL"
        )
        if version_key(r[0]) < minimum
    ]

    if not old:
        return 0

    placeholders = ",".join("?" * len(old))

    return conn.execute(
        f"DELETE FROM events WHERE app_version IN ({placeholders})",
        old
    ).rowcount