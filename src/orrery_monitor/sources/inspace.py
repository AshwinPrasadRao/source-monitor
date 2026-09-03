from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qs, urlsplit

from orrery_monitor.models import AdapterContext, AdapterResult, FeedBatch, FeedItem
from orrery_monitor.sources.common import (
    canonical_url,
    clean_text,
    parse_date_text,
    preceding_year,
    stable_hash,
)

PAGE_API_URL = "https://www.inspace.gov.in/api/now/sp/page?id=inspace_index"
OFFICIAL_URL = "https://www.inspace.gov.in/inspace"
ANNOUNCEMENTS_FEED_ID = "inspace-announcements"
UPDATES_FEED_ID = "inspace-updates"


class INSpaceAdapter:
    source_id = "inspace"

    def fetch(self, client, context: AdapterContext) -> AdapterResult:
        payload = client.get(PAGE_API_URL).json()
        announcements, updates, counts = parse_page_payload(payload, context)
        return AdapterResult(
            source_id=self.source_id,
            retrieval_mode="api",
            feeds={
                ANNOUNCEMENTS_FEED_ID: FeedBatch(
                    ANNOUNCEMENTS_FEED_ID,
                    announcements,
                    counts[0],
                    counts[1],
                ),
                UPDATES_FEED_ID: FeedBatch(
                    UPDATES_FEED_ID,
                    updates,
                    counts[2],
                    counts[3],
                ),
            },
        )


def parse_page_payload(
    payload: dict[str, Any], context: AdapterContext
) -> tuple[tuple[FeedItem, ...], tuple[FeedItem, ...], tuple[int, int, int, int]]:
    announcement_records: list[dict[str, Any]] | None = None
    update_records: list[dict[str, Any]] | None = None
    for widget in _walk_objects(payload):
        options = widget.get("options")
        data = widget.get("data")
        if not isinstance(options, dict) or not isinstance(data, dict):
            continue
        widget_type = clean_text(options.get("type")).casefold()
        if widget_type == "announcement" and isinstance(data.get("launches"), list):
            announcement_records = data["launches"]
        elif widget_type == "update" and isinstance(data.get("updates"), list):
            update_records = data["updates"]

    if announcement_records is None or update_records is None:
        raise ValueError("IN-SPACe page payload is missing announcement or update widgets")

    announcements, announcement_valid = _parse_announcements(
        announcement_records, context
    )
    updates, update_valid = _parse_updates(update_records, context)
    return (
        announcements,
        updates,
        (
            len(announcement_records),
            announcement_valid,
            len(update_records),
            update_valid,
        ),
    )


def _walk_objects(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_objects(child)


def _parse_announcements(
    records: list[dict[str, Any]], context: AdapterContext
) -> tuple[tuple[FeedItem, ...], int]:
    items: list[FeedItem] = []
    valid_count = 0
    for record in records:
        title = clean_text(record.get("launchdata"))
        if not title:
            continue
        valid_count += 1
        link = clean_text(record.get("link"))
        url = canonical_url(OFFICIAL_URL, link) if link else OFFICIAL_URL
        guid = _stable_guid("announcement", url, title, None)
        items.append(
            FeedItem(
                source_id="inspace",
                title=title,
                url=url,
                guid=guid,
                first_seen_at=context.now,
                category="Announcement",
            )
        )
    return tuple(items[:100]), valid_count


def _parse_updates(
    records: list[dict[str, Any]], context: AdapterContext
) -> tuple[tuple[FeedItem, ...], int]:
    items: list[FeedItem] = []
    valid_count = 0
    cutoff = preceding_year(context.now)
    for record in records:
        title = clean_text(record.get("content"))
        if not title:
            continue
        valid_count += 1
        published = parse_date_text(clean_text(record.get("date")), ("%B %d, %Y",))
        if published is not None and published < cutoff:
            continue
        link = clean_text(record.get("link"))
        url = canonical_url(OFFICIAL_URL, link) if link else OFFICIAL_URL
        guid = _stable_guid("update", url, title, published.isoformat() if published else None)
        items.append(
            FeedItem(
                source_id="inspace",
                title=title,
                url=url,
                guid=guid,
                first_seen_at=context.now,
                published_at=published,
                category="Update",
            )
        )
    items.sort(
        key=lambda item: (item.published_at or item.first_seen_at, item.guid),
        reverse=True,
    )
    return tuple(items[:100]), valid_count


def _stable_guid(stream: str, url: str, title: str, date_value: str | None) -> str:
    query = parse_qs(urlsplit(url).query)
    attachment_id = query.get("sys_id", [""])[0]
    if attachment_id and "sys_attachment.do" in url:
        return f"inspace-{stream}-attachment-{attachment_id}"
    return f"inspace-{stream}-{stable_hash(url, title, date_value or '')}"
