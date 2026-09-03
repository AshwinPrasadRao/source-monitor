from datetime import UTC, datetime

from orrery_monitor.config import FeedConfig, MonitorConfig, SourceConfig
from orrery_monitor.models import AdapterResult, FeedBatch, FeedItem
from orrery_monitor.rss import generate_rss
from orrery_monitor.runner import MonitorRunner
from orrery_monitor.state import FeedState, save_state

NOW = datetime(2026, 9, 2, 8, tzinfo=UTC)


class DummyClient:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None


class StaticAdapter:
    def __init__(self, source_id: str, batch: FeedBatch, auxiliary_state=None) -> None:
        self.source_id = source_id
        self.batch = batch
        self.auxiliary_state = auxiliary_state

    def fetch(self, client, context) -> AdapterResult:
        return AdapterResult(
            source_id=self.source_id,
            retrieval_mode="fixture",
            feeds={self.batch.feed_id: self.batch},
            auxiliary_state=self.auxiliary_state,
        )


class RaisingAdapter:
    source_id = "broken"

    def fetch(self, client, context) -> AdapterResult:
        raise RuntimeError("upstream unavailable")


def make_item(source_id: str, guid: str) -> FeedItem:
    return FeedItem(
        source_id=source_id,
        title=f"Notice {guid}",
        url=f"https://example.gov/{source_id}/{guid}",
        guid=guid,
        first_seen_at=NOW,
        published_at=NOW,
    )


def make_source(source_id: str, feed_id: str) -> SourceConfig:
    return SourceConfig(
        id=source_id,
        name=source_id.title(),
        adapter=source_id,
        enabled=True,
        retrieval_mode="fixture",
        upstream_urls=("https://example.gov",),
        feeds=(
            FeedConfig(
                id=feed_id,
                title=f"{source_id.title()} Feed",
                description="Official notices.",
                output=f"feeds/{feed_id}.xml",
                official_link="https://example.gov",
                retention=300,
            ),
        ),
    )


def test_parser_failure_preserves_existing_state_and_feed(tmp_path) -> None:
    source = make_source("example", "example-feed")
    config = MonitorConfig(tmp_path, "https://owner.github.io/source-monitor", 300, (source,))
    old_item = make_item("example", "old")
    state_path = tmp_path / "state/example-feed.json"
    feed_path = tmp_path / "feeds/example-feed.xml"
    save_state(
        state_path,
        FeedState(
            feed_id="example-feed",
            items=(old_item,),
            previous_visible_count=24,
            feed_config_hash="old-config",
        ),
    )
    feed_path.parent.mkdir(parents=True)
    feed_path.write_bytes(
        generate_rss(
            source.feeds[0],
            (old_item,),
            self_url="https://owner.github.io/source-monitor/feeds/example-feed.xml",
            build_date=NOW,
        )
    )
    before_state = state_path.read_bytes()
    before_feed = feed_path.read_bytes()
    adapter = StaticAdapter(
        "example",
        FeedBatch(feed_id="example-feed", items=(), raw_count=0, valid_count=0),
    )

    statuses = MonitorRunner(
        config,
        {"example": adapter},
        client_factory=DummyClient,
        clock=lambda: NOW,
    ).run()

    assert statuses[0].status == "failed"
    assert state_path.read_bytes() == before_state
    assert feed_path.read_bytes() == before_feed


def test_broken_source_does_not_prevent_another_source_completing(tmp_path) -> None:
    broken = make_source("broken", "broken-feed")
    healthy = make_source("healthy", "healthy-feed")
    healthy_item = make_item("healthy", "new")
    config = MonitorConfig(
        tmp_path,
        "https://owner.github.io/source-monitor",
        300,
        (broken, healthy),
    )
    adapters = {
        "broken": RaisingAdapter(),
        "healthy": StaticAdapter(
            "healthy",
            FeedBatch(
                feed_id="healthy-feed",
                items=(healthy_item,),
                raw_count=1,
                valid_count=1,
            ),
        ),
    }

    statuses = MonitorRunner(
        config,
        adapters,
        client_factory=DummyClient,
        clock=lambda: NOW,
    ).run()

    assert [status.status for status in statuses] == ["failed", "ok"]
    assert (tmp_path / "state/healthy-feed.json").exists()
    assert (tmp_path / "feeds/healthy-feed.xml").exists()


def test_second_identical_run_does_not_rewrite_feed(tmp_path) -> None:
    source = make_source("healthy", "healthy-feed")
    config = MonitorConfig(tmp_path, "https://owner.github.io/source-monitor", 300, (source,))
    item = make_item("healthy", "one")
    adapter = StaticAdapter(
        "healthy",
        FeedBatch(feed_id="healthy-feed", items=(item,), raw_count=1, valid_count=1),
    )
    runner = MonitorRunner(
        config,
        {"healthy": adapter},
        client_factory=DummyClient,
        clock=lambda: NOW,
    )

    first = runner.run()
    feed_path = tmp_path / "feeds/healthy-feed.xml"
    state_path = tmp_path / "state/healthy-feed.json"
    first_feed = feed_path.read_bytes()
    first_state = state_path.read_bytes()
    second = runner.run()

    assert first[0].new_count == 1
    assert second[0].new_count == 0
    assert feed_path.read_bytes() == first_feed
    assert state_path.read_bytes() == first_state


def test_auxiliary_adapter_state_is_saved_only_after_safe_feed_update(tmp_path) -> None:
    source = make_source("example", "example-feed")
    config = MonitorConfig(tmp_path, "https://owner.github.io/source-monitor", 300, (source,))
    item = make_item("example", "one")
    healthy = StaticAdapter(
        "example",
        FeedBatch("example-feed", (item,), raw_count=1, valid_count=1),
        auxiliary_state={"cache": {"one": "classified"}},
    )
    runner = MonitorRunner(
        config,
        {"example": healthy},
        client_factory=DummyClient,
        clock=lambda: NOW,
    )

    assert runner.run()[0].status == "ok"
    auxiliary_path = tmp_path / "state/example-adapter.json"
    before = auxiliary_path.read_bytes()

    unsafe = StaticAdapter(
        "example",
        FeedBatch("example-feed", (), raw_count=0, valid_count=0),
        auxiliary_state={"cache": {"one": "lost"}},
    )
    failed = MonitorRunner(
        config,
        {"example": unsafe},
        client_factory=DummyClient,
        clock=lambda: NOW,
    ).run()

    assert failed[0].status == "failed"
    assert auxiliary_path.read_bytes() == before
