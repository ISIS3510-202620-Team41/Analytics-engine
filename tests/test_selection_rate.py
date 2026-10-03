import unittest
from uuid import uuid4

from db import connect
from filters import Filters
from metrics.selection_rate import selection_rate
from tests.helpers import HAS_FASTAPI, U1, U2, U3, ApiTestCase, DbTestCase, row


class SelectionRateTests(DbTestCase):
    def test_only_joins_count_and_loads_without_free_time_are_excluded(self):
        self.load([
            row("recommendation_shown", recommendation_id="r1", free_time_minutes=60),
            row("recommendation_shown", recommendation_id="r2", free_time_minutes=45),
            row("recommendation_shown", recommendation_id="r3", free_time_minutes=90),   # nadie hizo join
            row("recommendation_shown", recommendation_id="r4", free_time_minutes=0),    # sin tiempo libre
            row("recommended_activity_selected", user=U1, activity_id="A", category="DEPORTES",
                recommendation_id="r1", free_time_minutes=60),
            row("recommended_activity_selected", user=U1, activity_id="A", category="DEPORTES",
                recommendation_id="r1", free_time_minutes=60),                           # duplicado
            row("recommended_activity_selected", user=U1, activity_id="B", category="ESTUDIO",
                recommendation_id="r1", free_time_minutes=60),                           # 2do join, misma carga
            row("recommended_activity_selected", user=U2, activity_id="C", category="CULTURA",
                recommendation_id="r2", free_time_minutes=45),
            row("recommended_activity_selected", user=U3, activity_id="D", category="CULTURA",
                recommendation_id="r4", free_time_minutes=0),                            # sin tiempo libre
        ])
        with connect() as conn:
            result = selection_rate(conn, Filters())
        self.assertEqual(result["shown"], 3)
        self.assertEqual(result["selected"], 3)                 # (U1,A), (U1,B), (U2,C)
        self.assertAlmostEqual(result["selectionRate"], 1.0)
        self.assertEqual(result["loadsWithSelection"], 2)       # r1 y r2
        self.assertAlmostEqual(result["loadSelectionRate"], 2 / 3)

    def test_empty_is_zero(self):
        with connect() as conn:
            result = selection_rate(conn, Filters())
        self.assertEqual((result["shown"], result["selected"], result["selectionRate"]), (0, 0, 0.0))


@unittest.skipUnless(HAS_FASTAPI, "fastapi/httpx no instalados")
class SelectionRateApiTests(ApiTestCase):
    def test_endpoint_and_summary(self):
        user = str(uuid4())
        events = [
            {"eventType": "recommendation_shown", "userId": user, "recommendationId": "r1", "freeTimeMinutes": 60},
            {"eventType": "recommended_activity_selected", "userId": user, "activityId": "a",
             "category": "ESTUDIO", "freeTimeMinutes": 60, "recommendationId": "r1"},
        ]
        self.client.post("/events/batch", json={"events": events})
        result = self.client.get("/metrics/selection-rate").json()
        self.assertEqual((result["shown"], result["selected"]), (1, 1))
        self.assertIn("selectionRate", self.client.get("/metrics/summary").json())


if __name__ == "__main__":
    unittest.main()