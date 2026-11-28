"""Tests for bq14: Plan Creation Success Analytics."""

import json
import os
import tempfile
import unittest

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import config
from db import COLUMNS, connect, insert_rows
from metrics.plan_creation_success import calculate_plan_creation_success
from models import (
    PlanCreationAttemptedEvent,
    PlanCreationResultEvent,
)
from pydantic import ValidationError


class PlanCreationModelsTest(unittest.TestCase):
    """Tests for the Pydantic models introduced by bq14."""

    def setUp(self):
        self.user_id = uuid4()
        self.attempt_id = uuid4()
        self.timestamp = datetime.now(timezone.utc)

    def _valid_attempt_data(self):
        return {
            "eventType": "plan_creation_attempted",
            "userId": self.user_id,
            "timestamp": self.timestamp,
            "attemptId": self.attempt_id,
            "preferences": ["deportes", "cultura"],
            "freeTimeMinutes": 90,
            "locationName": "Universidad de los Andes",
            "latitude": 4.601,
            "longitude": -74.065,
            "availableFriendsCount": 5,
            "selectedAvailableFriendsCount": 2,
        }

    def test_valid_attempt_is_accepted(self):
        event = PlanCreationAttemptedEvent(**self._valid_attempt_data())

        self.assertEqual(event.eventType, "plan_creation_attempted")
        self.assertEqual(event.attemptId, self.attempt_id)
        self.assertEqual(event.preferences, ["DEPORTES", "CULTURA"])
        self.assertEqual(event.freeTimeMinutes, 90)

    def test_attempt_without_preferences_is_accepted(self):
        data = self._valid_attempt_data()
        data["preferences"] = []

        event = PlanCreationAttemptedEvent(**data)

        self.assertEqual(event.preferences, [])

    def test_attempt_with_null_preferences_becomes_empty_list(self):
        data = self._valid_attempt_data()
        data["preferences"] = None

        event = PlanCreationAttemptedEvent(**data)

        self.assertEqual(event.preferences, [])

    def test_attempt_rejects_invalid_latitude(self):
        data = self._valid_attempt_data()
        data["latitude"] = 95

        with self.assertRaises(ValidationError):
            PlanCreationAttemptedEvent(**data)

    def test_attempt_rejects_invalid_longitude(self):
        data = self._valid_attempt_data()
        data["longitude"] = -190

        with self.assertRaises(ValidationError):
            PlanCreationAttemptedEvent(**data)

    def test_attempt_rejects_only_one_coordinate(self):
        data = self._valid_attempt_data()
        data["longitude"] = None

        with self.assertRaises(ValidationError):
            PlanCreationAttemptedEvent(**data)

    def test_attempt_rejects_negative_free_time(self):
        data = self._valid_attempt_data()
        data["freeTimeMinutes"] = -10

        with self.assertRaises(ValidationError):
            PlanCreationAttemptedEvent(**data)

    def test_attempt_rejects_negative_friend_count(self):
        data = self._valid_attempt_data()
        data["availableFriendsCount"] = -1

        with self.assertRaises(ValidationError):
            PlanCreationAttemptedEvent(**data)

    def test_attempt_rejects_more_selected_friends_than_available(self):
        data = self._valid_attempt_data()
        data["availableFriendsCount"] = 2
        data["selectedAvailableFriendsCount"] = 3

        with self.assertRaises(ValidationError):
            PlanCreationAttemptedEvent(**data)

    def test_valid_success_result_requires_plan_id(self):
        event = PlanCreationResultEvent(
            eventType="plan_creation_result",
            userId=self.user_id,
            timestamp=self.timestamp,
            attemptId=self.attempt_id,
            status="success",
            planId="plan-123",
        )

        self.assertEqual(event.status, "success")
        self.assertEqual(event.planId, "plan-123")

    def test_success_result_without_plan_id_is_rejected(self):
        with self.assertRaises(ValidationError):
            PlanCreationResultEvent(
                eventType="plan_creation_result",
                userId=self.user_id,
                timestamp=self.timestamp,
                attemptId=self.attempt_id,
                status="success",
                planId=None,
            )

    def test_valid_failure_result_without_plan_id_is_accepted(self):
        event = PlanCreationResultEvent(
            eventType="plan_creation_result",
            userId=self.user_id,
            timestamp=self.timestamp,
            attemptId=self.attempt_id,
            status="failure",
            planId=None,
        )

        self.assertEqual(event.status, "failure")
        self.assertIsNone(event.planId)

    def test_failure_result_with_plan_id_is_rejected(self):
        with self.assertRaises(ValidationError):
            PlanCreationResultEvent(
                eventType="plan_creation_result",
                userId=self.user_id,
                timestamp=self.timestamp,
                attemptId=self.attempt_id,
                status="failure",
                planId="plan-123",
            )

    def test_invalid_result_status_is_rejected(self):
        with self.assertRaises(ValidationError):
            PlanCreationResultEvent(
                eventType="plan_creation_result",
                userId=self.user_id,
                timestamp=self.timestamp,
                attemptId=self.attempt_id,
                status="cancelled",
                planId=None,
            )


class PlanCreationDatabaseTest(unittest.TestCase):
    """Tests for bq14 SQLite columns and persistence."""

    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_directory.name) / "analytics_test.db"

        self.db_path_patcher = patch(
            "config.db_path",
            return_value=self.database_path,
        )
        self.db_path_patcher.start()

        # Initialize the database using the normal connection function.
        with connect() as conn:
            pass

    def tearDown(self):
        self.db_path_patcher.stop()
        self.temp_directory.cleanup()

    def test_ae2_columns_exist(self):
        expected_columns = {
            "attempt_id",
            "preferences",
            "location_name",
            "latitude",
            "longitude",
            "available_friends_count",
            "selected_available_friends_count",
            "creation_status",
            "plan_id",
        }

        with connect() as conn:
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(events)").fetchall()
            }

        self.assertTrue(expected_columns.issubset(columns))

    def test_attempt_id_index_exists(self):
        with connect() as conn:
            indexes = {
                row["name"]
                for row in conn.execute("PRAGMA index_list(events)").fetchall()
            }

        self.assertIn("idx_events_attempt_id", indexes)

    def test_columns_list_does_not_contain_duplicates(self):
        self.assertEqual(len(COLUMNS), len(set(COLUMNS)))

    def test_attempt_event_can_be_persisted(self):
        attempt_id = str(uuid4())
        user_id = str(uuid4())

        row = self._base_row(
            event_id=str(uuid4()),
            event_type="plan_creation_attempted",
            user_id=user_id,
            attempt_id=attempt_id,
            preferences=json.dumps(["DEPORTES", "CULTURA"]),
            free_time_minutes=90,
            location_name="Universidad de los Andes",
            latitude=4.601,
            longitude=-74.065,
            available_friends_count=5,
            selected_available_friends_count=2,
        )

        with connect() as conn:
            accepted, rejected = insert_rows(conn, [row])

            stored = conn.execute(
                "SELECT * FROM events WHERE attempt_id = ?",
                (attempt_id,),
            ).fetchone()

        self.assertEqual(accepted, 1)
        self.assertEqual(rejected, 0)
        self.assertIsNotNone(stored)
        self.assertEqual(stored["event_type"], "plan_creation_attempted")
        self.assertEqual(stored["free_time_minutes"], 90)
        self.assertEqual(stored["available_friends_count"], 5)

    def test_result_event_can_be_persisted(self):
        attempt_id = str(uuid4())

        row = self._base_row(
            event_id=str(uuid4()),
            event_type="plan_creation_result",
            user_id=str(uuid4()),
            attempt_id=attempt_id,
            creation_status="success",
            plan_id="plan-123",
        )

        with connect() as conn:
            accepted, rejected = insert_rows(conn, [row])

            stored = conn.execute(
                "SELECT * FROM events WHERE attempt_id = ?",
                (attempt_id,),
            ).fetchone()

        self.assertEqual(accepted, 1)
        self.assertEqual(rejected, 0)
        self.assertEqual(stored["creation_status"], "success")
        self.assertEqual(stored["plan_id"], "plan-123")

    def test_duplicate_event_id_is_ignored(self):
        event_id = str(uuid4())

        row = self._base_row(
            event_id=event_id,
            event_type="plan_creation_result",
            user_id=str(uuid4()),
            attempt_id=str(uuid4()),
            creation_status="success",
            plan_id="plan-123",
        )

        with connect() as conn:
            accepted, rejected = insert_rows(conn, [row, row])

        self.assertEqual(accepted, 1)
        self.assertEqual(rejected, 1)

    @staticmethod
    def _base_row(**overrides):
        row = {column: None for column in COLUMNS}
        row.update({
            "event_id": str(uuid4()),
            "event_type": "plan_creation_attempted",
            "user_id": str(uuid4()),
            "occurred_at": "2026-11-25T20:00:00+00:00",
            "received_at": "2026-11-25T20:00:01+00:00",
        })
        row.update(overrides)
        return row


class PlanCreationSuccessMetricTest(unittest.TestCase):
    """Tests for attempt/result correlation and success-rate calculation."""

    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_directory.name) / "analytics_test.db"

        self.db_path_patcher = patch(
            "config.db_path",
            return_value=self.database_path,
        )
        self.db_path_patcher.start()

        self.minimum_sample_patcher = patch.dict(
            os.environ,
            {"ANALYTICS_PLAN_CREATION_MIN_SAMPLE": "3"},
        )
        self.minimum_sample_patcher.start()

        with connect() as conn:
            pass

    def tearDown(self):
        self.minimum_sample_patcher.stop()
        self.db_path_patcher.stop()
        self.temp_directory.cleanup()

    def _add_attempt(
        self,
        attempt_id,
        *,
        user_id="user-1",
        preferences=None,
        free_time_minutes=90,
        location_name="Universidad de los Andes",
        latitude=4.601,
        longitude=-74.065,
        available_friends=5,
        selected_friends=2,
        event_id=None,
        occurred_at="2026-11-25T20:00:00+00:00",
    ):
        row = self._base_row(
            event_id=event_id or str(uuid4()),
            event_type="plan_creation_attempted",
            user_id=user_id,
            attempt_id=attempt_id,
            preferences=json.dumps(
                preferences if preferences is not None else ["DEPORTES"]
            ),
            free_time_minutes=free_time_minutes,
            location_name=location_name,
            latitude=latitude,
            longitude=longitude,
            available_friends_count=available_friends,
            selected_available_friends_count=selected_friends,
            occurred_at=occurred_at,
        )

        self._insert(row)

    def _add_result(
        self,
        attempt_id,
        *,
        user_id="user-1",
        status="success",
        plan_id="plan-123",
        event_id=None,
        occurred_at="2026-11-25T20:01:00+00:00",
    ):
        row = self._base_row(
            event_id=event_id or str(uuid4()),
            event_type="plan_creation_result",
            user_id=user_id,
            attempt_id=attempt_id,
            creation_status=status,
            plan_id=plan_id if status == "success" else None,
            occurred_at=occurred_at,
        )

        self._insert(row)

    def _insert(self, row):
        with connect() as conn:
            accepted, rejected = insert_rows(conn, [row])

        self.assertEqual(accepted, 1)
        self.assertEqual(rejected, 0)

    @staticmethod
    def _base_row(**overrides):
        row = {column: None for column in COLUMNS}
        row.update({
            "event_id": str(uuid4()),
            "event_type": "plan_creation_attempted",
            "user_id": "user-1",
            "occurred_at": "2026-11-25T20:00:00+00:00",
            "received_at": "2026-11-25T20:00:01+00:00",
        })
        row.update(overrides)
        return row

    def _calculate(self):
        return calculate_plan_creation_success()

    def test_empty_database_returns_no_combinations(self):
        result = self._calculate()

        self.assertEqual(result["totalResolvedAttempts"], 0)
        self.assertEqual(result["combinations"], [])
        self.assertIsNone(result["winner"])

    def test_successful_attempt_is_counted(self):
        attempt_id = str(uuid4())

        self._add_attempt(attempt_id)
        self._add_result(attempt_id, status="success")

        result = self._calculate()

        self.assertEqual(result["totalResolvedAttempts"], 1)
        self.assertEqual(len(result["combinations"]), 1)

        combination = result["combinations"][0]

        self.assertEqual(combination["attempts"], 1)
        self.assertEqual(combination["successes"], 1)
        self.assertEqual(combination["failures"], 0)
        self.assertEqual(combination["successRate"], 100.0)

    def test_failed_attempt_is_counted_as_failure(self):
        attempt_id = str(uuid4())

        self._add_attempt(attempt_id)
        self._add_result(attempt_id, status="failure")

        result = self._calculate()
        combination = result["combinations"][0]

        self.assertEqual(combination["attempts"], 1)
        self.assertEqual(combination["successes"], 0)
        self.assertEqual(combination["failures"], 1)
        self.assertEqual(combination["successRate"], 0.0)

    def test_attempt_without_result_is_not_counted(self):
        self._add_attempt(str(uuid4()))

        result = self._calculate()

        self.assertEqual(result["totalResolvedAttempts"], 0)
        self.assertEqual(result["combinations"], [])

    def test_result_received_before_attempt_is_correlated(self):
        attempt_id = str(uuid4())

        self._add_result(
            attempt_id,
            occurred_at="2026-11-25T19:59:00+00:00",
        )
        self._add_attempt(
            attempt_id,
            occurred_at="2026-11-25T20:00:00+00:00",
        )

        result = self._calculate()

        self.assertEqual(result["totalResolvedAttempts"], 1)
        self.assertEqual(result["combinations"][0]["successes"], 1)

    def test_duplicate_attempt_with_same_context_counts_once(self):
        attempt_id = str(uuid4())

        self._add_attempt(attempt_id)
        self._add_attempt(attempt_id)
        self._add_result(attempt_id)

        result = self._calculate()

        self.assertEqual(result["totalResolvedAttempts"], 1)
        self.assertEqual(result["combinations"][0]["attempts"], 1)

    def test_duplicate_identical_results_count_once(self):
        attempt_id = str(uuid4())

        self._add_attempt(attempt_id)
        self._add_result(attempt_id, plan_id="plan-123")
        self._add_result(attempt_id, plan_id="plan-123")

        result = self._calculate()

        self.assertEqual(result["totalResolvedAttempts"], 1)
        self.assertEqual(result["combinations"][0]["successes"], 1)

    def test_conflicting_attempt_context_is_excluded(self):
        attempt_id = str(uuid4())

        self._add_attempt(attempt_id, free_time_minutes=90)
        self._add_attempt(attempt_id, free_time_minutes=120)
        self._add_result(attempt_id)

        result = self._calculate()

        self.assertEqual(result["totalResolvedAttempts"], 0)

    def test_conflicting_results_are_excluded(self):
        attempt_id = str(uuid4())

        self._add_attempt(attempt_id)
        self._add_result(attempt_id, status="success", plan_id="plan-123")
        self._add_result(attempt_id, status="failure")

        result = self._calculate()

        self.assertEqual(result["totalResolvedAttempts"], 0)

    def test_result_from_different_user_is_excluded(self):
        attempt_id = str(uuid4())

        self._add_attempt(attempt_id, user_id="user-1")
        self._add_result(attempt_id, user_id="user-2")

        result = self._calculate()

        self.assertEqual(result["totalResolvedAttempts"], 0)

    def test_three_attempts_calculate_success_rate(self):
        for status in ("success", "success", "failure"):
            attempt_id = str(uuid4())

            self._add_attempt(attempt_id)
            self._add_result(attempt_id, status=status)

        result = self._calculate()
        combination = result["combinations"][0]

        self.assertEqual(result["totalResolvedAttempts"], 3)
        self.assertEqual(combination["attempts"], 3)
        self.assertEqual(combination["successes"], 2)
        self.assertEqual(combination["failures"], 1)
        self.assertEqual(combination["successRate"], 66.67)

    def test_combination_below_minimum_sample_is_not_eligible(self):
        for _ in range(2):
            attempt_id = str(uuid4())

            self._add_attempt(attempt_id)
            self._add_result(attempt_id)

        result = self._calculate()

        self.assertEqual(len(result["combinations"]), 1)
        self.assertFalse(result["combinations"][0]["eligible"])
        self.assertIsNone(result["winner"])

    def test_combination_at_minimum_sample_is_eligible(self):
        for _ in range(3):
            attempt_id = str(uuid4())

            self._add_attempt(attempt_id)
            self._add_result(attempt_id)

        result = self._calculate()

        self.assertTrue(result["combinations"][0]["eligible"])
        self.assertIsNotNone(result["winner"])

    def test_location_coordinates_are_rounded_for_grouping(self):
        coordinates = [
            (4.60123, -74.06531),
            (4.60118, -74.06528),
            (4.60121, -74.06529),
        ]

        for latitude, longitude in coordinates:
            attempt_id = str(uuid4())

            self._add_attempt(
                attempt_id,
                latitude=latitude,
                longitude=longitude,
            )
            self._add_result(attempt_id)

        result = self._calculate()

        self.assertEqual(len(result["combinations"]), 1)
        self.assertEqual(result["combinations"][0]["attempts"], 3)
        self.assertIn("4.601", result["combinations"][0]["location"])
        self.assertIn("-74.065", result["combinations"][0]["location"])

    def test_different_rounded_locations_create_different_combinations(self):
        locations = [
            (4.6012, -74.0652),
            (4.6022, -74.0652),
        ]

        for latitude, longitude in locations:
            attempt_id = str(uuid4())

            self._add_attempt(
                attempt_id,
                latitude=latitude,
                longitude=longitude,
            )
            self._add_result(attempt_id)

        result = self._calculate()

        self.assertEqual(len(result["combinations"]), 2)

    def test_preferences_are_normalized_and_sorted(self):
        first_attempt = str(uuid4())
        second_attempt = str(uuid4())

        self._add_attempt(
            first_attempt,
            preferences=["DEPORTES", "CULTURA"],
        )
        self._add_result(first_attempt)

        self._add_attempt(
            second_attempt,
            preferences=["CULTURA", "DEPORTES"],
        )
        self._add_result(second_attempt)

        result = self._calculate()

        self.assertEqual(len(result["combinations"]), 1)
        self.assertEqual(
            result["combinations"][0]["preferences"],
            ["CULTURA", "DEPORTES"],
        )
        self.assertEqual(result["combinations"][0]["attempts"], 2)

    def test_different_free_time_buckets_create_different_combinations(self):
        first_attempt = str(uuid4())
        second_attempt = str(uuid4())

        self._add_attempt(first_attempt, free_time_minutes=30)
        self._add_result(first_attempt)

        self._add_attempt(second_attempt, free_time_minutes=90)
        self._add_result(second_attempt)

        result = self._calculate()

        self.assertEqual(len(result["combinations"]), 2)

        buckets = {
            item["freeTimeBucket"]
            for item in result["combinations"]
        }

        self.assertEqual(buckets, {"0-30 min", "61-120 min"})

    def test_different_friend_counts_create_different_combinations(self):
        first_attempt = str(uuid4())
        second_attempt = str(uuid4())

        self._add_attempt(
            first_attempt,
            available_friends=5,
            selected_friends=2,
        )
        self._add_result(first_attempt)

        self._add_attempt(
            second_attempt,
            available_friends=5,
            selected_friends=3,
        )
        self._add_result(second_attempt)

        result = self._calculate()

        self.assertEqual(len(result["combinations"]), 2)

    def test_missing_coordinates_fall_back_to_location_name(self):
        attempt_id = str(uuid4())

        self._add_attempt(
            attempt_id,
            location_name="Biblioteca",
            latitude=None,
            longitude=None,
        )
        self._add_result(attempt_id)

        result = self._calculate()

        self.assertEqual(len(result["combinations"]), 1)
        self.assertEqual(
            result["combinations"][0]["location"],
            "Biblioteca",
        )

    def test_missing_free_time_is_excluded_from_grouping(self):
        attempt_id = str(uuid4())

        self._add_attempt(
            attempt_id,
            free_time_minutes=None,
        )
        self._add_result(attempt_id)

        result = self._calculate()

        self.assertEqual(result["totalResolvedAttempts"], 1)
        self.assertEqual(result["combinations"], [])

    def test_missing_friend_counts_are_excluded_from_grouping(self):
        attempt_id = str(uuid4())

        self._add_attempt(
            attempt_id,
            available_friends=None,
            selected_friends=None,
        )
        self._add_result(attempt_id)

        result = self._calculate()

        self.assertEqual(result["totalResolvedAttempts"], 1)
        self.assertEqual(result["combinations"], [])

    def test_winner_is_highest_eligible_success_rate(self):
        # Combination A: 2 successes out of 3 attempts = 66.67%.
        for status in ("success", "success", "failure"):
            attempt_id = str(uuid4())

            self._add_attempt(
                attempt_id,
                preferences=["DEPORTES"],
            )
            self._add_result(attempt_id, status=status)

        # Combination B: 3 successes out of 3 attempts = 100%.
        for _ in range(3):
            attempt_id = str(uuid4())

            self._add_attempt(
                attempt_id,
                preferences=["CULTURA"],
            )
            self._add_result(attempt_id, status="success")

        result = self._calculate()

        self.assertEqual(len(result["combinations"]), 2)
        self.assertIsNotNone(result["winner"])
        self.assertEqual(result["winner"]["preferences"], ["CULTURA"])
        self.assertEqual(result["winner"]["successRate"], 100.0)


if __name__ == "__main__":
    unittest.main()
