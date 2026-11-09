"""Decide whether captures certify that several resources shared one instant.

Each capture's true read instant lies in a known closed window [s, e] on one
monotone clock. A resource's target is *sound* when equal captures prove that
the target persisted between them; history_contracts.audit_contract decides
this for a finite contract. A target is *reusable* when every segment between
two of its captures can hide a departure (for example a content hash or an S3
version ID under ordinary writes and deletions). Every target is assumed able
to appear just before its first capture and to disappear just after its last
one; otherwise the contract itself carries extra knowledge.

For sound targets each resource contributes one run (its first and last
capture windows). The pairwise rule below is sound and complete; a reusable
target behaves exactly like a set of single captures. The rule and its
counterexample construction are checked independently by
verify_counterexample and by exhaustive enumeration in the tests.

Fields that are neither sound nor reusable (for example a contract that allows
exactly one return) are outside the rule: certify() refuses them. For explicit
finite contracts, sweep_certainty() decides every instance in which each
resource has a worst-case departure pattern, and exact_certainty() is the
exponential reference semantics for all of them.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from fractions import Fraction
from itertools import product
from typing import Sequence

Window = tuple[Fraction, Fraction]


def _window(value) -> Window:
    start, end = (Fraction(value[0]), Fraction(value[1]))
    if start >= end:
        raise ValueError("a capture window must have positive length: start < end")
    return start, end


FIELDS = ("sound", "reusable", "general")


@dataclass(frozen=True)
class Resource:
    """Captures of one resource with an equal target label, in read order.

    field is "sound", "reusable" or "general"; when it is omitted, the older
    boolean sound selects "sound" (True) or "reusable" (False).
    """
    windows: tuple[Window, ...]
    sound: bool = True
    field: str | None = None

    def kind(self) -> str:
        kind = self.field or ("sound" if self.sound else "reusable")
        if kind not in FIELDS:
            raise ValueError(f"unknown field class {kind!r}")
        return kind

    def checked(self) -> tuple[Window, ...]:
        if not self.windows:
            raise ValueError("a resource needs at least one capture")
        windows = tuple(_window(w) for w in self.windows)
        # Consecutive windows may touch (share an endpoint) but not overlap; the
        # reads in them still happen one after the other.
        if any(a[1] > b[0] for a, b in zip(windows, windows[1:])):
            raise ValueError("captures of one resource must have ordered windows that do not overlap")
        return windows


@dataclass(frozen=True)
class Decision:
    certified: bool
    reason: str
    pair: tuple[int, int] | None = None
    single: tuple[int, int] | None = None
    interval: Window | None = None


def certify(resources: Sequence[Resource]) -> Decision:
    """Exact certainty of a common target instant; O(total captures).

    Sound targets: certified iff first_end(i) <= last_start(j) for every
    ordered pair of distinct resources. With one reusable target r, certified
    iff the sound targets satisfy the rule among themselves and one capture of
    r has its whole window inside [max first_end, min last_start] of the
    others. Two or more reusable targets are never certified: positive-length
    or distinct windows let the adversary separate their single instants.
    """
    if not resources:
        raise ValueError("at least one resource is required")
    checked = [r.checked() for r in resources]
    if any(r.kind() == "general" for r in resources):
        raise ValueError("a general field is outside Theorem 3; decide it on an explicit contract "
                         "with sweep_certainty or exact_certainty")
    reusable = [i for i, r in enumerate(resources) if r.kind() == "reusable"]
    if len(resources) == 1:
        return Decision(True, "single resource: its capture instant is a common instant")
    if len(reusable) >= 2:
        return Decision(False, "two reusable targets", pair=(reusable[0], reusable[1]))
    sound = [i for i in range(len(resources)) if i not in reusable]
    firsts = {i: checked[i][0][1] for i in sound}
    lasts = {i: checked[i][-1][0] for i in sound}
    violation = _violating_pair(firsts, lasts)
    if violation is not None:
        return Decision(False, "first capture of one resource ends after another's last capture starts",
                        pair=violation)
    low = max(firsts.values()) if firsts else None
    high = min(lasts.values()) if lasts else None
    if not reusable:
        return Decision(True, "pairwise rule holds", interval=(low, high) if low <= high else None)
    r = reusable[0]
    for k, (start, end) in enumerate(checked[r]):
        if (low is None or start >= low) and (high is None or end <= high):
            return Decision(True, "a capture of the reusable target lies inside the sound targets' interval",
                            single=(r, k), interval=(low, high))
    return Decision(False, "no capture of the reusable target lies inside the sound targets' interval",
                    single=(r, -1))


def fixed_instant(resources: Sequence[Resource]) -> Window | None:
    """The instants that are common to every consistent history, or None.

    certify() decides whether every consistent history has *some* common
    instant; with a singly captured resource that instant is its read instant,
    which differs between histories. An instant that is common in every
    history needs every resource captured at least twice with a sound field:
    a single positive-length window lets the read move away from any given
    instant, and a reusable field certifies nothing between captures. Then the
    fixed common instants are exactly [max first-window end, min last-window
    start]. Like certify(), this treats general fields as outside the model.
    """
    if not resources:
        raise ValueError("at least one resource is required")
    checked = [r.checked() for r in resources]
    if any(r.kind() == "general" for r in resources):
        raise ValueError("a general field is outside Theorem 3")
    if any(r.kind() != "sound" or len(w) < 2 for r, w in zip(resources, checked)):
        return None
    low = max(w[0][1] for w in checked)
    high = min(w[-1][0] for w in checked)
    return (low, high) if low <= high else None


def _two(values: dict, better):
    """The two best keys of values under better(a, b), in one pass (ties by key)."""
    top = []
    for key in values:
        top.append(key)
        top.sort(key=lambda k: better(values[k], k))
        del top[2:]
    return top


def _violating_pair(firsts: dict, lasts: dict):
    """Return (i, j), i != j, with firsts[i] > lasts[j], in linear time.

    Only the two largest first-window ends and the two smallest last-window
    starts can form the most violating pair; each is found in one pass.
    """
    if len(firsts) < 2:
        return None
    by_first = _two(firsts, lambda v, k: (-v, k))
    by_last = _two(lasts, lambda v, k: (v, k))
    best = None
    for i in by_first:
        for j in by_last:
            if i != j and firsts[i] > lasts[j]:
                gap = firsts[i] - lasts[j]
                if best is None or gap > best[0]:
                    best = (gap, i, j)
    return None if best is None else (best[1], best[2])


@dataclass(frozen=True)
class Counterexample:
    instants: tuple[tuple[Fraction, ...], ...]
    presence: tuple[tuple[Window, ...], ...]   # half-open [a, b) target intervals per resource


def counterexample(resources: Sequence[Resource]) -> Counterexample:
    """Construct read instants and target-presence sets with no common instant.

    Sound runs are shrunk to [first window end, last window start]; the
    violating pair (if any) is placed at those extremes. Reusable captures are
    placed outside the sound targets' common interval and apart from each
    other. The result is checked by verify_counterexample before returning.
    """
    decision = certify(resources)
    if decision.certified:
        raise ValueError("certified captures have no counterexample")
    checked = [r.checked() for r in resources]
    instants = [[w[0] for w in windows] for windows in checked]
    sound = [i for i, r in enumerate(resources) if r.kind() == "sound"]
    reusable = [i for i, r in enumerate(resources) if r.kind() == "reusable"]
    for i in sound:
        if len(checked[i]) > 1:
            instants[i][0], instants[i][-1] = checked[i][0][1], checked[i][-1][0]
    if decision.pair is not None and not reusable[:2] == list(decision.pair):
        i, j = decision.pair
        if len(checked[i]) == 1:
            instants[i][0] = checked[i][0][1]
        if len(checked[j]) == 1:
            instants[j][0] = checked[j][0][0]
    firsts = [instants[i][0] for i in sound]
    lasts = [instants[i][-1] for i in sound]
    low = max(firsts) if firsts else None
    high = min(lasts) if lasts else None
    taken: set[Fraction] = set()
    # One more candidate per window than there are captures in total, so an
    # unused instant always remains; both window ends are candidates.
    total = sum(len(windows) for windows in checked)
    for r in reusable:
        for k, (start, end) in enumerate(checked[r]):
            candidates = [start + (end - start) * Fraction(j, total) for j in range(total + 1)]
            outside = [t for t in candidates if low is None or high is None or low > high
                       or not (low <= t <= high)]
            if len(reusable) > 1:
                outside = outside or candidates
            pool = [t for t in outside if t not in taken] or [t for t in candidates if t not in taken]
            if not pool:
                raise AssertionError("cannot separate reusable captures")
            instants[r][k] = pool[0]
            taken.add(pool[0])
    # Reads of one resource strictly increase. Where consecutive windows touch,
    # the placement above can put two reads on the shared endpoint; move one of
    # them by less than any gap between distinct instants, away from the pinned
    # end of a violating pair, which keeps the separation the refutation needs.
    pinned_first = decision.pair[0] if decision.pair is not None else None
    pinned_last = decision.pair[1] if decision.pair is not None else None
    step = min(_separation(resources, instants) / 2,
               min(e - s for windows in checked for s, e in windows) / 2)
    for i, windows in enumerate(checked):
        times = instants[i]
        if i == pinned_last and i != pinned_first:
            for k in range(len(times) - 2, -1, -1):
                if times[k] >= times[k + 1]:
                    times[k] = max(windows[k][0], times[k + 1] - step)
        else:
            for k in range(1, len(times)):
                if times[k] <= times[k - 1]:
                    times[k] = min(windows[k][1], times[k - 1] + step)
    eps = _separation(resources, instants)
    presence = []
    for i, resource in enumerate(resources):
        times = instants[i]
        if resource.kind() == "sound":
            presence.append(((times[0], times[-1] + eps),))
        else:
            presence.append(tuple((t, t + eps) for t in times))
    example = Counterexample(tuple(tuple(t) for t in instants), tuple(presence))
    if not verify_counterexample(resources, example):
        raise AssertionError("constructed counterexample failed independent verification")
    return example


def _separation(resources, instants) -> Fraction:
    points = sorted({t for times in instants for t in times})
    gaps = [b - a for a, b in zip(points, points[1:]) if b > a]
    return (min(gaps) / 4) if gaps else Fraction(1, 4)


def verify_counterexample(resources: Sequence[Resource], example: Counterexample) -> bool:
    """Check windows, order, required presence and an empty common intersection."""
    checked = [r.checked() for r in resources]
    if len(example.instants) != len(resources) or len(example.presence) != len(resources):
        return False
    for i, resource in enumerate(resources):
        times, spans = example.instants[i], example.presence[i]
        if len(times) != len(checked[i]):
            return False
        if any(not (s <= t <= e) for t, (s, e) in zip(times, checked[i])):
            return False
        if any(a >= b for a, b in zip(times, times[1:])):
            return False
        if any(a >= b for a, b in spans):
            return False
        covered = lambda t: any(a <= t < b for a, b in spans)
        if not all(covered(t) for t in times):
            return False
        if resource.kind() == "sound" and not any(a <= times[0] and times[-1] < b for a, b in spans):
            return False
    return not _common(example.presence)


def _common(families) -> bool:
    """Whether finite unions of half-open intervals have a common point."""
    points = sorted({x for spans in families for a, b in spans for x in (a, b)})
    for point in points:
        if all(any(a <= point < b for a, b in spans) for spans in families):
            return True
    return False


def palindrome(order: Sequence[int]) -> list[int]:
    """Read order 1..n-1, n, n-1..1 (2n-1 captures); the middle resource is read once."""
    order = list(order)
    return order[:-1] + [order[-1]] + order[-2::-1]


def schedule(sequence: Sequence[int], duration=1, gap=1):
    """Sequential windows, `gap` apart, for a read sequence (gap=0: consecutive windows touch).

    Returns the windows of each resource.
    """
    windows: dict[int, list[Window]] = {}
    for position, resource in enumerate(sequence):
        start = Fraction(position * (duration + gap))
        windows.setdefault(resource, []).append((start, start + duration))
    return windows


def certifies(sequence: Sequence[int], resources: int, sound=None, duration=1, gap=1) -> bool:
    """Whether a sequential read sequence certifies all resources (each read at least once)."""
    sound = set(range(resources)) if sound is None else set(sound)
    windows = schedule(sequence, duration, gap)
    if set(windows) != set(range(resources)):
        return False
    runs = []
    for i in range(resources):
        w = windows[i]
        runs.append(Resource((w[0], w[-1]) if i in sound and len(w) > 1 else tuple(w), sound=i in sound))
    return certify(runs).certified


def minimum_sequence_length(resources: int, sound=None) -> int | None:
    """Exhaustively find the shortest certifying sequential schedule (small n only)."""
    for length in range(1, 2 * resources + 1):
        for sequence in product(range(resources), repeat=length):
            if certifies(sequence, resources, sound):
                return length
    return None


def fixes_instant(sequence: Sequence[int], resources: int, duration=1, gap=1) -> bool:
    """Whether a sequential schedule with sound fields fixes a common instant."""
    windows = schedule(sequence, duration, gap)
    if set(windows) != set(range(resources)):
        return False
    return fixed_instant([Resource(tuple(windows[i])) for i in range(resources)]) is not None


def minimum_fixed_sequence_length(resources: int) -> int | None:
    """Shortest sequential schedule that fixes a common instant (small n only)."""
    for length in range(1, 2 * resources + 2):
        for sequence in product(range(resources), repeat=length):
            if fixes_instant(sequence, resources):
                return length
    return None


# ------------------------------------------------------------------ general --
# Exponential reference semantics for small finite contracts. Used to check the
# pairwise rule against explicit state machines and to check the hardness
# construction; never needed by the linear-time rule above.

@dataclass(frozen=True)
class Machine:
    """One resource: states with authoritative bodies and eligible labels."""
    bodies: dict
    labels: dict            # state -> label returned by an eligible read; absent = ineligible
    edges: tuple
    initial: tuple
    target: str


def _reach(machine: Machine, start, allowed=None):
    successors = {}
    for a, b in machine.edges:
        successors.setdefault(a, []).append(b)
    seen, stack = {start}, [start]
    while stack:
        for nxt in successors.get(stack.pop(), ()):
            if nxt not in seen and (allowed is None or allowed(nxt)):
                seen.add(nxt)
                stack.append(nxt)
    return seen


def _path(machine: Machine, a, b, *, depart: bool) -> bool:
    """A finite path a -> b exists that does (depart) / does not visit a non-target state."""
    target = lambda s: machine.bodies[s] == machine.target
    if not depart:
        return target(a) and b in _reach(machine, a, allowed=target)
    reachable = _reach(machine, a)
    return any(not target(m) and b in _reach(machine, m) for m in reachable)


def _presence(machine, states, instants, horizon):
    """Smallest target-presence pieces the adversary can force; closed intervals."""
    target = lambda s: machine.bodies[s] == machine.target
    pieces = [(t, t) for t in instants]
    first = states[0]
    absent_before = any(not target(i) and first in _reach(machine, i) for i in machine.initial)
    passing = any(target(i) and _path(machine, i, first, depart=True) for i in machine.initial)
    if not absent_before:
        pieces.append((Fraction(0), Fraction(0)) if passing else (Fraction(0), instants[0]))
    for (a, u), (b, v) in zip(zip(states, instants), zip(states[1:], instants[1:])):
        if not _path(machine, a, b, depart=True):
            pieces.append((u, v))
    last = states[-1]
    if not any(not target(m) for m in _reach(machine, last)):
        pieces.append((instants[-1], horizon))
    return pieces


def exact_certainty(machines, captures, horizon, step=Fraction(1, 2)) -> bool:
    """Brute-force certainty over layered state choices and grid instants.

    captures[i] lists (window, label) in read order for resource i. Every
    capture must return its machine's target body. Instants range over a grid
    containing all window endpoints; a common instant, if any, is then found
    among capture instants and time 0.
    """
    options = []
    for machine, observed in zip(machines, captures):
        layers = [[s for s, label in machine.labels.items() if label == want] for _, want in observed]
        if any(machine.bodies[s] != machine.target for layer in layers for s in layer):
            raise ValueError("every capture must return the target body")
        sequences = []
        for states in product(*layers):
            if not any(states[0] in _reach(machine, i) for i in machine.initial):
                continue
            if all(b in _reach(machine, a) for a, b in zip(states, states[1:])):
                sequences.append(states)
        grids = []
        for (start, end), _ in observed:
            point, values = Fraction(start), []
            while point <= Fraction(end):
                values.append(point)
                point += step
            grids.append(values)
        timings = [t for t in product(*grids) if all(a < b for a, b in zip(t, t[1:]))]
        options.append([(machine, s, t) for s in sequences for t in timings])
    for joint in product(*options):
        families = [_presence(m, s, t, Fraction(horizon)) for m, s, t in joint]
        candidates = {Fraction(0)} | {x for _, _, t in joint for x in t}
        if not any(all(any(a <= c <= b for a, b in pieces) for pieces in families) for c in candidates):
            return False
    return True


def _sequences(machine: Machine, observed):
    """State choices at the captures that some permitted path realizes, in read order."""
    layers = [[s for s, label in machine.labels.items() if label == want] for _, want in observed]
    if any(machine.bodies[s] != machine.target for layer in layers for s in layer):
        raise ValueError("every capture must return the target body")
    found = []
    for states in product(*layers):
        if not any(states[0] in _reach(machine, i) for i in machine.initial):
            continue
        if all(b in _reach(machine, a) for a, b in zip(states, states[1:])):
            found.append(states)
    return found


def departure_pattern(machine: Machine, states) -> tuple[int, ...]:
    """How much absence one state choice allows: before, between and after the captures.

    Entry 0 is 2 if the resource can be absent from time 0 until just before
    its first capture, 1 if it is present only at time 0, and 0 if it is
    present throughout [0, first read]. Entries 1..k-1 are 1 if a path between
    consecutive captures can leave the target. The last entry is 1 if the
    resource can leave the target after its last capture.
    """
    target = lambda s: machine.bodies[s] == machine.target
    first = states[0]
    if any(not target(i) and first in _reach(machine, i) for i in machine.initial):
        before = 2
    elif any(target(i) and _path(machine, i, first, depart=True) for i in machine.initial):
        before = 1
    else:
        before = 0
    between = tuple(int(_path(machine, a, b, depart=True)) for a, b in zip(states, states[1:]))
    after = int(any(not target(m) for m in _reach(machine, states[-1])))
    return (before,) + between + (after,)


def worst_case(machine: Machine, observed):
    """A state choice whose departure pattern dominates every other one, or None (enumeration).

    It exists whenever each observed label identifies its state, and for the
    single-run sound and reusable fields of Theorem 3. Hidden branches with
    incomparable departure patterns have none (the hardness construction).
    Exponential in the number of captures; worst_case_pattern is polynomial.
    """
    patterns = {states: departure_pattern(machine, states) for states in _sequences(machine, observed)}
    if not patterns:
        raise ValueError("no permitted history matches the captures")
    for states, mine in patterns.items():
        if all(all(a >= b for a, b in zip(mine, other)) for other in patterns.values()):
            return states, mine
    return None


def worst_case_pattern(machine: Machine, observed):
    """The worst-case departure pattern in polynomial time, or None if there is none.

    Forward and backward reachability over the capture layers give, for every
    gap, whether some consistent history leaves the target there; the
    componentwise maximum is the only possible worst case, and one more layered
    search decides whether a single history realizes it. A two-layer search per
    state (state, departed) gives reachability with and without a departure, so
    the work is O(|V| (|V| + |E|) + k |V|^2) for k captures.
    """
    target = lambda s: machine.bodies[s] == machine.target
    layers = [[s for s, label in machine.labels.items() if label == want] for _, want in observed]
    if any(not target(s) for layer in layers for s in layer):
        raise ValueError("every capture must return the target body")
    successors: dict = {}
    for a, b in machine.edges:
        successors.setdefault(a, []).append(b)

    def search(q):
        """Two-layer search over (state, departed): O(|V| + |E|) per start."""
        seen = {(q, not target(q))}
        stack = list(seen)
        while stack:
            state, departed = stack.pop()
            for nxt in successors.get(state, ()):
                item = (nxt, departed or not target(nxt))
                if item not in seen:
                    seen.add(item)
                    stack.append(item)
        return {s for s, _ in seen}, {s for s, d in seen if d}

    reach, leave = {}, {}
    for q in machine.bodies:
        reach[q], leave[q] = search(q)
    start = set().union(*[reach[i] for i in machine.initial])
    k = len(layers)
    forward = [[q for q in layers[0] if q in start]]
    for m in range(1, k):
        forward.append([q for q in layers[m] if any(q in reach[p] for p in forward[-1])])
    backward = [None] * k
    backward[k - 1] = list(layers[k - 1])
    for m in range(k - 2, -1, -1):
        backward[m] = [q for q in layers[m] if any(r in reach[q] for r in backward[m + 1])]
    consistent = [[q for q in forward[m] if q in backward[m]] for m in range(k)]
    if not consistent[0]:
        raise ValueError("no permitted history matches the captures")

    def before(q):
        if any(not target(i) and q in reach[i] for i in machine.initial):
            return 2
        return 1 if any(target(i) and q in leave[i] for i in machine.initial) else 0

    after = lambda q: int(any(not target(m) for m in reach[q]))
    gaps = [int(any(r in leave[q] for q in forward[m] for r in backward[m + 1])) for m in range(k - 1)]
    best_before = max(before(q) for q in consistent[0])
    best_after = max(after(q) for q in consistent[k - 1])
    current = {q for q in consistent[0] if before(q) == best_before}
    for m in range(k - 1):
        step = leave if gaps[m] else reach
        current = {r for r in consistent[m + 1] if any(r in step[q] for q in current)}
    if not any(after(q) == best_after for q in current):
        return None
    return (best_before,) + tuple(gaps) + (best_after,)


def _merged(spans):
    merged = []
    for a, b in sorted(spans):
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def sweep_certainty(machines, captures, horizon):
    """Decide certainty in polynomial time when every resource has a worst case.

    Returns None when some resource has no worst-case departure pattern. Under
    the worst case, each maximal run of captures joined by non-departing
    segments is certainly present on [first window end, last window start]
    (extended to 0 or the horizon where the resource cannot be absent there),
    and a capture that forms a run by itself is present only at its movable
    read instant. A common instant is certain iff the runs of all resources
    share a point, or some single-capture window lies inside the runs of every
    other resource. After the patterns, the two checks take O(M log M) and
    O(n M log M) time for M captures of n resources.
    """
    fixed, single = [], []
    for machine, observed in zip(machines, captures):
        pattern = worst_case_pattern(machine, observed)
        if pattern is None:
            return None
        windows = [(Fraction(w[0]), Fraction(w[1])) for w, _ in observed]
        k = len(windows)
        before, between, after = pattern[0], pattern[1:-1], pattern[-1]
        runs, start = [], 0
        for m in range(k - 1):
            if between[m]:
                runs.append((start, m))
                start = m + 1
        runs.append((start, k - 1))
        spans, points = [], []
        if before == 1:
            spans.append((Fraction(0), Fraction(0)))
        for a, b in runs:
            from_zero = a == 0 and before == 0
            to_end = b == k - 1 and after == 0
            if a == b and not from_zero and not to_end:
                points.append(windows[a])
                continue
            low = Fraction(0) if from_zero else windows[a][1]
            high = Fraction(horizon) if to_end else windows[b][0]
            spans.append((low, high))
        fixed.append(_merged(spans))
        single.append(points)
    # (A) A point covered by the fixed runs of every resource: one sweep over the
    # sorted endpoints. Each resource's merged runs are disjoint, so a point is
    # common exactly when the number of covering resources reaches n.
    events = sorted((x, kind) for spans in fixed for a, b in spans for x, kind in ((a, 0), (b, 1)))
    covering = 0
    for _, kind in events:          # closed intervals: starts before ends at one x
        covering += 1 if kind == 0 else -1
        if covering == len(fixed):
            return True
    # (B) A one-capture window inside the fixed runs of every other resource:
    # one binary search per other resource.
    starts = [[a for a, _ in spans] for spans in fixed]
    for i, points in enumerate(single):
        for start, end in points:
            inside = True
            for j, spans in enumerate(fixed):
                if j == i:
                    continue
                k = bisect_right(starts[j], start) - 1
                if k < 0 or end > spans[k][1]:
                    inside = False
                    break
            if inside:
                return True
    return False


def one_return_machine():
    """A target that may leave and come back once (unsound, not reusable)."""
    return Machine(bodies={"pre": "off", "A0": "x", "gap": "off", "A1": "x", "post": "off"},
                   labels={"A0": "A", "A1": "A"},
                   edges=(("pre", "A0"), ("A0", "gap"), ("gap", "A1"), ("A1", "post")),
                   initial=("pre",), target="x")


def three_sat_instance(clauses, variables, eps=Fraction(1, 2)):
    """Certainty instance whose answer is 'not certain' iff the CNF is satisfiable.

    A clock resource is certainly present exactly on slots [4k, 4k+2]; variable
    resource v hides a branch (true/false) behind identical labels and can
    depart during slot k only when its branch satisfies clause k. Literals are
    nonzero integers (+v true, -v false), variables numbered 1..variables.
    Every contract is acyclic; eps=0 makes every capture window a point.
    """
    q = len(clauses)
    clock_bodies, clock_labels, clock_edges = {"f0": "off"}, {}, []
    for k in range(1, q + 1):
        clock_bodies[f"z{k}"], clock_bodies[f"f{k}"] = "on", "off"
        clock_labels[f"z{k}"] = f"z{k}"
        clock_edges += [(f"f{k-1}", f"z{k}"), (f"z{k}", f"f{k}")]
    machines = [Machine(clock_bodies, clock_labels, tuple(clock_edges), ("f0",), "on")]
    eps = Fraction(eps)  # 0 gives exact read instants
    captures = [[]]
    for k in range(1, q + 1):
        captures[0] += [((4 * k - eps, 4 * k), f"z{k}"), ((4 * k + 2, 4 * k + 2 + eps), f"z{k}")]
    for v in range(1, variables + 1):
        bodies, labels, edges = {}, {}, []
        for branch, sign in (("T", 1), ("F", -1)):
            for k in range(0, q + 1):
                bodies[f"{branch}{k}"] = "x"
                labels[f"{branch}{k}"] = f"r{k}"
            for k in range(1, q + 1):
                edges.append((f"{branch}{k-1}", f"{branch}{k}"))
                if sign * v in clauses[k - 1]:
                    bodies[f"{branch}d{k}"] = "off"
                    edges += [(f"{branch}{k-1}", f"{branch}d{k}"), (f"{branch}d{k}", f"{branch}{k}")]
        machines.append(Machine(bodies, labels, tuple(edges), ("T0", "F0"), "x"))
        captures.append([((4 * k + 3, 4 * k + 3 + eps), f"r{k}") for k in range(0, q + 1)])
    return machines, captures, 4 * q + 4
