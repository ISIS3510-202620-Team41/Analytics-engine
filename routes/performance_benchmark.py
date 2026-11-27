
"""BQ-15: impacto de las micro-optimizaciones en el rendimiento."""

from db import connect
from deps import FiltersDep, metrics_router
from metrics.performance_benchmark import performance_benchmark

router = metrics_router()
summary_key = "performanceBenchmark"

@router.get("/performance-benchmark")
def get_performance_benchmark(filters: FiltersDep):
    """Compara la reducción de jank frames y memoria heap."""
    with connect() as conn:
        return performance_benchmark(conn, filters)

def summary(conn, filters):
    """Permite incluir BQ-15 en /metrics/summary."""
    return performance_benchmark(conn, filters)
