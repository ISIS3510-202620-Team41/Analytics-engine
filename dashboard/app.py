"""Llamalla Analytics dashboard (Streamlit).

    pip install -r dashboard/requirements.txt
    streamlit run dashboard/app.py

Optional env vars: ANALYTICS_URL (default http://localhost:8000) and ANALYTICS_ADMIN_KEY.
"""
import os
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="Llamalla Analytics", page_icon="📊", layout="wide")

def pct(value) -> str:
    return "no data" if value is None else f"{value * 100:.1f}%"


def secs(value) -> str:
    return "no data" if value is None else f"{value:.1f} s"


@st.cache_data(ttl=20, show_spinner=False)
def fetch_summary(url: str, key: str, params: tuple) -> dict:
    headers = {"X-API-Key": key} if key else {}
    response = requests.get(f"{url}/metrics/summary", params=dict(params), headers=headers, timeout=10)
    response.raise_for_status()
    return response.json()


# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.header("Connection")
    url = st.text_input("Engine URL", os.getenv("ANALYTICS_URL", "http://localhost:8000")).rstrip("/")
    key = st.text_input("API key (admin)", os.getenv("ANALYTICS_ADMIN_KEY", ""), type="password")

    st.header("Filters")
    period = st.selectbox("Period", ["Last 24 hours", "Last 7 days", "Last 30 days", "All time"], index=1)
    min_version = st.text_input("Minimum app version", placeholder="1.0.0")
    exact_version = st.text_input("Only this version", placeholder="1.2.0")
    active_days = st.slider("Days to consider a user active", 1, 30, 7)
    if st.button("Refresh"):
        fetch_summary.clear()

days = {"Last 24 hours": 1, "Last 7 days": 7, "Last 30 days": 30, "All time": None}[period]
params = {}
if days:
    params["from"] = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
if min_version.strip():
    params["minAppVersion"] = min_version.strip()
if exact_version.strip():
    params["appVersion"] = exact_version.strip()

st.title("Llamalla · Analytics")
st.caption(f"Engine: {url} · Period: {period}")

try:
    data = fetch_summary(url, key, tuple(sorted(params.items())))
    # Friend Availability uses its own window (activeDays), requested separately.
    fa_params = {k: v for k, v in params.items() if k != "from"} | {"activeDays": active_days}
    headers = {"X-API-Key": key} if key else {}
    fa = requests.get(f"{url}/metrics/friend-availability", params=fa_params, headers=headers, timeout=10)
    fa.raise_for_status()
    data["friendAvailability"] = fa.json()

    # BQ8 uses its own rolling window, independent of the global period.
    adoption_params = {
        k: v for k, v in params.items()
        if k not in {"from", "to"}
    } | {"windowDays": 7}

    adoption = requests.get(
        f"{url}/metrics/feature-adoption",
        params=adoption_params,
        headers=headers,
        timeout=10,
    )
    adoption.raise_for_status()
    data["featureAdoption"] = adoption.json()

except requests.ConnectionError:
    st.error(f"Could not connect to the engine at {url}. Is `uvicorn main:app --port 8000` running?")
    st.stop()
except requests.HTTPError as exc:
    if exc.response.status_code == 401:
        st.error("Invalid API key. Check the admin key in the sidebar.")
    else:
        st.error(f"The engine returned an error: {exc}")
    st.stop()

# ------------------------------------------------------------------ BQ1
st.header("1 · App loading time")
lt = data.get("loadingTime", {})
c1, c2, c3, c4 = st.columns(4)
c1.metric("Average (cold start)", "—" if lt.get("averageMs") is None else f"{lt['averageMs']:.0f} ms")
c2.metric("p50", "—" if lt.get("p50Ms") is None else f"{lt['p50Ms']} ms")
c3.metric("p95", "—" if lt.get("p95Ms") is None else f"{lt['p95Ms']} ms")
c4.metric("Samples", lt.get("samples", 0))
if lt.get("underThreshold") is None:
    st.info("No startup measurements yet.")
elif lt["underThreshold"]:
    st.success(f"Meets the goal: the average is below {lt['thresholdMs']} ms.")
else:
    st.error(f"Does not meet the goal: the average exceeds {lt['thresholdMs']} ms.")

# ------------------------------------------------------------------ BQ2
st.header("2 · Crash rate by screen")
cr = data.get("crashRate", {})
screens = cr.get("screens", [])
if not screens:
    st.info("No screen views or crashes yet.")
else:
    left, right = st.columns([3, 2])
    df = pd.DataFrame(screens)
    df["crashRate"] = df["crashRate"].fillna(0.0)
    left.bar_chart(df.set_index("screen")["crashRate"], y_label="crashes / views")
    highest = cr.get("highest")
    right.metric("Screen with highest rate", highest["screen"] if highest else "No crashes",
                 pct(highest["crashRate"]) if highest else None)
    right.metric("Overall rate", pct(cr.get("overallCrashRate")))
    table = df[["screen", "views", "crashes", "crashRate"]].copy()
    table.columns = ["Screen", "Views", "Crashes", "Crash rate"]
    table["Crash rate"] = table["Crash rate"].map(pct)
    table["Most frequent component"] = [
        (s["components"][0]["component"] or "—") if s["components"] else "—" for s in screens]
    st.dataframe(table, hide_index=True, use_container_width=True)

# ------------------------------------------------------------------ BQ3
st.header("3 · Recommendations selected during free time")
sr = data.get("selectionRate", {})
c1, c2, c3, c4 = st.columns(4)
c1.metric("Selection rate", pct(sr.get("selectionRate")),
          help="Unique (user, activity) joins / recommendation loads with free time")
c2.metric("Unique selections", sr.get("selected", 0))
c3.metric("Loads shown", sr.get("shown", 0))
c4.metric("Loads with at least one join", pct(sr.get("loadSelectionRate")), help="Never exceeds 100%")

# ------------------------------------------------------------------ BQ4
# Que responde: con X minutos libres, ¿que tipo de plan escoge el estudiante?
# Se dibuja como barras apiladas por rango para poder comparar de un vistazo si la
# categoria ganadora cambia al crecer el tiempo disponible, que es el patron que el
# motor de recomendaciones necesita conocer.
st.header("4 · Most selected category by free time")
cat = data.get("categoryByFreeTime", {})
buckets = cat.get("buckets", [])
# any(total) y no "if buckets": el motor SIEMPRE devuelve los rangos, aunque esten
# vacios. Preguntar por los totales distingue "no hay datos" de "hay rangos en cero".
if not any(b["total"] for b in buckets):
    st.info("No selections with a free-time duration yet.")
else:
    # Matriz rango x categoria. El .T transpone para que cada FILA sea un rango: asi
    # st.bar_chart pone los rangos en el eje X y apila las categorias dentro de cada uno.
    matrix = pd.DataFrame(
        {b["label"] + " min": {c["category"]: c["count"] for c in b["categories"]} for b in buckets}).T
    # Categorical conserva el orden en que vienen del motor (0-30, 30-60, 60-120, 120+).
    # Sin esto pandas ordena las etiquetas como TEXTO y "120+" queda de segundo, lo que
    # rompe la lectura: el punto de la grafica es ver la progresion al subir los minutos.
    matrix.index = pd.CategoricalIndex(matrix.index, categories=matrix.index, ordered=True)
    st.bar_chart(matrix, y_label="selections")
    # La tabla repite la conclusion en texto porque la grafica apilada no deja leer con
    # precision quien gano cuando dos categorias quedan casi iguales.
    winners = pd.DataFrame([{
        "Range (min)": b["label"],
        # El guion cubre el rango sin datos, donde topCategory viene en None.
        "Top category": b["topCategory"] or "—",
        # Se muestra el empate para que nadie lea el ganador como si dominara: lo decidio
        # el desempate alfabetico, no los usuarios.
        "Tie": "yes" if b["tie"] else "",
        "Selections": b["total"]} for b in buckets])
    st.dataframe(winners, hide_index=True, use_container_width=True)
    # Solo se escribe la nota si de verdad quedo algo fuera, para no ensuciar la vista
    # con un "0 selecciones excluidas" en el caso normal.
    if cat.get("selectionsWithoutFreeTime"):
        st.caption(f"{cat['selectionsWithoutFreeTime']} selections without a duration are not in the chart.")

# ------------------------------------------------------------------ BQ5
st.header("5 · Friend Availability usage")
fa = data.get("friendAvailability", {})
c1, c2, c3, c4 = st.columns(4)
c1.metric("% of active users who use it", pct(fa.get("usageRate")))
c2.metric("Active users", fa.get("activeUsers", 0),
          help=f"With any event in the last {fa.get('activeDays', active_days)} days")
c3.metric("Used it", fa.get("usersUsingFeature", 0))
c4.metric("Created or joined a plan", pct(fa.get("planActionRate")))

# ------------------------------------------------------------------ BQ6
st.header("6 · Time from seeing recommendations to joining one")
tts = data.get("timeToSelect", {})
if not tts.get("samples"):
    st.info("No recommendation load has ended in a join yet.")
else:
    # Los tres numeros van juntos a proposito: el promedio resume, el p50 dice que le
    # pasa al usuario tipico y el p95 expone la cola de los que se atascan. Mirar solo
    # el promedio esconde justamente a quienes hay que arreglarles la experiencia.
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Average", secs(tts.get("averageSeconds")),
              # El help deja escrita la unidad de medida en la propia vista, para que
              # nadie interprete el numero como "por cada join".
              help="One sample per recommendation load, measured to its first join")
    c2.metric("p50", secs(tts.get("p50Seconds")))
    c3.metric("p95", secs(tts.get("p95Seconds")))
    # Samples da el peso estadistico: un p95 sacado de 4 muestras no se puede defender.
    c4.metric("Samples", tts.get("samples", 0))

    histogram = pd.DataFrame(tts["histogram"])
    # Categorical conserva el orden en que vienen los rangos del motor. Sin esto pandas
    # ordena las etiquetas como TEXTO y "180+" quedaria entre "10-30" y "30-60",
    # destruyendo la lectura de la distribucion.
    histogram["Range (s)"] = pd.Categorical(
        histogram["label"], categories=histogram["label"], ordered=True)
    # El histograma es el corazon de esta BQ: el promedio solo no distingue "todos tardan
    # 60 s" de "la mitad tarda 5 s y la otra mitad 115 s", y cada caso pide otro arreglo.
    st.bar_chart(histogram.set_index("Range (s)")["count"], y_label="joins")

    # La tabla acompana a la grafica con el numero exacto y el porcentaje, que no se
    # pueden leer con precision de una barra.
    table = histogram[["label", "count", "share"]].copy()
    table.columns = ["Range (s)", "Joins", "Share"]
    table["Share"] = table["Share"].map(pct)
    st.dataframe(table, hide_index=True, use_container_width=True)

    # Sin esta nota, alguien compara el total de BQ6 con el de BQ3, ve que no cuadran y
    # asume que la metrica esta mal. Aqui queda explicado dato por dato que se excluyo.
    ignored = [
        (tts.get("loadsWithoutSelection"), "loads ended without a join"),
        (tts.get("selectionsWithoutLoad"), "joins whose recommendation load is outside this period"),
        (tts.get("selectionsWithoutRecommendationId"), "joins made outside the recommendations screen"),
        (tts.get("discardedOutOfOrder"), "joins discarded because the device clock was behind"),
    ]
    note = " · ".join(f"{n} {text}" for n, text in ignored if n)
    if note:
        st.caption(f"Not in the chart: {note}.")

# ------------------------------------------------------------------ BQ7
st.header("7 · Activity Duration vs Available Free Time")
dm = data.get("durationMatch", {})

if not dm.get("totalUniqueSelections"):
    st.info("No activity selections recorded yet to evaluate duration match.")
else:
    c1, c2, c3, c4 = st.columns(4)

    valid_selections = dm.get("validSelections", 0)

    # Check for valid data before displaying rates using standard blocks
    if valid_selections == 0:
        match_str = "No valid data"
        overflow_str = "No valid data"
    else:
        match_str = pct(dm.get("matchRate"))
        overflow_str = pct(dm.get("overflowRate"))

    c1.metric("Overall Match Rate", match_str, help="Proportion of valid selections where activity duration <= free time")
    c2.metric("Overall Overflow Rate", overflow_str, help="Proportion of valid selections exceeding available free time")
    c3.metric("Missing Data Rate", pct(dm.get("missingRate")), help="Selections missing either free time or activity duration")
    c4.metric("Valid Selections Analyzed", valid_selections, help="Total unique selections excluding missing data")

    categories = dm.get("categories", {})
    if categories:
        st.subheader("Match/Overflow Rates by Category")

        # Prepare DataFrame for stacked bar chart using standard loops and blocks
        chart_data = {}
        for cat, stats in categories.items():
            if stats["validSelections"] > 0:
                chart_data[cat] = {
                    "Fits within free time": stats["matchRate"] * 100,
                    "Exceeds free time": stats["overflowRate"] * 100
                }

        if chart_data:
            df_chart = pd.DataFrame(chart_data).T
            st.bar_chart(df_chart, y_label="Percentage (%)", height=300)

        # Prepare table data for category breakdown
        table_rows = []
        for cat, stats in categories.items():
            cat_valid = stats.get("validSelections", 0)

            # Format category rates using standard blocks
            if cat_valid == 0:
                cat_match_str = "—"
                cat_overflow_str = "—"
            else:
                cat_match_str = pct(stats["matchRate"])
                cat_overflow_str = pct(stats["overflowRate"])

            table_rows.append({
                "Category": cat,
                "Matches": stats["matches"],
                "Overflows": stats["overflows"],
                "Missing Data": stats["missingValues"],
                "Match Rate": cat_match_str,
                "Overflow Rate": cat_overflow_str,
            })

        st.dataframe(pd.DataFrame(table_rows), hide_index=True, use_container_width=True)

# ------------------------------------------------------------------ BQ8
st.header("8 · Feature adoption among active users")

ad = data.get("featureAdoption", {})
screens = ad.get("screens", [])

if not screens:
    st.info("No screen usage data yet.")
else:
    st.metric("Active users (last 7 days)", ad.get("activeUsers", 0))

    # Exclude undefined adoption rates from the chart.
    chart_screens = [
        s for s in screens
        if s["adoptionRate"] is not None
    ]

    if chart_screens:
        chart_df = pd.DataFrame([
            {
                "Screen": s["screen"],
                "Usage (%)": s["adoptionRate"] * 100,
            }
            for s in chart_screens
        ]).set_index("Screen")

        st.bar_chart(
            chart_df,
            y_label="% of active users",
        )
        st.caption("Underutilization threshold: below 40%.")
    else:
        st.info("No active users in the selected window.")

    # Highlight underutilized screens.
    underutilized = [
        s for s in screens if s["underutilized"]
    ]

    if underutilized:
        names = ", ".join(s["screen"] for s in underutilized)
        st.warning(f"Below 40% adoption: {names}")

    # Keep a status table alongside the chart.
    table = pd.DataFrame([
        {
            "Screen": s["screen"],
            "Unique users": s["uniqueUsers"],
            "Adoption": (
                pct(s["adoptionRate"])
                if s["adoptionRate"] is not None
                else "No data"
            ),
            "Status": (
                "Underutilized"
                if s["underutilized"]
                else "No data"
                if s["adoptionRate"] is None
                else "OK"
            ),
        }
        for s in screens
    ])

    st.dataframe(
        table,
        hide_index=True,
        use_container_width=True,
    )
    

# ------------------------------------------------------------------ BQ9
st.header("9 · Category and Activity Demand by Time Slot (Commercial Partnerships)")
cd = data.get("categoryDemand", {})
slots = cd.get("timeSlots", [])
if not cd.get("totalSelectionsOverall"):
    st.info("No activity selections recorded yet.")
else:
    c1, c2, c3 = st.columns(3)
    c1.metric("Total Selections", cd.get("totalSelectionsOverall", 0))
    c2.metric("Top Category Overall", cd.get("topCategoryOverall") or "—")
    c3.metric("Peak Time Slot", cd.get("peakTimeSlot") or "—")

    matrix_data = {}
    for s in slots:
        label = s["label"].split(" (")[0]
        matrix_data[label] = {c["category"]: c["count"] for c in s.get("categories", [])}
    if matrix_data:
        st.subheader("Selections by Time Slot and Category")
        st.bar_chart(pd.DataFrame(matrix_data).T, y_label="selections")

    st.subheader("Commercial Partnership Opportunities")
    table_rows = []
    for s in slots:
        top_acts = ", ".join(f"{a['title']} ({a['count']})" for a in s.get("topActivities", [])) or "—"
        table_rows.append({
            "Franja Horaria": s["label"],
            "Selecciones": s["totalSelections"],
            "Categoría Líder": (s["topCategory"] or "—") + (" (Empate)" if s.get("tie") else ""),
            "Actividades Principales": top_acts,
            "Oportunidad de Alianza / Monetización": s.get("monetizationOpportunity", "—"),
        })
    st.dataframe(pd.DataFrame(table_rows), hide_index=True, use_container_width=True)

    # ------------------------------------------------------------------ BQ10
st.header("10 · Network quality impact on loading and selection")

ni = data.get("networkImpact", {})
rows = ni.get("byNetworkQuality", [])

if not rows:
    st.info("No network quality measurements yet.")
else:
    df = pd.DataFrame(rows)

    # Resumen de los datos disponibles
    total_loads = int(df["recommendationLoads"].sum())
    total_samples = int(df["loadingSamples"].sum())

    c1, c2 = st.columns(2)
    c1.metric("Recommendation loads", total_loads)
    c2.metric("Loading time samples", total_samples)

    # Comparacion del tiempo promedio de carga
    st.subheader("Average recommendation loading time")

    loading_df = df.dropna(
        subset=["averageLoadingMs"]
    ).copy()

    if loading_df.empty:
        st.info("No loading time measurements yet.")
    else:
        chart_df = loading_df.set_index(
            "networkQuality"
        )[["averageLoadingMs"]]

        st.bar_chart(
            chart_df,
            y_label="Milliseconds",
        )

    # Comparacion de las tasas de seleccion
    st.subheader("Selection rate by network quality")

    selection_df = df.dropna(
        subset=["selectionRate"]
    ).copy()

    if selection_df.empty:
        st.info("No linked recommendation selections yet.")
    else:
        chart_df = selection_df.set_index(
            "networkQuality"
        )[["selectionRate"]]

        st.bar_chart(
            chart_df,
            y_label="Proportion (0 to 1)",
        )

    # Tabla detallada
    st.subheader("Network quality details")

    table = df[
        [
            "networkQuality",
            "averageLoadingMs",
            "loadingSamples",
            "recommendationLoads",
            "loadsWithSelection",
            "selectionRate",
        ]
    ].copy()

    table.columns = [
        "Network quality",
        "Average loading (ms)",
        "Loading samples",
        "Recommendation loads",
        "Loads with selection",
        "Selection rate",
    ]

    table["Selection rate"] = table[
        "Selection rate"
    ].map(
        lambda value: (
            "No data"
            if pd.isna(value)
            else f"{value * 100:.1f}%"
        )
    )
    st.dataframe(
        table,
        hide_index=True,
        use_container_width=True,
    )