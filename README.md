# The Orrery Source Monitor

The Orrery Source Monitor converts a deliberately small set of difficult
official publication surfaces into persistent RSS 2.0 feeds for Readwise
Reader. It is a gap-filler: native RSS/Atom, first-party email, precise Google
News RSS, GovInfo, EDGAR, and naturally annual checks remain outside this
project.

## Status

All v1 phases and all twelve source-level feeds are implemented. The live local
audit on 2026-09-03 completed twice; the second pass created zero new or updated
items. The official PIB RSS currently has an empty channel, so its valid output
is empty and marked `warning` until PIB publishes upstream entries.

The generated [status page](site/index.html) and `status.json` record retrieval
mode, upstream links, last successful check, last new item time, retained count,
and health for every feed.

## Feeds

Once GitHub Pages is enabled for this repository, the subscriptions are:

- `https://ashwinprasadrao.github.io/source-monitor/feeds/inspace-announcements.xml`
- `https://ashwinprasadrao.github.io/source-monitor/feeds/inspace-updates.xml`
- `https://ashwinprasadrao.github.io/source-monitor/feeds/pib-department-of-space.xml`
- `https://ashwinprasadrao.github.io/source-monitor/feeds/dot-wpc-space.xml`
- `https://ashwinprasadrao.github.io/source-monitor/feeds/nsil-news.xml`
- `https://ashwinprasadrao.github.io/source-monitor/feeds/nsil-procurement.xml`
- `https://ashwinprasadrao.github.io/source-monitor/feeds/isro-press.xml`
- `https://ashwinprasadrao.github.io/source-monitor/feeds/idex-notices.xml`
- `https://ashwinprasadrao.github.io/source-monitor/feeds/idex-news.xml`
- `https://ashwinprasadrao.github.io/source-monitor/feeds/drdo-space-tech.xml`
- `https://ashwinprasadrao.github.io/source-monitor/feeds/parliament-space-committee.xml`
- `https://ashwinprasadrao.github.io/source-monitor/feeds/fcc-icfs-satellite-filings.xml`

There is intentionally no aggregate feed.

## Architecture and safety

Each source adapter retrieves and normalizes its official records into the
common `FeedItem` model. The runner merges observations into versioned JSON
state, retains older records after they disappear upstream, and regenerates RSS
only when item content or feed configuration changes. Default retention is 300
items; initial source backfills are documented in [SOURCES.md](SOURCES.md).

State and RSS writes are atomic. Zero results after a populated observation,
large count collapses or explosions, excessive missing fields, retrieval
errors, and parser exceptions abort only the affected adapter. Existing state
and feeds survive, other adapters continue, and the overall run reports a
failure. No database, credentials, LLM classification, Docker image, or
production browser dependency is used.

## Local setup

Python 3.12 or newer is required.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
ruff check src tests
pytest -p no:cacheprovider
```

Run and validate the monitor with:

```sh
python -m orrery_monitor.runner --all
python -m orrery_monitor.runner --source isro
python -m orrery_monitor.runner --source isro --dry-run
python -m orrery_monitor.runner --validate-only
python -m orrery_monitor.site --output _site
```

`--dry-run` performs retrieval, parsing, safety checks, and merging without
writing state, feeds, or status. An explicit `--source` updates that adapter and
preserves the previous status entries for every source not selected.

## GitHub Actions and Pages

`.github/workflows/monitor.yml` runs at 00:17, 06:17, 12:17, and 18:17 UTC and
supports manual dispatch. It installs Python dependencies, runs tests and all
adapters, validates all twelve feeds, creates a Pages artifact, and commits
generated state/feed/status changes as `Update monitored sources`. A broken
adapter does not prevent the preserved feeds and failed health status from being
deployed, but the workflow ends failed so the problem remains visible.

For a repository with no item or health change, status is deployed from the
workflow artifact without a commit. At least every 28 days, the workflow commits
the current status as a low-noise heartbeat; this also mitigates scheduled
workflow inactivity in public repositories.

Deployment needs these one-time repository steps:

1. Push this project to `ashwinprasadrao/source-monitor` with the default branch
   containing the generated `feeds/`, `state/`, `status.json`, and workflow.
2. In **Settings → Pages**, select **GitHub Actions** as the build and deployment
   source. The ordinary `GITHUB_TOKEN` cannot enable Pages on a repository where
   it has never been enabled.
3. Run **Monitor official sources** manually once, confirm the Pages deployment,
   then add each of the twelve public URLs above to Readwise Reader.

The workflow uses only public official data and repository-provided GitHub
permissions. The detailed provenance and maintenance rationale for every source
is in [SOURCES.md](SOURCES.md).
