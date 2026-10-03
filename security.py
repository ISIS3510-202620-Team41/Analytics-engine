"""Autenticacion por API key (header X-API-Key). Cada llave solo se exige si esta configurada."""
import secrets

from fastapi import Header, HTTPException, status

import config


def _matches(provided: str | None, *valid: str | None) -> bool:
    return provided is not None and any(
        secrets.compare_digest(provided.encode(), key.encode()) for key in valid if key)


def require_ingest_key(x_api_key: str | None = Header(default=None)) -> None:
    """Escribir eventos: sirve la llave de ingesta o la de admin."""
    ingest, admin = config.ingest_key(), config.admin_key()
    if ingest is not None and not _matches(x_api_key, ingest, admin):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "API key invalida")


def require_admin_key(x_api_key: str | None = Header(default=None)) -> None:
    """Leer metricas y borrar eventos: solo la llave de admin."""
    admin = config.admin_key()
    if admin is not None and not _matches(x_api_key, admin):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "API key invalida")