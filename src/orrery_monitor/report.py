"""Render this run's results in Actions without relying on older status files."""

from __future__ import annotations

import argparse
import html
import json
import os
from pathlib import Path


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
    args = parser.parse_args(argv)
    try:
        results = json.loads(args.results.read_text(encoding="utf-8"))
        if not isinstance(results, list) or not results:
            raise ValueError("expected a nonempty list of source results")
        summary = render_summary(results)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"::error::{annotation(f'Monitor produced no usable run report: {exc}')}")
        return 1
    if summary_path := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(summary_path).open("a", encoding="utf-8") as handle:
            handle.write(summary)
    else:
        print(summary)
    for result in results:
        if result["status"] == "failed":
            message = f"{result['source_id']}: {result.get('error') or 'source failed'}"
            print(f"::error::{annotation(message)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
