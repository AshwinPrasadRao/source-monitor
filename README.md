# The Orrery Source Monitor

The Orrery Source Monitor converts a deliberately small set of difficult
official publication surfaces into persistent RSS 2.0 feeds for Readwise
Reader. It is a gap-filler: native RSS/Atom, first-party email, precise Google
News RSS, GovInfo, EDGAR, and naturally annual checks remain outside this
project.

## Status

Eleven source-level feeds are active. DoT/WPC was retired on 2026-09-23
after persistent HTTP 403 responses from its eServices pages on GitHub runners.
Its adapter and saved records remain available for historical reference. The live local
audit on 2026-09-03 completed twice; the second pass created zero new or updated
items. PIB requests explicitly select region 1 to avoid redirects to an empty
regional feed. A populated PIB feed with no Department of Space releases is
valid; an upstream feed that becomes empty after containing records remains a failure.

The generated [status page](site/index.html) and `status.json` record retrieval
mode, upstream links, last successful check, last new item time, retained count,
and health for every feed.

## Feeds

Once GitHub Pages is enabled for this repository, the subscriptions are:

- `https://ashwinprasadrao.github.io/source-monitor/feeds/inspace-announcements.xml`
- `https://ashwinprasadrao.github.io/source-monitor/feeds/inspace-updates.xml`
- `https://ashwinprasadrao.github.io/source-monitor/feeds/pib-department-of-space.xml`
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
and feeds survive, other adapters continue, and the runner exits with a
failure. Actions applies the notification policy below. No database, credentials,
LLM classification, Docker image, or
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

`requirements.txt` applies the reviewed runtime/test versions in
`requirements.lock`; all Actions workflows use those constraints too. To refresh
them, install `-e '.[test]'` in a clean Python 3.12 environment, capture
`python -m pip freeze --exclude orrery-source-monitor`, and review the changes to
`requirements.lock`. Run the offline suite and a live `--all --dry-run` before
adopting an update. The lock covers Python runtime/test packages; the runner OS
and its CA updates remain managed by GitHub.

HTTPS uses the operating system's certificate store through `truststore`, with
certificate and hostname verification required. Linux needs its standard
`ca-certificates` package (provided by GitHub's Ubuntu runners). Connection/read
timeouts, server disconnects, rate limiting, and selected server errors receive
up to three attempts. Retry logs include the URL and delay; exhausted network
errors include the URL in the source health report. Certificate verification
failures are reported immediately.

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
adapters, validates retained feeds, creates a Pages artifact, and commits
generated state/feed/status changes as `Update monitored sources`. A broken
adapter does not prevent the preserved feeds and failed health status from being
deployed. The first upstream failure for a source fails the workflow, triggering
the existing GitHub failure notification. Continuing outages generate at most
one reminder per source every 24 hours, on the first run after the reminder is
due. Recovery clears that source's outage, so a later failure alerts immediately.
Parser, safety-check, unclassified, test, validation, and deployment failures
always fail the workflow.

Between reminders, a successful workflow means publication completed without a
new alert; it does not mean every source is healthy. Failed sources retain their
failed status and previous successful-check timestamp on the public status page,
and appear as warnings in Actions. Every scheduled run still attempts every
enabled source with the normal bounded retries.

Notification history is committed in `state/alerts.json`. It changes only when
an outage begins, a reminder is due, or a source recovers/is disabled. The report
step checks that every enabled source has exactly one result and that those
results agree with the runner's exit status. Missing results or corrupt alert
state fail the workflow rather than suppressing notifications. The standalone
runner remains strict and exits nonzero whenever any source fails.

The run summary lists each source's health and the failing URLs and errors;
it is generated from that run's results. Code and configuration changes also
run offline regression tests on pull requests and pushes to `main` through
`.github/workflows/checks.yml`.

The 2026-10-19 repair addresses two observed causes: the Parliament API's CA was
[removed from certifi on 2026-10-18](https://github.com/certifi/python-certifi/pull/437),
and DRDO disconnected with a protocol error outside the former retry handler.
The client now follows native OS trust policy, and retries interrupted HTTP
responses. Existing feed retention and failure reporting still apply to real
upstream outages, including the iDEX connection timeouts observed on 2026-10-15.

On 2026-10-22, six consecutive runs showed DRDO connection timeouts after all
three retries. Current and archive endpoints on both bare and `www` hosts also
timed out in independent local probes. The notification policy above avoids
repeated mail for a continuing outage while preserving its failed health status.
Initial notification history records the first failed run
[39502292562](https://github.com/AshwinPrasadRao/source-monitor/actions/runs/39502292562)
and the latest already-issued alert from
[39725102853](https://github.com/AshwinPrasadRao/source-monitor/actions/runs/39725102853).

For DoT access failures, manually run **Diagnose DoT access** in Actions (or
`python -m orrery_monitor.diagnose_dot` locally). It compares the public endpoint
responses, Referer headers, and HTTP clients on standard Linux and macOS
runners. Logs include bounded error text and response fingerprints; the probes
do not change feeds or state. This separates request-format failures from
runner-dependent failures before changing production retrieval.
A successful diagnostic job means its probes completed; inspect the recorded
HTTP statuses for source availability. DoT/WPC is disabled in the production monitor.

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
   then add each of the eleven public URLs above to Readwise Reader.

The workflow uses only public official data and repository-provided GitHub
permissions. The detailed provenance and maintenance rationale for every source
is in [SOURCES.md](SOURCES.md).
