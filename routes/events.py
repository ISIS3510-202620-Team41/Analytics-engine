"""Ingesta de eventos."""
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from db import clear_all, connect, insert_rows, purge_versions_before
from models import AnalyticsEvent, EventBatch, IngestResponse, to_row
from security import require_admin_key, require_ingest_key

router = APIRouter(prefix="/events", tags=["events"])


def _ingest(events: list) -> IngestResponse:
    received_at = datetime.now(timezone.utc)
    rows = [to_row(e, received_at) for e in events]
    with connect() as conn:
        accepted, duplicates = insert_rows(conn, rows)
    return IngestResponse(accepted=accepted, duplicates=duplicates)


@router.post("", status_code=201, response_model=IngestResponse, dependencies=[Depends(require_ingest_key)])
def register_event(event: AnalyticsEvent):
    return _ingest([event])


@router.post("/batch", status_code=201, response_model=IngestResponse, dependencies=[Depends(require_ingest_key)])
def register_events(batch: EventBatch):
    return _ingest(batch.events)


@router.delete("", dependencies=[Depends(require_admin_key)])
def delete_events(
    appVersionBefore: Annotated[
        str | None, Query(description="Si se manda, solo borra eventos de versiones anteriores a esta")] = None,
):
    """Sin parametros borra TODO. Con appVersionBefore limpia las versiones viejas de la app."""
    with connect() as conn:
        deleted = purge_versions_before(conn, appVersionBefore) if appVersionBefore else clear_all(conn)
    return {"deleted": deleted}