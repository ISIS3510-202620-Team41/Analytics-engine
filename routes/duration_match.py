"""BQ7: Determine the frequency and proportion with which joined activities fit strictly within the user's available free time (Type 2)."""

from db import connect
from deps import FiltersDep, metrics_router
from metrics.duration_match import duration_match

router = metrics_router()
summary_key = "durationMatch"


@router.get("/duration-match")
def get_duration_match(
    filters: FiltersDep,
):
    """BQ7: Determine the frequency and proportion with which joined activities fit strictly within the user's available free time (Type 2)."""
    with connect() as conn:
        return duration_match(conn, filters)


def summary(conn, filters):
    return duration_match(conn, filters)