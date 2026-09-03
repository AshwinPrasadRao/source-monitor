from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from orrery_monitor.config import MonitorConfig
from orrery_monitor.models import SourceRunStatus
from orrery_monitor.state import atomic_write_if_changed, load_state

STATUS_PATH = "status.json"
INDEX_PATH = "site/index.html"


def update_status_files(
    config: MonitorConfig,
    statuses: list[SourceRunStatus],
    generated_at: datetime,
) -> dict[str, Any]:
    prior = _load_prior_status(config.root / STATUS_PATH)
    document = build_status_document(config, statuses, generated_at, prior)
    atomic_write_if_changed(
        config.root / STATUS_PATH,
        (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    atomic_write_if_changed(
        config.root / INDEX_PATH,
        render_status_html(document).encode("utf-8"),
    )
    return document


def build_status_document(
    config: MonitorConfig,
    statuses: list[SourceRunStatus],
    generated_at: datetime,
    prior: dict[str, Any] | None = None,
) -> dict[str, Any]:
    prior_feeds = {
        str(entry.get("feed_id")): entry
        for entry in (prior or {}).get("feeds", [])
        if isinstance(entry, dict) and entry.get("feed_id")
    }
    status_by_source = {status.source_id: status for status in statuses}
    feeds: list[dict[str, Any]] = []
    for source in config.sources:
        run_status = status_by_source.get(source.id)
        for feed in source.feeds:
            previous = prior_feeds.get(feed.id, {})
            state = load_state(config.root / "state" / f"{feed.id}.json", feed.id)
            last_new_item = max(
                (item.first_seen_at for item in state.items),
                default=None,
            )
            if run_status is None:
                current_status = str(previous.get("status") or "not_checked")
                last_success = previous.get("last_successful_check")
                retrieval_mode = str(
                    previous.get("retrieval_mode") or source.retrieval_mode
                )
                warnings = previous.get("warnings") or []
                error = previous.get("error")
            else:
                current_status = run_status.status
                retrieval_mode = run_status.retrieval_mode
                warnings = list(run_status.warnings)
                error = run_status.error
                last_success = (
                    generated_at.isoformat()
                    if run_status.status in {"ok", "warning"}
                    else previous.get("last_successful_check")
                )
            feeds.append(
                {
                    "feed_id": feed.id,
                    "feed_title": feed.title,
                    "rss_url": f"{config.site_base_url}/{feed.output}",
                    "official_upstream_urls": list(source.upstream_urls),
                    "retrieval_mode": retrieval_mode,
                    "last_successful_check": last_success,
                    "last_new_item_time": (
                        last_new_item.isoformat() if last_new_item else None
                    ),
                    "item_count": len(state.items),
                    "status": current_status,
                    "warnings": warnings,
                    "error": error,
                }
            )
    return {
        "generated_at": generated_at.isoformat(),
        "project": "The Orrery Source Monitor",
        "feeds": feeds,
    }


def render_status_html(document: dict[str, Any]) -> str:
    rows: list[str] = []
    for feed in document["feeds"]:
        upstreams = "<br>".join(
            f'<a href="{html.escape(url, quote=True)}">{html.escape(url)}</a>'
            for url in feed["official_upstream_urls"]
        )
        status_text = html.escape(str(feed["status"]))
        if feed.get("error"):
            status_text += f"<br><small>{html.escape(str(feed['error']))}</small>"
        rows.append(
            "<tr>"
            f'<td><a href="{html.escape(feed["rss_url"], quote=True)}">'
            f'{html.escape(feed["feed_title"])}</a></td>'
            f"<td>{upstreams}</td>"
            f'<td>{html.escape(feed["retrieval_mode"])}</td>'
            f"<td>{_display(feed['last_successful_check'])}</td>"
            f"<td>{_display(feed['last_new_item_time'])}</td>"
            f'<td>{int(feed["item_count"])}</td>'
            f'<td class="status-{html.escape(str(feed["status"]))}">{status_text}</td>'
            "</tr>"
        )
    generated = html.escape(str(document["generated_at"]))
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>The Orrery Source Monitor</title>
    <style>
      body {{
        font: 15px/1.45 system-ui, sans-serif;
        margin: 2rem auto;
        max-width: 90rem;
        padding: 0 1rem;
      }}
      table {{ border-collapse: collapse; width: 100%; }}
      th, td {{
        border-bottom: 1px solid #ddd;
        padding: .55rem;
        text-align: left;
        vertical-align: top;
      }}
      th {{ background: #f5f5f5; }}
      small, .note {{ color: #555; }}
      .status-failed {{ color: #a00; }}
      .status-warning {{ color: #795b00; }}
      .status-ok {{ color: #075f2d; }}
    </style>
  </head>
  <body>
    <h1>The Orrery Source Monitor</h1>
    <p class="note">
      Operational status for twelve official-source RSS feeds.
      Generated {generated}. <a href="status.json">JSON status</a>.
    </p>
    <table>
      <thead><tr>
        <th>Feed</th><th>Official upstream</th><th>Retrieval</th>
        <th>Last successful check</th><th>Last new item</th>
        <th>Items</th><th>Status</th>
      </tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
  </body>
</html>
"""


def _display(value: Any) -> str:
    return html.escape(str(value)) if value else "—"


def _load_prior_status(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return value if isinstance(value, dict) else {}
