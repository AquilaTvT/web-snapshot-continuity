"""Reproduce the four-state equality-label objective limitation.

Run from any directory:
    python3 -B /path/to/repo/scripts/check_label_objective.py

All graph paths and all 15 partitions are enumerated independently. The script
then cross-checks the repository's existing synthesis and independent checkers.
It writes JSON to stdout or to --output and does not modify the implementation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.validator_synthesis import (
    synthesize_validators, synthesize_observable_validators,
    verify_assignment, verify_lower_bound, verify_observable_synthesis,
)

NODES = ("s", "u", "v", "z")
BODIES = {"s": "A", "u": "A", "v": "A", "z": "B"}
EDGES = (("s", "u"), ("u", "v"), ("s", "z"), ("z", "v"))
QUERIES = (("s", "u"), ("u", "v"))


def all_dag_paths():
    outgoing = {n: [] for n in NODES}
    for a, b in EDGES:
        outgoing[a].append(b)
    paths = []

    def extend(path):
        paths.append(tuple(path))
        for nxt in outgoing[path[-1]]:
            if nxt in path:
                raise AssertionError("This exhaustive path oracle requires a DAG")
            extend(path + [nxt])

    for n in NODES:
        extend([n])
    return tuple(paths)


PATHS = all_dag_paths()


def paths_between(a, b):
    return tuple(p for p in PATHS if p[0] == a and p[-1] == b)


def safe_pair(a, b):
    paths = paths_between(a, b)
    # Unreachable pairs are ineligible, not vacuous positive certificates.
    return bool(paths) and BODIES[a] == BODIES[b] and all(
        all(BODIES[n] == BODIES[a] for n in p) for p in paths
    )


def partitions(prefix=()):
    """Canonical set partitions, independent of the synthesizer's search."""
    if len(prefix) == len(NODES):
        yield dict(zip(NODES, prefix))
        return
    for label in range(1, max(prefix, default=0) + 2):
        yield from partitions(prefix + (label,))


def path_safe(tags):
    for p in PATHS:
        a, b = p[0], p[-1]
        if BODIES[a] == BODIES[b] and tags[a] == tags[b]:
            if any(BODIES[n] != BODIES[a] for n in p):
                return False
    return True


def body_binding(tags):
    return all(
        tags[a] != tags[b] or BODIES[a] == BODIES[b]
        for a in NODES for b in NODES
    )


def accepted_queries(tags):
    return [list(pair) for pair in QUERIES if tags[pair[0]] == tags[pair[1]]]


def pair_relation_by_reachability(a, b):
    reach_a = {p[-1] for p in PATHS if p[0] == a}
    coreach_b = {p[0] for p in PATHS if p[-1] == b}
    return (
        b in reach_a
        and BODIES[a] == BODIES[b]
        and all(BODIES[n] == BODIES[a] for n in reach_a & coreach_b)
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    assert safe_pair("s", "u")
    assert safe_pair("u", "v")
    assert not safe_pair("s", "v")
    assert ("s", "z", "v") in PATHS
    assert len(PATHS) == 10
    for a in NODES:
        for b in NODES:
            assert pair_relation_by_reachability(a, b) == safe_pair(a, b)

    candidates = list(partitions())
    assert len(candidates) == 15
    valid_aux = [t for t in candidates if path_safe(t)]
    valid_strong = [t for t in valid_aux if body_binding(t)]
    assert len(valid_aux) == 10
    assert len(valid_strong) == 3
    assert all(not (t["s"] == t["u"] == t["v"]) for t in valid_aux)
    assert max(map(lambda t: len(accepted_queries(t)), valid_aux)) == 1
    assert min(len(set(t.values())) for t in valid_aux) == 2
    assert min(len(set(t.values())) for t in valid_strong) == 3

    for tags in candidates:
        count = len(set(tags.values()))
        assert verify_assignment(BODIES, EDGES, tags, count) == path_safe(tags)
        assert verify_assignment(BODIES, EDGES, tags, count, strong=True) == (
            path_safe(tags) and body_binding(tags)
        )

    full = synthesize_validators(BODIES, EDGES)
    assert full.feasible and full.auxiliary_tag_count == 2
    assert full.strong_tag_count == 3
    assert full.auxiliary_tags == {"s": 1, "u": 1, "v": 2, "z": 1}
    assert verify_lower_bound(BODIES, EDGES, full)
    assert verify_assignment(BODIES, EDGES, full.auxiliary_tags, 2)
    assert verify_assignment(BODIES, EDGES, full.strong_tags, 3, strong=True)

    projected = {}
    for strong in (False, True):
        result = synthesize_observable_validators(
            BODIES, EDGES, {n: n for n in NODES}, strong=strong
        )
        assert verify_observable_synthesis(
            BODIES, EDGES, {n: n for n in NODES}, result
        )
        assert result.tag_count == (3 if strong else 2)
        projected["strong" if strong else "auxiliary"] = asdict(result)

    alternative = {"s": 1, "u": 2, "v": 2, "z": 1}
    assert path_safe(alternative)
    assert verify_assignment(BODIES, EDGES, alternative, 2)
    weights = {("s", "u"): 1, ("u", "v"): 100}
    weighted = lambda t: sum(
        w for (a, b), w in weights.items() if t[a] == t[b]
    )
    assert weighted(full.auxiliary_tags) == 1
    assert weighted(alternative) == 100

    files = ("src/validator_synthesis.py",)
    report = {
        "schema": 1,
        "evidence_kind": "exhaustive_fixed_four_state_DAG_not_a_benchmark",
        "graph": {"nodes": NODES, "bodies": BODIES, "edges": EDGES},
        "all_paths": PATHS,
        "pair_checks": [
            {"pair": pair, "paths": paths_between(*pair),
             "safe": safe_pair(*pair)}
            for pair in (("s", "u"), ("u", "v"), ("s", "v"))
        ],
        "all_reachable_equal_body_pairs": [
            {"pair": [a, b], "safe": safe_pair(a, b)}
            for a in NODES for b in NODES
            if BODIES[a] == BODIES[b] and paths_between(a, b)
        ],
        "canonical_partition_count": len(candidates),
        "safe_auxiliary_partition_count": len(valid_aux),
        "safe_strong_partition_count": len(valid_strong),
        "safe_auxiliary_partitions_by_alphabet": dict(sorted(Counter(
            len(set(t.values())) for t in valid_aux).items())),
        "auxiliary_optimum": 2,
        "strong_optimum": 3,
        "max_of_two_safe_distinct_queries_accepted_by_any_equality_label": 1,
        "safe_auxiliary_partitions": [
            {"tags": t, "label_count": len(set(t.values())),
             "accepted_queries": accepted_queries(t)}
            for t in valid_aux
        ],
        "full_synthesis": asdict(full),
        "field_restricted_identity_projection": projected,
        "alternative_minimum_assignment": alternative,
        "synthetic_weighted_example": {
            "not_empirical_workload": True,
            "query_weights": [
                {"pair": p, "weight": w} for p, w in weights.items()
            ],
            "rank_assignment_score": weighted(full.auxiliary_tags),
            "alternative_assignment_score": weighted(alternative),
        },
        "checks": {
            "all_16_ordered_pairs_match_reachability_relation": True,
            "all_15_partitions_match_independent_assignment_checker": True,
            "full_and_projected_upper_lower_certificates_pass": True,
            "no_equality_partition_accepts_both_safe_pairs": True,
            "all_assertions_passed": True,
        },
        "implementation_sha256": {
            p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
            for p in files
        },
        "verifier_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    serialized = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized)
    else:
        print(serialized, end="")


if __name__ == "__main__":
    main()
