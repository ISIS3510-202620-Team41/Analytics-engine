"""BQ11: ¿los cupones comerciales se interactuan y se redimen mas durante los descansos?

PROPOSITO DE NEGOCIO
--------------------
Es la pregunta que decide cuanto vale un espacio publicitario en la app. Los comercios
cercanos al campus pagan por aparecer en el catalogo, y lo que quieren saber es cuando
conviene aparecer. Si un cupon mostrado en el hueco entre dos clases se redime tres
veces mas que el mismo cupon mostrado en mitad de una clase, la conclusion no es
academica: el equipo puede vender esa franja mas cara, y el estudiante recibe ofertas
cuando de verdad puede usarlas.

Se responde con un embudo de tres pasos (mostrado, abierto, redimido) medido por
separado dentro y fuera de los descansos. Hacen falta los tres porque la pregunta es
por una TASA: contar solo las redenciones diria cuantas hubo, pero no si fueron muchas
o pocas respecto a cuantas oportunidades hubo.

DECISION CLAVE: LOS TRES ESTADOS DEL CONTEXTO
---------------------------------------------
`during_break` tiene tres valores posibles y no dos: 1 en un hueco, 0 fuera, y NULL
cuando el estudiante no ha importado su horario y la app no puede saberlo.

Los NULL se EXCLUYEN de la comparacion. Es la decision que sostiene la validez de toda
la BQ. Si se contaran como "fuera de descanso", todos los usuarios sin horario
engrosarian el grupo de control, que es precisamente el grupo contra el que se mide la
diferencia: la tasa de ese lado saldria diluida y la BQ reportaria una mejora que no
existe. Se cuentan aparte y se reportan, para que el dashboard pueda decir sobre cuanta
poblacion se calculo la respuesta.
"""
from filters import Filters, build_where

# Los tres pasos del embudo, en orden. El primero es el denominador.
_SHOWN = "deals_shown"
_OPENED = "deal_opened"
_REDEEMED = "deal_redeemed"


def _group(shown: int, opened: int, redeemed: int) -> dict:
    """Un lado de la comparacion, con sus dos tasas ya calculadas.

    Las tasas se calculan aqui y no en el dashboard para que cualquier cliente del API
    vea el mismo numero obtenido de la misma forma. Con cero impresiones se devuelve 0.0
    y no se divide; se devuelve 0.0 y no None porque la forma de la respuesta tiene que
    ser estable para quien la pinte, y el campo `shown` ya dice que no hubo datos.
    """
    return {
        "shown": shown,
        "opened": opened,
        "redeemed": redeemed,
        "interactionRate": (opened / shown) if shown else 0.0,
        "redemptionRate": (redeemed / shown) if shown else 0.0,
    }


def _totals(conn, f: Filters, during_break: int) -> tuple[int, int, int]:
    """Impresiones, aperturas y redenciones de un lado de la comparacion.

    Las impresiones se SUMAN (`deal_count`) y las otras dos se CUENTAN. No es una
    inconsistencia: un evento `deals_shown` representa una pantalla con varias tarjetas
    y lleva cuantas eran, mientras que abrir o redimir es siempre un cupon. Contar los
    eventos de impresion en vez de sumar su cuenta daria un denominador diez veces mas
    pequeno y las tasas saldrian infladas.

    `COALESCE` sobre la suma porque SUM() devuelve NULL, no 0, cuando no hay filas.
    """
    where, params = build_where(conn, f, (_SHOWN, _OPENED, _REDEEMED))

    row = conn.execute(
        f"""
        SELECT
            COALESCE(SUM(CASE WHEN event_type = ? THEN deal_count ELSE 0 END), 0) AS shown,
            SUM(CASE WHEN event_type = ? THEN 1 ELSE 0 END) AS opened,
            SUM(CASE WHEN event_type = ? THEN 1 ELSE 0 END) AS redeemed
        FROM events
        WHERE {where} AND during_break = ?
        """,
        [_SHOWN, _OPENED, _REDEEMED, *params, during_break],
    ).fetchone()

    return row["shown"] or 0, row["opened"] or 0, row["redeemed"] or 0


def _by_category(conn, f: Filters) -> list[dict]:
    """El desglose por tipo de comercio, solo dentro de los descansos.

    Responde la pregunta de seguimiento que el area comercial hace enseguida: si los
    descansos funcionan, que tipo de negocio aprovecha mejor ese momento. Un cafe de
    diez minutos y un gimnasio de noventa no compiten por el mismo hueco.

    Las impresiones no se pueden desglosar por categoria porque el evento de impresion
    es por pantalla y no por cupon: no se sabe de que categoria era cada tarjeta. Por
    eso aqui se cuentan aperturas y redenciones, y la tasa es redenciones sobre
    aperturas, que es una pregunta distinta y se nombra distinto.
    """
    where, params = build_where(conn, f, (_OPENED, _REDEEMED))

    rows = conn.execute(
        f"""
        SELECT deal_category AS category,
               SUM(CASE WHEN event_type = ? THEN 1 ELSE 0 END) AS opened,
               SUM(CASE WHEN event_type = ? THEN 1 ELSE 0 END) AS redeemed
        FROM events
        WHERE {where} AND during_break = 1 AND deal_category IS NOT NULL
        GROUP BY deal_category
        ORDER BY redeemed DESC, opened DESC
        """,
        [_OPENED, _REDEEMED, *params],
    ).fetchall()

    return [
        {
            "category": row["category"],
            "opened": row["opened"] or 0,
            "redeemed": row["redeemed"] or 0,
            "redemptionRatePerOpen": ((row["redeemed"] or 0) / row["opened"]) if row["opened"] else 0.0,
        }
        for row in rows
    ]


def deal_break_funnel(conn, f: Filters) -> dict:
    inside = _group(*_totals(conn, f, during_break=1))
    outside = _group(*_totals(conn, f, during_break=0))

    # Cuantos eventos quedaron fuera de la comparacion por no saberse el contexto. Se
    # reporta en vez de esconderse: si este numero es alto, la respuesta se calculo
    # sobre una minoria de los usuarios y quien la lea tiene que saberlo antes de tomar
    # una decision comercial con ella.
    where_all, params_all = build_where(conn, f, (_SHOWN, _OPENED, _REDEEMED))
    unknown = conn.execute(
        f"SELECT COUNT(*) FROM events WHERE {where_all} AND during_break IS NULL",
        params_all,
    ).fetchone()[0]

    # El multiplicador es la respuesta de una sola cifra, la que se lee en voz alta:
    # "durante los descansos se redime 5.4 veces mas". None cuando no se puede dividir,
    # porque un infinito no es una conclusion y un 0 diria lo contrario de lo que pasa.
    lift = (inside["redemptionRate"] / outside["redemptionRate"]) \
        if outside["redemptionRate"] else None

    return {
        "duringBreak": inside,
        "outsideBreak": outside,
        "redemptionLift": round(lift, 2) if lift is not None else None,
        "eventsWithUnknownContext": unknown,
        "byCategoryDuringBreak": _by_category(conn, f),
    }
