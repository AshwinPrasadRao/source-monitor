"""Bounded, read-only probes for investigating DoT access from Actions."""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup

from orrery_monitor.sources.dot_wpc import DOT_API_URL, DOT_PAGE_URL, DOT_USER_AGENT, ESERVICES_URLS


def describe(response: httpx.Response) -> dict:
    soup = BeautifulSoup(response.text, "lxml")
    return {
        "url": str(response.url),
        "status": response.status_code,
        "headers": {
            key: response.headers[key]
            for key in ("server", "content-type", "via", "location")
            if key in response.headers
        },
        "bytes": len(response.content),
        "sha256": hashlib.sha256(response.content).hexdigest(),
        "title": soup.title.get_text(" ", strip=True) if soup.title else None,
        "error_text": soup.get_text(" ", strip=True)[:600] if response.is_error else None,
        "table_rows": len(soup.select("tbody tr")),
        "dated_cards": len(soup.select(".psn-container .policy-circular-presentation")),
    }


def main() -> None:
    print(json.dumps({"system": platform.system(), "machine": platform.machine()}), flush=True)
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        probes = [("monitor", url, DOT_PAGE_URL) for url in (DOT_API_URL, *ESERVICES_URLS)]
        resource = ESERVICES_URLS[-1]
        probes.extend([
            ("no-referer", resource, None),
            ("same-origin-referer", resource, f"https://{urlsplit(resource).netloc}/"),
            ("bare-host", resource.replace("www.eservices", "eservices"), None),
        ])
        for name, url, referer in probes:
            headers = {
                "User-Agent": DOT_USER_AGENT,
                "Accept": "application/json" if url == DOT_API_URL else "text/html",
            }
            if referer:
                headers["Referer"] = referer
            try:
                result = describe(client.get(url, headers=headers))
            except httpx.HTTPError as exc:
                result = {"url": url, "error": str(exc)}
            print(json.dumps({"probe": name, **result}), flush=True)

    # Compare HTTP clients with the same identifying headers and TLS validation.
    result = subprocess.run(
        [
            "curl", "--silent", "--show-error", "--location", "--max-time", "30",
            "--user-agent", DOT_USER_AGENT, "--header", "Accept: text/html",
            "--referer", DOT_PAGE_URL, "--write-out", "\n%{http_code}", resource,
        ],
        capture_output=True, text=True, check=False, timeout=40,
    )
    body, _, status = result.stdout.rpartition("\n")
    if result.returncode or not status.isdigit():
        detail = {"error": result.stderr[:600], "exit_code": result.returncode}
    else:
        detail = describe(httpx.Response(
            int(status), text=body, request=httpx.Request("GET", resource),
        ))
        # These headers belong to the synthetic response, not curl's server response.
        detail.pop("headers")
    print(json.dumps({"probe": "curl", **detail}), flush=True)


if __name__ == "__main__":
    main()
