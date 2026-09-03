from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from orrery_monitor.config import load_config


def build_pages(config_path: Path, output: Path) -> None:
    config = load_config(config_path)
    status_path = config.root / "status.json"
    index_path = config.root / "site/index.html"
    if not status_path.exists() or not index_path.exists():
        raise FileNotFoundError("run the monitor before building the Pages artifact")
    output.mkdir(parents=True, exist_ok=True)
    shutil.copy2(status_path, output / "status.json")
    shutil.copy2(index_path, output / "index.html")
    output_feeds = output / "feeds"
    output_feeds.mkdir(parents=True, exist_ok=True)
    for source in config.sources:
        for feed in source.feeds:
            source_path = config.root / feed.output
            if not source_path.exists():
                raise FileNotFoundError(f"missing required feed: {feed.output}")
            shutil.copy2(source_path, output / feed.output)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the GitHub Pages artifact")
    parser.add_argument("--config", type=Path, default=Path("sources.yml"))
    parser.add_argument("--output", type=Path, default=Path("_site"))
    args = parser.parse_args(argv)
    build_pages(args.config, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
