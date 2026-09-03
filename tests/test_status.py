from __future__ import annotations

from datetime import UTC, datetime

from orrery_monitor.config import FeedConfig, MonitorConfig, SourceConfig
from orrery_monitor.models import FeedItem, SourceRunStatus
from orrery_monitor.state import FeedState, save_state
from orrery_monitor.status import build_status_document, render_status_html

NOW = datetime(2026, 9, 3, 8, tzinfo=UTC)


def config_for(tmp_path) -> MonitorConfig:
    feed = FeedConfig(
        id="test-feed",
        title="Test Feed",
        description="A test feed.",
        output="feeds/test-feed.xml",
        official_link="https://example.gov/source",
        retention=300,
    )
    source = SourceConfig(
        id="test",
        name="Test",
        adapter="test",
        enabled=True,
        retrieval_mode="api",
        upstream_urls=("https://example.gov/source",),
        feeds=(feed,),
    )
    return MonitorConfig(tmp_path, "https://owner.github.io/project", 300, (source,))


def test_status_document_uses_persistent_state_and_renders_links(tmp_path) -> None:
    config = config_for(tmp_path)
    item = FeedItem(
        source_id="test",
        title="Record",
        url="https://example.gov/record",
        guid="record-1",
        first_seen_at=NOW,
        published_at=NOW,
    )
    save_state(
        tmp_path / "state/test-feed.json",
        FeedState("test-feed", (item,), 1, "hash"),
    )
    status = SourceRunStatus("test", "ok", "api", item_count=1, new_count=1)

    document = build_status_document(config, [status], NOW)
    feed = document["feeds"][0]
    page = render_status_html(document)

    assert feed["rss_url"] == "https://owner.github.io/project/feeds/test-feed.xml"
    assert feed["last_successful_check"] == NOW.isoformat()
    assert feed["last_new_item_time"] == NOW.isoformat()
    assert feed["item_count"] == 1
    assert 'href="https://example.gov/source"' in page
    assert 'href="https://owner.github.io/project/feeds/test-feed.xml"' in page


def test_failed_status_preserves_prior_success_time(tmp_path) -> None:
    config = config_for(tmp_path)
    prior_time = "2026-09-01T08:00:00+00:00"
    prior = {
        "feeds": [
            {
                "feed_id": "test-feed",
                "status": "ok",
                "last_successful_check": prior_time,
            }
        ]
    }
    failed = SourceRunStatus(
        "test",
        "failed",
        "api",
        error="upstream unavailable",
    )

    document = build_status_document(config, [failed], NOW, prior)

    assert document["feeds"][0]["status"] == "failed"
    assert document["feeds"][0]["last_successful_check"] == prior_time
