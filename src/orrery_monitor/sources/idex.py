from __future__ import annotations

from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from orrery_monitor.models import AdapterContext, AdapterResult, FeedBatch, FeedItem
from orrery_monitor.sources.common import (
    canonical_url,
    clean_text,
    parse_date_text,
    preceding_year,
    stable_hash,
)
from orrery_monitor.state import SourceSafetyError

NOTICES_URL = "https://idex.gov.in/notices"
NEWS_URL = "https://www.idex.gov.in/bulletin/details"
NOTICES_FEED_ID = "idex-notices"
NEWS_FEED_ID = "idex-news"


class IDEXAdapter:
    source_id = "idex"

    def fetch(self, client, context: AdapterContext) -> AdapterResult:
        notices_html = client.get(NOTICES_URL).text
        news_html = client.get(NEWS_URL).text
        notices, notices_raw, notices_valid = parse_notices(notices_html, context)
        news, news_raw, news_valid = parse_news(news_html, context)
        return AdapterResult(
            source_id=self.source_id,
            retrieval_mode="html",
            feeds={
                NOTICES_FEED_ID: FeedBatch(
                    NOTICES_FEED_ID, notices, notices_raw, notices_valid
                ),
                NEWS_FEED_ID: FeedBatch(NEWS_FEED_ID, news, news_raw, news_valid),
            },
        )


def parse_notices(
    html: str, context: AdapterContext
) -> tuple[tuple[FeedItem, ...], int, int]:
    soup = BeautifulSoup(html, "lxml")
    blocks = soup.select(".noticeArea")
    records = []
    for block in blocks:
        date_parts = [clean_text(part) for part in block.select(".eventDateArea li")]
        records.append((
            clean_text(block.select_one("h4")),
            clean_text(block.select_one("h2")) or "Notice",
            " ".join(date_parts),
            block.select_one("a[href]"),
        ))

    # The redesigned listing uses tables for both current and archived notices.
    # Match column labels rather than presentation classes or fixed positions.
    tables = 0
    for table in soup.select("table"):
        headers = [clean_text(th).casefold() for th in table.select("thead th")]
        if not {"title", "attachment", "publish date"}.issubset(headers):
            continue
        tables += 1
        for row in table.select("tbody > tr"):
            cells = row.find_all("td", recursive=False)
            fields = dict(zip(headers, cells, strict=False))
            attachment = fields.get("attachment")
            records.append((
                clean_text(fields.get("title")),
                "Notice",
                clean_text(fields.get("publish date")),
                attachment.select_one("a[href]") if attachment else None,
            ))
    if not blocks and not tables:
        raise SourceSafetyError(f"{NOTICES_URL}: notice listing not recognized")

    items: list[FeedItem] = []
    valid_count = 0
    cutoff = preceding_year(context.now)
    for title, notice_type, date_text, link in records:
        published = parse_date_text(date_text, ("%d %b %Y", "%d %B %Y"))
        if not title or published is None or not link:
            continue
        href = str(link["href"]).strip()
        url = canonical_url(NOTICES_URL, href)
        if not href or href.startswith("#") or urlsplit(url).scheme not in {"http", "https"}:
            continue
        valid_count += 1
        if published < cutoff:
            continue
        items.append(
            FeedItem(
                source_id="idex",
                title=title,
                url=url,
                guid=url,
                first_seen_at=context.now,
                published_at=published,
                category=notice_type,
            )
        )
    return _latest(items), len(records), valid_count


def parse_news(
    html: str, context: AdapterContext
) -> tuple[tuple[FeedItem, ...], int, int]:
    soup = BeautifulSoup(html, "lxml")
    blocks = soup.select(".bullContBox .NewCon")
    if not blocks:
        raise SourceSafetyError(f"{NEWS_URL}: news listing not recognized")
    items: list[FeedItem] = []
    valid_count = 0
    cutoff = preceding_year(context.now)
    for block in blocks:
        title = clean_text(block.select_one("h3"))
        published = parse_date_text(clean_text(block.select_one("span")), ("%d %B %Y",))
        description = clean_text(block.select_one("p"))
        container = block.find_parent(class_="bullContBox")
        image = container.select_one("img[src]") if container else None
        if not title or published is None:
            continue
        valid_count += 1
        if published < cutoff:
            continue
        image_url = canonical_url(NEWS_URL, str(image["src"])) if image else ""
        guid = image_url or f"idex-news-{stable_hash(title, published.isoformat())}"
        items.append(
            FeedItem(
                source_id="idex",
                title=title,
                url=NEWS_URL,
                guid=guid,
                first_seen_at=context.now,
                published_at=published,
                description=description or None,
                category="News Update",
                metadata={"image_url": image_url or None},
            )
        )
    return _latest(items), len(blocks), valid_count


def _latest(items: list[FeedItem]) -> tuple[FeedItem, ...]:
    return tuple(
        sorted(
            items,
            key=lambda item: (item.published_at or item.first_seen_at, item.guid),
            reverse=True,
        )[:100]
    )
