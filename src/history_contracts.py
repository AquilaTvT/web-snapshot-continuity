"""Check whether equal responses certify continuity in a finite server contract.

This is finite-state safety checking, not a new graph algorithm. The contract is
an explicit assumption about *all* permitted states and transitions of one
resource in one fixed request context. It is not inferred from a few captures.
An omitted restart, stale response, or update can invalidate a positive result.

The distinguished ``actual`` field is the authoritative representation at the
read's linearization point. It need not equal the response ``body``: that
distinction makes an old cache response an explicit read-fidelity failure.
Only declared certifiable endpoints must have faithful response bodies. Other
states, including absence or error responses without a contract token, remain
in every path search and can refute continuity between successful reads.
This endpoint restriction applies to auditing only. The separate label
synthesis APIs and their alphabet bounds still label every graph state; passing
only the bodies of certifiable states to them would discard hidden transitions.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class State:
    name: str
    body: str
    validator: str
    actual: str


@dataclass(frozen=True)
class Contract:
    name: str
    states: tuple[State, ...]
    edges: tuple[tuple[str, str], ...]
    context: str = "fixed resource and request context"
    # None means all states; () certifies no observations and supplies no bridge.
    # Keep this after context to preserve existing positional construction.
    certifiable_endpoints: tuple[str, ...] | None = None

    def checked(self) -> tuple[dict[str, State], dict[str, tuple[str, ...]]]:
        if not self.states:
            raise ValueError("a contract needs at least one permitted state")
        nodes = {s.name: s for s in self.states}
        if len(nodes) != len(self.states):
            raise ValueError("state names must be unique")
        for s in self.states:
            if any(not isinstance(v, str) for v in (s.name, s.body, s.validator, s.actual)):
                raise TypeError("state fields must be strings")
        if self.certifiable_endpoints is not None:
            if not isinstance(self.certifiable_endpoints, tuple):
                raise TypeError("certifiable endpoints must be a tuple of state names or None")
            if any(not isinstance(n, str) for n in self.certifiable_endpoints):
                raise TypeError("certifiable endpoint names must be strings")
            if len(set(self.certifiable_endpoints)) != len(self.certifiable_endpoints):
                raise ValueError("certifiable endpoints must not repeat state names")
            if not set(self.certifiable_endpoints) <= nodes.keys():
                raise ValueError("certifiable endpoint not present in contract")
        adjacency = {name: {} for name in nodes}
        for source, target in self.edges:
            if source not in nodes or target not in nodes:
                raise ValueError("edge endpoint not present in contract")
            adjacency[source][target] = None
        return nodes, {name: tuple(out) for name, out in adjacency.items()}


@dataclass(frozen=True)
class Invariant:
    body: str
    validator: str
    before_departure: tuple[str, ...]
    after_departure: tuple[str, ...]


@dataclass(frozen=True)
class Audit:
    safe: bool
    failure: str | None
    body: str | None
    validator: str | None
    witness: tuple[str, ...]
    certificate: tuple[Invariant, ...]


def audit_contract(contract: Contract) -> Audit:
    """Return a shortest bad path or a separately checkable safety invariant.

    A zero-edge bad path means a certifiable response misstates the distinguished
    authoritative state. Otherwise the path has equal (body, validator) at its
    endpoints but visits another authoritative body in between. Shortest means
    fewest transitions in this supplied graph, not least wall-clock duration.
    Only declared endpoints start or finish a witness; all states and edges
    remain available internally. An empty endpoint set is vacuously safe but
    certifies no response pair, so it cannot justify a read bridge. For k
    distinct certifiable observation pairs, work is O((k+1) (|V|+|E|)).
    """
    nodes, adjacency = contract.checked()
    eligible = (set(nodes) if contract.certifiable_endpoints is None
                else set(contract.certifiable_endpoints))
    for name in nodes:
        s = nodes[name]
        if name in eligible and s.body != s.actual:
            return Audit(False, "read_fidelity", s.body, s.validator, (name,), ())
    # Input order is deterministic; sorting would add an unnecessary log factor
    # to the linear graph construction and each certificate serialization.
    labels = tuple(dict.fromkeys((s.body, s.validator) for n, s in nodes.items()
                                if n in eligible))
    witnesses = []
    proofs = []
    for body, validator in labels:
        endpoints = tuple(n for n, s in nodes.items()
                          if n in eligible and (s.body, s.validator) == (body, validator))
        endpoint_set = set(endpoints)
        parent = {(n, False): None for n in endpoints}
        queue = deque(parent)
        accepting = None
        while queue:
            current = queue.popleft()
            name, departed = current
            if departed and name in endpoint_set:
                accepting = current
                break
            for target in adjacency[name]:
                successor = (target, departed or nodes[target].actual != body)
                if successor not in parent:
                    parent[successor] = current
                    queue.append(successor)
        if accepting is not None:
            path = []
            while accepting is not None:
                path.append(accepting[0])
                accepting = parent[accepting]
            witnesses.append((tuple(reversed(path)), body, validator))
        else:
            proofs.append(Invariant(body, validator,
                tuple(n for n, departed in parent if not departed),
                tuple(n for n, departed in parent if departed)))
    if witnesses:
        path, body, validator = min(witnesses, key=lambda w: (len(w[0]), w[0], w[1:]))
        return Audit(False, "return", body, validator, path, ())
    return Audit(True, None, None, None, (), tuple(proofs))


def verify_witness(contract: Contract, audit: Audit) -> bool:
    """Check a witness under this contract's endpoint scope, not shortestness."""
    nodes, adjacency = contract.checked()
    eligible = (set(nodes) if contract.certifiable_endpoints is None
                else set(contract.certifiable_endpoints))
    if audit.safe or not audit.witness or any(n not in nodes for n in audit.witness):
        return False
    if audit.witness[0] not in eligible or audit.witness[-1] not in eligible:
        return False
    first, last = nodes[audit.witness[0]], nodes[audit.witness[-1]]
    if (first.body, first.validator) != (audit.body, audit.validator):
        return False
    if audit.failure == "read_fidelity":
        return len(audit.witness) == 1 and first.body != first.actual
    if audit.failure != "return" or (last.body, last.validator) != (audit.body, audit.validator):
        return False
    if first.actual != first.body or last.actual != last.body:
        return False
    if not all(b in adjacency[a] for a, b in zip(audit.witness, audit.witness[1:])):
        return False
    return any(nodes[n].actual != first.body for n in audit.witness[1:-1])


def verify_certificate(contract: Contract, certificate: tuple[Invariant, ...]) -> bool:
    """Check closure of the claimed invariants; no reachability search is used.

    For each certifiable endpoint observation, every start belongs to the before
    set, all transitions preserve the before/after product invariant, and no
    after state is an equal-observation endpoint. This is an inductive proof for
    all finite paths in the model, including arbitrarily many self loops. The
    endpoint scope belongs to the contract, not to the supplied certificate.
    """
    nodes, adjacency = contract.checked()
    eligible = (set(nodes) if contract.certifiable_endpoints is None
                else set(contract.certifiable_endpoints))
    if any(s.body != s.actual for n, s in nodes.items() if n in eligible):
        return False
    labels = {(s.body, s.validator) for n, s in nodes.items() if n in eligible}
    if len(certificate) != len(labels) or {(p.body, p.validator) for p in certificate} != labels:
        return False
    for proof in certificate:
        before, after = set(proof.before_departure), set(proof.after_departure)
        if not before <= nodes.keys() or not after <= nodes.keys():
            return False
        starts = {n for n, s in nodes.items()
                  if n in eligible and (s.body, s.validator) == (proof.body, proof.validator)}
        if not starts <= before or starts & after:
            return False
        if any(nodes[n].actual != proof.body for n in before):
            return False
        for name in before:
            for target in adjacency[name]:
                destination = before if nodes[target].actual == proof.body else after
                if target not in destination:
                    return False
        for name in after:
            if not set(adjacency[name]) <= after:
                return False
    return True


@dataclass(frozen=True)
class Repair:
    """Whether any field computed from the contract state can certify continuity."""
    possible: bool
    labels: dict | None          # state -> component index, a sound field when possible
    cycle: tuple[str, ...]       # a closed walk from a certifiable state through another representation


def _components(names, adjacency):
    """Strongly connected components (iterative Tarjan), O(|V| + |E|)."""
    index, low, on_stack, stack, comp = {}, {}, set(), [], {}
    counter = components = 0
    for root in names:
        if root in index:
            continue
        work = [(root, iter(adjacency[root]))]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)
        while work:
            node, successors = work[-1]
            advanced = False
            for nxt in successors:
                if nxt not in index:
                    index[nxt] = low[nxt] = counter
                    counter += 1
                    stack.append(nxt)
                    on_stack.add(nxt)
                    work.append((nxt, iter(adjacency[nxt])))
                    advanced = True
                    break
                if nxt in on_stack:
                    low[node] = min(low[node], index[nxt])
            if advanced:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    comp[member] = components
                    if member == node:
                        break
                components += 1
    return comp


def repair(contract: Contract) -> Repair:
    """Decide whether some function of the state is a sound field, in O(|V| + |E|).

    With faithful certifiable states, a field f(q) of the state certifies
    continuity for every equal pair iff every strongly connected component that
    contains a certifiable state has a single authoritative representation. If a
    component mixes representations, a closed walk from a certifiable state q
    through another representation returns to q itself, so every field of the
    state, existing or new, repeats its value across a change. Otherwise the
    component index is a sound field. Body bytes need no separate treatment:
    they are part of the observation and equal on a monochromatic component.
    """
    nodes, adjacency = contract.checked()
    eligible = set(nodes) if contract.certifiable_endpoints is None else set(contract.certifiable_endpoints)
    if any(nodes[n].body != nodes[n].actual for n in eligible):
        raise ValueError("read fidelity fails; no field can repair an unfaithful read")
    comp = _components(list(nodes), adjacency)
    # One pass: a representative state per component and, if the component mixes
    # representations, a state whose representation differs from that representative.
    representative, differing = {}, {}
    for name in nodes:
        c = comp[name]
        if c not in representative:
            representative[c] = name
        elif c not in differing and nodes[name].actual != nodes[representative[c]].actual:
            differing[c] = name
    for name in nodes:
        c = comp[name]
        if name in eligible and c in differing:
            first = representative[c]
            other = differing[c] if nodes[first].actual == nodes[name].actual else first
            return Repair(False, None, _cycle(adjacency, name, other))
    return Repair(True, {n: comp[n] for n in nodes}, ())


def refine(contract: Contract, memory: int, update) -> Contract:
    """The contract with a finite memory of `memory` values added to every state.

    The refined states are (q, m) for every state q and memory value m; each
    transition q -> q' becomes (q, m) -> (q', update(q, q', m)). Every path of
    the contract therefore lifts from every memory value: the refinement keeps
    every permitted operation and only adds information that a field may read.
    Representations, bodies and the certifiable scope are those of q.
    """
    nodes, adjacency = contract.checked()
    if memory < 1:
        raise ValueError("a memory needs at least one value")
    name = lambda q, m: f"{q}|{m}"
    states = tuple(State(name(s.name, m), s.body, s.validator, s.actual)
                   for s in contract.states for m in range(memory))
    edges = []
    for q, targets in adjacency.items():
        for target in targets:
            for m in range(memory):
                after = update(q, target, m)
                if not isinstance(after, int) or not 0 <= after < memory:
                    raise ValueError("the memory update must return a memory value")
                edges.append((name(q, m), name(target, after)))
    scope = None if contract.certifiable_endpoints is None else tuple(
        name(q, m) for q in contract.certifiable_endpoints for m in range(memory))
    return Contract(contract.name + f" (memory {memory})", states, tuple(edges), contract.context, scope)


def _cycle(adjacency, start, via):
    """A closed walk start -> via -> start inside one component (breadth-first paths)."""
    def path(a, b):
        parent, queue = {a: None}, deque([a])
        while queue:
            node = queue.popleft()
            if node == b:
                break
            for nxt in adjacency[node]:
                if nxt not in parent:
                    parent[nxt] = node
                    queue.append(nxt)
        walk = []
        while b is not None:
            walk.append(b)
            b = parent[b]
        return walk[::-1]
    there, back = path(start, via), path(via, start)
    return tuple(there + back[1:])


def relabel(contract: Contract, labels: dict) -> Contract:
    """The contract with every state's validator replaced by labels[state]."""
    contract.checked()
    states = tuple(State(s.name, s.body, str(labels[s.name]), s.actual) for s in contract.states)
    return Contract(contract.name + " (relabelled)", states, contract.edges, contract.context,
                    contract.certifiable_endpoints)


def certified_read_bridge(first: tuple[int, int], second: tuple[int, int]) -> tuple[int, int] | None:
    """Conservative half-open bridge from two ordered atomic-read windows.

    Preconditions supplied by the caller: equal certifiable observations, a
    sound continuity contract covering them, and true read points in these
    windows on one monotone time axis. A vacuously safe contract with no
    certifiable endpoints does not meet these preconditions.
    A window includes its possible read points. [first.end, second.start) is a
    guaranteed bridge when it has positive duration. There is no claim about
    response freshness, remote clock conversion, or overlapping read windows.
    """
    for start, end in (first, second):
        if not isinstance(start, int) or not isinstance(end, int):
            raise TypeError("integer time bounds required")
        if start > end:
            raise ValueError("read windows must be ordered")
    return (first[1], second[0]) if first[1] < second[0] else None
