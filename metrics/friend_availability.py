"""BQ5: ¿que porcentaje de usuarios activos usa Friend Availability?

Usuario activo = al menos un evento de cualquier tipo en los ultimos `activeDays` dias (por defecto 7),
contados hacia atras desde `to` (o desde ahora). El filtro `from` no aplica: la ventana la define activeDays.

- usageRate:      usuarios con algun evento friend_availability_used / usuarios activos
                  (hoy: quien consulto /api/friends/gaps).
- planActionRate: usuarios que ademas crearon o se unieron a un plan desde la feature / usuarios activos.
"""
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import config
from filters import Filters, build_where, to_utc


def friend_availability_usage(conn, f: Filters, active_days: int = 7) -> dict:
    end = to_utc(f.to) if f.to else datetime.now(timezone.utc)
    start = end - timedelta(days=active_days)
    window = replace(f, from_=start)

    where_any, p_any = build_where(conn, window, None)
    active = conn.execute(
        f"SELECT COUNT(DISTINCT user_id) FROM events WHERE {where_any}", p_any).fetchone()[0]

    where_fa, p_fa = build_where(conn, window, ("friend_availability_used",))
    using = conn.execute(
        f"SELECT COUNT(DISTINCT user_id) FROM events WHERE {where_fa}", p_fa).fetchone()[0]

    actions = config.FRIEND_PLAN_ACTIONS
    acting = conn.execute(
        f"SELECT COUNT(DISTINCT user_id) FROM events WHERE {where_fa} "
        f"AND action IN ({','.join('?' * len(actions))})", p_fa + list(actions)).fetchone()[0]

    return {
        "windowStart": start.isoformat(),
        "windowEnd": end.isoformat(),
        "activeDays": active_days,
        "activeUsers": active,
        "usersUsingFeature": using,
        "usageRate": (using / active) if active else 0.0,
        "usersCreatingOrJoiningPlan": acting,
        "planActionRate": (acting / active) if active else 0.0,
    }