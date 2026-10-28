from typing import Annotated
from fastapi import Query
from db import connect
from deps import FiltersDep, metrics_router
from metrics.feature_adoption import feature_adoption


router = metrics_router()
summary_key = "featureAdoption"


@router.get("/feature-adoption")
def get_feature_adoption(
    filters: FiltersDep,
    windowDays: Annotated[int, Query(ge=1)] = 7,
):
    """BQ8: adopción por pantalla entre usuarios activos."""
    with connect() as conn:
        return feature_adoption(conn, filters, window_days=windowDays)


def summary(conn, filters):
    return feature_adoption(conn, filters)