"""Classify current-key identity outcomes from the frozen probe traces.

The classification is recomputed from raw request/response records; the
runner's case summaries are used only to locate request indices, and every
summary field is checked against the raw record it names. No server runs.
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ORDER = ("minio", "ceph", "seaweedfs", "versitygw", "rustfs", "cloudserver", "localstack", "moto", "fake-gcs-server")
S3_PROBES = ("delete_current", "delete_marker", "object_lock_marker", "suspended_null", "copy_restore", "reupload")


def raw(record):
    response = record["response"]
    data = base64.b64decode(response["body_base64"])
    assert hashlib.sha256(data).hexdigest() == response["body_sha256"], record["index"]
    headers = {k.lower(): v for k, v in response["headers"].items()}
    return response["status"], headers, data


def observed(trace, index, gcs=False):
    status, headers, data = raw(trace["requests"][index])
    identity = headers.get("x-goog-generation") if gcs else headers.get("x-amz-version-id")
    return {"index": index, "status": status, "id": identity, "etag": headers.get("etag"),
            "body": data if status == 200 else None}


def check_summary(trace, case, gcs=False):
    for capture in case.get("captures", []):
        actual = observed(trace, capture["index"], gcs)
        assert actual["status"] == capture["status"], (trace["server"], case["name"])
        key = "generation_header" if gcs else "version_id"
        assert actual["id"] == capture[key], (trace["server"], case["name"])


def classify_return(first, last, departed_body):
    """Outcome of a capture pair around a departure from first's body."""
    if last["status"] != 200:
        return "absent"
    if last["body"] == departed_body:
        return "not restored"
    if last["body"] != first["body"]:
        return "other body"
    if first["id"] is None and last["id"] is None:
        return "no identifier"
    return "returned" if last["id"] == first["id"] else "fresh"


def s3_outcomes(trace):
    cases = {c["name"]: c for c in trace["cases"]}
    result = {}
    for name in S3_PROBES:
        case = cases.get(name)
        if case is None or not case.get("created", True) or "captures" not in case:
            result[name] = {"outcome": "not run", "evidence": []}
            continue
        check_summary(trace, case)
        first, middle, last = (observed(trace, c["index"]) for c in case["captures"])
        evidence = [first["index"], middle["index"], last["index"]]
        if first["status"] != 200:
            result[name] = {"outcome": "unsupported", "evidence": case.get("writes", []) + evidence}
            continue
        if name == "suspended_null" and not case.get("suspended"):
            result[name] = {"outcome": "unsupported", "evidence": [case["suspend"]]}
            continue
        departed = middle["body"]
        outcome = classify_return(first, last, departed)
        if name == "suspended_null" and outcome in ("returned", "no identifier"):
            outcome = "identifier unchanged" if first["id"] == last["id"] == middle["id"] else outcome
        item = {"outcome": outcome, "first_id": first["id"], "last_id": last["id"],
                "middle_status": middle["status"], "evidence": evidence}
        if "mutation" in case:
            item["mutation_status"] = raw(trace["requests"][case["mutation"]])[0]
            item["evidence"].append(case["mutation"])
        if name == "copy_restore":
            item["attempt_statuses"] = [raw(trace["requests"][i])[0] for i in case["attempts"]]
        if name == "reupload":
            item["etag_returned"] = first["etag"] is not None and first["etag"] == last["etag"]
            cond = observed(trace, case["conditional"]["index"])
            item["conditional_status"] = cond["status"]
            item["evidence"].append(cond["index"])
        if name == "delete_current":
            cond = observed(trace, case["conditional"]["index"])
            item["conditional_status"] = cond["status"]
            item["evidence"].append(cond["index"])
        if name == "object_lock_marker":
            item["retained_delete_status"] = raw(trace["requests"][case["protected_delete"]])[0]
            item["evidence"].append(case["protected_delete"])
        result[name] = item
    return result


def gcs_outcomes(trace):
    cases = {c["name"]: c for c in trace["cases"]}
    result = {}
    for name in ("delete_current", "copy_restore", "reupload"):
        case = cases[name]
        check_summary(trace, case, gcs=True)
        first, middle, last = (observed(trace, c["index"], gcs=True) for c in case["captures"])
        item = {"outcome": classify_return(first, last, middle["body"]), "first_id": first["id"],
                "last_id": last["id"], "middle_status": middle["status"],
                "evidence": [first["index"], middle["index"], last["index"]]}
        if "mutation" in case:
            item["mutation_status"] = raw(trace["requests"][case["mutation"]])[0]
            item["evidence"].append(case["mutation"])
        if name == "reupload":
            item["etag_returned"] = None
        result[name] = item
    for name in ("delete_marker", "object_lock_marker", "suspended_null"):
        result[name] = {"outcome": "not applicable", "evidence": []}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=HERE / "traces")
    parser.add_argument("--output", type=Path, default=HERE)
    args = parser.parse_args()
    rows, summary = [], {"schema": 1, "implementations": {}, "inputs": {}}
    for server in ORDER:
        path = args.data / f"{server}.json"
        content = path.read_bytes()
        trace = json.loads(content)
        assert trace["server"] == server
        assert [r["index"] for r in trace["requests"]] == list(range(len(trace["requests"])))
        outcomes = gcs_outcomes(trace) if server == "fake-gcs-server" else s3_outcomes(trace)
        summary["inputs"][path.name] = hashlib.sha256(content).hexdigest()
        meta = trace["implementation"]
        summary["implementations"][server] = {
            "implementation": meta["implementation"], "version": meta.get("version", "").splitlines()[0],
            "distribution": meta.get("distribution"), "image": meta.get("image"),
            "executable_sha256": meta.get("executable_sha256"), "requests": len(trace["requests"]),
            "outcomes": outcomes}
        for probe, item in outcomes.items():
            rows.append({"server": server, "version": summary["implementations"][server]["version"],
                         "probe": probe, "outcome": item["outcome"],
                         "first_id": item.get("first_id") or "", "last_id": item.get("last_id") or "",
                         "etag_returned": "" if item.get("etag_returned") is None else int(item["etag_returned"]),
                         "conditional_status": item.get("conditional_status", ""),
                         "evidence": ";".join(map(str, item["evidence"]))})
    s3 = [s for s in ORDER if s != "fake-gcs-server"]
    impl = summary["implementations"]
    summary["findings"] = {
        "s3_implementations": len(s3),
        "requests_total": sum(impl[s]["requests"] for s in ORDER),
        "delete_current_returned": [s for s in s3 if impl[s]["outcomes"]["delete_current"]["outcome"] == "returned"],
        "delete_marker_returned": [s for s in s3 if impl[s]["outcomes"]["delete_marker"]["outcome"] == "returned"],
        "object_lock_marker_returned": [s for s in s3 if impl[s]["outcomes"]["object_lock_marker"]["outcome"] == "returned"],
        "suspended_identifier_unchanged": [s for s in s3 if impl[s]["outcomes"]["suspended_null"]["outcome"]
                                           in ("identifier unchanged", "no identifier")],
        "copy_restore_fresh": [s for s in s3 if impl[s]["outcomes"]["copy_restore"]["outcome"] == "fresh"],
        "copy_restore_not_restored": [s for s in s3 if impl[s]["outcomes"]["copy_restore"]["outcome"] == "not restored"],
        "reupload_fresh_and_etag_returned": [s for s in s3 if impl[s]["outcomes"]["reupload"]["outcome"] == "fresh"
                                             and impl[s]["outcomes"]["reupload"]["etag_returned"]],
        "conditional_304_after_return": [s for s in s3 if impl[s]["outcomes"]["delete_current"].get("conditional_status") == 304],
        "gcs_emulator": {k: impl["fake-gcs-server"]["outcomes"][k]["outcome"]
                         for k in ("delete_current", "copy_restore", "reupload")},
    }
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / "matrix.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (args.output / "summary.json").write_text(json.dumps(summary, indent=1, sort_keys=False) + "\n")
    print(json.dumps(summary["findings"], indent=1))


if __name__ == "__main__":
    main()
