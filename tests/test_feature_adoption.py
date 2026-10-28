import unittest
from datetime import timedelta
from uuid import uuid4
from db import connect
from filters import Filters
from metrics.feature_adoption import feature_adoption
from tests.helpers import HAS_FASTAPI, NOW, ApiTestCase, DbTestCase, row


class FeatureAdoptionTests(DbTestCase):

    def test_adoption_rates_and_threshold(self):
        recent = NOW - timedelta(days=1)
        rows = []

        # Diez usuarios activos, aunque no todos visiten las mismas pantallas.
        rows += [
            row(
                "app_loading_time",
                user=f"user-{i}",
                at=recent,
                load_type="cold_start",
                duration_ms=800,
            )
            for i in range(10)
        ]

        # Home: 6/10 usuarios; Search: 3/10; Settings: 4/10; Profile: 6/10.
        rows += [
            row("screen_view", user=f"user-{i}", screen="Home", at=recent)
            for i in range(6)
        ]
        rows += [
            row("screen_view", user=f"user-{i}", screen="Search", at=recent)
            for i in range(3)
        ]
        rows += [
            row("screen_view", user=f"user-{i}", screen="Settings", at=recent)
            for i in range(4)
        ]
        rows += [
            row("screen_view", user=f"user-{i}", screen="Profile", at=recent)
            for i in range(4, 10)
        ]

        # Visita repetida: no debe contar como un usuario adicional.
        rows.append(
            row("screen_view", user="user-0", screen="Search", at=recent)
        )

        # La pantalla se conoce históricamente, pero está fuera de la ventana.
        rows.append(
            row(
                "screen_view",
                user="old-user",
                screen="Legacy",
                at=NOW - timedelta(days=10),
            )
        )

        self.load(rows)

        with connect() as conn:
            result = feature_adoption(conn, Filters(), now=NOW)

        screens = {s["screen"]: s for s in result["screens"]}

        self.assertEqual(result["activeUsers"], 10)

        self.assertAlmostEqual(screens["Home"]["adoptionRate"], 0.60)
        self.assertAlmostEqual(screens["Search"]["adoptionRate"], 0.30)
        self.assertAlmostEqual(screens["Settings"]["adoptionRate"], 0.40)
        self.assertAlmostEqual(screens["Profile"]["adoptionRate"], 0.60)

        self.assertTrue(screens["Search"]["underutilized"])
        self.assertFalse(screens["Settings"]["underutilized"])
        self.assertFalse(screens["Home"]["underutilized"])

        self.assertEqual(screens["Search"]["uniqueUsers"], 3)

        self.assertEqual(screens["Legacy"]["uniqueUsers"], 0)
        self.assertEqual(screens["Legacy"]["adoptionRate"], 0)
        self.assertTrue(screens["Legacy"]["underutilized"])

        self.assertEqual(result["underutilizedCount"], 2)

    def test_any_event_can_make_a_user_active(self):
        recent = NOW - timedelta(days=1)

        self.load([
            row("screen_view", user="user-a", screen="Home", at=recent),
            row(
                "crash",
                user="user-b",
                screen="Home",
                component="test_component",
                at=recent,
            ),
        ])

        with connect() as conn:
            result = feature_adoption(conn, Filters(), now=NOW)

        home = next(s for s in result["screens"] if s["screen"] == "Home")

        # Ambos usuarios están activos, pero solo uno visitó Home.
        self.assertEqual(result["activeUsers"], 2)
        self.assertEqual(home["uniqueUsers"], 1)
        self.assertAlmostEqual(home["adoptionRate"], 0.50)
        self.assertFalse(home["underutilized"])

    def test_old_events_do_not_count_as_active(self):
        self.load([
            row(
                "screen_view",
                user="old-user",
                screen="OldScreen",
                at=NOW - timedelta(days=10),
            ),
            row(
                "screen_view",
                user="current-user",
                screen="Home",
                at=NOW - timedelta(days=1),
            ),
        ])

        with connect() as conn:
            result = feature_adoption(conn, Filters(), now=NOW)

        screens = {s["screen"]: s for s in result["screens"]}

        self.assertEqual(result["activeUsers"], 1)
        self.assertEqual(screens["OldScreen"]["uniqueUsers"], 0)
        self.assertEqual(screens["OldScreen"]["adoptionRate"], 0)
        self.assertEqual(screens["Home"]["uniqueUsers"], 1)
        self.assertAlmostEqual(screens["Home"]["adoptionRate"], 1.0)

    def test_no_active_users_produces_no_rate(self):
        self.load([
            row(
                "screen_view",
                user="old-user",
                screen="Home",
                at=NOW - timedelta(days=10),
            ),
        ])

        with connect() as conn:
            result = feature_adoption(conn, Filters(), now=NOW)

        self.assertEqual(result["activeUsers"], 0)
        self.assertEqual(len(result["screens"]), 1)
        self.assertIsNone(result["screens"][0]["adoptionRate"])
        self.assertFalse(result["screens"][0]["underutilized"])

    def test_custom_window_days(self):
        self.load([
            row(
                "screen_view",
                user="recent-user",
                screen="Home",
                at=NOW - timedelta(days=2),
            ),
            row(
                "screen_view",
                user="older-user",
                screen="Home",
                at=NOW - timedelta(days=5),
            ),
        ])

        with connect() as conn:
            result = feature_adoption(
                conn,
                Filters(),
                window_days=3,
                now=NOW,
            )

        self.assertEqual(result["windowDays"], 3)
        self.assertEqual(result["activeUsers"], 1)

        home = next(s for s in result["screens"] if s["screen"] == "Home")
        self.assertEqual(home["uniqueUsers"], 1)
        self.assertAlmostEqual(home["adoptionRate"], 1.0)

    def test_invalid_window_days(self):
        with connect() as conn:
            with self.assertRaises(ValueError):
                feature_adoption(conn, Filters(), window_days=0, now=NOW)


@unittest.skipUnless(HAS_FASTAPI, "fastapi/httpx no instalados")
class FeatureAdoptionApiTests(ApiTestCase):

    def test_endpoint_and_summary(self):
        user = str(uuid4())

        response = self.client.post(
            "/events/batch",
            json={
                "events": [
                    {
                        "eventType": "screen_view",
                        "userId": user,
                        "screen": "Home",
                    }
                ]
            },
        )
        self.assertLess(response.status_code, 300)

        result = self.client.get("/metrics/feature-adoption")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["windowDays"], 7)
        self.assertEqual(result.json()["activeUsers"], 1)

        home = next(
            s for s in result.json()["screens"] if s["screen"] == "Home"
        )
        self.assertEqual(home["uniqueUsers"], 1)
        self.assertAlmostEqual(home["adoptionRate"], 1.0)

        summary = self.client.get("/metrics/summary")
        self.assertEqual(summary.status_code, 200)
        self.assertIn("featureAdoption", summary.json())


if __name__ == "__main__":
    unittest.main()
