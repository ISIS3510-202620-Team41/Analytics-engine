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
st.header("4 · Most selected category by free time")
cat = data.get("categoryByFreeTime", {})
buckets = cat.get("buckets", [])
if not any(b["total"] for b in buckets):
    st.info("No selections with a free-time duration yet.")
else:
    matrix = pd.DataFrame(
        {b["label"] + " min": {c["category"]: c["count"] for c in b["categories"]} for b in buckets}).T
    st.bar_chart(matrix, y_label="selections")
    winners = pd.DataFrame([{
        "Range (min)": b["label"],
        "Top category": b["topCategory"] or "—",
        "Tie": "yes" if b["tie"] else "",
        "Selections": b["total"]} for b in buckets])
    st.dataframe(winners, hide_index=True, use_container_width=True)
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