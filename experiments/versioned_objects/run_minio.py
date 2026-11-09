"""Execute version-selection histories against a pinned, unmodified MinIO server.

Only a new temporary store and loopback listeners are used. All S3 requests are
signed with public fixture credentials; no cloud SDK, account, or emulator is
involved. The official server executable is supplied by the caller.
"""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import platform
import socket
import subprocess
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import ProxyHandler, Request, build_opener

ACCESS = "continuity-local-fixture"
SECRET = "continuity-local-fixture-secret-not-a-cloud-key"
REGION = "us-east-1"
BUCKET = "continuity-history"
LOCAL_HTTP = build_opener(ProxyHandler({}))
RELEASE = "RELEASE.2025-09-07T16-13-09Z"
HASHES = {
    ("Darwin", "arm64"): "7c3b3039b76e55a1b80935848ed83998d5e8d317374f87851f46a019ff5c0aa4",
    ("Darwin", "x86_64"): "4759080aeef7385aaceaac1131c30aaeb99605921553967dc6d3ef4e16ac64f9",
    ("Linux", "aarch64"): "5c83cd2cf151717ba0243f73e1c7802ff36e272b67144bdd7f1f7d684fd6f03d",
    ("Linux", "x86_64"): "7c5bd8512c6e966455b1d198209358b2d191c77a83ab377c4073281065fb855f",
}


def sha(value):
    return hashlib.sha256(value).hexdigest()


def port():
    with socket.socket() as stream:
        stream.bind(("127.0.0.1", 0))
        return stream.getsockname()[1]


class Client:
    def __init__(self, number, *, access=ACCESS, secret=SECRET, bucket=BUCKET,
                 records=None, start=None):
        self.host = f"127.0.0.1:{number}"
        self.access, self.secret, self.bucket = access, secret, bucket
        self.records = [] if records is None else records
        self.start = time.monotonic_ns() if start is None else start

    def request(self, method, path, *, query=None, body=b"", headers=None, label=""):
        query_string = urlencode(sorted((query or {}).items()), quote_via=quote, safe="~")
        path = quote(path, safe="/~")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        fields = {"host": self.host, "x-amz-date": stamp, "x-amz-content-sha256": sha(body)}
        fields.update({key.lower(): value for key, value in (headers or {}).items()})
        signed = ";".join(sorted(fields))
        canonical = "\n".join((method, path, query_string,
            "".join(key + ":" + fields[key].strip() + "\n" for key in sorted(fields)), signed, sha(body)))
        scope = f"{stamp[:8]}/{REGION}/s3/aws4_request"
        key = ("AWS4" + self.secret).encode()
        for value in (stamp[:8], REGION, "s3", "aws4_request"):
            key = hmac.new(key, value.encode(), hashlib.sha256).digest()
        to_sign = f"AWS4-HMAC-SHA256\n{stamp}\n{scope}\n{sha(canonical.encode())}"
        signature = hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()
        fields["authorization"] = f"AWS4-HMAC-SHA256 Credential={self.access}/{scope}, SignedHeaders={signed}, Signature={signature}"
        url = "http://" + self.host + path + ("?" + query_string if query_string else "")
        request = Request(url, data=body if method in ("PUT", "POST") else None, headers=fields, method=method)
        began = time.monotonic_ns() - self.start
        try:
            response = LOCAL_HTTP.open(request, timeout=10)
        except HTTPError as error:
            response = error
        with response:
            raw = response.read()
            result = {"index": len(self.records), "label": label,
                "request": {"method": method, "url": url, "headers": dict(request.header_items()),
                            "body_base64": base64.b64encode(body).decode(), "body_sha256": sha(body)},
                "response": {"status": response.status, "headers": dict(response.headers.items()),
                             "body_base64": base64.b64encode(raw).decode(), "body_sha256": sha(raw)},
                "read_window_ns": [began, time.monotonic_ns() - self.start]}
        self.records.append(result)
        return result

    def object(self, method, key, **kwargs):
        return self.request(method, f"/{self.bucket}/{key}", **kwargs)

    def put(self, key, body, label):
        result = self.object("PUT", key, body=body, headers={"content-type": "text/plain", "cache-control": "no-store"}, label=label)
        assert result["response"]["status"] == 200, result
        return header(result, "x-amz-version-id")


def header(record, name):
    return {key.lower(): value for key, value in record["response"]["headers"].items()}.get(name)


def read_body(record):
    return base64.b64decode(record["response"]["body_base64"])


def scenarios(client):
    cases = []
    for name, operation in (("delete_current", "delete_version"),
                            ("copy_restore", "copy"), ("reupload_restore", "put")):
        first_id = client.put(name, b"A\n", name + ": put A")
        first = client.object("GET", name, label=name + ": first current capture")
        second_id = client.put(name, b"B\n", name + ": put B")
        middle = client.object("GET", name, label=name + ": intermediate current")
        assert first_id != second_id and read_body(first) == b"A\n" and read_body(middle) == b"B\n"
        if operation == "delete_version":
            mutation = client.object("DELETE", name, query={"versionId": second_id}, label=name + ": delete B by version")
            assert mutation["response"]["status"] == 204
        elif operation == "copy":
            mutation = client.object("PUT", name, headers={"x-amz-copy-source": f"/{BUCKET}/{name}?versionId={quote(first_id, safe='')}"}, label=name + ": copy A as current")
            assert mutation["response"]["status"] == 200, mutation
        else:
            client.put(name, b"A\n", name + ": upload A as new version")
        last = client.object("GET", name, label=name + ": last current capture")
        assert read_body(last) == b"A\n"
        repeated = header(first, "x-amz-version-id") == header(last, "x-amz-version-id")
        assert repeated == (operation == "delete_version")
        cases.append({"name": name, "captures": [first["index"], middle["index"], last["index"]],
                      "expected_version_id_repeats": operation == "delete_version"})

    name = "delete_marker"
    first_id = client.put(name, b"A\n", name + ": put A")
    first = client.object("GET", name, label=name + ": first current capture")
    mutation = client.object("DELETE", name, label=name + ": create delete marker")
    marker_id = header(mutation, "x-amz-version-id")
    assert mutation["response"]["status"] == 204 and marker_id != first_id
    middle = client.object("GET", name, label=name + ": current absence")
    assert middle["response"]["status"] == 404 and header(middle, "x-amz-delete-marker") == "true"
    restored = client.object("DELETE", name, query={"versionId": marker_id}, label=name + ": delete marker by version")
    assert restored["response"]["status"] == 204
    last = client.object("GET", name, label=name + ": last current capture")
    assert read_body(last) == b"A\n" and header(last, "x-amz-version-id") == first_id
    cases.append({"name": name, "captures": [first["index"], middle["index"], last["index"]],
                  "expected_version_id_repeats": True, "absence_is_non_target_state": True})

    name = "pinned_selector"
    first_id = client.put(name, b"A\n", name + ": put A")
    first = client.object("GET", name, query={"versionId": first_id}, label=name + ": pinned capture before overwrite")
    client.put(name, b"B\n", name + ": put B")
    current = client.object("GET", name, label=name + ": actual current head")
    last = client.object("GET", name, query={"versionId": first_id}, label=name + ": pinned capture after overwrite")
    assert read_body(first) == read_body(last) == b"A\n" and read_body(current) == b"B\n"
    cases.append({"name": name, "captures": [first["index"], current["index"], last["index"]],
                  "resource_context": "pinned version differs from unqualified current key"})

    admission, fee = "bundle-admission", "bundle-fee"
    client.put(admission, b"eligible\n", "bundle: initial admission")
    client.put(fee, b"100\n", "bundle: initial fee")
    phases = []
    def phase(label):
        a = client.object("GET", admission, label="ground truth: " + label + " admission")
        b = client.object("GET", fee, label="ground truth: " + label + " fee")
        phases.append({"label": label, "observations": [a["index"], b["index"]]})
        assert (read_body(a), read_body(b)) != (b"eligible\n", b"10\n")
    phase("initial")
    a1 = client.object("GET", admission, label="bundle: capture A1")
    new_a = client.put(admission, b"ineligible\n", "bundle: change admission first")
    phase("admission changed")
    new_b = client.put(fee, b"10\n", "bundle: change fee second")
    phase("both changed")
    b1 = client.object("GET", fee, label="bundle: capture B1")
    b2 = client.object("GET", fee, label="bundle: capture B2")
    restore_b = client.object("DELETE", fee, query={"versionId": new_b}, label="bundle: restore fee first")
    assert restore_b["response"]["status"] == 204
    phase("fee restored")
    restore_a = client.object("DELETE", admission, query={"versionId": new_a}, label="bundle: restore admission second")
    assert restore_a["response"]["status"] == 204
    phase("both restored")
    a2 = client.object("GET", admission, label="bundle: capture A2")
    assert read_body(a1) == read_body(a2) == b"eligible\n"
    assert read_body(b1) == read_body(b2) == b"10\n"
    assert header(a1,"x-amz-version-id") == header(a2,"x-amz-version-id")
    assert header(b1,"x-amz-version-id") == header(b2,"x-amz-version-id")
    cases.append({"name": "two_object_bundle", "captures": [a1["index"], b1["index"], b2["index"], a2["index"]],
                  "phases": phases, "target": ["eligible\n", "10\n"],
                  "ground_truth_scope": "single writer, serialized acknowledged writes; every stable pair read back; target absent in all five phases"})
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minio", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    binary = args.minio.resolve()
    expected = HASHES[platform.system(), platform.machine()]
    actual = sha(binary.read_bytes())
    assert actual == expected, "server executable differs from pinned official release"
    version = subprocess.check_output([str(binary), "--version"], text=True)
    assert RELEASE in version
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="continuity-versioned-objects-") as directory:
        temporary = Path(directory)
        api_port, console_port = port(), port()
        while console_port == api_port:
            console_port = port()
        env = dict(os.environ)
        env.update(MINIO_ROOT_USER=ACCESS, MINIO_ROOT_PASSWORD=SECRET, MINIO_BROWSER="off",
                   MINIO_UPDATE="off", MINIO_REGION_NAME=REGION)
        command = [str(binary), "--config-dir", str(temporary / "config"), "--certs-dir", str(temporary / "certs"),
                   "server", "--quiet", "--address", f"127.0.0.1:{api_port}",
                   "--console-address", f"127.0.0.1:{console_port}", str(temporary / "store")]
        with (args.output / "server.log").open("w") as log:
            process = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                deadline = time.monotonic() + 20
                while True:
                    if process.poll() is not None:
                        raise RuntimeError("MinIO exited before readiness; inspect server.log")
                    try:
                        with LOCAL_HTTP.open(f"http://127.0.0.1:{api_port}/minio/health/live", timeout=.5) as response:
                            if response.status == 200:
                                break
                    except (HTTPError, URLError, OSError):
                        pass
                    if time.monotonic() >= deadline:
                        raise TimeoutError("MinIO startup exceeded 20 seconds")
                    time.sleep(.05)
                client = Client(api_port)
                bucket = client.request("PUT", "/" + BUCKET, label="create isolated bucket")
                assert bucket["response"]["status"] == 200, bucket
                enabled = client.request("PUT", "/" + BUCKET, query={"versioning": ""},
                    body=b'<VersioningConfiguration xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><Status>Enabled</Status></VersioningConfiguration>',
                    headers={"content-type": "application/xml"}, label="enable versioning")
                assert enabled["response"]["status"] == 200, enabled
                cases = scenarios(client)
                result = {"format_version": 1, "server": version.strip(), "server_sha256": actual,
                    "platform": {"system": platform.system(), "machine": platform.machine(), "python": platform.python_version()},
                    "transport": "actual loopback HTTP and native persistent MinIO server; no cloud service measured",
                    "cases": cases, "requests": client.records, "status": "passed"}
                (args.output / "trace.json").write_text(json.dumps(result, indent=2) + "\n")
            finally:
                if process.poll() is None:
                    process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=5)
    print(json.dumps({"status": "passed", "cases": len(cases), "requests": len(client.records), "server_sha256": actual}))


if __name__ == "__main__":
    main()
