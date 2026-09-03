from __future__ import annotations

from datetime import timedelta

from orrery_monitor.models import AdapterContext, AdapterResult, FeedBatch, FeedItem
from orrery_monitor.sources.common import canonical_url, clean_text, parse_date_text

REPORTS_URL = (
    "https://integration.rajyasabha.digital/committee-integration/api/v1/web/"
    "committee-reports?mstCommId=19&page=1&size=100"
)
PRESS_URL = (
    "https://integration.rajyasabha.digital/committee-integration/api/v1/web/"
    "GetPress_relese_committee?mstCommId=19"
)
OFFICIAL_PAGE = "https://sansad.in/rs/pressRelease"
FEED_ID = "parliament-space-committee"
TARGET_COMMITTEE_ID = 19


class ParliamentSpaceAdapter:
    source_id = "parliament_space"

    def fetch(self, client, context: AdapterContext) -> AdapterResult:
        reports_payload = client.get(REPORTS_URL).json()
        press_payload = client.get(PRESS_URL).json()
        records = reports_payload.get("data", {}).get("records", [])
        press_records = press_payload.get("data", [])
        items, raw_count, valid_count = parse_records(records, press_records, context)
        return AdapterResult(
            source_id=self.source_id,
            retrieval_mode="api",
            feeds={FEED_ID: FeedBatch(FEED_ID, items, raw_count, valid_count)},
        )


def parse_records(
    reports: list[dict], press_records: list[dict], context: AdapterContext
) -> tuple[tuple[FeedItem, ...], int, int]:
    cutoff = context.now - timedelta(days=366 * 2)
    items: list[FeedItem] = []
    eligible_press: list[dict] = []
    relevant_report_dates: dict[str, list[int]] = {}
    raw_count = 0
    valid_count = 0

    for report in reports:
        title = clean_text(report.get("subjectOfTheReport"))
        published = parse_date_text(clean_text(report.get("dateOfPresentation")), ("%d/%m/%Y",))
        url_value = clean_text(report.get("url"))
        report_number = report.get("reportNo")
        if published and published >= cutoff:
            raw_count += 1
        if not title or published is None or not url_value or report_number is None:
            continue
        if published >= cutoff:
            valid_count += 1
        if published < cutoff or "department of space" not in title.casefold():
            continue
        number = int(report_number)
        relevant_report_dates.setdefault(published.date().isoformat(), []).append(number)
        items.append(
            FeedItem(
                source_id="parliament_space",
                title=f"Report {number} — {title}" if not title.startswith(str(number)) else title,
                url=canonical_url(OFFICIAL_PAGE, url_value),
                guid=f"RS-report-{number}",
                first_seen_at=context.now,
                published_at=published,
                category=_document_type(title),
                metadata={
                    "report_number": number,
                    "document_type": _document_type(title),
                },
            )
        )

    for press in press_records:
        if int(press.get("nmastercomid") or 0) != TARGET_COMMITTEE_ID:
            continue
        published = parse_date_text(clean_text(press.get("pub_date")), ("%d/%m/%Y",))
        if published and published >= cutoff:
            raw_count += 1
            eligible_press.append(press)
        if (
            published is not None
            and published >= cutoff
            and clean_text(press.get("txtpress"))
            and press.get("pressid")
        ):
            valid_count += 1

    for press in eligible_press:
        title = clean_text(press.get("txtpress"))
        published = parse_date_text(clean_text(press.get("pub_date")), ("%d/%m/%Y",))
        url_value = clean_text(press.get("rptpressfile_dsp") or press.get("rptpressfilepath"))
        press_id = press.get("pressid")
        if not title or published is None or not url_value or press_id is None:
            continue
        related = relevant_report_dates.get(published.date().isoformat(), [])
        explicit = "department of space" in title.casefold()
        action_bundle = bool(related) and "action taken report" in title.casefold()
        if not explicit and not action_bundle:
            continue
        items.append(
            FeedItem(
                source_id="parliament_space",
                title=title,
                url=canonical_url(OFFICIAL_PAGE, url_value),
                guid=f"RS-press-{int(press_id)}",
                first_seen_at=context.now,
                published_at=published,
                category="Press Release",
                metadata={"press_id": int(press_id), "related_report_numbers": related},
            )
        )

    unique = {item.guid: item for item in items}
    ordered = tuple(
        sorted(
            unique.values(),
            key=lambda item: (item.published_at or item.first_seen_at, item.guid),
            reverse=True,
        )[:100]
    )
    return ordered, raw_count, valid_count


def _document_type(title: str) -> str:
    lowered = title.casefold()
    if "action taken" in lowered:
        return "Action Taken Report"
    if "status of implementation" in lowered:
        return "Status of Implementation"
    if "demand" in lowered and "grant" in lowered:
        return "Demands for Grants"
    return "Committee Report"
