import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from datetime import timedelta
from uuid import uuid4

from db import connect
from filters import Filters
from metrics.feature_adoption import feature_adoption
from tests.helpers import (
    HAS_FASTAPI,
    NOW,
    U1,
    U2,
    U3,
    ApiTestCase,
    DbTestCase,
    row,
)


class FeatureAdoptionTests(DbTestCase):

    def test_counts_unique_users_and_separates_screens_from_features(self):
        day = lambda n: NOW - timedelta(days=n)

        self.load([
            row(
                "screen_view",
                user=U1,
                at=day(1),
                screen="Home",
            ),
            row(
                "screen_view",
                user=U1,
                at=day(1),
                screen="Home",
            ),  # El mismo usuario no se cuenta dos veces.
            row(
                "screen_view",
                user=U2,
                at=day(2),
                screen="Home",
            ),
            row(
                "app_loading_time",
                user=U3,
                at=day(3),
                load_type="cold_start",
                duration_ms=800,
            ),  # Usuario activo sin screen_view.
            row(
                "feature_used",
                user=U1,
                at=day(1),
                feature="friend_availability",
                action="check_availability",
                screen="FriendAvailability",
            ),
            row(
                "feature_used",
                user=U1,
                at=day(1),
                feature="friend_availability",
                action="check_availability",
                screen="FriendAvailability",
            ),  # Tampoco se duplica al contar usuarios de la feature.
            row(
                "friend_availability_used",
                user=U2,
                at=day(2),
                action="viewed",
            ),  # No sustituye feature_used en la adopción de BQ8.
            row(
                "screen_view",
                user=U3,
                at=day(10),
                screen="LegacyScreen",
            ),  # Fuera de la ventana, pero ya conocida.
            row(
                "feature_used",
                user=U3,
                at=day(10),
                feature="legacy_feature",
                action="open_feature",
            ),  # También fuera de la ventana.
        ])

        with connect() as conn:
            result = feature_adoption(conn, Filters(to=NOW), 7)

        self.assertEqual(result["activeUsers"], 3)

        home = next(
            item for item in result["screens"]
            if item["screen"] == "Home"
        )
        self.assertEqual(home["uniqueUsers"], 2)
        self.assertAlmostEqual(home["adoptionRate"], 2 / 3)
        self.assertFalse(home["underutilized"])

        friend_availability = next(
            item for item in result["features"]
            if item["feature"] == "friend_availability"
        )
        self.assertEqual(friend_availability["uniqueUsers"], 1)
        self.assertAlmostEqual(
            friend_availability["adoptionRate"],
            1 / 3,
        )
        self.assertTrue(friend_availability["underutilized"])

        # El catálogo permite identificar un elemento sin uso reciente.
        profile = next(
            item for item in result["screens"]
            if item["screen"] == "Profile"
        )
        self.assertEqual(profile["uniqueUsers"], 0)
        self.assertEqual(profile["adoptionRate"], 0.0)
        self.assertTrue(profile["underutilized"])

        # Un elemento conocido solo por eventos antiguos también se conserva.
        legacy = next(
            item for item in result["features"]
            if item["feature"] == "legacy_feature"
        )
        self.assertEqual(legacy["uniqueUsers"], 0)
        self.assertEqual(legacy["adoptionRate"], 0.0)

        self.assertEqual(
            result["underutilizedCount"],
            result["underutilizedScreenCount"]
            + result["underutilizedFeatureCount"],
        )

    def test_returns_null_rates_when_there_are_no_active_users(self):
        self.load([
            row(
                "screen_view",
                user=U1,
                screen="OldScreen",
                at=NOW - timedelta(days=10),
            ),
            row(
                "feature_used",
                user=U1,
                feature="old_feature",
                action="open_feature",
                at=NOW - timedelta(days=10),
            ),
        ])

        with connect() as conn:
            result = feature_adoption(conn, Filters(to=NOW), 7)

        self.assertEqual(result["activeUsers"], 0)

        old_screen = next(
            item for item in result["screens"]
            if item["screen"] == "OldScreen"
        )
        old_feature = next(
            item for item in result["features"]
            if item["feature"] == "old_feature"
        )

        self.assertIsNone(old_screen["adoptionRate"])
        self.assertFalse(old_screen["underutilized"])
        self.assertIsNone(old_feature["adoptionRate"])
        self.assertFalse(old_feature["underutilized"])

    def test_rejects_invalid_window_size(self):
        with connect() as conn:
            with self.assertRaises(ValueError):
                feature_adoption(conn, Filters(to=NOW), 0)

            with self.assertRaises(ValueError):
                feature_adoption(conn, Filters(to=NOW), 91)


@unittest.skipUnless(HAS_FASTAPI, "fastapi/httpx no instalados")
class FeatureAdoptionApiTests(ApiTestCase):

    def test_endpoint_and_summary_accept_feature_used(self):
        user1 = str(uuid4())
        user2 = str(uuid4())

        response = self.client.post(
            "/events/batch",
            json={
                "events": [
                    {
                        "eventType": "screen_view",
                        "userId": user1,
                        "screen": "Home",
                    },
                    {
                        "eventType": "feature_used",
                        "userId": user1,
                        "feature": "friend_availability",
                        "action": "check_availability",
                        "screen": "FriendAvailability",
                    },
                    {
                        "eventType": "screen_view",
                        "userId": user2,
                        "screen": "Home",
                    },
                ]
            },
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["accepted"], 3)

        result = self.client.get(
            "/metrics/feature-adoption?windowDays=7"
        )

        self.assertEqual(result.status_code, 200)
        data = result.json()
        self.assertEqual(data["activeUsers"], 2)

        friend_availability = next(
            item for item in data["features"]
            if item["feature"] == "friend_availability"
        )
        self.assertEqual(friend_availability["uniqueUsers"], 1)
        self.assertAlmostEqual(
            friend_availability["adoptionRate"],
            0.5,
        )
        self.assertIn(
            "featureAdoption",
            self.client.get("/metrics/summary").json(),
        )

    def test_feature_identifier_must_be_snake_case(self):
        response = self.client.post(
            "/events",
            json={
                "eventType": "feature_used",
                "userId": str(uuid4()),
                "feature": "Friend Availability",
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_window_days_must_be_between_one_and_ninety(self):
        response = self.client.get(
            "/metrics/feature-adoption?windowDays=0"
        )
        self.assertEqual(response.status_code, 422)


class FeatureColumnMigrationTests(unittest.TestCase):

    def test_existing_database_gets_feature_column(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "legacy.db"
            old_path = os.environ.get("ANALYTICS_DB_PATH")

            try:
                os.environ["ANALYTICS_DB_PATH"] = str(database_path)

                # Crear una base antigua que no tiene la columna feature.
                legacy_conn = sqlite3.connect(str(database_path))
                try:
                    legacy_conn.execute("""
                        CREATE TABLE events (
                            event_id TEXT PRIMARY KEY,
                            event_type TEXT NOT NULL,
                            user_id TEXT NOT NULL,
                            session_id TEXT,
                            app_version TEXT,
                            occurred_at TEXT NOT NULL,
                            received_at TEXT NOT NULL,
                            screen TEXT,
                            component TEXT,
                            exception_type TEXT,
                            load_type TEXT,
                            duration_ms INTEGER,
                            activity_id TEXT,
                            category TEXT,
                            free_time_minutes INTEGER,
                            recommendation_id TEXT,
                            action TEXT,
                            title TEXT,
                            price TEXT,
                            activity_duration_minutes INTEGER
                        )
                    """)
                    legacy_conn.commit()
                finally:
                    # El context manager de sqlite3 no cierra la conexión.
                    legacy_conn.close()

                # Abrir la base con el código de la aplicación para ejecutar
                # la migración.
                with connect() as conn:
                    columns = {
                        row["name"]
                        for row in conn.execute("PRAGMA table_info(events)")
                    }

                self.assertIn("feature", columns)

            finally:
                if old_path is None:
                    os.environ.pop("ANALYTICS_DB_PATH", None)
                else:
                    os.environ["ANALYTICS_DB_PATH"] = old_path


if __name__ == "__main__":
    unittest.main()