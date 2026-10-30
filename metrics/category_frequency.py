"""BQ4: ¿que categoria recomendada se selecciona mas, segun la duracion del tiempo libre?

PROPOSITO DE NEGOCIO
--------------------
No basta con saber cual es la categoria mas popular en general: lo que sirve para
recomendar mejor es saber que elige el estudiante SEGUN cuanto tiempo libre tiene.
Alguien con 20 minutos no escoge lo mismo que alguien con 3 horas. Si el motor de
recomendaciones conoce ese patron, puede ordenar la lista distinto para cada hueco
de la agenda en vez de mostrar siempre lo mismo.

Por eso la respuesta no es un numero suelto: es una tabla "rango de minutos ->
categoria ganadora", que es lo que el dashboard dibuja.
"""
from bisect import bisect_right

import config
from filters import Filters, build_where


def _labels(edges: list[int]) -> list[tuple[str, int, int | None]]:
    """Convierte los cortes en rangos con nombre: [30, 60] -> 0-30, 30-60, 60+.

    Por que existe: los cortes que llegan son solo los limites interiores (30, 60).
    Hay que anteponer el 0 (no existe tiempo libre negativo) y dejar el ultimo rango
    abierto, porque alguien puede tener 8 horas libres y necesita caer en algun lado.
    Siempre salen len(edges)+1 rangos.
    """
    bounds = [0, *edges]
    out = []
    for i, lo in enumerate(bounds):
        # El ultimo rango no tiene tope: hi = None lo marca como abierto ("120+").
        hi = edges[i] if i < len(edges) else None
        out.append((f"{lo}-{hi}" if hi is not None else f"{lo}+", lo, hi))
    return out


def category_frequency(conn, f: Filters, edges: list[int] | None = None) -> dict:
    # Los cortes son configurables para poder responder la misma pregunta con otra
    # division (ej. 45,90) sin tocar el codigo: el negocio puede querer probar franjas
    # distintas. Si no mandan nada se usan los de la variable de entorno.
    edges = edges or config.free_time_edges()

    # build_where aplica los filtros comunes (fechas, version de la app) para que esta
    # metrica no repita esa logica ni quede desincronizada de las otras BQ.
    where, params = build_where(conn, f, ("recommended_activity_selected",))
    rows = conn.execute(
        f"SELECT user_id, activity_id, category, free_time_minutes FROM events "
        # Se excluye free_time_minutes = 0 porque significa "el usuario no tenia ningun
        # hueco libre en ese momento": esa seleccion no dice nada sobre la pregunta y
        # meterla inflaria artificialmente el primer rango.
        # El NULL SI pasa, porque es un caso distinto (nunca se midio el tiempo libre)
        # y se cuenta aparte mas abajo, en vez de confundirse con un cero.
        f"WHERE {where} AND (free_time_minutes IS NULL OR free_time_minutes > 0) "
        # Ordenado por tiempo para que, al deduplicar, la que sobreviva sea la PRIMERA
        # seleccion. received_at desempata cuando dos eventos traen el mismo occurred_at.
        f"ORDER BY occurred_at, received_at", params)

    # Una seleccion por (usuario, actividad): se queda la primera.
    # Por que deduplicar: la app reintenta el envio si falla la red, y un usuario puede
    # entrar y salir de la misma actividad varias veces. Sin esto, un solo estudiante
    # indeciso podria el solo decidir la categoria ganadora de un rango.
    unique: dict[tuple[str, str], tuple[str, int | None]] = {}
    for user_id, activity_id, category, minutes in rows:
        # setdefault y no asignacion directa: el primero que llega gana, el resto se ignora.
        unique.setdefault((user_id, activity_id), (category, minutes))

    buckets = _labels(edges)
    # Se arranca con TODAS las categorias en cero, no con un contador vacio, para que el
    # dashboard siempre reciba las mismas cuatro barras por rango. Si una categoria
    # faltara, la grafica cambiaria de forma entre recargas y seria imposible comparar.
    counts: list[dict[str, int]] = [{c: 0 for c in config.CATEGORIES} for _ in buckets]
    without_free_time = 0
    for category, minutes in unique.values():
        if minutes is None:
            # No se puede clasificar sin saber el tiempo libre. Se cuenta aparte en vez de
            # descartarlo en silencio: si este numero crece, es senal de que la app dejo de
            # mandar freeTimeMinutes y hay que arreglar la instrumentacion, no la metrica.
            without_free_time += 1
            continue
        # bisect_right ubica el rango en una sola operacion, sin recorrer la lista.
        # El corte pertenece al rango de ARRIBA: con cortes [30,60], 30 minutos no cae
        # en "0-30" sino en "30-60". Se eligio asi para que cada minuto pertenezca a un
        # unico rango y no haya ambiguedad en los bordes.
        bucket = counts[bisect_right(edges, minutes)]
        bucket[category] = bucket.get(category, 0) + 1

    result = []
    for (label, lo, hi), bucket in zip(buckets, counts):
        total = sum(bucket.values())
        # Orden: primero por conteo descendente y, a igualdad, alfabetico. El segundo
        # criterio existe para que el resultado sea DETERMINISTA: sin el, dos llamadas
        # con los mismos datos podrian devolver ganadores distintos y el dashboard
        # parpadearia. Alfabetico es arbitrario, pero estable.
        ordered = sorted(bucket.items(), key=lambda kv: (-kv[1], kv[0]))
        top_count = ordered[0][1]
        result.append({
            "label": label,
            "minMinutes": lo,
            "maxMinutes": hi,           # exclusivo; None = sin tope
            "total": total,
            # None y no un texto: un rango sin datos no tiene ganador, y el dashboard
            # necesita distinguir "nadie eligio nada aqui" de "gano una categoria".
            "topCategory": ordered[0][0] if total else None,
            # tie avisa que el ganador salio del desempate alfabetico y no porque domine
            # de verdad. Sin esta bandera el dashboard presentaria un empate con la misma
            # confianza que una victoria clara, y eso induciria a una mala decision.
            "tie": bool(total) and sum(1 for _, n in ordered if n == top_count) > 1,
            # Se devuelven todas las categorias con conteo y proporcion, no solo la
            # ganadora: el dashboard dibuja la distribucion completa, y "gano por poco"
            # frente a "gano arrasando" son conclusiones muy distintas.
            "categories": [
                {"category": c, "count": n, "share": (n / total) if total else 0.0} for c, n in ordered],
        })

    # selectionsWithoutFreeTime viaja al lado de los rangos y no se suma a ninguno:
    # es la medida de cuanto dato se quedo fuera, para que nadie lea los totales
    # creyendo que son todas las selecciones que hubo.
    return {"buckets": result, "selectionsWithoutFreeTime": without_free_time}
