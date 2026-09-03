from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

from orrery_monitor.models import FeedItem

STATE_SCHEMA_VERSION = 1


class SourceSafetyError(RuntimeError):
    """Raised when an observation looks like a source or parser failure."""


@dataclass(frozen=True, slots=True)
class ObservationCheck:
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FeedState:
    feed_id: str
    items: tuple[FeedItem, ...] = ()
    previous_visible_count: int | None = None
    feed_config_hash: str | None = None
    schema_version: int = STATE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "feed_id": self.feed_id,
            "previous_visible_count": self.previous_visible_count,
            "feed_config_hash": self.feed_config_hash,
            "items": [item.to_dict() for item in self.items],
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> FeedState:
        version = int(data.get("schema_version", 0))
        if version != STATE_SCHEMA_VERSION:
            raise ValueError(f"unsupported state schema version: {version}")
        items_raw = data.get("items", [])
        if not isinstance(items_raw, list):
            raise ValueError("state items must be a list")
        return cls(
            schema_version=version,
            feed_id=str(data["feed_id"]),
            previous_visible_count=(
                int(data["previous_visible_count"])
                if data.get("previous_visible_count") is not None
                else None
            ),
            feed_config_hash=(
                str(data["feed_config_hash"]) if data.get("feed_config_hash") is not None else None
            ),
            items=tuple(FeedItem.from_dict(item) for item in items_raw),
        )


@dataclass(frozen=True, slots=True)
class MergeResult:
    state: FeedState
    new_count: int
    updated_count: int
    duplicate_input_count: int
    items_changed: bool


def load_state(path: Path, feed_id: str) -> FeedState:
    if not path.exists():
        return FeedState(feed_id=feed_id)
    state = FeedState.from_dict(json.loads(path.read_text(encoding="utf-8")))
    if state.feed_id != feed_id:
        raise ValueError(f"state feed id {state.feed_id!r} does not match {feed_id!r}")
    return state


def merge_items(
    state: FeedState,
    incoming: tuple[FeedItem, ...],
    *,
    visible_count: int,
    feed_config_hash: str,
    retention: int,
) -> MergeResult:
    if retention <= 0:
        raise ValueError("retention must be positive")

    deduplicated: dict[str, FeedItem] = {}
    duplicates = 0
    for item in incoming:
        if item.guid in deduplicated:
            duplicates += 1
        deduplicated[item.guid] = item

    existing = {item.guid: item for item in state.items}
    new_count = 0
    updated_count = 0
    for guid, item in deduplicated.items():
        prior = existing.get(guid)
        if prior is None:
            existing[guid] = item
            new_count += 1
            continue
        candidate = replace(item, first_seen_at=prior.first_seen_at)
        if candidate != prior:
            existing[guid] = candidate
            updated_count += 1

    retained = tuple(
        sorted(
            existing.values(),
            key=lambda item: (item.published_at or item.first_seen_at, item.guid),
            reverse=True,
        )[:retention]
    )
    items_changed = retained != state.items
    merged = FeedState(
        feed_id=state.feed_id,
        items=retained,
        previous_visible_count=visible_count,
        feed_config_hash=feed_config_hash,
    )
    return MergeResult(
        state=merged,
        new_count=new_count,
        updated_count=updated_count,
        duplicate_input_count=duplicates,
        items_changed=items_changed,
    )


def check_observation(
    *,
    current_count: int,
    previous_count: int | None,
    valid_count: int,
) -> ObservationCheck:
    if current_count < 0 or valid_count < 0 or valid_count > current_count:
        raise ValueError("invalid observation counts")
    if current_count == 0:
        if previous_count and previous_count > 0:
            raise SourceSafetyError(
                f"parsed zero records after previously observing {previous_count}"
            )
        return ObservationCheck(("initial observation contained zero records",))

    missing_ratio = (current_count - valid_count) / current_count
    if missing_ratio > 0.05:
        raise SourceSafetyError(
            f"{missing_ratio:.1%} of records are missing required fields (limit 5%)"
        )

    if previous_count and previous_count > 0:
        drop = previous_count - current_count
        if drop >= 5 and current_count < previous_count * 0.35:
            raise SourceSafetyError(
                f"record count collapsed from {previous_count} to {current_count}"
            )
        growth = current_count - previous_count
        if growth >= 100 and current_count > previous_count * 5:
            raise SourceSafetyError(
                f"record count exploded from {previous_count} to {current_count}"
            )

    return ObservationCheck()


def state_bytes(state: FeedState) -> bytes:
    return (json.dumps(state.to_dict(), indent=2, sort_keys=True) + "\n").encode()


def atomic_write_if_changed(path: Path, content: bytes) -> bool:
    if path.exists() and path.read_bytes() == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temp_path = Path(handle.name)
        try:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise
    try:
        os.replace(temp_path, path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    return True


def save_state(path: Path, state: FeedState) -> bool:
    return atomic_write_if_changed(path, state_bytes(state))


def load_auxiliary_state(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    version = int(raw.get("schema_version", 0))
    if version != STATE_SCHEMA_VERSION:
        raise ValueError(f"unsupported auxiliary state schema version: {version}")
    data = raw.get("data", {})
    if not isinstance(data, dict):
        raise ValueError("auxiliary state data must be a mapping")
    return data


def auxiliary_state_bytes(data: dict[str, object]) -> bytes:
    payload = {"schema_version": STATE_SCHEMA_VERSION, "data": data}
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()


def save_auxiliary_state(path: Path, data: dict[str, object]) -> bool:
    return atomic_write_if_changed(path, auxiliary_state_bytes(data))
