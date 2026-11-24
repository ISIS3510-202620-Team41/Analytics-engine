"""API tests for BQ12 enrollment cancellation reporting."""

import unittest
from datetime import timedelta

from tests.helpers import HAS_FASTAPI, NOW, ApiTestCase
from tests.test_cancellation_rate import canceled, confirmed


@unittest.skipUnless(HAS_FASTAPI, "fastapi/httpx no instalados")
class CancellationRateApiTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.period_end = NOW + timedelta(hours=1)
        self.load([
            confirmed("earlier-enrollment", at=NOW - timedelta(hours=1)),
            confirmed("current-enrollment", at=NOW),
            canceled("current-enrollment", at=self.period_end),
        ])

    def test_cancellation_rate_is_half(self):
        response = self.client.get("/metrics/cancellation-rate")

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["confirmedEnrollments"], 2)
        self.assertEqual(result["canceledEnrollments"], 1)
        self.assertEqual(result["cancellationRate"], 0.5)

    def test_summary_includes_cancellation_rate_results(self):
        metric = self.client.get("/metrics/cancellation-rate")
        summary = self.client.get("/metrics/summary")

        self.assertEqual(metric.status_code, 200)
        self.assertEqual(summary.status_code, 200)
        self.assertEqual(summary.json()["cancellationRate"], metric.json())

    def test_date_filters_restrict_enrollment_events(self):
        response = self.client.get(
            "/metrics/cancellation-rate",
            params={"from": NOW.isoformat(), "to": self.period_end.isoformat()},
        )

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["confirmedEnrollments"], 1)
        self.assertEqual(result["canceledEnrollments"], 0)
        self.assertEqual(result["cancellationRate"], 0.0)

    def test_invalid_date_ranges_return_bad_request(self):
        for start in (NOW, self.period_end):
            with self.subTest(start=start):
                response = self.client.get(
                    "/metrics/cancellation-rate",
                    params={"from": start.isoformat(), "to": NOW.isoformat()},
                )
                self.assertEqual(response.status_code, 400)
