from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from orrery_monitor.config import load_config
from orrery_monitor.models import AdapterContext
from orrery_monitor.sources.inspace import parse_page_payload

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 9, 2, 8, tzinfo=UTC)
CONFIG = load_config(Path(__file__).parents[1] / "sources.yml")


def context() -> AdapterContext:
    return AdapterContext(NOW, CONFIG.source("inspace"), {})


def test_inspace_separates_official_widgets_and_normalizes_links() -> None:
    payload = json.loads((FIXTURES / "inspace_page.json").read_text(encoding="utf-8"))
    announcements, updates, counts = parse_page_payload(payload, context())

    assert counts == (2, 2, 2, 2)
    assert len(announcements) == 2
    assert len(updates) == 1
    assert announcements[0].url == (
        "https://www.inspace.gov.in/inspace/sys_attachment.do?sys_id=abc123"
    )
    assert announcements[0].guid == "inspace-announcement-attachment-abc123"
    assert announcements[0].published_at is None
    assert announcements[1].guid.startswith("inspace-announcement-")
    assert updates[0].url == "https://www.inspace.gov.in/inspace?id=inspace_publications"
    assert updates[0].published_at == datetime(2026, 6, 25, tzinfo=UTC)
    assert "Third-party" not in " ".join(item.title for item in updates)


def test_inspace_missing_stream_fails_safely() -> None:
    with pytest.raises(ValueError, match="missing announcement or update widgets"):
        parse_page_payload({"result": {}}, context())
