from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx

from orrery_monitor.config import load_config
from orrery_monitor.models import AdapterContext
from orrery_monitor.sources.isro import parse_press_archive
from orrery_monitor.sources.nsil import parse_news_page, parse_tender_page
from orrery_monitor.sources.pib_space import PIB_RSS_URL, PIBSpaceAdapter

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 9, 2, 8, tzinfo=UTC)
CONFIG = load_config(Path(__file__).parents[1] / "sources.yml")


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def context(source_id: str, auxiliary_state=None) -> AdapterContext:
    return AdapterContext(
        now=NOW,
        source_config=CONFIG.source(source_id),
        prior_feed_states={},
        auxiliary_state=auxiliary_state or {},
    )


class MappingClient:
    def __init__(self, mapping):
        self.mapping = mapping
        self.requests: list[str] = []

    def get(self, url: str, **kwargs):
        self.requests.append(url)
        result = self.mapping[url]
        if isinstance(result, Exception):
            raise result
        request = httpx.Request("GET", url)
        return httpx.Response(200, request=request, content=result.encode())


def test_isro_parses_normalizes_dates_and_applies_initial_backfill() -> None:
    items, raw, valid = parse_press_archive(fixture("isro_press.html"), context("isro"))

    assert (raw, valid) == (3, 3)
    assert len(items) == 1
    assert items[0].title == "Atmospheric Re-entry test"
    assert items[0].url == "https://www.isro.gov.in/Atmospheric_Re_entry.html"
    assert items[0].guid == items[0].url
    assert items[0].published_at == datetime(2026, 8, 12, tzinfo=UTC)


def test_isro_duplicate_rows_produce_the_same_stable_guid() -> None:
    html = fixture("isro_press.html")
    row = html[html.index("<tr>") : html.index("</tr>") + 5]
    duplicated = html.replace("</tbody>", row + "</tbody>")
    items, raw, valid = parse_press_archive(duplicated, context("isro"))

    assert (raw, valid) == (4, 4)
    assert len(items) == 2
    assert items[0].guid == items[1].guid


def test_nsil_news_parses_canonical_url_and_timezone() -> None:
    items, raw, valid, next_url = parse_news_page(fixture("nsil_news.html"), context("nsil"))

    assert (raw, valid) == (2, 2)
    assert next_url == "/news?page=1"
    assert items[0].url == "https://www.nsilindia.co.in/news-details/771"
    assert items[0].published_at.isoformat() == "2026-05-04T00:00:00+05:30"
    assert items[0].guid == items[0].url


def test_nsil_tender_preserves_id_dates_status_and_attachments() -> None:
    items, raw, valid, next_url = parse_tender_page(
        fixture("nsil_tenders.html"), context("nsil")
    )

    assert (raw, valid, next_url) == (1, 1, None)
    item = items[0]
    assert item.guid == "2026_NSIL_289625_1"
    assert item.url == "https://www.nsilindia.co.in/sites/default/files/InternalAuditRFPDoc.pdf"
    assert item.metadata["reference"] == "NSIL/RFP/IA/2026/02"
    assert item.metadata["status"] == "Open"
    assert item.metadata["end_date"] == "2026-09-23T14:30:00+05:30"
    assert item.metadata["attachments"][0]["title"] == "Internal Audit RFP Doc"
    assert item.title == "Request for Proposal (RFP) — Engagement of Internal Auditor"


def test_pib_filters_by_explicit_department_and_retries_unclassified() -> None:
    rss = fixture("pib_feed.xml")
    space_url = "https://www.pib.gov.in/PressReleasePage.aspx?PRID=2295424&reg=3&lang=2"
    other_url = "https://www.pib.gov.in/PressReleasePage.aspx?PRID=2295000"
    unavailable_url = "https://www.pib.gov.in/PressReleasePage.aspx?PRID=2294000"
    client = MappingClient(
        {
            PIB_RSS_URL: rss,
            space_url: fixture("pib_space_release.html"),
            other_url: fixture("pib_other_release.html"),
            unavailable_url: httpx.ConnectError("temporary failure"),
        }
    )

    first = PIBSpaceAdapter().fetch(client, context("pib_space"))
    batch = first.feeds["pib-department-of-space"]

    assert (batch.raw_count, batch.valid_count) == (3, 3)
    assert [item.guid for item in batch.items] == ["PIB-2295424"]
    assert batch.items[0].metadata["official_department"] == "Department of Space"
    assert any("will be retried" in warning for warning in first.warnings)

    retry_client = MappingClient(
        {
            PIB_RSS_URL: rss,
            unavailable_url: fixture("pib_other_release.html"),
        }
    )
    second = PIBSpaceAdapter().fetch(
        retry_client,
        context("pib_space", first.auxiliary_state),
    )

    assert space_url not in retry_client.requests
    assert other_url not in retry_client.requests
    assert unavailable_url in retry_client.requests
    assert len(second.feeds["pib-department-of-space"].items) == 1


def test_pib_rejects_non_feed_response() -> None:
    client = MappingClient({PIB_RSS_URL: "<html><body>maintenance</body></html>"})

    try:
        PIBSpaceAdapter().fetch(client, context("pib_space"))
    except ValueError as exc:
        assert "did not return RSS" in str(exc)
    else:
        raise AssertionError("non-feed response was accepted")
