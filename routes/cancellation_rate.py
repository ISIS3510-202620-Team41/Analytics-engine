"""BQ12: Enrollment cancellation rate and advance notice before activities."""

from db import connect
from deps import FiltersDep, metrics_router
from filters import Filters
from metrics.cancellation_rate import cancellation_rate

router = metrics_router()
summary_key = "cancellationRate"


@router.get("/cancellation-rate")
def get_cancellation_rate(
    filters: FiltersDep,
):
    """Report enrollment cancellations and advance notice for the selected period."""
    with connect() as conn:
        return cancellation_rate(conn, filters)


def summary(conn, filters: Filters):
    return cancellation_rate(conn, filters)
