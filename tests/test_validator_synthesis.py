"""Brute-force label assignments independently verify synthesis optimality."""

import itertools
import unittest
from dataclasses import replace

from src.history_contracts import Contract, State, audit_contract, verify_certificate
from src.validator_synthesis import (synthesize_validators, verify_lower_bound, verify_assignment,
    synthesize_observable_validators, verify_observable_synthesis, verify_coloring_lower_bound)


def brute_optimum(bodies, edges, strong=False):
    names = tuple(bodies)
    count = len(names)
    index = {name: i for i, name in enumerate(names)}
    reach = [[i == j for j in range(count)] for i in range(count)]
    for left, right in edges:
        reach[index[left]][index[right]] = True
    for k, i, j in itertools.product(range(count), repeat=3):
        reach[i][j] = reach[i][j] or (reach[i][k] and reach[k][j])
    conflicts = set()
    for i, j in itertools.product(range(count), repeat=2):
        if bodies[names[i]] != bodies[names[j]]:
            if strong:
                conflicts.add((i, j))
        elif any(reach[i][k] and reach[k][j] and bodies[names[k]] != bodies[names[i]]
                 for k in range(count)):
            conflicts.add((i, j))
    for colors in range(1, count + 1):
        for assignment in itertools.product(range(colors), repeat=count):
            if all(assignment[i] != assignment[j] for i, j in conflicts):
                return colors
    return None


def brute_observable_optimum(bodies, edges, observable, strong=False):
    names = tuple(bodies)
    values = tuple(dict.fromkeys(observable.values()))
    index = {name: i for i, name in enumerate(names)}
    reach = [[i == j for j in range(len(names))] for i in range(len(names))]
    for left, right in edges:
        reach[index[left]][index[right]] = True
    for k, i, j in itertools.product(range(len(names)), repeat=3):
        reach[i][j] = reach[i][j] or (reach[i][k] and reach[k][j])
    # Direct state-pair constraints; no synthesizer conflict graph is read.
    incompatible = []
    for i, j in itertools.product(range(len(names)), repeat=2):
        different = bodies[names[i]] != bodies[names[j]]
        if ((strong and different) or
            (not different and any(reach[i][k] and reach[k][j]
              and bodies[names[k]] != bodies[names[i]] for k in range(len(names))))):
            incompatible.append((names[i], names[j]))
    for colors in range(1, len(values) + 1):
        for labels in itertools.product(range(colors), repeat=len(values)):
            candidate = dict(zip(values, labels))
            if all(candidate[observable[a]] != candidate[observable[b]] for a, b in incompatible):
                return colors
    return None


def edge_gadgets(vertices, graph_edges):
    bodies, edges, observable = {}, [], {}
    # Isolated A states ensure that isolated input vertices are represented.
    for vertex in vertices:
        state = "isolated-" + vertex
        bodies[state], observable[state] = "A", vertex
    for i, (left, right) in enumerate(graph_edges):
        start, middle, end = (f"edge-{i}-{kind}" for kind in ("left", "middle", "right"))
        bodies.update({start: "A", middle: "B", end: "A"})
        observable.update({start: left, middle: "separator", end: right})
        edges.extend(((start, middle), (middle, end)))
    return bodies, tuple(edges), observable


class ValidatorSynthesisTests(unittest.TestCase):
    def assert_optimal(self, bodies, edges):
        result = synthesize_validators(bodies, edges)
        self.assertEqual(result.auxiliary_tag_count, brute_optimum(bodies, edges))
        self.assertEqual(result.strong_tag_count, brute_optimum(bodies, edges, strong=True))
        self.assertTrue(verify_lower_bound(bodies, edges, result))
        if result.feasible:
            self.assertTrue(verify_assignment(bodies, edges, result.auxiliary_tags,
                                             result.auxiliary_tag_count))
            self.assertTrue(verify_assignment(bodies, edges, result.strong_tags,
                                             result.strong_tag_count, strong=True))
            for tags in (result.auxiliary_tags, result.strong_tags):
                contract = Contract("synthesized", tuple(State(n, b, str(tags[n]), b)
                                    for n, b in bodies.items()), tuple(edges))
                checked = audit_contract(contract)
                self.assertTrue(checked.safe)
                self.assertTrue(verify_certificate(contract, checked.certificate))

    def test_all_three_state_binary_graphs(self):
        names = tuple(map(str, range(3)))
        possible_edges = tuple(itertools.product(names, repeat=2))
        cases = 0
        for mask in range(1 << len(possible_edges)):
            edges = tuple(e for k, e in enumerate(possible_edges) if mask >> k & 1)
            for values in itertools.product("AB", repeat=3):
                self.assert_optimal(dict(zip(names, values)), edges)
                cases += 1
        self.assertEqual(cases, 4096)

    def test_all_four_state_binary_ordered_dags(self):
        names = tuple(map(str, range(4)))
        possible_edges = tuple((a, b) for a, b in itertools.combinations(names, 2))
        cases = 0
        for mask in range(1 << len(possible_edges)):
            edges = tuple(e for k, e in enumerate(possible_edges) if mask >> k & 1)
            for values in itertools.product("AB", repeat=4):
                self.assert_optimal(dict(zip(names, values)), edges)
                cases += 1
        self.assertEqual(cases, 1024)

    def test_cycle_obstruction_and_history_state_expansion(self):
        result = synthesize_validators({"a": "A", "b": "B"}, (("a", "b"), ("b", "a")))
        self.assertFalse(result.feasible)
        self.assertTrue(verify_lower_bound({"a": "A", "b": "B"}, (("a", "b"), ("b", "a")), result))
        # Splitting a returned A into a fresh history state changes the input problem.
        result = synthesize_validators({"a0": "A", "b1": "B", "a2": "A"},
                                       (("a0", "b1"), ("b1", "a2")))
        self.assertEqual(result.auxiliary_tag_count, 2)
        self.assertEqual(result.strong_tag_count, 3)

    def test_incomparable_returns_reuse_a_label(self):
        bodies = {"a0": "A", "b": "B", "a1": "A", "a2": "A"}
        edges = (("a0", "b"), ("b", "a1"), ("b", "a2"))
        result = synthesize_validators(bodies, edges)
        self.assertEqual(result.auxiliary_tag_count, 2)
        self.assertEqual(result.auxiliary_tags["a1"], result.auxiliary_tags["a2"])
        self.assertNotEqual(result.strong_tags["a0"], result.strong_tags["b"])
        self.assertFalse(verify_lower_bound(bodies, edges, replace(result, auxiliary_tag_count=1)))

    def test_damaged_assignments_are_rejected(self):
        bodies = {"a0": "A", "b": "B", "a1": "A", "a2": "A"}
        edges = (("a0", "b"), ("b", "a1"), ("b", "a2"))
        result = synthesize_validators(bodies, edges)
        # The count is truthful here: rejection requires cross-body binding.
        cross_body = dict(result.strong_tags)
        cross_body["b"] = cross_body["a0"]
        self.assertFalse(verify_assignment(bodies, edges, cross_body,
                                          len(set(cross_body.values())), strong=True))
        extra_label = dict(result.auxiliary_tags)
        extra_label["a2"] = 99
        self.assertFalse(verify_assignment(bodies, edges, extra_label,
                                          result.auxiliary_tag_count))
        missing_state = dict(result.auxiliary_tags)
        missing_state.pop("a2")
        self.assertFalse(verify_assignment(bodies, edges, missing_state,
                                          result.auxiliary_tag_count))
        extra_state = dict(result.auxiliary_tags, absent=1)
        self.assertFalse(verify_assignment(bodies, edges, extra_state,
                                          result.auxiliary_tag_count))
        wrong_return = dict(result.auxiliary_tags)
        wrong_return["a1"] = wrong_return["a0"]
        self.assertFalse(verify_assignment(bodies, edges, wrong_return,
                                          len(set(wrong_return.values()))))

    def test_invalid_inputs(self):
        with self.assertRaises(ValueError):
            synthesize_validators({}, ())
        with self.assertRaises(ValueError):
            synthesize_validators({"a": "A"}, (("a", "unknown"),))


class ObservableSynthesisTests(unittest.TestCase):
    def test_all_three_state_graphs_bodies_and_partitions(self):
        names = ("0", "1", "2")
        possible_edges = tuple(itertools.product(names, repeat=2))
        partitions = (("x", "x", "x"), ("x", "x", "y"), ("x", "y", "x"),
                      ("x", "y", "y"), ("x", "y", "z"))
        cases = 0
        for mask in range(1 << len(possible_edges)):
            edges = tuple(e for k, e in enumerate(possible_edges) if mask >> k & 1)
            for values in itertools.product("AB", repeat=3):
                bodies = dict(zip(names, values))
                for partition in partitions:
                    observable = dict(zip(names, partition))
                    for strong in (False, True):
                        result = synthesize_observable_validators(bodies, edges, observable, strong=strong)
                        self.assertEqual(result.tag_count,
                            brute_observable_optimum(bodies, edges, observable, strong))
                        self.assertTrue(verify_observable_synthesis(bodies, edges, observable, result))
                        cases += 1
        self.assertEqual(cases, 40960)

    def test_hidden_restart_state_cannot_be_recovered_by_relabeling(self):
        bodies = {"a0": "A", "b": "B", "a1": "A"}
        edges = (("a0", "b"), ("b", "a1"))
        observable = {"a0": "same", "b": "other", "a1": "same"}
        self.assertTrue(synthesize_validators(bodies, edges).feasible)
        result = synthesize_observable_validators(bodies, edges, observable)
        self.assertFalse(result.feasible)
        self.assertTrue(verify_observable_synthesis(bodies, edges, observable, result))
        self.assertIn(("same", "same"), result.conflicts)

    def test_odd_cycle_needs_three_colors_despite_no_triangle(self):
        vertices = tuple(map(str, range(5)))
        edges = tuple((str(i), str((i + 1) % 5)) for i in range(5))
        bodies, transitions, observable = edge_gadgets(vertices, edges)
        full = synthesize_validators(bodies, transitions)
        self.assertEqual((full.auxiliary_tag_count, full.strong_tag_count), (2, 3))
        for strong, expected in ((False, 3), (True, 4)):
            result = synthesize_observable_validators(bodies, transitions, observable, strong=strong)
            self.assertEqual(result.tag_count, expected)
            self.assertTrue(verify_observable_synthesis(bodies, transitions, observable, result))
            self.assertFalse(verify_observable_synthesis(bodies, transitions, observable,
                             replace(result, lower_bound_proof=())))
            self.assertFalse(verify_observable_synthesis(bodies, transitions, observable,
                             replace(result, witnesses=())))
        # A fabricated "no 3-coloring" proof is rejected because a coloring exists.
        self.assertFalse(verify_coloring_lower_bound(vertices, edges, 3, (((0,),),)))

    def test_projection_domain_binding_and_limits(self):
        bodies = {"a": "A", "b": "B"}
        observable = {"a": "same", "b": "same"}
        auxiliary = synthesize_observable_validators(bodies, (), observable)
        strong = synthesize_observable_validators(bodies, (), observable, strong=True)
        self.assertTrue(auxiliary.feasible)
        self.assertFalse(strong.feasible)
        self.assertTrue(verify_observable_synthesis(bodies, (), observable, strong))
        self.assertFalse(verify_observable_synthesis(bodies, (), observable,
            replace(auxiliary, state_tags={"a": 1, "b": 2})))
        with self.assertRaises(ValueError):
            synthesize_observable_validators(bodies, (), {"a": "same"})
        with self.assertRaises(ValueError):
            synthesize_observable_validators(bodies, (), {"a": "a", "b": "b"}, max_observations=1)


if __name__ == "__main__":
    unittest.main()
