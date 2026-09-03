from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from orrery_monitor.config import SourceConfig
    from orrery_monitor.state import FeedState


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _require_aware(value: datetime | None, field_name: str) -> None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class FeedItem:
    source_id: str
    title: str
    url: str
    guid: str
    first_seen_at: datetime
    published_at: datetime | None = None
    description: str | None = None
    category: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("source_id", "title", "url", "guid"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be empty")
        _require_aware(self.first_seen_at, "first_seen_at")
        _require_aware(self.published_at, "published_at")

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "title": self.title,
            "url": self.url,
            "guid": self.guid,
            "first_seen_at": self.first_seen_at.isoformat(),
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "description": self.description,
            "category": self.category,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FeedItem:
        return cls(
            source_id=str(data["source_id"]),
            title=str(data["title"]),
            url=str(data["url"]),
            guid=str(data["guid"]),
            first_seen_at=_parse_datetime(str(data["first_seen_at"])),  # type: ignore[arg-type]
            published_at=_parse_datetime(data.get("published_at")),
            description=data.get("description"),
            category=data.get("category"),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True, slots=True)
class FeedBatch:
    feed_id: str
    items: tuple[FeedItem, ...]
    raw_count: int
    valid_count: int

    def __post_init__(self) -> None:
        if self.raw_count < 0 or self.valid_count < 0:
            raise ValueError("record counts must be non-negative")
        if self.valid_count > self.raw_count:
            raise ValueError("valid_count cannot exceed raw_count")


@dataclass(frozen=True, slots=True)
class AdapterResult:
    source_id: str
    retrieval_mode: str
    feeds: dict[str, FeedBatch]
    warnings: tuple[str, ...] = ()
    auxiliary_state: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class AdapterContext:
    now: datetime
    source_config: SourceConfig
    prior_feed_states: dict[str, FeedState]
    auxiliary_state: dict[str, Any] = field(default_factory=dict)


class SourceAdapter(Protocol):
    source_id: str

    def fetch(self, client: Any, context: AdapterContext) -> AdapterResult: ...


@dataclass(frozen=True, slots=True)
class SourceRunStatus:
    source_id: str
    status: str
    retrieval_mode: str
    item_count: int = 0
    new_count: int = 0
    updated_count: int = 0
    warnings: tuple[str, ...] = ()
    error: str | None = None
