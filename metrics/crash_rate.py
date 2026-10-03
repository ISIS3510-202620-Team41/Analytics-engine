"""BQ2: Â¿que pantalla o componente tiene la mayor tasa de crash? (crashes / vistas de la pantalla)"""
from filters import Filters, build_where


def crash_rate(conn, f: Filters, min_views: int = 1) -> dict:
    where, params = build_where(conn, f, ("screen_view",))
    views = {r[0]: r[1] for r in conn.execute(
        f"SELECT screen, COUNT(*) FROM events WHERE {where} GROUP BY screen", params)}

    where, params = build_where(conn, f, ("crash",))
    crashes: dict[str, int] = {}
    components: dict[str, dict[str | None, int]] = {}
    for screen, component, n in conn.execute(
            f"SELECT screen, component, COUNT(*) FROM events WHERE {where} GROUP BY screen, component", params):
        crashes[screen] = crashes.get(screen, 0) + n
        components.setdefault(screen, {})[component] = n

    ranked, unranked = [], []
    for screen in set(views) | set(crashes):
        v, c = views.get(screen, 0), crashes.get(screen, 0)
        entry = {
            "screen": screen,
            "views": v,
            "crashes": c,
            # Sin vistas suficientes la tasa no es confiable (o hay un hueco de instrumentacion).
            "crashRate": (c / v) if v >= min_views else None,
            "components": sorted(
                ({"component": comp, "crashes": n} for comp, n in components.get(screen, {}).items()),
                key=lambda x: (-x["crashes"], x["component"] or "")),
        }
        (ranked if entry["crashRate"] is not None else unranked).append(entry)

    ranked.sort(key=lambda e: (-e["crashRate"], -e["crashes"], e["screen"]))
    unranked.sort(key=lambda e: (-e["crashes"], e["screen"]))

    total_views, total_crashes = sum(views.values()), sum(crashes.values())
    return {
        "minViews": min_views,
        "totalViews": total_views,
        "totalCrashes": total_crashes,
        "overallCrashRate": (total_crashes / total_views) if total_views else None,
        "highest": ranked[0] if ranked and ranked[0]["crashes"] > 0 else None,
        "screens": ranked + unranked,
    }