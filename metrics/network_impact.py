
"""BQ-10: impacto de la calidad de red en la carga y seleccion."""

from collections import defaultdict

from filters import Filters, build_where


NETWORK_QUALITIES = (
    "good",
    "fair",
    "poor",
    "offline",
    "unknown",
)

_HAS_FREE_TIME = (
    "(free_time_minutes IS NULL OR free_time_minutes > 0)"
)

_NETWORK_SQL = (
    "COALESCE(NULLIF(network_quality, ''), 'unknown')"
)


def network_impact(conn, f: Filters) -> dict:
    # 1. Medir las cargas de la pantalla de recomendaciones
    where_load, p_load = build_where(
        conn, f, ("app_loading_time",)
    )

    loading_rows = conn.execute(
        f"""
        SELECT {_NETWORK_SQL} AS quality, duration_ms
        FROM events
        WHERE {where_load}
            AND load_type = 'screen'
            AND screen = 'recommendations'
        """,
        p_load,
    ).fetchall()

    durations = defaultdict(list)

    for row in loading_rows:
        if row["duration_ms"] is not None:
            quality = row["quality"]
            durations[quality].append(row["duration_ms"])

    # 2. Obtener las listas de recomendaciones mostradas
    where_shown, p_shown = build_where(
        conn, f, ("recommendation_shown",)
    )

    shown_rows = conn.execute(
        f"""
        SELECT recommendation_id,
               {_NETWORK_SQL} AS quality
        FROM events
        WHERE {where_shown}
          AND {_HAS_FREE_TIME}
          AND recommendation_id IS NOT NULL
        """,
        p_shown,
    ).fetchall()

    # Una lista cuenta una sola vez, aunque haya registros duplicados de recommendationId en eventos distintos.
    loads = {}

    for row in shown_rows:
        loads.setdefault(
            row["recommendation_id"], row["quality"]
        )

    # 3. Obtener las listas que tuvieron al menos una seleccion
    where_selected, p_selected = build_where(
        conn, f, ("recommended_activity_selected",)
    )

    selected_rows = conn.execute(
        f"""
        SELECT DISTINCT recommendation_id
        FROM events
        WHERE {where_selected}
          AND {_HAS_FREE_TIME}
          AND recommendation_id IS NOT NULL
        """,
        p_selected,
    ).fetchall()

    selected_ids = {
        row["recommendation_id"] for row in selected_rows
    }

    # 4. Agrupar cargas y selecciones por la calidad de red registrada al mostrar cada lista.
    recommendation_counts = defaultdict(int)
    selected_counts = defaultdict(int)

    for recommendation_id, quality in loads.items():
        recommendation_counts[quality] += 1

        if recommendation_id in selected_ids:
            selected_counts[quality] += 1

    # 5. Construir resultados consistentes para el dashboard
    qualities = set(NETWORK_QUALITIES)
    qualities.update(durations)
    qualities.update(recommendation_counts)

    by_quality = []

    for quality in NETWORK_QUALITIES:
        if quality not in qualities:
            continue

        times = durations[quality]
        shown = recommendation_counts[quality]
        with_selection = selected_counts[quality]

        by_quality.append({
            "networkQuality": quality,
            "averageLoadingMs": (
                round(sum(times) / len(times), 1)
                if times else None
            ),
            "loadingSamples": len(times),
            "recommendationLoads": shown,
            "loadsWithSelection": with_selection,
            "selectionRate": (
                with_selection / shown if shown else None
            ),
        })

    # Las categorías no previstas también deben poder diagnosticarse.
    for quality in sorted(qualities - set(NETWORK_QUALITIES)):
        times = durations[quality]
        shown = recommendation_counts[quality]
        with_selection = selected_counts[quality]

        by_quality.append({
            "networkQuality": quality,
            "averageLoadingMs": (
                round(sum(times) / len(times), 1)
                if times else None
            ),
            "loadingSamples": len(times),
            "recommendationLoads": shown,
            "loadsWithSelection": with_selection,
            "selectionRate": (
                with_selection / shown if shown else None
            ),
        })

    return {
        "loadingScreen": "recommendations",
        "byNetworkQuality": by_quality,
    }