import unittest
from datetime import timedelta
from uuid import uuid4

from db import connect
from filters import Filters
from metrics.friend_availability import friend_availability_usage
from tests.helpers import HAS_FASTAPI, NOW, U1, U2, U3, U4, U5, ApiTestCase, DbTestCase, row


class FriendAvailabilityTests(DbTestCase):
    def test_percentage_of_active_users(self):
        day = lambda n: NOW - timedelta(days=n)
        self.load([
            row("screen_view", user=U1, screen="Home", at=day(1)),
            row("screen_view", user=U2, screen="Home", at=day(2)),
            row("screen_view", user=U3, screen="Home", at=day(3)),
            row("screen_view", user=U4, screen="Home", at=day(6)),
            row("screen_view", user=U5, screen="Home", at=day(10)),                 # inactivo
            row("friend_availability_used", user=U1, action="viewed", at=day(1)),
            row("friend_availability_used", user=U1, action="viewed", at=day(1)),   # mismo usuario: cuenta una vez
            row("friend_availability_used", user=U2, action="plan_joined", at=day(2)),
            row("friend_availability_used", user=U5, action="viewed", at=day(10)),  # fuera de la ventana
        ])
        with connect() as conn:
            result = friend_availability_usage(conn, Filters(to=NOW + timedelta(seconds=1)))
        self.assertEqual(result["activeUsers"], 4)
        self.assertEqual(result["usersUsingFeature"], 2)
        self.assertAlmostEqual(result["usageRate"], 0.5)
        self.assertEqual(result["usersCreatingOrJoiningPlan"], 1)
        self.assertAlmostEqual(result["planActionRate"], 0.25)

    def test_active_days_changes_the_window(self):
        self.load([
            row("screen_view", user=U1, screen="Home", at=NOW - timedelta(days=20)),
            row("friend_availability_used", user=U1, at=NOW - timedelta(days=20)),
        ])
        with connect() as conn:
            self.assertEqual(friend_availability_usage(conn, Filters(to=NOW), 7)["activeUsers"], 0)
            self.assertEqual(friend_availability_usage(conn, Filters(to=NOW), 30)["usageRate"], 1.0)

    def test_no_active_users(self):
        with connect() as conn:
            result = friend_availability_usage(conn, Filters(to=NOW))
        self.assertEqual((result["activeUsers"], result["usageRate"]), (0, 0.0))


@unittest.skipUnless(HAS_FASTAPI, "fastapi/httpx no instalados")
class FriendAvailabilityApiTests(ApiTestCase):
    def test_endpoint_and_summary(self):
        user = str(uuid4())
        events = [{"eventType": "screen_view", "userId": user, "screen": "Home"},
                  {"eventType": "friend_availability_used", "userId": user, "action": "plan_created"}]
        self.client.post("/events/batch", json={"events": events})
        result = self.client.get("/metrics/friend-availability").json()
        self.assertEqual((result["usageRate"], result["planActionRate"]), (1.0, 1.0))
        self.assertIn("friendAvailability", self.client.get("/metrics/summary").json())


if __name__ == "__main__":
    unittest.main()