"""Record the exhaustive checks of the certification test and its hardness construction.

Runs the same independent oracles as tests/test_certification.py and writes
exact case counts with implementation hashes. Standard library only.
"""
import argparse
import hashlib
import json
import random
import sys
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fractions import Fraction  # noqa: E402
from src.certification import (Machine, Resource, certify, counterexample, exact_certainty,  # noqa: E402
                               fixed_instant, minimum_fixed_sequence_length, minimum_sequence_length,
                               one_return_machine, palindrome, schedule, sweep_certainty, three_sat_instance,
                               verify_counterexample, worst_case, worst_case_pattern)
from src.history_contracts import Contract, State, audit_contract, refine, relabel, repair  # noqa: E402
from tests.test_certification import (fixed_oracle, fresh_token_machine, oracle, reusable_machine, runs)  # noqa: E402
from tests.test_history_contracts import _set_partitions  # noqa: E402


def agree(windows, sound):
    expected = oracle(windows, sound)
    resources = runs(windows, sound)
    decision = certify(resources)
    assert decision.certified == expected, (windows, sound)
    if not decision.certified:
        assert verify_counterexample(resources, counterexample(resources))
    return expected


def random_contract(rng, deterministic, most=3):
    """A small random contract and a capture sequence that one of its paths realizes."""
    while True:
        size = rng.randrange(3, 6)
        bodies = {f"q{k}": ("x" if rng.random() < 0.6 else "off") for k in range(size)}
        targets = [q for q, b in bodies.items() if b == "x"]
        if not targets:
            continue
        labels, used = {}, set()
        for q in targets:
            if rng.random() < 0.85:
                label = rng.choice("AB")
                if deterministic and label in used:
                    continue
                labels[q] = label
                used.add(label)
        if not labels:
            continue
        edges = tuple((a, b) for a in bodies for b in bodies if a != b and rng.random() < 0.4)
        initial = tuple(rng.sample(sorted(bodies), rng.randrange(1, 3)))
        machine = Machine(bodies, labels, edges, initial, "x")
        successors = {}
        for a, b in edges:
            successors.setdefault(a, []).append(b)
        state, walk = rng.choice(initial), []
        for _ in range(12):
            walk.append(state)
            if not successors.get(state):
                break
            state = rng.choice(successors[state])
        reads = [q for q in walk if q in labels]
        if not reads:
            continue
        count = rng.randrange(1, min(most, len(reads)) + 1)
        picks = sorted(rng.sample(range(len(reads)), count))
        return machine, [labels[reads[k]] for k in picks]


def windows_for(rng, count):
    start, out = rng.randrange(0, 3), []
    for _ in range(count):
        out.append((start, start + 1))
        start += 1 + rng.randrange(1, 3)
    return out


def sweep_checks():
    """Worst-case sweep against the exponential reference semantics on random contracts."""
    rng = random.Random(20261106)
    agreed = deterministic = without = 0
    for trial in range(600):
        det = trial % 2 == 0
        n = rng.choice((2, 2, 3))
        machines, captures = [], []
        for _ in range(n):
            machine, labels = random_contract(rng, det and rng.random() < 0.9, most=3 if n == 2 else 2)
            machines.append(machine)
            captures.append(list(zip(windows_for(rng, len(labels)), labels)))
        horizon = max(w[1] for observed in captures for w, _ in observed) + 2
        fast = sweep_certainty(machines, captures, horizon)
        if all(len({q for q, l in m.labels.items()}) == len(set(m.labels.values())) for m in machines):
            deterministic += 1
            assert fast is not None, "observation-deterministic contracts always have a worst case"
        if fast is None:
            without += 1
            continue
        assert fast == exact_certainty(machines, captures, horizon), (trial, captures)
        agreed += 1
    rng = random.Random(5)
    patterns = 0
    for _ in range(3000):
        machine, labels = random_contract(rng, rng.random() < 0.5, most=4)
        observed = list(zip(windows_for(rng, len(labels)), labels))
        slow, fast = worst_case(machine, observed), worst_case_pattern(machine, observed)
        assert (slow is None) == (fast is None) and (slow is None or slow[1] == fast)
        patterns += 1
    one = one_return_machine()
    ababa = [[((1, Fraction(3, 2)), "A"), ((5, Fraction(11, 2)), "A"), ((9, Fraction(19, 2)), "A")],
             [((3, Fraction(7, 2)), "A"), ((7, Fraction(15, 2)), "A")]]
    assert worst_case(one, ababa[0]) is None and sweep_certainty([one, one], ababa, 11) is None
    assert exact_certainty([one, one], ababa, 11, step=Fraction(1, 4)) is True
    # Hardness needs hidden branches whose departure patterns are incomparable: with
    # clauses (v), (not v) the two branches of v depart in different slots and no worst case
    # exists; with (v), (v) the true branch dominates and the sweep decides the instance.
    machines, captures, horizon = three_sat_instance([(1,), (-1,)], 1)
    assert any(worst_case(m, c) is None for m, c in zip(machines, captures))
    machines, captures, horizon = three_sat_instance([(1,), (1,)], 1)
    assert all(worst_case(m, c) is not None for m, c in zip(machines, captures))
    assert sweep_certainty(machines, captures, horizon) == exact_certainty(machines, captures, horizon) is False
    return agreed, deterministic, without, patterns


def fixed_checks():
    """Fixed common instants (shared by every history) against brute force."""
    checked = fixed = 0
    for n in (1, 2, 3):
        for length in range(n, 2 * n + 1):
            for sequence in product(range(n), repeat=length):
                if set(sequence) != set(range(n)):
                    continue
                windows = schedule(sequence)
                for mask in product((True, False), repeat=n):
                    ws = [windows[i] for i in range(n)]
                    expected = fixed_oracle(ws, list(mask))
                    assert (fixed_instant([Resource(tuple(w), ok) for w, ok in zip(ws, mask)]) is not None) == expected
                    checked += 1
                    fixed += expected
    lengths = {n: minimum_fixed_sequence_length(n) for n in (1, 2, 3)}
    assert lengths == {1: 2, 2: 4, 3: 6}
    return checked, fixed, lengths


def repair_checks():
    """Some field of the state is sound iff every component with a certifiable
    state has one representation: compared with every labeling of the
    certifiable states, audited independently."""
    cases = possible = 0
    for size in (2, 3):
        names = tuple(map(str, range(size)))
        possible_edges = tuple(product(range(size), repeat=2))
        for mask in range(1 << len(possible_edges)):
            edges = tuple((names[a], names[b]) for k, (a, b) in enumerate(possible_edges) if mask >> k & 1)
            for actual in product("AB", repeat=size):
                for scope_mask in range(1, 1 << size):
                    scope = tuple(names[i] for i in range(size) if scope_mask >> i & 1)
                    contract = Contract("repair", tuple(State(names[i], actual[i], "-", actual[i])
                                                        for i in range(size)), edges,
                                        certifiable_endpoints=scope)
                    exists = any(audit_contract(relabel(contract, {n: labels.get(n, "x") for n in names})).safe
                                 for labels in _set_partitions(scope))
                    result = repair(contract)
                    assert result.possible == exists
                    if result.possible:
                        assert audit_contract(relabel(contract, result.labels)).safe
                    cases += 1
                    possible += result.possible
    return cases, possible


def refinement_checks():
    """No finite refinement that keeps every permitted path repairs a contract whose
    certifiable state lies on a cycle through another representation, and none
    breaks a contract that passes (Proposition 2(ii))."""
    rng = random.Random(1103)
    cases = failing = 0
    while cases < 2000:
        size = rng.randrange(2, 6)
        names = tuple(map(str, range(size)))
        edges = tuple((a, b) for a in names for b in names if rng.random() < 0.35)
        actual = tuple(rng.choice("AB") for _ in names)
        scope = tuple(n for n in names if rng.random() < 0.7) or (names[0],)
        contract = Contract("random", tuple(State(n, actual[i], "-", actual[i]) for i, n in enumerate(names)),
                            edges, certifiable_endpoints=scope)
        base = repair(contract).possible
        memory = rng.randrange(1, 6)
        table = {(a, b, m): rng.randrange(memory) for a, b in edges for m in range(memory)}
        assert repair(refine(contract, memory, lambda a, b, m: table[a, b, m])).possible == base
        cases += 1
        failing += not base
    s3 = Contract("s3", (State("A", "A", "vA", "A"), State("AB", "B", "vB", "B"), State("Am", "404", "-", "ABSENT")),
                  (("A", "AB"), ("AB", "A"), ("A", "Am"), ("Am", "A")), certifiable_endpoints=("A", "AB"))
    epochs = 0
    for k in range(1, 17):
        assert not repair(refine(s3, k, lambda a, b, m: (m + 1) % k)).possible
        assert not repair(refine(s3, k, lambda a, b, m: min(m + 1, k - 1))).possible
        epochs += 2
    return cases, failing, epochs


def touching_checks():
    """Windows of one resource may touch: sequential schedules without gaps for
    n = 2, 3 with every assignment of sound and reusable fields, and random
    windows whose gaps include zero, all against the brute-force oracle."""
    schedules = certified = 0
    for n in (2, 3):
        for length in range(n, 2 * n + 1):
            for sequence in product(range(n), repeat=length):
                if set(sequence) != set(range(n)):
                    continue
                windows = schedule(sequence, gap=0)
                for mask in product((True, False), repeat=n):
                    certified += agree([windows[i] for i in range(n)], list(mask))
                    schedules += 1
    rng = random.Random(20261108)
    random_cases = 0
    for _ in range(2000):
        n = rng.choice((2, 3))
        windows, sound = [], []
        for _ in range(n):
            count, start, own = rng.choice((1, 2, 3)), rng.randrange(0, 4), []
            for _ in range(count):
                length = rng.randrange(1, 3)
                own.append((start, start + length))
                start += length + rng.randrange(0, 2)
            windows.append(own)
            sound.append(rng.random() < 0.75)
        agree(windows, sound)
        random_cases += 1
    return schedules, certified, random_cases


def constructor_checks():
    """Counterexamples for many reusable reads in one window (once limited to five)."""
    sizes = (2, 6, 9, 12)
    for count in sizes:
        resources = [Resource(((0, 1),), field="reusable") for _ in range(count)]
        assert not certify(resources).certified
        assert verify_counterexample(resources, counterexample(resources))
    return list(sizes)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "data/derived/certification-audit.json")
    args = parser.parse_args()
    sequential = certified = 0
    for n in (2, 3):
        for length in range(n, 2 * n + 1):
            for sequence in product(range(n), repeat=length):
                if set(sequence) != set(range(n)):
                    continue
                windows = schedule(sequence)
                for mask in product((True, False), repeat=n):
                    certified += agree([windows[i] for i in range(n)], list(mask))
                    sequential += 1
    rng = random.Random(20261105)
    overlapping = 0
    for _ in range(4000):
        n = rng.choice((2, 3))
        windows, sound = [], []
        for _ in range(n):
            count, start, own = rng.choice((1, 2)), rng.randrange(0, 4), []
            for _ in range(count):
                length = rng.randrange(1, 3)
                own.append((start, start + length))
                start += length + rng.randrange(1, 3)
            windows.append(own)
            sound.append(rng.random() < 0.75)
        agree(windows, sound)
        overlapping += 1
    rng = random.Random(7)
    machines_checked = 0
    for _ in range(600):
        n = rng.choice((2, 3))
        sequence = [rng.randrange(n) for _ in range(rng.randrange(n, 2 * n + 1))]
        if set(sequence) != set(range(n)):
            continue
        windows = schedule(sequence)
        sound = [rng.random() < 0.7 for _ in range(n)]
        machines = [fresh_token_machine(1) if ok else reusable_machine() for ok in sound]
        captures = [[(w, "A/1" if ok else "A/h") for w in windows[i]] for i, ok in enumerate(sound)]
        horizon = max(w[1] for i in range(n) for w in windows[i]) + 2
        assert exact_certainty(machines, captures, horizon) == certify(runs([windows[i] for i in range(n)], sound)).certified
        machines_checked += 1
    literals = (1, -1, 2, -2)
    types = [(l,) for l in literals] + [(a, b) for i, a in enumerate(literals) for b in literals[i + 1:] if a != -b]
    cnf = 0
    for eps in (0.5, 0):
        for size in (1, 2):
            for clauses in product(types, repeat=size):
                satisfiable = any(all(any((l > 0) == a[abs(l) - 1] for l in c) for c in clauses)
                                  for a in product((False, True), repeat=2))
                machines, captures, horizon = three_sat_instance(list(clauses), 2, eps=eps)
                assert exact_certainty(machines, captures, horizon) == (not satisfiable)
                cnf += 1
    swept, deterministic, without, patterns = sweep_checks()
    fixed_checked, fixed_true, fixed_lengths = fixed_checks()
    repair_cases, repair_possible = repair_checks()
    constructor_sizes = constructor_checks()
    refinement_cases, refinement_failing, finite_epochs = refinement_checks()
    touching_schedules, touching_certified, touching_random = touching_checks()
    lengths = {n: minimum_sequence_length(n) for n in (1, 2, 3, 4)}
    assert lengths == {1: 1, 2: 3, 3: 5, 4: 7}
    assert minimum_sequence_length(3, sound={0, 1}) == 5 and minimum_sequence_length(3, sound={0}) is None
    for n in range(2, 9):
        assert len(palindrome(range(n))) == 2 * n - 1
    record = {
        "schema": 1,
        "implementation_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                                  for name in ("src/certification.py", "src/history_contracts.py",
                                               "tests/test_certification.py", "tests/test_history_contracts.py")},
        "sequential_schedules_vs_brute_force": sequential,
        "sequential_schedules_certified": certified,
        "random_overlapping_windows_vs_brute_force": overlapping,
        "explicit_state_machines_vs_rule": machines_checked,
        "cnf_instances_for_hardness_construction": cnf,
        "worst_case_sweep_vs_brute_force": swept,
        "worst_case_sweep_observation_deterministic": deterministic,
        "random_contracts_without_worst_case": without,
        "polynomial_worst_case_vs_enumeration": patterns,
        "one_return_contract_ababa": "certified by the reference semantics; no worst case, so outside the sweep",
        "minimum_sequential_captures": {str(k): v for k, v in lengths.items()},
        "fixed_instant_schedules_vs_brute_force": fixed_checked,
        "fixed_instant_schedules_fixing_an_instant": fixed_true,
        "minimum_sequential_captures_fixed_instant": {str(k): v for k, v in fixed_lengths.items()},
        "repair_contracts_vs_all_labelings": repair_cases,
        "repair_contracts_with_a_sound_field": repair_possible,
        "counterexample_reusable_reads_in_one_window": constructor_sizes,
        "touching_window_schedules_vs_brute_force": touching_schedules,
        "touching_window_schedules_certified": touching_certified,
        "random_touching_windows_vs_brute_force": touching_random,
        "finite_refinements_vs_component_criterion": refinement_cases,
        "finite_refinements_of_contracts_without_a_sound_field": refinement_failing,
        "s3_finite_epochs_checked": finite_epochs,
        "scope": "Finite enumerations that check the implementation and the stated proofs; they are not a proof by themselves.",
    }
    args.output.write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
