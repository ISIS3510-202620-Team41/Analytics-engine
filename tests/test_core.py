"""Ingesta, almacenamiento, seguridad y utilidades comunes."""
import os
import unittest
from uuid import uuid4

import config
from db import clear_all, connect, insert_rows, purge_versions_before
from filters import version_key
from tests.helpers import HAS_FASTAPI, ApiTestCase, DbTestCase, row

USER = str(uuid4())


class StorageTests(DbTestCase):
    def test_duplicate_event_id_is_ignored(self):
        r = row("screen_view", screen="Home")
        with connect() as conn:
            self.assertEqual(insert_rows(conn, [r]), (1, 0))
            self.assertEqual(insert_rows(conn, [r]), (0, 1))

    def test_purge_old_versions_and_clear(self):
        self.load([
            row("screen_view", screen="Home", app_version="0.9.0"),
            row("screen_view", screen="Home", app_version="1.0.0"),
            row("recommendation_shown", recommendation_id="r1"),   # sin version: no se toca
        ])
        with connect() as conn:
            self.assertEqual(purge_versions_before(conn, "1.0.0"), 1)
            self.assertEqual(clear_all(conn), 2)

    def test_version_key_ignores_trailing_zeros(self):
        self.assertEqual(version_key("1.2"), version_key("1.2.0"))
        self.assertLess(version_key("1.9.0"), version_key("1.10.0"))
        self.assertLess(version_key("1.0.0-debug"), version_key("1.0.1"))

    def test_invalid_edges(self):
        for bad in ("", "0,30", "60,30", "a,b", "30,30"):
            with self.assertRaises(ValueError):
                config.parse_edges(bad)

    def test_categories_match_model_enum(self):
        try:
            from models import Category
        except ImportError:
            self.skipTest("pydantic no instalado")
        self.assertEqual(tuple(c.value for c in Category), config.CATEGORIES)


@unittest.skipUnless(HAS_FASTAPI, "fastapi/httpx no instalados")
class IngestApiTests(ApiTestCase):
    def test_health(self):
        self.assertEqual(self.client.get("/health").json(), {"status": "ok"})

    def test_single_event_and_duplicate(self):
        body = {"eventType": "screen_view", "userId": USER, "screen": "Home", "eventId": str(uuid4())}
        self.assertEqual(self.client.post("/events", json=body).json(), {"accepted": 1, "duplicates": 0})
        self.assertEqual(self.client.post("/events", json=body).json(), {"accepted": 0, "duplicates": 1})

    def test_invalid_events_are_rejected(self):
        bad = [
            {"eventType": "nope", "userId": USER},
            {"eventType": "screen_view", "userId": "not-a-uuid", "screen": "Home"},
            {"eventType": "app_loading_time", "userId": USER, "loadType": "screen", "durationMs": 10},
            {"eventType": "app_loading_time", "userId": USER, "loadType": "cold_start", "durationMs": -1},
            {"eventType": "recommended_activity_selected", "userId": USER, "activityId": "a", "category": "X"},
        ]
        for body in bad:
            self.assertEqual(self.client.post("/events", json=body).status_code, 422, body)

    def test_category_is_normalized_and_future_timestamp_is_clamped(self):
        body = {"eventType": "recommended_activity_selected", "userId": USER, "activityId": "a",
                "category": "deportes", "timestamp": "2999-01-01T00:00:00Z"}
        self.assertEqual(self.client.post("/events", json=body).status_code, 201)
        with connect() as conn:
            category, occurred, received = conn.execute(
                "SELECT category, occurred_at, received_at FROM events").fetchone()
        self.assertEqual(category, "DEPORTES")
        self.assertEqual(occurred, received)     # la fecha del futuro se reemplazo por la del servidor

    def test_batch_is_all_or_nothing(self):
        good = {"eventType": "screen_view", "userId": USER, "screen": "Home"}
        self.assertEqual(self.client.post("/events/batch", json={"events": [good, good]}).json()["accepted"], 2)
        self.assertEqual(self.client.post("/events/batch", json={"events": [good, {"eventType": "x"}]}).status_code, 422)
        self.assertEqual(self.client.post("/events/batch", json={"events": []}).status_code, 422)

    def test_api_keys(self):
        os.environ["ANALYTICS_INGEST_KEY"] = "ingest-secret"
        os.environ["ANALYTICS_ADMIN_KEY"] = "admin-secret"
        body = {"eventType": "screen_view", "userId": USER, "screen": "Home"}
        self.assertEqual(self.client.post("/events", json=body).status_code, 401)
        self.assertEqual(self.client.post("/events", json=body, headers={"X-API-Key": "x"}).status_code, 401)
        self.assertEqual(self.client.post("/events", json=body, headers={"X-API-Key": "ingest-secret"}).status_code, 201)
        # La llave de ingesta no sirve para leer ni para borrar.
        self.assertEqual(self.client.get("/metrics/summary", headers={"X-API-Key": "ingest-secret"}).status_code, 401)
        self.assertEqual(self.client.delete("/events", headers={"X-API-Key": "ingest-secret"}).status_code, 401)
        self.assertEqual(self.client.get("/metrics/summary", headers={"X-API-Key": "admin-secret"}).status_code, 200)

    def test_purge_old_versions(self):
        for version in ("0.9.0", "1.0.0"):
            self.client.post("/events", json={"eventType": "screen_view", "userId": USER,
                                              "screen": "Home", "appVersion": version})
        self.assertEqual(self.client.delete("/events?appVersionBefore=1.0.0").json(), {"deleted": 1})
        self.assertEqual(self.client.delete("/events").json(), {"deleted": 1})

    def test_summary_and_filter_validation(self):
        self.assertEqual(self.client.get("/metrics/summary").status_code, 200)
        bad_range = "/metrics/summary?from=2026-10-02T00:00:00Z&to=2026-10-01T00:00:00Z"
        self.assertEqual(self.client.get(bad_range).status_code, 400)


if __name__ == "__main__":
    unittest.main()