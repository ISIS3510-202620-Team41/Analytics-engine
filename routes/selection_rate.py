from db import connect
from deps import FiltersDep, metrics_router
from metrics.selection_rate import selection_rate

router = metrics_router()
summary_key = "selectionRate"


@router.get("/selection-rate")
def get_selection_rate(filters: FiltersDep):
    """BQ3: proporcion de recomendaciones en las que el usuario hizo join, dentro de su tiempo libre."""
    with connect() as conn:
        return selection_rate(conn, filters)


def summary(conn, filters):
    return selection_rate(conn, filters)