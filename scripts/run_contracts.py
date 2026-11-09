"""Recompute every finite-contract verdict, witness, and safety certificate."""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.history_contracts import Contract, State, audit_contract, verify_certificate, verify_witness


def load_contract(item):
    """Load a JSON contract without silently discarding its endpoint scope."""
    endpoints = item.get("certifiable_endpoints")
    if endpoints is not None and not isinstance(endpoints, list):
        raise TypeError("JSON certifiable_endpoints must be an array or null")
    contract = Contract(item["name"], tuple(State(**s) for s in item["states"]),
                        tuple(map(tuple, item["edges"])), item["context"],
                        None if endpoints is None else tuple(endpoints))
    contract.checked()
    return contract


def main():
    path = ROOT / "data/constructed/contracts.json"
    source = path.read_bytes()
    specification = json.loads(source)
    results, summary = [], []
    for item in specification["models"]:
        contract = load_contract(item)
        audit = audit_contract(contract)
        verified = (verify_certificate(contract, audit.certificate) if audit.safe
                    else verify_witness(contract, audit))
        if not verified or audit.safe != item["expected_safe"]:
            raise AssertionError(f"contract check failed: {contract.name}")
        by_name = {s.name: asdict(s) for s in contract.states}
        results.append({"name": contract.name, "evidence_kind": "constructed_finite_contract",
            "scope": item["scope"], "explanation": item["explanation"],
            "audit": asdict(audit), "independently_verified": verified,
            "witness_states": [by_name[n] for n in audit.witness]})
        summary.append({"name": contract.name, "states": len(contract.states),
            "edges": len(set(contract.edges)), "safe_in_model": audit.safe,
            "failure": audit.failure or "none",
            "shortest_counterexample_edges": "" if audit.safe else len(audit.witness)-1,
            "certificate_labels": len(audit.certificate), "verified": verified})
    derived = ROOT / "data/derived"
    derived.mkdir(parents=True, exist_ok=True)
    report = {"schema": 1, "input": "data/constructed/contracts.json",
              "input_sha256": hashlib.sha256(source).hexdigest(),
              "interpretation": "Exact verdicts for declared finite transition models; not measurements of deployed systems.",
              "results": results}
    (derived / "contracts-results.json").write_text(json.dumps(report, indent=2) + "\n")
    with (derived / "contracts-summary.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(summary[0]))
        writer.writeheader()
        writer.writerows(summary)
    print(json.dumps({"models": len(summary), "safe": sum(x["safe_in_model"] for x in summary),
                      "verified": all(x["verified"] for x in summary)}))


if __name__ == "__main__":
    main()
