import unittest
from uuid import uuid4

from db import connect
from filters import Filters
from metrics.crash_rate import crash_rate
from tests.helpers import HAS_FASTAPI, ApiTestCase, DbTestCase, row


class CrashRateTests(DbTestCase):
    def test_highest_rate_is_by_views_not_by_count(self):
        rows = [row("screen_view", screen="Login") for _ in range(10)]
        rows += [row("screen_view", screen="Home") for _ in range(100)]
        rows += [row("crash", screen="Login", component="btn_login") for _ in range(2)]
        rows += [row("crash", screen="Home", component="map") for _ in range(3)]
        self.load(rows)
        with connect() as conn:
            result = crash_rate(conn, Filters())
        self.assertEqual(result["highest"]["screen"], "Login")          # 20% vs 3%
        self.assertAlmostEqual(result["highest"]["crashRate"], 0.2)
        self.assertEqual(result["highest"]["components"], [{"component": "btn_login", "crashes": 2}])
        self.assertEqual([s["screen"] for s in result["screens"]], ["Login", "Home"])
        self.assertAlmostEqual(result["overallCrashRate"], 5 / 110)

    def test_min_views_moves_noisy_screens_to_the_end(self):
        rows = [row("screen_view", screen="Rare"), row("crash", screen="Rare")]
        rows += [row("screen_view", screen="Home") for _ in range(50)]
        rows += [row("crash", screen="Home")]
        self.load(rows)
        with connect() as conn:
            result = crash_rate(conn, Filters(), min_views=10)
        self.assertEqual(result["highest"]["screen"], "Home")
        self.assertIsNone(result["screens"][-1]["crashRate"])

    def test_no_crashes_means_no_highest(self):
        self.load([row("screen_view", screen="Home")])
        with connect() as conn:
            self.assertIsNone(crash_rate(conn, Filters())["highest"])


@unittest.skipUnless(HAS_FASTAPI, "fastapi/httpx no instalados")
class CrashRateApiTests(ApiTestCase):
    def test_endpoint_and_summary(self):
        user = str(uuid4())
        events = [{"eventType": "screen_view", "userId": user, "screen": "Home"},
                  {"eventType": "crash", "userId": user, "screen": "Home", "component": "btn_join"}]
        self.client.post("/events/batch", json={"events": events})
        self.assertEqual(self.client.get("/metrics/crash-rate").json()["highest"]["screen"], "Home")
        self.assertIn("crashRate", self.client.get("/metrics/summary").json())


if __name__ == "__main__":
    unittest.main()