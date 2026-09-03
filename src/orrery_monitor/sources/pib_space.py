from __future__ import annotations

import calendar
import re
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import feedparser
from bs4 import BeautifulSoup

from orrery_monitor.models import AdapterContext, AdapterResult, FeedBatch, FeedItem
from orrery_monitor.sources.common import canonical_url, clean_text, stable_hash

PIB_RSS_URL = "https://pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=1"
PIB_DIRECTORY_URL = "https://www.pib.gov.in/ViewRss.aspx?lang=1&reg=1"
FEED_ID = "pib-department-of-space"
TARGET_DEPARTMENT = "Department of Space"
PIB_HEADERS = {"User-Agent": "OrrerySourceMonitor/0.1"}
DEPARTMENT_RE = re.compile(
    r"(?:Department|Ministry)(?:\s+Name)?\s*[:\-]\s*([^|;<>]+)", re.IGNORECASE
)


class PIBSpaceAdapter:
    source_id = "pib_space"

    def fetch(self, client, context: AdapterContext) -> AdapterResult:
        response = client.get(PIB_RSS_URL, headers=PIB_HEADERS)
        parsed = feedparser.parse(response.content)
        if not parsed.version:
            raise ValueError("PIB upstream did not return RSS or Atom")

        raw_cache = context.auxiliary_state.get("classification_cache", {})
        cache = dict(raw_cache) if isinstance(raw_cache, dict) else {}
        warnings: list[str] = []
        items: list[FeedItem] = []
        valid_count = 0
        unclassified = 0

        for entry in parsed.entries:
            title = clean_text(entry.get("title"))
            link_value = clean_text(entry.get("link"))
            if not title or not link_value:
                continue
            valid_count += 1
            url = canonical_url(PIB_DIRECTORY_URL, link_value)
            guid = _release_id(entry, url, title)
            classification = _classification_from_rss(entry)
            department: str | None = None

            if classification:
                department = classification
                cache[guid] = {"classification": _class_name(department), "department": department}
            else:
                prior = cache.get(guid)
                if not isinstance(prior, dict) or prior.get("classification") == "unclassified":
                    try:
                        page = client.get(url, headers=PIB_HEADERS)
                        department = parse_release_department(page.text)
                        cache[guid] = {
                            "classification": (
                                _class_name(department) if department else "unclassified"
                            ),
                            "department": department,
                        }
                    except Exception as exc:  # retry this record on the next monitor run
                        cache[guid] = {
                            "classification": "unclassified",
                            "department": None,
                        }
                        warnings.append(f"PIB {guid}: release page unavailable: {exc}")
                else:
                    department = clean_text(prior.get("department")) or None

            record = cache.get(guid, {})
            if isinstance(record, dict) and record.get("classification") == "unclassified":
                unclassified += 1
                continue
            if _class_name(department) != "space":
                continue

            items.append(
                FeedItem(
                    source_id=self.source_id,
                    title=title,
                    url=url,
                    guid=guid,
                    first_seen_at=context.now,
                    published_at=_entry_date(entry),
                    description=_entry_description(entry),
                    category=TARGET_DEPARTMENT,
                    metadata={"official_department": TARGET_DEPARTMENT, "release_id": guid},
                )
            )

        if unclassified:
            warnings.append(
                f"PIB: {unclassified} release(s) remain unclassified and will be retried"
            )
        cache = dict(list(cache.items())[-2000:])
        batch = FeedBatch(
            feed_id=FEED_ID,
            items=tuple(items[:100]),
            raw_count=len(parsed.entries),
            valid_count=valid_count,
        )
        return AdapterResult(
            source_id=self.source_id,
            retrieval_mode="rss-filter",
            feeds={FEED_ID: batch},
            warnings=tuple(warnings),
            auxiliary_state={"classification_cache": cache},
        )


def parse_release_department(html: str) -> str | None:
    soup = BeautifulSoup(html, "lxml")
    marker = soup.select_one("#MinistryName")
    return clean_text(marker) or None


def _classification_from_rss(entry) -> str | None:
    for key, value in entry.items():
        lowered = str(key).casefold()
        if "department" in lowered or "ministry" in lowered:
            text = clean_text(value)
            if text:
                return text
    for tag in entry.get("tags", []):
        term = clean_text(tag.get("term"))
        if "department" in term.casefold() or "ministry" in term.casefold():
            match = DEPARTMENT_RE.search(term)
            return clean_text(match.group(1)) if match else term
    for field in ("summary", "description"):
        match = DEPARTMENT_RE.search(clean_text(entry.get(field)))
        if match:
            return clean_text(match.group(1))
    return None


def _class_name(department: str | None) -> str:
    if not department:
        return "unclassified"
    return "space" if clean_text(department).casefold() == TARGET_DEPARTMENT.casefold() else "other"


def _release_id(entry, url: str, title: str) -> str:
    query = parse_qs(urlsplit(url).query)
    for key, values in query.items():
        if key.casefold() == "prid" and values and values[0].strip():
            return f"PIB-{values[0].strip()}"
    entry_id = clean_text(entry.get("id") or entry.get("guid"))
    match = re.search(r"(?:PRID=|\bPRID[- :])([0-9]+)", entry_id, re.IGNORECASE)
    if match:
        return f"PIB-{match.group(1)}"
    return f"PIB-{stable_hash(url, title)}"


def _entry_date(entry) -> datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    return datetime.fromtimestamp(calendar.timegm(parsed), tz=UTC)


def _entry_description(entry) -> str | None:
    value = clean_text(entry.get("summary") or entry.get("description"))
    return value or None
