from __future__ import annotations

from datetime import datetime
from pathlib import Path

import feedparser
from feedgen.feed import FeedGenerator
from lxml import etree

from orrery_monitor.config import FeedConfig
from orrery_monitor.models import FeedItem


class FeedValidationError(ValueError):
    """Raised when generated or existing RSS does not satisfy the feed contract."""


def generate_rss(
    config: FeedConfig,
    items: tuple[FeedItem, ...],
    *,
    self_url: str,
    build_date: datetime,
) -> bytes:
    if build_date.tzinfo is None or build_date.utcoffset() is None:
        raise ValueError("build_date must be timezone-aware")

    generator = FeedGenerator()
    generator.title(config.title)
    generator.description(config.description)
    generator.link(href=self_url, rel="self", type="application/rss+xml")
    # Feedgen uses the last alternate-style link as the RSS channel link, so the
    # official upstream must be registered after the Atom self-link.
    generator.link(href=config.official_link, rel="alternate")
    generator.lastBuildDate(build_date)
    generator.language("en")

    for item in items:
        entry = generator.add_entry(order="append")
        entry.title(item.title)
        entry.link(href=item.url)
        entry.guid(item.guid, permalink=False)
        entry.pubDate(item.published_at or item.first_seen_at)
        if item.description:
            entry.description(item.description)
        if item.category:
            entry.category(term=item.category)

    return generator.rss_str(pretty=True)


def validate_rss(content: bytes) -> None:
    try:
        root = etree.fromstring(content, parser=etree.XMLParser(resolve_entities=False))
    except etree.XMLSyntaxError as exc:
        raise FeedValidationError(f"invalid XML: {exc}") from exc
    if root.tag != "rss" or root.get("version") != "2.0":
        raise FeedValidationError("document is not RSS 2.0")

    parsed = feedparser.parse(content)
    if parsed.bozo:
        raise FeedValidationError(f"feedparser rejected feed: {parsed.bozo_exception}")
    for field in ("title", "description", "link"):
        if not parsed.feed.get(field):
            raise FeedValidationError(f"channel is missing {field}")

    guids: list[str] = []
    for entry in parsed.entries:
        for field in ("title", "link", "id"):
            if not entry.get(field):
                raise FeedValidationError(f"item is missing {field}")
        guids.append(str(entry.id))
    if len(guids) != len(set(guids)):
        raise FeedValidationError("feed contains duplicate GUIDs")


def validate_rss_file(path: Path) -> None:
    validate_rss(path.read_bytes())
