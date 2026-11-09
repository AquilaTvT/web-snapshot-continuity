"""Independent all-pairs oracle and certificate checks for finite contracts."""

import itertools
import unittest
from dataclasses import replace

from src.history_contracts import (
    Audit, Contract, State, audit_contract, certified_read_bridge, refine, relabel, repair,
    verify_certificate, verify_witness,
)


def _set_partitions(items):
    """All labelings of items up to renaming (restricted growth strings)."""
    def grow(prefix, k):
        if len(prefix) == len(items):
            yield dict(zip(items, prefix))
            return
        for label in range(k + 1):
            yield from grow(prefix + [label], max(k, label + 1))
    yield from grow([], 0)


class RepairTests(unittest.TestCase):
    """Some field of the state is sound iff every component holding a certifiable
    state has one representation; checked against every labeling of the
    certifiable states with the independent auditor."""

    def test_exhaustive_small_contracts(self):
        cases = possible = 0
        for size in (2, 3):
            names = tuple(map(str, range(size)))
            possible_edges = tuple(itertools.product(range(size), repeat=2))
            for mask in range(1 << len(possible_edges)):
                edges = tuple((names[a], names[b]) for k, (a, b) in enumerate(possible_edges) if mask >> k & 1)
                for actual in itertools.product("AB", repeat=size):
                    for scope_mask in range(1, 1 << size):
                        scope = tuple(names[i] for i in range(size) if scope_mask >> i & 1)
                        states = tuple(State(names[i], actual[i], "-", actual[i]) for i in range(size))
                        contract = Contract("repair", states, edges, certifiable_endpoints=scope)
                        exists = False
                        for labels in _set_partitions(scope):
                            full = {n: labels.get(n, "x") for n in names}
                            if audit_contract(relabel(contract, full)).safe:
                                exists = True
                                break
                        result = repair(contract)
                        self.assertEqual(result.possible, exists, (edges, actual, scope))
                        if result.possible:
                            self.assertTrue(audit_contract(relabel(contract, result.labels)).safe)
                        else:
                            walk = result.cycle
                            self.assertEqual(walk[0], walk[-1])
                            self.assertIn(walk[0], scope)
                            self.assertTrue(all((a, b) in edges for a, b in zip(walk, walk[1:])))
                            self.assertTrue(any(actual[int(q)] != actual[int(walk[0])] for q in walk))
                        cases += 1
                        possible += result.possible
        self.assertEqual(cases, 2 ** 4 * 4 * 3 + 2 ** 9 * 8 * 7)
        self.assertGreater(possible, 0)

    def test_versioned_store_models(self):
        # S3: deleting the newest version or a delete marker restores the stored state.
        s3 = Contract("s3", (State("A", "A", "vA", "A"), State("AB", "B", "vB", "B"),
                             State("Am", "404", "-", "ABSENT")),
                      (("A", "AB"), ("AB", "A"), ("A", "Am"), ("Am", "A")), certifiable_endpoints=("A", "AB"))
        self.assertFalse(repair(s3).possible)
        self.assertEqual(repair(s3).cycle, ("A", "AB", "A"))
        # GCS: deletion promotes nothing and restoration copies under a new generation.
        gcs = Contract("gcs", (State("g1", "A", "1", "A"), State("none", "404", "-", "ABSENT"),
                               State("g2", "A", "2", "A"), State("g3", "B", "3", "B")),
                       (("g1", "none"), ("none", "g2"), ("g1", "g3"), ("g3", "g2")),
                       certifiable_endpoints=("g1", "g2", "g3"))
        self.assertTrue(repair(gcs).possible)
        self.assertTrue(audit_contract(gcs).safe)


class FiniteRefinementTests(unittest.TestCase):
    """If no field of a contract's state is sound, no field of any finite refinement
    that keeps every permitted path is sound either (pigeonhole on the lifted cycle)."""

    def test_random_finite_memories_never_repair_a_mixed_cycle(self):
        import random
        rng = random.Random(41)
        checked = failing = 0
        while checked < 400:
            size = rng.randrange(2, 5)
            names = tuple(map(str, range(size)))
            edges = tuple((a, b) for a in names for b in names if rng.random() < 0.35)
            actual = tuple(rng.choice("AB") for _ in names)
            scope = tuple(n for n in names if rng.random() < 0.7) or (names[0],)
            contract = Contract("random", tuple(State(n, actual[i], "-", actual[i]) for i, n in enumerate(names)),
                                edges, certifiable_endpoints=scope)
            base = repair(contract).possible
            memory = rng.randrange(1, 5)
            table = {(a, b, m): rng.randrange(memory) for a, b in edges for m in range(memory)}
            refined = refine(contract, memory, lambda a, b, m: table[a, b, m])
            self.assertEqual(repair(refined).possible, base, (edges, actual, scope, memory))
            checked += 1
            failing += not base
        self.assertGreater(failing, 50)

    def test_s3_deletions_need_unbounded_state(self):
        s3 = Contract("s3", (State("A", "A", "vA", "A"), State("AB", "B", "vB", "B"),
                             State("Am", "404", "-", "ABSENT")),
                      (("A", "AB"), ("AB", "A"), ("A", "Am"), ("Am", "A")), certifiable_endpoints=("A", "AB"))
        # A per-key epoch counted modulo k, or saturating at k, is finite state: it never repairs S3.
        for k in range(1, 9):
            wrap = refine(s3, k, lambda a, b, m: (m + 1) % k)
            stop = refine(s3, k, lambda a, b, m: min(m + 1, k - 1))
            self.assertFalse(repair(wrap).possible)
            self.assertFalse(repair(stop).possible)
        # An epoch that may only grow up to a horizon is sound, because the horizon removes
        # the (k+1)-th change: that contract no longer permits every path of S3.
        k = 6
        states = tuple(State(f"{q}|{e}", body, f"{validator}/{e}", actual)
                       for q, body, validator, actual in (("A", "A", "vA", "A"), ("AB", "B", "vB", "B"),
                                                          ("Am", "404", "-", "ABSENT")) for e in range(k))
        edges = tuple((f"{a}|{e}", f"{b}|{e + 1}") for a, b in s3.edges for e in range(k - 1))
        bounded = Contract("s3 epoch", states, edges,
                           certifiable_endpoints=tuple(f"{q}|{e}" for q in ("A", "AB") for e in range(k)))
        self.assertTrue(repair(bounded).possible)
        self.assertTrue(audit_contract(bounded).safe)

    def test_repair_is_linear_on_long_chains(self):
        import time
        size = 20000
        names = [f"s{k}" for k in range(size)]
        states = tuple(State(n, "A", "-", "A") for n in names)
        edges = tuple((names[k], names[k + 1]) for k in range(size - 1))
        started = time.perf_counter()
        result = repair(Contract("chain", states, edges))
        self.assertTrue(result.possible)
        self.assertLess(time.perf_counter() - started, 10.0)


class ContractTests(unittest.TestCase):
    def test_exhaustive_three_state_graphs_and_binary_labels(self):
        # 512 directed graphs x 8 body maps x 8 validator maps = 32,768.
        # Floyd-Warshall distances are independent of the product-BFS solver.
        names = tuple(map(str, range(3)))
        possible_edges = tuple(itertools.product(range(3), repeat=2))
        cases = 0
        for mask in range(1 << len(possible_edges)):
            edges = tuple((a, b) for k, (a, b) in enumerate(possible_edges) if mask >> k & 1)
            distance = [[0 if a == b else 100 for b in range(3)] for a in range(3)]
            for a, b in edges:
                distance[a][b] = min(distance[a][b], 1)
            for k, a, b in itertools.product(range(3), repeat=3):
                distance[a][b] = min(distance[a][b], distance[a][k] + distance[k][b])
            for bodies, tokens in itertools.product(itertools.product("AB", repeat=3),
                                                    itertools.product("01", repeat=3)):
                contract = Contract("oracle", tuple(State(names[i], bodies[i], tokens[i], bodies[i])
                                  for i in range(3)), tuple((names[a], names[b]) for a, b in edges))
                minimum = min((distance[a][b] + distance[b][c]
                               for a, b, c in itertools.product(range(3), repeat=3)
                               if bodies[a] == bodies[c] and tokens[a] == tokens[c]
                               and bodies[a] != bodies[b]), default=100)
                result = audit_contract(contract)
                self.assertEqual(result.safe, minimum >= 100)
                if result.safe:
                    self.assertTrue(verify_certificate(contract, result.certificate))
                else:
                    self.assertEqual(len(result.witness) - 1, minimum)
                    self.assertTrue(verify_witness(contract, result))
                cases += 1
        self.assertEqual(cases, 32768)

    def test_positive_invariant_corruption(self):
        contract = Contract("durable", (State("a", "A", "0", "A"),
            State("b", "B", "1", "B"), State("c", "A", "2", "A")),
            (("a", "a"), ("a", "b"), ("b", "c"), ("c", "c")))
        result = audit_contract(contract)
        self.assertTrue(result.safe)
        self.assertFalse(verify_certificate(contract, result.certificate[:-1]))
        damaged = replace(result.certificate[0], before_departure=())
        self.assertFalse(verify_certificate(contract, (damaged,) + result.certificate[1:]))
        damaged = replace(result.certificate[0], after_departure=())
        self.assertFalse(verify_certificate(contract, (damaged,) + result.certificate[1:]))
        # A counter-reset edge invalidates the old proof without regenerating it.
        reset = replace(contract, edges=contract.edges + (("c", "a"),))
        self.assertFalse(verify_certificate(reset, result.certificate))
        self.assertTrue(verify_witness(reset, audit_contract(reset)))

    def test_cached_response_and_corrupt_witness(self):
        cache = Contract("cache", (State("old", "A", "0", "B"),), (("old", "old"),))
        result = audit_contract(cache)
        self.assertEqual(result.failure, "read_fidelity")
        self.assertEqual(result.witness, ("old",))
        self.assertTrue(verify_witness(cache, result))
        self.assertFalse(verify_witness(cache, replace(result, body="B")))
        self.assertFalse(verify_certificate(cache, ()))
        rollback = Contract("rollback", (State("a", "A", "hA", "A"),
            State("b", "B", "hB", "B")), (("a", "b"), ("b", "a")))
        bad = audit_contract(rollback)
        self.assertFalse(verify_witness(rollback, replace(bad, witness=("a", "a"))))
        self.assertFalse(verify_witness(rollback, replace(bad, witness=("a", "b", "missing"))))

    def test_absence_is_internal_even_when_not_certifiable(self):
        # An HTTP error body is not the authoritative absence marker. Neither
        # its bytes nor its lack of a generation makes it an eligible endpoint.
        contract = Contract("deleted-and-restored", (
            State("old", "A", "generation-1", "A"),
            State("absent", "404 page", "", "ABSENT"),
            State("restored", "A", "generation-1", "A")),
            (("old", "absent"), ("absent", "restored")),
            certifiable_endpoints=("old", "restored"))
        result = audit_contract(contract)
        self.assertEqual(result.failure, "return")
        self.assertEqual(result.witness, ("old", "absent", "restored"))
        self.assertTrue(verify_witness(contract, result))
        self.assertFalse(verify_witness(contract, replace(result, witness=("old", "restored"))))
        # Discarding the ineligible node creates a false positive: the checker
        # must keep the original graph, not take an endpoint-induced subgraph.
        pruned = replace(contract, states=(contract.states[0], contract.states[2]), edges=())
        pruned_proof = audit_contract(pruned)
        self.assertTrue(pruned_proof.safe)
        self.assertFalse(verify_certificate(contract, pruned_proof.certificate))
        # A newly allocated generation excludes the equal-observation return.
        fresh = replace(contract, states=contract.states[:2] +
                        (replace(contract.states[2], validator="generation-2"),))
        good = audit_contract(fresh)
        self.assertTrue(good.safe)
        self.assertTrue(verify_certificate(fresh, good.certificate))
        damaged = replace(good.certificate[0], after_departure=("restored",))
        self.assertFalse(verify_certificate(fresh, (damaged,) + good.certificate[1:]))
        # Eligible successful responses still have to describe actual state.
        stale = replace(fresh, states=(replace(fresh.states[0], actual="B"),) + fresh.states[1:])
        bad = audit_contract(stale)
        self.assertEqual(bad.failure, "read_fidelity")
        self.assertEqual(bad.witness, ("old",))
        self.assertTrue(verify_witness(stale, bad))
        self.assertFalse(verify_certificate(stale, good.certificate))

    def test_repeated_absence_is_not_a_certifiable_return(self):
        states = (State("absent0", "ABSENT", "", "ABSENT"),
                  State("live", "A", "generation-1", "A"),
                  State("absent1", "ABSENT", "", "ABSENT"))
        full = Contract("repeated-absence", states, (("absent0", "live"), ("live", "absent1")))
        old_result = audit_contract(full)
        self.assertEqual(old_result.witness, ("absent0", "live", "absent1"))
        partial = replace(full, certifiable_endpoints=("live",))
        result = audit_contract(partial)
        self.assertTrue(result.safe)
        self.assertEqual(len(result.certificate), 1)
        self.assertTrue(verify_certificate(partial, result.certificate))
        self.assertFalse(verify_witness(partial, old_result))
        # A proof for fewer endpoint labels cannot certify the original scope.
        self.assertFalse(verify_certificate(full, result.certificate))
        extra = replace(result.certificate[0], body="ABSENT", validator="")
        self.assertFalse(verify_certificate(partial, result.certificate + (extra,)))
        # Even when an excluded response happens to have the same raw pair as
        # a successful read, it is not an accepted equal-observation endpoint.
        mixed = Contract("same-pair-excluded", (
            State("live", "A", "1", "A"), State("error", "A", "1", "ABSENT")),
            (("live", "error"),), certifiable_endpoints=("live",))
        mixed_result = audit_contract(mixed)
        self.assertTrue(mixed_result.safe)
        self.assertTrue(verify_certificate(mixed, mixed_result.certificate))
        fabricated = Audit(False, "read_fidelity", "A", "1", ("error",), ())
        self.assertFalse(verify_witness(mixed, fabricated))

    def test_empty_and_explicit_full_endpoint_scopes(self):
        contract = Contract("old-positional-call", (State("x", "A", "0", "A"),),
                            (("x", "x"),), "positional context")
        self.assertEqual(contract.context, "positional context")
        self.assertIsNone(contract.certifiable_endpoints)
        self.assertEqual(audit_contract(contract),
                         audit_contract(replace(contract, certifiable_endpoints=("x",))))
        empty = replace(contract, certifiable_endpoints=(),
                        states=(State("x", "404 page", "", "ABSENT"),))
        result = audit_contract(empty)
        self.assertTrue(result.safe)
        self.assertEqual(result.certificate, ())
        self.assertTrue(verify_certificate(empty, ()))
        self.assertFalse(verify_certificate(empty, audit_contract(contract).certificate))
        self.assertFalse(verify_witness(empty, Audit(False, "read_fidelity", "404 page", "",
                                                    ("x",), ())))

    def test_invalid_endpoint_scopes(self):
        base = Contract("scope-validation", (State("x", "A", "0", "A"),), ())
        for endpoints, error in (("x", TypeError), (["x"], TypeError),
                                 ({"x"}, TypeError), ((1,), TypeError),
                                 (("missing",), ValueError), (("x", "x"), ValueError)):
            malformed = replace(base, certifiable_endpoints=endpoints)
            with self.subTest(endpoints=endpoints):
                for check in (lambda: audit_contract(malformed),
                              lambda: verify_certificate(malformed, ()),
                              lambda: verify_witness(malformed, Audit(True, None, None, None, (), ()))):
                    with self.assertRaises(error):
                        check()

    def test_json_loaders_preserve_or_reject_endpoint_scope(self):
        from scripts.run_contracts import load_contract
        from scripts.run_validator_synthesis import load_synthesis_contract

        item = {"name": "JSON scope", "context": "current resource", "states": [
            {"name": "a", "body": "A", "validator": "1", "actual": "A"},
            {"name": "b", "body": "B", "validator": "2", "actual": "B"}],
            "edges": [["a", "b"]]}
        default = load_contract(item)
        self.assertIsNone(default.certifiable_endpoints)
        for loader in (load_contract, load_synthesis_contract):
            self.assertEqual(loader(item), default)
            self.assertEqual(loader(dict(item, certifiable_endpoints=None)), default)
            explicit = loader(dict(item, certifiable_endpoints=["b", "a"]))
            self.assertEqual(explicit.certifiable_endpoints, ("b", "a"))
            self.assertEqual(audit_contract(explicit), audit_contract(default))
            for bad, error in (("a", TypeError), (("a",), TypeError),
                               ([1], TypeError), (["a", "a"], ValueError),
                               (["missing"], ValueError)):
                with self.assertRaises(error):
                    loader(dict(item, certifiable_endpoints=bad))
        for selected in ([], ["a"]):
            partial = dict(item, certifiable_endpoints=selected)
            self.assertEqual(load_contract(partial).certifiable_endpoints, tuple(selected))
            with self.assertRaisesRegex(ValueError, "every state"):
                load_synthesis_contract(partial)

    def test_exhaustive_endpoint_scopes_against_all_pairs(self):
        # All 2-node digraphs: 16 graphs * 4 actuals * 4 tokens * 4 scopes = 1024.
        # Ordered 3-node DAGs: 8 graphs * 8 actuals * 8 tokens * 8 scopes = 4096.
        # Uncertifiable response bytes intentionally differ from actual state;
        # the independent Floyd-Warshall oracle uses all actual-state vertices.
        cases = 0
        for size in (2, 3):
            names = tuple(map(str, range(size)))
            pairs = tuple(itertools.product(range(size), repeat=2))
            candidates = pairs if size == 2 else tuple((a, b) for a, b in pairs if a < b)
            for edge_mask in range(1 << len(candidates)):
                edges = tuple((a, b) for k, (a, b) in enumerate(candidates) if edge_mask >> k & 1)
                distance = [[0 if a == b else 100 for b in range(size)] for a in range(size)]
                for a, b in edges:
                    distance[a][b] = min(distance[a][b], 1)
                for k, a, b in itertools.product(range(size), repeat=3):
                    distance[a][b] = min(distance[a][b], distance[a][k] + distance[k][b])
                for actual, tokens in itertools.product(itertools.product("AB", repeat=size),
                                                        itertools.product("01", repeat=size)):
                    for scope_mask in range(1 << size):
                        selected = tuple(i for i in range(size) if scope_mask >> i & 1)
                        contract = Contract("partial-oracle", tuple(
                            State(names[i], actual[i] if i in selected else "ignored error body",
                                  tokens[i], actual[i]) for i in range(size)),
                            tuple((names[a], names[b]) for a, b in edges),
                            certifiable_endpoints=tuple(names[i] for i in selected))
                        minimum = min((distance[a][b] + distance[b][c]
                                       for a in selected for b in range(size) for c in selected
                                       if actual[a] == actual[c] and tokens[a] == tokens[c]
                                       and actual[b] != actual[a]), default=100)
                        result = audit_contract(contract)
                        self.assertEqual(result.safe, minimum >= 100)
                        if result.safe:
                            self.assertTrue(verify_certificate(contract, result.certificate))
                        else:
                            self.assertEqual(len(result.witness) - 1, minimum)
                            self.assertTrue(verify_witness(contract, result))
                        cases += 1
        self.assertEqual(cases, 5120)

    def test_read_windows_and_clock_conversion(self):
        self.assertEqual(certified_read_bridge((0, 3), (7, 9)), (3, 7))
        self.assertIsNone(certified_read_bridge((0, 7), (7, 9)))
        self.assertIsNone(certified_read_bridge((0, 8), (7, 9)))
        # Explicit +/-2 clock error widens both windows before this call.
        self.assertIsNone(certified_read_bridge((-2, 5), (5, 11)))
        with self.assertRaises(ValueError):
            certified_read_bridge((3, 2), (7, 9))
        with self.assertRaises(TypeError):
            certified_read_bridge((0.0, 2), (7, 9))

    def test_counter_bound_depends_on_allowed_body_transitions(self):
        for alphabet, expected in (("AB", 6), ("ABC", 3)):
            states = tuple(State(f"{b}{i}", b, str(i), b) for i in range(3) for b in alphabet)
            edges = tuple((f"{b}{i}", f"{c}{(i + 1) % 3}")
                          for i in range(3) for b in alphabet for c in alphabet if b != c)
            result = audit_contract(Contract("modulo3", states, edges))
            self.assertFalse(result.safe)
            self.assertEqual(len(result.witness) - 1, expected)

    def test_invalid_contracts(self):
        with self.assertRaises(ValueError):
            audit_contract(Contract("empty", (), ()))
        state = State("x", "A", "0", "A")
        with self.assertRaises(ValueError):
            audit_contract(Contract("duplicate", (state, state), ()))
        with self.assertRaises(ValueError):
            audit_contract(Contract("unknown", (state,), (("x", "y"),)))


if __name__ == "__main__":
    unittest.main()
