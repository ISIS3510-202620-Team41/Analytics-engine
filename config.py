"""Configuracion por variables de entorno y parametros del motor."""

import os
from pathlib import Path

# Espejo del enum Category del backend.
CATEGORIES = ("DEPORTES", "ESTUDIO", "CULTURA", "ENTRETENIMIENTO")

FRIEND_PLAN_ACTIONS = ("plan_created", "plan_joined")

# Catalogo inicial de pantallas para BQ8.
SCREEN_CATALOG = (
    "Home",
    "Recommendations",
    "FriendAvailability",
    "ActivityDetail",
    "Profile",
)

# Catalogo inicial de funcionalidades para BQ8.
FEATURE_CATALOG = (
    "activity_recommendations",
    "friend_availability",
    "activity_joining",
)

# Precision geografica para agrupar coordenadas en BQ14.
# 3 decimales representan aproximadamente una zona de 100-110 metros.
PLAN_LOCATION_DECIMALS = 3


def db_path() -> Path:
    return Path(os.getenv("ANALYTICS_DB_PATH", "data/analytics.db"))


def ingest_key() -> str | None:
    """Llave para escribir eventos. Vacia = sin proteccion (solo desarrollo)."""
    return os.getenv("ANALYTICS_INGEST_KEY") or None


def admin_key() -> str | None:
    """Llave para leer metricas y borrar eventos. Vacia = sin proteccion."""
    return os.getenv("ANALYTICS_ADMIN_KEY") or None


def loading_threshold_ms() -> int:
    return int(os.getenv("ANALYTICS_LOADING_THRESHOLD_MS", "1000"))


def parse_edges(raw: str) -> list[int]:
    """Convierte '30,60,120' en cortes enteros positivos y crecientes."""
    try:
        edges = [int(part) for part in raw.split(",") if part.strip()]
    except ValueError:
        raise ValueError(
            "Los rangos deben ser enteros separados por coma, ej. 30,60,120"
        )

    if not edges or edges[0] <= 0 or edges != sorted(set(edges)):
        raise ValueError(
            "Los rangos deben ser positivos y estrictamente crecientes"
        )

    return edges


def free_time_edges() -> list[int]:
    return parse_edges(os.getenv("ANALYTICS_FREE_TIME_BUCKETS", "30,60,120"))


def time_to_select_edges() -> list[int]:
    """BQ6: cortes del histograma, en segundos."""
    return parse_edges(
        os.getenv("ANALYTICS_TIME_TO_SELECT_BUCKETS", "10,30,60,180")
    )


def plan_location_decimals() -> int:
    """BQ14: precision fija inicial para agrupar coordenadas."""
    return PLAN_LOCATION_DECIMALS


def plan_creation_min_sample() -> int:
    """BQ14: intentos resueltos minimos para considerar una combinacion."""
    value = int(os.getenv("ANALYTICS_PLAN_CREATION_MIN_SAMPLE", "3"))
    if value < 1:
        raise ValueError("El minimo de muestra debe ser al menos 1")
    return value
