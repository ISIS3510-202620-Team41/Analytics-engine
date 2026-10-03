"""BQ1: ¿el tiempo de carga promedio de la app es menor a 1 segundo?"""
import math

import config
from filters import Filters, build_where


def _percentile(sorted_values: list[int], p: float) -> int | None:
    """Percentil por rango mas cercano."""
    if not sorted_values:
        return None
    index = max(math.ceil(p / 100 * len(sorted_values)) - 1, 0)
    return sorted_values[index]


def loading_time(conn, f: Filters, load_type: str = "cold_start", screen: str | None = None) -> dict:
    where, params = build_where(conn, f, ("app_loading_time",))
    where += " AND load_type = ?"
    params.append(load_type)
    if screen:
        where += " AND screen = ?"
        params.append(screen)

    durations = sorted(r[0] for r in conn.execute(
        f"SELECT duration_ms FROM events WHERE {where}", params))
    samples = len(durations)
    average = sum(durations) / samples if samples else None
    threshold = config.loading_threshold_ms()

    return {
        "loadType": load_type,
        "screen": screen,
        "samples": samples,
        "averageMs": round(average, 1) if average is not None else None,
        "p50Ms": _percentile(durations, 50),
        "p95Ms": _percentile(durations, 95),
        "thresholdMs": threshold,
        # None cuando no hay muestras: "sin datos" no es lo mismo que "no cumple".
        "underThreshold": (average < threshold) if average is not None else None,
    }