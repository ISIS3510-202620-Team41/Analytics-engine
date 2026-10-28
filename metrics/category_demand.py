"""BQ9: Demanda de actividades y categorias por franja horaria para alianzas comerciales (Tipo 4)."""
from collections import Counter
from datetime import datetime

import config
from filters import Filters, build_where

SLOT_DEFS = [
    {
        "slotId": "morning",
        "label": "Mañana (06:00 - 12:00)",
        "defaultOpportunity": "Alianzas de café matutino, desayunos universitarios y espacios de coworking/estudio.",
    },
    {
        "slotId": "midday",
        "label": "Almuerzo / Mediodía (12:00 - 14:00)",
        "defaultOpportunity": "Convenios con restaurantes y cafeterías de campus para pedidos to-go y menús ejecutivos.",
    },
    {
        "slotId": "afternoon",
        "label": "Tarde (14:00 - 18:00)",
        "defaultOpportunity": "Alianzas con centros deportivos, canchas sintéticas, marcas de ropa e hidratación.",
    },
    {
        "slotId": "evening",
        "label": "Noche (18:00 - 23:00)",
        "defaultOpportunity": "Promociones con cines, teatros, salas de juegos de mesa y planes sociales universitarios.",
    },
    {
        "slotId": "off_hours",
        "label": "Madrugada / Fuera de horario (23:00 - 06:00)",
        "defaultOpportunity": "Servicios 24 horas, tiendas de conveniencia y plataformas de estudio virtual.",
    },
]


def _slot_for_hour(hour: int) -> str:
    if 6 <= hour < 12:
        return "morning"
    if 12 <= hour < 14:
        return "midday"
    if 14 <= hour < 18:
        return "afternoon"
    if 18 <= hour < 23:
        return "evening"
    return "off_hours"


def _category_recommendation(category: str | None) -> str:
    if category == "ESTUDIO":
        return "Alta demanda de estudio. Oportunidad para convenios con cafeterías, espacios silenciosos y librerías."
    if category == "DEPORTES":
        return "Alta demanda deportiva. Alianzas recomendadas con alquiler de canchas, venta de bebidas hidratantes y gimnasios."
    if category == "CULTURA":
        return "Interés cultural destacado. Ideal para venta anticipada de entradas a museos, cineclubes y exposiciones."
    if category == "ENTRETENIMIENTO":
        return "Pico de ocio y socialización. Recomendar promociones en juegos grupales, restaurantes y eventos sociales."
    return "Sin demanda suficiente en este horario para perfilar alianzas comerciales."


def category_demand(conn, f: Filters, tz_offset: int = -5) -> dict:
    where, params = build_where(conn, f, ("recommended_activity_selected",))
    rows = conn.execute(
        f"SELECT user_id, activity_id, category, occurred_at, title, price FROM events "
        f"WHERE {where} "
        f"ORDER BY occurred_at, received_at", params).fetchall()

    # Una seleccion por (usuario, actividad): se toma la primera
    unique_selections: dict[tuple[str, str], dict] = {}
    for r in rows:
        key = (r["user_id"], r["activity_id"])
        if key not in unique_selections:
            unique_selections[key] = {
                "category": r["category"],
                "occurred_at": r["occurred_at"],
                "activity_id": r["activity_id"],
                "title": r["title"] or f"Actividad {r['activity_id'][:8]}",
                "price": r["price"],
            }

    # Inicializar contadores por slot
    slot_data: dict[str, dict] = {
        s["slotId"]: {
            "slotId": s["slotId"],
            "label": s["label"],
            "categories": {c: 0 for c in config.CATEGORIES},
            "activities": Counter(),
            "total": 0,
        }
        for s in SLOT_DEFS
    }

    overall_categories = Counter()

    for item in unique_selections.values():
        cat = item["category"]
        if not cat:
            continue

        raw_time = item["occurred_at"]
        try:
            # occurred_at esta en formato ISO UTC
            dt = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
            local_hour = (dt.hour + tz_offset) % 24
        except (ValueError, TypeError):
            local_hour = 12

        slot_id = _slot_for_hour(local_hour)
        slot = slot_data[slot_id]

        slot["categories"][cat] = slot["categories"].get(cat, 0) + 1
        slot["activities"][(item["activity_id"], item["title"])] += 1
        slot["total"] += 1
        overall_categories[cat] += 1

    result_slots = []
    peak_slot = None
    max_slot_total = -1

    for s in SLOT_DEFS:
        slot_id = s["slotId"]
        current = slot_data[slot_id]
        total = current["total"]

        if total > max_slot_total:
            max_slot_total = total
            peak_slot = current["label"] if total > 0 else None

        ordered_cats = sorted(current["categories"].items(), key=lambda kv: (-kv[1], kv[0]))
        top_cat = ordered_cats[0][0] if total > 0 else None
        top_count = ordered_cats[0][1] if total > 0 else 0
        tie = total > 0 and sum(1 for _, n in ordered_cats if n == top_count) > 1

        top_activities = [
            {"activityId": act_id, "title": title, "count": cnt}
            for (act_id, title), cnt in current["activities"].most_common(3)
        ]

        opportunity = _category_recommendation(top_cat) if total > 0 else s["defaultOpportunity"]

        result_slots.append({
            "slotId": slot_id,
            "label": current["label"],
            "totalSelections": total,
            "topCategory": top_cat,
            "tie": tie,
            "monetizationOpportunity": opportunity,
            "categories": [
                {"category": c, "count": n, "share": (n / total) if total else 0.0}
                for c, n in ordered_cats
            ],
            "topActivities": top_activities,
        })

    top_overall = overall_categories.most_common(1)[0][0] if overall_categories else None

    return {
        "tzOffsetHours": tz_offset,
        "totalSelectionsOverall": sum(overall_categories.values()),
        "topCategoryOverall": top_overall,
        "peakTimeSlot": peak_slot,
        "timeSlots": result_slots,
    }
