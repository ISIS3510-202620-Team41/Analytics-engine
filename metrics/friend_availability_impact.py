"""BQ-13 (Tipo 3): Impacto del uso de disponibilidad de amigos en la creacion de planes grupales.

Pregunta de negocio:
¿Como afecta el uso de la funcionalidad Friend Availability al numero y tasa de planes
creados con otros estudiantes en comparacion con el flujo directo sin consulta de disponibilidad?

Metodologia:
- Segmento Con Disponibilidad: Usuarios activos que consultaron la disponibilidad de amigos
  (eventos `friend_availability_used` con accion 'viewed' o 'matrix_viewed').
  Se evalua cuantos de ellos concretaron la creacion o union a un plan ('create_plan', 'plan_created', 'plan_joined').
- Segmento Sin Disponibilidad: Usuarios activos que crearon/se unieron a planes directamente
  (eventos `recommended_activity_selected`) sin haber consultado disponibilidad de amigos en la ventana.
- Tasa de Conversion y Lift Factor: Compara la efectividad de la matriz de disponibilidad frente
  al flujo estandard para responder si conocer los huecos de amigos impulsa significativamente la creacion de planes.
"""
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import config
from filters import Filters, build_where, to_utc


def friend_availability_impact(conn, f: Filters, active_days: int = 7) -> dict:
    end = to_utc(f.to) if f.to else datetime.now(timezone.utc)
    start = end - timedelta(days=active_days)
    window = replace(f, from_=start, to=end)

    # 1. Total de usuarios activos en la ventana de analisis
    where_any, p_any = build_where(conn, window, None)
    active_users = conn.execute(
        f"SELECT COUNT(DISTINCT user_id) FROM events WHERE {where_any}", p_any
    ).fetchone()[0]

    # 2. Segmento A: Usuarios que consultaron disponibilidad de amigos
    where_fa, p_fa = build_where(conn, window, ("friend_availability_used",))
    consult_actions = ("viewed", "matrix_viewed")
    consult_placeholders = ",".join("?" * len(consult_actions))

    consulted_users_query = f"""
        SELECT DISTINCT user_id FROM events
        WHERE {where_fa}
          AND action IN ({consult_placeholders})
    """
    consulted_users_rows = conn.execute(
        consulted_users_query, p_fa + list(consult_actions)
    ).fetchall()
    consulted_user_ids = {r[0] for r in consulted_users_rows}
    consulted_count = len(consulted_user_ids)

    # Planes creados/unidos desde Friend Availability
    plan_actions = ("create_plan", "plan_created", "plan_joined")
    plan_placeholders = ",".join("?" * len(plan_actions))

    avail_plans_query = f"""
        SELECT user_id, COUNT(*) as plan_count
        FROM events
        WHERE {where_fa}
          AND action IN ({plan_placeholders})
        GROUP BY user_id
    """
    avail_plans_rows = conn.execute(
        avail_plans_query, p_fa + list(plan_actions)
    ).fetchall()

    avail_acting_users = len(avail_plans_rows)
    total_plans_with_avail = sum(r[1] for r in avail_plans_rows)
    avail_conversion_rate = (
        (avail_acting_users / consulted_count) if consulted_count > 0 else 0.0
    )

    # 3. Segmento B: Usuarios y planes generados sin consultar disponibilidad (flujo directo)
    where_direct, p_direct = build_where(conn, window, ("recommended_activity_selected",))
    
    if consulted_user_ids:
        consulted_escaped = ",".join("?" * len(consulted_user_ids))
        direct_plans_query = f"""
            SELECT user_id, COUNT(*) as plan_count
            FROM events
            WHERE {where_direct}
              AND user_id NOT IN ({consulted_escaped})
            GROUP BY user_id
        """
        direct_params = p_direct + list(consulted_user_ids)
    else:
        direct_plans_query = f"""
            SELECT user_id, COUNT(*) as plan_count
            FROM events
            WHERE {where_direct}
            GROUP BY user_id
        """
        direct_params = p_direct

    direct_plans_rows = conn.execute(direct_plans_query, direct_params).fetchall()
    direct_acting_users = len(direct_plans_rows)
    total_plans_without_avail = sum(r[1] for r in direct_plans_rows)

    users_without_avail_count = max(0, active_users - consulted_count)
    direct_conversion_rate = (
        (direct_acting_users / users_without_avail_count)
        if users_without_avail_count > 0
        else 0.0
    )

    # 4. Metricas de Impacto y Lift Factor
    if direct_conversion_rate > 0:
        lift_factor = round(avail_conversion_rate / direct_conversion_rate, 2)
    elif avail_conversion_rate > 0:
        lift_factor = round(avail_conversion_rate * 5.0, 2)
    else:
        lift_factor = 1.0

    total_combined_plans = total_plans_with_avail + total_plans_without_avail
    share_from_availability = (
        round((total_plans_with_avail / total_combined_plans) * 100, 1)
        if total_combined_plans > 0
        else 0.0
    )

    # 5. Tendencia Diaria para visualizacion grafica
    daily_query = f"""
        SELECT substr(occurred_at, 1, 10) as day,
               SUM(CASE WHEN event_type = 'friend_availability_used' AND action IN ({plan_placeholders}) THEN 1 ELSE 0 END) as with_avail,
               SUM(CASE WHEN event_type = 'recommended_activity_selected' THEN 1 ELSE 0 END) as direct
        FROM events
        WHERE {where_any}
        GROUP BY day
        ORDER BY day ASC
    """
    daily_rows = conn.execute(daily_query, list(plan_actions) + p_any).fetchall()
    daily_trend = [
        {
            "date": r["day"],
            "withAvailability": r["with_avail"],
            "withoutAvailability": r["direct"],
        }
        for r in daily_rows
        if r["day"] is not None
    ]

    conclusion = (
        f"La tasa de concrecion de planes usando Disponibilidad de Amigos es del {avail_conversion_rate * 100:.1f}%, "
        f"representando un Lift Factor de {lift_factor}x frente a la tasa directa ({direct_conversion_rate * 100:.1f}%)."
    )

    return {
        "windowStart": start.isoformat(),
        "windowEnd": end.isoformat(),
        "activeDays": active_days,
        "activeUsers": active_users,
        "usersConsultingAvailability": consulted_count,
        "plansWithAvailability": total_plans_with_avail,
        "usersCreatingPlansWithAvailability": avail_acting_users,
        "availabilityConversionRate": round(avail_conversion_rate, 4),
        "usersWithoutAvailability": users_without_avail_count,
        "plansWithoutAvailability": total_plans_without_avail,
        "usersCreatingPlansWithoutAvailability": direct_acting_users,
        "directConversionRate": round(direct_conversion_rate, 4),
        "liftFactor": lift_factor,
        "shareFromAvailabilityPct": share_from_availability,
        "dailyTrend": daily_trend,
        "conclusion": conclusion,
    }
