"""/metrics/summary: junta las metricas de todas las features que esten instaladas."""
from db import connect
from deps import FiltersDep, metrics_router
from routes import feature_modules

router = metrics_router()


@router.get("/summary")
def get_summary(filters: FiltersDep):
    with connect() as conn:
        return {m.summary_key: m.summary(conn, filters)
                for m in feature_modules() if hasattr(m, "summary_key")}