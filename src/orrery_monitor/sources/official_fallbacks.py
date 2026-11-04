"""Bounded, explicitly partial retrieval from alternative government publishers."""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from orrery_monitor.models import FeedItem
from orrery_monitor.sources.common import clean_text, parse_date_text
from orrery_monitor.state import SourceSafetyError, check_observation

PIB_ARCHIVE = "https://www.pib.gov.in/allRel.aspx?lang=1&reg=3"
TENDER_DIRECTORY = (
    "https://etenders.gov.in/eprocure/app?page=FrontEndTendersByOrganisation&service=page"
)
HEADERS = {"User-Agent": "OrrerySourceMonitor/0.1"}
NSIL = re.compile(r"\b(?:NSIL|New\s*Space India Limited)\b", re.I)
DRDO = re.compile(r"\b(?:DRDO|Defence Research and Development Organisation)\b", re.I)


def pib_releases(client, context, *, ministry, select, candidate=lambda title: True):
    """Read current and previous month; the caller specifies the selection policy."""
    soup = BeautifulSoup(client.get(PIB_ARCHIVE, headers=HEADERS).text, "lxml")
    prefix = "ctl00$ContentPlaceHolder1$"
    if soup.select_one('input[name="__VIEWSTATE"]') is None:
        raise SourceSafetyError("PIB archive form not recognized")
    months = [context.now.replace(day=1)]
    count = 2 if context.auxiliary_state.get('pib_backfill_complete') else 12
    for _ in range(count - 1):
        months.append(months[-1].replace(day=1) - timedelta(days=1))
    found = {}
    raw = valid = 0
    for month in months:
        data = {n['name']: n.get('value', '') for n in soup.select('input[type=hidden][name]')}
        for control in soup.select('select[name]'):
            option = control.select_one('option[selected]') or control.select_one('option')
            data[control['name']] = option['value']
        expected = {'ddlMinistry': str(ministry), 'ddlday': '0',
                    'ddlMonth': str(month.month), 'ddlYear': str(month.year)}
        data.update({prefix + k: v for k, v in expected.items()})
        data['__EVENTTARGET'] = prefix + 'ddlday'
        soup = BeautifulSoup(client.post(PIB_ARCHIVE, data=data, headers=HEADERS).text, 'lxml')
        for key, value in expected.items():
            option = soup.select_one(f'select[name="{prefix + key}"] option[selected]')
            if option is None or option.get('value') != value:
                raise SourceSafetyError("PIB archive did not apply requested filters")
        links = soup.select('a[href*="PRID="]')
        for link in links:
            raw += 1
            title = clean_text(link)
            date = link.parent.select_one('.publishdatesmall')
            published = parse_date_text(clean_text(date).removeprefix('Posted On:').strip(),
                                        ('%d %b %Y', '%d %B %Y'))
            url = urljoin(PIB_ARCHIVE, link['href'])
            if urlsplit(url).hostname not in {'www.pib.gov.in', 'pib.gov.in'}:
                continue
            prid = parse_qs(urlsplit(url).query).get('PRID', [''])[0]
            if not title or not published or not prid.isdigit():
                continue
            url = f'https://www.pib.gov.in/PressReleasePage.aspx?PRID={prid}&lang=1&reg=3'
            valid += 1
            if not candidate(title):
                continue
            page = BeautifulSoup(client.get(url, headers=HEADERS).text, 'lxml')
            body = page.select_one('#pibReleaseBody')
            if body is None:
                raise SourceSafetyError(f'PIB release body not recognized: {url}')
            if not select(title + ' ' + clean_text(body)):
                continue
            guid = f'PIB-{prid}'
            # Existing DRDO items may already use this PIB URL as their identifier.
            prior = [item for state in context.prior_feed_states.values() for item in state.items]
            for item in prior:
                if parse_qs(urlsplit(item.url).query).get('PRID') == [prid]:
                    guid = item.guid
                    break
            found[guid] = FeedItem(
                source_id=context.source_config.id, title=title, url=url, guid=guid,
                first_seen_at=context.now, published_at=published,
                category='PIB official release',
                metadata={'publisher': 'Press Information Bureau', 'coverage': 'partial'},
            )
    check_observation(current_count=raw, previous_count=None, valid_count=valid)
    return tuple(found.values()), raw, valid


def nsil_tenders(client, context):
    soup = BeautifulSoup(client.get(TENDER_DIRECTORY).text, 'lxml')
    node = soup.find(string=lambda s: s and s.strip() == 'NewSpace India Limited')
    row = node.find_parent('tr') if node else None
    link = row.select_one('a[href]') if row else None
    if link is None:
        raise SourceSafetyError('eTender organisation directory has no NSIL listing')
    url = urljoin(TENDER_DIRECTORY, link['href'])
    if urlsplit(url).hostname != 'etenders.gov.in':
        raise SourceSafetyError('Unexpected tender directory destination')
    soup = BeautifulSoup(client.get(url).text, 'lxml')
    return parse_nsil_tenders(soup, context)


def parse_nsil_tenders(soup, context):
    table = soup.select_one('table.list_table')
    if table is None or 'Organisation Chain' not in clean_text(table):
        raise SourceSafetyError('eTender listing not recognized')
    rows = [r for r in table.select('tr') if r.select_one('a[title="View Tender Information"]')]
    items = []
    for row in rows:
        cells = row.find_all('td', recursive=False)
        if len(cells) != 6 or not clean_text(cells[5]).startswith('NewSpace India Limited||'):
            continue
        link = cells[4].select_one('a')
        match = re.search(r'\b\d{4}_NSIL_\d+_\d+\b', clean_text(cells[4]))
        try:
            published = datetime.strptime(clean_text(cells[1]), '%d-%b-%Y %I:%M %p').replace(
                tzinfo=ZoneInfo('Asia/Kolkata'))
            closing = datetime.strptime(clean_text(cells[2]), '%d-%b-%Y %I:%M %p').replace(
                tzinfo=ZoneInfo('Asia/Kolkata'))
        except ValueError:
            continue
        if match is None:
            continue
        tender_id = match.group()
        items.append(FeedItem(
            source_id='nsil', title=clean_text(link).strip('[] '),
            url=TENDER_DIRECTORY, guid=tender_id, first_seen_at=context.now,
            published_at=published, category='Active tender',
            description=f'Tender ID: {tender_id}. Closing: {closing.isoformat()}. '
                        'Open NewSpace India Limited in the official directory to view the tender.',
            metadata={'tender_id': tender_id, 'end_date': closing.isoformat(),
                      'publisher': 'Government eProcurement System',
                      'coverage': 'active tenders only'},
        ))
    if not rows:
        raise SourceSafetyError('eTender listing has no recognized tender rows')
    check_observation(current_count=len(rows), previous_count=None, valid_count=len(items))
    return tuple(items), len(rows), len(items)
