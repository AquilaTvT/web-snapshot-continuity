#!/usr/bin/env python3
"""Official SDK / simulated HTTP origin experiment; never connects to GCS.

Archive: python run.py --record
Replay experiment and check archived semantics: python run.py --verify
The server models current A -> B and retained version A. It does not test GCS.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import inspect
import json
import platform
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import requests
from google.auth.credentials import AnonymousCredentials
from google.cloud import storage

ROOT = Path(__file__).resolve().parent
VERSIONS = {"101": b"body A\n", "202": b"body B\n"}
CASES = ("reuse_blob", "fresh_blob", "explicit_generation_control")


def digest(data):
    return hashlib.sha256(data).hexdigest()


class LoopbackOnlySession(requests.Session):
    def __init__(self, endpoint):
        super().__init__()
        self.trust_env = False  # no environment proxies or netrc
        self.endpoint = endpoint

    def send(self, request, **kwargs):
        parsed = urlsplit(request.url)
        if f"{parsed.scheme}://{parsed.netloc}" != self.endpoint:
            raise RuntimeError(f"Refusing non-fixture endpoint: {request.url}")
        return super().send(request, **kwargs)


def experiment():
    state = {"generation": "101", "case": None, "step": None, "requests": []}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            parsed = urlsplit(self.path)
            query = parse_qs(parsed.query)
            expected_path = "/download/storage/v1/b/fixture-bucket/o/config.json"
            if parsed.path != expected_path or query.get("alt") != ["media"]:
                self.send_error(400, "Unexpected fixture request")
                return
            generation = query.get("generation", [state["generation"]])[0]
            if generation not in VERSIONS:
                self.send_error(404)
                return
            body = VERSIONS[generation]
            headers = {
                "Content-Type": "application/octet-stream",
                "Content-Length": str(len(body)),
                "Cache-Control": "no-store",
                "X-Goog-Generation": generation,
                "X-Goog-Metageneration": "1",
            }
            state["requests"].append({
                "case": state["case"], "step": state["step"],
                "current_generation": state["generation"],
                "method": "GET", "url": f"http://{self.headers['Host']}{self.path}",
                "raw_request_target": self.path,
                "request_headers": dict(self.headers.items()),
                "response_status": 200, "response_headers": headers,
                "response_body_utf8": body.decode(), "response_body_sha256": digest(body),
            })
            # No clock-dependent Date/Server response headers.
            self.send_response_only(200)
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    endpoint = f"http://127.0.0.1:{server.server_port}"
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    session = LoopbackOnlySession(endpoint)
    client = storage.Client(project="local-fixture-project", credentials=AnonymousCredentials(),
                            client_options={"api_endpoint": endpoint}, _http=session)
    results = []
    try:
        bucket = client.bucket("fixture-bucket")  # no remote request
        for case in CASES:
            state.update(generation="101", case=case)
            blob = bucket.blob("config.json", generation=101 if case == CASES[2] else None)
            observations = []
            for step in (1, 2):
                state["step"] = step
                if step == 2:
                    state["generation"] = "202"
                    if case == "fresh_blob":
                        blob = bucket.blob("config.json")
                before = blob.generation
                body = blob.download_as_bytes(raw_download=True, single_shot_download=True,
                                              checksum=None, retry=None, timeout=5)
                request = state["requests"][-1]
                observations.append({
                    "step": step, "current_generation": state["generation"],
                    "blob_generation_before": before,
                    "blob_generation_after": blob.generation,
                    "request_target": request["raw_request_target"],
                    "request_generation_selector": parse_qs(urlsplit(request["url"]).query).get("generation"),
                    "response_generation": request["response_headers"]["X-Goog-Generation"],
                    "body_utf8": body.decode(), "body_sha256": digest(body),
                })
            results.append({"case": case, "observations": observations})
    finally:
        client.close()
        session.close()
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)

    expected = {
        "reuse_blob": [(None, "101"), (["101"], "101")],
        "fresh_blob": [(None, "101"), (None, "202")],
        "explicit_generation_control": [(["101"], "101"), (["101"], "101")],
    }
    for case in results:
        actual = [(o["request_generation_selector"], o["response_generation"])
                  for o in case["observations"]]
        assert actual == expected[case["case"]], (case["case"], actual)
        for o in case["observations"]:
            assert o["blob_generation_after"] == int(o["response_generation"])
            assert o["body_utf8"].encode() == VERSIONS[o["response_generation"]]
    assert len(state["requests"]) == 6
    installed_source = Path(inspect.getsourcefile(storage.Blob))
    dependencies = dict(sorted((d.metadata["Name"], d.version)
                              for d in importlib.metadata.distributions()))
    summary = {
        "schema": "gcs-sdk-selector-fixture-v1",
        "scope": "Official Python SDK request construction against a simulated loopback origin; no GCS service test.",
        "sdk_version": importlib.metadata.version("google-cloud-storage"),
        "blob_py_sha256": digest(installed_source.read_bytes()),
        "cases": results,
    }
    capture = {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(), "platform": platform.platform(),
        "endpoint": endpoint, "dependencies": dependencies,
        "requests": state["requests"], "summary": summary,
    }
    return summary, capture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--record", action="store_true")
    mode.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    summary, capture = experiment()
    if args.record:
        for filename, payload in (("summary.json", summary), ("capture.json", capture)):
            (ROOT / filename).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        print("Recorded 3 cases / 6 local SDK GETs; no GCS service was contacted.")
    else:
        expected = json.loads((ROOT / "summary.json").read_text())
        assert summary == expected, "SDK semantics/source differs from archived summary"
        baseline = json.loads((ROOT / "capture.json").read_text())
        assert capture["dependencies"] == baseline["dependencies"], "Dependency versions differ"
        print("Verified exact 3-case semantic summary, SDK source hash and dependency versions.")
        print("Raw archived capture is preserved; ephemeral port, runtime and request IDs are not compared.")


if __name__ == "__main__":
    main()
