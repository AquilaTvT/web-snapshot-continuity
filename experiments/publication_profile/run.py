"""Measure publication operations under an isolated, restricted MinIO identity.

This uses the official native server and management client, not a cloud account.
Fixture credentials are public. All writable state lives in an owned temporary
directory. A successful execution is not a proof of all S3 implementations.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experiments.versioned_objects.run_minio import (
    Client, ACCESS, SECRET, REGION, HASHES, RELEASE, LOCAL_HTTP,
    header, read_body, port, sha,
)

PUBLISHER = "continuity-publisher"
PASSWORD = "continuity-publisher-public-fixture-secret"
BUCKET = "restricted-publication"
POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        {"Effect": "Allow", "Action": ["s3:GetObject", "s3:GetObjectVersion",
            "s3:PutObject", "s3:DeleteObject"], "Resource": [f"arn:aws:s3:::{BUCKET}/*"]},
        {"Effect": "Allow", "Action": ["s3:GetBucketVersioning"],
            "Resource": [f"arn:aws:s3:::{BUCKET}"]},
        {"Effect": "Deny", "Action": ["s3:DeleteObjectVersion"],
            "Resource": [f"arn:aws:s3:::{BUCKET}/*"]},
    ],
}
VERSIONING = b'<VersioningConfiguration xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><Status>Enabled</Status></VersioningConfiguration>'


def expect(record, status):
    if record["response"]["status"] != status:
        raise AssertionError((record["label"], status, record["response"]))
    return record


def md5(body):
    return base64.b64encode(hashlib.md5(body, usedforsecurity=False).digest()).decode()


def xml_text(record, key):
    return ET.fromstring(read_body(record)).findtext(".//{*}" + key)


def scenarios(root, publisher, mc, temporary):
    cases = []
    def case(name, first_index, **extra):
        cases.append({"name": name, "request_indices": list(range(first_index, len(root.records))), **extra})
    def sibling(bucket):
        return Client(int(root.host.split(":")[1]), bucket=bucket, records=root.records, start=root.start)
    def create(client, lock=False):
        expect(client.request("PUT", "/" + client.bucket,
            headers={"x-amz-bucket-object-lock-enabled": "true"} if lock else {},
            label=f"setup: create {client.bucket}"), 200)
        expect(client.request("PUT", "/" + client.bucket, query={"versioning": ""}, body=VERSIONING,
            headers={"content-type": "application/xml"}, label="setup: enable versioning"), 200)
    def copy(client, key, version, label):
        return expect(client.object("PUT", key,
            headers={"x-amz-copy-source": f"/{client.bucket}/{key}?versionId={quote(version, safe='')}"},
            label=label), 200)

    # A policy document alone is not evidence that the acting principal is bound.
    start = len(root.records)
    owner = sibling("root-policy-control")
    create(owner)
    old = owner.put("page", b"A\n", "root control: publish A")
    first = owner.object("GET", "page", label="root control: first capture")
    newer = owner.put("page", b"B\n", "root control: publish B")
    middle = owner.object("GET", "page", label="root control: B is current")
    deny = {"Version": "2012-10-17", "Statement": [{"Effect": "Deny", "Principal": "*",
        "Action": ["s3:DeleteObjectVersion"], "Resource": ["arn:aws:s3:::root-policy-control/*"]}]}
    expect(owner.request("PUT", "/" + owner.bucket, query={"policy": ""},
        body=json.dumps(deny).encode(), headers={"content-type": "application/json"},
        label="root control: install bucket deny"), 204)
    expect(owner.object("DELETE", "page", query={"versionId": newer}, label="root control: delete B"), 204)
    last = owner.object("GET", "page", label="root control: A becomes current again")
    assert header(last, "x-amz-version-id") == old
    case("root_bucket_policy_control", start, captures=[r["index"] for r in (first, middle, last)])

    create(root)
    policy_path = temporary / "publisher-policy.json"
    policy_path.write_text(json.dumps(POLICY, indent=2) + "\n")
    mc("admin", "user", "add", "fixture", PUBLISHER, PASSWORD)
    mc("admin", "policy", "create", "fixture", "publication", str(policy_path))
    mc("admin", "policy", "attach", "fixture", "publication", "--user", PUBLISHER)
    mc("admin", "user", "info", "fixture", PUBLISHER)

    start = len(root.records)
    first_id = publisher.put("page", b"A\n", "publisher: publish A")
    first = publisher.object("GET", "page", label="publisher: first current A")
    newer = publisher.put("page", b"B\n", "publisher: publish B")
    middle = publisher.object("GET", "page", label="publisher: current B")
    denied = expect(publisher.object("DELETE", "page", query={"versionId": newer},
        label="publisher: forbidden deletion of B version"), 403)
    still_b = publisher.object("GET", "page", label="publisher: B after rejected deletion")
    restored = copy(publisher, "page", first_id, "publisher: copy old A into new current version")
    last = publisher.object("GET", "page", label="publisher: A after copy restore")
    assert read_body(last) == b"A\n" and header(last, "x-amz-version-id") not in (first_id, newer)
    assert header(still_b, "x-amz-version-id") == newer
    case("restricted_data_delete_and_copy", start,
        captures=[r["index"] for r in (first, middle, last)], denied=[denied["index"]],
        successful_restore=restored["index"])

    start = len(root.records)
    first_id = publisher.put("marker", b"A\n", "publisher marker: publish A")
    first = publisher.object("GET", "marker", label="publisher marker: first capture")
    deletion = expect(publisher.object("DELETE", "marker", label="publisher marker: unqualified delete"), 204)
    marker = header(deletion, "x-amz-version-id")
    middle = expect(publisher.object("GET", "marker", label="publisher marker: current absence"), 404)
    denied = expect(publisher.object("DELETE", "marker", query={"versionId": marker},
        label="publisher marker: forbidden marker removal"), 403)
    expect(publisher.object("GET", "marker", label="publisher marker: absence after rejection"), 404)
    copy(publisher, "marker", first_id, "publisher marker: restore by fresh copy")
    last = publisher.object("GET", "marker", label="publisher marker: new A capture")
    assert header(last, "x-amz-version-id") != first_id and read_body(last) == b"A\n"
    case("restricted_marker_delete_and_copy", start,
        captures=[r["index"] for r in (first, middle, last)], denied=[denied["index"]])

    start = len(root.records)
    data_version = publisher.put("batch", b"A\n", "batch: initial A")
    newer = publisher.put("batch", b"B\n", "batch: current B")
    body = ("<Delete><Object><Key>batch</Key><VersionId>" + data_version +
        "</VersionId></Object><Object><Key>batch</Key><VersionId>" + newer +
        "</VersionId></Object></Delete>").encode()
    batch = expect(publisher.request("POST", "/" + BUCKET, query={"delete": ""}, body=body,
        headers={"content-md5": md5(body), "content-type": "application/xml"}, label="batch: forbidden version deletions"), 200)
    errors = ET.fromstring(read_body(batch)).findall("{*}Error")
    assert len(errors) == 2 and all(e.findtext("{*}Code") == "AccessDenied" for e in errors)
    current = publisher.object("GET", "batch", label="batch: B remains current")
    assert header(current, "x-amz-version-id") == newer
    case("restricted_batch_version_delete", start, batch_response=batch["index"])

    start = len(root.records)
    expect(publisher.request("GET", "/" + BUCKET, query={"versioning": ""}, label="publisher config: versioning before"), 200)
    mutations = [
        ("versioning", VERSIONING.replace(b"Enabled", b"Suspended")),
        ("policy", json.dumps({"Version":"2012-10-17","Statement":[]}).encode()),
        ("lifecycle", b'<LifecycleConfiguration><Rule><ID>expire</ID><Status>Enabled</Status><Filter><Prefix></Prefix></Filter><Expiration><Days>1</Days></Expiration></Rule></LifecycleConfiguration>'),
    ]
    denied = []
    for kind, body in mutations:
        denied.append(expect(publisher.request("PUT", "/" + BUCKET, query={kind: ""}, body=body,
            headers={"content-md5": md5(body), "content-type": "application/json" if kind == "policy" else "application/xml"},
            label="publisher config: forbidden " + kind), 403)["index"])
    after = expect(publisher.request("GET", "/" + BUCKET, query={"versioning": ""}, label="publisher config: versioning after"), 200)
    assert xml_text(after, "Status") == "Enabled"
    case("restricted_configuration", start, denied=denied)

    start = len(root.records)
    publisher.put("admission", b"eligible\n", "stable bundle: publish admission")
    publisher.put("fee", b"10\n", "stable bundle: publish fee")
    a1 = publisher.object("GET", "admission", label="stable bundle: A1")
    b1 = publisher.object("GET", "fee", label="stable bundle: B1")
    publisher.put("unrelated", b"changed\n", "stable bundle: unrelated write")
    b2 = publisher.object("GET", "fee", label="stable bundle: B2")
    a2 = publisher.object("GET", "admission", label="stable bundle: A2")
    case("restricted_stable_bundle", start, captures=[r["index"] for r in (a1,b1,b2,a2)])

    # PutObject permission also authorizes multipart completion. Record it rather
    # than equating an IAM action name with just the single-request PUT API.
    start = len(root.records)
    uploads = []
    for body in (b"multipart A\n", b"multipart B\n"):
        init = expect(publisher.object("POST", "multipart", query={"uploads": ""}, label="multipart: initiate"), 200)
        upload_id = xml_text(init, "UploadId")
        part = expect(publisher.object("PUT", "multipart", query={"uploadId": upload_id, "partNumber": "1"},
            body=body, label="multipart: upload only part"), 200)
        uploads.append((upload_id, header(part, "etag")))
    captures = []
    for number in (1, 0):
        upload_id, etag = uploads[number]
        body = f'<CompleteMultipartUpload><Part><PartNumber>1</PartNumber><ETag>{etag}</ETag></Part></CompleteMultipartUpload>'.encode()
        expect(publisher.object("POST", "multipart", query={"uploadId": upload_id}, body=body,
            headers={"content-type":"application/xml"}, label=f"multipart: complete {'AB'[number]}"), 200)
        captures.append(publisher.object("GET", "multipart", label="multipart: current after completion")["index"])
    case("restricted_multipart", start, captures=captures,
        scope="two single-part uploads; A initiated first, B completed first; no cross-operation ordering theorem inferred")

    start = len(root.records)
    locked = sibling("object-lock-control")
    create(locked, lock=True)
    until = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    put = expect(locked.object("PUT", "page", body=b"A\n", headers={
        "x-amz-object-lock-mode": "COMPLIANCE", "x-amz-object-lock-retain-until-date": until,
        "content-md5": md5(b"A\n")}, label="object lock: publish retained A"), 200)
    version = header(put, "x-amz-version-id")
    first = locked.object("GET", "page", label="object lock: first A capture")
    protected = expect(locked.object("DELETE", "page", query={"versionId":version}, label="object lock: retained data deletion rejected"), 400)
    assert xml_text(protected, "Code") == "InvalidRequest"
    assert "WORM protected" in xml_text(protected, "Message")
    deleted = expect(locked.object("DELETE", "page", label="object lock: create delete marker"), 204)
    middle = expect(locked.object("GET", "page", label="object lock: current absence"), 404)
    expect(locked.object("DELETE", "page", query={"versionId":header(deleted, "x-amz-version-id")},
        label="object lock: remove unprotected delete marker"), 204)
    last = locked.object("GET", "page", label="object lock: same retained A current again")
    assert header(last, "x-amz-version-id") == version and read_body(last) == b"A\n"
    case("object_lock_marker_control", start, captures=[r["index"] for r in (first,middle,last)])
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minio", type=Path, required=True)
    parser.add_argument("--mc", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    binary, management = args.minio.resolve(), args.mc.resolve()
    actual = sha(binary.read_bytes())
    assert actual == HASHES[platform.system(), platform.machine()]
    lock = json.loads(Path(__file__).with_name("mc-release.json").read_text())
    os_name = {"Darwin":"darwin", "Linux":"linux"}[platform.system()]
    arch = {"arm64":"arm64", "aarch64":"arm64", "x86_64":"amd64"}[platform.machine()]
    asset = next(a for a in lock["assets"] if a["name"].startswith(f"mc.{os_name}-{arch}."))
    mc_hash = sha(management.read_bytes())
    assert "sha256:" + mc_hash == asset["digest"]
    version = subprocess.check_output([str(binary), "--version"], text=True).strip()
    mc_version = subprocess.check_output([str(management), "--version"], text=True).strip()
    assert RELEASE in version and lock["tag"] in mc_version
    args.output.mkdir(parents=True, exist_ok=True)
    trace_path = args.output / "trace.json"
    if trace_path.exists():
        raise FileExistsError("Refusing to overwrite an existing raw trace: " + str(trace_path))
    records, admin = [], []
    with tempfile.TemporaryDirectory(prefix="publication-profile-") as directory:
        temporary = Path(directory)
        api, console = port(), port()
        while api == console:
            console = port()
        env = dict(os.environ, MINIO_ROOT_USER=ACCESS, MINIO_ROOT_PASSWORD=SECRET,
            MINIO_BROWSER="off", MINIO_UPDATE="off", MINIO_REGION_NAME=REGION)
        command = [str(binary), "--config-dir", str(temporary/"config"), "--certs-dir", str(temporary/"certs"),
            "server", "--quiet", "--address", f"127.0.0.1:{api}", "--console-address", f"127.0.0.1:{console}", str(temporary/"store")]
        def mc(*arguments):
            result = subprocess.run([str(management), "--config-dir", str(temporary/"mc"), "--json", *arguments],
                capture_output=True, text=True, timeout=25)
            admin.append({"arguments":list(arguments), "returncode":result.returncode,
                "stdout":result.stdout, "stderr":result.stderr})
            if result.returncode:
                raise RuntimeError(admin[-1])
        result = {"format_version":1, "server":version, "server_sha256":actual,
            "management_client":mc_version, "management_client_sha256":mc_hash,
            "platform":{"system":platform.system(), "machine":platform.machine(), "python":platform.python_version()},
            "transport":"actual loopback HTTP; native MinIO; no cloud service measured",
            "policy":POLICY, "requests":records, "administration":admin, "status":"incomplete"}
        with (args.output/"server.log").open("w") as log:
            process = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                deadline = time.monotonic() + 20
                while True:
                    if process.poll() is not None:
                        raise RuntimeError("MinIO exited before readiness")
                    try:
                        with LOCAL_HTTP.open(f"http://127.0.0.1:{api}/minio/health/live", timeout=.5) as response:
                            if response.status == 200:
                                break
                    except (HTTPError, URLError, OSError):
                        pass
                    if time.monotonic() > deadline:
                        raise TimeoutError("MinIO readiness deadline")
                    time.sleep(.05)
                mc("alias", "set", "fixture", f"http://127.0.0.1:{api}", ACCESS, SECRET, "--api", "S3v4")
                root = Client(api, bucket=BUCKET, records=records)
                publisher = Client(api, access=PUBLISHER, secret=PASSWORD, bucket=BUCKET, records=records, start=root.start)
                result["cases"] = scenarios(root, publisher, mc, temporary)
                result["status"] = "passed"
            except BaseException as error:
                result["failure"] = repr(error)
                raise
            finally:
                trace_path.write_text(json.dumps(result, indent=2) + "\n")
                if process.poll() is None:
                    process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
    print(json.dumps({"status":result["status"], "cases":len(result["cases"]), "requests":len(records), "trace_sha256":sha(trace_path.read_bytes())}))


if __name__ == "__main__":
    main()
