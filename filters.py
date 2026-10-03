"""Filtros comunes a todas las metricas y utilidades de tiempo/version. Sin dependencias externas."""
import re
from dataclasses import dataclass
from datetime import datetime, timezone


def to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_db_time(dt: datetime) -> str:
    """Formato fijo en UTC, para que comparar texto equivalga a comparar fechas."""
    return to_utc(dt).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def version_key(version: str) -> tuple[int, ...]:
    """'1.2.0' -> (1, 2). Quita ceros finales para que 1.2 == 1.2.0. Lo no numerico cuenta como version minima."""
    core = re.split(r"[-+]", version.strip(), maxsplit=1)[0]
    numbers = [int(n) for n in re.findall(r"\d+", core)]
    while numbers and numbers[-1] == 0:
        numbers.pop()
    return tuple(numbers)


@dataclass(frozen=True)
class Filters:
    from_: datetime | None = None          # inclusivo
    to: datetime | None = None             # exclusivo
    app_version: str | None = None         # version exacta
    min_app_version: str | None = None     # descarta versiones mas viejas


def build_where(conn, f: Filters, event_types: tuple[str, ...] | None) -> tuple[str, list]:
    """Devuelve (clausula, parametros) para un WHERE. Solo se interpolan fragmentos fijos; los valores van como parametros.

    Regla para app_version: las filas sin version (eventos emitidos por el backend) pasan el filtro
    minAppVersion, porque no se puede saber si son viejas; el filtro appVersion exacto si las excluye.
    """
    clauses: list[str] = []
    params: list = []

    if event_types:
        clauses.append(f"event_type IN ({','.join('?' * len(event_types))})")
        params.extend(event_types)
    if f.from_ is not None:
        clauses.append("occurred_at >= ?")
        params.append(to_db_time(f.from_))
    if f.to is not None:
        clauses.append("occurred_at < ?")
        params.append(to_db_time(f.to))
    if f.app_version:
        clauses.append("app_version = ?")
        params.append(f.app_version)
    if f.min_app_version:
        minimum = version_key(f.min_app_version)
        known = [r[0] for r in conn.execute(
            "SELECT DISTINCT app_version FROM events WHERE app_version IS NOT NULL")]
        allowed = [v for v in known if version_key(v) >= minimum]
        if allowed:
            clauses.append(f"(app_version IS NULL OR app_version IN ({','.join('?' * len(allowed))}))")
            params.extend(allowed)
        else:
            clauses.append("app_version IS NULL")

    return (" AND ".join(clauses) or "1=1"), params