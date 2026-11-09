"""Reconstruct four policy contrasts directly from the accompanying raw trace."""
import argparse
import base64
import copy
import csv
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
SPECS = [
    ("owner_deny", "Owner + bucket deny", [3, 5, 8], [7], 204, ["A", "B", "A"], ["α", "β", "α"]),
    ("object_lock", "Owner + Object Lock", [54, 57, 59], [55, 56, 58], 204, ["A", "ABSENT", "A"], ["α", "β", "α"]),
    ("restricted_delete", "Publisher: remove B", [12, 14, 16], [15], 403, ["A", "B", "B"], ["α", "β", "β"]),
    ("restricted_copy", "Publisher: copy A", [12, 14, 18], [17], 200, ["A", "B", "A"], ["α", "β", "γ"]),
]


def derive(trace):
    assert trace["status"] == "passed" and len(trace["requests"]) == 60
    records = trace["requests"]
    for index, r in enumerate(records):
        assert r["index"] == index
        for side in ("request", "response"):
            raw = base64.b64decode(r[side]["body_base64"], validate=True)
            assert hashlib.sha256(raw).hexdigest() == r[side]["body_sha256"]
    rows, mappings = [], []
    for name, title, captures, mutations, expected_status, bodies, aliases in SPECS:
        ids = {}
        for step, (index, body, alias) in enumerate(zip(captures, bodies, aliases)):
            r = records[index]
            request, response = r["request"], r["response"]
            url = urlsplit(request["url"])
            assert request["method"] == "GET" and not url.query
            h = {k.lower():v for k,v in response["headers"].items()}
            assert h.get("x-amz-version-id")
            raw = base64.b64decode(response["body_base64"])
            if body == "ABSENT":
                assert response["status"] == 404 and h["x-amz-delete-marker"] == "true"
            else:
                assert response["status"] == 200 and raw == (body + "\n").encode()
            version = h["x-amz-version-id"]
            if alias in ids:
                assert ids[alias] == version
            else:
                assert version not in ids.values()
                ids[alias] = version
                mappings.append({"case":name,"alias":alias,"version_id":version})
            auth = {k.lower():v for k,v in request["headers"].items()}["authorization"]
            principal = auth.split("Credential=")[1].split("/")[0]
            assert principal == ("continuity-publisher" if name.startswith("restricted") else "continuity-local-fixture")
            rows.append({"case":name,"row_title":title,"step":step,"request_index":index,
                "current_key":url.path,"principal":principal,"status":response["status"],
                "body_symbol":body,"body_sha256":response["body_sha256"],"version_alias":alias,
                "version_id":version,"read_start_ns":r["read_window_ns"][0],
                "read_end_ns":r["read_window_ns"][1]})
        assert records[mutations[-1]]["response"]["status"] == expected_status
        if name == "object_lock":
            assert records[55]["response"]["status"] == 400
            assert b"WORM protected" in base64.b64decode(records[55]["response"]["body_base64"])
            assert records[56]["response"]["status"] == 204
        if name == "restricted_delete":
            assert b"AccessDenied" in base64.b64decode(records[15]["response"]["body_base64"])
    return rows, mappings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    raw = (ROOT/"trace.json").read_bytes()
    trace = json.loads(raw)
    rows, mappings = derive(trace)
    if args.self_test:
        for alteration in ("status", "identifier", "selector", "principal"):
            broken = copy.deepcopy(trace)
            if alteration == "status":
                broken["requests"][15]["response"]["status"] = 204
            elif alteration == "identifier":
                broken["requests"][18]["response"]["headers"]["X-Amz-Version-Id"] = rows[6]["version_id"]
            elif alteration == "selector":
                broken["requests"][12]["request"]["url"] += "?versionId=old"
            else:
                broken["requests"][12]["request"]["headers"]["Authorization"] = broken["requests"][3]["request"]["headers"]["Authorization"]
            try:
                derive(broken)
            except (AssertionError, KeyError):
                continue
            raise AssertionError("Accepted corrupted " + alteration)
    for name, entries in (("plot-data.csv", rows), ("version-id-map.csv", mappings)):
        with (ROOT/name).open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(entries[0]))
            writer.writeheader(); writer.writerows(entries)
    result = {"trace_sha256":hashlib.sha256(raw).hexdigest(),"rows":len(rows),
        "unique_request_indices":sorted({r["request_index"] for r in rows}),
        "scope":"Four recorded contrasts; no frequency estimate or universal API proof."}
    (ROOT/"derivation.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
