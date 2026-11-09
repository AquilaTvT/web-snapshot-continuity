"""Run the current-name generation probes against a local GCS JSON-API emulator.

The emulator is fake-gcs-server, not Google Cloud Storage. Its responses test
what the emulator implements; documented GCS semantics remain a separate source
of evidence. All exchanges are recorded completely on loopback.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import platform
import socket
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import ProxyHandler, Request, build_opener

LOCAL = build_opener(ProxyHandler({}))


def sha(data):
    return hashlib.sha256(data).hexdigest()


class Client:
    def __init__(self, port):
        self.base = f"http://127.0.0.1:{port}"
        self.records, self.origin = [], time.monotonic_ns()

    def request(self, method, path, *, query=None, body=b"", headers=None, label=""):
        url = self.base + path + ("?" + urlencode(query) if query else "")
        request = Request(url, data=body if method in ("POST", "PUT", "PATCH") else None,
                          headers=headers or {}, method=method)
        began = time.monotonic_ns() - self.origin
        try:
            response = LOCAL.open(request, timeout=30)
        except HTTPError as error:
            response = error
        with response:
            raw = response.read()
        record = {"index": len(self.records), "label": label,
                  "request": {"method": method, "url": url, "headers": dict(request.header_items()),
                              "body_base64": base64.b64encode(body).decode(), "body_sha256": sha(body)},
                  "response": {"status": response.status, "headers": dict(response.headers.items()),
                               "body_base64": base64.b64encode(raw).decode(), "body_sha256": sha(raw)},
                  "window_ns": [began, time.monotonic_ns() - self.origin]}
        self.records.append(record)
        return record


def header(record, name):
    return {k.lower(): v for k, v in record["response"]["headers"].items()}.get(name)


def payload(record):
    return base64.b64decode(record["response"]["body_base64"])


def upload(client, bucket, name, data, label):
    record = client.request("POST", f"/upload/storage/v1/b/{bucket}/o", query={"uploadType": "media", "name": name},
                            body=data, headers={"Content-Type": "text/plain"}, label=label)
    try:
        generation = json.loads(payload(record)).get("generation")
    except ValueError:
        generation = None
    return record, generation


def read(client, bucket, name, label, generation=None):
    query = {"alt": "media"}
    if generation:
        query["generation"] = generation
    record = client.request("GET", f"/storage/v1/b/{bucket}/o/{quote(name, safe='')}", query=query, label=label)
    meta = client.request("GET", f"/storage/v1/b/{bucket}/o/{quote(name, safe='')}",
                          query={"generation": generation} if generation else None, label=label + " (metadata)")
    try:
        described = json.loads(payload(meta)).get("generation") if meta["response"]["status"] == 200 else None
    except ValueError:
        described = None
    return {"index": record["index"], "metadata_index": meta["index"], "status": record["response"]["status"],
            "generation_header": header(record, "x-goog-generation"), "generation_metadata": described,
            "body": payload(record).decode("utf-8", "replace") if record["response"]["status"] == 200 else None,
            "body_sha256": record["response"]["body_sha256"]}


def probes(client):
    bucket = "probe-versioned"
    created = client.request("POST", "/storage/v1/b", query={"project": "probe"},
                             body=json.dumps({"name": bucket, "versioning": {"enabled": True}}).encode(),
                             headers={"Content-Type": "application/json"}, label="setup: create versioned bucket")
    cases = [{"name": "setup_versioned_bucket", "created": created["response"]["status"] == 200,
              "setup": [created["index"]]}]
    # Delete the live generation by number while an older generation is retained.
    k = "delete-current"
    a, g1 = upload(client, bucket, k, b"A\n", "delete_current: upload A")
    c1 = read(client, bucket, k, "delete_current: first capture")
    b, g2 = upload(client, bucket, k, b"B\n", "delete_current: upload B")
    mid = read(client, bucket, k, "delete_current: intermediate capture")
    d = client.request("DELETE", f"/storage/v1/b/{bucket}/o/{k}", query={"generation": g2},
                       label="delete_current: delete live generation B")
    c2 = read(client, bucket, k, "delete_current: last capture")
    cases.append({"name": "delete_current", "generations": [g1, g2], "mutation": d["index"],
                  "captures": [c1, mid, c2]})
    # Delete the live object without naming a generation.
    k = "delete-live"
    a, g1 = upload(client, bucket, k, b"A\n", "delete_live: upload A")
    c1 = read(client, bucket, k, "delete_live: first capture")
    d = client.request("DELETE", f"/storage/v1/b/{bucket}/o/{k}", label="delete_live: delete live object")
    c2 = read(client, bucket, k, "delete_live: capture after delete")
    cases.append({"name": "delete_live", "generations": [g1], "mutation": d["index"], "captures": [c1, c2]})
    # Restore old bytes by copying the noncurrent generation onto the live name.
    k = "copy-restore"
    a, g1 = upload(client, bucket, k, b"A\n", "copy_restore: upload A")
    c1 = read(client, bucket, k, "copy_restore: first capture")
    b, g2 = upload(client, bucket, k, b"B\n", "copy_restore: upload B")
    mid = read(client, bucket, k, "copy_restore: intermediate capture")
    cp = client.request("POST", f"/storage/v1/b/{bucket}/o/{k}/copyTo/b/{bucket}/o/{k}",
                        query={"sourceGeneration": g1}, body=b"{}", headers={"Content-Type": "application/json"},
                        label="copy_restore: copy generation A to the live name")
    c2 = read(client, bucket, k, "copy_restore: last capture")
    cases.append({"name": "copy_restore", "generations": [g1, g2], "mutation": cp["index"],
                  "captures": [c1, mid, c2]})
    # Upload the old bytes again.
    k = "reupload"
    a, g1 = upload(client, bucket, k, b"A\n", "reupload: upload A")
    c1 = read(client, bucket, k, "reupload: first capture")
    b, g2 = upload(client, bucket, k, b"B\n", "reupload: upload B")
    mid = read(client, bucket, k, "reupload: intermediate capture")
    a2, g3 = upload(client, bucket, k, b"A\n", "reupload: upload A again")
    c2 = read(client, bucket, k, "reupload: last capture")
    cases.append({"name": "reupload", "generations": [g1, g2, g3], "captures": [c1, mid, c2]})
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emulator", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("output exists; traces are never overwritten")
    with socket.socket() as stream:
        stream.bind(("127.0.0.1", 0))
        port = stream.getsockname()[1]
    binary = args.emulator.resolve()
    with tempfile.TemporaryDirectory(prefix="gcs-probe-") as directory:
        process = subprocess.Popen([str(binary), "-scheme", "http", "-host", "127.0.0.1", "-port", str(port),
                                    "-backend", "memory", "-filesystem-root", directory],
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            end = time.monotonic() + 30
            while True:
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=1):
                        break
                except OSError:
                    if time.monotonic() > end or process.poll() is not None:
                        raise RuntimeError("emulator did not start")
                    time.sleep(0.2)
            client = Client(port)
            started = datetime.now(timezone.utc).isoformat()
            cases = probes(client)
        finally:
            process.terminate()
            log = process.communicate(timeout=10)[0].decode("utf-8", "replace")
    trace = {"schema": 1, "server": "fake-gcs-server",
             "implementation": {"implementation": "fake-gcs-server (GCS JSON API emulator, memory backend)",
                                "distribution": "go install github.com/fsouza/fake-gcs-server@v1.56.1",
                                "version": "v1.56.1", "executable_sha256": sha(binary.read_bytes())},
             "started_utc": started, "finished_utc": datetime.now(timezone.utc).isoformat(),
             "client": {"python": platform.python_version(), "system": platform.system(), "machine": platform.machine()},
             "cases": cases, "requests": client.records, "server_log_tail": log[-4000:]}
    args.output.write_text(json.dumps(trace, indent=1) + "\n")
    print(json.dumps({"server": "fake-gcs-server", "requests": len(client.records)}))


if __name__ == "__main__":
    main()
