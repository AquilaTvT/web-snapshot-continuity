"""Freeze a small, explicitly purposive set of public revision histories.

Network collection is separate from the offline audit. No users, edit comments,
or private fields are requested. This is not a probability sample of the Web.
"""
import argparse
import hashlib
import json
import ssl
import sys
import time
import urllib.parse
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
API = "https://en.wikipedia.org/w/api.php"
TITLES = ("World Wide Web", "HTTP", "HTML", "CSS", "JavaScript", "Web browser")


def request(params, destination, user_agent):
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    cafile = "/etc/ssl/cert.pem" if Path("/etc/ssl/cert.pem").exists() else None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, context=ssl.create_default_context(cafile=cafile),
                                        timeout=45) as response:
                raw = response.read()
            break
        except urllib.error.HTTPError as exc:
            retry = exc.headers.get("Retry-After", "30")
            print("HTTP", exc.code, "Retry-After", retry, flush=True)
            if exc.code != 429 or attempt or not retry.isdigit() or int(retry) > 60:
                raise
            time.sleep(max(30, int(retry)))
    payload = json.loads(raw)
    if "error" in payload or "warnings" in payload:
        raise RuntimeError(payload.get("error", payload.get("warnings")))
    destination.write_bytes(raw)
    return payload, {"file": destination.name, "url": url,
                     "sha256": hashlib.sha256(raw).hexdigest(),
                     "bytes": len(raw)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True,
                        help="A new directory; existing data are never overwritten.")
    parser.add_argument("--user-agent", required=True,
                        help="Descriptive client name with operator contact, per Wikimedia policy.")
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Output directory exists; choose a new snapshot directory.")
    args.output.mkdir(parents=True)
    manifest = {
        "schema": 1, "api": API, "titles": list(TITLES),
        "window": ["2024-01-01T00:00:00Z", "2025-01-01T00:00:00Z"],
        "selection": "Six purposively selected Web-topic titles. World Wide Web was explored before this set was frozen; this is not preregistered or random.",
        "scope": "Public revision metadata and selected source-text witnesses, not rendered-page, deployment, or cache histories.",
        "started_utc": datetime.now(timezone.utc).isoformat(), "pages": [],
    }
    for number, title in enumerate(TITLES):
        params = {"action": "query", "prop": "revisions", "titles": title, "redirects": "1",
                  "rvprop": "ids|timestamp|sha1|size", "rvlimit": "500",
                  "rvdir": "newer", "rvstart": manifest["window"][0],
                  "rvend": manifest["window"][1], "formatversion": "2", "format": "json"}
        batches, revisions, page_identity = [], [], None
        seen_continuations = set()
        while True:
            payload, evidence = request(params, args.output / f"page-{number:02d}-{len(batches):03d}.json", args.user_agent)
            pages = payload.get("query", {}).get("pages", [])
            if len(pages) != 1 or "missing" in pages[0] or "revisions" not in pages[0]:
                raise RuntimeError(f"Unexpected page response for {title}")
            page = pages[0]
            identity = (page["pageid"], page["title"])
            if page_identity is not None and page_identity != identity:
                raise RuntimeError("Page identity changed during collection")
            page_identity = identity
            revisions.extend(page["revisions"])
            batches.append(evidence)
            continuation = payload.get("continue")
            if not continuation:
                break
            key = json.dumps(continuation, sort_keys=True)
            if key in seen_continuations:
                raise RuntimeError("Repeated API continuation")
            seen_continuations.add(key)
            params.update(continuation)
            time.sleep(2)
        manifest["pages"].append({"requested_title": title, "pageid": page_identity[0],
                                  "returned_title": page_identity[1], "batches": batches,
                                  "revision_count": len(revisions)})
        print(title, len(revisions), "revisions", flush=True)
        time.sleep(2)
    manifest["finished_utc"] = datetime.now(timezone.utc).isoformat()
    (args.output / "collection.json").write_text(json.dumps(manifest, indent=2) + "\n")
    # Use the same offline provenance validator before reporting a complete
    # snapshot. Rejected raw responses remain available for diagnosis.
    from scripts.run_revision_audit import load_pages
    load_pages(args.output)
    print("Validated frozen metadata snapshot", flush=True)


if __name__ == "__main__":
    main()
