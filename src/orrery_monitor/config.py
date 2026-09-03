from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REQUIRED_FEED_OUTPUTS = {
    "feeds/dot-wpc-space.xml",
    "feeds/drdo-space-tech.xml",
    "feeds/fcc-icfs-satellite-filings.xml",
    "feeds/idex-news.xml",
    "feeds/idex-notices.xml",
    "feeds/inspace-announcements.xml",
    "feeds/inspace-updates.xml",
    "feeds/isro-press.xml",
    "feeds/nsil-news.xml",
    "feeds/nsil-procurement.xml",
    "feeds/parliament-space-committee.xml",
    "feeds/pib-department-of-space.xml",
}


@dataclass(frozen=True, slots=True)
class FeedConfig:
    id: str
    title: str
    description: str
    output: str
    official_link: str
    retention: int


@dataclass(frozen=True, slots=True)
class SourceConfig:
    id: str
    name: str
    adapter: str
    enabled: bool
    retrieval_mode: str
    upstream_urls: tuple[str, ...]
    feeds: tuple[FeedConfig, ...]
    filters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MonitorConfig:
    root: Path
    site_base_url: str
    default_retention: int
    sources: tuple[SourceConfig, ...]

    def source(self, source_id: str) -> SourceConfig:
        for source in self.sources:
            if source.id == source_id:
                return source
        raise KeyError(f"unknown source: {source_id}")

    @property
    def feed_outputs(self) -> set[str]:
        return {feed.output for source in self.sources for feed in source.feeds}


def load_config(path: Path) -> MonitorConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("configuration root must be a mapping")

    default_retention = int(raw.get("default_retention", 300))
    if default_retention <= 0:
        raise ValueError("default_retention must be positive")

    sources: list[SourceConfig] = []
    source_ids: set[str] = set()
    feed_ids: set[str] = set()
    outputs: set[str] = set()

    for source_raw in raw.get("sources", []):
        feeds: list[FeedConfig] = []
        for feed_raw in source_raw.get("feeds", []):
            feed = FeedConfig(
                id=str(feed_raw["id"]),
                title=str(feed_raw["title"]),
                description=str(feed_raw["description"]),
                output=str(feed_raw["output"]),
                official_link=str(feed_raw["official_link"]),
                retention=int(feed_raw.get("retention", default_retention)),
            )
            if feed.id in feed_ids:
                raise ValueError(f"duplicate feed id: {feed.id}")
            if feed.output in outputs:
                raise ValueError(f"duplicate feed output: {feed.output}")
            if not feed.output.startswith("feeds/") or not feed.output.endswith(".xml"):
                raise ValueError(f"invalid feed output path: {feed.output}")
            if feed.retention <= 0:
                raise ValueError(f"retention must be positive for {feed.id}")
            feed_ids.add(feed.id)
            outputs.add(feed.output)
            feeds.append(feed)

        source = SourceConfig(
            id=str(source_raw["id"]),
            name=str(source_raw["name"]),
            adapter=str(source_raw["adapter"]),
            enabled=bool(source_raw.get("enabled", False)),
            retrieval_mode=str(source_raw["retrieval_mode"]),
            upstream_urls=tuple(str(url) for url in source_raw.get("upstream_urls", [])),
            feeds=tuple(feeds),
            filters=dict(source_raw.get("filters") or {}),
        )
        if source.id in source_ids:
            raise ValueError(f"duplicate source id: {source.id}")
        source_ids.add(source.id)
        sources.append(source)

    if outputs != REQUIRED_FEED_OUTPUTS:
        missing = sorted(REQUIRED_FEED_OUTPUTS - outputs)
        extra = sorted(outputs - REQUIRED_FEED_OUTPUTS)
        raise ValueError(
            f"feed outputs must be exactly the v1 set; missing={missing}, extra={extra}"
        )

    return MonitorConfig(
        root=path.resolve().parent,
        site_base_url=str(raw["site_base_url"]).rstrip("/"),
        default_retention=default_retention,
        sources=tuple(sources),
    )
