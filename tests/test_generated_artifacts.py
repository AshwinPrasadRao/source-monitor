from __future__ import annotations

import json
from pathlib import Path

import feedparser

from orrery_monitor.config import REQUIRED_FEED_OUTPUTS, load_config
from orrery_monitor.rss import validate_rss_file
from orrery_monitor.state import load_state

ROOT = Path(__file__).parents[1]


def test_all_generated_v1_feeds_match_persistent_state() -> None:
    config = load_config(ROOT / "sources.yml")
    generated = {
        path.relative_to(ROOT).as_posix() for path in (ROOT / "feeds").glob("*.xml")
    }

    assert generated == REQUIRED_FEED_OUTPUTS
    for source in config.sources:
        for feed in source.feeds:
            feed_path = ROOT / feed.output
            validate_rss_file(feed_path)
            parsed = feedparser.parse(feed_path.read_bytes())
            state = load_state(ROOT / "state" / f"{feed.id}.json", feed.id)
            assert [entry.id for entry in parsed.entries] == [
                item.guid for item in state.items
            ]
            assert [entry.link for entry in parsed.entries] == [
                item.url for item in state.items
            ]
            assert len({entry.id for entry in parsed.entries}) == len(parsed.entries)


def test_generated_status_covers_exactly_the_v1_feeds() -> None:
    config = load_config(ROOT / "sources.yml")
    document = json.loads((ROOT / "status.json").read_text(encoding="utf-8"))
    expected_ids = {feed.id for source in config.sources for feed in source.feeds}

    assert {entry["feed_id"] for entry in document["feeds"]} == expected_ids
    assert len(document["feeds"]) == 12
    assert all(entry["status"] in {"ok", "warning", "failed"} for entry in document["feeds"])
