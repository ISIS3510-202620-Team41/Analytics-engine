"""Piezas compartidas por las rutas: filtros comunes y el router base de /metrics."""
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from filters import Filters, to_utc
from security import require_admin_key


def get_filters(
    from_: Annotated[datetime | None, Query(alias="from", description="Inicio inclusivo (ISO 8601)")] = None,
    to: Annotated[datetime | None, Query(description="Fin exclusivo (ISO 8601)")] = None,
    appVersion: Annotated[str | None, Query(description="Solo esta version exacta de la app")] = None,
    minAppVersion: Annotated[str | None, Query(description="Descarta versiones mas viejas que esta")] = None,
) -> Filters:
    if from_ and to and to_utc(from_) >= to_utc(to):
        raise HTTPException(400, "'from' debe ser anterior a 'to'")
    return Filters(from_=from_, to=to, app_version=appVersion, min_app_version=minAppVersion)


FiltersDep = Annotated[Filters, Depends(get_filters)]


def metrics_router() -> APIRouter:
    """Router de /metrics protegido con la llave de admin. Cada feature crea el suyo."""
    return APIRouter(prefix="/metrics", tags=["metrics"], dependencies=[Depends(require_admin_key)])