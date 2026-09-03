from datetime import UTC, datetime

import feedparser
import pytest

from orrery_monitor.config import FeedConfig
from orrery_monitor.models import FeedItem
from orrery_monitor.rss import FeedValidationError, generate_rss, validate_rss

BUILD_DATE = datetime(2026, 9, 2, 8, tzinfo=UTC)
CONFIG = FeedConfig(
    id="example",
    title="Example Official Feed",
    description="Official example notices.",
    output="feeds/example.xml",
    official_link="https://example.gov/notices",
    retention=300,
)


def make_item(guid: str) -> FeedItem:
    return FeedItem(
        source_id="example",
        title=f"Notice {guid}",
        url=f"https://example.gov/notices/{guid}",
        guid=guid,
        first_seen_at=BUILD_DATE,
        published_at=datetime(2026, 9, 1, 7, tzinfo=UTC),
        description="Summary only, not a mirrored document.",
        category="Notice",
    )


def test_rss_is_valid_deterministic_and_preserves_official_links() -> None:
    items = (make_item("one"), make_item("two"))

    first = generate_rss(
        CONFIG,
        items,
        self_url="https://owner.github.io/source-monitor/feeds/example.xml",
        build_date=BUILD_DATE,
    )
    second = generate_rss(
        CONFIG,
        items,
        self_url="https://owner.github.io/source-monitor/feeds/example.xml",
        build_date=BUILD_DATE,
    )

    validate_rss(first)
    assert first == second
    parsed = feedparser.parse(first)
    channel_links = {(link.rel, link.href) for link in parsed.feed.links}
    assert ("alternate", CONFIG.official_link) in channel_links
    assert (
        "self",
        "https://owner.github.io/source-monitor/feeds/example.xml",
    ) in channel_links
    assert [entry.link for entry in parsed.entries] == [item.url for item in items]
    assert [entry.id for entry in parsed.entries] == ["one", "two"]


def test_rss_validation_rejects_duplicate_guids() -> None:
    content = generate_rss(
        CONFIG,
        (make_item("same"), make_item("same")),
        self_url="https://owner.github.io/source-monitor/feeds/example.xml",
        build_date=BUILD_DATE,
    )

    with pytest.raises(FeedValidationError, match="duplicate GUID"):
        validate_rss(content)
