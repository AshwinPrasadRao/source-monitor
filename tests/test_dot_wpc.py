from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from orrery_monitor.config import load_config
from orrery_monitor.http import HttpClient
from orrery_monitor.models import AdapterContext, FeedItem
from orrery_monitor.runner import MonitorRunner
from orrery_monitor.sources.dot_wpc import (
    DOT_API_URL,
    DOT_USER_AGENT,
    ESERVICES_URLS,
    FEED_ID,
    DotWPCAdapter,
)
from orrery_monitor.state import FeedState, load_auxiliary_state, load_state, save_state
from orrery_monitor.status import update_status_files

ROOT = Path(__file__).parents[1]
NOW = datetime(2026, 9, 14, tzinfo=UTC)
SOURCE = load_config(ROOT / "sources.yml").source("dot_wpc")
ENDPOINTS = (DOT_API_URL, *ESERVICES_URLS)


def response(request):
    name = "dot_gazette.json" if str(request.url) == DOT_API_URL else "dot_eservices.html"
    return httpx.Response(200, text=(ROOT / "tests/fixtures" / name).read_text())


def client_for(handler):
    return HttpClient(transport=httpx.MockTransport(handler), sleep=lambda _: None)


def test_dot_fetches_publication_pages_directly_with_short_identification():
    requested = []

    def handler(request):
        requested.append(str(request.url))
        assert request.headers["User-Agent"] == DOT_USER_AGENT
        assert request.url.path != "/"
        return response(request)

    with client_for(handler) as client:
        result = DotWPCAdapter().fetch(client, AdapterContext(NOW, SOURCE, {}))

    assert requested == list(ENDPOINTS)
    assert not result.errors
    assert result.feeds[FEED_ID].observation_complete


@pytest.mark.parametrize("blocked", ENDPOINTS)
def test_each_blocked_endpoint_is_reported_and_others_continue(blocked):
    requested = []

    def handler(request):
        requested.append(str(request.url))
        return httpx.Response(403) if str(request.url) == blocked else response(request)

    with client_for(handler) as client:
        result = DotWPCAdapter().fetch(client, AdapterContext(NOW, SOURCE, {}))

    assert requested == list(ENDPOINTS)
    assert len(result.errors) == 1
    assert blocked in result.errors[0]
    assert "403" in result.errors[0]
    assert result.feeds[FEED_ID].items
    assert not result.feeds[FEED_ID].observation_complete
    assert blocked not in result.auxiliary_state["endpoint_counts"]


@pytest.mark.parametrize("body", ["<html>Access denied</html>", "<html>New layout</html>"])
def test_http_200_error_or_changed_layout_is_not_treated_as_empty_success(body):
    def handler(request):
        return response(request) if str(request.url) == DOT_API_URL else httpx.Response(
            200, text=body
        )

    with client_for(handler) as client:
        result = DotWPCAdapter().fetch(client, AdapterContext(NOW, SOURCE, {}))

    assert len(result.errors) == len(ESERVICES_URLS)
    assert result.feeds[FEED_ID].items[0].guid == "DOT-70860"


def test_endpoint_count_collapse_is_isolated_without_lowering_its_baseline():
    collapsed = ESERVICES_URLS[0]
    context = AdapterContext(
        NOW, SOURCE, {}, auxiliary_state={"endpoint_counts": {collapsed: 20}}
    )
    with client_for(response) as client:
        result = DotWPCAdapter().fetch(client, context)

    assert len(result.errors) == 1
    assert "record count collapsed from 20 to 3" in result.errors[0]
    assert result.auxiliary_state["endpoint_counts"][collapsed] == 20
    assert result.feeds[FEED_ID].items


def test_changed_api_shape_is_reported_while_html_listings_continue():
    def handler(request):
        return httpx.Response(200, json={"message": "Unavailable"}) if (
            str(request.url) == DOT_API_URL
        ) else response(request)

    with client_for(handler) as client:
        result = DotWPCAdapter().fetch(client, AdapterContext(NOW, SOURCE, {}))

    assert len(result.errors) == 1
    assert "no posts list" in result.errors[0]
    assert result.feeds[FEED_ID].items
    assert all(item.guid != "DOT-70860" for item in result.feeds[FEED_ID].items)


def test_partial_update_preserves_items_count_baseline_and_success_time_then_recovers(tmp_path):
    config = replace(load_config(ROOT / "sources.yml"), root=tmp_path, sources=(SOURCE,))
    old = FeedItem("dot_wpc", "Old satellite notice", "https://example.gov/old", "old", NOW)
    state_path = tmp_path / "state" / f"{FEED_ID}.json"
    save_state(state_path, FeedState(FEED_ID, (old,), 11))
    # An initial successful run creates both a valid feed and endpoint baselines.
    outage = False

    def handler(request):
        if outage and str(request.url) != DOT_API_URL:
            return httpx.Response(403)
        return response(request)

    runner = MonitorRunner(
        config, {"dot_wpc": DotWPCAdapter()},
        client_factory=lambda: client_for(handler), clock=lambda: NOW,
    )
    healthy = runner.run()
    assert healthy[0].status == "ok"
    initial = load_state(state_path, FEED_ID)
    assert initial.previous_visible_count == 11
    # Remove one API item from prior state so partial success must restore it.
    save_state(state_path, replace(initial, items=tuple(
        item for item in initial.items if item.guid != "DOT-70860"
    )))
    before_aux = load_auxiliary_state(tmp_path / "state/dot_wpc-adapter.json")
    outage = True
    partial = runner.run()
    assert partial[0].status == "failed"
    assert partial[0].new_count == 1
    assert "403" in partial[0].error
    after = load_state(state_path, FEED_ID)
    assert {item.guid for item in after.items} == {item.guid for item in initial.items}
    assert after.previous_visible_count == 11  # partial count of 2 cannot replace it
    assert load_auxiliary_state(tmp_path / "state/dot_wpc-adapter.json") == before_aux
    later = datetime(2026, 9, 15, tzinfo=UTC)
    document = update_status_files(config, partial, later)
    assert document["feeds"][0]["last_successful_check"] == NOW.isoformat()
    assert not runner.validate_existing()

    outage = False
    runner.clock = lambda: later
    recovered = runner.run()
    assert recovered[0].status == "ok"
    assert recovered[0].new_count == 0
    assert recovered[0].updated_count == 0
    document = update_status_files(config, recovered, later)
    assert document["feeds"][0]["last_successful_check"] == later.isoformat()


def test_total_outage_preserves_feed_state_and_endpoint_baselines(tmp_path):
    config = replace(load_config(ROOT / "sources.yml"), root=tmp_path, sources=(SOURCE,))
    runner = MonitorRunner(
        config, {"dot_wpc": DotWPCAdapter()},
        client_factory=lambda: client_for(response), clock=lambda: NOW,
    )
    assert runner.run()[0].status == "ok"
    paths = [tmp_path / SOURCE.feeds[0].output, *sorted((tmp_path / "state").glob("*.json"))]
    before = [path.read_bytes() for path in paths]
    runner.client_factory = lambda: client_for(lambda _: httpx.Response(403))
    result = runner.run()
    assert result[0].status == "failed"
    assert "All DoT endpoints failed" in result[0].error
    assert [path.read_bytes() for path in paths] == before
