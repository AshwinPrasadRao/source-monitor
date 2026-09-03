from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from orrery_monitor.models import AdapterContext, AdapterResult, FeedBatch, FeedItem
from orrery_monitor.sources.common import (
    canonical_url,
    clean_text,
    parse_iso_datetime,
    preceding_year,
    stable_hash,
)

NEWS_URL = "https://www.nsilindia.co.in/news"
TENDERS_URL = "https://www.nsilindia.co.in/tenders"
NEWS_FEED_ID = "nsil-news"
PROCUREMENT_FEED_ID = "nsil-procurement"
TENDER_ID_RE = re.compile(r"Tender\s+ID\s*:\s*([A-Za-z0-9_./-]+)", re.IGNORECASE)
REFERENCE_RE = re.compile(
    r"Tender\s+Reference\s+Number\s+in\s+CPPP\s*[-:]\s*(.+?)"
    r"(?=\s+Tender\s+ID|\s+CPPP\s+Link|$)",
    re.IGNORECASE,
)


class NSILAdapter:
    source_id = "nsil"

    def fetch(self, client, context: AdapterContext) -> AdapterResult:
        news, news_raw, news_valid = _collect_paginated(
            client, NEWS_URL, context, parse_news_page
        )
        tenders, tender_raw, tender_valid = _collect_paginated(
            client, TENDERS_URL, context, parse_tender_page
        )
        return AdapterResult(
            source_id=self.source_id,
            retrieval_mode="html",
            feeds={
                NEWS_FEED_ID: FeedBatch(
                    NEWS_FEED_ID, tuple(news[:100]), news_raw, news_valid
                ),
                PROCUREMENT_FEED_ID: FeedBatch(
                    PROCUREMENT_FEED_ID, tuple(tenders[:100]), tender_raw, tender_valid
                ),
            },
        )


def _collect_paginated(client, start_url: str, context: AdapterContext, parser):
    url: str | None = start_url
    visited: set[str] = set()
    items: list[FeedItem] = []
    raw_count = 0
    valid_count = 0
    cutoff = preceding_year(context.now)

    while url and url not in visited and len(visited) < 20:
        visited.add(url)
        response = client.get(url)
        page_items, page_raw, page_valid, next_url = parser(response.text, context)
        raw_count += page_raw
        valid_count += page_valid
        items.extend(
            item for item in page_items if item.published_at and item.published_at >= cutoff
        )
        dated = [item.published_at for item in page_items if item.published_at]
        if dated and min(dated) < cutoff:
            break
        url = urljoin(start_url, next_url) if next_url else None

    deduplicated = {item.guid: item for item in items}
    ordered = sorted(
        deduplicated.values(),
        key=lambda item: (item.published_at or item.first_seen_at, item.guid),
        reverse=True,
    )
    return ordered, raw_count, valid_count


def _next_href(soup: BeautifulSoup) -> str | None:
    link = soup.select_one("li.pager-next a[href]")
    return str(link["href"]) if link else None


def parse_news_page(
    html: str, context: AdapterContext
) -> tuple[list[FeedItem], int, int, str | None]:
    soup = BeautifulSoup(html, "lxml")
    blocks = soup.select("div.nw_bl_rw")
    items: list[FeedItem] = []
    valid_count = 0
    for block in blocks:
        link = block.select_one("h3 > a[href]")
        date = block.select_one(".news_date [content]")
        title = clean_text(link)
        published = parse_iso_datetime(str(date["content"])) if date else None
        if not link or not title or published is None:
            continue
        valid_count += 1
        url = canonical_url(NEWS_URL, str(link["href"]))
        items.append(
            FeedItem(
                source_id="nsil",
                title=title,
                url=url,
                guid=url,
                first_seen_at=context.now,
                published_at=published,
                category="News",
            )
        )
    return items, len(blocks), valid_count, _next_href(soup)


def parse_tender_page(
    html: str, context: AdapterContext
) -> tuple[list[FeedItem], int, int, str | None]:
    soup = BeautifulSoup(html, "lxml")
    table = soup.select_one("table.custom-style")
    body = table.find("tbody", recursive=False) if table else None
    rows = body.find_all("tr", recursive=False) if body else []
    items: list[FeedItem] = []
    valid_count = 0
    for row in rows:
        cells = row.find_all("td", recursive=False)
        if len(cells) < 6:
            continue
        kind = clean_text(cells[0])
        description = clean_text(cells[1])
        dates = [parse_iso_datetime(str(node["content"])) for node in row.select("[content]")]
        start = dates[0] if dates else None
        end = dates[1] if len(dates) > 1 else None
        status = clean_text(cells[5])
        tender_id_match = TENDER_ID_RE.search(description)
        reference_match = REFERENCE_RE.search(description)
        tender_id = clean_text(tender_id_match.group(1)) if tender_id_match else ""
        reference = clean_text(reference_match.group(1)) if reference_match else ""
        attachments = [
            {
                "title": clean_text(link),
                "url": canonical_url(TENDERS_URL, str(link["href"])),
            }
            for link in cells[4].select("a[href]")
            if clean_text(link)
        ]
        if not kind or not description or start is None:
            continue
        valid_count += 1
        url = attachments[0]["url"] if attachments else TENDERS_URL
        guid = tender_id or reference or (
            url
            if attachments
            else f"nsil-tender-{stable_hash(kind, description, start.isoformat())}"
        )
        summary = _tender_summary(description)
        title = f"{kind} — {summary}" if summary and summary != kind else kind
        metadata = {
            "tender_id": tender_id or None,
            "reference": reference or None,
            "start_date": start.isoformat(),
            "end_date": end.isoformat() if end else None,
            "status": status or None,
            "attachments": attachments,
        }
        items.append(
            FeedItem(
                source_id="nsil",
                title=title,
                url=url,
                guid=guid,
                first_seen_at=context.now,
                published_at=start,
                description=_tender_description(description, end, status),
                category=kind,
                metadata=metadata,
            )
        )
    return items, len(rows), valid_count, _next_href(soup)


def _tender_summary(description: str) -> str:
    before_metadata = re.split(
        r"\s+Tender\s+(?:Reference\s+Number(?:\s+in\s+CPPP)?|ID)\s*[:\-]",
        description,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    return clean_text(before_metadata).strip(" .-")


def _tender_description(description: str, end, status: str) -> str:
    parts = [description]
    if end:
        parts.append(f"Closing date: {end.isoformat()}")
    if status:
        parts.append(f"Status: {status}")
    return " | ".join(parts)
