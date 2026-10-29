
"""BQ-10: impacto de la calidad de red."""

from db import connect
from deps import FiltersDep, metrics_router
from metrics.network_impact import network_impact


router = metrics_router()
summary_key = "networkImpact"


@router.get("/network-impact")
def get_network_impact(filters: FiltersDep):
    """Compara tiempos de carga y seleccion por calidad de red."""
    with connect() as conn:
        return network_impact(conn, filters)


def summary(conn, filters):
    return network_impact(conn, filters)