from __future__ import annotations

from bs4 import BeautifulSoup

from orrery_monitor.models import AdapterContext, AdapterResult, FeedBatch, FeedItem
from orrery_monitor.sources.common import canonical_url, clean_text, parse_date_text, preceding_year

ISRO_PRESS_URL = "https://www.isro.gov.in/Press.html"
FEED_ID = "isro-press"


class ISROAdapter:
    source_id = "isro"

    def fetch(self, client, context: AdapterContext) -> AdapterResult:
        response = client.get(ISRO_PRESS_URL)
        items, raw_count, valid_count = parse_press_archive(response.text, context)
        return AdapterResult(
            source_id=self.source_id,
            retrieval_mode="html",
            feeds={
                FEED_ID: FeedBatch(
                    feed_id=FEED_ID,
                    items=items,
                    raw_count=raw_count,
                    valid_count=valid_count,
                )
            },
        )


def parse_press_archive(
    html: str,
    context: AdapterContext,
) -> tuple[tuple[FeedItem, ...], int, int]:
    soup = BeautifulSoup(html, "lxml")
    rows = soup.select("td[class^='title']")
    candidates: list[FeedItem] = []
    raw_count = 0
    valid_count = 0
    cutoff = preceding_year(context.now)

    for title_cell in rows:
        raw_count += 1
        link = title_cell.find("a", href=True)
        row = title_cell.find_parent("tr")
        date_cell = row.select_one("td[class^='date']") if row else None
        title = clean_text(link.get("title")) if link else ""
        if not title and link:
            title = clean_text(link)
        published = parse_date_text(
            clean_text(date_cell),
            (
                "%B %d, %Y",
                "%b %d, %Y",
                "%b, %d, %Y",
                "%b,%d,%Y",
                "%d %B %Y",
                "%d-%m-%Y",
                "%d/%m/%Y",
            ),
        )
        if not link or not title or published is None:
            continue
        valid_count += 1
        if published < cutoff:
            continue
        url = canonical_url(ISRO_PRESS_URL, str(link["href"]))
        candidates.append(
            FeedItem(
                source_id="isro",
                title=title,
                url=url,
                guid=url,
                first_seen_at=context.now,
                published_at=published,
                category="Press Release",
            )
        )

    candidates.sort(key=lambda item: (item.published_at, item.guid), reverse=True)
    selected = tuple(candidates[:100])
    # Safety is evaluated over structurally recognized archive rows, while the
    # first-run backfill filter controls which valid rows enter persistent state.
    return selected, raw_count, valid_count
