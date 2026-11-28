from typing import Annotated

from fastapi import Query

from db import connect
from deps import FiltersDep, metrics_router
from metrics.friend_availability_impact import friend_availability_impact

router = metrics_router()
summary_key = "friendAvailabilityImpact"


@router.get("/friend-availability-impact")
def get_friend_availability_impact(
    filters: FiltersDep,
    activeDays: Annotated[int, Query(ge=1, le=90)] = 7
):
    """BQ-13 (Tipo 3): Impacto del uso de disponibilidad de amigos en la creacion de planes."""
    with connect() as conn:
        return friend_availability_impact(conn, filters, activeDays)


def summary(conn, filters):
    return friend_availability_impact(conn, filters)
