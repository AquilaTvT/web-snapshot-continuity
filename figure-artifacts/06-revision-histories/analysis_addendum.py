"""Post hoc analyses of protocol-addendum.json on the frozen revision collection.

Every method is evaluated on the draws of protocol.json M2 (same bundles, read
orders, start times and read instants), so all comparisons are paired. The
script first reproduces the three preregistered methods exactly and stops if
any count differs from derived/bundles.csv.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_base(path: Path):
    """The preregistered analysis module (derive.py here, analysis.py in the figure directory)."""
    spec = importlib.util.spec_from_file_location("revision_base", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

METHODS = ("hash_bridge", "id_bridge", "id_exact",  # preregistered, reproduced
           "hash_double_closed", "id_double_closed", "id_drop_center", "hash_exact",
           "mixed_offcenter_trusting", "mixed_offcenter_theorem")


def sha(page, i):
    return page.shas[i]


def rev(page, i):
    return page.revids[i]


def plan_double(order):
    sequence = order + order[::-1]
    return [(page, j) for j, page in enumerate(sequence)]


def plan_exact(order):
    sequence = order[:-1] + [order[-1]] + order[-2::-1]
    return [(page, j) for j, page in enumerate(sequence)]


def plan_drop_center(order):
    n = len(order)
    return [(page, j) for page, j in plan_double(order) if j != n]


def capture(plan, t0, gap, offsets):
    """Reads grouped by page, in read order; windows [s, s+1], true instants u."""
    reads = {}
    for page, j in plan:
        s = t0 + j * gap
        u = s + offsets[j]
        reads.setdefault(id(page), []).append({"page": page, "s": s, "e": s + 1, "u": u, "state": page.index(u)})
    return list(reads.values())


def equal_ends(group, field):
    first, last = group[0], group[-1]
    return field(first["page"], first["state"]) == field(last["page"], last["state"])


def continuity(groups):
    """G2: every twice-read page keeps its observed sha1 between its true read instants."""
    return all(g[0]["page"].next_diff[g[0]["state"]] > g[-1]["page"].index(g[-1]["u"]) for g in groups if len(g) > 1)


def coexists_at(groups, t):
    return all(g[0]["page"].shas[g[0]["page"].index(t)] == g[0]["page"].shas[g[0]["state"]] for g in groups)


def coexists_in(groups, low, high, closed):
    """G1 for bridge rules: some instant of the claimed interval has every observed sha1."""
    points = {low}
    for g in groups:
        page = g[0]["page"]
        for t in page.times:
            if low < t < high or (closed and t == high):
                points.add(t)
    return any(coexists_at(groups, t) for t in points)


def bridge(groups, field, closed):
    if not all(equal_ends(g, field) for g in groups):
        return {"certified": False}
    low, high = max(g[0]["e"] for g in groups), min(g[-1]["s"] for g in groups)
    if not (low <= high if closed else low < high):
        return {"certified": False}
    return {"certified": True, "g1": coexists_in(groups, low, high, closed), "g2": continuity(groups)}


def pairwise(groups):
    firsts = [g[0]["e"] for g in groups]
    lasts = [g[-1]["s"] for g in groups]
    return all(firsts[a] <= lasts[b] for a in range(len(groups)) for b in range(len(groups)) if a != b)


def exact(groups, fields, reusable=()):
    """Exact test (Theorem 3). fields[k] compares page k's reads; a page in reusable is its one-reusable-field case."""
    if not all(equal_ends(g, fields[k]) for k, g in enumerate(groups) if len(g) > 1):
        return {"certified": False}
    if len(reusable) >= 2:
        return {"certified": False}
    if reusable:
        r = reusable[0]
        others = [g for k, g in enumerate(groups) if k != r]
        if not pairwise(others):
            return {"certified": False}
        low, high = max(g[0]["e"] for g in others), min(g[-1]["s"] for g in others)
        if not any(low <= c["s"] and c["e"] <= high for c in groups[r]):
            return {"certified": False}
    elif not pairwise(groups):
        return {"certified": False}
    once = [g for g in groups if len(g) == 1]
    g1 = coexists_at(groups, once[0][0]["u"]) if once else None
    return {"certified": True, "g1": g1, "g2": continuity(groups)}


def run(order, t0, gap, offsets):
    double = capture(plan_double(order), t0, gap, offsets)
    exact_reads = capture(plan_exact(order), t0, gap, offsets)
    drop = capture(plan_drop_center(order), t0, gap, offsets)
    k_off = next(k for k, g in enumerate(exact_reads) if g[0]["page"] is order[0])
    mixed = [sha if k == k_off else rev for k in range(len(exact_reads))]
    results = {
        "hash_bridge": bridge(double, sha, closed=False),
        "id_bridge": bridge(double, rev, closed=False),
        "id_exact": exact(exact_reads, [rev] * len(exact_reads)),
        "hash_double_closed": bridge(double, sha, closed=True),
        "id_double_closed": bridge(double, rev, closed=True),
        "id_drop_center": exact(drop, [rev] * len(drop)),
        "hash_exact": exact(exact_reads, [sha] * len(exact_reads)),
        "mixed_offcenter_trusting": exact(exact_reads, mixed),
        "mixed_offcenter_theorem": exact(exact_reads, mixed, reusable=(k_off,)),
    }
    return results


def replay(base, pages, window, sizes, count, starts, gaps):
    start, end = (base.seconds(w) for w in window)
    rows = []
    for stratum, stratum_index in base.STRATA.items():
        eligible = sorted((p for p in pages if p.stratum == stratum and p.times and p.times[0] == start),
                          key=lambda p: p.title)
        for n in sizes:
            rng = random.Random(1000 * n + stratum_index)
            tallies = {}
            span = (2 * n + 1) * max(gaps) + 2
            for _ in range(count):
                members = rng.sample(eligible, n)
                order = [members[k] for k in rng.sample(range(n), n)]
                for _ in range(starts):
                    t0 = rng.uniform(start, end - span)
                    offsets = {gap: [rng.random() for _ in range(2 * n)] for gap in gaps}
                    for gap in gaps:
                        for method, outcome in run(order, t0, gap, offsets[gap]).items():
                            tally = tallies.setdefault((gap, method), [0, 0, 0, 0])
                            tally[0] += 1
                            if outcome["certified"]:
                                tally[1] += 1
                                tally[2] += outcome["g1"] is False
                                tally[3] += not outcome["g2"]
            for gap in gaps:
                for method in METHODS:
                    runs, certified, g1, g2 = tallies[gap, method]
                    rows.append({"stratum": stratum, "n": n, "gap_seconds": gap, "method": method,
                                 "runs": runs, "certified": certified,
                                 "certified_violating_g1": g1, "certified_violating_g2": g2})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", type=Path, default=HERE / "data")
    parser.add_argument("--output", type=Path, default=HERE / "derived")
    parser.add_argument("--base", type=Path, default=HERE / "derive.py")
    parser.add_argument("--preregistered", type=Path, default=HERE / "derived" / "bundles.csv")
    args = parser.parse_args()
    base = load_base(args.base)
    protocol = json.loads((HERE / "protocol.json").read_text())
    json.loads((HERE / "protocol-addendum.json").read_text())
    manifest, predecessors = base.load(args.collection)
    window = protocol["window"]
    pages = []
    for history in manifest["histories"]:
        if history.get("missing"):
            continue
        states, hidden, _ = base.timeline(history, predecessors, window)
        if hidden or not states:
            continue
        pages.append(base.Page(history.get("title"), history["stratum"], states, window))
    m2 = protocol["measurements"]["M2_bundles"]
    rows = replay(base, pages, window, m2["bundle_sizes"], m2["bundles_per_size"], m2["starts_per_bundle"],
                  m2["gaps_seconds"])
    # The preregistered methods must come out exactly as derive.py reported them.
    preregistered = {(r["stratum"], r["n"], r["gap_seconds"], r["method"]): r
                     for r in csv.DictReader(args.preregistered.open())}
    for r in rows:
        key = (r["stratum"], str(r["n"]), str(r["gap_seconds"]), r["method"])
        if key in preregistered:
            p = preregistered[key]
            for field in ("runs", "certified", "certified_violating_g1", "certified_violating_g2"):
                assert int(p[field]) == r[field], (key, field, p[field], r[field])
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / "addendum.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    digest = hashlib.sha256((args.output / "addendum.csv").read_bytes()).hexdigest()
    print(json.dumps({"rows": len(rows), "addendum_csv_sha256": digest,
                      "preregistered_methods_reproduced": True}, indent=1))


if __name__ == "__main__":
    main()
