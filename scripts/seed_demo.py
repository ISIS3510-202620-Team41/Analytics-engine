"""Genera datos de prueba y los manda a un engine que ya este corriendo. Solo libreria estandar.

    python scripts/seed_demo.py --url http://localhost:8000 --users 30
    python scripts/seed_demo.py --ingest-key MI_LLAVE   # si configuraste ANALYTICS_INGEST_KEY
"""
import argparse
import json
import random
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

SCREENS = ["Home", "Recommendations", "FriendAvailability", "ActivityDetail", "Profile"]
CATEGORIES = ["DEPORTES", "ESTUDIO", "CULTURA", "ENTRETENIMIENTO"]
VERSIONS = ["0.9.0", "1.0.0", "1.1.0"]


def build_events(users: int, days: int, rng: random.Random) -> list[dict]:
    now = datetime.now(timezone.utc)
    events = []

    def add(user, at, version, event_type, **fields):
        events.append({"eventId": str(uuid.uuid4()), "eventType": event_type, "userId": user,
                       "appVersion": version, "timestamp": at.isoformat(), **fields})

    for _ in range(users):
        user, version = str(uuid.uuid4()), rng.choice(VERSIONS)
        for day in range(days):
            if rng.random() < 0.4:
                continue                                    # ese dia no uso la app
            at = now - timedelta(days=day, minutes=rng.randint(10, 600))
            add(user, at, version, "app_loading_time", loadType="cold_start",
                durationMs=max(200, int(rng.gauss(1400 if version == "0.9.0" else 850, 250))))
            for screen in rng.sample(SCREENS, 3):
                add(user, at, version, "screen_view", screen=screen)
                if rng.random() < (0.12 if screen == "ActivityDetail" else 0.02):
                    add(user, at, version, "crash", screen=screen,
                        component="btn_join" if screen == "ActivityDetail" else None,
                        exceptionType="NullPointerException")
            free = rng.choice([0, 20, 45, 90, 150])
            rec_id = str(uuid.uuid4())
            add(user, at, None, "recommendation_shown", recommendationId=rec_id, freeTimeMinutes=free)
            if free > 0 and rng.random() < 0.35:
                add(user, at, None, "recommended_activity_selected", activityId=str(uuid.uuid4()),
                    category=rng.choice(CATEGORIES), freeTimeMinutes=free, recommendationId=rec_id)
            if rng.random() < 0.25:
                add(user, at, None, "friend_availability_used",
                    action=rng.choice(["viewed", "viewed", "plan_created", "plan_joined"]))
    return events


def post(url: str, events: list[dict], key: str | None) -> dict:
    request = urllib.request.Request(
        f"{url}/events/batch", data=json.dumps({"events": events}).encode(),
        headers={"Content-Type": "application/json", **({"X-API-Key": key} if key else {})})
    with urllib.request.urlopen(request) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--users", type=int, default=30)
    parser.add_argument("--days", type=int, default=10)
    parser.add_argument("--seed", type=int, default=41)
    parser.add_argument("--ingest-key")
    args = parser.parse_args()

    events = build_events(args.users, args.days, random.Random(args.seed))
    accepted = duplicates = 0
    for i in range(0, len(events), 200):
        result = post(args.url, events[i:i + 200], args.ingest_key)
        accepted += result["accepted"]
        duplicates += result["duplicates"]
    print(f"Enviados {len(events)} eventos: {accepted} aceptados, {duplicates} duplicados.")
    print(f"Mira el resultado en {args.url}/docs  ->  GET /metrics/summary")


if __name__ == "__main__":
    main()