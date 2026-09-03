from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from orrery_monitor.config import load_config
from orrery_monitor.models import AdapterContext
from orrery_monitor.sources.dot_wpc import _matches, parse_dot_json, parse_eservices_html
from orrery_monitor.sources.drdo import matches_filter, parse_page
from orrery_monitor.sources.idex import parse_news, parse_notices
from orrery_monitor.sources.parliament_space import parse_records

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 9, 2, 8, tzinfo=UTC)
CONFIG = load_config(Path(__file__).parents[1] / "sources.yml")


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def context(source_id: str) -> AdapterContext:
    return AdapterContext(
        now=NOW,
        source_config=CONFIG.source(source_id),
        prior_feed_states={},
    )


def test_idex_parses_separate_streams_and_stable_identifiers() -> None:
    notices, notice_raw, notice_valid = parse_notices(
        fixture("idex_notices.html"), context("idex")
    )
    news, news_raw, news_valid = parse_news(fixture("idex_news.html"), context("idex"))

    assert (notice_raw, notice_valid, len(notices)) == (2, 2, 1)
    assert notices[0].guid == "https://idex.gov.in/uploads/notice/aditi-4.pdf"
    assert notices[0].published_at == datetime(2026, 8, 18, tzinfo=UTC)
    assert (news_raw, news_valid, len(news)) == (2, 2, 1)
    assert news[0].guid == "https://www.idex.gov.in/uploads/bulletin/disc-13.jpg"
    assert news[0].url == "https://www.idex.gov.in/bulletin/details"


def test_drdo_filter_is_transparent_and_rejects_general_activity() -> None:
    items, raw, valid, next_href = parse_page(
        fixture("drdo_archive.html"), context("drdo")
    )
    filters = CONFIG.source("drdo").filters

    assert (raw, valid, next_href) == (3, 3, "?page=1")
    assert items[0].url == "https://drdo.gov.in/drdo/press-release/quantum-timing"
    assert matches_filter(items[0].title, filters)
    assert not matches_filter(items[1].title, filters)
    assert matches_filter(items[2].title, filters)
    assert not matches_filter("Space-saving lightweight field shelter", filters)


def test_parliament_keeps_space_reports_and_related_action_press_only() -> None:
    reports = json.loads(fixture("parliament_reports.json"))["data"]["records"]
    press = json.loads(fixture("parliament_press.json"))["data"]
    items, raw, valid = parse_records(reports, press, context("parliament_space"))

    assert (raw, valid) == (6, 6)
    assert {item.guid for item in items} == {
        "RS-report-391",
        "RS-report-398",
        "RS-press-770",
        "RS-press-804",
    }
    action = next(item for item in items if item.guid == "RS-report-398")
    assert action.category == "Action Taken Report"
    assert action.metadata["report_number"] == 398


def test_dot_prefers_service_metadata_then_conservative_terms() -> None:
    gazette, raw, valid = parse_dot_json(
        json.loads(fixture("dot_gazette.json")), context("dot_wpc")
    )
    eservices, html_raw, html_valid = parse_eservices_html(
        fixture("dot_eservices.html"),
        "https://www.eservices.dot.gov.in/",
        context("dot_wpc"),
    )
    filters = CONFIG.source("dot_wpc").filters

    assert (raw, valid, html_raw, html_valid) == (2, 2, 3, 3)
    selected = {item.guid for item in (*gazette, *eservices) if _matches(item, filters)}
    assert "DOT-70860" in selected
    assert "DOT-70861" not in selected
    satellite_url = (
        "https://www.eservices.dot.gov.in/sites/default/files/satellite-procedure.pdf"
    )
    assert satellite_url in selected
    assert "https://www.eservices.dot.gov.in/sites/default/files/network-guidance.pdf" in selected
    assert "https://www.eservices.dot.gov.in/sites/default/files/general-format.pdf" not in selected


def test_phase2_duplicate_inputs_keep_stable_guids() -> None:
    html = fixture("dot_eservices.html")
    first = parse_eservices_html(
        html, "https://www.eservices.dot.gov.in/", context("dot_wpc")
    )[0]
    second = parse_eservices_html(
        html, "https://www.eservices.dot.gov.in/", context("dot_wpc")
    )[0]

    assert [item.guid for item in first] == [item.guid for item in second]
