from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from orrery_monitor.config import load_config
from orrery_monitor.models import AdapterContext
from orrery_monitor.sources.fcc_icfs import (
    build_widget_request,
    parse_session_bootstrap,
    parse_widget_payload,
)

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 9, 3, 8, tzinfo=UTC)
CONFIG = load_config(Path(__file__).parents[1] / "sources.yml")


def context() -> AdapterContext:
    return AdapterContext(NOW, CONFIG.source("fcc_icfs"), {})


def allowed_types() -> frozenset[str]:
    return frozenset(CONFIG.source("fcc_icfs").filters["filing_types"])


def test_icfs_parses_public_satellite_space_station_records() -> None:
    payload = json.loads(
        (FIXTURES / "fcc_icfs_widget.json").read_text(encoding="utf-8")
    )
    items, raw, valid = parse_widget_payload(payload, context(), allowed_types())

    assert (raw, valid, len(items)) == (3, 3, 2)
    assert items[0].guid == "SAT-LOA-20260527-00216"
    assert items[0].published_at == datetime(2026, 9, 2, 23, 54, 55, tzinfo=UTC)
    assert items[0].metadata["record_id"] == "f3687362cf810b1006fffff42f851c95"
    assert items[0].url.endswith(
        "id=ibfs_application_summary&number=SAT-LOA-20260527-00216"
    )
    assert items[1].category == "Modification"


def test_icfs_request_is_server_filtered_and_bounded() -> None:
    request = build_widget_request(tuple(sorted(allowed_types())))

    assert request["filter"].startswith("subsystem=SAT^filing_typeIN")
    assert "STA" not in request["filter"].split("IN", 1)[1].split(",")
    assert request["window_size"] == 100
    assert request["o"] == "submission_date"
    assert request["d"] == "desc"


def test_icfs_guest_bootstrap_requires_token_and_portal() -> None:
    html = "g_ck = 'token-value'; portal_id = '6865628b1bd2625069c154e2604bcbf2'"
    assert parse_session_bootstrap(html) == (
        "token-value",
        "6865628b1bd2625069c154e2604bcbf2",
    )
    with pytest.raises(ValueError, match="guest session bootstrap"):
        parse_session_bootstrap("<html>maintenance</html>")


def test_icfs_broken_widget_response_fails_safely() -> None:
    with pytest.raises(ValueError, match="missing its public filing list"):
        parse_widget_payload({"result": {"data": {}}}, context(), allowed_types())
