"""Independently audit the eight-case publication-profile HTTP transcript.

Standard library only; does not import the runner, start a server, or contact a
network. This is a strict checker for this experiment's schedule, not a generic
S3 verifier. Positive path observations do not prove an API-wide no-return rule.
Fixture credentials are public: checking their signatures detects inconsistent
transcripts, not forged evidence or an unrecorded administrator's actions.
"""
from __future__ import annotations

import argparse
import base64
import copy
import csv
from datetime import datetime, timezone
import hashlib
import hmac
import io
import json
from pathlib import Path
import re
import sys
from urllib.parse import parse_qsl, quote, urlencode, urlsplit
import xml.etree.ElementTree as ET

ROOT_USER = "continuity-local-fixture"
PUBLISHER = "continuity-publisher"
KEYS = {
    ROOT_USER: "continuity-local-fixture-secret-not-a-cloud-key",
    PUBLISHER: "continuity-publisher-public-fixture-secret",
}
BUCKET = "restricted-publication"
SERVER_RELEASE = "RELEASE.2025-09-07T16-13-09Z"
MC_RELEASE = "RELEASE.2025-08-13T08-35-41Z"
# Pinned official assets, repeated here rather than importing the producer.
ASSETS = {
    ("Darwin", "arm64"): (
        "7c3b3039b76e55a1b80935848ed83998d5e8d317374f87851f46a019ff5c0aa4",
        "a877fd0c183409da9f20f9d6e1811987298bbbca1aa03428eebdffba79fb9445"),
    ("Darwin", "x86_64"): (
        "4759080aeef7385aaceaac1131c30aaeb99605921553967dc6d3ef4e16ac64f9",
        "2862c79cce11b09be9a8911a279b2e9465bebf74b9f01abca9c348a0d795f0cb"),
    ("Linux", "aarch64"): (
        "5c83cd2cf151717ba0243f73e1c7802ff36e272b67144bdd7f1f7d684fd6f03d",
        "14c8c9616cfce4636add161304353244e8de383b2e2752c0e9dad01d4c27c12c"),
    ("Linux", "x86_64"): (
        "7c5bd8512c6e966455b1d198209358b2d191c77a83ab377c4073281065fb855f",
        "01f866e9c5f9b87c2b09116fa5d7c06695b106242d829a8bb32990c00312e891"),
}
CASE_LAYOUT = [
    ("root_bucket_policy_control", 0, 9, [3, 5, 8]),
    ("restricted_data_delete_and_copy", 11, 19, [12, 14, 18]),
    ("restricted_marker_delete_and_copy", 19, 27, [20, 22, 26]),
    ("restricted_batch_version_delete", 27, 31, []),
    ("restricted_configuration", 31, 36, []),
    ("restricted_stable_bundle", 36, 43, [38, 39, 41, 42]),
    ("restricted_multipart", 43, 51, [48, 50]),
    ("object_lock_marker_control", 51, 60, [54, 57, 59]),
]
SCOPE = [
    "Actual loopback native MinIO execution; no AWS S3 or GCS service measured.",
    "Finite recorded schedule only; not an exhaustive API or IAM verification.",
    "The restricted profile assumes continuously enabled versioning, a fixed bucket/key authority, and only the declared publisher mutations.",
    "Root/admin and other identities remain possible outside the profile; policy attachment does not constrain them.",
    "No unrecorded external writer, lifecycle/replication job, admin change, server restore, or storage rollback is established absent by this transcript.",
    "Bridge promotion needs a separately justified all-operation no-return contract, faithful atomic current-name reads, and the declared time windows.",
    "The stable bundle is observed under the controlled single-writer schedule; no global API-safe certificate is issued.",
    "Multipart evidence covers two single-part uploads completed in reverse initiation order, not all multipart schedules.",
    "Object Lock protects retained data in this test but does not prevent deleting its unprotected delete marker.",
    "Signatures use public fixture secrets. Their verification binds submitted request fields to a named fixture principal, not nonrepudiation or server-response authenticity.",
    "Administration evidence is recorded mc command output. The policy file bytes are declared in trace.policy but are not returned by policy-create stdout.",
]


class AuditError(ValueError):
    """Input cannot support this experiment's conclusions."""


def need(condition, message):
    if not condition:
        raise AuditError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def headers(message):
    fields = message.get("headers")
    need(isinstance(fields, dict), "headers must be an object")
    out = {}
    for key, value in fields.items():
        need(isinstance(key, str) and isinstance(value, str), "non-string header")
        need(key.lower() not in out, "duplicate case-insensitive header")
        need("\n" not in value and "\r" not in value, "multiline header")
        out[key.lower()] = value
    return out


def body(message):
    try:
        raw = base64.b64decode(message["body_base64"], validate=True)
    except (ValueError, KeyError, TypeError) as error:
        raise AuditError("invalid base64 body") from error
    need(message.get("body_sha256") == sha(raw), "body SHA256 mismatch")
    hs = headers(message)
    if "content-length" in hs:
        need(hs["content-length"].isdigit() and int(hs["content-length"]) == len(raw),
             "Content-Length differs from recorded bytes")
    return raw


def xml(raw, expected_root):
    need(b"<!DOCTYPE" not in raw.upper() and b"<!ENTITY" not in raw.upper(),
         "XML declarations/entities outside fixture format")
    try:
        node = ET.fromstring(raw)
    except ET.ParseError as error:
        raise AuditError("invalid XML response/request") from error
    need(node.tag.rsplit("}", 1)[-1] == expected_root, f"expected XML {expected_root}")
    return node


def child(node, name):
    found = node.findall("{*}" + name)
    need(len(found) == 1 and found[0].text is not None, f"expected one XML {name}")
    return found[0].text


def parse_url(value):
    need(isinstance(value, str), "URL must be a string")
    parsed = urlsplit(value)
    need(parsed.scheme == "http" and parsed.hostname == "127.0.0.1"
         and parsed.port and not parsed.username and not parsed.password
         and not parsed.fragment, "not an unambiguous loopback fixture URL")
    pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
    need(len(dict(pairs)) == len(pairs), "duplicate query key")
    canonical_query = urlencode(sorted(pairs), quote_via=quote, safe="~")
    need(parsed.query == canonical_query, "non-canonical query encoding")
    return parsed, dict(pairs)


def signature(request):
    """Reconstruct SigV4 independently from captured HTTP fields."""
    raw = body(request)
    hs = headers(request)
    u, _ = parse_url(request.get("url"))
    match = re.fullmatch(
        r"AWS4-HMAC-SHA256 Credential=([^/]+)/([0-9]{8})/([^/]+)/s3/aws4_request, "
        r"SignedHeaders=([a-z0-9;-]+), Signature=([0-9a-f]{64})", hs.get("authorization", ""))
    need(match is not None, "malformed SigV4 authorization")
    principal, date, region, signed, supplied = match.groups()
    need(principal in KEYS and region == "us-east-1", "unrecognized signing principal or region")
    names = signed.split(";")
    need(names == sorted(set(names)), "non-canonical SignedHeaders")
    need({"host", "x-amz-date", "x-amz-content-sha256"}.issubset(names),
         "required headers not signed")
    need(set(names).issubset(hs), "signed header missing")
    need(all(k in names for k in hs if k.startswith("x-amz-") or k == "content-md5"),
         "semantic fixture header is unsigned")
    stamp = hs["x-amz-date"]
    try:
        datetime.strptime(stamp, "%Y%m%dT%H%M%SZ")
    except ValueError as error:
        raise AuditError("invalid request timestamp") from error
    need(stamp[:8] == date and hs["host"] == u.netloc, "SigV4 scope or host mismatch")
    need(hs["x-amz-content-sha256"] == sha(raw), "signed payload digest mismatch")
    if "content-md5" in hs:
        md5 = base64.b64encode(hashlib.md5(raw, usedforsecurity=False).digest()).decode()
        need(hs["content-md5"] == md5, "Content-MD5 mismatch")
    canonical_headers = "".join(k + ":" + " ".join(hs[k].split()) + "\n" for k in names)
    canonical = "\n".join((request["method"], u.path, u.query, canonical_headers, signed, sha(raw)))
    scope = f"{date}/{region}/s3/aws4_request"
    digest = sha(canonical.encode())
    key = ("AWS4" + KEYS[principal]).encode()
    for component in (date, region, "s3", "aws4_request"):
        key = hmac.new(key, component.encode(), hashlib.sha256).digest()
    calculated = hmac.new(key, f"AWS4-HMAC-SHA256\n{stamp}\n{scope}\n{digest}".encode(), hashlib.sha256).hexdigest()
    need(hmac.compare_digest(calculated, supplied), "SigV4 signature mismatch")
    return principal


def expected_policy():
    return {"Version": "2012-10-17", "Statement": [
        {"Effect": "Allow", "Action": ["s3:GetObject", "s3:GetObjectVersion", "s3:PutObject", "s3:DeleteObject"],
         "Resource": [f"arn:aws:s3:::{BUCKET}/*"]},
        {"Effect": "Allow", "Action": ["s3:GetBucketVersioning"], "Resource": [f"arn:aws:s3:::{BUCKET}"]},
        {"Effect": "Deny", "Action": ["s3:DeleteObjectVersion"], "Resource": [f"arn:aws:s3:::{BUCKET}/*"]},
    ]}


def administration(trace, authority):
    need(trace.get("policy") == expected_policy(), "declared publisher policy differs from reviewed profile")
    logs = trace.get("administration")
    need(isinstance(logs, list) and len(logs) == 5, "missing/extra administration steps")
    commands = [
        ["alias", "set", "fixture", "http://" + authority, ROOT_USER, KEYS[ROOT_USER], "--api", "S3v4"],
        ["admin", "user", "add", "fixture", PUBLISHER, KEYS[PUBLISHER]],
        None,
        ["admin", "policy", "attach", "fixture", "publication", "--user", PUBLISHER],
        ["admin", "user", "info", "fixture", PUBLISHER],
    ]
    outputs = []
    for number, log in enumerate(logs):
        need(log.get("returncode") == 0 and log.get("stderr") == "", "administration command failed")
        args = log.get("arguments")
        if number == 2:
            need(isinstance(args, list) and len(args) == 6
                 and args[:5] == ["admin", "policy", "create", "fixture", "publication"]
                 and Path(args[5]).name == "publisher-policy.json", "wrong policy creation command")
        else:
            need(args == commands[number], "wrong administration principal/command")
        try:
            result = json.loads(log["stdout"])
        except (KeyError, json.JSONDecodeError) as error:
            raise AuditError("invalid mc output") from error
        need(result.get("status") == "success", "mc did not report success")
        outputs.append(result)
    need(outputs[0].get("URL") == "http://" + authority
         and outputs[0].get("accessKey") == ROOT_USER
         and outputs[0].get("api") == "S3v4", "mc alias mismatch")
    need(outputs[1].get("accessKey") == PUBLISHER and outputs[1].get("userStatus") == "enabled", "publisher not enabled")
    need(outputs[2].get("policy") == "publication", "wrong created policy")
    need(outputs[3].get("user") == PUBLISHER and outputs[3].get("policiesAttached") == ["publication"], "policy attachment mismatch")
    need(outputs[4].get("accessKey") == PUBLISHER and outputs[4].get("policyName") == "publication"
         and outputs[4].get("userStatus") == "enabled", "policy identity readback mismatch")


class Transcript:
    def __init__(self, trace):
        need(trace.get("format_version") == 1 and trace.get("status") == "passed", "incomplete or unknown trace format")
        self.trace = trace
        self.records = trace.get("requests")
        need(isinstance(self.records, list) and len(self.records) == 60, "expected 60 recorded S3 requests")
        need(isinstance(trace.get("cases"), list) and len(trace["cases"]) == 8, "expected eight cases")
        self.principals, self.query, self.urls = [], [], []
        self.request_bodies, self.response_bodies = [], []
        previous_end, authority = -1, None
        for number, record in enumerate(self.records):
            need(type(record.get("index")) is int and record["index"] == number, "record index/order mismatch")
            w = record.get("read_window_ns")
            need(isinstance(w, list) and len(w) == 2 and all(type(v) is int for v in w)
                 and previous_end < w[0] < w[1], "non-positive, overlapping, or unordered request windows")
            previous_end = w[1]
            req, resp = record.get("request", {}), record.get("response", {})
            need(req.get("method") in {"GET", "PUT", "POST", "DELETE"}, "unexpected method")
            need(type(resp.get("status")) is int and 100 <= resp["status"] <= 599, "invalid HTTP status")
            principal = signature(req)
            u, q = parse_url(req["url"])
            if authority is None:
                authority = u.netloc
            need(u.netloc == authority, "request authority changed")
            self.urls.append(u)
            self.query.append(q)
            self.principals.append(principal)
            self.request_bodies.append(body(req))
            self.response_bodies.append(body(resp))
            need(headers(resp).get("server") == "MinIO", "unexpected HTTP server header")
        self.authority = authority
        administration(trace, authority)
        platform = trace.get("platform", {})
        asset = ASSETS.get((platform.get("system"), platform.get("machine")))
        need(asset is not None and (trace.get("server_sha256"), trace.get("management_client_sha256")) == asset,
             "unrecognized pinned server/management asset digests")
        need(SERVER_RELEASE in trace.get("server", "") and "07c3a429bfed433e49018cb0f78a52145d4bedeb" in trace["server"],
             "server release/commit mismatch")
        need(MC_RELEASE in trace.get("management_client", "") and "7394ce0dd2a80935aded936b09fa12cbb3cb8096" in trace["management_client"],
             "management client release/commit mismatch")
        self.case_for_record = {9: "publisher_setup", 10: "publisher_setup"}
        self.capture_indices = set()
        for supplied, (name, start, end, captures) in zip(trace["cases"], CASE_LAYOUT):
            need(supplied.get("name") == name and supplied.get("request_indices") == list(range(start, end)),
                 "case name/index partition differs from fixture schedule")
            need(supplied.get("captures", []) == captures, "case capture references differ from raw schedule")
            self.capture_indices.update(captures)
            self.case_for_record.update({i: name for i in range(start, end)})
        need(len(self.case_for_record) == 60, "unaccounted record")
        self.used = set()
        self.allocated = {}

    def hs(self, i, request=False):
        return headers(self.records[i]["request" if request else "response"])

    def check(self, i, method, bucket, key="", query=None, status=200, principal=PUBLISHER):
        r = self.records[i]
        need(r["request"]["method"] == method and self.urls[i].path == "/" + bucket + ("/" + key if key else "")
             and self.query[i] == (query or {}), f"record {i}: wrong operation, resource, or selector")
        need(r["response"]["status"] == status, f"record {i}: unexpected HTTP status")
        need(self.principals[i] == principal, f"record {i}: wrong authenticated fixture principal")
        self.used.add(i)
        return r

    def version(self, i):
        value = self.hs(i).get("x-amz-version-id")
        need(isinstance(value, str) and value not in ("", "null") and not any(c.isspace() for c in value),
             f"record {i}: missing/non-versioned object identity")
        return value

    def allocate(self, i):
        value = self.version(i)
        # Allocation uniqueness is an observed property, not activation continuity.
        need(value not in self.allocated, f"record {i}: allocated version ID reused")
        self.allocated[value] = i
        return value

    def error(self, i, code, bucket, key="", message=None):
        node = xml(self.response_bodies[i], "Error")
        need(child(node, "Code") == code and child(node, "BucketName") == bucket
             and child(node, "Resource") == "/" + bucket + ("/" + key if key else ""),
             f"record {i}: wrong error code/resource")
        if key:
            need(child(node, "Key") == key, f"record {i}: wrong error key")
        need(child(node, "RequestId") == self.hs(i).get("x-amz-request-id"), f"record {i}: error request ID mismatch")
        if message:
            need(message in child(node, "Message"), f"record {i}: expected error explanation missing")

    def put(self, i, bucket, key, payload, principal=PUBLISHER):
        self.check(i, "PUT", bucket, key, principal=principal)
        need(self.request_bodies[i] == payload and not self.response_bodies[i], f"record {i}: wrong PUT bytes/result")
        need("x-amz-copy-source" not in self.hs(i, True), "PUT unexpectedly copies a source")
        return self.allocate(i)

    def current(self, i, bucket, key, payload, version, principal=PUBLISHER):
        self.check(i, "GET", bucket, key, status=200 if payload is not None else 404, principal=principal)
        req = self.hs(i, True)
        need(not self.request_bodies[i] and not any(k in req for k in (
            "range", "if-match", "if-none-match", "if-modified-since", "if-unmodified-since", "accept", "accept-encoding")),
             f"record {i}: not the fixture's unqualified whole current GET")
        need(self.version(i) == version, f"record {i}: returned version does not follow the recorded mutation")
        if payload is None:
            need(self.hs(i).get("x-amz-delete-marker") == "true", f"record {i}: missing authoritative delete-marker evidence")
            self.error(i, "NoSuchKey", bucket, key)
        else:
            need(self.response_bodies[i] == payload and self.hs(i).get("x-amz-delete-marker") != "true",
                 f"record {i}: current body/readback mismatch")

    def copy_restore(self, i, bucket, key, original, principal=PUBLISHER):
        self.check(i, "PUT", bucket, key, principal=principal)
        need(not self.request_bodies[i], "copy request unexpectedly carries upload bytes")
        source = self.hs(i, True).get("x-amz-copy-source", "")
        parsed = urlsplit(source)
        need(parsed.path == f"/{bucket}/{key}" and not parsed.scheme and not parsed.netloc
             and parse_qsl(parsed.query, keep_blank_values=True) == [("versionId", original)],
             "copy restore did not select the old version at the same key")
        result = xml(self.response_bodies[i], "CopyObjectResult")
        child(result, "ETag")
        child(result, "LastModified")
        return self.allocate(i)

    def delete(self, i, bucket, key, selected=None, status=204, principal=PUBLISHER, marker=False):
        self.check(i, "DELETE", bucket, key, query={"versionId": selected} if selected else {}, status=status, principal=principal)
        need(not self.request_bodies[i], "DELETE unexpectedly carries request bytes")
        if status == 403:
            self.error(i, "AccessDenied", bucket, key)
            return None
        if status == 400:
            self.error(i, "InvalidRequest", bucket, key, "WORM protected")
            return None
        need(not self.response_bodies[i], "successful DELETE has unexpected response bytes")
        value = self.version(i)
        if selected:
            need(value == selected, "deleted response version differs from selected version")
        else:
            self.allocate(i)
            marker = True
        need((self.hs(i).get("x-amz-delete-marker") == "true") == marker, "delete-marker response mismatch")
        return value

    def setup(self, create, enable, bucket, lock=False):
        self.check(create, "PUT", bucket, principal=ROOT_USER)
        need(not self.request_bodies[create] and not self.response_bodies[create], "bucket create has unexpected bytes")
        need((self.hs(create, True).get("x-amz-bucket-object-lock-enabled") == "true") == lock, "object lock bucket creation mismatch")
        self.check(enable, "PUT", bucket, query={"versioning": ""}, principal=ROOT_USER)
        node = xml(self.request_bodies[enable], "VersioningConfiguration")
        need(child(node, "Status") == "Enabled" and not self.response_bodies[enable], "versioning was not enabled")

    def bridge(self, first, last):
        a, b = self.records[first], self.records[last]
        need(a["request"]["method"] == b["request"]["method"] == "GET"
             and self.urls[first].path == self.urls[last].path
             and self.query[first] == self.query[last] == {}
             and self.principals[first] == self.principals[last], "bridge context mismatch")
        need(a["response"]["status"] == b["response"]["status"] == 200
             and self.response_bodies[first] == self.response_bodies[last]
             and self.version(first) == self.version(last), "bridge endpoints do not match")
        start, end = a["read_window_ns"][1], b["read_window_ns"][0]
        need(start < end, "bridge has no positive conservative interval")
        return {"captures": [first, last], "interval_ns": [start, end], "interval_convention": "[start,end)",
                "duration_ns": end - start, "native_version_id": self.version(first),
                "body_sha256": sha(self.response_bodies[first])}


def audit(trace):
    t = Transcript(trace)
    results = []
    # Root control: policy installation is checked, but the acting key is root.
    bucket = "root-policy-control"
    t.setup(0, 1, bucket)
    old = t.put(2, bucket, "page", b"A\n", ROOT_USER)
    t.current(3, bucket, "page", b"A\n", old, ROOT_USER)
    new = t.put(4, bucket, "page", b"B\n", ROOT_USER)
    t.current(5, bucket, "page", b"B\n", new, ROOT_USER)
    t.check(6, "PUT", bucket, query={"policy": ""}, status=204, principal=ROOT_USER)
    deny = {"Version": "2012-10-17", "Statement": [{"Effect": "Deny", "Principal": "*",
        "Action": ["s3:DeleteObjectVersion"], "Resource": [f"arn:aws:s3:::{bucket}/*"]}]}
    need(json.loads(t.request_bodies[6]) == deny and not t.response_bodies[6], "root control bucket deny missing")
    t.delete(7, bucket, "page", new, principal=ROOT_USER)
    t.current(8, bucket, "page", b"A\n", old, ROOT_USER)
    results.append({"name": CASE_LAYOUT[0][0], "principal": ROOT_USER, "observed_path": ["A", "B", "A"],
        "capture_versions": [old, new, old], "counterexample_records": [3, 5, 8],
        "naive_bridge": t.bridge(3, 8), "continuity_decision": "reject_observed_return",
        "finding": "The recorded root request deleted B despite the installed bucket deny; a policy document alone did not constrain this actor."})
    t.setup(9, 10, BUCKET)

    old = t.put(11, BUCKET, "page", b"A\n")
    t.current(12, BUCKET, "page", b"A\n", old)
    new = t.put(13, BUCKET, "page", b"B\n")
    t.current(14, BUCKET, "page", b"B\n", new)
    t.delete(15, BUCKET, "page", new, status=403)
    t.current(16, BUCKET, "page", b"B\n", new)
    copied = t.copy_restore(17, BUCKET, "page", old)
    t.current(18, BUCKET, "page", b"A\n", copied)
    results.append({"name": CASE_LAYOUT[1][0], "principal": PUBLISHER, "observed_path": ["A", "B", "B", "A"],
        "capture_versions": [old, new, copied], "denial_records": [15], "denial_codes": ["AccessDenied"],
        "same_bytes_restored_with_fresh_id": True, "continuity_decision": "no_equal_endpoint_bridge",
        "finding": "Version-specific deletion was refused; readback stayed B; a copy of historical A allocated a fresh current version."})

    old = t.put(19, BUCKET, "marker", b"A\n")
    t.current(20, BUCKET, "marker", b"A\n", old)
    marker = t.delete(21, BUCKET, "marker")
    t.current(22, BUCKET, "marker", None, marker)
    t.delete(23, BUCKET, "marker", marker, status=403)
    t.current(24, BUCKET, "marker", None, marker)
    copied = t.copy_restore(25, BUCKET, "marker", old)
    t.current(26, BUCKET, "marker", b"A\n", copied)
    results.append({"name": CASE_LAYOUT[2][0], "principal": PUBLISHER, "observed_path": ["A", "ABSENT", "ABSENT", "A"],
        "capture_versions": [old, marker, copied], "denial_records": [23], "denial_codes": ["AccessDenied"],
        "same_bytes_restored_with_fresh_id": True, "continuity_decision": "no_equal_endpoint_bridge",
        "finding": "Ordinary deletion created a marker; removing that version was refused; copying old A produced a fresh ID."})

    old = t.put(27, BUCKET, "batch", b"A\n")
    new = t.put(28, BUCKET, "batch", b"B\n")
    t.check(29, "POST", BUCKET, query={"delete": ""})
    request = xml(t.request_bodies[29], "Delete")
    items = request.findall("{*}Object")
    need(len(items) == 2 and [(child(x, "Key"), child(x, "VersionId")) for x in items] == [("batch", old), ("batch", new)],
         "batch did not target both recorded data versions")
    response = xml(t.response_bodies[29], "DeleteResult")
    errors = response.findall("{*}Error")
    need(len(errors) == 2 and not response.findall("{*}Deleted"), "batch response did not deny every requested deletion")
    per_item = [(child(x, "Key"), child(x, "VersionId"), child(x, "Code")) for x in errors]
    need(sorted(per_item) == sorted([("batch", old, "AccessDenied"), ("batch", new, "AccessDenied")]),
         "batch denial identities/codes do not match requests")
    t.current(30, BUCKET, "batch", b"B\n", new)
    results.append({"name": CASE_LAYOUT[3][0], "principal": PUBLISHER, "http_status": 200,
        "per_object_results": [{"key": k, "version_id": v, "code": c} for k, v, c in per_item],
        "current_version_after": new, "finding": "HTTP 200 contains two AccessDenied item results; B remains current."})

    for i in (31, 35):
        t.check(i, "GET", BUCKET, query={"versioning": ""})
        need(child(xml(t.response_bodies[i], "VersioningConfiguration"), "Status") == "Enabled", "versioning readback not Enabled")
    for i, kind in ((32, "versioning"), (33, "policy"), (34, "lifecycle")):
        t.check(i, "PUT", BUCKET, query={kind: ""}, status=403)
        t.error(i, "AccessDenied", BUCKET)
    need(child(xml(t.request_bodies[32], "VersioningConfiguration"), "Status") == "Suspended", "suspension was not attempted")
    need(json.loads(t.request_bodies[33]) == {"Version": "2012-10-17", "Statement": []}, "policy change not attempted")
    lifecycle = xml(t.request_bodies[34], "LifecycleConfiguration")
    rules = lifecycle.findall("{*}Rule")
    need(len(rules) == 1 and child(rules[0], "Status") == "Enabled"
         and rules[0].findtext("{*}Expiration/{*}Days") == "1", "lifecycle expiration not attempted")
    results.append({"name": CASE_LAYOUT[4][0], "principal": PUBLISHER,
        "denial_records": [32, 33, 34], "denial_codes": ["AccessDenied"] * 3,
        "versioning_readback": ["Enabled", "Enabled"],
        "finding": "Suspension, bucket-policy replacement and expiration-configuration requests were denied; only versioning has explicit post-attempt readback."})

    a = t.put(36, BUCKET, "admission", b"eligible\n")
    b = t.put(37, BUCKET, "fee", b"10\n")
    t.current(38, BUCKET, "admission", b"eligible\n", a)
    t.current(39, BUCKET, "fee", b"10\n", b)
    t.put(40, BUCKET, "unrelated", b"changed\n")
    t.current(41, BUCKET, "fee", b"10\n", b)
    t.current(42, BUCKET, "admission", b"eligible\n", a)
    bridges = [t.bridge(38, 42), t.bridge(39, 41)]
    intersection = [max(x["interval_ns"][0] for x in bridges), min(x["interval_ns"][1] for x in bridges)]
    need(intersection[0] < intersection[1], "stable bundle bridge intersection is empty")
    need(t.records[40]["read_window_ns"][0] >= intersection[0]
         and t.records[40]["read_window_ns"][1] <= intersection[1], "unrelated mutation outside the bridge intersection")
    results.append({"name": CASE_LAYOUT[5][0], "principal": PUBLISHER, "target": ["eligible\n", "10\n"],
        "captures": [38, 39, 41, 42], "bridges": bridges, "intersection_ns": intersection,
        "intersection_duration_ns": intersection[1] - intersection[0], "interval_convention": "[start,end)",
        "unrelated_mutation_record": 40, "recorded_target_mutations_inside_capture_window": [],
        "continuity_decision": "conditional_bridge_if_declared_operation_contract_holds",
        "observed_schedule_supports_target_pair": True, "api_wide_continuity_proved": False,
        "finding": "Equal current-name captures yield overlapping candidate supports under a separate no-return contract; the controlled recorded schedule includes only an unrelated-key write inside the intersection."})

    uploads = []
    for initiate, part, payload in ((43, 44, b"multipart A\n"), (45, 46, b"multipart B\n")):
        t.check(initiate, "POST", BUCKET, "multipart", query={"uploads": ""})
        need(not t.request_bodies[initiate], "multipart initiation has unexpected bytes")
        node = xml(t.response_bodies[initiate], "InitiateMultipartUploadResult")
        need(child(node, "Bucket") == BUCKET and child(node, "Key") == "multipart", "multipart initiation target mismatch")
        upload = child(node, "UploadId")
        need(upload not in [x[0] for x in uploads], "multipart upload identity reused")
        t.check(part, "PUT", BUCKET, "multipart", query={"uploadId": upload, "partNumber": "1"})
        need(t.request_bodies[part] == payload and not t.response_bodies[part], "multipart part bytes mismatch")
        etag = t.hs(part).get("etag")
        need(etag == '"' + hashlib.md5(payload, usedforsecurity=False).hexdigest() + '"', "single-part ETag does not match uploaded bytes")
        uploads.append((upload, etag, payload))
    complete_versions = []
    for complete, capture, position in ((47, 48, 1), (49, 50, 0)):
        upload, etag, payload = uploads[position]
        t.check(complete, "POST", BUCKET, "multipart", query={"uploadId": upload})
        node = xml(t.request_bodies[complete], "CompleteMultipartUpload")
        parts = node.findall("{*}Part")
        need(len(parts) == 1 and child(parts[0], "PartNumber") == "1" and child(parts[0], "ETag") == etag,
             "multipart completion did not bind its uploaded part")
        response = xml(t.response_bodies[complete], "CompleteMultipartUploadResult")
        need(child(response, "Bucket") == BUCKET and child(response, "Key") == "multipart", "multipart completion response target mismatch")
        version = t.allocate(complete)
        t.current(capture, BUCKET, "multipart", payload, version)
        complete_versions.append(version)
    results.append({"name": CASE_LAYOUT[6][0], "principal": PUBLISHER,
        "initiation_order": ["A", "B"], "completion_order": ["B", "A"],
        "capture_records": [48, 50], "capture_versions": complete_versions,
        "distinct_completion_ids": True, "finding": "The publisher could complete multipart uploads; the older initiation completed later and returned a distinct observed version ID. No universal multipart ordering or ID-allocation-time claim follows."})

    bucket = "object-lock-control"
    t.setup(51, 52, bucket, lock=True)
    retained = t.put(53, bucket, "page", b"A\n", ROOT_USER)
    hs = t.hs(53, True)
    need(hs.get("x-amz-object-lock-mode") == "COMPLIANCE", "retained PUT was not COMPLIANCE mode")
    try:
        until = datetime.strptime(hs["x-amz-object-lock-retain-until-date"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        attempted = datetime.strptime(t.hs(55, True)["x-amz-date"], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except (KeyError, ValueError) as error:
        raise AuditError("invalid retention period") from error
    need(until > attempted, "retention had expired before attempted deletion")
    t.current(54, bucket, "page", b"A\n", retained, ROOT_USER)
    t.delete(55, bucket, "page", retained, status=400, principal=ROOT_USER)
    marker = t.delete(56, bucket, "page", principal=ROOT_USER)
    t.current(57, bucket, "page", None, marker, ROOT_USER)
    t.delete(58, bucket, "page", marker, principal=ROOT_USER, marker=True)
    t.current(59, bucket, "page", b"A\n", retained, ROOT_USER)
    results.append({"name": CASE_LAYOUT[7][0], "principal": ROOT_USER, "observed_path": ["A", "ABSENT", "A"],
        "capture_versions": [retained, marker, retained], "retained_delete_status": 400,
        "retained_delete_code": "InvalidRequest", "retained_delete_message_contains": "WORM protected",
        "counterexample_records": [54, 57, 59], "naive_bridge": t.bridge(54, 59),
        "continuity_decision": "reject_observed_return", "finding": "Retained data survived attempted version deletion, but deleting the unprotected marker reactivated its old current ID."})
    need(t.used == set(range(60)), "raw requests remain unaudited")
    # Cross-check redundant producer annotations only after deriving mechanisms.
    for n, denied in ((1, [15]), (2, [23]), (4, [32, 33, 34])):
        need(trace["cases"][n].get("denied") == denied, "denial index annotations disagree with raw evidence")
    need(trace["cases"][1].get("successful_restore") == 17 and trace["cases"][3].get("batch_response") == 29,
         "producer response index annotation mismatch")
    return t, results


def derive(trace, trace_bytes):
    t, cases = audit(trace)
    aliases = {value: f"v{n}" for n, value in enumerate(t.allocated)}
    rows = []
    for i, record in enumerate(t.records):
        u = t.urls[i]
        version = t.hs(i).get("x-amz-version-id", "")
        is_object_get = record["request"]["method"] == "GET" and u.path.count("/") == 2
        rows.append({"index": i, "case": t.case_for_record[i], "principal": t.principals[i],
            "method": record["request"]["method"], "path": u.path, "query": u.query,
            "status": record["response"]["status"], "capture": i in t.capture_indices,
            "current_object_get": is_object_get and not t.query[i],
            "certifiable_read_candidate": is_object_get and not t.query[i] and record["response"]["status"] == 200,
            "version_id": version, "version_alias": aliases.get(version, ""),
            "delete_marker": t.hs(i).get("x-amz-delete-marker", ""),
            "request_body_sha256": sha(t.request_bodies[i]), "response_body_sha256": sha(t.response_bodies[i]),
            "object_body_utf8": t.response_bodies[i].decode() if is_object_get and record["response"]["status"] == 200 else "",
            "window_start_ns": record["read_window_ns"][0], "window_end_ns": record["read_window_ns"][1]})
    observations = [r for r in rows if r["current_object_get"]]
    summary = {"format_version": 1, "status": "passed_independent_transcript_audit",
        "provenance": {"trace_sha256": sha(trace_bytes), "derive_source_sha256": sha(Path(__file__).read_bytes()),
            "runner_imported": False, "network_used": False},
        "server": {"release": SERVER_RELEASE, "recorded_binary_sha256": trace["server_sha256"],
            "management_release": MC_RELEASE, "recorded_management_binary_sha256": trace["management_client_sha256"],
            "binary_evidence_scope": "Recorded hashes agree with pinned official asset identities; offline derivation does not re-execute or independently identify the serving process."},
        "counts": {"s3_requests": len(rows), "cases": len(cases), "object_get_observations": len(observations),
            "successful_object_gets": sum(r["status"] == 200 for r in observations),
            "absence_object_gets": sum(r["status"] == 404 for r in observations),
            "publisher_requests": t.principals.count(PUBLISHER), "root_requests": t.principals.count(ROOT_USER),
            "allocated_native_ids": len(aliases), "sigv4_requests_verified": len(rows)},
        "administration": {"principal": PUBLISHER, "recorded_policy_attachment": "publication", "enabled_readback": True,
            "policy_sha256": sha(json.dumps(trace["policy"], sort_keys=True, separators=(",", ":")).encode()),
            "policy_file_content_independently_fetched": False},
        "cases": cases,
        "version_id_map": [{"alias": aliases[v], "native_version_id": v, "allocation_record": i} for v, i in t.allocated.items()],
        "api_wide_continuity_proved": False, "scope_limits": SCOPE}
    return summary, rows, observations


def csv_bytes(rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode()


def _replace_body(message, raw):
    """Test helper: change bytes with consistent digest/length, not just a stale hash."""
    message["body_base64"] = base64.b64encode(raw).decode()
    message["body_sha256"] = sha(raw)
    for key in list(message["headers"]):
        if key.lower() == "content-length":
            message["headers"][key] = str(len(raw))


def _resign(request, principal=None):
    """Test helper: semantic corruptions with valid public-fixture-secret signatures."""
    hs = headers(request)
    old = re.fullmatch(r"AWS4-HMAC-SHA256 Credential=([^/]+)/([^,]+), SignedHeaders=([^,]+), Signature=([0-9a-f]{64})", hs["authorization"])
    who, scope, signed, _ = old.groups()
    who = principal or who
    raw = base64.b64decode(request["body_base64"])
    for key in list(request["headers"]):
        if key.lower() == "x-amz-content-sha256":
            request["headers"][key] = sha(raw)
        if key.lower() == "content-md5":
            request["headers"][key] = base64.b64encode(hashlib.md5(raw, usedforsecurity=False).digest()).decode()
    hs = headers(request)
    u = urlsplit(request["url"])
    canonical = "\n".join((request["method"], u.path, u.query,
        "".join(k + ":" + " ".join(hs[k].split()) + "\n" for k in signed.split(";")), signed, sha(raw)))
    key = ("AWS4" + KEYS[who]).encode()
    for component in scope.split("/"):
        key = hmac.new(key, component.encode(), hashlib.sha256).digest()
    digest = hmac.new(key, f"AWS4-HMAC-SHA256\n{hs['x-amz-date']}\n{scope}\n{sha(canonical.encode())}".encode(), hashlib.sha256).hexdigest()
    for key in request["headers"]:
        if key.lower() == "authorization":
            request["headers"][key] = f"AWS4-HMAC-SHA256 Credential={who}/{scope}, SignedHeaders={signed}, Signature={digest}"


def self_test(trace):
    audit(copy.deepcopy(trace))
    checks = []
    def rejected(name, mutate, expected):
        specimen = copy.deepcopy(trace)
        mutate(specimen)
        try:
            audit(specimen)
        except AuditError as error:
            need(expected in str(error), f"self-test {name}: rejected for unexpected reason: {error}")
            checks.append({"name": name, "status": "rejected", "reason": str(error)})
        else:
            raise AuditError("self-test accepted corrupted input: " + name)
    def response_bytes(d, i, raw):
        _replace_body(d["requests"][i]["response"], raw)
    def header_value(d, i, name, value, request=False):
        target = d["requests"][i]["request" if request else "response"]["headers"]
        for key in list(target):
            if key.lower() == name:
                target[key] = value
                return
        target[name] = value
    rejected("incomplete_trace", lambda d: d.update(status="incomplete"), "incomplete")
    rejected("body_hash_corruption", lambda d: d["requests"][12]["response"].update(body_base64="Qg=="), "SHA256")
    rejected("duplicate_record_index", lambda d: d["requests"][12].update(index=11), "index/order")
    rejected("overlapping_windows", lambda d: d["requests"][41].update(read_window_ns=d["requests"][39]["read_window_ns"]), "windows")
    rejected("valid_root_signature_on_publisher_request", lambda d: _resign(d["requests"][15]["request"], ROOT_USER), "wrong authenticated")
    def bad_signature(d):
        req = d["requests"][15]["request"]
        key = next(k for k in req["headers"] if k.lower() == "authorization")
        value = req["headers"][key]
        req["headers"][key] = value[:-1] + ("0" if value[-1] != "0" else "1")
    rejected("signature_corruption", bad_signature, "signature mismatch")
    def pinned_get(d):
        req = d["requests"][38]["request"]
        req["url"] += "?versionId=" + headers(d["requests"][38]["response"])["x-amz-version-id"]
        _resign(req)
    rejected("capture_is_historical_selector", pinned_get, "selector")
    rejected("capture_reference_swap", lambda d: d["cases"][5].update(captures=[39, 38, 41, 42]), "capture references")
    rejected("denial_annotation_disagrees", lambda d: d["cases"][1].update(denied=[16]), "denial index")
    rejected("rehash_wrong_post_denial_readback", lambda d: response_bytes(d, 16, b"A\n"), "current body")
    def missing_batch_denial(d):
        node = ET.fromstring(base64.b64decode(d["requests"][29]["response"]["body_base64"]))
        node.remove(node.findall("{*}Error")[0])
        response_bytes(d, 29, ET.tostring(node))
    rejected("http200_batch_missing_item_error", missing_batch_denial, "deny every")
    def wrong_error(d):
        raw = base64.b64decode(d["requests"][23]["response"]["body_base64"])
        response_bytes(d, 23, raw.replace(b"AccessDenied", b"NoSuchVersion"))
    rejected("403_wrong_xml_code", wrong_error, "wrong error code")
    rejected("404_missing_marker", lambda d: header_value(d, 22, "x-amz-delete-marker", "false"), "delete-marker evidence")
    rejected("removed_policy_deny", lambda d: d["policy"]["Statement"].pop(), "declared publisher policy")
    def wrong_admin(d):
        out = json.loads(d["administration"][4]["stdout"])
        out["accessKey"] = ROOT_USER
        d["administration"][4]["stdout"] = json.dumps(out)
    rejected("wrong_policy_subject_readback", wrong_admin, "identity readback")
    def wrong_copy(d):
        req = d["requests"][17]["request"]
        new = headers(d["requests"][13]["response"])["x-amz-version-id"]
        header_value(d, 17, "x-amz-copy-source", f"/{BUCKET}/page?versionId={new}", True)
        _resign(req)
    rejected("copy_selects_newer_version", wrong_copy, "old version")
    rejected("copy_200_error_body", lambda d: response_bytes(d, 17, b"<Error><Code>AccessDenied</Code></Error>"), "CopyObjectResult")
    def reused_completion_id(d):
        same = headers(d["requests"][47]["response"])["x-amz-version-id"]
        header_value(d, 49, "x-amz-version-id", same)
        header_value(d, 50, "x-amz-version-id", same)
    rejected("mpu_reuses_completed_id", reused_completion_id, "allocated version ID reused")
    def wrong_upload(d):
        req = d["requests"][49]["request"]
        req["url"] = d["requests"][47]["request"]["url"]
        _resign(req)
    rejected("mpu_wrong_upload_pairing", wrong_upload, "selector")
    def expired_retention(d):
        header_value(d, 53, "x-amz-object-lock-retain-until-date", "2000-01-01T00:00:00Z", True)
        _resign(d["requests"][53]["request"])
    rejected("expired_retention_control", expired_retention, "retention had expired")
    rejected("assumed_worm403_instead_of_recorded400", lambda d: d["requests"][55]["response"].update(status=403), "HTTP status")
    rejected("stable_bundle_changed_body", lambda d: response_bytes(d, 41, b"20\n"), "current body")
    return {"status": "passed", "valid_trace_accepted": True, "damaged_inputs_rejected": len(checks), "checks": checks}


def load_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            need(key not in result, "duplicate JSON key")
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=unique)
    except (ValueError, TypeError) as error:
        if isinstance(error, AuditError):
            raise
        raise AuditError("invalid trace JSON") from error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", type=Path, default=Path(__file__).with_name("data") / "trace.json")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true", help="accept the real trace and reject targeted damaged copies first; also derive files when --output is supplied")
    args = parser.parse_args()
    raw = args.trace.read_bytes()
    trace = load_json(raw)
    if args.self_test:
        print(json.dumps(self_test(trace), indent=2))
        if args.output is None:
            return
    if args.output is None:
        parser.error("--output is required unless --self-test is used")
    summary, requests, observations = derive(trace, raw)
    payloads = {"summary.json": (json.dumps(summary, indent=2) + "\n").encode(),
                "requests.csv": csv_bytes(requests), "observations.csv": csv_bytes(observations)}
    # No destination is created or changed until every input/semantic check passes.
    args.output.mkdir(parents=True, exist_ok=True)
    for name, data in payloads.items():
        (args.output / name).write_bytes(data)
    print(json.dumps({"status": summary["status"], "counts": summary["counts"],
                      "trace_sha256": summary["provenance"]["trace_sha256"]}))


if __name__ == "__main__":
    try:
        main()
    except (AuditError, KeyError, TypeError, ValueError) as error:
        print(f"Audit refused: {error}", file=sys.stderr)
        raise SystemExit(1)
