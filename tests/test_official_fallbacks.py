from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from bs4 import BeautifulSoup

from orrery_monitor.config import load_config
from orrery_monitor.models import AdapterContext, FeedItem, SourceRunStatus
from orrery_monitor.sources.official_fallbacks import (
    NSIL,
    PIB_ARCHIVE,
    TENDER_DIRECTORY,
    parse_nsil_tenders,
    pib_releases,
)
from orrery_monitor.state import FeedState, SourceSafetyError
from orrery_monitor.status import build_status_document, render_status_html

CONFIG = load_config(Path(__file__).parents[1] / 'sources.yml')
NOW = datetime(2026, 11, 4, tzinfo=UTC)
PREFIX = 'ctl00$ContentPlaceHolder1$'


def context(source='nsil', states=None, backfilled=True):
    return AdapterContext(NOW, CONFIG.source(source), states or {},
                          {'pib_backfill_complete': backfilled})


def form(values):
    return '<input type="hidden" name="__VIEWSTATE" value="fixture">' + ''.join(
        f'<select name="{PREFIX}{key}"><option selected value="{value}">x</option></select>'
        for key, value in values.items()
    )


class ArchiveClient:
    def __init__(self, *, bad_filters=False, bad_body=False):
        self.posts = []
        self.bad_filters = bad_filters
        self.bad_body = bad_body

    def get(self, url, **kwargs):
        if url == PIB_ARCHIVE:
            return httpx.Response(200, text=form({}))
        assert 'lang=1&reg=3' in url
        return httpx.Response(200, text=(
            '<h1>Unavailable</h1>' if self.bad_body
            else '<div id="pibReleaseBody">NewSpace India Limited (NSIL) signed a contract.</div>'
        ))

    def post(self, url, *, data, **kwargs):
        self.posts.append(data)
        values = {k.removeprefix(PREFIX): v for k, v in data.items() if k.startswith(PREFIX)}
        if self.bad_filters:
            values['ddlMinistry'] = '0'
        return httpx.Response(200, text=form(values) + '''
        <ul><li><a href="/PressReleaseDetail.aspx?PRID=12345">Commercial space activities</a>
        <span class="publishdatesmall">Posted On: 03 Nov 2026</span></li></ul>''')


def test_pib_checks_release_body_and_deduplicates_across_months():
    client = ArchiveClient()
    items, raw, valid = pib_releases(client, context(), ministry=14, select=NSIL.search)
    assert (raw, valid, len(items)) == (2, 2, 1)
    assert items[0].guid == 'PIB-12345'
    assert items[0].published_at == datetime(2026, 11, 3, tzinfo=UTC)
    assert items[0].metadata['coverage'] == 'partial'
    assert [p[PREFIX + 'ddlMonth'] for p in client.posts] == ['11', '10']


def test_initial_archive_backfill_is_bounded_and_preserves_existing_pib_identifier():
    old = FeedItem('drdo', 'Old title', 'https://pib.gov.in/old?PRID=12345',
                   'existing-url-guid', NOW)
    client = ArchiveClient()
    items, _, _ = pib_releases(client, context('drdo', {'feed': FeedState('feed', (old,))}, False),
                               ministry=33, select=lambda text: True)
    assert len(client.posts) == 12
    assert items[0].guid == old.guid


@pytest.mark.parametrize('bad', ['bad_filters', 'bad_body'])
def test_unrecognized_pib_response_fails_without_claiming_success(bad):
    with pytest.raises(SourceSafetyError):
        pib_releases(ArchiveClient(**{bad: True}), context(), ministry=14, select=NSIL.search)


def test_nonmatching_release_is_not_published():
    items, _, _ = pib_releases(ArchiveClient(), context(), ministry=14,
                               select=lambda text: False)
    assert items == ()


TENDERS = '''<table class="list_table"><tr><td>Organisation Chain</td></tr><tr>
<td>1</td><td>03-Nov-2026 05:00 PM</td><td>25-Nov-2026 02:30 PM</td><td>26-Nov-2026 02:30 PM</td>
<td><a title="View Tender Information" href="?session=volatile">[Satellite separation system]</a>
[NSIL/26-27/RFP-16/IBL298/02][2026_NSIL_296767_1]</td>
<td>NewSpace India Limited||NewSpace India Limited - Bangalore||Purchase - NSIL</td>
</tr></table>'''


def test_tenders_use_stable_id_and_indian_timezone_not_session_url():
    items, raw, valid = parse_nsil_tenders(BeautifulSoup(TENDERS, 'lxml'), context())
    assert (raw, valid) == (1, 1)
    assert items[0].guid == '2026_NSIL_296767_1'
    assert items[0].url == TENDER_DIRECTORY
    assert items[0].published_at.isoformat() == '2026-11-03T17:00:00+05:30'
    assert '2026_NSIL_296767_1' in items[0].description


@pytest.mark.parametrize('html', [
    '<html>Maintenance</html>',
    TENDERS.replace('NewSpace India Limited||', 'Other Organisation||'),
    TENDERS.replace('03-Nov-2026 05:00 PM', 'bad date'),
])
def test_bad_tender_pages_fail_safely(html):
    with pytest.raises(SourceSafetyError):
        parse_nsil_tenders(BeautifulSoup(html, 'lxml'), context())


def test_partial_status_keeps_full_success_time_and_shows_coverage_warning(tmp_path):
    from dataclasses import replace
    config = replace(CONFIG, root=tmp_path, sources=(CONFIG.source('nsil'),))
    prior = {'feeds': [{'feed_id': 'nsil-news', 'last_successful_check': '2026-10-01'}]}
    status = SourceRunStatus('nsil', 'warning', 'pib+etenders-partial',
                             warnings=('Partial coverage: active tenders only',))
    doc = build_status_document(config, [status], NOW, prior)
    assert doc['feeds'][0]['last_successful_check'] == '2026-10-01'
    assert doc['feeds'][0]['last_partial_check'] == NOW.isoformat()
    assert 'Partial coverage: active tenders only' in render_status_html(doc)
