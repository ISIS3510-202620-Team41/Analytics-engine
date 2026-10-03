from typing import Annotated

from fastapi import HTTPException, Query

import config
from db import connect
from deps import FiltersDep, metrics_router
from metrics.category_frequency import category_frequency

router = metrics_router()
summary_key = "categoryByFreeTime"


@router.get("/category-by-free-time")
def get_category_by_free_time(
    filters: FiltersDep,
    buckets: Annotated[str | None, Query(description="Limites en minutos, ej. 30,60,120")] = None,
):
    """BQ4: categoria mas seleccionada por rango de duracion del tiempo libre."""
    try:
        edges = config.parse_edges(buckets) if buckets is not None else None
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    with connect() as conn:
        return category_frequency(conn, filters, edges)


def summary(conn, filters):
    return category_frequency(conn, filters)