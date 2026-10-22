"""Render this run's results in Actions without relying on older status files."""

from __future__ import annotations

import argparse
import html
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from orrery_monitor.alerts import plan_alerts, validate_results
from orrery_monitor.config import load_config
from orrery_monitor.state import atomic_write_if_changed


def render_summary(results: list[dict]) -> str:
    lines = ["## Source monitor results", ""]
    for result in results:
        source = html.escape(result["source_id"])
        status = html.escape(result["status"])
        lines.append(f"### {source}: {status}")
        lines.append("")
        if result.get("error"):
            lines.append(f"<pre>{html.escape(result['error'])}</pre>")
        for warning in result.get("warnings", []):
            lines.append(f"- {html.escape(warning)}")
        lines.append("")
    lines.append(
        "Failed sources have incomplete coverage. Older feed items are retained; "
        "See the deployment step for publication status."
    )
    return "\n".join(lines) + "\n"


def annotation(message: str) -> str:
    # Keep upstream text from creating additional workflow commands.
    return message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("--alert-state", type=Path)
    parser.add_argument("--config", type=Path, default=Path("sources.yml"))
    parser.add_argument("--monitor-outcome", choices=("success", "failure"))
    args = parser.parse_args(argv)
    decision = None
    try:
        results = json.loads(args.results.read_text(encoding="utf-8"))
        expected = None
        if args.alert_state:
            expected = {s.id for s in load_config(args.config).sources if s.enabled}
        validate_results(results, expected)
        summary = render_summary(results)
        if args.alert_state:
            failed = any(result["status"] == "failed" for result in results)
            if args.monitor_outcome != ("failure" if failed else "success"):
                raise ValueError("monitor step outcome does not match its source results")
            prior = (
                json.loads(args.alert_state.read_text(encoding="utf-8"))
                if args.alert_state.exists() else None
            )
            decision = plan_alerts(results, prior, datetime.now(UTC))
            summary += "\n### Notifications\n\n"
            for source, reason in decision.notify.items():
                summary += f"- {html.escape(source)}: {reason}.\n"
            for source, due in decision.next_reminders.items():
                summary += (
                    f"- {html.escape(source)}: outage continues; already alerted. "
                    f"Next reminder on the first run at or after {due}.\n"
                )
            if decision.next_reminders:
                summary += (
                    "\nA successful workflow means publication completed without a new alert. "
                    "Failed sources above still have incomplete coverage.\n"
                )
            if not failed:
                summary += "All sources checked successfully.\n"
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"::error::{annotation(f'Monitor produced no usable run report: {exc}')}")
        return 1
    if summary_path := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(summary_path).open("a", encoding="utf-8") as handle:
            handle.write(summary)
    else:
        print(summary)
    if decision is not None:
        atomic_write_if_changed(
            args.alert_state,
            (json.dumps(decision.state, indent=2, sort_keys=True) + "\n").encode(),
        )
        if output_path := os.environ.get("GITHUB_OUTPUT"):
            with Path(output_path).open("a", encoding="utf-8") as handle:
                handle.write(f"alert={str(bool(decision.notify)).lower()}\n")
    for result in results:
        if result["status"] == "failed":
            message = f"{result['source_id']}: {result.get('error') or 'source failed'}"
            level = (
                "warning"
                if decision is not None and result["source_id"] not in decision.notify
                else "error"
            )
            print(f"::{level}::{annotation(message)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
