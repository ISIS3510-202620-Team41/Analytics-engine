"""BQ6: ¿cuantos segundos pasan entre que al estudiante le muestran las recomendaciones y elige una?

PROPOSITO DE NEGOCIO
--------------------
Es una pregunta de eficiencia, no de gusto. Mide cuanto le cuesta al usuario DECIDIR
una vez que ya tiene la lista enfrente. Si el promedio y el p95 se disparan, quiere
decir que la lista no esta ayudando: o muestra demasiadas opciones, o no son
relevantes, o la informacion de cada tarjeta no alcanza para decidir sin entrar.
Es la senal mas directa de si el motor de recomendaciones esta haciendo bien su trabajo.

Se reporta promedio, p50 y p95 porque los tres cuentan cosas distintas: el promedio
resume, el p50 dice que le pasa al usuario tipico, y el p95 expone la cola de los que
se quedan atascados, que es justamente a quienes hay que arreglarles la experiencia.

DECISION CLAVE: LA UNIDAD DE MEDIDA
-----------------------------------
La unidad es la CARGA de recomendaciones (recommendationId), no el evento suelto.
Cada carga que termino en un join aporta una muestra, medida hasta la PRIMERA
seleccion. Si el usuario se une a dos actividades de la misma lista, eso sigue siendo
una sola decision: contar la segunda como otra muestra inflaria el promedio con un
tiempo que ya no mide "cuanto tardo en decidir", sino "cuanto se quedo navegando".
"""
import math
from bisect import bisect_right
from datetime import datetime

import config
from filters import Filters, build_where

# Formato exacto con el que filters.to_db_time escribe las fechas. Se guarda como texto
# fijo en UTC para que comparar cadenas equivalga a comparar instantes, y asi SQLite
# pueda ordenar y agrupar por fecha sin funciones de fecha propias del motor.
_DB_FORMAT = "%Y-%m-%dT%H:%M:%S.%f%z"


def _parse(timestamp: str) -> datetime:
    """Texto de la base -> datetime, para poder restar dos instantes.

    Se parsea en Python y no en SQL a proposito: las funciones de fecha de SQLite no
    aceptan los 6 decimales de microsegundos ni la 'Z' final, y hacerlo aqui mantiene
    el SQL portable si algun dia se migra a Postgres.
    """
    return datetime.strptime(timestamp, _DB_FORMAT)


def _percentile(sorted_values: list[float], p: float) -> float | None:
    """Percentil por rango mas cercano, el mismo metodo que usa BQ1.

    Por que el mismo metodo: para que "p95" signifique exactamente lo mismo en todo el
    dashboard. Si cada metrica interpolara distinto, comparar dos p95 no tendria sentido.
    Devuelve None y no 0 cuando no hay datos, porque "no se midio" no es "tardo 0 s".
    """
    if not sorted_values:
        return None
    # Rango mas cercano: el valor real de la muestra que deja p% por debajo. No interpola,
    # asi que el resultado siempre es un tiempo que de verdad le paso a alguien.
    index = max(math.ceil(p / 100 * len(sorted_values)) - 1, 0)
    return sorted_values[index]


def _labels(edges: list[int]) -> list[tuple[str, int, int | None]]:
    """Cortes -> rangos con nombre: [10, 30] -> 0-10, 10-30, 30+.

    Mismo criterio que BQ4: se antepone el 0 y el ultimo rango queda abierto, porque
    siempre puede haber alguien que tarde muchisimo y tiene que caer en algun lado.
    """
    bounds = [0, *edges]
    return [(f"{lo}-{edges[i]}" if i < len(edges) else f"{lo}+", lo, edges[i] if i < len(edges) else None)
            for i, lo in enumerate(bounds)]


def _first_occurrence(conn, where: str, params: list) -> dict[str, str]:
    """{recommendationId: instante del primer evento de ese tipo para esa carga}.

    Por que MIN y no el evento tal cual: tanto la carga como el join pueden llegar
    repetidos (la app reintenta cuando falla la red, o el usuario recarga la lista).
    Quedarse con el mas temprano hace que la medicion sea estable: el inicio es la
    primera vez que vio la lista y el fin es la primera vez que eligio.

    Las filas sin recommendationId se excluyen aqui porque no hay con que emparejarlas;
    se cuentan por separado en time_to_select para no perderlas de vista.
    """
    return dict(conn.execute(
        f"SELECT recommendation_id, MIN(occurred_at) FROM events "
        f"WHERE {where} AND recommendation_id IS NOT NULL GROUP BY recommendation_id", params))


def time_to_select(conn, f: Filters, edges: list[int] | None = None) -> dict:
    # Cortes configurables: permite mirar la misma distribucion con otro detalle
    # (ej. 5,15 para enfocarse en los que deciden rapido) sin tocar el codigo.
    edges = edges or config.time_to_select_edges()

    # Dos WHERE separados porque son dos tipos de evento distintos, pero ambos pasan por
    # build_where para que los filtros de fecha y version se apliquen igual a los dos
    # lados de la resta. Si solo se filtrara uno, se emparejarian cargas y joins de
    # periodos diferentes y los tiempos saldrian absurdos.
    where_shown, p_shown = build_where(conn, f, ("recommendation_shown",))
    where_selected, p_selected = build_where(conn, f, ("recommended_activity_selected",))

    shown = _first_occurrence(conn, where_shown, p_shown)        # inicio del cronometro
    selected = _first_occurrence(conn, where_selected, p_selected)  # fin del cronometro

    # Un join sin recommendationId es alguien que entro a la actividad por otro camino
    # (buscador, link de un amigo, detalle directo). No tiene inicio que medir, asi que
    # no es una muestra; pero se cuenta para poder decir en el dashboard cuantos joins
    # quedaron fuera y por que. Se deduplica por (usuario, actividad) igual que en BQ4,
    # para que un reintento de red no se vea como dos joins distintos.
    without_id = conn.execute(
        f"SELECT COUNT(*) FROM (SELECT DISTINCT user_id, activity_id FROM events "
        f"WHERE {where_selected} AND recommendation_id IS NULL)", p_selected).fetchone()[0]

    seconds: list[float] = []
    out_of_order = 0   # descartados por reloj desajustado
    orphan = 0         # joins cuya carga no esta en el periodo consultado

    # Se recorre desde los joins y no desde las cargas porque solo las cargas que
    # terminaron en join producen una medicion: una lista que el usuario miro y abandono
    # no tiene un "fin" que restar.
    for recommendation_id, selected_at in selected.items():
        shown_at = shown.get(recommendation_id)
        if shown_at is None:
            # Hay join pero no se ve la carga. Pasa cuando la carga ocurrio antes del
            # rango de fechas filtrado. No es un error: es un recorte de la ventana, y
            # por eso se reporta aparte en vez de descartarse en silencio.
            orphan += 1
            continue
        elapsed = (_parse(selected_at) - _parse(shown_at)).total_seconds()
        # Negativo = el reloj del telefono esta atrasado y el join quedo fechado antes
        # que la carga. Se descarta porque un tiempo negativo no es una decision rapida,
        # es un dato malo, y meterlo bajaria el promedio sin que nada haya mejorado.
        if elapsed < 0:
            out_of_order += 1
            continue
        # El 0 exacto SI se acepta: significa que el usuario eligio en menos de un
        # segundo, que es un dato legitimo y ademas interesante.
        seconds.append(elapsed)

    # Ordenar es obligatorio antes de sacar percentiles (el metodo de rango mas cercano
    # asume la lista ordenada) y de paso deja listos el minimo y el maximo.
    seconds.sort()
    samples = len(seconds)
    # None y no 0 cuando no hay muestras: "no hay datos" y "tardaron 0 segundos" son
    # conclusiones opuestas, y el dashboard tiene que poder distinguirlas.
    average = sum(seconds) / samples if samples else None

    buckets = _labels(edges)
    counts = [0] * len(buckets)
    for value in seconds:
        # bisect_right ubica el rango en una operacion. El corte pertenece al rango de
        # arriba: con cortes [10,30], exactamente 10 s cae en "10-30". Mismo criterio
        # que BQ4, para que los bordes se lean igual en todo el dashboard.
        counts[bisect_right(edges, value)] += 1

    # El histograma es lo que responde la pregunta de verdad: el promedio solo no
    # distingue "todos tardan 60 s" de "la mitad tarda 5 s y la otra mitad 115 s",
    # y esas dos situaciones exigen arreglos distintos.
    histogram = []
    for (label, lo, hi), count in zip(buckets, counts):
        histogram.append({
            "label": label,
            "minSeconds": lo,
            "maxSeconds": hi,              # exclusivo; None = sin tope
            "count": count,
            # share ya calculado aqui y no en el dashboard: la proporcion es parte de la
            # respuesta, y asi cualquier cliente del API la ve igual sin recalcularla.
            "share": (count / samples) if samples else 0.0,
        })

    return {
        "samples": samples,
        # Se redondea a un decimal solo el promedio, que es el unico valor derivado;
        # los percentiles, el minimo y el maximo son muestras reales y se dejan intactas.
        "averageSeconds": round(average, 1) if average is not None else None,
        "p50Seconds": _percentile(seconds, 50),
        "p95Seconds": _percentile(seconds, 95),
        "minSeconds": seconds[0] if samples else None,
        "maxSeconds": seconds[-1] if samples else None,
        "histogram": histogram,

        # ---- Diagnostico: por que una carga o un join no produjo muestra ----
        # Van en la respuesta para que el dashboard pueda explicar la diferencia entre
        # "cuantos joins hubo" y "cuantos se midieron". Sin esto, alguien compara el
        # total de BQ6 con el de BQ3, ve que no cuadran y asume que hay un error.

        # Cargas que el usuario vio y abandono. Se restan las que si midieron y las
        # descartadas por reloj, porque esas si tuvieron join: no fueron abandonos.
        "loadsWithoutSelection": len(shown) - (samples + out_of_order),
        "selectionsWithoutLoad": orphan,
        "selectionsWithoutRecommendationId": without_id,
        "discardedOutOfOrder": out_of_order,
    }
