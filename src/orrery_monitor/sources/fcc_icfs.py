from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlencode

from orrery_monitor.models import AdapterContext, AdapterResult, FeedBatch, FeedItem
from orrery_monitor.sources.common import clean_text, parse_iso_datetime

LOG = logging.getLogger("orrery_monitor")
ICFS_URL = "https://fccprod.servicenowservices.com/icfs"
WIDGET_URL = (
    "https://fccprod.servicenowservices.com/api/now/sp/widget/"
    "842c213fdb4a0410d02ffb0e0f961934"
)
FEED_ID = "fcc-icfs-satellite-filings"
SESSION_TOKEN_PATTERN = re.compile(r"\bg_ck\s*=\s*'([^']+)'")
PORTAL_ID_PATTERN = re.compile(r"\bportal_id\s*=\s*'([0-9a-f]{32})'")


class FCCICFSAdapter:
    source_id = "fcc_icfs"

    def fetch(self, client, context: AdapterContext) -> AdapterResult:
        bootstrap = client.get(ICFS_URL).text
        token, portal_id = parse_session_bootstrap(bootstrap)
        allowed_types = tuple(
            str(value) for value in context.source_config.filters["filing_types"]
        )
        payload = build_widget_request(allowed_types)
        response = client.post(
            WIDGET_URL,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Referer": ICFS_URL,
                "X-UserToken": token,
                "x-portal": portal_id,
            },
            json=payload,
        )
        items, raw_count, valid_count = parse_widget_payload(
            response.json(), context, frozenset(allowed_types)
        )
        rejected = valid_count - len(items)
        warnings: tuple[str, ...] = ()
        if rejected:
            warnings = (
                f"ICFS server filter returned {rejected} structurally valid "
                "record(s) outside the configured SAT filing classes",
            )
        LOG.info(
            "[FCC-ICFS] satellite_space_station_records=%d new_candidates=%d",
            raw_count,
            len(items),
        )
        return AdapterResult(
            source_id=self.source_id,
            retrieval_mode="api",
            feeds={FEED_ID: FeedBatch(FEED_ID, items, raw_count, valid_count)},
            warnings=warnings,
        )


def parse_session_bootstrap(html: str) -> tuple[str, str]:
    token_match = SESSION_TOKEN_PATTERN.search(html)
    portal_match = PORTAL_ID_PATTERN.search(html)
    if token_match is None or portal_match is None:
        raise ValueError("ICFS public page did not expose its guest session bootstrap")
    return token_match.group(1), portal_match.group(1)


def build_widget_request(allowed_types: tuple[str, ...]) -> dict[str, Any]:
    if not allowed_types:
        raise ValueError("FCC ICFS filing_types must not be empty")
    query = f"subsystem=SAT^filing_typeIN{','.join(allowed_types)}"
    return {
        "title": "Satellite Space Station Filings",
        "table": "x_fmc_ibfs_base_table",
        "filter": query,
        "fields": (
            "number,call_sign,applicant_name,submission_date,subsystem,filing_type"
        ),
        "o": "submission_date",
        "d": "desc",
        "p": 1,
        "window_size": 100,
        "view": "default",
        "url": "?id=ibfs_application_summary&number=Number",
        "u": "number",
        "show_breadcrumbs": "true",
        "show_only_breadcrumbs": "true",
    }


def parse_widget_payload(
    payload: dict[str, Any],
    context: AdapterContext,
    allowed_types: frozenset[str],
) -> tuple[tuple[FeedItem, ...], int, int]:
    result = payload.get("result")
    data = result.get("data") if isinstance(result, dict) else None
    records = data.get("list") if isinstance(data, dict) else None
    if not isinstance(records, list):
        raise ValueError("ICFS widget response is missing its public filing list")
    if data.get("invalid_table"):
        raise ValueError("ICFS public filing table became unavailable")

    items: list[FeedItem] = []
    valid_count = 0
    for record in records:
        file_number = _field(record, "number")
        applicant = _field(record, "applicant_name", display=True)
        filed_value = _field(record, "submission_date")
        subsystem = _field(record, "subsystem")
        filing_type = _field(record, "filing_type")
        filing_label = _field(record, "filing_type", display=True)
        sys_id = clean_text(record.get("sys_id"))
        published = parse_iso_datetime(filed_value.replace(" ", "T"))
        if (
            not file_number
            or not applicant
            or published is None
            or not subsystem
            or not filing_type
            or not filing_label
            or not sys_id
        ):
            continue
        valid_count += 1
        if subsystem != "SAT" or filing_type not in allowed_types:
            continue
        call_sign = _field(record, "call_sign", display=True)
        url = f"{ICFS_URL}?{urlencode({'id': 'ibfs_application_summary', 'number': file_number})}"
        description_parts = [applicant]
        if call_sign:
            description_parts.append(f"Call sign/Auth ID: {call_sign}")
        items.append(
            FeedItem(
                source_id="fcc_icfs",
                title=f"{file_number} — {applicant} — {filing_label}",
                url=url,
                guid=file_number,
                first_seen_at=context.now,
                published_at=published,
                description="; ".join(description_parts),
                category=filing_label,
                metadata={
                    "file_number": file_number,
                    "record_id": sys_id,
                    "target_table": clean_text(record.get("targetTable")),
                    "subsystem": subsystem,
                    "filing_type": filing_type,
                    "applicant": applicant,
                    "call_sign": call_sign or None,
                },
            )
        )
    items.sort(
        key=lambda item: (item.published_at or item.first_seen_at, item.guid),
        reverse=True,
    )
    return tuple(items), len(records), valid_count


def _field(record: dict[str, Any], name: str, *, display: bool = False) -> str:
    field = record.get(name)
    if not isinstance(field, dict):
        return ""
    key = "display_value" if display else "value"
    return clean_text(field.get(key))
