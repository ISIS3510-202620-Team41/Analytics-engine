"""Configuracion por variables de entorno.

Se lee en cada llamada (no al importar) para que los tests puedan cambiarla.
"""
import os
from pathlib import Path

# Espejo del enum Category del backend (com.group41.backend.activity.domain.Category).
# Si el backend agrega una categoria, hay que agregarla aqui y en models.Category.
CATEGORIES = ("DEPORTES", "ESTUDIO", "CULTURA", "ENTRETENIMIENTO")

FRIEND_PLAN_ACTIONS = ("plan_created", "plan_joined")


def db_path() -> Path:
    return Path(os.getenv("ANALYTICS_DB_PATH", "data/analytics.db"))


def ingest_key() -> str | None:
    """Llave que usan la app y el backend para ESCRIBIR eventos. Vacia = sin proteccion (solo dev)."""
    return os.getenv("ANALYTICS_INGEST_KEY") or None


def admin_key() -> str | None:
    """Llave que usa el dashboard para LEER metricas y borrar eventos. Vacia = sin proteccion (solo dev)."""
    return os.getenv("ANALYTICS_ADMIN_KEY") or None


def loading_threshold_ms() -> int:
    return int(os.getenv("ANALYTICS_LOADING_THRESHOLD_MS", "1000"))


def parse_edges(raw: str) -> list[int]:
    """'30,60,120' -> [30, 60, 120]. Deben ser enteros positivos y estrictamente crecientes."""
    try:
        edges = [int(part) for part in raw.split(",") if part.strip()]
    except ValueError:
        raise ValueError("Los rangos deben ser enteros separados por coma, ej. 30,60,120")
    if not edges or edges[0] <= 0 or edges != sorted(set(edges)):
        raise ValueError("Los rangos deben ser positivos y estrictamente crecientes")
    return edges


def free_time_edges() -> list[int]:
    return parse_edges(os.getenv("ANALYTICS_FREE_TIME_BUCKETS", "30,60,120"))