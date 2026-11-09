import unittest
from datetime import timedelta
from uuid import uuid4

from db import connect
from filters import Filters
from metrics.friend_availability_impact import friend_availability_impact
from tests.helpers import HAS_FASTAPI, NOW, U1, U2, U3, U4, U5, ApiTestCase, DbTestCase, row


class FriendAvailabilityImpactTests(DbTestCase):

    def test_friend_availability_impact_calculation(self):
        day = lambda n: NOW - timedelta(days=n)
        self.load([
            # U1: Consulta disponibilidad y crea plan grupal
            row("screen_view", user=U1, screen="Home", at=day(1)),
            row("friend_availability_used", user=U1, action="matrix_viewed", at=day(1)),
            row("friend_availability_used", user=U1, action="create_plan", at=day(1)),

            # U2: Consulta disponibilidad pero no crea plan
            row("screen_view", user=U2, screen="Home", at=day(2)),
            row("friend_availability_used", user=U2, action="viewed", at=day(2)),

            # U3: Usuario directo que crea plan sin consultar disponibilidad
            row("screen_view", user=U3, screen="Home", at=day(3)),
            row("recommended_activity_selected", user=U3, category="DEPORTES", at=day(3)),

            # U4: Usuario activo que solo navega
            row("screen_view", user=U4, screen="Home", at=day(4)),

            # U5: Fuera de la ventana
            row("screen_view", user=U5, screen="Home", at=day(12)),
        ])

        with connect() as conn:
            result = friend_availability_impact(conn, Filters(to=NOW + timedelta(seconds=1)), active_days=7)

        self.assertEqual(result["activeUsers"], 4)
        self.assertEqual(result["usersConsultingAvailability"], 2)
        self.assertEqual(result["usersCreatingPlansWithAvailability"], 1)
        self.assertEqual(result["plansWithAvailability"], 1)
        self.assertAlmostEqual(result["availabilityConversionRate"], 0.5)

        self.assertEqual(result["usersWithoutAvailability"], 2)
        self.assertEqual(result["usersCreatingPlansWithoutAvailability"], 1)
        self.assertEqual(result["plansWithoutAvailability"], 1)
        self.assertAlmostEqual(result["directConversionRate"], 0.5)

        self.assertAlmostEqual(result["liftFactor"], 1.0)
        self.assertEqual(result["shareFromAvailabilityPct"], 50.0)
        self.assertTrue(len(result["dailyTrend"]) > 0)
        self.assertIn("Lift Factor", result["conclusion"])

    def test_no_active_users_returns_safe_defaults(self):
        with connect() as conn:
            result = friend_availability_impact(conn, Filters(to=NOW), active_days=7)

        self.assertEqual(result["activeUsers"], 0)
        self.assertEqual(result["usersConsultingAvailability"], 0)
        self.assertEqual(result["availabilityConversionRate"], 0.0)
        self.assertEqual(result["directConversionRate"], 0.0)
        self.assertEqual(result["liftFactor"], 1.0)
        self.assertEqual(result["shareFromAvailabilityPct"], 0.0)


@unittest.skipUnless(HAS_FASTAPI, "fastapi/httpx no instalados")
class FriendAvailabilityImpactApiTests(ApiTestCase):

    def test_endpoint_and_summary(self):
        user = str(uuid4())
        events = [
            {"eventType": "screen_view", "userId": user, "screen": "Home"},
            {"eventType": "friend_availability_used", "userId": user, "action": "matrix_viewed"},
            {"eventType": "friend_availability_used", "userId": user, "action": "create_plan"}
        ]
        self.client.post("/events/batch", json={"events": events})

        resp = self.client.get("/metrics/friend-availability-impact")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["usersConsultingAvailability"], 1)
        self.assertEqual(data["plansWithAvailability"], 1)
        self.assertEqual(data["availabilityConversionRate"], 1.0)

        summary_resp = self.client.get("/metrics/summary")
        self.assertEqual(summary_resp.status_code, 200)
        summary_data = summary_resp.json()
        self.assertIn("friendAvailabilityImpact", summary_data)
        self.assertEqual(summary_data["friendAvailabilityImpact"]["plansWithAvailability"], 1)


if __name__ == "__main__":
    unittest.main()
