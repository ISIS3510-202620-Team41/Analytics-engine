"BQ8: Que funcionalidades y pantallas son usadas por menos del 40% de usuarios activos"

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from filters import Filters, build_where, to_db_time, to_utc
import config

DEFAULT_WINDOW_DAYS = 7
UNDERUTILIZED_THRESHOLD = 0.40
MAX_WINDOW_DAYS = 90

def _known_values(conn, filters: Filters, event_type: str)
    """Recupera nombres observados historicamente, sin limitarse a la ventana actual."""

    where, params = build_where(conn,filters,(event_type,),)

    rows = conn.execute(
        f"""
        SELECT DISTINCT {column}
        FROM events
        WHERE {where}
          AND {column} IS NOT NULL
          AND TRIM({column}) <> ''
        """,
        params,
    )

    return {row[column] for row in rows}

def _users_by_value(conn,filters: Filters, event_type: str, column: str,) -> dict[str, int]
    """Cuenta los usuarios unicos por pantalla o funcionalidad dentro de la ventana"""
    where, params = build_where(conn, filters, (event_type,),)

    rows = conn.execute(
        f"""
        SELECT {column}, COUNT(DISTINCT user_id) AS users
        FROM events
        WHERE {where}
          AND {column} IS NOT NULL
          AND TRIM({column}) <> ''
          AND TRIM(user_id) <> ''
        GROUP BY {column}
        """,
        params,
    )

    return {row[column]: row["users"] for row in rows}

def _adoption_entries(catalog: tuple[str,...], historically_known: set[str], users_by_value: dict[str, int], active_users: int, key: str) -> list[dict]:
    """Combina el catalogo e historial, incluyendo los elementos con 0 uso reciente"""
    names = set(catalog) | historically_known | set(users_by_value)
    entries = []

    for name in names:
        users = users_by_value.get(name, 0)
        rate = users / active_users if active_users else None
        
        entries.appedn(
            {
                key: name,
                "uniqueUsers": users,
                "adoptionRate": rate,
                "underutilized": (rate is not None and rate < UNDERUTILIZED_THRESHOLD),
            }
        )
    
    #Las tasas mas bajas aparecen primero; sin usuarios activos quedan al final
    entries.sort(
        key=lambda item: (
            item["adoptionRate"] is None,
            item["adoptionRate"]
            if item["adoptionRate"] is not None
            else 0,
            item[key],
        )
    )

    return entries

def feature_adoption(conn, f:Filters, window_days = DEFAULT_WINDOW_DAYS) -> dict:
    """Devuelve la adopción por pantalla y funcionalidad en una ventana movible.

    Usuario activo: usuario con al menos un evento de cualquier tipo dentro
    de la ventana.

    Adopción de pantalla: usuarios únicos que generaron screen_view para esa
    pantalla / usuarios activos.

    Adopción de funcionalidad: usuarios únicos que generaron feature_used para
    esa funcionalidad / usuarios activos.

    El filtro `from` se sustituye por el inicio de la ventana móvil.
    El filtro `to`, si existe, define el final exclusivo de la ventana.
    """
    
    if window_days < 1 <= MAX_WINDOW_DAYS:
        raise ValueError(f"window_days debe estar entre 1 y {MAX_WINDOW_DAYS}")

    end = to_utc(now or datetime.now(timezone.utc))
    start = end - timedelta(days=window_days)

    # La ventana movil sustituye el from pero se mantiene le to y filtros
    window = replace(f, from=start)

    where_active, params_active = build_where(conn,window,None,)

    #Filtramos para obtener los usuarios activos por los parametros que necesitamos + los del dashboard
    active_users = conn.execute(
        f"""
        SELECT COUNT(DISTINCT user_id)
        FROM events
        WHERE {where_active}
          AND TRIM(user_id) <> ''
        """,
        params,
    ).fetchone()[0]

    #Catalogo historico sin restricciones de timepo per con los filtros seleccionados

    catalog_filters = replace(f, from_=None, to=None)

    historically_known_screens = _known_values(conn,catalog_filters,"screen_view","screen",)
    historically_known_features = _known_values(conn,catalog_filters,"features_used","feature",)

    screen_users = _users_by_value(conn,window,"screen_view","screen",)
    feature_users = _users_by_value(conn,window,"feature_used","feature",)

    screens = _adoption_entries(config.SCREEN_CATALOG,historically_known_screens,screen_users,active_users,"screen",)
    features = _adoption_entries(config.FEATURE_CATALOG,historically_known_features,feature_users,active_users,"feature",)

    underutilized_screen_count = sum(item["underutilized"] for item in screens)
    underutilized_feature_count = sum(item["underutilized"] for item in features)

    return {
        "windowDays": window_days,
        "windowStart": to_db_time(start),
        "windowEnd": to_db_time(end),
        "activeUsers": active_users,
        "threshold": UNDERUTILIZED_THRESHOLD,
        "underutilizedScreenCount": underutilized_screen_count,
        "underutilizedFeatureCount": underutilized_feature_count,
        "underutilizedCount": (
            underutilized_screen_count + underutilized_feature_count
        ),
        "screens": screens,
        "features": features,
    }