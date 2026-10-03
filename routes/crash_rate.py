from typing import Annotated

from fastapi import Query

from db import connect
from deps import FiltersDep, metrics_router
from metrics.crash_rate import crash_rate

router = metrics_router()
summary_key = "crashRate"


@router.get("/crash-rate")
def get_crash_rate(filters: FiltersDep, minViews: Annotated[int, Query(ge=1)] = 1):
    """BQ2: crashes / vistas por pantalla, de mayor a menor, con el detalle por componente."""
    with connect() as conn:
        return crash_rate(conn, filters, minViews)


def summary(conn, filters):
    return crash_rate(conn, filters)