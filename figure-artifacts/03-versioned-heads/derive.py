"""Derive Figure 3 from actual MinIO HTTP evidence, without parent imports.

Requires a frozen trace.json from the native-server runner. Missing or invalid
evidence is an error; no synthetic data or fallback trajectories are generated.
"""
from __future__ import annotations

import base64
import csv
import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

ROOT = Path(__file__).resolve().parent
CASES = ("delete_current", "copy_restore", "reupload_restore", "delete_marker")
LETTERS = ("α", "β", "γ")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON member: {key}")
        result[key] = value
    return result


def sha(data):
    return hashlib.sha256(data).hexdigest()


def headers(record, side="response"):
    result = {}
    for key, value in record[side]["headers"].items():
        name = key.lower()
        require(name not in result, "duplicate case-insensitive header")
        result[name] = value
    return result


def body(record, side="response"):
    raw = base64.b64decode(record[side]["body_base64"], validate=True)
    require(sha(raw) == record[side]["body_sha256"], "body hash mismatch")
    return raw


def version(record):
    return headers(record).get("x-amz-version-id", "")


def location(record):
    url = urlsplit(record["request"]["url"])
    require(url.scheme == "http" and url.hostname == "127.0.0.1" and not url.fragment,
            "expected unfragmented loopback HTTP evidence")
    return (url.scheme, url.netloc, url.path), parse_qsl(url.query, keep_blank_values=True)


def validate_records(trace):
    require(trace.get("format_version") == 1 and trace.get("status") == "passed",
            "requires a passed native-server trace in format_version 1")
    require("minio version" in trace["server"].lower(), "server identity missing")
    require(len(trace["server_sha256"]) == 64, "server executable hash missing")
    records = trace["requests"]
    require(isinstance(records, list) and records, "empty request trace")
    previous_end = -1
    for index, record in enumerate(records):
        require(type(record["index"]) is int and record["index"] == index,
                "nonconsecutive request indices")
        start, end = record["read_window_ns"]
        require(type(start) is int and type(end) is int and previous_end <= start <= end,
                "requests are not serialized on the recorded monotone clock")
        previous_end = end
        location(record)
        for side in ("request", "response"):
            body(record, side)
            headers(record, side)
        require(type(record["response"]["status"]) is int, "noninteger status")
    cases = {case["name"]: case for case in trace["cases"]}
    require(len(cases) == len(trace["cases"]), "duplicate case names")
    require(set(CASES + ("pinned_selector", "two_object_bundle")) == set(cases),
            "expected the complete six-case source trace")
    return records, cases


def captures(case, records):
    indices = case["captures"]
    require(len(indices) == 3 and all(type(i) is int and 0 <= i < len(records) for i in indices)
            and indices == sorted(set(indices)), "invalid ordered capture references")
    selected = [records[i] for i in indices]
    require(all(r["request"]["method"] == "GET" and body(r, "request") == b"" for r in selected),
            "captures must be bodyless GET requests")
    return selected


def current_case(name, case, records):
    first, middle, last = observations = captures(case, records)
    key = location(first)[0]
    require(all(location(r) == (key, []) for r in observations),
            "a plotted current-key GET has a selector or a different resource")
    require(first["response"]["status"] == last["response"]["status"] == 200,
            "endpoints must be successful GETs")
    require(body(first) == body(last) == b"A\n", "endpoint bytes differ from recorded A")
    require(version(first) and version(last), "missing native endpoint version ID")
    relevant = [r for r in records if location(r)[0] == key]
    before = [r for r in relevant if r["index"] < first["index"]]
    require(len(before) == 1 and before[0]["request"]["method"] == "PUT"
            and before[0]["response"]["status"] == 200
            and body(before[0], "request") == body(first) and version(before[0]) == version(first),
            "initial current GET is not tied to its acknowledged PUT")
    mutations = [r for r in relevant if first["index"] < r["index"] < last["index"]
                 and r["request"]["method"] != "GET"]
    expected_methods = ["DELETE", "DELETE"] if name == "delete_marker" else (
        ["PUT", "DELETE"] if name == "delete_current" else ["PUT", "PUT"])
    require([r["request"]["method"] for r in mutations] == expected_methods,
            "unexpected mutation sequence")
    m1, m2 = mutations
    require(m1["index"] < middle["index"] < m2["index"], "middle capture misplaced")
    require(all(r["response"]["status"] == (204 if r["request"]["method"] == "DELETE" else 200)
                for r in mutations), "mutation not successfully acknowledged")
    if name == "delete_marker":
        require(location(m1)[1] == [] and headers(m1).get("x-amz-delete-marker") == "true"
                and version(m1) and version(m1) != version(first), "missing marker allocation")
        require(middle["response"]["status"] == 404
                and headers(middle).get("x-amz-delete-marker") == "true", "absence is not marker-backed 404")
        require(not version(middle) or version(middle) == version(m1), "inconsistent marker ID")
        removed = version(m1)
    else:
        require(middle["response"]["status"] == 200 and body(middle) == b"B\n"
                and version(middle) and version(middle) != version(first), "missing different current B")
        require(location(m1)[1] == [] and body(m1, "request") == body(middle)
                and version(m1) == version(middle), "B GET differs from its PUT")
        removed = version(middle)
    if name in ("delete_current", "delete_marker"):
        require(location(m2)[1] == [("versionId", removed)], "DELETE targets a different version")
    elif name == "copy_restore":
        source = urlsplit(headers(m2, "request").get("x-amz-copy-source", ""))
        require(source.path == key[2] and parse_qsl(source.query) == [("versionId", version(first))],
                "copy does not select original A")
        require(location(m2)[1] == [] and version(m2) == version(last), "copy/final version mismatch")
    else:
        require(location(m2)[1] == [] and body(m2, "request") == body(first)
                and version(m2) == version(last), "reupload/final version mismatch")
    repeats = version(first) == version(last)
    require(repeats == (name in ("delete_current", "delete_marker")),
            "actual endpoint ID equality does not match the declared figure case")
    if not repeats:
        require(version(last) != version(middle), "new A reuses B's ID")
    return observations


def pinned_control(case, records):
    first, middle, last = captures(case, records)
    key = location(first)[0]
    require(location(middle) == (key, []), "pinned control lacks unqualified current read")
    require(location(first) == location(last) == (key, [("versionId", version(first))]),
            "pinned endpoints do not explicitly select the same version")
    require(all(r["response"]["status"] == 200 for r in (first, middle, last)), "pinned control GET failed")
    require(body(first) == body(last) == b"A\n" and body(middle) == b"B\n"
            and version(first) == version(last) != version(middle), "pinned control bytes/versions inconsistent")
    return [dict(request_index=r["index"], status=r["response"]["status"],
                 request_url=r["request"]["url"], native_version_id=version(r),
                 response_body_sha256=r["response"]["body_sha256"],
                 selector=location(r)[1]) for r in (first, middle, last)]


def write_csv(name, rows):
    with (ROOT / name).open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    source = ROOT / "trace.json"
    if not source.is_file():
        raise SystemExit("Missing trace.json: no data or figure generated; copy the completed native MinIO trace first.")
    payload = source.read_bytes()
    meta = json.loads((ROOT / "figure.json").read_text(), object_pairs_hook=unique_object)
    expected = meta.get("data_sources", {}).get("trace.json")
    require(expected is None or expected == sha(payload), "trace differs from frozen figure input hash")
    trace = json.loads(payload, object_pairs_hook=unique_object)
    records, cases = validate_records(trace)
    # Complete raw-response ID mapping includes unplotted controls and markers.
    id_map = {}
    for record in records:
        native = version(record)
        if native and native not in id_map:
            id_map[native] = dict(global_alias=f"v{len(id_map)}", native_version_id=native,
                first_request_index=record["index"], first_method=record["request"]["method"],
                first_status=record["response"]["status"],
                first_seen_delete_marker=headers(record).get("x-amz-delete-marker", ""),
                plotted_case_aliases="")
    rows = []
    for name in CASES:
        observations = current_case(name, cases[name], records)
        local = {}
        for step, record in enumerate(observations):
            present = record["response"]["status"] == 200
            native = version(record)
            if present and native not in local:
                local[native] = LETTERS[len(local)]
                item = id_map[native]
                item["plotted_case_aliases"] += (";" if item["plotted_case_aliases"] else "") + name + ":" + local[native]
            rows.append(dict(case=name, step=step, request_index=record["index"],
                request_url=record["request"]["url"], status=record["response"]["status"],
                body_symbol=("A" if body(record) == b"A\n" else "B") if present else "ABSENT",
                response_body_base64=record["response"]["body_base64"],
                response_body_sha256=record["response"]["body_sha256"],
                native_version_id=native, version_alias=local[native] if present else "",
                global_version_alias=id_map[native]["global_alias"] if native else "",
                response_delete_marker=headers(record).get("x-amz-delete-marker", ""),
                certifiable_endpoint=present, read_start_ns=record["read_window_ns"][0],
                read_end_ns=record["read_window_ns"][1]))
    control = pinned_control(cases["pinned_selector"], records)
    # Every validation precedes all output writes. No expected-result flag is read.
    write_csv("plot-data.csv", rows)
    write_csv("version-id-map.csv", list(id_map.values()))
    report = dict(evidence_class="native_minio_loopback_http", trace_sha256=sha(payload),
        server=trace["server"], server_sha256=trace["server_sha256"], source_requests=len(records),
        plotted_current_gets=len(rows), plotted_cases=list(CASES),
        pinned_control=dict(plotted=False, different_request_context=True, observations=control),
        two_object_bundle=dict(plotted=False, preserved_in_raw_trace=True),
        scope="Observed controlled current-key trajectories; no cloud-service measurement or API-wide positive guarantee.")
    (ROOT / "derivation.json").write_text(json.dumps(report, indent=2) + "\n")
    meta.update(status="derived_from_native_trace", data_sources={"trace.json":sha(payload)})
    (ROOT / "figure.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(json.dumps({"plotted_current_gets":len(rows),"source_requests":len(records),"version_ids":len(id_map)}))


if __name__ == "__main__":
    main()
