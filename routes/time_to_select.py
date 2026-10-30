"""Capa HTTP de BQ6. Solo traduce la peticion web a una llamada a la metrica.

Por que la ruta esta separada de metrics/time_to_select.py: la metrica se puede probar
sin levantar servidor (los tests la llaman con una conexion directa) y la pregunta de
negocio queda independiente de como se exponga. Si manana se expone por otro transporte,
el archivo de la metrica no cambia.
"""
from typing import Annotated

from fastapi import HTTPException, Query

import config
from db import connect
from deps import FiltersDep, metrics_router
from metrics.time_to_select import time_to_select

# metrics_router() ya trae el prefijo /metrics y la proteccion con la llave de admin,
# para que ninguna feature se olvide de protegerla por su cuenta.
router = metrics_router()

# summary_key + summary() son el contrato que lee routes/__init__.py: con estas dos
# lineas la metrica aparece sola en /metrics/summary y en el dashboard. Por eso agregar
# una BQ es agregar un archivo, sin tocar main.py ni ningun registro central.
summary_key = "timeToSelect"


@router.get("/time-to-select")
def get_time_to_select(
    # FiltersDep inyecta y valida los filtros comunes (from, to, appVersion,
    # minAppVersion). Se reusa para que todas las BQ se filtren igual y para poder
    # responder "¿mejoro el tiempo de decision con la version nueva?" sin codigo extra.
    filters: FiltersDep,
    # buckets permite cambiar el detalle del histograma sin redeploy: con 5,15 se mira
    # de cerca a los que deciden rapido; con 60,300 se mira la cola de los que se atascan.
    buckets: Annotated[str | None, Query(description="Cortes del histograma en segundos, ej. 10,30,60,180")] = None,
):
    """BQ6: segundos entre ver las recomendaciones y unirse a una actividad (promedio, p50 y p95)."""
    try:
        # None (no mandaron el parametro) es distinto de "" (lo mandaron vacio): el
        # primero usa los cortes por defecto, el segundo es un error del cliente.
        edges = config.parse_edges(buckets) if buckets is not None else None
    except ValueError as exc:
        # 400 y no 500: unos cortes mal escritos son culpa de quien llama, no del
        # servidor. Se reusa el mensaje de parse_edges para que sepa como corregirlo.
        raise HTTPException(400, str(exc))
    # connect() como context manager asegura commit/rollback y cierre de la conexion
    # aunque la metrica lance una excepcion a mitad de camino.
    with connect() as conn:
        return time_to_select(conn, filters, edges)


def summary(conn, filters):
    """Version para /metrics/summary: siempre con los cortes por defecto.

    El resumen lo consume el dashboard de un solo golpe y no puede pedir cortes distintos
    por metrica, asi que aqui no se acepta el parametro buckets. Quien necesite otra
    division llama al endpoint individual.
    """
    return time_to_select(conn, filters)
