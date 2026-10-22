import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from orrery_monitor.config import load_config
from orrery_monitor.report import main


def test_report_surfaces_failing_url_and_escapes_upstream_text(tmp_path, monkeypatch, capsys):
    results = tmp_path / "results.json"
    summary = tmp_path / "summary.md"
    results.write_text(json.dumps([{
        "source_id": "dot_wpc", "status": "failed",
        "error": "https://example.gov/: 403\n::warning::untrusted <html>",
    }]))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))

    assert main([str(results)]) == 0
    assert "dot_wpc: failed" in summary.read_text()
    assert "https://example.gov/: 403" in summary.read_text()
    assert "&lt;html&gt;" in summary.read_text()
    output = capsys.readouterr().out
    assert output.startswith("::error::dot_wpc:")
    assert "%0A::warning::" in output
    assert len(output.splitlines()) == 1


def test_missing_run_results_fail_instead_of_using_old_health(tmp_path, capsys):
    assert main([str(tmp_path / "missing.json")]) == 1
    assert "::error::Monitor produced no usable run report" in capsys.readouterr().out


def all_results():
    config = load_config(Path(__file__).parents[1] / "sources.yml")
    return [
        {"source_id": source.id, "status": "ok", "error_kind": None}
        for source in config.sources if source.enabled
    ]


def outage_results():
    results = all_results()
    drdo = next(r for r in results if r["source_id"] == "drdo")
    drdo.update(status="failed", error_kind="upstream", error="https://drdo.gov.in: timed out")
    return results


def test_report_persists_outage_then_emits_warning_without_mutating_source_health(
    tmp_path, monkeypatch, capsys,
):
    results_path = tmp_path / "results.json"
    state_path = tmp_path / "alerts.json"
    output = tmp_path / "output.txt"
    summary = tmp_path / "summary.md"
    results_path.write_text(json.dumps(outage_results()))
    before_results = results_path.read_bytes()
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    args = [str(results_path), "--alert-state", str(state_path), "--monitor-outcome", "failure"]

    assert main(args) == 0
    assert "alert=true" in output.read_text()
    assert "::error::drdo:" in capsys.readouterr().out
    initial_state = state_path.read_bytes()
    initial_mtime = state_path.stat().st_mtime_ns
    output.write_text("")

    assert main(args) == 0
    assert output.read_text() == "alert=false\n"
    assert "::warning::drdo:" in capsys.readouterr().out
    assert state_path.read_bytes() == initial_state
    assert state_path.stat().st_mtime_ns == initial_mtime
    assert results_path.read_bytes() == before_results
    assert "drdo: failed" in summary.read_text()
    assert "outage continues; already alerted" in summary.read_text()

    # A due reminder must change state, so the workflow commits the new alert time.
    state = json.loads(initial_state)
    yesterday = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
    state["outages"]["drdo"] = {"started_at": yesterday, "last_alerted_at": yesterday}
    state_path.write_text(json.dumps(state))
    output.write_text("")
    assert main(args) == 0
    assert output.read_text() == "alert=true\n"
    assert "daily outage reminder" in summary.read_text()
    assert json.loads(state_path.read_text())["outages"]["drdo"]["last_alerted_at"] != yesterday


@pytest.mark.parametrize("problem", ["missing_source", "wrong_outcome", "corrupt_state"])
def test_invalid_report_fails_without_advancing_alert_state(tmp_path, monkeypatch, capsys, problem):
    results_path = tmp_path / "results.json"
    state_path = tmp_path / "alerts.json"
    output = tmp_path / "output.txt"
    results = outage_results()
    state_path.write_text('{"schema_version": 1, "outages": {}}')
    outcome = "failure"
    if problem == "missing_source":
        results.pop()
    elif problem == "wrong_outcome":
        outcome = "success"
    else:
        state_path.write_text("{broken")
    initial_state = state_path.read_bytes()
    results_path.write_text(json.dumps(results))
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))

    assert main([
        str(results_path), "--alert-state", str(state_path), "--monitor-outcome", outcome,
    ]) == 1
    assert state_path.read_bytes() == initial_state
    assert not output.exists()
    assert "::error::Monitor produced no usable run report" in capsys.readouterr().out
