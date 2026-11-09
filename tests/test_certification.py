import random
import sys
import unittest
from fractions import Fraction
from itertools import product
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.certification import (Machine, Resource, _violating_pair, certify, counterexample, exact_certainty,
                               fixed_instant, minimum_fixed_sequence_length, minimum_sequence_length,
                               one_return_machine, palindrome, schedule, sweep_certainty, three_sat_instance,
                               verify_counterexample, worst_case, worst_case_pattern)

HALF = Fraction(1, 2)


def grid(window):
    start, end = Fraction(window[0]), Fraction(window[1])
    points, t = [], start
    while t <= end:
        points.append(t)
        t += HALF
    return points


def oracle(windows_by_resource, sound):
    """Brute force over read instants; does not use the pairwise rule.

    A sound resource is certainly present on [first instant, last instant]; a
    reusable one only at its instants. A common instant exists for a choice
    iff some chosen instant lies in every resource's presence set.
    """
    choices = []
    for windows in windows_by_resource:
        options = [p for p in product(*(grid(w) for w in windows)) if all(a < b for a, b in zip(p, p[1:]))]
        choices.append(options)
    for joint in product(*choices):
        def present(i, t):
            times = joint[i]
            if sound[i]:
                return times[0] <= t <= times[-1]
            return t in times
        candidates = {t for times in joint for t in times}
        if not any(all(present(i, t) for i in range(len(joint))) for t in candidates):
            return False
    return True


def fixed_oracle(windows_by_resource, sound):
    """Brute force for a fixed common instant: some grid instant t is common in
    every choice of read instants. Independent of fixed_instant()."""
    choices = []
    for windows in windows_by_resource:
        choices.append([p for p in product(*(grid(w) for w in windows)) if all(a < b for a, b in zip(p, p[1:]))])
    low = min(Fraction(w[0]) for ws in windows_by_resource for w in ws)
    high = max(Fraction(w[1]) for ws in windows_by_resource for w in ws)
    instants, t = [], low
    while t <= high:
        instants.append(t)
        t += HALF / 2
    def common(t, joint):
        return all((times[0] <= t <= times[-1]) if sound[i] else (t in times) for i, times in enumerate(joint))
    return any(all(common(t, joint) for joint in product(*choices)) for t in instants)


def runs(windows_by_resource, sound):
    result = []
    for windows, ok in zip(windows_by_resource, sound):
        if ok and len(windows) > 1:
            result.append(Resource((windows[0], windows[-1]), True))
        else:
            result.append(Resource(tuple(windows), ok))
    return result


class CertificationTest(unittest.TestCase):
    def check(self, windows_by_resource, sound):
        expected = oracle(windows_by_resource, sound)
        resources = runs(windows_by_resource, sound)
        decision = certify(resources)
        self.assertEqual(decision.certified, expected, (windows_by_resource, sound, decision))
        if not decision.certified:
            self.assertTrue(verify_counterexample(resources, counterexample(resources)))
        return expected

    def test_all_sequential_schedules_against_brute_force(self):
        checked = 0
        for n in (2, 3):
            for length in range(n, 2 * n + 1):
                for sequence in product(range(n), repeat=length):
                    if set(sequence) != set(range(n)):
                        continue
                    windows = schedule(sequence)
                    for mask in product((True, False), repeat=n):
                        self.check([windows[i] for i in range(n)], list(mask))
                        checked += 1
        self.assertEqual(checked, 5944)

    def test_random_overlapping_windows_against_brute_force(self):
        rng = random.Random(20261105)
        certified = 0
        for _ in range(4000):
            n = rng.choice((2, 3))
            windows_by_resource, sound = [], []
            for _ in range(n):
                count = rng.choice((1, 2))
                start = rng.randrange(0, 4)
                windows = []
                for _ in range(count):
                    length = rng.randrange(1, 3)
                    windows.append((start, start + length))
                    start += length + rng.randrange(1, 3)
                windows_by_resource.append(windows)
                sound.append(rng.random() < 0.75)
            certified += self.check(windows_by_resource, sound)
        self.assertGreater(certified, 200)

    def test_optimal_schedule_length_is_2n_minus_1(self):
        self.assertEqual([minimum_sequence_length(n) for n in (1, 2, 3, 4)], [1, 3, 5, 7])
        self.assertEqual(minimum_sequence_length(3, sound={0, 1}), 5)
        self.assertIsNone(minimum_sequence_length(3, sound={0}))
        for n in range(2, 9):
            order = palindrome(range(n))
            self.assertEqual(len(order), 2 * n - 1)
            windows = schedule(order)
            self.assertTrue(certify(runs([windows[i] for i in range(n)], [True] * n)).certified)
            # The singly read middle resource may be reusable.
            self.assertTrue(certify(runs([windows[i] for i in range(n)],
                                         [True] * (n - 1) + [False])).certified)

    def test_touching_windows_share_a_certain_instant(self):
        # Windows of one resource may touch. With sound fields the closed bridge
        # is the shared endpoint, and it is common to every history: the two
        # reads lie on either side of it.
        resources = [Resource(((0, 1), (3, 4))), Resource(((1, 2), (2, 3)))]
        decision = certify(resources)
        self.assertTrue(decision.certified)
        self.assertEqual(decision.interval, (Fraction(2), Fraction(2)))
        self.assertEqual(fixed_instant(resources), (Fraction(2), Fraction(2)))
        self.assertTrue(oracle([[(0, 1), (3, 4)], [(1, 2), (2, 3)]], [True, True]))
        # A refusal whose witness must keep the reads of a touching pair apart.
        refused = [Resource(((0, 1), (1, 2))), Resource(((3, 4),))]
        self.assertFalse(certify(refused).certified)
        example = counterexample(refused)
        self.assertTrue(verify_counterexample(refused, example))
        self.assertLess(example.instants[0][0], example.instants[0][1])

    def test_positive_windows_and_order_are_required(self):
        with self.assertRaises(ValueError):
            certify([Resource(((1, 1),)), Resource(((0, 2),))])
        with self.assertRaises(ValueError):
            certify([Resource(((0, 2), (1, 3))), Resource(((0, 1),))])

    def test_counterexample_rejects_tampering(self):
        resources = [Resource(((4, 5), (8, 9))), Resource(((0, 1), (2, 3)))]
        example = counterexample(resources)
        self.assertTrue(verify_counterexample(resources, example))
        moved = type(example)(((Fraction(4), Fraction(8)),) + example.instants[1:], example.presence)
        self.assertTrue(verify_counterexample(resources, moved) in (True, False))
        widened = type(example)(example.instants, (((Fraction(0), Fraction(20)),),) + example.presence[1:])
        self.assertFalse(verify_counterexample(resources, widened))
        outside = type(example)(((Fraction(3), Fraction(8)),) + example.instants[1:], example.presence)
        self.assertFalse(verify_counterexample(resources, outside))


def fresh_token_machine(runs_needed):
    """Sound field: a new token whenever the target is published again."""
    bodies, labels, edges = {"off0": "off"}, {}, []
    for k in range(1, runs_needed + 1):
        bodies[f"A{k}"], bodies[f"B{k}"], bodies[f"off{k}"] = "A", "B", "off"
        labels[f"A{k}"] = f"A/{k}"
        edges += [(f"off{k-1}", f"A{k}"), (f"A{k}", f"B{k}"), (f"B{k}", f"off{k}"), (f"A{k}", f"off{k}")]
    return Machine(bodies, labels, tuple(edges), ("off0",), "A")


def reusable_machine():
    """Content-derived field: A, B and absence can follow each other freely."""
    bodies = {"off": "off", "A": "A", "B": "B"}
    edges = tuple((a, b) for a in bodies for b in bodies if a != b)
    return Machine(bodies, {"A": "A/h"}, edges, ("off",), "A")


class FixedInstantTest(unittest.TestCase):
    """A common instant shared by every history needs 2n captures; some common instant needs 2n - 1 (Corollary 4)."""

    def test_fixed_instant_matches_brute_force(self):
        checked = fixed = 0
        for n in (1, 2, 3):
            for length in range(n, 2 * n + 1):
                for sequence in product(range(n), repeat=length):
                    if set(sequence) != set(range(n)):
                        continue
                    windows = schedule(sequence)
                    for mask in product((True, False), repeat=n):
                        ws = [windows[i] for i in range(n)]
                        resources = [Resource(tuple(w), ok) for w, ok in zip(ws, mask)]
                        expected = fixed_oracle(ws, list(mask))
                        self.assertEqual(fixed_instant(resources) is not None, expected, (sequence, mask))
                        checked += 1
                        fixed += expected
        self.assertEqual(checked, 5948)
        self.assertGreater(fixed, 0)

    def test_fixed_interval_is_exact(self):
        rng = random.Random(29)
        for _ in range(300):
            n = rng.choice((1, 2, 3))
            ws = []
            for _ in range(n):
                start, own = rng.randrange(0, 3), []
                for _ in range(rng.choice((1, 2))):
                    own.append((start, start + 1))
                    start += 1 + rng.randrange(1, 3)
                ws.append(own)
            interval = fixed_instant([Resource(tuple(w)) for w in ws])
            self.assertEqual(interval is not None, fixed_oracle(ws, [True] * n), ws)
            if interval is not None:
                self.assertTrue(certify(runs(ws, [True] * n)).certified)

    def test_minimum_schedules(self):
        self.assertEqual([minimum_fixed_sequence_length(n) for n in (1, 2, 3)], [2, 4, 6])
        self.assertEqual([minimum_sequence_length(n) for n in (1, 2, 3)], [1, 3, 5])
        for n in range(1, 9):
            windows = schedule(list(range(n)) + list(range(n))[::-1])
            self.assertIsNotNone(fixed_instant([Resource(tuple(windows[i])) for i in range(n)]))
            if n > 1:
                windows = schedule(palindrome(range(n)))
                self.assertIsNone(fixed_instant([Resource(tuple(windows[i])) for i in range(n)]))


class CounterexampleSizeTest(unittest.TestCase):
    def test_many_reusable_captures_in_one_window(self):
        # Five fixed candidate instants once limited the constructor to five reusable reads.
        for count in (2, 6, 9):
            resources = [Resource(((0, 1),), field="reusable") for _ in range(count)]
            self.assertFalse(certify(resources).certified)
            self.assertTrue(verify_counterexample(resources, counterexample(resources)))
        resources = [Resource(((0, 1), (2, 3)), field="reusable") for _ in range(4)] + [Resource(((0, 3),))]
        self.assertTrue(verify_counterexample(resources, counterexample(resources)))


class StateMachineCertificationTest(unittest.TestCase):
    def test_pairwise_rule_matches_explicit_state_machines(self):
        rng = random.Random(7)
        agreed = 0
        for _ in range(600):
            n = rng.choice((2, 3))
            sequence = [rng.randrange(n) for _ in range(rng.randrange(n, 2 * n + 1))]
            if set(sequence) != set(range(n)):
                continue
            windows = schedule(sequence)
            sound = [rng.random() < 0.7 for _ in range(n)]
            machines, captures = [], []
            for i in range(n):
                if sound[i]:
                    machines.append(fresh_token_machine(1))
                    captures.append([(w, "A/1") for w in windows[i]])
                else:
                    machines.append(reusable_machine())
                    captures.append([(w, "A/h") for w in windows[i]])
            horizon = max(w[1] for i in range(n) for w in windows[i]) + 2
            expected = exact_certainty(machines, captures, horizon)
            decision = certify(runs([windows[i] for i in range(n)], sound))
            self.assertEqual(decision.certified, expected, (sequence, sound))
            agreed += 1
        self.assertEqual(agreed, 361)

    def test_three_sat_construction(self):
        def satisfiable(clauses, n):
            return any(all(any((l > 0) == a[abs(l) - 1] for l in c) for c in clauses)
                       for a in product((False, True), repeat=n))
        literals = (1, -1, 2, -2)
        clause_types = [(l,) for l in literals] + [(a, b) for i, a in enumerate(literals)
                                                   for b in literals[i + 1:] if a != -b]
        checked = 0
        for size in (1, 2):
            for clauses in product(clause_types, repeat=size):
                machines, captures, horizon = three_sat_instance(list(clauses), 2)
                self.assertEqual(exact_certainty(machines, captures, horizon),
                                 not satisfiable(clauses, 2), clauses)
                checked += 1
        for clauses in ([(1,), (-1, 2), (-2,)], [(1, 2), (-1, 2), (-2,)], [(1, 2), (-1, -2), (1, -2)]):
            machines, captures, horizon = three_sat_instance(list(clauses), 2)
            self.assertEqual(exact_certainty(machines, captures, horizon), not satisfiable(clauses, 2))
            checked += 1
        # Exact read instants: every capture window is a single point.
        for size in (1, 2):
            for clauses in product(clause_types, repeat=size):
                machines, captures, horizon = three_sat_instance(list(clauses), 2, eps=0)
                self.assertTrue(all(s == e for c in captures for (s, e), _ in c))
                self.assertEqual(exact_certainty(machines, captures, horizon),
                                 not satisfiable(clauses, 2), clauses)
                checked += 1
        self.assertEqual(checked, 147)


class FieldClassTest(unittest.TestCase):
    def test_general_fields_are_refused_by_the_pairwise_rule(self):
        with self.assertRaises(ValueError):
            certify([Resource(((0, 1), (4, 5)), field="general"), Resource(((2, 3),))])
        self.assertEqual(Resource(((0, 1),), sound=False).kind(), "reusable")
        self.assertEqual(Resource(((0, 1),), field="sound", sound=False).kind(), "sound")

    def test_violating_pair_matches_quadratic_search(self):
        rng = random.Random(3)
        for _ in range(500):
            n = rng.randrange(2, 7)
            firsts = {i: rng.randrange(0, 6) for i in range(n)}
            lasts = {i: rng.randrange(0, 6) for i in range(n)}
            pair = _violating_pair(firsts, lasts)
            brute = [(firsts[i] - lasts[j], i, j) for i in range(n) for j in range(n)
                     if i != j and firsts[i] > lasts[j]]
            self.assertEqual(pair is None, not brute)
            if pair is not None:
                i, j = pair
                self.assertEqual(firsts[i] - lasts[j], max(b[0] for b in brute))


class WorstCaseSweepTest(unittest.TestCase):
    def test_one_return_contract_has_no_worst_case(self):
        one = one_return_machine()
        ababa = [[((1, Fraction(3, 2)), "A"), ((5, Fraction(11, 2)), "A"), ((9, Fraction(19, 2)), "A")],
                 [((3, Fraction(7, 2)), "A"), ((7, Fraction(15, 2)), "A")]]
        self.assertIsNone(worst_case(one, ababa[0]))
        self.assertIsNone(sweep_certainty([one, one], ababa, 11))
        self.assertTrue(exact_certainty([one, one], ababa, 11, step=Fraction(1, 4)))

    def test_observation_deterministic_contracts_agree_with_reference(self):
        # Fresh labels: every observation identifies its state, so a worst case exists.
        a = Machine(bodies={"off": "off", "A1": "x", "gap": "off", "A2": "x", "B": "x"},
                    labels={"A1": "a1", "A2": "a2", "B": "b"},
                    edges=(("off", "A1"), ("A1", "gap"), ("gap", "A2"), ("A2", "B"), ("A1", "A2")),
                    initial=("off",), target="x")
        cases = [
            [[((0, 1), "a1"), ((4, 5), "a2")], [((2, 3), "a1")]],
            [[((0, 1), "a1"), ((4, 5), "b")], [((2, 3), "a1"), ((6, 7), "a2")]],
            [[((0, 1), "a1")], [((2, 3), "a1")]],
        ]
        for captures in cases:
            fast = sweep_certainty([a, a], captures, 9)
            self.assertIsNotNone(fast)
            self.assertEqual(fast, exact_certainty([a, a], captures, 9), captures)

    def test_polynomial_worst_case_matches_enumeration(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        from check_certification import random_contract, windows_for
        rng = random.Random(11)
        for _ in range(400):
            machine, labels = random_contract(rng, rng.random() < 0.5, most=4)
            observed = list(zip(windows_for(rng, len(labels)), labels))
            slow, fast = worst_case(machine, observed), worst_case_pattern(machine, observed)
            self.assertEqual(slow is None, fast is None)
            if slow is not None:
                self.assertEqual(slow[1], fast)

    def test_hardness_needs_incomparable_branches(self):
        machines, captures, horizon = three_sat_instance([(1,), (-1,)], 1)
        self.assertTrue(any(worst_case(m, c) is None for m, c in zip(machines, captures)))
        machines, captures, horizon = three_sat_instance([(1,), (1,)], 1)
        self.assertFalse(sweep_certainty(machines, captures, horizon))
        self.assertFalse(exact_certainty(machines, captures, horizon))


if __name__ == "__main__":
    unittest.main()
