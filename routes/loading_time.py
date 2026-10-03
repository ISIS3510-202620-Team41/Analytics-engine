from typing import Literal

from db import connect
from deps import FiltersDep, metrics_router
from metrics.loading_time import loading_time

router = metrics_router()
summary_key = "loadingTime"


@router.get("/loading-time")
def get_loading_time(
    filters: FiltersDep,
    loadType: Literal["cold_start", "warm_start", "screen"] = "cold_start",
    screen: str | None = None,
):
    """BQ1: tiempo de carga promedio, p50 y p95, y si el promedio esta bajo el umbral (1 s)."""
    with connect() as conn:
        return loading_time(conn, filters, loadType, screen)


def summary(conn, filters):
    return loading_time(conn, filters)