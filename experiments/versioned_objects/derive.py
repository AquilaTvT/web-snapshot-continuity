"""Derive scoped continuity checks from run_minio.py's actual HTTP trace.

No HTTP traffic or server behavior is simulated here. Recorded-path models and
declared API reactivation obstructions are separate evidence classes. In the
latter, an unread internal state's token is explicitly not an observed ID.
"""

from __future__ import annotations

import argparse
import base64
import csv
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.history_contracts import (Contract, State, audit_contract,
    certified_read_bridge, verify_certificate, verify_witness)

NAMES = ("delete_current", "copy_restore", "reupload_restore", "delete_marker",
         "pinned_selector", "two_object_bundle")
INTERNAL_TOKEN = "model-only: internal state has no observed/used version token"
ABSENCE = "model-meaning: no current representation (HTTP 404 delete marker)"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON member: {key}")
        result[key] = value
    return result


def headers(record, side="response"):
    result = {}
    for key, value in record[side]["headers"].items():
        lower = key.lower()
        require(lower not in result, f"duplicate case-insensitive header: {key}")
        result[lower] = value
    return result


def version(record):
    return headers(record).get("x-amz-version-id")


def body(record):
    return base64.b64decode(record["response"]["body_base64"], validate=True)


def body_symbol(record):
    # Exact bytes, not a hash equality assumption. Error XML is not an object.
    if record["response"]["status"] == 200:
        return "object-bytes-base64:" + base64.b64encode(body(record)).decode()
    require(record["response"]["status"] == 404 and
            headers(record).get("x-amz-delete-marker") == "true",
            "only a documented current-delete-marker 404 is an internal absence")
    return ABSENCE


def resource(record):
    request = record["request"]
    require(request["method"] == "GET", "observations must be actual GETs")
    url = urlsplit(request["url"])
    require(not url.fragment, "request fragment is unsupported")
    query = sorted(parse_qsl(url.query, keep_blank_values=True))
    h = headers(record, "request")
    return {"url": urlunsplit((url.scheme, url.netloc, url.path, urlencode(query), "")),
            "query": query,
            "request_fields": {key: h.get(key) for key in
                               ("accept", "accept-encoding", "range")},
            "principal_scope": "one run_minio fixture principal"}


def selected(record):
    return any(key == "versionId" for key, _ in resource(record)["query"])


def state(record):
    symbol = body_symbol(record)
    return State("request_" + str(record["index"]), symbol,
                 version(record) or INTERNAL_TOKEN, symbol)


def recorded_path(name, records):
    require(bool(records), "empty observation path")
    context = resource(records[0])
    require(all(resource(record) == context for record in records),
            "different resource selectors/request contexts cannot share a path")
    require(all(a["index"] < b["index"] for a, b in zip(records, records[1:])),
            "recorded paths must follow request order")
    states = tuple(state(record) for record in records)
    edges = tuple((a.name, b.name) for a, b in zip(states, states[1:]))
    # Residence/stuttering does not imply that unseen API operations are covered.
    edges += tuple((s.name, s.name) for s in states)
    endpoints = tuple(s.name for s, record in zip(states, records)
                      if record["response"]["status"] == 200)
    require(all(version(record) for record in records
                if record["response"]["status"] == 200),
            "every successful certifiable observation needs its native version ID")
    contract = Contract(name, states, edges, json.dumps(context, sort_keys=True), endpoints)
    return contract, {"evidence_class": "finite_recorded_path",
        "source_records": [r["index"] for r in records], "resource": context,
        "scope": "Only this ordered, controlled observation path with stuttering; "
                 "a positive verdict is not an API-wide contract or an inference "
                 "that point observations alone exclude missing changes."}


def reactivation_obstruction(name, endpoint, different_body, supporting_records):
    require(endpoint["response"]["status"] == 200 and version(endpoint),
            "reactivation endpoints need an observed successful native ID")
    require(not selected(endpoint), "current-key obstruction cannot audit a pinned URL")
    target = body_symbol(endpoint)
    require(target != different_body, "reactivation needs a distinct internal body")
    states = (State("selected_before", target, version(endpoint), target),
              State("different_current", different_body, INTERNAL_TOKEN, different_body),
              State("selected_again", target, version(endpoint), target))
    contract = Contract(name, states,
        (("selected_before", "different_current"), ("different_current", "selected_again")),
        json.dumps(resource(endpoint), sort_keys=True), ("selected_before", "selected_again"))
    return contract, {"evidence_class": "declared_api_reactivation_obstruction",
        "resource": resource(endpoint), "endpoint_record": endpoint["index"],
        "supporting_executed_operation_records": supporting_records,
        "scope": "A counterexample pattern allowed by an unrestricted current-key "
                 "mutation contract: select this retained version, create a different "
                 "current version, then delete that new version. This submodel "
                 "refutes the universal equality rule; it does not enumerate the API "
                 "or assert that this sequence occurred between these captures.",
        "internal_token": "No intermediate native ID is invented. This unread, "
                          "non-certifiable state's placeholder is model notation only.",
        "operation_source": "https://docs.aws.amazon.com/AmazonS3/latest/userguide/RestoringPreviousVersions.html"}


def checked_model(contract, provenance):
    audit = audit_contract(contract)
    verified = (verify_certificate(contract, audit.certificate) if audit.safe
                else verify_witness(contract, audit))
    require(verified, "independent verification failed: " + contract.name)
    by_name = {s.name: asdict(s) for s in contract.states}
    model = {"name": contract.name, **provenance, "contract": asdict(contract)}
    result = {"name": contract.name, "evidence_class": provenance["evidence_class"],
        "audit": asdict(audit), "independent_verification": {
            "kind": "invariant_closure" if audit.safe else "concrete_path_edges_and_body_departure",
            "passed": verified, "shortestness_independently_checked": False},
        "witness_states": [by_name[n] for n in audit.witness]}
    return model, result


def compare(first, last):
    same_resource = resource(first) == resource(last)
    eligible = first["response"]["status"] == last["response"]["status"] == 200
    same_body = body(first) == body(last)
    same_id = version(first) == version(last) and bool(version(first))
    equal = same_resource and eligible and same_body and same_id
    bridge = certified_read_bridge(tuple(first["read_window_ns"]),
                                   tuple(last["read_window_ns"])) if equal else None
    return {"first_record": first["index"], "last_record": last["index"],
        "resource": resource(first), "same_resource": same_resource,
        "eligible_200_endpoints": eligible, "exact_endpoint_bytes_equal": same_body,
        "first_version_id": version(first), "last_version_id": version(last),
        "native_version_ids_equal": same_id,
        "raw_equality_baseline_accepts": bool(bridge), "baseline_bridge_ns": bridge,
        "baseline_status": "Research baseline only: it assumes equality implies "
                           "continuity; this is not an identified archive implementation."}


def check_single_operations(name, first, middle, last, records):
    mutations = [r for r in records if first["index"] < r["index"] < last["index"]
                 and r["request"]["method"] != "GET"]
    expected = (["DELETE", "DELETE"] if name == "delete_marker" else
                ["PUT"] if name == "pinned_selector" else
                ["PUT", "DELETE"] if name == "delete_current" else ["PUT", "PUT"])
    require([r["request"]["method"] for r in mutations] == expected,
            "unexpected mutation sequence: " + name)
    path = urlsplit(first["request"]["url"]).path
    require(all(urlsplit(r["request"]["url"]).path == path for r in mutations),
            "single-object mutation changes a different key")
    require(all(r["response"]["status"] == (204 if r["request"]["method"] == "DELETE" else 200)
                for r in mutations), "mutation did not acknowledge the expected result")
    first_mutation = mutations[0]
    if name == "delete_marker":
        require(not parse_qsl(urlsplit(first_mutation["request"]["url"]).query, keep_blank_values=True),
                "marker creation must be an unqualified DELETE")
        require(headers(first_mutation).get("x-amz-delete-marker") == "true"
                and bool(version(first_mutation)), "missing delete-marker allocation identity")
        require(version(middle) is None or version(first_mutation) == version(middle),
                "404 names a different delete marker")
    else:
        require(base64.b64decode(first_mutation["request"]["body_base64"], validate=True) == body(middle)
                and version(first_mutation) == version(middle), "intermediate GET differs from acknowledged PUT")
    if name in ("delete_current", "delete_marker"):
        removed_id = version(first_mutation) if name == "delete_marker" else version(middle)
        require(parse_qsl(urlsplit(mutations[-1]["request"]["url"]).query, keep_blank_values=True)
                == [("versionId", removed_id)], "restore DELETE does not select the intervening version")
    elif name == "copy_restore":
        copy_source = headers(mutations[-1], "request").get("x-amz-copy-source", "")
        require(urlsplit(copy_source).path == path and
                parse_qsl(urlsplit(copy_source).query, keep_blank_values=True) == [("versionId", version(first))],
                "copy restore does not select the original version")
        require(version(mutations[-1]) == version(last), "copy allocation and final ID differ")
    elif name == "reupload_restore":
        require(base64.b64decode(mutations[-1]["request"]["body_base64"], validate=True) == body(first)
                and version(mutations[-1]) == version(last), "reupload does not restore the observed bytes")
    return [r["index"] for r in mutations]


def validate_trace(trace):
    require(trace.get("format_version") == 1 and trace.get("status") == "passed",
            "a successful run_minio format_version=1 trace is required")
    records = trace["requests"]
    require(isinstance(records, list) and records, "no HTTP records")
    previous_end = -1
    for index, record in enumerate(records):
        require(type(record["index"]) is int and record["index"] == index,
                "HTTP record indices must be consecutive")
        window = record["read_window_ns"]
        require(len(window) == 2 and all(type(t) is int for t in window)
                and previous_end <= window[0] <= window[1],
                "request windows must be serialized on one monotone clock")
        previous_end = window[1]
        for side in ("request", "response"):
            raw = base64.b64decode(record[side]["body_base64"], validate=True)
            require(sha(raw) == record[side]["body_sha256"], "body SHA-256 mismatch")
            headers(record, side)
        require(type(record["response"]["status"]) is int, "HTTP status must be integer")
    cases = {case["name"]: case for case in trace["cases"]}
    require(len(cases) == len(trace["cases"]) and set(cases) == set(NAMES),
            "the six declared runner cases are required exactly once")
    for name, case in cases.items():
        indices = case["captures"]
        require(len(indices) == (4 if name == "two_object_bundle" else 3), "unexpected capture count")
        require(all(type(i) is int and 0 <= i < len(records) for i in indices)
                and indices == sorted(set(indices)), "invalid capture indices")
        for i in indices:
            resource(records[i])
    return records, cases


def derive(trace, trace_bytes):
    records, cases = validate_trace(trace)
    models, audits, results, rows, observations = [], [], [], [], []
    aliases = {}
    for record in records:
        value = version(record)
        if value and value not in aliases:
            aliases[value] = {"alias": f"v{len(aliases)}", "native_version_id": value,
                              "first_response_record": record["index"]}

    def add_model(pair):
        model, audit = checked_model(*pair)
        models.append(model); audits.append(audit)
        return audit

    def add_observations(case, role, selected_records):
        for record in selected_records:
            observations.append({"case": case, "role": role, "record": record["index"],
                "resource": resource(record)["url"], "status": record["response"]["status"],
                "native_version_id": version(record) or "", "version_alias": aliases.get(version(record), {}).get("alias", ""),
                "body_base64": record["response"]["body_base64"], "body_sha256": record["response"]["body_sha256"],
                "window_start_ns": record["read_window_ns"][0], "window_end_ns": record["read_window_ns"][1]})

    for name in NAMES[:-1]:
        case_records = [records[i] for i in cases[name]["captures"]]
        first, middle, last = case_records
        mutation_records = check_single_operations(name, first, middle, last, records)
        comparison = compare(first, last)
        require(comparison["same_resource"] and comparison["eligible_200_endpoints"]
                and comparison["exact_endpoint_bytes_equal"], "unexpected single-case endpoints")
        excluded = []
        if name == "pinned_selector":
            require(selected(first) and selected(last) and not selected(middle)
                    and resource(first) != resource(middle), "pinned/current distinction missing")
            path_records = [first, last]
            excluded = [middle["index"]]
            require(body(first) != body(middle), "pinned selector control must differ from current")
        else:
            require(all(not selected(r) for r in case_records), "current case has a version selector")
            path_records = case_records
            require(body_symbol(first) != body_symbol(middle), "missing intervening departure")
        audit = add_model(recorded_path(name + ":recorded", path_records))
        expected_equal = name in ("delete_current", "delete_marker", "pinned_selector")
        require(comparison["native_version_ids_equal"] == expected_equal, "unexpected endpoint ID behavior")
        require(audit["audit"]["safe"] == (name not in ("delete_current", "delete_marker")),
                "unexpected recorded-path contract verdict")
        decision = ("abstain: concrete reactivation refutes current-key equality contract"
                    if name in ("delete_current", "delete_marker") else
                    "no bridge: native endpoint IDs differ; no global API conclusion"
                    if name != "pinned_selector" else
                    "scope-limited bridge for retained pinned resource; no current-key claim")
        result = {"name": name, "comparison": comparison,
            "checked_mutation_records": mutation_records,
            "recorded_model": audit["name"], "recorded_path_safe": audit["audit"]["safe"],
            "excluded_other_resource_records": excluded,
            "checked_decision": decision,
            "checked_bridge_ns": comparison["baseline_bridge_ns"] if name == "pinned_selector" else None,
            "checked_bridge_scope": ("Declared retained-version fixture path, not a "
                 "conclusion from two point reads or a complete provider API proof") if name == "pinned_selector" else None,
            "observed_departure_in_compared_resource_context": name != "pinned_selector",
            "other_current_resource_control_record": middle["index"] if name == "pinned_selector" else None,
            "observed_current_control_differs_from_pinned_body": True if name == "pinned_selector" else None,
            "api_wide_safety_established": False}
        results.append(result)
        add_observations(name, "capture_or_intermediate", case_records)
        rows.append({"case": name, "resource": comparison["resource"]["url"],
            "first_record": first["index"], "last_record": last["index"],
            "first_version_id": version(first), "last_version_id": version(last),
            "first_alias": aliases[version(first)]["alias"], "last_alias": aliases[version(last)]["alias"],
            "same_bytes": True, "same_id": comparison["native_version_ids_equal"],
            "recorded_path_safe": audit["audit"]["safe"],
            "baseline_accepts": comparison["raw_equality_baseline_accepts"],
            "checked_decision": decision, "independently_verified": True})

    bundle = cases["two_object_bundle"]
    a1, b1, b2, a2 = [records[i] for i in bundle["captures"]]
    require(len(bundle["phases"]) == 5, "bundle needs five stable phase readbacks")
    target = tuple(value.encode() for value in bundle["target"])
    require(len(target) == 2 and (body(a1), body(b1)) == target, "target differs from captures")
    phase_records, phase_rows = [], []
    previous = -1
    for number, phase in enumerate(bundle["phases"]):
        indices = phase["observations"]
        require(len(indices) == 2 and all(type(i) is int and 0 <= i < len(records) for i in indices),
                "invalid phase observation references")
        a, b = [records[i] for i in indices]
        require(previous < a["index"] < b["index"], "phase readbacks out of order")
        previous = b["index"]
        require(resource(a) == resource(a1) and resource(b) == resource(b1)
                and a["response"]["status"] == b["response"]["status"] == 200,
                "phase uses wrong resources or incomplete responses")
        pair = (body(a), body(b))
        require(pair != target, "target actually occurs in a recorded stable phase")
        phase_records.append((a, b))
        phase_rows.append({"phase": number, "label": phase["label"],
            "admission_record": a["index"], "fee_record": b["index"],
            "admission_body_base64": a["response"]["body_base64"], "fee_body_base64": b["response"]["body_base64"],
            "admission_version_id": version(a), "fee_version_id": version(b),
            "target_present": False})
        add_observations("two_object_bundle", "phase_" + str(number), [a, b])
    # Check the complete ordering that makes the two-key trajectory a counterexample.
    p = phase_records
    require(p[0][1]["index"] < a1["index"] < p[1][0]["index"] and
            p[2][1]["index"] < b1["index"] < b2["index"] < p[3][0]["index"] and
            p[4][1]["index"] < a2["index"], "bundle capture/phase schedule differs")
    expected_pairs = [(body(p[0][0]), body(p[0][1])),
                      (body(p[1][0]), body(p[0][1])),
                      (body(p[1][0]), body(p[2][1])),
                      (body(p[1][0]), body(p[0][1])),
                      (body(p[0][0]), body(p[0][1]))]
    require([(body(a), body(b)) for a, b in p] == expected_pairs and
            body(p[0][0]) != body(p[1][0]) and body(p[0][1]) != body(p[2][1]),
            "bundle must change A, change B, restore B, then restore A")
    # Readback pairs are not atomic snapshots. The runner's serialized one-key
    # mutations and the absence of intervening writers justify each stable pair.
    mutations = [r for r in records if a1["index"] < r["index"] < a2["index"]
                 and r["request"]["method"] != "GET"]
    require([r["request"]["method"] for r in mutations] == ["PUT", "PUT", "DELETE", "DELETE"],
            "unexpected mutations within the bundle capture window")
    require([urlsplit(r["request"]["url"]).path for r in mutations] ==
            [urlsplit(a1["request"]["url"]).path, urlsplit(b1["request"]["url"]).path,
             urlsplit(b1["request"]["url"]).path, urlsplit(a1["request"]["url"]).path],
            "bundle mutations are not A,B,B,A")
    require(all(r["response"]["status"] in (200, 204) for r in mutations), "unacknowledged mutation")
    for put, readback in ((mutations[0], p[1][0]), (mutations[1], p[2][1])):
        require(base64.b64decode(put["request"]["body_base64"], validate=True) == body(readback)
                and version(put) == version(readback), "bundle PUT differs from phase readback")
    for deletion, put in ((mutations[2], mutations[1]), (mutations[3], mutations[0])):
        require(parse_qsl(urlsplit(deletion["request"]["url"]).query, keep_blank_values=True)
                == [("versionId", version(put))], "bundle DELETE selects the wrong current version")
    require(version(p[0][0]) == version(p[4][0]) == version(a1) == version(a2)
            and version(p[0][1]) == version(p[3][1]) == version(p[4][1])
            and version(p[2][1]) == version(b1) == version(b2),
            "bundle restored-phase IDs disagree with the client captures")
    for a, b in p:
        require(not any(a["index"] < r["index"] < b["index"] for r in mutations),
                "a phase readback pair straddles a mutation")

    components = []
    source_captures = cases["delete_current"]["captures"]
    support = list(range(source_captures[0], source_captures[-1] + 1))
    for column, first, last, label in ((0, a1, a2, "admission"), (1, b1, b2, "fee")):
        comparison = compare(first, last)
        require(comparison["raw_equality_baseline_accepts"], "four bundle captures must repeat IDs and bytes")
        all_component = sorted({r["index"]: r for r in [first, last] +
            [pair[column] for pair in p]}.values(), key=lambda r: r["index"])
        finite = add_model(recorded_path("bundle:" + label + ":recorded", all_component))
        capture_slice = [r for r in all_component if first["index"] <= r["index"] <= last["index"]]
        slice_audit = add_model(recorded_path("bundle:" + label + ":capture_window", capture_slice))
        different = next(body_symbol(r) for r in all_component if body_symbol(r) != body_symbol(first))
        obstruction = add_model(reactivation_obstruction("bundle:" + label + ":api_obstruction", first, different, support))
        require(not obstruction["audit"]["safe"], "reactivation submodel must refute equality")
        components.append({"resource_role": label, "comparison": comparison,
            "full_recorded_model": finite["name"], "capture_window_model": slice_audit["name"],
            "recorded_capture_window_safe": slice_audit["audit"]["safe"],
            "api_obstruction_model": obstruction["name"], "checked_bridge_ns": None,
            "checked_decision": "abstain under unrestricted current-key mutation scope",
            "actual_interruption_between_captures": any(body_symbol(r) != body_symbol(first) for r in capture_slice)})
    left, right = [c["comparison"]["baseline_bridge_ns"] for c in components]
    overlap = [max(left[0], right[0]), min(left[1], right[1])]
    require(overlap[0] < overlap[1], "baseline bridges do not overlap")
    require(not components[0]["recorded_capture_window_safe"] and components[1]["recorded_capture_window_safe"],
            "bundle should interrupt A while B's observed capture window is stable")
    bundle_result = {"name": "two_object_bundle", "target_body_base64": [base64.b64encode(v).decode() for v in target],
        "captures": bundle["captures"], "components": components,
        "baseline_common_time_interval_ns": overlap, "baseline_claims_common_time": True,
        "target_present_in_any_of_five_stable_phases": False,
        "checked_common_time_claim": False, "checked_decision": "abstain: native current-key ID does not supply the required contract",
        "ground_truth_scope": "Actual controlled runner: one writer, acknowledged one-key mutations in A,B,B,A order, "
            "no concurrent writers, and readback of every stable phase. Pair reads themselves are not atomic.",
        "api_model_scope": "Declared reactivation submodels refute equality contracts. No complete API-positive proof is inferred.",
        "mutations": [r["index"] for r in mutations]}
    results.append(bundle_result)
    add_observations("two_object_bundle", "client_capture", [a1, b1, b2, a2])
    rows.append({"case": "two_object_bundle", "resource": "two current-key resources; see results.json", "first_record": a1["index"],
        "last_record": a2["index"], "first_version_id": version(a1), "last_version_id": version(a2),
        "first_alias": aliases[version(a1)]["alias"], "last_alias": aliases[version(a2)]["alias"],
        "same_bytes": True, "same_id": True, "recorded_path_safe": False,
        "baseline_accepts": True, "checked_decision": bundle_result["checked_decision"], "independently_verified": True})
    return {"format_version": 1, "status": "passed", "trace_sha256": sha(trace_bytes),
        "server": trace["server"], "server_sha256": trace["server_sha256"], "transport": trace["transport"],
        "provenance": {"derive_sha256": sha(Path(__file__).read_bytes()),
            "contract_source_sha256": sha((ROOT / "src/history_contracts.py").read_bytes())},
        "interpretation": "Recorded-path checks and declared API obstructions are separate; no production frequency or AWS/GCS execution is claimed.",
        "cases": results}, models, audits, rows, observations, phase_rows, list(aliases.values())


def self_test():
    # Small semantic checks only; these are not fabricated HTTP measurements.
    a = State("a", "A", "id-a", "A")
    absent = State("missing", "error XML", INTERNAL_TOKEN, "ABSENT")
    end = State("c", "A", "id-a", "A")
    contract = Contract("absence", (a, absent, end), (("a", "missing"), ("missing", "c")),
                        "unit model", ("a", "c"))
    audit = audit_contract(contract)
    require(not audit.safe and audit.witness == ("a", "missing", "c") and verify_witness(contract, audit),
            "non-certifiable absence must remain inside a witness")
    require(not verify_witness(contract, replace(audit, witness=("a", "c"))), "missing-edge witness accepted")
    changed = replace(contract, states=(a, absent, replace(end, validator="new-id")))
    positive = audit_contract(changed)
    require(positive.safe and verify_certificate(changed, positive.certificate), "distinct endpoints should pass this finite path")
    require(not verify_certificate(changed, positive.certificate[:-1]), "incomplete invariant accepted")
    require(certified_read_bridge((1, 2), (5, 6)) == (2, 5), "positive bridge")
    require(certified_read_bridge((1, 5), (4, 6)) is None, "overlapping windows")
    require(audit_contract(replace(contract, certifiable_endpoints=())).safe, "empty endpoint scope")
    # An empty endpoint scope is not used for any client bridge in derive().
    print(json.dumps({"status": "passed", "checks": 7,
                      "scope": "unit graph/interval logic only; no HTTP/server experiment"}))


def write_csv(path, rows):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        require(args.trace is None and args.output is None, "self-test does not derive measurements")
        self_test(); return
    if args.trace is None or args.output is None:
        parser.error("--trace and --output are required unless --self-test is used")
    source = args.trace.read_bytes()
    trace = json.loads(source, object_pairs_hook=unique_object)
    result, models, audits, rows, observations, phases, aliases = derive(trace, source)
    args.output.mkdir(parents=True, exist_ok=True)
    for name, value in (("results.json", result), ("models.json", {"trace_sha256": sha(source), "models": models}),
                        ("audit.json", {"trace_sha256": sha(source), "results": audits})):
        (args.output / name).write_text(json.dumps(value, indent=2) + "\n")
    for name, value in (("summary.csv", rows), ("observations.csv", observations),
                        ("phases.csv", phases), ("version-id-map.csv", aliases)):
        write_csv(args.output / name, value)
    print(json.dumps({"status": "passed", "cases": len(result["cases"]), "models": len(models),
                      "independently_verified": len(audits), "trace_sha256": sha(source)}))


if __name__ == "__main__":
    main()
