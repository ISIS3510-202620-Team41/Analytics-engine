import unittest
from datetime import timedelta
from uuid import uuid4

from db import connect
from filters import Filters
from metrics.time_to_select import time_to_select
from tests.helpers import HAS_FASTAPI, NOW, U1, U2, U3, ApiTestCase, DbTestCase, row


def shown(recommendation, user=U1, offset=0):
    return row("recommendation_shown", user=user, at=NOW + timedelta(seconds=offset),
               recommendation_id=recommendation)


def chosen(recommendation, user=U1, offset=0, activity="a1"):
    return row("recommended_activity_selected", user=user, at=NOW + timedelta(seconds=offset),
               recommendation_id=recommendation, activity_id=activity, category="DEPORTES")


class TimeToSelectTests(DbTestCase):
    def test_measures_seconds_between_load_and_selection(self):
        self.load([
            shown("r1", offset=0), chosen("r1", offset=5),
            shown("r2", U2, offset=0), chosen("r2", U2, offset=25),
            shown("r3", U3, offset=0), chosen("r3", U3, offset=120),
        ])
        with connect() as conn:
            result = time_to_select(conn, Filters())
        self.assertEqual(result["samples"], 3)
        self.assertEqual(result["averageSeconds"], 50.0)
        self.assertEqual(result["p50Seconds"], 25.0)
        self.assertEqual(result["p95Seconds"], 120.0)
        self.assertEqual((result["minSeconds"], result["maxSeconds"]), (5.0, 120.0))

    def test_one_sample_per_load_using_the_first_selection(self):
        """Unirse a dos actividades de la misma carga no cuenta dos veces."""
        self.load([
            shown("r1", offset=0),
            chosen("r1", offset=8, activity="a1"),
            chosen("r1", offset=90, activity="a2"),
        ])
        with connect() as conn:
            result = time_to_select(conn, Filters())
        self.assertEqual(result["samples"], 1)
        self.assertEqual(result["averageSeconds"], 8.0)

    def test_repeated_load_event_uses_the_earliest(self):
        self.load([shown("r1", offset=0), shown("r1", offset=40), chosen("r1", offset=50)])
        with connect() as conn:
            result = time_to_select(conn, Filters())
        self.assertEqual(result["averageSeconds"], 50.0)

    def test_histogram_buckets_and_shares(self):
        self.load([
            shown("r1", offset=0), chosen("r1", offset=5),       # 0-10
            shown("r2", U2, offset=0), chosen("r2", U2, offset=10),   # el borde 10 cae en 10-30
            shown("r3", U3, offset=0), chosen("r3", U3, offset=500),  # 180+
        ])
        with connect() as conn:
            result = time_to_select(conn, Filters())
        histogram = {b["label"]: b for b in result["histogram"]}
        self.assertEqual(list(histogram), ["0-10", "10-30", "30-60", "60-180", "180+"])
        self.assertEqual(histogram["0-10"]["count"], 1)
        self.assertEqual(histogram["10-30"]["count"], 1)
        self.assertEqual(histogram["30-60"]["count"], 0)
        self.assertEqual(histogram["180+"]["count"], 1)
        self.assertAlmostEqual(histogram["0-10"]["share"], 1 / 3)
        self.assertIsNone(histogram["180+"]["maxSeconds"])

    def test_custom_buckets(self):
        self.load([shown("r1", offset=0), chosen("r1", offset=45)])
        with connect() as conn:
            result = time_to_select(conn, Filters(), edges=[60])
        self.assertEqual([b["label"] for b in result["histogram"]], ["0-60", "60+"])
        self.assertEqual(result["histogram"][0]["count"], 1)

    def test_load_without_selection_is_reported_but_not_measured(self):
        self.load([shown("r1", offset=0), shown("r2", U2, offset=0), chosen("r2", U2, offset=12)])
        with connect() as conn:
            result = time_to_select(conn, Filters())
        self.assertEqual(result["samples"], 1)
        self.assertEqual(result["loadsWithoutSelection"], 1)

    def test_selection_without_load_or_without_id_is_reported(self):
        self.load([
            chosen("r-huerfana", offset=30),                                  # nunca se mostro
            row("recommended_activity_selected", user=U2, activity_id="a9",   # sin recommendationId
                category="CULTURA"),
        ])
        with connect() as conn:
            result = time_to_select(conn, Filters())
        self.assertEqual(result["samples"], 0)
        self.assertEqual(result["selectionsWithoutLoad"], 1)
        self.assertEqual(result["selectionsWithoutRecommendationId"], 1)

    def test_negative_elapsed_is_discarded(self):
        """Reloj del telefono desajustado: la seleccion llega antes que la carga."""
        self.load([shown("r1", offset=60), chosen("r1", offset=10)])
        with connect() as conn:
            result = time_to_select(conn, Filters())
        self.assertEqual(result["samples"], 0)
        self.assertEqual(result["discardedOutOfOrder"], 1)
        self.assertEqual(result["loadsWithoutSelection"], 0)

    def test_zero_seconds_counts_as_a_sample(self):
        self.load([shown("r1", offset=0), chosen("r1", offset=0)])
        with connect() as conn:
            result = time_to_select(conn, Filters())
        self.assertEqual(result["samples"], 1)
        self.assertEqual(result["averageSeconds"], 0.0)

    def test_no_data_returns_none_instead_of_zero(self):
        with connect() as conn:
            result = time_to_select(conn, Filters())
        self.assertEqual(result["samples"], 0)
        for key in ("averageSeconds", "p50Seconds", "p95Seconds", "minSeconds", "maxSeconds"):
            self.assertIsNone(result[key], key)
        self.assertEqual(sum(b["count"] for b in result["histogram"]), 0)

    def test_date_filter_applies(self):
        self.load([
            shown("r1", offset=0), chosen("r1", offset=5),
            shown("r2", U2, offset=7200), chosen("r2", U2, offset=7260),
        ])
        with connect() as conn:
            result = time_to_select(conn, Filters(from_=NOW + timedelta(seconds=3600)))
        self.assertEqual(result["samples"], 1)
        self.assertEqual(result["averageSeconds"], 60.0)


@unittest.skipUnless(HAS_FASTAPI, "fastapi/httpx no instalados")
class TimeToSelectApiTests(ApiTestCase):
    def test_endpoint_custom_buckets_and_summary(self):
        user = str(uuid4())
        recommendation = str(uuid4())
        self.client.post("/events", json={
            "eventType": "recommendation_shown", "userId": user, "recommendationId": recommendation})
        self.client.post("/events", json={
            "eventType": "recommended_activity_selected", "userId": user, "activityId": "a1",
            "category": "deportes", "recommendationId": recommendation})

        data = self.client.get("/metrics/time-to-select").json()
        self.assertEqual(data["samples"], 1)
        self.assertEqual([b["label"] for b in data["histogram"]], ["0-10", "10-30", "30-60", "60-180", "180+"])

        custom = self.client.get("/metrics/time-to-select?buckets=5").json()
        self.assertEqual([b["label"] for b in custom["histogram"]], ["0-5", "5+"])

        self.assertEqual(self.client.get("/metrics/time-to-select?buckets=60,30").status_code, 400)
        self.assertIn("timeToSelect", self.client.get("/metrics/summary").json())


if __name__ == "__main__":
    unittest.main()
