from __future__ import annotations

import argparse
import hashlib
import json
import logging
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from orrery_monitor.config import FeedConfig, MonitorConfig, SourceConfig, load_config
from orrery_monitor.http import HttpClient
from orrery_monitor.models import AdapterContext, SourceAdapter, SourceRunStatus
from orrery_monitor.rss import FeedValidationError, generate_rss, validate_rss, validate_rss_file
from orrery_monitor.sources import load_adapters
from orrery_monitor.state import (
    FeedState,
    atomic_write_if_changed,
    check_observation,
    load_auxiliary_state,
    load_state,
    merge_items,
    save_auxiliary_state,
    save_state,
)
from orrery_monitor.status import update_status_files

LOG = logging.getLogger("orrery_monitor")


def _feed_config_hash(config: FeedConfig, self_url: str) -> str:
    payload = {
        "title": config.title,
        "description": config.description,
        "official_link": config.official_link,
        "self_url": self_url,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


class MonitorRunner:
    def __init__(
        self,
        config: MonitorConfig,
        adapters: dict[str, SourceAdapter],
        *,
        client_factory: Any = HttpClient,
        clock: Any = lambda: datetime.now(UTC),
    ) -> None:
        self.config = config
        self.adapters = adapters
        self.client_factory = client_factory
        self.clock = clock

    def run(
        self,
        *,
        source_ids: tuple[str, ...] | None = None,
        dry_run: bool = False,
    ) -> list[SourceRunStatus]:
        if source_ids is None:
            sources = tuple(source for source in self.config.sources if source.enabled)
        else:
            sources = tuple(self.config.source(source_id) for source_id in source_ids)

        statuses: list[SourceRunStatus] = []
        if not sources:
            LOG.warning("No sources are enabled")
            return statuses

        with self.client_factory() as client:
            for source in sources:
                try:
                    statuses.append(self._run_source(source, client, dry_run=dry_run))
                except Exception as exc:  # source isolation is intentional
                    LOG.exception("[%s] failed", source.id)
                    statuses.append(
                        SourceRunStatus(
                            source_id=source.id,
                            status="failed",
                            retrieval_mode=source.retrieval_mode,
                            error=str(exc),
                        )
                    )
        if not dry_run:
            update_status_files(self.config, statuses, self.clock())
        return statuses

    def _run_source(
        self,
        source: SourceConfig,
        client: HttpClient,
        *,
        dry_run: bool,
    ) -> SourceRunStatus:
        if source.adapter not in self.adapters:
            raise KeyError(f"adapter is not registered: {source.adapter}")
        now = self.clock()
        prior_states = {
            feed.id: load_state(self.config.root / "state" / f"{feed.id}.json", feed.id)
            for feed in source.feeds
        }
        auxiliary_path = self.config.root / "state" / f"{source.id}-adapter.json"
        result = self.adapters[source.adapter].fetch(
            client,
            AdapterContext(
                now=now,
                source_config=source,
                prior_feed_states=prior_states,
                auxiliary_state=load_auxiliary_state(auxiliary_path),
            ),
        )
        if result.source_id != source.id:
            raise ValueError(
                f"adapter returned source_id {result.source_id!r}, expected {source.id!r}"
            )

        expected = {feed.id for feed in source.feeds}
        actual = set(result.feeds)
        if actual != expected:
            raise ValueError(
                f"adapter feed mismatch for {source.id}: missing={sorted(expected - actual)}, "
                f"extra={sorted(actual - expected)}"
            )

        staged: list[tuple[Path, bytes]] = []
        state_updates: list[tuple[Path, FeedState]] = []
        warnings = list(result.warnings)
        total_items = 0
        total_new = 0
        total_updated = 0

        for feed_config in source.feeds:
            batch = result.feeds[feed_config.id]
            state_path = self.config.root / "state" / f"{feed_config.id}.json"
            feed_path = self.config.root / feed_config.output
            prior = prior_states[feed_config.id]
            check = check_observation(
                current_count=batch.raw_count,
                previous_count=prior.previous_visible_count,
                valid_count=batch.valid_count,
            )
            warnings.extend(check.warnings)

            self_url = f"{self.config.site_base_url}/{feed_config.output}"
            config_hash = _feed_config_hash(feed_config, self_url)
            merged = merge_items(
                prior,
                batch.items,
                visible_count=batch.raw_count,
                feed_config_hash=config_hash,
                retention=feed_config.retention,
            )
            state_updates.append((state_path, merged.state))
            total_items += len(merged.state.items)
            total_new += merged.new_count
            total_updated += merged.updated_count
            if merged.duplicate_input_count:
                warnings.append(
                    f"{feed_config.id}: deduplicated {merged.duplicate_input_count} input records"
                )

            feed_needs_build = (
                merged.items_changed
                or prior.feed_config_hash != config_hash
                or not feed_path.exists()
            )
            if feed_needs_build:
                rss = generate_rss(
                    feed_config,
                    merged.state.items,
                    self_url=self_url,
                    build_date=now,
                )
                validate_rss(rss)
                staged.append((feed_path, rss))
            elif feed_path.exists():
                validate_rss_file(feed_path)

            LOG.info(
                "[%s] feed=%s current=%d new=%d updated=%d retained=%d",
                source.id,
                feed_config.id,
                batch.raw_count,
                merged.new_count,
                merged.updated_count,
                len(merged.state.items),
            )

        if not dry_run:
            for feed_path, content in staged:
                atomic_write_if_changed(feed_path, content)
            for state_path, state in state_updates:
                save_state(state_path, state)
            if result.auxiliary_state is not None:
                save_auxiliary_state(auxiliary_path, result.auxiliary_state)

        return SourceRunStatus(
            source_id=source.id,
            status="warning" if warnings else "ok",
            retrieval_mode=result.retrieval_mode,
            item_count=total_items,
            new_count=total_new,
            updated_count=total_updated,
            warnings=tuple(warnings),
        )

    def validate_existing(self, source_ids: tuple[str, ...] | None = None) -> list[str]:
        selected = (
            self.config.sources
            if source_ids is None
            else tuple(self.config.source(source_id) for source_id in source_ids)
        )
        errors: list[str] = []
        found = 0
        for source in selected:
            for feed in source.feeds:
                path = self.config.root / feed.output
                if not path.exists():
                    if source.enabled or source_ids is not None:
                        errors.append(f"{feed.id}: required feed does not exist")
                    continue
                found += 1
                try:
                    validate_rss_file(path)
                except FeedValidationError as exc:
                    errors.append(f"{feed.id}: {exc}")
        if found == 0:
            LOG.warning("No generated feeds exist yet")
        return errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run The Orrery source monitors")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("sources.yml"),
    )
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--all", action="store_true", help="run every enabled source")
    target.add_argument("--source", action="append", default=[], help="run one source ID")
    parser.add_argument("--dry-run", action="store_true", help="fetch and parse without writing")
    parser.add_argument(
        "--validate-only", action="store_true", help="validate generated feeds without fetching"
    )
    parser.add_argument("--status-json", action="store_true", help="print run status as JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = build_parser().parse_args(argv)
    config = load_config(args.config)
    runner = MonitorRunner(config, load_adapters())
    selected = tuple(args.source) if args.source else None

    if args.validate_only:
        errors = runner.validate_existing(selected)
        for error in errors:
            LOG.error(error)
        return 1 if errors else 0
    if not args.all and not args.source:
        LOG.error("choose --all or at least one --source")
        return 2

    statuses = runner.run(source_ids=selected, dry_run=args.dry_run)
    if args.status_json:
        print(json.dumps([asdict(status) for status in statuses], indent=2))
    return 1 if any(status.status == "failed" for status in statuses) else 0


if __name__ == "__main__":
    raise SystemExit(main())
