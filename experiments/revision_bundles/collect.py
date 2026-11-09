"""Freeze public revision metadata for the protocol in protocol.json.

Network collection is separate from the offline derivation. Only revision IDs,
parent IDs, timestamps, SHA-1 values and sizes are requested; no user names,
edit comments or page text. Every raw API response is stored unchanged with
its URL and SHA-256. The output directory must not exist.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
API = "https://en.wikipedia.org/w/api.php"
FRAME_PAGE = "Wikipedia:Vital articles/Level 3"
SPACING = 2.0


class Session:
    def __init__(self, output: Path, user_agent: str, replay: bool = False):
        self.output, self.user_agent = output, user_agent
        self.records, self.last = [], 0.0
        self.context = ssl.create_default_context()
        # Resume: saved responses are replayed through the same request code, so
        # URLs and continuation tokens are rebuilt exactly; live requests follow.
        self.saved = sorted((output / "raw").glob("*.json")) if replay else []
        self.replayed = 0

    def get(self, params: dict, stem: str) -> dict:
        params = dict(params, format="json", formatversion="2", maxlag="5")
        url = API + "?" + urllib.parse.urlencode(params)
        number = len(self.records)
        if number < len(self.saved):
            path = self.saved[number]
            if path.name != f"{number:05d}-{stem}.json":
                raise RuntimeError(f"replay diverged at {path.name}, expected {stem}")
            raw = path.read_bytes()
            stamp = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
            self.records.append({"file": "raw/" + path.name, "url": url,
                                 "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
                                 "retrieved_utc": stamp, "retrieved_utc_source": "file modification time"})
            self.replayed += 1
            return json.loads(raw)
        for attempt in range(8):
            wait = self.last + SPACING - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self.last = time.monotonic()
            request = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
            try:
                with urllib.request.urlopen(request, context=self.context, timeout=60) as response:
                    raw = response.read()
            except urllib.error.HTTPError as error:
                if error.code not in (429, 500, 502, 503, 504) or attempt == 7:
                    raise
                retry = error.headers.get("Retry-After", "")
                delay = min(120, int(retry)) if retry.isdigit() else 15 * (attempt + 1)
                print("HTTP", error.code, "retry in", delay, flush=True)
                time.sleep(delay)
                continue
            except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
                if attempt == 7:
                    raise
                print("network error", error, flush=True)
                time.sleep(15 * (attempt + 1))
                continue
            payload = json.loads(raw)
            if payload.get("error", {}).get("code") == "maxlag":
                time.sleep(10 * (attempt + 1))
                continue
            if "error" in payload:
                raise RuntimeError(payload["error"])
            name = f"{len(self.records):05d}-{stem}.json"
            (self.output / "raw" / name).write_bytes(raw)
            self.records.append({"file": "raw/" + name, "url": url,
                                 "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
                                 "retrieved_utc": datetime.now(timezone.utc).isoformat()})
            return payload
        raise RuntimeError("request did not succeed: " + url)


def continued(session: Session, params: dict, stem: str):
    seen = set()
    while True:
        payload = session.get(params, stem)
        yield payload
        token = payload.get("continue")
        if not token:
            return
        key = json.dumps(token, sort_keys=True)
        if key in seen:
            raise RuntimeError("repeated continuation")
        seen.add(key)
        params = dict(params, **token)


def vital_frame(session: Session):
    titles, revision = set(), None
    params = {"action": "query", "titles": FRAME_PAGE, "prop": "links|revisions",
              "rvprop": "ids|timestamp|sha1|size", "plnamespace": "0", "pllimit": "max"}
    for payload in continued(session, params, "frame-vital"):
        page = payload["query"]["pages"][0]
        revision = page.get("revisions", [revision])[0] if page.get("revisions") else revision
        titles.update(link["title"] for link in page.get("links", []))
    return sorted(titles), revision


def random_frame(session: Session, size: int):
    pages = {}
    while len(pages) < size:
        payload = session.get({"action": "query", "list": "random", "rnnamespace": "0",
                               "rnfilterredir": "nonredirects", "rnlimit": "50"}, "frame-random")
        for page in payload["query"]["random"]:
            if len(pages) < size:
                pages.setdefault(page["id"], page["title"])
    return [{"pageid": pageid, "title": title} for pageid, title in pages.items()]


def history(session: Session, selector: dict, stem: str, window):
    params = {"action": "query", "prop": "revisions", "redirects": "1", "rvprop": "ids|timestamp|sha1|size",
              "rvlimit": "max", "rvdir": "newer", "rvstart": window[0], "rvend": window[1], **selector}
    identity, revisions = None, []
    for payload in continued(session, params, stem):
        pages = payload["query"]["pages"]
        if len(pages) != 1:
            raise RuntimeError("expected one page")
        page = pages[0]
        if "missing" in page or "invalid" in page:
            return {"missing": True, "selector": selector}
        current = (page["pageid"], page["title"])
        if identity not in (None, current):
            raise RuntimeError("page identity changed during continuation")
        identity = current
        revisions.extend(page.get("revisions", []))
    return {"selector": selector, "pageid": identity[0], "title": identity[1], "revisions": revisions}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--user-agent", required=True)
    parser.add_argument("--resume", action="store_true",
                        help="continue an interrupted run in --output; saved responses are replayed, never refetched")
    args = parser.parse_args()
    protocol = json.loads((HERE / "protocol.json").read_text())
    if args.resume:
        if (args.output / "collection.json").exists() or not (args.output / "raw").is_dir():
            raise SystemExit("--resume needs an interrupted run: raw/ present and no collection.json")
    elif args.output.exists():
        raise SystemExit("output exists; frozen evidence is never overwritten")
    else:
        (args.output / "raw").mkdir(parents=True)
    session = Session(args.output, args.user_agent, replay=args.resume)
    window = protocol["window"]
    started = datetime.now(timezone.utc).isoformat()
    if args.resume and session.saved:
        started = datetime.fromtimestamp(session.saved[0].stat().st_mtime, timezone.utc).isoformat()
    resumed_at = datetime.now(timezone.utc).isoformat() if args.resume else None
    frame, frame_revision = vital_frame(session)
    size = protocol["strata"]["vital"]["sample_size"]
    vital = random.Random(20261105).sample(frame, size)
    randoms = random_frame(session, protocol["strata"]["random"]["sample_size"])
    pages = [("vital", {"titles": title}) for title in vital]
    pages += [("random", {"pageids": str(page["pageid"])}) for page in randoms]
    histories = []
    for number, (stratum, selector) in enumerate(pages):
        record = history(session, selector, f"history-{number:03d}", window)
        record["stratum"] = stratum
        histories.append(record)
        print(number, stratum, record.get("title"), len(record.get("revisions", [])), flush=True)
    # Predecessors of the first in-window revision are fetched by revision ID.
    parents = sorted({r["revisions"][0]["parentid"] for r in histories
                      if r.get("revisions") and r["revisions"][0]["parentid"]})
    predecessors = {}
    for start in range(0, len(parents), 50):
        batch = parents[start:start + 50]
        payload = session.get({"action": "query", "prop": "revisions", "revids": "|".join(map(str, batch)),
                               "rvprop": "ids|timestamp|sha1|size"}, f"parents-{start // 50:03d}")
        for page in payload["query"]["pages"]:
            for revision in page.get("revisions", []):
                predecessors[revision["revid"]] = {"pageid": page["pageid"], **revision}
    # Pages without in-window revisions need the revision current at window start.
    for number, record in enumerate(histories):
        if record.get("missing") or record["revisions"]:
            continue
        payload = session.get({"action": "query", "prop": "revisions", "pageids": str(record["pageid"]),
                               "rvprop": "ids|timestamp|sha1|size", "rvlimit": "1", "rvdir": "older",
                               "rvstart": window[0]}, f"before-{number:03d}")
        found = payload["query"]["pages"][0].get("revisions", [])
        record["before_window"] = found[0] if found else None
    manifest = {"schema": 1, "protocol_sha256": hashlib.sha256((HERE / "protocol.json").read_bytes()).hexdigest(),
                "api": API, "user_agent": args.user_agent, "started_utc": started,
                "finished_utc": datetime.now(timezone.utc).isoformat(),
                "frame": {"page": FRAME_PAGE, "page_revision": frame_revision, "titles": frame,
                          "vital_sample": vital, "random_sample": randoms},
                "histories": histories, "predecessors": {str(k): v for k, v in sorted(predecessors.items())},
                "responses": session.records}
    if args.resume:
        manifest["interruption"] = {
            "resumed_utc": resumed_at, "replayed_responses": session.replayed,
            "live_responses_after_resume": len(session.records) - session.replayed,
            "note": ("The first run stopped when its worker process was restarted. Saved responses were replayed "
                     "through the same request code to rebuild URLs and continuation tokens; their retrieval "
                     "times are file modification times. Frames, samples and parameters are unchanged.")}
    (args.output / "collection.json").write_text(json.dumps(manifest, indent=1) + "\n")
    print("requests", len(session.records), flush=True)


if __name__ == "__main__":
    main()
