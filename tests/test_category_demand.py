import unittest
from datetime import datetime, timezone
from uuid import uuid4

import config
from db import connect
from filters import Filters
from metrics.category_demand import category_demand
from tests.helpers import HAS_FASTAPI, U1, U2, U3, U4, ApiTestCase, DbTestCase, row


def sel_time(user, activity, category, at_dt, title="Test Act", price="$10.000 COP"):
    return row(
        "recommended_activity_selected",
        user=user,
        activity_id=activity,
        category=category,
        at=at_dt,
        title=title,
        price=price,
    )


class CategoryDemandTests(DbTestCase):
    def test_empty_database(self):
        with connect() as conn:
            result = category_demand(conn, Filters())
        self.assertEqual(result["totalSelectionsOverall"], 0)
        self.assertIsNone(result["topCategoryOverall"])
        self.assertIsNone(result["peakTimeSlot"])
        self.assertEqual(len(result["timeSlots"]), 5)
        for s in result["timeSlots"]:
            self.assertEqual(s["totalSelections"], 0)
            self.assertIsNone(s["topCategory"])
            self.assertFalse(s["tie"])
            self.assertEqual(len(s["topActivities"]), 0)
            self.assertTrue(len(s["monetizationOpportunity"]) > 0)

    def test_time_slot_distribution_and_deduplication(self):
        # Desfase -5 (Colombia)
        # 14:00 UTC = 09:00 COT (morning)
        # 18:00 UTC = 13:00 COT (midday)
        # 20:00 UTC = 15:00 COT (afternoon)
        # 00:00 UTC = 19:00 COT dia anterior (evening)
        # 08:00 UTC = 03:00 COT (off_hours)
        dt_morning = datetime(2026, 10, 26, 14, 0, tzinfo=timezone.utc)
        dt_midday = datetime(2026, 10, 26, 18, 0, tzinfo=timezone.utc)
        dt_afternoon = datetime(2026, 10, 26, 20, 0, tzinfo=timezone.utc)
        dt_evening = datetime(2026, 10, 27, 0, 0, tzinfo=timezone.utc)
        dt_offhours = datetime(2026, 10, 26, 8, 0, tzinfo=timezone.utc)

        self.load([
            sel_time(U1, "a1", "ESTUDIO", dt_morning, title="Taller Calculo"),
            sel_time(U2, "a2", "ESTUDIO", dt_morning, title="Club Lectura"),
            sel_time(U3, "a3", "DEPORTES", dt_morning, title="Running Campus"),
            # Duplicado: U1 selecciona a1 de nuevo mas tarde -> debe ignorarse
            sel_time(U1, "a1", "ESTUDIO", dt_afternoon, title="Taller Calculo"),
            # Midday
            sel_time(U1, "a4", "ENTRETENIMIENTO", dt_midday, title="Almuerzo Juegos"),
            # Afternoon
            sel_time(U2, "a5", "DEPORTES", dt_afternoon, title="Torneo Futbol 5"),
            sel_time(U3, "a5", "DEPORTES", dt_afternoon, title="Torneo Futbol 5"),
            # Evening
            sel_time(U4, "a6", "CULTURA", dt_evening, title="Cineclub UniAndes"),
            # Off hours
            sel_time(U1, "a7", "ESTUDIO", dt_offhours, title="Estudio Nocturno"),
        ])

        with connect() as conn:
            result = category_demand(conn, Filters(), tz_offset=-5)

        self.assertEqual(result["totalSelectionsOverall"], 8)
        self.assertEqual(result["topCategoryOverall"], "ESTUDIO")
        self.assertEqual(result["peakTimeSlot"], "Mañana (06:00 - 12:00)")

        slots_by_id = {s["slotId"]: s for s in result["timeSlots"]}

        # Morning slot
        morning = slots_by_id["morning"]
        self.assertEqual(morning["totalSelections"], 3)
        self.assertEqual(morning["topCategory"], "ESTUDIO")
        self.assertFalse(morning["tie"])
        self.assertIn("cafeterías", morning["monetizationOpportunity"].lower())
        self.assertEqual(len(morning["topActivities"]), 3)

        # Midday slot
        midday = slots_by_id["midday"]
        self.assertEqual(midday["totalSelections"], 1)
        self.assertEqual(midday["topCategory"], "ENTRETENIMIENTO")

        # Afternoon slot (2 selections of a5)
        afternoon = slots_by_id["afternoon"]
        self.assertEqual(afternoon["totalSelections"], 2)
        self.assertEqual(afternoon["topCategory"], "DEPORTES")
        self.assertEqual(afternoon["topActivities"][0]["activityId"], "a5")
        self.assertEqual(afternoon["topActivities"][0]["count"], 2)

        # Evening slot
        evening = slots_by_id["evening"]
        self.assertEqual(evening["totalSelections"], 1)
        self.assertEqual(evening["topCategory"], "CULTURA")

        # Off hours slot
        off_hours = slots_by_id["off_hours"]
        self.assertEqual(off_hours["totalSelections"], 1)
        self.assertEqual(off_hours["topCategory"], "ESTUDIO")

    def test_tie_handling_alphabetical(self):
        dt = datetime(2026, 10, 26, 15, 0, tzinfo=timezone.utc) # 10:00 COT -> morning
        self.load([
            sel_time(U1, "a1", "ESTUDIO", dt),
            sel_time(U2, "a2", "DEPORTES", dt),
        ])
        with connect() as conn:
            result = category_demand(conn, Filters(), tz_offset=-5)

        morning = next(s for s in result["timeSlots"] if s["slotId"] == "morning")
        self.assertEqual(morning["totalSelections"], 2)
        self.assertTrue(morning["tie"])
        # DEPORTES viene antes de ESTUDIO alfabeticamente
        self.assertEqual(morning["topCategory"], "DEPORTES")


@unittest.skipUnless(HAS_FASTAPI, "fastapi/httpx no instalados")
class CategoryDemandApiTests(ApiTestCase):
    def test_category_demand_endpoint(self):
        dt = datetime(2026, 10, 26, 15, 0, tzinfo=timezone.utc)
        self.load([
            sel_time(U1, "a1", "DEPORTES", dt, title="Tenis de Mesa"),
        ])
        resp = self.client.get("/metrics/category-demand?tz_offset=-5")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["totalSelectionsOverall"], 1)
        self.assertEqual(data["topCategoryOverall"], "DEPORTES")
        self.assertEqual(data["tzOffsetHours"], -5)

    def test_summary_includes_category_demand(self):
        dt = datetime(2026, 10, 26, 15, 0, tzinfo=timezone.utc)
        self.load([
            sel_time(U1, "a1", "CULTURA", dt, title="Visita Museo"),
        ])
        resp = self.client.get("/metrics/summary")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("categoryDemand", data)
        self.assertEqual(data["categoryDemand"]["totalSelectionsOverall"], 1)
        self.assertEqual(data["categoryDemand"]["topCategoryOverall"], "CULTURA")
