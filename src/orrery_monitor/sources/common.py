from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import Tag


def clean_text(value: str | Tag | None) -> str:
    if value is None:
        return ""
    text = value.get_text(" ", strip=True) if isinstance(value, Tag) else str(value)
    return re.sub(r"\s+", " ", text).strip()


def canonical_url(base_url: str, value: str) -> str:
    absolute = urljoin(base_url, value.strip())
    parts = urlsplit(absolute)
    scheme = parts.scheme.lower()
    hostname = (parts.hostname or "").lower()
    port = f":{parts.port}" if parts.port else ""
    netloc = f"{hostname}{port}"
    path = re.sub(r"/{2,}", "/", parts.path) or "/"
    return urlunsplit((scheme, netloc, path, parts.query, ""))


def stable_hash(*parts: str) -> str:
    normalized = "\x1f".join(clean_text(part).casefold() for part in parts)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def parse_date_text(value: str, formats: tuple[str, ...]) -> datetime | None:
    text = clean_text(value)
    for date_format in formats:
        try:
            return datetime.strptime(text, date_format).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def preceding_year(now: datetime) -> datetime:
    try:
        return now.replace(year=now.year - 1)
    except ValueError:
        return now.replace(year=now.year - 1, day=28)
