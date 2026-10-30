"""Capa HTTP de BQ4. Solo traduce la peticion web a una llamada a la metrica.

Por que la ruta esta separada de metrics/category_frequency.py: asi la metrica se
puede probar sin levantar un servidor (los tests la llaman con una conexion directa)
y la pregunta de negocio queda independiente de como se exponga. Si manana se expone
por gRPC o por un job batch, el archivo de la metrica no cambia.
"""
from typing import Annotated

from fastapi import HTTPException, Query

import config
from db import connect
from deps import FiltersDep, metrics_router
from metrics.category_frequency import category_frequency

# metrics_router() ya trae el prefijo /metrics y la proteccion con la llave de admin,
# para que ninguna feature se olvide de protegerla por su cuenta.
router = metrics_router()

# summary_key + summary() son el contrato que lee routes/__init__.py: con estas dos
# lineas la metrica aparece sola en /metrics/summary. Por eso agregar una BQ es
# agregar un archivo, sin tocar main.py ni ningun registro central.
summary_key = "categoryByFreeTime"


@router.get("/category-by-free-time")
def get_category_by_free_time(
    # FiltersDep inyecta y valida los filtros comunes (from, to, appVersion,
    # minAppVersion). Se reusa para que todas las BQ se filtren igual.
    filters: FiltersDep,
    # buckets permite al dashboard pedir otra division sin redeploy: el analista
    # prueba 45,90 y ve el resultado al instante.
    buckets: Annotated[str | None, Query(description="Limites en minutos, ej. 30,60,120")] = None,
):
    """BQ4: categoria mas seleccionada por rango de duracion del tiempo libre."""
    try:
        # None (no mandaron el parametro) es distinto de "" (lo mandaron vacio): el
        # primero usa los cortes por defecto, el segundo es un error del cliente.
        edges = config.parse_edges(buckets) if buckets is not None else None
    except ValueError as exc:
        # 400 y no 500: unos cortes mal escritos son culpa de quien llama, no del
        # servidor. Se devuelve el mensaje de parse_edges para que sepa como corregirlo.
        raise HTTPException(400, str(exc))
    # connect() como context manager asegura commit/rollback y cierre de la conexion
    # aunque la metrica lance una excepcion a mitad de camino.
    with connect() as conn:
        return category_frequency(conn, filters, edges)


def summary(conn, filters):
    """Version para /metrics/summary: siempre con los cortes por defecto.

    El resumen lo consume el dashboard de un solo golpe y no puede pedir cortes
    distintos por metrica, asi que aqui no se acepta el parametro buckets. Quien
    necesite otra division llama al endpoint individual.
    """
    return category_frequency(conn, filters)
