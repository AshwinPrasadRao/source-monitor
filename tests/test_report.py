import json

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
