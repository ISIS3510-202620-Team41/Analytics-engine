"BQ8: Que funcionalidades y pantallas son usadas por menos del 40% de usuarios activos"


from datetime import datetime, timedelta, timezone
from filters import Filters, build_where, to_db_time, to_utc


DEFAULT_WINDOW_DAYS = 7
UNDERUTILIZED_THRESHOLD = 0.40


def feature_adoption(conn, f:Filters, window_days = DEFAULT_WINDOW_DAYS, now: datetime | None = None,) -> dict:
    if window_days < 1:
        raise ValueError("El valor de ventana de dias debe ser por lo menos 1")

    end = to_utc(now or datetime.now(timezone.utc))
    start = end - timedelta(days=window_days)

    # La métrica usa su propia ventana, pero conserva los filtros del dashboard.
    window = Filters(
        from_=start,
        to=end,
        app_version=f.app_version,
        min_app_version=f.min_app_version,
    )

    # Usuarios activos: cualquier tipo de evento dentro de la ventana.
    where, params = build_where(conn, window, None)

     #Filtramos para obtener los usuarios activos por los parametros que necesitamos + los del dashboard
    active_users = conn.execute(
        f"""
        SELECT COUNT(DISTINCT user_id)
        FROM events
        WHERE {where}
          AND TRIM(user_id) <> ''
        """,
        params,
    ).fetchone()[0]


    # Usuarios únicos por pantalla, contando únicamente screen_view.
    where, params = build_where(conn, window, ("screen_view",))

    users_by_screen = {
        row["screen"]: row["users"]
        for row in conn.execute(
            f"""
            SELECT screen, COUNT(DISTINCT user_id) AS users
            FROM events
            WHERE {where}
              AND TRIM(user_id) <> ''
              AND screen IS NOT NULL
              AND TRIM(screen) <> ''
            GROUP BY screen
            """,
            params,
        )
    }

    # Recuperar las pantallas conocidas, aunque no tengan visitas recientes.
    screen_filters = Filters(
        app_version=f.app_version,
        min_app_version=f.min_app_version,
    )
    where, params = build_where(
        conn, screen_filters, ("screen_view",)
    )

    known_screens = {
        row["screen"]
        for row in conn.execute(
            f"""
            SELECT DISTINCT screen
            FROM events
            WHERE {where}
              AND screen IS NOT NULL
              AND TRIM(screen) <> ''
            """,
            params,
        )
    }

    screens = []

    for screen in sorted(known_screens | set(users_by_screen)):
        users = users_by_screen.get(screen, 0)
        rate = users / active_users if active_users else None

        screens.append({
            "screen": screen,
            "uniqueUsers": users,
            "adoptionRate": rate,
            "underutilized": (
                rate is not None
                and rate < UNDERUTILIZED_THRESHOLD
            ),
        })

    # Primero las pantallas de menor adopción; las no evaluables van al final.
    screens.sort(
        key=lambda s: (
            s["adoptionRate"] is None,
            s["adoptionRate"] if s["adoptionRate"] is not None else 0,
            s["screen"],
        )
    )

    return {
        "windowDays": window_days,
        "windowStart": to_db_time(start),
        "windowEnd": to_db_time(end),
        "activeUsers": active_users,
        "threshold": UNDERUTILIZED_THRESHOLD,
        "underutilizedCount": sum(
            s["underutilized"] for s in screens
        ),
        "screens": screens,
    }