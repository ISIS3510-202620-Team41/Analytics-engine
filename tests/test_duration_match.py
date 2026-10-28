import unittest
from datetime import timedelta


from db import connect
from filters import Filters
from metrics.duration_match import duration_match
from tests.helpers import HAS_FASTAPI, NOW, U1, U2, U3, U4, ApiTestCase, DbTestCase, row

# Added the 'at' parameter defaulting to NOW
def sel_duration(user, activity, category, free_time, activity_duration, title="Test Act", at=NOW):
    return row(
        "recommended_activity_selected",
        user=user,
        activity_id=activity,
        category=category,
        free_time_minutes=free_time,
        activity_duration_minutes=activity_duration,
        title=title,
        at=at,
    )

class DurationMatchTests(DbTestCase):
    def test_empty_database(self):
        with connect() as conn:
            result = duration_match(conn, Filters())
            
        self.assertEqual(result["totalUniqueSelections"], 0)
        self.assertEqual(result["matches"], 0)
        self.assertEqual(result["overflows"], 0)
        self.assertEqual(result["validSelections"], 0)
        self.assertEqual(result["missingValues"], 0)
        self.assertEqual(result["matchRate"], 0.0)
        self.assertEqual(result["overflowRate"], 0.0)
        self.assertEqual(result["missingRate"], 0.0)
        self.assertEqual(len(result["categories"]), 0)

    def test_match_overflow_missing_logic(self):
        # Create a timestamp a few minutes later for the duplicate
        later = NOW + timedelta(minutes=5)
        
        self.load([
            sel_duration(U1, "a1", "ESTUDIO", 60, 45),     # Match
            sel_duration(U2, "a2", "ESTUDIO", 30, 60),     # Overflow
            sel_duration(U3, "a3", "DEPORTES", None, 60),  # Missing
            sel_duration(U4, "a4", "DEPORTES", 60, 60),    # Match
            
            # Duplicate: U1 selects a1 again but later -> should be ignored
            sel_duration(U1, "a1", "ESTUDIO", 30, 45, at=later),
        ])

        with connect() as conn:
            result = duration_match(conn, Filters())

        self.assertEqual(result["totalUniqueSelections"], 4)
        self.assertEqual(result["validSelections"], 3)
        self.assertEqual(result["matches"], 2)
        self.assertEqual(result["overflows"], 1)
        self.assertEqual(result["missingValues"], 1)
        
        self.assertAlmostEqual(result["matchRate"], 2 / 3)
        self.assertAlmostEqual(result["overflowRate"], 1 / 3)
        self.assertAlmostEqual(result["missingRate"], 1 / 4)

        cats = result["categories"]
        
        # Check ESTUDIO Category
        estudio = cats["ESTUDIO"]
        self.assertEqual(estudio["validSelections"], 2)
        self.assertEqual(estudio["matches"], 1)
        self.assertEqual(estudio["overflows"], 1)
        self.assertEqual(estudio["missingValues"], 0)
        self.assertEqual(estudio["matchRate"], 0.5)
        self.assertEqual(estudio["overflowRate"], 0.5)
        self.assertEqual(estudio["missingRate"], 0.0)

        # Check DEPORTES Category
        deportes = cats["DEPORTES"]
        self.assertEqual(deportes["validSelections"], 1)
        self.assertEqual(deportes["matches"], 1)
        self.assertEqual(deportes["overflows"], 0)
        self.assertEqual(deportes["missingValues"], 1)
        self.assertEqual(deportes["matchRate"], 1.0)
        self.assertEqual(deportes["overflowRate"], 0.0)
        self.assertEqual(deportes["missingRate"], 0.5)

@unittest.skipUnless(HAS_FASTAPI, "fastapi/httpx no instalados")
class DurationMatchApiTests(ApiTestCase):
    def test_duration_match_endpoint(self):
        self.load([
            sel_duration(U1, "a1", "DEPORTES", 60, 30),
        ])
        resp = self.client.get("/metrics/duration-match")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["totalUniqueSelections"], 1)
        self.assertEqual(data["matchRate"], 1.0)

    def test_summary_includes_duration_match(self):
        self.load([
            sel_duration(U1, "a1", "CULTURA", 30, 60),
        ])
        resp = self.client.get("/metrics/summary")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("durationMatch", data)
        self.assertEqual(data["durationMatch"]["overflows"], 1)