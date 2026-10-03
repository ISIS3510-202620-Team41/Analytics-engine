from typing import Annotated

from fastapi import Query

from db import connect
from deps import FiltersDep, metrics_router
from metrics.friend_availability import friend_availability_usage

router = metrics_router()
summary_key = "friendAvailability"


@router.get("/friend-availability")
def get_friend_availability(filters: FiltersDep, activeDays: Annotated[int, Query(ge=1, le=90)] = 7):
    """BQ5: % de usuarios activos (ultimos activeDays dias) que usan Friend Availability."""
    with connect() as conn:
        return friend_availability_usage(conn, filters, activeDays)


def summary(conn, filters):
    return friend_availability_usage(conn, filters)