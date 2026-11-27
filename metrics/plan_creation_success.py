
import json
from collections import defaultdict
from bisect import bisect_left

import config
from db import connect


def _free_time_bucket(minutes: int, edges: list[int]) -> str:
    """Agrupa minutos en intervalos definidos por config.free_time_edges()."""
    index = bisect_left(edges, minutes)

    if index == 0:
        return f"0-{edges[0]} min"

    if index == len(edges):
        return f">{edges[-1]} min"

    return f"{edges[index - 1] + 1}-{edges[index]} min"


def _location_key(row):
    """Agrupa por coordenadas redondeadas; usa el nombre como alternativa."""
    latitude = row["latitude"]
    longitude = row["longitude"]

    if latitude is not None and longitude is not None:
        decimals = config.plan_location_decimals()
        rounded_latitude = round(latitude, decimals)
        rounded_longitude = round(longitude, decimals)

        key = ("coordinates", rounded_latitude, rounded_longitude)
        label = (
            f"{row['location_name']} "
            f"({rounded_latitude:.{decimals}f}, "
            f"{rounded_longitude:.{decimals}f})"
        )
        return key, label

    name = (row["location_name"] or "").strip().casefold()
    return ("name", name), row["location_name"] or "Ubicacion desconocida"


def _attempt_signature(row):
    """Campos que deben ser iguales si un attemptId aparece mas de una vez."""
    return (
        row["user_id"],
        row["preferences"],
        row["free_time_minutes"],
        row["location_name"],
        row["latitude"],
        row["longitude"],
        row["available_friends_count"],
        row["selected_available_friends_count"],
    )


def _decode_preferences(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()

    try:
        values = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return ()

    if not isinstance(values, list):
        return ()

    return tuple(sorted({
        str(value).strip().upper()
        for value in values
        if str(value).strip()
    }))


def _load_attempts_and_results(conn):
    rows = conn.execute(
        """
        SELECT *
        FROM events
        WHERE event_type IN (
            'plan_creation_attempted',
            'plan_creation_result'
        )
          AND attempt_id IS NOT NULL
        ORDER BY occurred_at ASC, received_at ASC
        """
    ).fetchall()

    attempts = defaultdict(list)
    results = defaultdict(list)

    for row in rows:
        attempt_id = row["attempt_id"]

        if row["event_type"] == "plan_creation_attempted":
            attempts[attempt_id].append(row)
        elif row["event_type"] == "plan_creation_result":
            results[attempt_id].append(row)

    return attempts, results


def _resolved_attempts(attempts, results):
    """Devuelve pares (contexto, resultado), excluyendo correlaciones ambiguas."""
    resolved = []

    for attempt_id, attempt_rows in attempts.items():
        result_rows = results.get(attempt_id, [])

        # Un intento sin resultado no se considera ni exito ni fracaso.
        if not result_rows:
            continue

        # Los intentos duplicados solo son aceptables si su contexto coincide.
        signatures = {
            _attempt_signature(row)
            for row in attempt_rows
        }

        if len(signatures) != 1:
            continue

        # Un resultado repetido con el mismo contenido es deduplicable.
        result_signatures = {
            (row["user_id"], row["creation_status"], row["plan_id"])
            for row in result_rows
        }

        # Resultados contradictorios o distintos se excluyen.
        if len(result_signatures) != 1:
            continue

        attempt = attempt_rows[0]
        result = result_rows[0]

        # Evita correlacionar eventos de usuarios diferentes.
        if attempt["user_id"] != result["user_id"]:
            continue

        if result["creation_status"] not in ("success", "failure"):
            continue

        resolved.append((attempt, result))

    return resolved


def calculate_plan_creation_success() -> dict:
    """Calcula las tasas de exito por combinacion de contexto."""

    free_time_edges = config.free_time_edges()
    minimum_sample = config.plan_creation_min_sample()

    with connect() as conn:
        attempts, results = _load_attempts_and_results(conn)

    resolved = _resolved_attempts(attempts, results)

    grouped = {}

    for attempt, result in resolved:
        preferences = _decode_preferences(attempt["preferences"])

        free_time_minutes = attempt["free_time_minutes"]
        if free_time_minutes is None:
            continue

        available_friends = attempt["available_friends_count"]
        selected_friends = attempt["selected_available_friends_count"]

        if available_friends is None or selected_friends is None:
            continue

        location_key, location_label = _location_key(attempt)

        free_time_label = _free_time_bucket(
            free_time_minutes,
            free_time_edges,
        )

        key = (
            preferences,
            free_time_label,
            location_key,
            available_friends,
            selected_friends,
        )

        if key not in grouped:
            grouped[key] = {
                "preferences": list(preferences),
                "freeTimeBucket": free_time_label,
                "location": location_label,
                "availableFriendsCount": available_friends,
                "selectedAvailableFriendsCount": selected_friends,
                "attempts": 0,
                "successes": 0,
                "failures": 0,
            }

        group = grouped[key]
        group["attempts"] += 1

        if result["creation_status"] == "success":
            group["successes"] += 1
        else:
            group["failures"] += 1

    combinations = []

    for group in grouped.values():
        attempts_count = group["attempts"]
        success_rate = (
            group["successes"] / attempts_count
            if attempts_count
            else 0
        )

        combinations.append({
            **group,
            "successRate": round(success_rate * 100, 2),
            "eligible": attempts_count >= minimum_sample,
        })

    combinations.sort(
        key=lambda item: (
            item["eligible"],
            item["successRate"],
            item["attempts"],
        ),
        reverse=True,
    )

    eligible = [
        item for item in combinations
        if item["eligible"]
    ]

    winner = eligible[0] if eligible else None

    return {
        "totalResolvedAttempts": len(resolved),
        "minimumSampleSize": minimum_sample,
        "locationPrecisionDecimals": config.plan_location_decimals(),
        "combinations": combinations,
        "winner": winner,
    }
