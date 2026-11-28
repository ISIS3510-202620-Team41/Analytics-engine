"""BQ12: Enrollment cancellation rate and advance notice before activities."""

from datetime import datetime

from filters import Filters, build_where, to_db_time, to_utc


def fetch_enrollment_events(conn, f: Filters) -> list:
    """Fetch enrollment transitions under the same date and version filters."""
    where, params = build_where(
        conn, f, ("activity_enrollment_confirmed", "activity_enrollment_canceled")
    )

    # Order dated events first so duplicates retain the earliest known transition.
    query = (
        "SELECT event_id, event_type, enrollment_id, occurred_at, scheduled_start_time "
        "FROM events "
        f"WHERE {where} "
        "ORDER BY occurred_at IS NULL, occurred_at, received_at, event_id"
    )
    return conn.execute(query, params).fetchall()


def _earlier_confirmations(conn, f: Filters, enrollment_ids: set[str]) -> set[str]:
    """Find confirmations strictly before the start of the report window."""
    if f.from_ is None or not enrollment_ids:
        return set()

    period_start = to_db_time(f.from_)

    # Keep each query below SQLite's parameter limit for large reporting periods.
    historical = set()
    ids = list(enrollment_ids)
    for index in range(0, len(ids), 500):
        batch = ids[index:index + 500]
        placeholders = ", ".join("?" for _ in batch)
        query = (
            "SELECT DISTINCT enrollment_id FROM events "
            "WHERE event_type = 'activity_enrollment_confirmed' "
            f"AND enrollment_id IN ({placeholders}) AND occurred_at < ?"
        )
        historical.update(enrollment_id for (enrollment_id,) in conn.execute(query, [*batch, period_start]))
    return historical


def cancellation_rate(conn, f: Filters) -> dict:
    """Measure cancellations among enrollments confirmed in the selected period."""
    confirmed = set()
    cancellations = {}

    # Reenrolling generates a new enrollment ID, so each enrollment counts separately.
    for event_id, event_type, enrollment_id, occurred_at, scheduled_start_time in (
        fetch_enrollment_events(conn, f)
    ):
        if event_type == "activity_enrollment_confirmed":
            if enrollment_id:
                confirmed.add(enrollment_id)
            continue

        # Without an enrollment ID, only repeated copies of the same event can be identified.
        cancellation_key = (enrollment_id, None if enrollment_id else event_id)
        cancellations.setdefault(cancellation_key, (occurred_at, scheduled_start_time))

    unpaired_ids = {
        enrollment_id for enrollment_id, _ in cancellations
        if enrollment_id and enrollment_id not in confirmed
    }
    historical = _earlier_confirmations(conn, f, unpaired_ids)

    matched = 0
    unmatched = 0
    earlier = 0
    late = 0
    missing_timestamps = 0
    total_advance_minutes = 0.0
    distribution = {"under1Hour": 0, "between1And24Hours": 0, "over24Hours": 0}

    for (enrollment_id, _), (occurred_at, scheduled_start_time) in cancellations.items():
        # Only in-period pairs contribute to the rate and timing statistics.
        if enrollment_id not in confirmed:
            if enrollment_id in historical:
                earlier += 1
            else:
                unmatched += 1
            continue

        matched += 1
        try:
            canceled_at = to_utc(datetime.fromisoformat(occurred_at))
            starts_at = to_utc(datetime.fromisoformat(scheduled_start_time))
        except (TypeError, ValueError, OverflowError):
            # Missing or invalid timestamps affect timing statistics only.
            missing_timestamps += 1
            continue

        lead_minutes = (starts_at - canceled_at).total_seconds() / 60
        if lead_minutes <= 0:
            # At or after the activity start there was no advance notice.
            late += 1
            continue

        total_advance_minutes += lead_minutes
        if lead_minutes < 60:
            distribution["under1Hour"] += 1
        elif lead_minutes <= 24 * 60:
            distribution["between1And24Hours"] += 1
        else:
            distribution["over24Hours"] += 1

    advance_samples = sum(distribution.values())
    return {
        "confirmedEnrollments": len(confirmed),
        "canceledEnrollments": matched,
        "cancellationRate": matched / len(confirmed) if confirmed else 0.0,
        "averageAdvanceLeadTimeMinutes": (
            total_advance_minutes / advance_samples if advance_samples else None
        ),
        "lateCancellations": late,
        "unmatchedCancellations": unmatched,
        "cancellationsFromEarlierEnrollments": earlier,
        "cancellationsWithMissingTimestamps": missing_timestamps,
        "leadTimeDistribution": distribution,
    }
