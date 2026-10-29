
import unittest

from db import connect
from filters import Filters
from metrics.network_impact import network_impact
from tests.helpers import DbTestCase, NOW, row


class NetworkImpactTests(DbTestCase):

    def test_loading_and_selection_by_quality(self):
        self.load([
            row(
                "app_loading_time",
                at=NOW,
                load_type="screen",
                screen="recommendations",
                duration_ms=400,
                network_quality="good",
            ),
            row(
                "app_loading_time",
                at=NOW,
                load_type="screen",
                screen="recommendations",
                duration_ms=600,
                network_quality="good",
            ),
            row(
                "app_loading_time",
                at=NOW,
                load_type="screen",
                screen="recommendations",
                duration_ms=1800,
                network_quality="poor",
            ),
            row(
                "recommendation_shown",
                at=NOW,
                recommendation_id="rec-good",
                free_time_minutes=30,
                network_quality="good",
            ),
            row(
                "recommended_activity_selected",
                at=NOW,
                recommendation_id="rec-good",
                activity_id="activity-1",
                free_time_minutes=30,
            ),
            row(
                "recommendation_shown",
                at=NOW,
                recommendation_id="rec-poor",
                free_time_minutes=30,
                network_quality="poor",
            ),
        ])

        with connect() as conn:
            result = network_impact(conn, Filters())

        by_quality = {
            item["networkQuality"]: item
            for item in result["byNetworkQuality"]
        }

        self.assertEqual(
            by_quality["good"]["averageLoadingMs"], 500.0
        )
        self.assertEqual(
            by_quality["poor"]["averageLoadingMs"], 1800.0
        )
        self.assertEqual(
            by_quality["good"]["recommendationLoads"], 1
        )
        self.assertEqual(
            by_quality["good"]["loadsWithSelection"], 1
        )
        self.assertEqual(
            by_quality["good"]["selectionRate"], 1.0
        )
        self.assertEqual(
            by_quality["poor"]["recommendationLoads"], 1
        )
        self.assertEqual(
            by_quality["poor"]["loadsWithSelection"], 0
        )
        self.assertEqual(
            by_quality["poor"]["selectionRate"], 0.0
        )

    def test_missing_data_is_none(self):
        with connect() as conn:
            result = network_impact(conn, Filters())

        by_quality = {
            item["networkQuality"]: item
            for item in result["byNetworkQuality"]
        }

        self.assertIsNone(
            by_quality["good"]["averageLoadingMs"]
        )
        self.assertIsNone(
            by_quality["good"]["selectionRate"]
        )


if __name__ == "__main__":
    unittest.main()