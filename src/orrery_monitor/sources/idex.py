from __future__ import annotations

from bs4 import BeautifulSoup

from orrery_monitor.models import AdapterContext, AdapterResult, FeedBatch, FeedItem
from orrery_monitor.sources.common import (
    canonical_url,
    clean_text,
    parse_date_text,
    preceding_year,
    stable_hash,
)

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
    items: list[FeedItem] = []
    valid_count = 0
    cutoff = preceding_year(context.now)
    for block in blocks:
        date_parts = [clean_text(part) for part in block.select(".eventDateArea li")]
        published = parse_date_text(" ".join(date_parts), ("%d %b %Y", "%d %B %Y"))
        title = clean_text(block.select_one("h4"))
        notice_type = clean_text(block.select_one("h2")) or "Notice"
        link = block.select_one("a[href]")
        if not title or published is None or not link:
            continue
        valid_count += 1
        if published < cutoff:
            continue
        url = canonical_url(NOTICES_URL, str(link["href"]))
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
    return _latest(items), len(blocks), valid_count


def parse_news(
    html: str, context: AdapterContext
) -> tuple[tuple[FeedItem, ...], int, int]:
    soup = BeautifulSoup(html, "lxml")
    blocks = soup.select(".bullContBox .NewCon")
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
