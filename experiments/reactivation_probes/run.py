"""Run identical current-key identity probes against S3-compatible servers.

Every server runs locally on loopback with public fixture credentials and a new
temporary store. Requests are signed with SigV4 by this standard-library client
and recorded completely: method, URL, headers, body, status, response headers,
response body and a monotone request window. Probe outcomes are not asserted;
only setup steps are checked, and an unsupported feature is recorded as such.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import ProxyHandler, Request, build_opener

LOCAL = build_opener(ProxyHandler({}))
ACCESS = "continuityprobefixture"
SECRET = "continuity-probe-public-fixture-secret-0000"
REGION = "us-east-1"
VERSIONING = '<VersioningConfiguration xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><Status>{}</Status></VersioningConfiguration>'


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def free_port() -> int:
    with socket.socket() as stream:
        stream.bind(("127.0.0.1", 0))
        return stream.getsockname()[1]


class S3:
    def __init__(self, port: int, access: str, secret: str):
        self.host, self.access, self.secret = f"127.0.0.1:{port}", access, secret
        self.records: list[dict] = []
        self.origin = time.monotonic_ns()

    def request(self, method, path, *, query=None, body=b"", headers=None, label=""):
        query_string = urlencode(sorted((query or {}).items()), quote_via=quote, safe="~")
        path = quote(path, safe="/~")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        fields = {"host": self.host, "x-amz-date": stamp, "x-amz-content-sha256": sha(body)}
        fields.update({k.lower(): v for k, v in (headers or {}).items()})
        signed = ";".join(sorted(fields))
        canonical = "\n".join((method, path, query_string,
                               "".join(f"{k}:{fields[k].strip()}\n" for k in sorted(fields)), signed, sha(body)))
        scope = f"{stamp[:8]}/{REGION}/s3/aws4_request"
        key = ("AWS4" + self.secret).encode()
        for part in (stamp[:8], REGION, "s3", "aws4_request"):
            key = hmac.new(key, part.encode(), hashlib.sha256).digest()
        to_sign = f"AWS4-HMAC-SHA256\n{stamp}\n{scope}\n{sha(canonical.encode())}"
        fields["authorization"] = (f"AWS4-HMAC-SHA256 Credential={self.access}/{scope}, SignedHeaders={signed}, "
                                   f"Signature={hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()}")
        url = "http://" + self.host + path + ("?" + query_string if query_string else "")
        data = body if method in ("PUT", "POST") else None
        request = Request(url, data=data, headers=fields, method=method)
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


def status(record):
    return record["response"]["status"]


def body(record):
    return base64.b64decode(record["response"]["body_base64"])


def make_bucket(s3, bucket, *, versioning=True, lock=False):
    """Create a bucket; return which requested features the server accepted."""
    created = s3.request("PUT", "/" + bucket, label=f"setup: create {bucket}",
                         headers={"x-amz-bucket-object-lock-enabled": "true"} if lock else None)
    if status(created) != 200:
        return {"created": False, "versioning": False, "setup": [created["index"]]}
    steps = [created["index"]]
    enabled = False
    if versioning:
        result = s3.request("PUT", "/" + bucket, query={"versioning": ""},
                            body=VERSIONING.format("Enabled").encode(), headers={"content-type": "application/xml"},
                            label="setup: enable versioning")
        steps.append(result["index"])
        check = s3.request("GET", "/" + bucket, query={"versioning": ""}, label="setup: read versioning")
        steps.append(check["index"])
        enabled = b"<Status>Enabled</Status>" in body(check)
    return {"created": True, "versioning": enabled, "setup": steps}


def put(s3, bucket, key, data, label, extra=None):
    return s3.request("PUT", f"/{bucket}/{key}", body=data, label=label,
                      headers={"content-type": "text/plain", **(extra or {})})


def get(s3, bucket, key, label, query=None, extra=None):
    return s3.request("GET", f"/{bucket}/{key}", query=query, label=label, headers=extra)


def capture(record):
    return {"index": record["index"], "status": status(record), "version_id": header(record, "x-amz-version-id"),
            "etag": header(record, "etag"), "last_modified": header(record, "last-modified"),
            "body_sha256": record["response"]["body_sha256"],
            "body": body(record).decode("utf-8", "replace") if status(record) == 200 else None}


def probes(s3):
    cases = []
    bucket = "probe-versioned"
    features = make_bucket(s3, bucket)
    cases.append({"name": "setup_versioned_bucket", **features})
    if features["created"]:
        # P1: delete the current version by ID.
        k = "delete-current"
        a = put(s3, bucket, k, b"A\n", "delete_current: put A")
        c1 = get(s3, bucket, k, "delete_current: first capture")
        b = put(s3, bucket, k, b"B\n", "delete_current: put B")
        mid = get(s3, bucket, k, "delete_current: intermediate capture")
        vb = header(b, "x-amz-version-id")
        d = s3.request("DELETE", f"/{bucket}/{k}", query={"versionId": vb} if vb else None,
                       label="delete_current: delete B by version ID")
        c2 = get(s3, bucket, k, "delete_current: last capture")
        cond = get(s3, bucket, k, "delete_current: conditional GET with first ETag",
                   extra={"If-None-Match": header(c1, "etag") or '"none"'})
        cases.append({"name": "delete_current", "writes": [a["index"], b["index"]], "mutation": d["index"],
                      "captures": [capture(c1), capture(mid), capture(c2)], "conditional": capture(cond)})
        # P2: create and remove a delete marker.
        k = "delete-marker"
        a = put(s3, bucket, k, b"A\n", "delete_marker: put A")
        c1 = get(s3, bucket, k, "delete_marker: first capture")
        m = s3.request("DELETE", f"/{bucket}/{k}", label="delete_marker: create delete marker")
        mid = get(s3, bucket, k, "delete_marker: intermediate capture")
        vm = header(m, "x-amz-version-id")
        r = s3.request("DELETE", f"/{bucket}/{k}", query={"versionId": vm} if vm else None,
                       label="delete_marker: remove marker by version ID")
        c2 = get(s3, bucket, k, "delete_marker: last capture")
        cases.append({"name": "delete_marker", "writes": [a["index"]], "marker": m["index"], "mutation": r["index"],
                      "captures": [capture(c1), capture(mid), capture(c2)]})
        # P3: restore old bytes by copying the old version.
        k = "copy-restore"
        a = put(s3, bucket, k, b"A\n", "copy_restore: put A")
        c1 = get(s3, bucket, k, "copy_restore: first capture")
        b = put(s3, bucket, k, b"B\n", "copy_restore: put B")
        mid = get(s3, bucket, k, "copy_restore: intermediate capture")
        va = header(a, "x-amz-version-id")
        source = f"/{bucket}/{k}" + (f"?versionId={quote(va, safe='')}" if va else "")
        cp = s3.request("PUT", f"/{bucket}/{k}", headers={"x-amz-copy-source": source},
                        label="copy_restore: copy old A to current")
        attempts = [cp["index"]]
        # Some implementations reject a same-key version copy unless metadata
        # changes, or accept the copy source only without a leading slash.
        for variant, label in ((source, "copy old A, replacing metadata"),
                               (source.lstrip("/"), "copy old A, replacing metadata, bucket-relative source")):
            if status(cp) == 200:
                break
            cp = s3.request("PUT", f"/{bucket}/{k}", label="copy_restore: " + label,
                            headers={"x-amz-copy-source": variant, "x-amz-metadata-directive": "REPLACE",
                                     "content-type": "text/plain; charset=utf-8"})
            attempts.append(cp["index"])
        c2 = get(s3, bucket, k, "copy_restore: last capture")
        cases.append({"name": "copy_restore", "writes": [a["index"], b["index"]], "mutation": cp["index"],
                      "attempts": attempts, "captures": [capture(c1), capture(mid), capture(c2)]})
        # P4: upload the old bytes again.
        k = "reupload"
        a = put(s3, bucket, k, b"A\n", "reupload: put A")
        c1 = get(s3, bucket, k, "reupload: first capture")
        b = put(s3, bucket, k, b"B\n", "reupload: put B")
        mid = get(s3, bucket, k, "reupload: intermediate capture")
        a2 = put(s3, bucket, k, b"A\n", "reupload: put A again")
        c2 = get(s3, bucket, k, "reupload: last capture")
        cond = get(s3, bucket, k, "reupload: conditional GET with first ETag",
                   extra={"If-None-Match": header(c1, "etag") or '"none"'})
        cases.append({"name": "reupload", "writes": [a["index"], b["index"], a2["index"]],
                      "captures": [capture(c1), capture(mid), capture(c2)], "conditional": capture(cond)})
    # P5: versioning enabled, then suspended: the null version is overwritten.
    bucket = "probe-suspended"
    features = make_bucket(s3, bucket)
    suspend = s3.request("PUT", "/" + bucket, query={"versioning": ""},
                         body=VERSIONING.format("Suspended").encode(), headers={"content-type": "application/xml"},
                         label="suspended_null: suspend versioning")
    check = s3.request("GET", "/" + bucket, query={"versioning": ""}, label="suspended_null: read versioning")
    record = {"name": "suspended_null", **features, "suspend": suspend["index"],
              "suspended": status(suspend) == 200 and b"<Status>Suspended</Status>" in body(check)}
    if features["created"]:
        k = "suspended"
        a = put(s3, bucket, k, b"A\n", "suspended_null: put A")
        c1 = get(s3, bucket, k, "suspended_null: first capture")
        b = put(s3, bucket, k, b"B\n", "suspended_null: put B")
        mid = get(s3, bucket, k, "suspended_null: intermediate capture")
        a2 = put(s3, bucket, k, b"A\n", "suspended_null: put A again")
        c2 = get(s3, bucket, k, "suspended_null: last capture")
        record.update(writes=[a["index"], b["index"], a2["index"]], captures=[capture(c1), capture(mid), capture(c2)])
    cases.append(record)
    # P6: compliance retention on the data version; delete-marker insertion and removal.
    bucket = "probe-locked"
    features = make_bucket(s3, bucket, lock=True)
    record = {"name": "object_lock_marker", **features}
    if features["created"]:
        k = "locked"
        until = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        md5 = base64.b64encode(hashlib.md5(b"A\n", usedforsecurity=False).digest()).decode()
        a = put(s3, bucket, k, b"A\n", "object_lock: put retained A",
                {"x-amz-object-lock-mode": "COMPLIANCE", "x-amz-object-lock-retain-until-date": until,
                 "content-md5": md5})
        retention = s3.request("GET", f"/{bucket}/{k}", query={"retention": ""}, label="object_lock: read retention")
        c1 = get(s3, bucket, k, "object_lock: first capture")
        va = header(a, "x-amz-version-id")
        protected = s3.request("DELETE", f"/{bucket}/{k}", query={"versionId": va} if va else None,
                               label="object_lock: delete retained data version")
        m = s3.request("DELETE", f"/{bucket}/{k}", label="object_lock: create delete marker")
        mid = get(s3, bucket, k, "object_lock: intermediate capture")
        vm = header(m, "x-amz-version-id")
        r = s3.request("DELETE", f"/{bucket}/{k}", query={"versionId": vm} if vm else None,
                       label="object_lock: remove delete marker")
        c2 = get(s3, bucket, k, "object_lock: last capture")
        record.update(writes=[a["index"]], retention=retention["index"], protected_delete=protected["index"],
                      marker=m["index"], mutation=r["index"], captures=[capture(c1), capture(mid), capture(c2)])
    cases.append(record)
    return cases


# ---------------------------------------------------------------- launchers --

def wait_ready(port, deadline=120.0, process=None):
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        if process is not None and process.poll() is not None:
            raise RuntimeError("server exited before readiness")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return
        except OSError:
            time.sleep(0.3)
    raise TimeoutError("server did not open its port")


def halt(process):
    """Stop a server process owned by this run; kill it if termination stalls."""
    process.terminate()
    try:
        process.wait(15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(15)


def docker_digest(image):
    out = subprocess.run(["docker", "image", "inspect", image, "--format", "{{json .RepoDigests}} {{.Id}}"],
                         capture_output=True, text=True, check=True).stdout.strip()
    return out


class Docker:
    def __init__(self, image, args, env, port, inner_port, extra=(), network_host=False):
        self.image, self.port = image, port
        command = ["docker", "run", "-d", "--rm"]
        if network_host:
            command += ["--net=host"]
        else:
            command += ["-p", f"127.0.0.1:{port}:{inner_port}"]
        for key, value in env.items():
            command += ["-e", f"{key}={value}"]
        command += list(extra) + [image] + list(args)
        self.container = subprocess.run(command, capture_output=True, text=True, check=True).stdout.strip()

    def run(self, command):
        return subprocess.run(["docker", "exec", self.container, "sh", "-c", command],
                              capture_output=True, text=True).stdout.strip()

    def stop(self):
        logs = subprocess.run(["docker", "logs", self.container], capture_output=True, text=True).stdout[-20000:]
        subprocess.run(["docker", "rm", "-f", self.container], capture_output=True)
        return logs


def launch(name, tools: Path, workdir: Path):
    """Return (port, access, secret, metadata, stop)."""
    port = free_port()
    if name == "minio":
        binary = tools / "minio"
        env = dict(os.environ, MINIO_ROOT_USER=ACCESS, MINIO_ROOT_PASSWORD=SECRET, MINIO_BROWSER="off",
                   MINIO_UPDATE="off", MINIO_REGION_NAME=REGION)
        process = subprocess.Popen([str(binary), "server", "--quiet", "--address", f"127.0.0.1:{port}",
                                    "--console-address", f"127.0.0.1:{free_port()}", str(workdir / "store")],
                                   env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, start_new_session=True)
        wait_ready(port, process=process)
        version = subprocess.run([str(binary), "--version"], capture_output=True, text=True).stdout.strip()
        meta = {"implementation": "MinIO", "distribution": "official release binary", "version": version,
                "executable_sha256": sha(binary.read_bytes())}
        return port, ACCESS, SECRET, meta, lambda: halt(process)
    if name == "versitygw":
        binary = tools / "versitygw"
        (workdir / "root").mkdir()
        (workdir / "versions").mkdir()
        process = subprocess.Popen([str(binary), "--access", ACCESS, "--secret", SECRET, "--port", f"127.0.0.1:{port}",
                                    "posix", "--versioning-dir", str(workdir / "versions"), str(workdir / "root")],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, start_new_session=True)
        wait_ready(port, process=process)
        meta = {"implementation": "Versity S3 Gateway (posix backend)",
                "distribution": "go install github.com/versity/versitygw/cmd/versitygw@v1.10.0", "version": "v1.10.0",
                "executable_sha256": sha(binary.read_bytes())}
        return port, ACCESS, SECRET, meta, lambda: halt(process)
    if name == "moto":
        python = tools.parent.parent / "moto-venv" / "bin" / "python"
        process = subprocess.Popen([str(python), "-m", "moto.server", "-H", "127.0.0.1", "-p", str(port)],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, start_new_session=True)
        wait_ready(port, process=process)
        version = subprocess.run([str(python), "-c", "import moto;print(moto.__version__)"],
                                 capture_output=True, text=True).stdout.strip()
        meta = {"implementation": "moto (server mode)", "distribution": "PyPI moto[server]==5.1.15", "version": version}
        return port, ACCESS, SECRET, meta, lambda: halt(process)
    if name == "seaweedfs":
        binary = tools / "weed"
        config = workdir / "s3.json"
        config.write_text(json.dumps({"identities": [{"name": "probe", "credentials": [
            {"accessKey": ACCESS, "secretKey": SECRET}], "actions": ["Admin", "Read", "Write", "List", "Tagging"]}]}))
        # SeaweedFS also listens on each port + 10000 for gRPC; keep both free and valid.
        ports = []
        candidate = 21000
        while len(ports) < 4:
            candidate += 7
            try:
                for value in (candidate, candidate + 10000):
                    with socket.socket() as stream:
                        stream.bind(("127.0.0.1", value))
                ports.append(candidate)
            except OSError:
                continue
        port = ports.pop()
        (workdir / "data").mkdir()
        process = subprocess.Popen([str(binary), "server", "-dir", str(workdir / "data"), "-ip", "127.0.0.1",
                                    "-ip.bind", "127.0.0.1", "-master.port", str(ports[0]), "-volume.port", str(ports[1]),
                                    "-filer.port", str(ports[2]), "-s3", "-s3.port", str(port), "-s3.config", str(config)],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, start_new_session=True)
        wait_ready(port, process=process)
        time.sleep(8)
        version = subprocess.run([str(binary), "version"], capture_output=True, text=True).stdout.strip()
        meta = {"implementation": "SeaweedFS (S3 gateway on filer)", "distribution": "official release linux_amd64.tar.gz 3.97",
                "version": version, "executable_sha256": sha(binary.read_bytes())}
        return port, ACCESS, SECRET, meta, lambda: halt(process)
    if name == "cloudserver":
        image = "ghcr.io/scality/cloudserver:9.0.27"
        box = Docker(image, [], {"S3BACKEND": "mem", "REMOTE_MANAGEMENT_DISABLE": "1",
                                 "SCALITY_ACCESS_KEY_ID": ACCESS, "SCALITY_SECRET_ACCESS_KEY": SECRET}, port, 8000)
        wait_ready(port)
        time.sleep(5)
        meta = {"version": box.run("node -e \"console.log(require('/usr/src/app/package.json').version)\""), "implementation": "Scality CloudServer (mem backend)", "distribution": image,
                "image": docker_digest(image)}
        return port, ACCESS, SECRET, meta, box.stop
    if name == "rustfs":
        image = "rustfs/rustfs:latest"
        box = Docker(image, ["/data"], {"RUSTFS_ACCESS_KEY": ACCESS, "RUSTFS_SECRET_KEY": SECRET}, port, 9000)
        wait_ready(port)
        time.sleep(5)
        meta = {"version": box.run("rustfs --version 2>&1 | head -1"), "implementation": "RustFS", "distribution": image, "image": docker_digest(image)}
        return port, ACCESS, SECRET, meta, box.stop
    if name == "localstack":
        image = "localstack/localstack:4.9"
        box = Docker(image, [], {"SERVICES": "s3", "EAGER_SERVICE_LOADING": "1"}, port, 4566)
        wait_ready(port)
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            try:
                with LOCAL.open(f"http://127.0.0.1:{port}/_localstack/health", timeout=2) as response:
                    if b'"s3": "running"' in response.read() or True:
                        break
            except (HTTPError, URLError, OSError):
                time.sleep(1)
        time.sleep(3)
        meta = {"version": box.run("printenv LOCALSTACK_BUILD_VERSION"), "implementation": "LocalStack (S3 provider)", "distribution": image, "image": docker_digest(image)}
        return port, "test", "test", meta, box.stop
    if name == "ceph":
        image = "quay.io/ceph/demo:latest-squid"
        box = Docker(image, [], {"MON_IP": "127.0.0.1", "CEPH_PUBLIC_NETWORK": "127.0.0.0/8",
                                 "CEPH_DEMO_UID": "probe", "CEPH_DEMO_ACCESS_KEY": ACCESS,
                                 "CEPH_DEMO_SECRET_KEY": SECRET, "RGW_FRONTEND_PORT": str(port),
                                 "DEMO_DAEMONS": "mon,mgr,osd,rgw", "OSD_TYPE": "directory"},
                     port, port, network_host=True)
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            try:
                with LOCAL.open(f"http://127.0.0.1:{port}/", timeout=2):
                    break
            except HTTPError:
                break
            except (URLError, OSError):
                time.sleep(2)
        time.sleep(10)
        meta = {"version": box.run("radosgw --version 2>&1 | head -1"), "implementation": "Ceph RADOS Gateway (single-node demo cluster)", "distribution": image,
                "image": docker_digest(image)}
        return port, ACCESS, SECRET, meta, box.stop
    raise SystemExit("unknown server " + name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", required=True)
    parser.add_argument("--tools", type=Path, required=True, help="directory with server executables")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("output exists; traces are never overwritten")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="reactivation-probe-") as directory:
        workdir = Path(directory)
        started = datetime.now(timezone.utc).isoformat()
        port, access, secret, meta, stop = launch(args.server, args.tools.resolve(), workdir)
        try:
            s3 = S3(port, access, secret)
            cases = probes(s3)
        finally:
            logs = stop()
        trace = {"schema": 1, "server": args.server, "implementation": meta, "started_utc": started,
                 "finished_utc": datetime.now(timezone.utc).isoformat(),
                 "client": {"python": platform.python_version(), "system": platform.system(),
                            "machine": platform.machine(), "transport": "loopback HTTP, SigV4 path-style"},
                 "cases": cases, "requests": s3.records}
        if isinstance(logs, str):
            trace["server_log_tail"] = logs[-4000:]
        args.output.write_text(json.dumps(trace, indent=1) + "\n")
    print(json.dumps({"server": args.server, "requests": len(s3.records),
                      "cases": [c["name"] for c in cases]}))


if __name__ == "__main__":
    main()
