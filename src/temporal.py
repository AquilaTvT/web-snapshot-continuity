"""Exact coexistence checks for versioned Web resources.

Times are integer ticks and intervals are half open. A tick can represent a
nanosecond or a revision index, but all resources must use the same time axis.
The caller supplies *known validity intervals*, not inferred crawl lifetimes.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from math import exp, expm1
from typing import Iterable, Sequence

Interval = tuple[int, int]
Validity = tuple[Interval, ...]


def normalize(intervals: Iterable[Interval]) -> Validity:
    """Union intervals, rejecting invalid intervals rather than silently fixing them."""
    ordered = sorted(intervals)
    merged: list[Interval] = []
    for start, stop in ordered:
        if not isinstance(start, int) or not isinstance(stop, int):
            raise TypeError("integer endpoints required")
        if start >= stop:
            raise ValueError("intervals must have positive duration")
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(stop, merged[-1][1]))
        else:
            merged.append((start, stop))
    return tuple(merged)


def contains(intervals: Iterable[Interval], time: int) -> bool:
    return any(start <= time < stop for start, stop in intervals)


def common_times(family: Sequence[Iterable[Interval]], window: Interval) -> Validity:
    """Sweep validity boundaries; O(M log M + n), including normalization.

    Each resource is counted at most once. At coincident boundaries all deltas
    are applied together before evaluating the following half-open segment.
    The empty family is vacuously valid throughout the requested window.
    """
    normalize([window])
    left, right = window
    events: dict[int, int] = {left: 0, right: 0}
    for validity in family:
        for start, stop in normalize(validity):
            start, stop = max(left, start), min(right, stop)
            if start < stop:
                events[start] = events.get(start, 0) + 1
                events[stop] = events.get(stop, 0) - 1
    active = 0
    points = sorted(events)
    result = []
    for index, time in enumerate(points[:-1]):
        active += events[time]
        if active == len(family):
            result.append((time, points[index + 1]))
    return normalize(result)


@dataclass(frozen=True)
class BlockedSegment:
    start: int
    stop: int
    resource: int


def noncoexistence_certificate(
    family: Sequence[Iterable[Interval]], window: Interval
) -> tuple[BlockedSegment, ...]:
    """Cover the window by segments and a resource absent on each segment.

    Preprocessing costs O(M log M + n). Monotone interval cursors then give
    O(M*n + n) work: each interval is advanced past once and each elementary
    segment inspects at most n resources. Certificates are independently
    checked by verify_noncoexistence; they do not depend on a trusted solver.
    """
    validities = tuple(normalize(v) for v in family)
    normalize([window])
    if common_times(validities, window):
        raise ValueError("the resources do coexist in the requested window")
    left, right = window
    points = sorted({left, right} | {
        x for intervals in validities for interval in intervals for x in interval
        if left < x < right
    })
    pieces: list[BlockedSegment] = []
    cursors = [0] * len(validities)
    for start, stop in zip(points, points[1:]):
        for resource, intervals in enumerate(validities):
            cursor = cursors[resource]
            while cursor < len(intervals) and intervals[cursor][1] <= start:
                cursor += 1
            cursors[resource] = cursor
            if cursor == len(intervals) or intervals[cursor][0] > start:
                blocker = resource
                break
        else:
            raise AssertionError("nonempty common support passed the decision check")
        if pieces and pieces[-1].resource == blocker:
            pieces[-1] = BlockedSegment(pieces[-1].start, stop, blocker)
        else:
            pieces.append(BlockedSegment(start, stop, blocker))
    return tuple(pieces)


def verify_noncoexistence(
    family: Sequence[Iterable[Interval]], window: Interval,
    certificate: Sequence[BlockedSegment],
) -> bool:
    """Check every certificate segment directly against supplied validity data."""
    validities = tuple(normalize(v) for v in family)
    normalize([window])
    cursor = window[0]
    for segment in certificate:
        if segment.start != cursor or not (cursor < segment.stop <= window[1]):
            return False
        if type(segment.resource) is not int or not (0 <= segment.resource < len(validities)):
            return False
        for start, stop in validities[segment.resource]:
            if max(start, segment.start) < min(stop, segment.stop):
                return False
        cursor = segment.stop
    return cursor == window[1]


def minimal_conflict(family: Sequence[Iterable[Interval]], window: Interval) -> tuple[int, ...]:
    """Return an inclusion-minimal conflict, NOT a minimum-cardinality conflict."""
    validities = tuple(normalize(v) for v in family)
    if common_times(validities, window):
        return ()
    keep = list(range(len(validities)))
    for resource in tuple(keep):
        trial = [i for i in keep if i != resource]
        if not common_times([validities[i] for i in trial], window):
            keep = trial
    return tuple(keep)


def return_obstruction(size: int) -> tuple[tuple[Validity, ...], Interval]:
    """Every proper subfamily coexists, but all resources never coexist.

    Resource i is absent only on [i, i+1). Each target value has at most two
    episodes. This is the classical unbounded-Helly construction for unions
    of two intervals, expressed as histories rather than claimed as new math.
    """
    if size < 2:
        raise ValueError("size must be at least two")
    family = []
    for i in range(size):
        family.append(tuple(x for x in ((0, i), (i + 1, size)) if x[0] < x[1]))
    return tuple(family), (0, size)


def all_k_subsets_coexist(family: Sequence[Validity], window: Interval, k: int) -> bool:
    if not 1 <= k <= len(family):
        raise ValueError("k outside family size")
    return all(common_times([family[i] for i in group], window)
               for group in combinations(range(len(family)), k))


def intervals_from_revisions(
    revisions: Sequence[tuple[int, str]], target: str, window: Interval
) -> Validity:
    """Derive intervals from a COMPLETE ordered change log through window end.

    The first revision must precede or coincide with window start. Missing,
    suppressed, or selectively filtered revisions invalidate this assumption.
    Equal timestamps are disallowed because their order is not known here.
    """
    normalize([window])
    if any(not isinstance(time, int) for time, _ in revisions):
        raise TypeError("integer revision timestamps required")
    if not revisions or revisions[0][0] > window[0]:
        raise ValueError("a boundary revision at or before window start is required")
    if any(revisions[i][0] >= revisions[i + 1][0] for i in range(len(revisions) - 1)):
        raise ValueError("revision timestamps must be strictly increasing")
    spans = []
    for i, (start, value) in enumerate(revisions):
        stop = revisions[i + 1][0] if i + 1 < len(revisions) else window[1]
        start, stop = max(start, window[0]), min(stop, window[1])
        if value == target and start < stop:
            spans.append((start, stop))
    return normalize(spans)


def bridge_error(rate: float, duration: float, position: float) -> float:
    """Illustrative symmetric two-state CTMC, conditioned on equal endpoints.

    Returns P[X(position) != X(0) | X(duration) = X(0)]. This is a model
    calculation, not an estimate of real Web error rates.
    """
    if rate < 0 or duration < 0 or not 0 <= position <= duration:
        raise ValueError("invalid rate, duration, or position")
    left = -expm1(-2 * rate * position)
    right = -expm1(-2 * rate * (duration - position))
    return left * right / (2 * (1 + exp(-2 * rate * duration)))


def sparse_ambiguity_fixture() -> dict:
    """Two full histories with identical asynchronous crawl/revisit observations."""
    return {
        "window": (0, 4),
        "observations": ((0, 0, "A"), (1, 1, "B"), (1, 2, "B"), (0, 3, "A")),
        "coherent_history": (((0, "A"),), ((0, "B"),)),
        "incoherent_history": (((0, "A"), (1, "a"), (3, "A")),
                               ((0, "b"), (1, "B"), (3, "b"))),
        "targets": ("A", "B"),
    }
