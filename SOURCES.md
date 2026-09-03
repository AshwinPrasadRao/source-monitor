# Source provenance ledger

Last manual audit: **2026-09-03**

This ledger is updated whenever retrieval, filtering, stable-ID, or backfill
behavior changes. Every source below fills a monitoring gap; none is intended to
replace a satisfactory native subscription.

## IN-SPACe

- **Last manually audited:** 2026-09-03.
- **Purpose:** announcements and operational updates from India's space regulator.
- **Official URLs:** <https://www.inspace.gov.in/> and <https://www.inspace.gov.in/inspace>.
- **Outputs:** `feeds/inspace-announcements.xml`, `feeds/inspace-updates.xml`.
- **Retrieval:** confirmed public ServiceNow page JSON. The public
  `api/now/sp/page?id=inspace_index` response exposes separate announcement and
  update widget datasets; Playwright is not justified.
- **Stable IDs:** ServiceNow attachment ID where present; otherwise a
  deterministic hash of stream, canonical link, date, and title/content. The
  hash is necessary because the live widgets reuse some internal page links for
  distinct records.
- **Filtering:** keep the two official widget streams separate; exclude the
  adjacent general “Space News” widget.
- **Initial backfill:** current Announcements widget (records are undated) and
  preceding 12 months of Updates, capped at 100 per feed.
- **Known quirks:** the bare domain redirects to `/inspace`; some records have no
  link and some widget links are relative.

## PIB — Department of Space

- **Last manually audited:** 2026-09-03.
- **Purpose:** isolate Department of Space releases from the Government-wide PIB feed.
- **Official URLs:** <https://www.pib.gov.in/ViewRss.aspx?lang=1&reg=1> and
  <https://pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=1>.
- **Output:** `feeds/pib-department-of-space.xml`.
- **Retrieval:** RSS filtering, with linked-release HTML classification only when
  the RSS lacks an explicit department field.
- **Stable ID:** PIB Release ID (`PRID`).
- **Filtering:** the explicit originating department must be “Department of
  Space”; subject keywords are never a substitute.
- **Initial backfill:** whatever the upstream RSS exposes on the first successful
  run, capped at 100.
- **Known quirks:** the upstream returned a valid but empty channel during the
  2026-09-03 audit. Its WAF rejects a User-Agent containing the project URL, so
  this adapter sends the shorter identifying token `OrrerySourceMonitor/0.1`.
  Unavailable release pages remain unclassified and are retried.

## DoT / WPC

- **Last manually audited:** 2026-09-03.
- **Purpose:** radio-frequency administration, satellite licensing and
  authorisation, assignments, coordination, and telecom-space convergence.
- **Official URLs:** <https://www.dot.gov.in/documents/gazettes-notifications>,
  <https://www.eservices.dot.gov.in/>,
  <https://www.eservices.dot.gov.in/circular-notifications-others>,
  <https://www.eservices.dot.gov.in/satellite-license>, and
  <https://www.eservices.dot.gov.in/resources>.
- **Output:** `feeds/dot-wpc-space.xml`.
- **Retrieval:** the public first-party DoT document JSON endpoint used by the
  client-rendered Gazette page, plus structured server-rendered eServices HTML
  tables and dated update/document lists.
- **Stable ID:** DoT document record ID; otherwise normalized official document
  URL.
- **Filtering:** prefer exposed WPC/Satellite service paths and categories, then
  use the transparent conservative vocabulary in `sources.yml`.
- **Initial backfill:** preceding 12 months, capped at 100.
- **Known quirks:** the same document can occur on several surfaces; generic
  service-page prose is not itself a feed item. The DoT edge rejected the
  project URL in the default User-Agent during the 2026-09-03 live test, while
  accepting the shorter identifying token `OrrerySourceMonitor/0.1`; the JSON
  request therefore uses that token and the official page as its Referer. The
  eServices host appears with and without `www`; both forms normalize to the
  same host before GUID deduplication.

## NSIL

- **Last manually audited:** 2026-09-03.
- **Purpose:** keep commercial news analytically separate from procurement signals.
- **Official URLs:** <https://www.nsilindia.co.in/news> and
  <https://www.nsilindia.co.in/tenders>.
- **Outputs:** `feeds/nsil-news.xml`, `feeds/nsil-procurement.xml`.
- **Retrieval:** paginated server-rendered HTML.
- **Stable IDs:** canonical news URL; tender ID, then tender reference or canonical URL.
- **Filtering:** no keyword filtering in v1; ingest every tender row.
- **Initial backfill:** preceding 12 months, capped at 100 per feed.
- **Known quirks:** tender descriptions embed CPPP IDs and may expose multiple
  documents, corrigenda, start/end dates, and status text in one row.

## ISRO institutional press releases

- **Last manually audited:** 2026-09-03.
- **Purpose:** monitor the dedicated institutional press-release archive rather
  than the generic homepage news stream.
- **Official URL:** <https://www.isro.gov.in/Press.html>.
- **Output:** `feeds/isro-press.xml`.
- **Retrieval:** server-rendered archive HTML.
- **Stable ID:** canonical release URL.
- **Filtering:** none in v1.
- **Initial backfill:** preceding 12 months, capped at 100.
- **Known quirks:** historical years use four observed date conventions, all
  covered by fixtures; no fuzzy date parser is used.

## iDEX / Defence Innovation Organisation

- **Last manually audited:** 2026-09-03.
- **Purpose:** challenge launches, problem statements, results, awards, notices,
  and test/evaluation or procurement signals.
- **Official URLs:** <https://idex.gov.in/notices> and <https://www.idex.gov.in/>.
- **Outputs:** `feeds/idex-notices.xml`, `feeds/idex-news.xml`.
- **Retrieval:** server-rendered notices/archive and homepage news records.
- **Stable IDs:** official PDF/detail/bulletin identifier, otherwise date/title hash.
- **Filtering:** no aggressive exclusions in v1.
- **Initial backfill:** preceding 12 months, capped at 100 per feed.
- **Known quirks:** the site advertises a broad newsletter, but it does not
  provide a verifiable complete, granular substitute for notices and challenge records.

## DRDO

- **Last manually audited:** 2026-09-03.
- **Purpose:** a selective foresight sensor for military technical requirements
  relevant to space power.
- **Official URLs:** <https://drdo.gov.in/drdo/documents/press-release>,
  <https://drdo.gov.in/drdo/en/documents/press-release/archive>, and
  <https://drdo.gov.in/drdo/en/archive>.
- **Output:** `feeds/drdo-space-tech.xml`.
- **Retrieval:** Drupal server-rendered current/archive HTML.
- **Stable ID:** canonical release or document URL.
- **Filtering:** transparent primary and contextual term groups in `sources.yml`;
  source tags/categories take precedence when useful.
- **Initial backfill:** preceding 12 months, capped at 100 matching records.
- **Known quirks:** DRDO offers generic updates, but they are too broad to replace
  the required selective feed. RF/EW and quantum terms require space/PNT context.

## Parliament Standing Committee — Department of Space

- **Last manually audited:** 2026-09-03.
- **Purpose:** Demands for Grants, Action Taken, implementation, and other reports
  explicitly pertaining to the Department of Space.
- **Official URLs:** <https://sansad.in/rs/pressRelease>,
  <https://sansad.in/rs/committees/committee-meetings>, and their public
  first-party Rajya Sabha committee integration APIs.
- **Output:** `feeds/parliament-space-committee.xml`.
- **Retrieval:** official Rajya Sabha JSON APIs used by the public pages. The
  target committee is master committee ID `19`.
- **Stable IDs:** committee report number or press-release ID.
- **Filtering:** explicit Department of Space text. A generic Action Taken press
  bundle is retained only when its publication date matches a selected
  Department of Space report; unrelated science/environment output is excluded.
- **Initial backfill:** preceding 24 months, capped at 100, so reports 391, 398,
  and 410 are represented.
- **Known quirks:** report and press-release PDF hosts vary, and legacy subjects
  contain multiply encoded HTML entities. The press endpoint is broad even when
  given `mstCommId=19`, so the adapter still enforces the returned committee ID;
  the query form was materially more responsive during the 2026-09-03 audit.

## FCC ICFS — satellite filings

- **Last manually audited:** 2026-09-03.
- **Purpose:** raw Satellite Space Station filings before they become newsworthy.
- **Official URL:** <https://fccprod.servicenowservices.com/icfs>.
- **Output:** `feeds/fcc-icfs-satellite-filings.xml`.
- **Retrieval:** the public ServiceNow `IBFS Public Data Table` widget request
  used by the ICFS portal. A normal guest page load supplies the session token
  and portal ID; the public widget is then queried server-side for subsystem
  `SAT` and the configured filing types. Static portal HTML, page JSON, and the
  widget request were inspected on 2026-09-03. A temporary Chromium inspection
  was attempted but the local sandbox could not launch AppKit; it is not needed
  by the adapter because the public HTTP request was reproduced directly.
- **Stable ID:** official file number, with ServiceNow record ID retained as metadata.
- **Filtering:** Satellite Space Stations only; configured filing-class allowlist;
  exclude grants/actions and STAs in v1.
- **Initial backfill:** latest 100 matching filings. Each later run requests the
  same bounded latest-100 window so persistent state can retain records that
  fall out of view without relying on fragile relative-date syntax.
- **Known quirks:** this is the post-2025 cloud ICFS, not legacy IBFS; no private
  API, authentication bypass, CAPTCHA handling, or anti-bot evasion is permitted.
