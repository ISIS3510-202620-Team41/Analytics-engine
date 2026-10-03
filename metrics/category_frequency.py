"""BQ4: ¿que categoria recomendada se selecciona mas, segun la duracion del tiempo libre?"""
from bisect import bisect_right

import config
from filters import Filters, build_where


def _labels(edges: list[int]) -> list[tuple[str, int, int | None]]:
    bounds = [0, *edges]
    out = []
    for i, lo in enumerate(bounds):
        hi = edges[i] if i < len(edges) else None
        out.append((f"{lo}-{hi}" if hi is not None else f"{lo}+", lo, hi))
    return out


def category_frequency(conn, f: Filters, edges: list[int] | None = None) -> dict:
    edges = edges or config.free_time_edges()
    where, params = build_where(conn, f, ("recommended_activity_selected",))
    rows = conn.execute(
        f"SELECT user_id, activity_id, category, free_time_minutes FROM events "
        f"WHERE {where} AND (free_time_minutes IS NULL OR free_time_minutes > 0) "
        f"ORDER BY occurred_at, received_at", params)

    # Una seleccion por (usuario, actividad): se queda la primera.
    unique: dict[tuple[str, str], tuple[str, int | None]] = {}
    for user_id, activity_id, category, minutes in rows:
        unique.setdefault((user_id, activity_id), (category, minutes))

    buckets = _labels(edges)
    counts: list[dict[str, int]] = [{c: 0 for c in config.CATEGORIES} for _ in buckets]
    without_free_time = 0
    for category, minutes in unique.values():
        if minutes is None:
            without_free_time += 1
            continue
        bucket = counts[bisect_right(edges, minutes)]
        bucket[category] = bucket.get(category, 0) + 1

    result = []
    for (label, lo, hi), bucket in zip(buckets, counts):
        total = sum(bucket.values())
        ordered = sorted(bucket.items(), key=lambda kv: (-kv[1], kv[0]))
        top_count = ordered[0][1]
        result.append({
            "label": label,
            "minMinutes": lo,
            "maxMinutes": hi,           # exclusivo; None = sin tope
            "total": total,
            "topCategory": ordered[0][0] if total else None,
            "tie": bool(total) and sum(1 for _, n in ordered if n == top_count) > 1,
            "categories": [
                {"category": c, "count": n, "share": (n / total) if total else 0.0} for c, n in ordered],
        })

    return {"buckets": result, "selectionsWithoutFreeTime": without_free_time}