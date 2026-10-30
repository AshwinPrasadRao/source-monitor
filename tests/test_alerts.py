from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from orrery_monitor.alerts import plan_alerts, validate_results

NOW = datetime(2026, 10, 22, 5, tzinfo=UTC)


def result(source="drdo", status="failed", kind="upstream"):
    return {"source_id": source, "status": status, "error_kind": kind}


def test_first_outage_alerts_then_repeats_stay_quiet_regardless_of_duration():
    first = plan_alerts([result()], None, NOW)
    assert first.notify == {"drdo": "new upstream outage"}
    initial = deepcopy(first.state)

    for hours in (6, 12, 18, 24, 25, 53, 24 * 30, 24 * 365):
        repeat = plan_alerts([result()], first.state, NOW + timedelta(hours=hours))
        assert not repeat.notify
        assert repeat.state == initial  # no extra commits for repeat failures
        assert repeat.continuing_outages == {"drdo": NOW.isoformat()}

    assert first.state == initial  # evaluating a run must not mutate prior state


def test_existing_daily_reminder_history_is_preserved_without_realerting():
    prior = {"schema_version": 1, "outages": {
        "drdo": {"started_at": NOW.isoformat(), "last_alerted_at": NOW.isoformat()},
        "idex": {
            "started_at": (NOW + timedelta(hours=6)).isoformat(),
            "last_alerted_at": (NOW + timedelta(hours=30)).isoformat(),
        },
    }}
    initial = deepcopy(prior)
    later = plan_alerts([result(), result("idex")], prior, NOW + timedelta(days=10))
    assert not later.notify
    assert later.state == initial
    assert prior == initial
    assert set(later.continuing_outages) == {"drdo", "idex"}


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
    assert set(second.continuing_outages) == {"drdo"}


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
