from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from orrery_monitor.alerts import plan_alerts, validate_results

NOW = datetime(2026, 10, 22, 5, tzinfo=UTC)


def result(source="drdo", status="failed", kind="upstream"):
    return {"source_id": source, "status": status, "error_kind": kind}


def test_first_outage_alerts_then_repeats_are_quiet_until_24_hours():
    first = plan_alerts([result()], None, NOW)
    assert first.notify == {"drdo": "new upstream outage"}
    initial = deepcopy(first.state)

    for hours in (6, 12, 18, 23.99):
        repeat = plan_alerts([result()], first.state, NOW + timedelta(hours=hours))
        assert not repeat.notify
        assert repeat.state == initial  # no extra commits for repeat failures
        assert repeat.next_reminders == {"drdo": (NOW + timedelta(days=1)).isoformat()}

    daily = plan_alerts([result()], first.state, NOW + timedelta(days=1))
    assert daily.notify == {"drdo": "daily outage reminder"}
    assert daily.state["outages"]["drdo"]["started_at"] == NOW.isoformat()
    assert first.state == initial  # evaluating a run must not mutate prior state
    later = plan_alerts([result()], daily.state, NOW + timedelta(hours=30))
    assert not later.notify


def test_delayed_schedule_sends_one_reminder_then_starts_a_new_24_hour_window():
    first = plan_alerts([result()], None, NOW)
    later = plan_alerts([result()], first.state, NOW + timedelta(hours=53))
    assert later.notify == {"drdo": "daily outage reminder"}
    assert not plan_alerts([result()], later.state, NOW + timedelta(hours=54)).notify


@pytest.mark.parametrize("recovered_status", ["ok", "warning"])
def test_recovery_resets_outage_so_a_new_failure_alerts_immediately(recovered_status):
    first = plan_alerts([result()], None, NOW)
    recovered = plan_alerts(
        [result(status=recovered_status)], first.state, NOW + timedelta(hours=1)
    )
    assert recovered.state["outages"] == {}
    assert not recovered.notify
    again = plan_alerts([result()], recovered.state, NOW + timedelta(hours=2))
    assert again.notify == {"drdo": "new upstream outage"}
    assert again.state["outages"]["drdo"]["started_at"] == (
        NOW + timedelta(hours=2)
    ).isoformat()


def test_another_source_failing_alerts_even_during_an_existing_outage():
    first = plan_alerts([result(), result("isro", "ok")], None, NOW)
    second = plan_alerts(
        [result(), result("isro")], first.state, NOW + timedelta(hours=1)
    )
    assert second.notify == {"isro": "new upstream outage"}
    assert set(second.next_reminders) == {"drdo"}


@pytest.mark.parametrize("kind", ["internal", None, "unknown"])
def test_programming_and_unclassified_failures_always_alert(kind):
    previous = plan_alerts([result()], None, NOW)
    for hours in (1, 2):
        decision = plan_alerts([result(kind=kind)], previous.state, NOW + timedelta(hours=hours))
        assert decision.notify == {"drdo": "monitor error"}
        assert decision.state["outages"] == {}
        previous = decision


def test_retired_source_does_not_leave_an_active_outage():
    previous = plan_alerts([result()], None, NOW)
    next_run = plan_alerts([result("isro", "ok")], previous.state, NOW)
    assert next_run.state["outages"] == {}


@pytest.mark.parametrize("prior", [
    {},
    {"schema_version": 99, "outages": {}},
    {"schema_version": 1, "outages": []},
    {"schema_version": 1, "outages": {"drdo": {}}},
    {"schema_version": 1, "outages": {"drdo": {
        "started_at": "2026-10-22T05:00:00", "last_alerted_at": NOW.isoformat(),
    }}},
    {"schema_version": 1, "outages": {"drdo": {
        "started_at": NOW.isoformat(),
        "last_alerted_at": (NOW + timedelta(days=1)).isoformat(),
    }}},
])
def test_bad_saved_state_cannot_silence_alerts(prior):
    with pytest.raises(ValueError):
        plan_alerts([result()], prior, NOW)


@pytest.mark.parametrize("results", [
    [], [result(), result()], [None], [{"source_id": "drdo", "status": "not_checked"}],
])
def test_unusable_results_are_rejected(results):
    with pytest.raises(ValueError):
        validate_results(results)


def test_report_must_cover_exactly_the_enabled_sources():
    with pytest.raises(ValueError, match="missing=.*isro"):
        validate_results([result()], {"drdo", "isro"})
    with pytest.raises(ValueError, match="unexpected=.*drdo"):
        validate_results([result()], {"isro"})
