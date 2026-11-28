"""Capa HTTP de BQ11. Solo traduce la peticion web a una llamada a la metrica.

La metrica vive aparte en metrics/deal_break_funnel.py para poder probarla sin levantar
el servidor, y para que la pregunta de negocio no dependa de como se exponga.
"""
from db import connect
from deps import FiltersDep, metrics_router
from metrics.deal_break_funnel import deal_break_funnel

router = metrics_router()

# summary_key + summary() son el contrato que lee routes/__init__.py: con estas dos
# lineas la metrica aparece sola en /metrics/summary y en el dashboard, sin tocar
# main.py ni ningun registro central.
summary_key = "dealBreakFunnel"


@router.get("/deal-break-funnel")
def get_deal_break_funnel(filters: FiltersDep):
    """BQ11: interaccion y redencion de cupones comerciales durante los descansos."""
    with connect() as conn:
        return deal_break_funnel(conn, filters)


def summary(conn, filters):
    return deal_break_funnel(conn, filters)
