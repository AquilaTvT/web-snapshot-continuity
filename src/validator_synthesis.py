"""Minimum fixed-state continuity labels for a completely specified body graph.

The supplied states already include every permitted history variable, and the
server must be able to distinguish those states when computing a label. A model
node is not necessarily an observable implementation state: a diagram that
splits two indistinguishable visits cannot itself supply missing memory. This
solver does not add an epoch or otherwise remember earlier visits to a state.
Auxiliary labels are compared together with the observed body; strong labels
also separate different bodies. Graph algorithms and poset layering are
standard. The artifact makes their contract and lower-bound witnesses explicit.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Mapping, Iterable

from src.history_contracts import Contract, State, audit_contract, verify_certificate


@dataclass(frozen=True)
class Synthesis:
    feasible: bool
    auxiliary_tag_count: int | None
    strong_tag_count: int | None
    auxiliary_tags: dict[str, int]
    strong_tags: dict[str, int]
    body_heights: dict[str, int]
    chains: dict[str, tuple[str, ...]]
    separating_paths: dict[str, tuple[tuple[str, ...], ...]]
    impossible_cycle: tuple[str, ...]


def _path(adjacency: dict[str, tuple[str, ...]], start: str, end: str) -> tuple[str, ...]:
    parent: dict[str, str | None] = {start: None}
    queue = deque([start])
    while queue:
        node = queue.popleft()
        if node == end:
            result = []
            while node is not None:
                result.append(node)
                node = parent[node]
            return tuple(reversed(result))
        for successor in adjacency[node]:
            if successor not in parent:
                parent[successor] = node
                queue.append(successor)
    raise ValueError("requested endpoints are not reachable")


def synthesize_validators(
    bodies: Mapping[str, str], edges: Iterable[tuple[str, str]],
) -> Synthesis:
    """Synthesize minimum-cardinality fixed-state equality labels, or a mixed-body cycle proving impossibility.

    All states are distinguishable to the labeling implementation, all states
    are possible read states, all finite paths are permitted, and
    each state may persist for positive time. Bodies are faithful observations
    of the distinguished resource. Empty graphs and malformed edges are errors.
    The simple reference implementation uses O(V(V+E) + B(V+E)) graph work plus
    witness construction bounded by O(V(V+E)); B is the number of distinct bodies.
    It stores O(V^2+E) reachability data. No new graph-algorithm claim is made.
    """
    if not bodies:
        raise ValueError("a body graph must contain at least one state")
    if any(not isinstance(n, str) or not isinstance(b, str) for n, b in bodies.items()):
        raise TypeError("state identifiers and bodies must be strings")
    outgoing = {node: {} for node in bodies}
    for source, target in edges:
        if source not in bodies or target not in bodies:
            raise ValueError("edge endpoint not present in body graph")
        outgoing[source][target] = None
    adjacency = {node: tuple(out) for node, out in outgoing.items()}
    reach = {}
    for start in bodies:
        seen, queue = {start}, deque([start])
        while queue:
            for target in adjacency[queue.popleft()]:
                if target not in seen:
                    seen.add(target)
                    queue.append(target)
        reach[start] = seen

    components = []
    membership = {}
    for start in bodies:
        if start in membership:
            continue
        component = tuple(n for n in bodies if n in reach[start] and start in reach[n])
        other = next((n for n in component if bodies[n] != bodies[start]), None)
        if other is not None:
            cycle = _path(adjacency, start, other) + _path(adjacency, other, start)[1:]
            return Synthesis(False, None, None, {}, {}, {}, {}, {}, cycle)
        for node in component:
            membership[node] = len(components)
        components.append(component)

    successors = {i: {} for i in range(len(components))}
    predecessors = {i: {} for i in range(len(components))}
    for source, out in adjacency.items():
        for target in out:
            left, right = membership[source], membership[target]
            if left != right:
                successors[left][right] = None
                predecessors[right][left] = None
    indegree = {i: len(p) for i, p in predecessors.items()}
    queue = deque(i for i, degree in indegree.items() if not degree)
    order = []
    while queue:
        node = queue.popleft()
        order.append(node)
        for target in successors[node]:
            indegree[target] -= 1
            if not indegree[target]:
                queue.append(target)
    if len(order) != len(components):
        raise AssertionError("SCC condensation was not acyclic")
    component_body = {i: bodies[nodes[0]] for i, nodes in enumerate(components)}
    tags, strong_tags, heights, chains, paths = {}, {}, {}, {}, {}
    strong_offset = 0
    for body in dict.fromkeys(bodies.values()):
        scores, parent = {}, {}
        for node in order:
            score = int(component_body[node] == body)
            best_parent = None
            for previous in predecessors[node]:
                candidate = scores[previous] + int(component_body[node] == body
                                                   and component_body[previous] != body)
                if candidate > score:
                    score, best_parent = candidate, previous
            scores[node], parent[node] = score, best_parent
        target = max((i for i in order if component_body[i] == body), key=scores.get)
        heights[body] = scores[target]
        for state in bodies:
            if bodies[state] == body:
                tags[state] = scores[membership[state]]
                strong_tags[state] = strong_offset + tags[state]
        strong_offset += heights[body]
        component_path = []
        while target is not None:
            component_path.append(target)
            target = parent[target]
        component_path.reverse()
        chain = tuple(components[i][0] for k, i in enumerate(component_path)
                      if component_body[i] == body and
                      (k == 0 or component_body[component_path[k - 1]] != body))
        if len(chain) != heights[body]:
            raise AssertionError("dynamic-programming chain does not attain the claimed height")
        chains[body] = chain
        links = []
        for start, end in zip(chain, chain[1:]):
            middle = next(n for n in bodies if bodies[n] != body
                          and n in reach[start] and end in reach[n])
            links.append(_path(adjacency, start, middle) + _path(adjacency, middle, end)[1:])
        paths[body] = tuple(links)
    return Synthesis(True, max(heights.values()), sum(heights.values()),
                     tags, strong_tags, heights, chains, paths, ())


def verify_lower_bound(bodies: Mapping[str, str], edges: Iterable[tuple[str, str]],
                       result: Synthesis) -> bool:
    """Check impossibility or lower-bound paths; does not check assigned labels.

    Assignment safety is checked separately with history_contracts.audit_contract
    and its invariant checker, avoiding trust in the synthesizer's rank logic.
    """
    edge_set = set(edges)
    def valid_path(path):
        return (bool(path) and all(n in bodies for n in path)
                and all(edge in edge_set for edge in zip(path, path[1:])))
    if not result.feasible:
        path = result.impossible_cycle
        return (valid_path(path) and path[0] == path[-1]
                and any(bodies[n] != bodies[path[0]] for n in path))
    if set(result.chains) != set(bodies.values()) or set(result.body_heights) != set(bodies.values()):
        return False
    for body, chain in result.chains.items():
        if not chain or len(chain) != result.body_heights[body] or len(set(chain)) != len(chain):
            return False
        if any(n not in bodies or bodies[n] != body for n in chain):
            return False
        links = result.separating_paths.get(body, ())
        if len(links) != len(chain) - 1:
            return False
        for start, end, path in zip(chain, chain[1:], links):
            if not valid_path(path) or path[0] != start or path[-1] != end:
                return False
            if not any(bodies[n] != body for n in path[1:-1]):
                return False
    return (result.auxiliary_tag_count == max(result.body_heights.values())
            and result.strong_tag_count == sum(result.body_heights.values()))


def verify_assignment(bodies: Mapping[str, str], edges: Iterable[tuple[str, str]],
                      tags: Mapping[str, int], claimed_count: int, *,
                      strong: bool = False) -> bool:
    """Independently check a reported upper bound, including actual label use.

    Checks the full state domain, number of labels actually assigned, strong
    representation binding when requested, and continuity using the separate
    finite-contract auditor and its invariant checker. Combined with valid
    lower-bound paths, this certifies the reported optimum without trusting the
    synthesizer's SCCs, ranks, offsets, or reported label counts.
    """
    if not bodies or set(tags) != set(bodies):
        return False
    if type(claimed_count) is not int or claimed_count < 1:
        return False
    if any(type(tag) is not int or tag < 1 for tag in tags.values()):
        return False
    if len(set(tags.values())) != claimed_count:
        return False
    if strong:
        owner = {}
        for state, body in bodies.items():
            if tags[state] in owner and owner[tags[state]] != body:
                return False
            owner[tags[state]] = body
    contract = Contract("assignment-verification", tuple(State(n, b, str(tags[n]), b)
                        for n, b in bodies.items()), tuple(edges))
    try:
        checked = audit_contract(contract)
        return checked.safe and verify_certificate(contract, checked.certificate)
    except (ValueError, TypeError):
        return False


@dataclass(frozen=True)
class ProjectionConflict:
    left: str
    right: str
    reason: str
    path: tuple[str, ...]


@dataclass(frozen=True)
class ProjectionSynthesis:
    feasible: bool
    strong: bool
    tag_count: int | None
    observable_tags: dict[str, int]
    state_tags: dict[str, int]
    conflicts: tuple[tuple[str, str], ...]
    witnesses: tuple[ProjectionConflict, ...]
    lower_bound_colors: int | None
    lower_bound_proof: tuple | None


def _exact_coloring(vertices, adjacency):
    """Small-graph exact upper bound, using saturation-order backtracking."""
    order = {v: i for i, v in enumerate(vertices)}
    for budget in range(1, len(vertices) + 1):
        assignment = {}

        def visit():
            if len(assignment) == len(vertices):
                return dict(assignment)
            remaining = (v for v in vertices if v not in assignment)
            node = max(remaining, key=lambda v: (
                len({assignment[n] for n in adjacency[v] if n in assignment}),
                len(adjacency[v]), -order[v]))
            unavailable = {assignment[n] for n in adjacency[node] if n in assignment}
            # New color names are interchangeable, so introduce them in order.
            for color in range(1, min(budget, max(assignment.values(), default=0) + 1) + 1):
                if color not in unavailable:
                    assignment[node] = color
                    answer = visit()
                    if answer is not None:
                        return answer
                    del assignment[node]
            return None

        answer = visit()
        if answer is not None:
            return budget, answer
    raise AssertionError("a loop-free finite graph must be colorable")


def _coloring_lower_proof(vertices, adjacency, colors, max_nodes):
    """Enumerate fixed-order prefixes independently of the upper-bound search.

    A proof node has one branch per canonical color available at that prefix.
    An integer branch identifies a previously colored conflicting neighbor;
    a tuple branch is a complete proof for the extended prefix. Color names
    are canonical by first use. No clique bound is substituted for enumeration.
    """
    visited = 0

    def visit(prefix):
        nonlocal visited
        visited += 1
        if visited > max_nodes:
            raise ValueError("exact lower-bound proof exceeded the declared node limit")
        if len(prefix) == len(vertices):
            return None
        node = vertices[len(prefix)]
        branches = []
        for color in range(1, min(colors, max(prefix, default=0) + 1) + 1):
            blocker = next((j for j, value in enumerate(prefix)
                            if value == color and vertices[j] in adjacency[node]), None)
            if blocker is not None:
                branches.append(blocker)
            else:
                proof = visit(prefix + (color,))
                if proof is None:
                    return None
                branches.append(proof)
        return tuple(branches)

    proof = visit(())
    if proof is None:
        raise AssertionError("claimed lower bound admits a coloring")
    return proof


def verify_coloring_lower_bound(vertices: tuple[str, ...], conflicts, colors: int, proof) -> bool:
    """Check an exhaustive canonical-prefix proof of non-colorability.

    This checker does not run the optimizer or trust its search order. Every
    coloring can be renamed by first use, so checking every canonical branch
    suffices. A complete valid assignment invalidates an unsatisfiability proof.
    """
    if not vertices or len(set(vertices)) != len(vertices) or type(colors) is not int or colors < 0:
        return False
    edge_set = {frozenset(edge) for edge in conflicts}

    def visit(prefix, subtree):
        if len(prefix) >= len(vertices) or not isinstance(subtree, (tuple, list)):
            return False
        candidates = tuple(range(1, min(colors, max(prefix, default=0) + 1) + 1))
        if len(subtree) != len(candidates):
            return False
        node = vertices[len(prefix)]
        for color, branch in zip(candidates, subtree):
            if type(branch) is int:
                if not 0 <= branch < len(prefix) or prefix[branch] != color:
                    return False
                if frozenset((node, vertices[branch])) not in edge_set:
                    return False
            elif not visit(prefix + (color,), branch):
                return False
        return True

    return visit((), proof)


def synthesize_observable_validators(
    bodies: Mapping[str, str], edges: Iterable[tuple[str, str]],
    observable: Mapping[str, str], *, strong: bool = False,
    max_observations: int = 12, max_proof_nodes: int = 1_000_000,
) -> ProjectionSynthesis:
    """Exact small-model synthesis when tags must be functions of given fields.

    ``observable[state]`` names the existing field tuple visible to the tag
    implementation. States in one fiber must receive the same tag. Return-path
    conflicts are projected onto these fibers; a self-loop proves impossibility.
    Otherwise the optimum is the conflict graph's chromatic number. Exact graph
    coloring is exponential; explicit limits fail rather than claim an optimum
    without a verified lower bound. This changes labels, never state memory.
    """
    if not bodies or set(observable) != set(bodies):
        raise ValueError("every state needs exactly one observable value")
    if any(not isinstance(n, str) or not isinstance(b, str) or not isinstance(observable[n], str)
           for n, b in bodies.items()):
        raise TypeError("states, bodies, and observable values must be strings")
    if type(strong) is not bool or max_observations < 1 or max_proof_nodes < 1:
        raise ValueError("invalid synthesis options")
    outgoing = {n: {} for n in bodies}
    for left, right in edges:
        if left not in bodies or right not in bodies:
            raise ValueError("edge endpoint not present in body graph")
        outgoing[left][right] = None
    adjacency = {n: tuple(out) for n, out in outgoing.items()}
    reach = {}
    for start in bodies:
        seen, queue = {start}, deque([start])
        while queue:
            for target in adjacency[queue.popleft()]:
                if target not in seen:
                    seen.add(target)
                    queue.append(target)
        reach[start] = seen
    vertices = tuple(dict.fromkeys(observable.values()))
    position = {v: i for i, v in enumerate(vertices)}
    witnesses = {}
    for start in bodies:
        for end in bodies:
            path, reason = None, None
            if bodies[start] == bodies[end]:
                middle = next((n for n in bodies if bodies[n] != bodies[start]
                               and n in reach[start] and end in reach[n]), None)
                if middle is not None:
                    path = _path(adjacency, start, middle) + _path(adjacency, middle, end)[1:]
                    reason = "body_return"
            elif strong:
                path, reason = (start, end), "representation_binding"
            if path is not None:
                left, right = observable[start], observable[end]
                edge = ((left, right) if position[left] <= position[right] else (right, left))
                witnesses.setdefault(edge, ProjectionConflict(left, right, reason, path))
    conflicts = tuple(witnesses)
    if any(left == right for left, right in conflicts):
        return ProjectionSynthesis(False, strong, None, {}, {}, conflicts,
                                   tuple(witnesses.values()), None, None)
    if len(vertices) > max_observations:
        raise ValueError("exact coloring exceeds the declared observation limit")
    neighbors = {v: set() for v in vertices}
    for left, right in conflicts:
        neighbors[left].add(right)
        neighbors[right].add(left)
    count, labels = _exact_coloring(vertices, neighbors)
    proof = _coloring_lower_proof(vertices, neighbors, count - 1, max_proof_nodes)
    return ProjectionSynthesis(True, strong, count, labels,
                               {n: labels[observable[n]] for n in bodies}, conflicts,
                               tuple(witnesses.values()), count - 1, proof)


def verify_observable_synthesis(bodies: Mapping[str, str], edges: Iterable[tuple[str, str]],
                                observable: Mapping[str, str], result: ProjectionSynthesis) -> bool:
    """Verify conflict evidence, exact lower bound, and an independent upper bound.

    Only soundness of listed conflicts is needed for the lower bound; omitted
    conflicts cannot produce a false positive because the separate contract
    auditor checks the proposed upper-bound assignment on the original graph.
    """
    if not bodies or set(observable) != set(bodies) or type(result.strong) is not bool:
        return False
    edge_set = set(edges)
    vertices = tuple(dict.fromkeys(observable.values()))
    listed = {frozenset(edge) for edge in result.conflicts}
    if len(listed) != len(result.conflicts):
        return False
    witnessed = set()
    for witness in result.witnesses:
        path = witness.path
        if not path or any(n not in bodies for n in path):
            return False
        if (observable[path[0]], observable[path[-1]]) != (witness.left, witness.right):
            return False
        if witness.reason == "body_return":
            if bodies[path[0]] != bodies[path[-1]]:
                return False
            if not all(edge in edge_set for edge in zip(path, path[1:])):
                return False
            if not any(bodies[n] != bodies[path[0]] for n in path[1:-1]):
                return False
        elif witness.reason == "representation_binding":
            if not result.strong or len(path) != 2 or bodies[path[0]] == bodies[path[-1]]:
                return False
        else:
            return False
        witnessed.add(frozenset((witness.left, witness.right)))
    if witnessed != listed:
        return False
    has_loop = any(left == right for left, right in result.conflicts)
    if not result.feasible:
        return has_loop and result.tag_count is None
    if has_loop or set(result.observable_tags) != set(vertices) or set(result.state_tags) != set(bodies):
        return False
    if any(result.state_tags[n] != result.observable_tags[observable[n]] for n in bodies):
        return False
    if not verify_assignment(bodies, edge_set, result.state_tags, result.tag_count, strong=result.strong):
        return False
    if result.lower_bound_colors != result.tag_count - 1:
        return False
    return verify_coloring_lower_bound(vertices, result.conflicts, result.lower_bound_colors,
                                       result.lower_bound_proof)
