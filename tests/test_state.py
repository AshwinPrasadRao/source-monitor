from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from orrery_monitor.models import FeedItem
from orrery_monitor.state import (
    FeedState,
    SourceSafetyError,
    check_observation,
    load_state,
    merge_items,
    save_state,
)

NOW = datetime(2026, 9, 2, 8, tzinfo=UTC)


def make_item(index: int, *, title: str | None = None, seen: datetime = NOW) -> FeedItem:
    return FeedItem(
        source_id="example",
        title=title or f"Notice {index}",
        url=f"https://example.gov/notices/{index}",
        guid=f"notice-{index}",
        first_seen_at=seen,
        published_at=NOW - timedelta(days=index),
        metadata={"version": 1},
    )


def test_state_merge_adds_updates_deduplicates_and_preserves_first_seen() -> None:
    original = make_item(1, seen=NOW - timedelta(days=10))
    state = FeedState(feed_id="example", items=(original,), previous_visible_count=1)
    changed = replace(
        make_item(1, title="Corrected notice"),
        metadata={"version": 2},
    )
    new = make_item(2)

    result = merge_items(
        state,
        (changed, new, new),
        visible_count=3,
        feed_config_hash="abc",
        retention=300,
    )

    by_guid = {item.guid: item for item in result.state.items}
    assert result.new_count == 1
    assert result.updated_count == 1
    assert result.duplicate_input_count == 1
    assert by_guid["notice-1"].first_seen_at == original.first_seen_at
    assert by_guid["notice-1"].title == "Corrected notice"


def test_state_merge_retains_disappeared_items_and_applies_retention() -> None:
    existing = tuple(make_item(index) for index in range(5))
    state = FeedState(feed_id="example", items=existing)

    result = merge_items(
        state,
        (),
        visible_count=4,
        feed_config_hash="abc",
        retention=3,
    )

    assert [item.guid for item in result.state.items] == ["notice-0", "notice-1", "notice-2"]


def test_state_file_round_trip(tmp_path) -> None:
    path = tmp_path / "state" / "example.json"
    state = FeedState(
        feed_id="example",
        items=(make_item(1),),
        previous_visible_count=8,
        feed_config_hash="hash",
    )

    assert save_state(path, state)
    assert not save_state(path, state)
    assert load_state(path, "example") == state


@pytest.mark.parametrize(
    ("current", "previous", "valid", "message"),
    [
        (0, 24, 0, "zero records"),
        (4, 24, 4, "collapsed"),
        (151, 10, 151, "exploded"),
        (100, None, 94, "missing required fields"),
    ],
)
def test_failure_guards(current: int, previous: int | None, valid: int, message: str) -> None:
    with pytest.raises(SourceSafetyError, match=message):
        check_observation(
            current_count=current,
            previous_count=previous,
            valid_count=valid,
        )


def test_initial_empty_observation_is_a_warning() -> None:
    check = check_observation(current_count=0, previous_count=None, valid_count=0)

    assert check.warnings == ("initial observation contained zero records",)
