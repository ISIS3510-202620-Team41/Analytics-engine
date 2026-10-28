"""BQ9: Demanda de actividades y categorias por franja horaria para alianzas comerciales."""
from typing import Annotated

from fastapi import Query

from db import connect
from deps import FiltersDep, metrics_router
from metrics.category_demand import category_demand

router = metrics_router()
summary_key = "categoryDemand"


@router.get("/category-demand")
def get_category_demand(
    filters: FiltersDep,
    tz_offset: Annotated[int, Query(description="Desfase horario respecto a UTC en horas, ej. -5 para Colombia")] = -5,
):
    """BQ9: Demanda de actividades y categorias por franja horaria para alianzas comerciales (Tipo 4)."""
    with connect() as conn:
        return category_demand(conn, filters, tz_offset=tz_offset)


def summary(conn, filters):
    return category_demand(conn, filters)
