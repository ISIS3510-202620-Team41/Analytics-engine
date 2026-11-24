"""Regression tests for BQ12 enrollment cancellation reporting."""

from datetime import timedelta

from db import connect
from filters import Filters, to_db_time
from metrics.cancellation_rate import cancellation_rate
from tests.helpers import NOW, DbTestCase, row


def confirmed(enrollment_id, at=NOW, **fields):
    return row(
        "activity_enrollment_confirmed",
        activity_id="same-activity",
        enrollment_id=enrollment_id,
        at=at,
        **fields,
    )


def canceled(enrollment_id, at=NOW, *, lead_minutes=30, **fields):
    scheduled_start = None
    if lead_minutes is not None:
        scheduled_start = to_db_time(at + timedelta(minutes=lead_minutes))
    return row(
        "activity_enrollment_canceled",
        activity_id="same-activity",
        enrollment_id=enrollment_id,
        scheduled_start_time=scheduled_start,
        at=at,
        **fields,
    )


class CancellationRateTests(DbTestCase):
    def report(self, filters=Filters()):
        with connect() as conn:
            return cancellation_rate(conn, filters)

    def test_successful_cancellations_and_distribution_boundaries(self):
        lead_times = [30, 60, 1440, 1500]
        for index, minutes in enumerate(lead_times):
            enrollment_id = str(index)
            self.load([
                confirmed(enrollment_id, NOW - timedelta(hours=1)),
                canceled(enrollment_id, lead_minutes=minutes),
            ])

        result = self.report()
        self.assertEqual(result["confirmedEnrollments"], 4)
        self.assertEqual(result["canceledEnrollments"], 4)
        self.assertEqual(result["cancellationRate"], 1.0)
        self.assertEqual(result["averageAdvanceLeadTimeMinutes"], sum(lead_times) / 4)
        self.assertEqual(result["leadTimeDistribution"], {
            "under1Hour": 1, "between1And24Hours": 2, "over24Hours": 1,
        })

    def test_duplicate_events_count_once_per_transition(self):
        first_cancel = canceled("repeated")
        self.load([
            confirmed("repeated", NOW - timedelta(minutes=10)),
            confirmed("repeated", NOW - timedelta(minutes=5)),
            first_cancel,
            first_cancel,
            canceled("repeated", NOW + timedelta(minutes=5), lead_minutes=10),
        ])

        result = self.report()
        self.assertEqual(result["confirmedEnrollments"], 1)
        self.assertEqual(result["canceledEnrollments"], 1)
        self.assertEqual(result["averageAdvanceLeadTimeMinutes"], 30)

    def test_reenrollment_counts_separately_for_same_user_and_activity(self):
        self.load([
            confirmed("first", NOW - timedelta(hours=1)),
            canceled("first"),
            confirmed("second", NOW + timedelta(minutes=1)),
        ])

        result = self.report()
        self.assertEqual(result["confirmedEnrollments"], 2)
        self.assertEqual(result["canceledEnrollments"], 1)
        self.assertEqual(result["cancellationRate"], 0.5)

    def test_earlier_enrollment_is_distinct_from_missing_confirmation(self):
        self.load([
            confirmed("earlier", NOW - timedelta(days=1)),
            canceled("earlier", NOW + timedelta(minutes=1)),
            canceled("earlier", NOW + timedelta(minutes=2)),
            canceled("missing", NOW + timedelta(minutes=1)),
            canceled(None, NOW + timedelta(minutes=1)),
        ])

        result = self.report(Filters(from_=NOW))
        self.assertEqual(result["confirmedEnrollments"], 0)
        self.assertEqual(result["canceledEnrollments"], 0)
        self.assertEqual(result["cancellationRate"], 0.0)
        self.assertEqual(result["cancellationsFromEarlierEnrollments"], 1)
        self.assertEqual(result["unmatchedCancellations"], 2)
        self.assertIsNone(result["averageAdvanceLeadTimeMinutes"])

    def test_future_confirmation_is_not_an_earlier_enrollment(self):
        end = NOW + timedelta(hours=1)
        self.load([
            canceled("future", NOW),
            confirmed("future", end),
        ])

        for filters in (Filters(from_=NOW, to=end), Filters(to=end)):
            with self.subTest(filters=filters):
                result = self.report(filters)
                self.assertEqual(result["confirmedEnrollments"], 0)
                self.assertEqual(result["canceledEnrollments"], 0)
                self.assertEqual(result["cancellationRate"], 0.0)
                self.assertEqual(result["cancellationsFromEarlierEnrollments"], 0)
                self.assertEqual(result["unmatchedCancellations"], 1)

    def test_late_cancellations_count_in_rate_without_advance_notice(self):
        self.load([
            confirmed("at-start"), canceled("at-start", lead_minutes=0),
            confirmed("after-start"), canceled("after-start", lead_minutes=-1),
        ])

        result = self.report()
        self.assertEqual(result["cancellationRate"], 1.0)
        self.assertEqual(result["lateCancellations"], 2)
        self.assertIsNone(result["averageAdvanceLeadTimeMinutes"])
        self.assertEqual(sum(result["leadTimeDistribution"].values()), 0)

    def test_missing_timestamps_do_not_change_rate(self):
        self.load([
            confirmed("no-start"), canceled("no-start", lead_minutes=None),
            confirmed("bad-time"), canceled("bad-time", occurred_at="invalid"),
        ])

        result = self.report()
        self.assertEqual(result["canceledEnrollments"], 2)
        self.assertEqual(result["cancellationRate"], 1.0)
        self.assertEqual(result["cancellationsWithMissingTimestamps"], 2)
        self.assertIsNone(result["averageAdvanceLeadTimeMinutes"])

    def test_empty_dataset(self):
        result = self.report()
        self.assertEqual(result["cancellationRate"], 0.0)
        self.assertEqual(result["cancellationsFromEarlierEnrollments"], 0)
        self.assertEqual(result["unmatchedCancellations"], 0)
        self.assertIsNone(result["averageAdvanceLeadTimeMinutes"])

    def test_date_filter_is_inclusive_at_start_and_exclusive_at_end(self):
        end = NOW + timedelta(hours=1)
        self.load([
            confirmed("earlier", NOW - timedelta(seconds=1)),
            canceled("earlier", NOW),
            confirmed("inside", NOW),
            canceled("inside", end - timedelta(seconds=1)),
            confirmed("cancel-at-end", NOW),
            canceled("cancel-at-end", end),
            confirmed("join-at-end", end),
        ])

        result = self.report(Filters(from_=NOW, to=end))
        self.assertEqual(result["confirmedEnrollments"], 2)
        self.assertEqual(result["canceledEnrollments"], 1)
        self.assertEqual(result["cancellationRate"], 0.5)
        self.assertEqual(result["cancellationsFromEarlierEnrollments"], 1)
        self.assertEqual(result["unmatchedCancellations"], 0)

        unfiltered = self.report()
        self.assertEqual(unfiltered["confirmedEnrollments"], 4)
        self.assertEqual(unfiltered["canceledEnrollments"], 3)
        self.assertEqual(unfiltered["cancellationsFromEarlierEnrollments"], 0)
