import unittest
from datetime import timedelta
from uuid import uuid4

from db import connect
from filters import Filters
from metrics.loading_time import loading_time
from tests.helpers import HAS_FASTAPI, NOW, ApiTestCase, DbTestCase, row


class LoadingTimeTests(DbTestCase):
    def test_average_percentiles_and_threshold(self):
        self.load([
            row("app_loading_time", load_type="cold_start", duration_ms=800, app_version="1.2.0"),
            row("app_loading_time", load_type="cold_start", duration_ms=900, app_version="1.2.0"),
            row("app_loading_time", load_type="cold_start", duration_ms=1200, app_version="1.2.0"),
            row("app_loading_time", load_type="warm_start", duration_ms=50, app_version="1.2.0"),
        ])
        with connect() as conn:
            result = loading_time(conn, Filters())
        self.assertEqual(result["samples"], 3)
        self.assertEqual(result["averageMs"], 966.7)
        self.assertEqual(result["p50Ms"], 900)
        self.assertEqual(result["p95Ms"], 1200)
        self.assertTrue(result["underThreshold"])

    def test_old_versions_are_excluded_with_min_app_version(self):
        self.load([
            row("app_loading_time", load_type="cold_start", duration_ms=5000, app_version="0.9.0"),
            row("app_loading_time", load_type="cold_start", duration_ms=500, app_version="1.2.0"),
        ])
        with connect() as conn:
            all_versions = loading_time(conn, Filters())
            recent = loading_time(conn, Filters(min_app_version="1.0.0"))
        self.assertFalse(all_versions["underThreshold"])
        self.assertTrue(recent["underThreshold"])
        self.assertEqual(recent["samples"], 1)

    def test_screen_loads_can_be_filtered_by_screen(self):
        self.load([
            row("app_loading_time", load_type="screen", screen="Home", duration_ms=300),
            row("app_loading_time", load_type="screen", screen="Profile", duration_ms=900),
        ])
        with connect() as conn:
            result = loading_time(conn, Filters(), load_type="screen", screen="Home")
        self.assertEqual((result["samples"], result["averageMs"]), (1, 300.0))

    def test_no_samples_is_none_not_false(self):
        with connect() as conn:
            result = loading_time(conn, Filters())
        self.assertIsNone(result["underThreshold"])
        self.assertIsNone(result["averageMs"])

    def test_time_filters(self):
        self.load([
            row("app_loading_time", load_type="cold_start", duration_ms=500, at=NOW - timedelta(days=10)),
            row("app_loading_time", load_type="cold_start", duration_ms=1500, at=NOW),
        ])
        with connect() as conn:
            result = loading_time(conn, Filters(from_=NOW - timedelta(days=1)))
        self.assertEqual((result["samples"], result["averageMs"]), (1, 1500.0))


@unittest.skipUnless(HAS_FASTAPI, "fastapi/httpx no instalados")
class LoadingTimeApiTests(ApiTestCase):
    def test_endpoint_and_summary(self):
        user = str(uuid4())
        events = [{"eventType": "app_loading_time", "userId": user, "loadType": "cold_start",
                   "durationMs": 700, "appVersion": "1.0.0"}]
        self.client.post("/events/batch", json={"events": events})
        self.assertTrue(self.client.get("/metrics/loading-time").json()["underThreshold"])
        self.assertIn("loadingTime", self.client.get("/metrics/summary").json())


if __name__ == "__main__":
    unittest.main()