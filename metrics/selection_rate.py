"""BQ3: proporcion de actividades recomendadas que los estudiantes seleccionan dentro de su tiempo libre.

- shown:    cargas de recomendaciones (una por recommendationId), sin contar las de usuarios con 0 min libres.
- selected: pares (usuario, actividad) unicos que hicieron join a una actividad recomendada.
  Quien no hace join no cuenta. Se excluyen los joins con 0 min libres, igual que las cargas.
- loadsWithSelection: cargas mostradas en las que hubo al menos una seleccion (acotada por shown).
"""
from filters import Filters, build_where

_HAS_FREE_TIME = "(free_time_minutes IS NULL OR free_time_minutes > 0)"


def selection_rate(conn, f: Filters) -> dict:
    where_shown, p_shown = build_where(conn, f, ("recommendation_shown",))
    where_sel, p_sel = build_where(conn, f, ("recommended_activity_selected",))

    shown = conn.execute(
        f"SELECT COUNT(DISTINCT recommendation_id) FROM events WHERE {where_shown} AND {_HAS_FREE_TIME}",
        p_shown).fetchone()[0]

    selected = conn.execute(
        f"SELECT COUNT(*) FROM (SELECT DISTINCT user_id, activity_id FROM events "
        f"WHERE {where_sel} AND {_HAS_FREE_TIME})", p_sel).fetchone()[0]

    loads_with_selection = conn.execute(
        f"SELECT COUNT(DISTINCT recommendation_id) FROM events "
        f"WHERE {where_sel} AND {_HAS_FREE_TIME} AND recommendation_id IN ("
        f"SELECT recommendation_id FROM events WHERE {where_shown} AND {_HAS_FREE_TIME})",
        p_sel + p_shown).fetchone()[0]

    return {
        "shown": shown,
        "selected": selected,
        "selectionRate": (selected / shown) if shown else 0.0,
        "loadsWithSelection": loads_with_selection,
        "loadSelectionRate": (loads_with_selection / shown) if shown else 0.0,
    }