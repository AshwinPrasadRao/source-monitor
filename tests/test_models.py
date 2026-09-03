from datetime import UTC, datetime

import pytest

from orrery_monitor.models import FeedBatch, FeedItem


def test_feed_item_round_trip_preserves_dates_and_metadata() -> None:
    item = FeedItem(
        source_id="example",
        title="Official notice",
        url="https://example.gov/notice/1",
        guid="notice-1",
        first_seen_at=datetime(2026, 9, 2, 8, tzinfo=UTC),
        published_at=datetime(2026, 9, 1, 6, 30, tzinfo=UTC),
        description="A concise summary.",
        category="Notice",
        metadata={"status": "open", "closing_date": "2026-09-30"},
    )

    assert FeedItem.from_dict(item.to_dict()) == item


def test_feed_item_rejects_naive_dates() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        FeedItem(
            source_id="example",
            title="Notice",
            url="https://example.gov/notice",
            guid="notice",
            first_seen_at=datetime(2026, 9, 2),
        )


def test_feed_batch_rejects_impossible_counts() -> None:
    with pytest.raises(ValueError, match="valid_count"):
        FeedBatch(feed_id="example", items=(), raw_count=1, valid_count=2)
