from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

from bs4 import BeautifulSoup

from orrery_monitor.models import AdapterContext, AdapterResult, FeedBatch, FeedItem
from orrery_monitor.sources.common import (
    canonical_url,
    clean_text,
    parse_date_text,
    preceding_year,
)

DOT_API_URL = (
    "https://www.dot.gov.in/cms/wp-json/document/documents?"
    "document_category=gazette-notifications&limit=100&page=1"
)
DOT_PAGE_URL = "https://www.dot.gov.in/documents/gazettes-notifications"
ESERVICES_URLS = (
    "https://www.eservices.dot.gov.in/",
    "https://eservices.dot.gov.in/circular-notifications-others",
    "https://www.eservices.dot.gov.in/satellite-license",
    "https://www.eservices.dot.gov.in/resources",
)
FEED_ID = "dot-wpc-space"


class DotWPCAdapter:
    source_id = "dot_wpc"

    def fetch(self, client, context: AdapterContext) -> AdapterResult:
        dot_response = client.get(
            DOT_API_URL,
            headers={
                "Accept": "application/json",
                "Referer": DOT_PAGE_URL,
                "User-Agent": "OrrerySourceMonitor/0.1",
            },
        )
        dot_records, dot_raw, dot_valid = parse_dot_json(dot_response.json(), context)
        all_records = list(dot_records)
        raw_count = dot_raw
        valid_count = dot_valid
        for url in ESERVICES_URLS:
            page_records, page_raw, page_valid = parse_eservices_html(
                client.get(url).text, url, context
            )
            all_records.extend(page_records)
            raw_count += page_raw
            valid_count += page_valid

        unique = {item.guid: item for item in all_records}
        selected = [
            item for item in unique.values() if _matches(item, context.source_config.filters)
        ]
        selected.sort(
            key=lambda item: (item.published_at or item.first_seen_at, item.guid),
            reverse=True,
        )
        return AdapterResult(
            source_id=self.source_id,
            retrieval_mode="api+html",
            feeds={
                FEED_ID: FeedBatch(FEED_ID, tuple(selected[:100]), raw_count, valid_count)
            },
        )


def parse_dot_json(
    payload: dict, context: AdapterContext
) -> tuple[list[FeedItem], int, int]:
    posts = payload.get("posts", [])
    items: list[FeedItem] = []
    valid_count = 0
    cutoff = preceding_year(context.now)
    for post in posts:
        acf = post.get("acf_data") or {}
        title = clean_text(acf.get("title") or post.get("post_title"))
        published = parse_date_text(clean_text(acf.get("date")), ("%d/%m/%Y",))
        post_id = post.get("ID")
        slug = clean_text(post.get("post_slug") or post.get("post_name"))
        if not title or published is None or post_id is None or not slug:
            continue
        valid_count += 1
        if published < cutoff:
            continue
        categories = [
            clean_text(value.get("name"))
            for value in post.get("documents_category", [])
        ]
        url = f"{DOT_PAGE_URL}/{slug}"
        items.append(
            FeedItem(
                source_id="dot_wpc",
                title=title,
                url=url,
                guid=f"DOT-{int(post_id)}",
                first_seen_at=context.now,
                published_at=published,
                category=categories[0] if categories else "Gazette Notification",
                metadata={
                    "official_record_id": int(post_id),
                    "service": "",
                    "categories": categories,
                },
            )
        )
    return items, len(posts), valid_count


def parse_eservices_html(
    html: str, base_url: str, context: AdapterContext
) -> tuple[list[FeedItem], int, int]:
    soup = BeautifulSoup(html, "lxml")
    records: list[FeedItem] = []
    raw_count = 0
    valid_count = 0
    cutoff = preceding_year(context.now)
    for table in soup.select("table"):
        headers = {clean_text(th).casefold() for th in table.select("thead th")}
        if "published date" not in headers or "title" not in headers:
            continue
        body = table.find("tbody", recursive=False)
        rows = body.find_all("tr", recursive=False) if body else []
        for row in rows:
            raw_count += 1
            title = _cell(row, "view-title-table-column")
            published = parse_date_text(
                _cell(row, "view-field-circular-date-table-column"), ("%d/%m/%Y",)
            )
            link = row.select_one(".views-field-nothing a[href]")
            if not title or published is None or not link:
                continue
            valid_count += 1
            if published < cutoff:
                continue
            url = normalize_eservices_url(base_url, str(link["href"]))
            category = _cell(row, "view-name-table-column")
            service = _cell(row, "view-field-services-type-table-column")
            records.append(
                FeedItem(
                    source_id="dot_wpc",
                    title=title,
                    url=url,
                    guid=url,
                    first_seen_at=context.now,
                    published_at=published,
                    category=category or "Publication",
                    metadata={
                        "service": service,
                        "issued_by": _cell(
                            row, "view-field-policy-issue-by-table-column"
                        ),
                    },
                )
            )

    for container in soup.select(".psn-container"):
        date_element = container.select_one(".policy-circular-presentation")
        if date_element is None:
            continue
        raw_count += 1
        title = clean_text(container.select_one(".psn-name"))
        published = parse_date_text(
            clean_text(date_element), ("%d/%m/%Y",)
        )
        link = container.select_one("a[href]")
        if not title or published is None or not link:
            continue
        valid_count += 1
        if published < cutoff:
            continue
        url = normalize_eservices_url(base_url, str(link["href"]))
        records.append(
            FeedItem(
                source_id="dot_wpc",
                title=title,
                url=url,
                guid=url,
                first_seen_at=context.now,
                published_at=published,
                category=clean_text(container.select_one(".badge")) or "Publication",
                metadata={"service": "Satellite License", "issued_by": "WPC"},
            )
        )
    return records, raw_count, valid_count


def _cell(row, header: str) -> str:
    return clean_text(row.select_one(f'[headers="{header}"]'))


def normalize_eservices_url(base_url: str, value: str) -> str:
    url = canonical_url(base_url, value)
    parts = urlsplit(url)
    if parts.hostname == "eservices.dot.gov.in":
        return urlunsplit(
            (parts.scheme, "www.eservices.dot.gov.in", parts.path, parts.query, "")
        )
    return url


def _matches(item: FeedItem, filters: dict) -> bool:
    service = clean_text(item.metadata.get("service"))
    if any(marker in service.casefold() for marker in ("wpc", "satellite")):
        return True
    text = f"{item.title} {service}".casefold()
    return any(_contains(text, str(term)) for term in filters.get("concepts", []))


def _contains(text: str, term: str) -> bool:
    needle = clean_text(term).casefold()
    if len(needle) <= 4:
        return bool(re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", text))
    return needle in text
