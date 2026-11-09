"""Second post hoc addendum (protocol-addendum-2.json) on the frozen revision collection.

For every certified run this records what failed, from the weakest to the
strongest notion: the certificate's premise (G2, a twice-read page changed
between its reads), its own claim (the asserted interval or instant), and
whether the certified combination held at any instant of the capture. It adds
one schedule chosen from the field contract: the page that offers only a
content hash is placed at the center of the revisit order. All draws are those
of protocol.json; the nine methods of addendum.py are reproduced first.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import importlib.util
import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent

BRIDGES = {"hash_bridge": False, "id_bridge": False, "hash_double_closed": True, "id_double_closed": True}
METHODS = ("hash_bridge", "id_bridge", "id_exact", "hash_double_closed", "id_double_closed", "id_drop_center",
           "hash_exact", "mixed_offcenter_trusting", "mixed_offcenter_theorem", "mixed_center_theorem")


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def holds_at(groups, t):
    """Every page has its observed sha1 at instant t."""
    return all(g[0]["page"].shas[g[0]["page"].index(t)] == g[0]["page"].shas[g[0]["state"]] for g in groups)


def pieces(groups, low, high, closed=True):
    """low and every state change of any page in (low, high] (or (low, high)):
    the predicate holds_at is constant between consecutive points."""
    points = {low}
    for g in groups:
        page = g[0]["page"]
        k = bisect.bisect_right(page.times, low)
        while k < len(page.times) and (page.times[k] < high or (closed and page.times[k] == high)):
            points.add(page.times[k])
            k += 1
    return sorted(points)


def assess(groups, bridge, closed):
    """(claim holds, preregistered G1 holds, combination held somewhere in the capture span)."""
    if bridge:
        low, high = max(g[0]["e"] for g in groups), min(g[-1]["s"] for g in groups)
        points = pieces(groups, low, high, closed)
        claim = all(holds_at(groups, t) for t in points)
        g1 = any(holds_at(groups, t) for t in points)
    else:
        once = [g for g in groups if len(g) == 1]
        assert len(once) == 1, "every exact-test schedule reads one page once"
        claim = g1 = holds_at(groups, once[0][0]["u"])
    span = (min(c["s"] for g in groups for c in g), max(c["e"] for g in groups for c in g))
    held = any(holds_at(groups, t) for t in pieces(groups, *span))
    return claim, g1, held


def run(first, order, t0, gap, offsets):
    outcomes = first.run(order, t0, gap, offsets)
    groups = {}
    double = first.capture(first.plan_double(order), t0, gap, offsets)
    exact_reads = first.capture(first.plan_exact(order), t0, gap, offsets)
    for method in ("hash_bridge", "id_bridge", "hash_double_closed", "id_double_closed"):
        groups[method] = double
    groups["id_drop_center"] = first.capture(first.plan_drop_center(order), t0, gap, offsets)
    for method in ("id_exact", "hash_exact", "mixed_offcenter_trusting", "mixed_offcenter_theorem"):
        groups[method] = exact_reads
    # The collector knows which page offers only a content hash and reads it once, at the center.
    centered = first.capture(first.plan_exact(order[1:] + order[:1]), t0, gap, offsets)
    k_hash = next(k for k, g in enumerate(centered) if g[0]["page"] is order[0])
    assert len(centered[k_hash]) == 1
    fields = [first.sha if k == k_hash else first.rev for k in range(len(centered))]
    outcomes["mixed_center_theorem"] = first.exact(centered, fields, reusable=(k_hash,))
    groups["mixed_center_theorem"] = centered
    result = {}
    for method in METHODS:
        outcome = dict(outcomes[method])
        if outcome["certified"]:
            claim, g1, held = assess(groups[method], method in BRIDGES, BRIDGES.get(method, True))
            if method in BRIDGES or outcome["g1"] is not None:
                assert g1 == outcome["g1"], (method, "preregistered G1 must be reproduced")
            # Nesting: fictitious => claim violated => continuity violated.
            assert held or not claim, method
            assert claim or not outcome["g2"], method
            assert g1 or not claim, method
            outcome.update(claim=claim, g1=g1, held=held)
        result[method] = outcome
    return result


def replay(base, first, pages, window, sizes, count, starts, gaps):
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
                        for method, outcome in run(first, order, t0, gap, offsets[gap]).items():
                            tally = tallies.setdefault((gap, method), [0] * 6)
                            tally[0] += 1
                            if outcome["certified"]:
                                tally[1] += 1
                                tally[2] += not outcome["g2"]
                                tally[3] += not outcome["claim"]
                                tally[4] += not outcome["g1"]
                                tally[5] += not outcome["held"]
            for gap in gaps:
                for method in METHODS:
                    runs, certified, g2, claim, g1, fictitious = tallies[gap, method]
                    rows.append({"stratum": stratum, "n": n, "gap_seconds": gap, "method": method, "runs": runs,
                                 "certified": certified, "continuity_violations": g2, "claim_violations": claim,
                                 "preregistered_g1_violations": g1, "fictitious": fictitious})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", type=Path, default=HERE / "data")
    parser.add_argument("--output", type=Path, default=HERE / "derived")
    parser.add_argument("--base", type=Path, default=HERE / "derive.py")
    parser.add_argument("--first", type=Path, default=HERE / "addendum.py")
    parser.add_argument("--reproduce", type=Path, default=HERE / "derived" / "addendum.csv")
    args = parser.parse_args()
    base = load(args.base, "revision_base")
    first = load(args.first, "revision_addendum")
    protocol = json.loads((HERE / "protocol.json").read_text())
    for name in ("protocol-addendum.json", "protocol-addendum-2.json"):
        json.loads((HERE / name).read_text())
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
    rows = replay(base, first, pages, window, m2["bundle_sizes"], m2["bundles_per_size"], m2["starts_per_bundle"],
                  m2["gaps_seconds"])
    # The first addendum's methods must come out exactly as reported there.
    earlier = {(r["stratum"], r["n"], r["gap_seconds"], r["method"]): r for r in csv.DictReader(args.reproduce.open())}
    reproduced = 0
    for r in rows:
        key = (r["stratum"], str(r["n"]), str(r["gap_seconds"]), r["method"])
        if key in earlier:
            e = earlier[key]
            assert int(e["runs"]) == r["runs"] and int(e["certified"]) == r["certified"], key
            assert int(e["certified_violating_g2"]) == r["continuity_violations"], key
            assert int(e["certified_violating_g1"]) == r["preregistered_g1_violations"], key
            reproduced += 1
    assert reproduced == len(earlier), "every row of addendum.csv must be reproduced"
    args.output.mkdir(parents=True, exist_ok=True)
    out = args.output / "addendum-2.csv"
    with out.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps({"rows": len(rows), "addendum_rows_reproduced": reproduced,
                      "addendum_2_csv_sha256": hashlib.sha256(out.read_bytes()).hexdigest()}, indent=1))


if __name__ == "__main__":
    main()
