import unittest
from uuid import uuid4

import config
from db import connect
from filters import Filters
from metrics.category_frequency import category_frequency
from tests.helpers import HAS_FASTAPI, U1, U2, U3, U4, ApiTestCase, DbTestCase, row


def sel(user, activity, category, minutes):
    return row("recommended_activity_selected", user=user, activity_id=activity, category=category,
               free_time_minutes=minutes)


class CategoryFrequencyTests(DbTestCase):
    def test_buckets_and_winner_per_bucket(self):
        self.load([
            sel(U1, "a1", "DEPORTES", 20),
            sel(U1, "a2", "ESTUDIO", 30),             # el borde 30 cae en 30-60
            sel(U2, "a3", "ESTUDIO", 45),
            sel(U3, "a4", "CULTURA", 90),
            sel(U3, "a5", "ENTRETENIMIENTO", 200),
            sel(U4, "a5", "DEPORTES", 200),           # misma actividad, otro usuario: cuenta aparte
            sel(U4, "a6", "CULTURA", 0),              # sin tiempo libre: se ignora
            sel(U4, "a7", "CULTURA", None),           # sin duracion: se reporta aparte
            sel(U1, "a1", "DEPORTES", 20),            # duplicado: no suma
        ])
        with connect() as conn:
            result = category_frequency(conn, Filters())
        buckets = {b["label"]: b for b in result["buckets"]}
        self.assertEqual(list(buckets), ["0-30", "30-60", "60-120", "120+"])
        self.assertEqual((buckets["0-30"]["topCategory"], buckets["0-30"]["total"]), ("DEPORTES", 1))
        self.assertEqual((buckets["30-60"]["topCategory"], buckets["30-60"]["total"]), ("ESTUDIO", 2))
        self.assertEqual(buckets["60-120"]["topCategory"], "CULTURA")
        self.assertEqual(buckets["120+"]["total"], 2)
        self.assertTrue(buckets["120+"]["tie"])
        self.assertEqual(result["selectionsWithoutFreeTime"], 1)

    def test_custom_buckets_and_ties(self):
        self.load([sel(U1, "a1", "DEPORTES", 10), sel(U2, "a2", "ESTUDIO", 10)])
        with connect() as conn:
            result = category_frequency(conn, Filters(), edges=[60])
        first = result["buckets"][0]
        self.assertEqual(first["label"], "0-60")
        self.assertTrue(first["tie"])
        self.assertEqual(first["topCategory"], "DEPORTES")      # desempate alfabetico
        self.assertIsNone(result["buckets"][1]["topCategory"])

    def test_every_bucket_lists_every_category(self):
        with connect() as conn:
            result = category_frequency(conn, Filters())
        for bucket in result["buckets"]:
            self.assertEqual({c["category"] for c in bucket["categories"]}, set(config.CATEGORIES))


@unittest.skipUnless(HAS_FASTAPI, "fastapi/httpx no instalados")
class CategoryFrequencyApiTests(ApiTestCase):
    def test_endpoint_custom_buckets_and_summary(self):
        user = str(uuid4())
        event = {"eventType": "recommended_activity_selected", "userId": user, "activityId": "a",
                 "category": "cultura", "freeTimeMinutes": 45}
        self.client.post("/events", json=event)
        data = self.client.get("/metrics/category-by-free-time").json()
        self.assertEqual(next(b for b in data["buckets"] if b["label"] == "30-60")["topCategory"], "CULTURA")
        self.assertEqual(self.client.get("/metrics/category-by-free-time?buckets=60,30").status_code, 400)
        self.assertIn("categoryByFreeTime", self.client.get("/metrics/summary").json())


if __name__ == "__main__":
    unittest.main()