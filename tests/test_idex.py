from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from bs4 import BeautifulSoup

from orrery_monitor.config import load_config
from orrery_monitor.http import HttpClient
from orrery_monitor.models import AdapterContext, FeedItem
from orrery_monitor.runner import MonitorRunner
from orrery_monitor.sources.idex import (
    NEWS_URL,
    NOTICES_URL,
    IDEXAdapter,
    parse_news,
    parse_notices,
)
from orrery_monitor.sources.nsil import NSILAdapter
from orrery_monitor.state import FeedState, SourceSafetyError, load_state, save_state

FIXTURES = Path(__file__).parent / "fixtures"
CONFIG = load_config(Path(__file__).parents[1] / "sources.yml")
NOW = datetime(2026, 11, 4, tzinfo=UTC)


def fixture(name):
    return (FIXTURES / name).read_text()


def context():
    return AdapterContext(now=NOW, source_config=CONFIG.source("idex"), prior_feed_states={})


def test_current_notice_tables_include_archives_and_preserve_existing_ids():
    items, raw, valid = parse_notices(fixture("idex_notices_table.html"), context())
    assert (raw, valid, len(items)) == (26, 26, 5)
    assert items[0].guid == "https://idex.gov.in/uploads/notice/EOI.pdf"
    assert items[0].published_at == datetime(2026, 8, 6, tzinfo=UTC)
    assert all(item.category == "Notice" for item in items)
    assert len({item.guid for item in items}) == 5


def test_notice_table_uses_headers_even_if_columns_and_presentation_change():
    html = fixture("idex_notices_table.html")
    soup = BeautifulSoup(html, "lxml")
    for table in soup.select("table"):
        table.attrs.clear()
        for row in table.select("tr"):
            first = row.find(["th", "td"], recursive=False)
            row.append(first.extract())
    assert parse_notices(str(soup), context()) == parse_notices(html, context())


@pytest.mark.parametrize("href", [None, "", "#", "javascript:void(0)"])
def test_malformed_notice_is_counted_but_not_published(href):
    soup = BeautifulSoup(fixture("idex_notices_table.html"), "lxml")
    link = soup.select_one("tbody tr a")
    if href is None:
        link.decompose()
    else:
        link["href"] = href
    items, raw, valid = parse_notices(str(soup), context())
    assert (raw, valid, len(items)) == (26, 25, 4)
    assert all(item.guid != "https://idex.gov.in/uploads/notice/EOI.pdf" for item in items)


def test_current_news_markup_keeps_dates_identifiers_and_nested_description():
    items, raw, valid = parse_news(fixture("idex_news_current.html"), context())
    assert (raw, valid, len(items)) == (4, 4, 3)
    assert items[0].title == "BharatInnovates2026"
    assert items[0].published_at == datetime(2026, 6, 14, tzinfo=UTC)
    assert items[0].guid.endswith("/1787222026_4232bff84efba0bf15a2.jpeg")
    assert "EyeROV" in items[0].description


@pytest.mark.parametrize("parser", [parse_notices, parse_news])
def test_unrecognized_successful_html_is_a_content_failure_even_on_first_run(parser):
    with pytest.raises(SourceSafetyError, match="listing not recognized"):
        parser("<html><h1>Service temporarily unavailable</h1></html>", context())


def test_redesigned_idex_recovers_while_nsil_404_remains_failed(tmp_path):
    config = replace(CONFIG, root=tmp_path, sources=(CONFIG.source("idex"), CONFIG.source("nsil")))
    existing = FeedItem(
        source_id="idex", title="Old EOI title",
        url="https://idex.gov.in/uploads/notice/EOI.pdf",
        guid="https://idex.gov.in/uploads/notice/EOI.pdf",
        first_seen_at=datetime(2026, 9, 3, tzinfo=UTC),
        published_at=datetime(2026, 8, 6, tzinfo=UTC),
    )
    save_state(tmp_path / "state/idex-notices.json", FeedState(
        feed_id="idex-notices", items=(existing,), previous_visible_count=26,
    ))

    def respond(request):
        if str(request.url) == NOTICES_URL:
            return httpx.Response(200, text=fixture("idex_notices_table.html"))
        if str(request.url) == NEWS_URL:
            return httpx.Response(200, text=fixture("idex_news_current.html"))
        return httpx.Response(404, text="Not Found")

    runner = MonitorRunner(
        config, {"idex": IDEXAdapter(), "nsil": NSILAdapter()},
        client_factory=lambda: HttpClient(transport=httpx.MockTransport(respond)),
        clock=lambda: NOW,
    )
    statuses = {s.source_id: s for s in runner.run()}
    assert statuses["idex"].status == "ok"
    assert statuses["nsil"].status == "failed"
    assert statuses["nsil"].error_kind == "upstream"
    assert "404" in statuses["nsil"].error
    state = load_state(tmp_path / "state/idex-notices.json", "idex-notices")
    assert len(state.items) == 5
    assert state.previous_visible_count == 26
    same_item = next(item for item in state.items if item.guid == existing.guid)
    assert same_item.first_seen_at == existing.first_seen_at
    assert same_item.title != existing.title
    before = (tmp_path / "feeds/idex-notices.xml").read_bytes()
    runner.run()
    assert (tmp_path / "feeds/idex-notices.xml").read_bytes() == before
