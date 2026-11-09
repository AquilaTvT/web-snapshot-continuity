"""Synthesize labels for every declared finite history contract, preserving scope."""

import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.history_contracts import Contract, State, audit_contract, verify_certificate
from src.validator_synthesis import (synthesize_validators, verify_lower_bound, verify_assignment,
    synthesize_observable_validators, verify_observable_synthesis)
from scripts.run_contracts import load_contract


def require_complete_endpoint_scope(item, state_names):
    """Reject partial scopes in either of the runner's two JSON input schemas."""
    endpoints = item.get("certifiable_endpoints")
    if endpoints is None:
        return
    if not isinstance(endpoints, list) or any(not isinstance(n, str) for n in endpoints):
        raise TypeError("JSON certifiable_endpoints must be an array of state names or null")
    if len(set(endpoints)) != len(endpoints):
        raise ValueError("certifiable endpoints must not repeat state names")
    if set(endpoints) != set(state_names):
        raise ValueError("label synthesis requires every state to be a certifiable endpoint")


def load_synthesis_contract(item):
    """The alphabet theorems require every state to be a certifiable endpoint."""
    contract = load_contract(item)
    require_complete_endpoint_scope(item, (s.name for s in contract.states))
    return contract


def projection_report(bodies, edges, observable):
    reports = {}
    for strong in (False, True):
        result = synthesize_observable_validators(bodies, edges, observable, strong=strong)
        if not verify_observable_synthesis(bodies, edges, observable, result):
            raise AssertionError("observable synthesis certificate failed")
        reports["strong" if strong else "auxiliary"] = {
            "result": asdict(result), "independent_lower_and_upper_verified": True}
    return {"observable": observable, "checks": reports}


def main():
    source = ROOT / "data/constructed/contracts.json"
    payload = source.read_bytes()
    rows = []
    for item in json.loads(payload)["models"]:
        input_contract = load_synthesis_contract(item)
        if any(s.body != s.actual for s in input_contract.states):
            rows.append({"name": item["name"], "status": "ineligible_read_fidelity",
                         "reason": "Changing a token alone cannot make a stale body a faithful origin read."})
            continue
        bodies = {s.name: s.body for s in input_contract.states}
        edges = input_contract.edges
        result = synthesize_validators(bodies, edges)
        if not verify_lower_bound(bodies, edges, result):
            raise AssertionError("lower-bound witness failed")
        checks = {}
        if result.feasible:
            for kind, tags in (("auxiliary", result.auxiliary_tags), ("strong", result.strong_tags)):
                claimed = result.strong_tag_count if kind == "strong" else result.auxiliary_tag_count
                if not verify_assignment(bodies, edges, tags, claimed, strong=kind == "strong"):
                    raise AssertionError("assignment domain, count, binding, or continuity check failed")
                contract = Contract(item["name"], tuple(State(n, b, str(tags[n]), b)
                                    for n, b in bodies.items()), edges)
                audit = audit_contract(contract)
                if not audit.safe or not verify_certificate(contract, audit.certificate):
                    raise AssertionError("synthesized assignment violates the continuity contract")
                checks[kind] = {"assigned_distinct_labels": len(set(tags.values())),
                                "domain_count_binding_and_continuity_verified": True,
                                "audit": asdict(audit)}
        policies = {"full_state": {n: n for n in bodies},
                    "body_and_validator": {s["name"]: json.dumps([s["body"], s["validator"]],
                                                              separators=(",", ":"))
                                           for s in item["states"]}}
        projections = {name: projection_report(bodies, edges, observable)
                       for name, observable in policies.items()}
        rows.append({"name": item["name"], "status": "feasible" if result.feasible else "fixed_state_impossible",
            "scope": item["scope"], "result": asdict(result), "assignment_checks": checks,
            "observable_synthesis": projections})
    examples_source = ROOT / "data/constructed/validator-projections.json"
    examples_payload = examples_source.read_bytes()
    examples = []
    for example in json.loads(examples_payload)["models"]:
        bodies, edges, observable = example["bodies"], tuple(map(tuple, example["edges"])), example["observable"]
        require_complete_endpoint_scope(example, bodies)
        full = synthesize_validators(bodies, edges)
        if not verify_lower_bound(bodies, edges, full):
            raise AssertionError("example full-state lower bound failed")
        if full.feasible and not all((
            verify_assignment(bodies, edges, full.auxiliary_tags, full.auxiliary_tag_count),
            verify_assignment(bodies, edges, full.strong_tags, full.strong_tag_count, strong=True))):
            raise AssertionError("example full-state upper bound failed")
        examples.append({"name": example["name"], "scope": example["scope"],
                         "full_state": asdict(full),
                         "restricted_observable": projection_report(bodies, edges, observable)})
    report = {"schema": 2, "input_sha256": hashlib.sha256(payload).hexdigest(),
              "projection_examples_sha256": hashlib.sha256(examples_payload).hexdigest(),
              "evidence_kind": "constructed_finite_state_label_synthesis",
              "semantics": "Auxiliary tags compare together with bodies; strong tags additionally separate different bodies. Every supplied state must be distinguishable by the labeling implementation. No history state is added; model nodes may themselves encode history that a real implementation does not expose.",
              "projection_semantics": "Restricted labels are deterministic functions of the supplied observable tuple. A self-loop is a certified obstruction; otherwise an exact coloring is certified by a separate continuity audit and an exhaustive canonical-prefix proof for one fewer color. These are constructed models, not production availability measurements.",
              "results": rows, "projection_examples": examples}
    output = ROOT / "data/derived/validator-synthesis.json"
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"models": len(rows), "feasible": sum(r["status"] == "feasible" for r in rows),
                      "fixed_state_impossible": sum(r["status"] == "fixed_state_impossible" for r in rows),
                      "read_fidelity_ineligible": sum(r["status"] == "ineligible_read_fidelity" for r in rows),
                      "existing_fields_feasible": sum(r.get("observable_synthesis", {}).get("body_and_validator", {})
                            .get("checks", {}).get("auxiliary", {}).get("result", {}).get("feasible", False) for r in rows),
                      "projection_examples": len(examples)}))


if __name__ == "__main__":
    main()
