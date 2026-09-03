from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from orrery_monitor.models import AdapterContext, AdapterResult, FeedBatch, FeedItem
from orrery_monitor.sources.common import (
    canonical_url,
    clean_text,
    parse_iso_datetime,
    preceding_year,
)

LOG = logging.getLogger("orrery_monitor")
CURRENT_URL = "https://drdo.gov.in/drdo/documents/press-release"
ARCHIVE_URL = "https://drdo.gov.in/drdo/en/documents/press-release/archive"
FEED_ID = "drdo-space-tech"


class DRDOAdapter:
    source_id = "drdo"

    def fetch(self, client, context: AdapterContext) -> AdapterResult:
        observed: list[FeedItem] = []
        raw_count = 0
        valid_count = 0
        current, raw, valid, _ = parse_page(client.get(CURRENT_URL).text, context)
        observed.extend(current)
        raw_count += raw
        valid_count += valid

        url: str | None = ARCHIVE_URL
        visited: set[str] = set()
        cutoff = preceding_year(context.now)
        while url and url not in visited and len(visited) < 20:
            visited.add(url)
            page_items, raw, valid, next_href = parse_page(client.get(url).text, context)
            observed.extend(page_items)
            raw_count += raw
            valid_count += valid
            dates = [item.published_at for item in page_items if item.published_at]
            if dates and min(dates) < cutoff:
                break
            url = urljoin(ARCHIVE_URL, next_href) if next_href else None

        unique = {item.guid: item for item in observed}
        recent = [
            item
            for item in unique.values()
            if item.published_at and item.published_at >= cutoff
        ]
        matched = [
            item
            for item in recent
            if matches_filter(item.title, context.source_config.filters)
        ]
        matched.sort(
            key=lambda item: (item.published_at or item.first_seen_at, item.guid),
            reverse=True,
        )
        LOG.info(
            "[DRDO] structured=%d recent=%d matched=%d",
            len(unique),
            len(recent),
            len(matched),
        )
        return AdapterResult(
            source_id=self.source_id,
            retrieval_mode="html",
            feeds={
                FEED_ID: FeedBatch(FEED_ID, tuple(matched[:100]), raw_count, valid_count)
            },
        )


def parse_page(
    html: str, context: AdapterContext
) -> tuple[list[FeedItem], int, int, str | None]:
    soup = BeautifulSoup(html, "lxml")
    table = soup.select_one("table.views-view-table")
    body = table.find("tbody", recursive=False) if table else None
    rows = body.find_all("tr", recursive=False) if body else []
    items: list[FeedItem] = []
    valid_count = 0
    for row in rows:
        title = clean_text(row.select_one(".views-field-title"))
        date_node = row.select_one(".views-field-field-date-of-publishing time[datetime]")
        link = row.select_one(".views-field-view-node a[href]")
        published = parse_iso_datetime(str(date_node["datetime"])) if date_node else None
        if not title or published is None or not link:
            continue
        valid_count += 1
        url = canonical_url(CURRENT_URL, str(link["href"]))
        items.append(
            FeedItem(
                source_id="drdo",
                title=title,
                url=url,
                guid=url,
                first_seen_at=context.now,
                published_at=published,
                category="Press Release",
            )
        )
    next_link = soup.select_one(".pager__item--next a[href]")
    return items, len(rows), valid_count, str(next_link["href"]) if next_link else None


def matches_filter(title: str, filters: dict) -> bool:
    text = clean_text(title).casefold()
    for term in filters.get("primary_terms", []):
        if _contains(text, str(term)):
            return True
    for group in filters.get("contextual_groups", []):
        contexts = group.get("all_contexts", [])
        required = group.get("require_any", [])
        if any(_contains(text, str(term)) for term in contexts) and any(
            _contains(text, str(term)) for term in required
        ):
            return True
    return False


def _contains(text: str, term: str) -> bool:
    needle = clean_text(term).casefold()
    if needle.replace("&", "").isalnum():
        return bool(re.search(rf"(?<!\w){re.escape(needle)}(?![\w-])", text))
    return needle in text
