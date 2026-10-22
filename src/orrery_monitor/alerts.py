"""Notify once per upstream outage, then at most once per 24 hours per source."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

REMINDER_INTERVAL = timedelta(hours=24)


@dataclass(frozen=True)
class AlertDecision:
    state: dict[str, Any]
    notify: dict[str, str]
    next_reminders: dict[str, str]


def validate_results(results: Any, expected_sources: set[str] | None = None) -> None:
    if not isinstance(results, list) or not results:
        raise ValueError("expected a nonempty list of source results")
    seen: set[str] = set()
    for result in results:
        if not isinstance(result, dict):
            raise ValueError("source result must be an object")
        source = result.get("source_id")
        if not isinstance(source, str) or not source or source in seen:
            raise ValueError("source results must have unique, nonempty source IDs")
        seen.add(source)
        if result.get("status") not in {"ok", "warning", "failed"}:
            raise ValueError(f"invalid status for {source}")
        if result.get("error") is not None and not isinstance(result["error"], str):
            raise ValueError(f"invalid error for {source}")
        warnings = result.get("warnings", [])
        if not isinstance(warnings, list) or not all(isinstance(w, str) for w in warnings):
            raise ValueError(f"invalid warnings for {source}")
    if expected_sources is not None and seen != expected_sources:
        raise ValueError(
            f"incomplete source report: missing={sorted(expected_sources - seen)}, "
            f"unexpected={sorted(seen - expected_sources)}"
        )


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("outage timestamps must be ISO datetime strings")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("outage timestamps must include a timezone")
    return parsed


def plan_alerts(
    results: list[dict], prior: Any, now: datetime,
) -> AlertDecision:
    validate_results(results)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("alert clock must include a timezone")
    if prior is None:
        prior = {"schema_version": 1, "outages": {}}
    if not isinstance(prior, dict) or prior.get("schema_version") != 1:
        raise ValueError("unsupported alert state schema")
    previous = prior.get("outages")
    if not isinstance(previous, dict):
        raise ValueError("alert state outages must be an object")
    for source, outage in previous.items():
        if not isinstance(source, str) or not isinstance(outage, dict):
            raise ValueError("invalid saved outage")
        started = _timestamp(outage.get("started_at"))
        alerted = _timestamp(outage.get("last_alerted_at"))
        if not started <= alerted <= now:
            raise ValueError(f"invalid outage timestamp order for {source}")

    outages: dict[str, dict] = {}
    notify: dict[str, str] = {}
    next_reminders: dict[str, str] = {}
    for result in results:
        source = result["source_id"]
        if result["status"] != "failed":
            continue  # recovery resets the notification window
        if result.get("error_kind") != "upstream":
            # Unknown failures, parser regressions, and safety checks always alert.
            notify[source] = "monitor error"
            continue

        outage = previous.get(source)
        if outage is None:
            notify[source] = "new upstream outage"
            outage = {"started_at": now.isoformat(), "last_alerted_at": now.isoformat()}
        elif now - _timestamp(outage["last_alerted_at"]) >= REMINDER_INTERVAL:
            notify[source] = "daily outage reminder"
            outage = {**outage, "last_alerted_at": now.isoformat()}
        else:
            next_reminders[source] = (
                _timestamp(outage["last_alerted_at"]) + REMINDER_INTERVAL
            ).isoformat()
        outages[source] = dict(outage)

    return AlertDecision({"schema_version": 1, "outages": outages}, notify, next_reminders)
