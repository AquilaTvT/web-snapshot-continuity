"""Offline analysis of the frozen revision collection, following protocol.json.

Inputs are the collection manifest and its raw API responses; every response
hash is checked and histories are rebuilt from the raw files, then compared
with the manifest. Outputs are exact counts; the bootstrap uses a fixed seed.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import json
import random
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
STRATA = {"vital": 1, "random": 2}


def seconds(stamp: str) -> int:
    return int(datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp())


def load(collection_dir: Path):
    manifest = json.loads((collection_dir / "collection.json").read_text())
    protocol_bytes = (HERE / "protocol.json").read_bytes()
    assert manifest["protocol_sha256"] == hashlib.sha256(protocol_bytes).hexdigest(), "protocol changed"
    responses = {}
    for record in manifest["responses"]:
        data = (collection_dir / record["file"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == record["sha256"], record["file"]
        responses[record["file"]] = json.loads(data)
    # Rebuild every history from raw history responses and compare with the manifest.
    rebuilt = {}
    for name, payload in responses.items():
        if "-history-" not in name:
            continue
        number = int(name.split("-history-")[1].split(".")[0])
        page = payload["query"]["pages"][0]
        entry = rebuilt.setdefault(number, {"revisions": [], "identity": set()})
        if "missing" not in page and "invalid" not in page:
            entry["identity"].add((page["pageid"], page["title"]))
            entry["revisions"].extend(page.get("revisions", []))
    for number, history in enumerate(manifest["histories"]):
        if history.get("missing"):
            continue
        entry = rebuilt[number]
        assert entry["identity"] == {(history["pageid"], history["title"])}, number
        assert entry["revisions"] == history["revisions"], number
    # No-edit pages obtain their initial state from a separate raw response.
    # Bind it to the same page and compare its value, rather than trusting the
    # duplicated before_window object in the manifest.
    before_numbers = set()
    for name, payload in responses.items():
        if "-before-" not in name:
            continue
        number = int(name.split("-before-")[1].split(".")[0])
        if number in before_numbers or not 0 <= number < len(manifest["histories"]):
            raise ValueError("duplicate or unknown before-window response: " + name)
        before_numbers.add(number)
        history = manifest["histories"][number]
        pages = payload["query"]["pages"]
        if len(pages) != 1 or history.get("missing") or history["revisions"]:
            raise ValueError("unexpected before-window response: " + name)
        page = pages[0]
        if (page.get("pageid"), page.get("title")) != (history["pageid"], history["title"]):
            raise ValueError("before-window page identity mismatch: " + name)
        revisions = page.get("revisions", [])
        if len(revisions) > 1:
            raise ValueError("multiple before-window revisions: " + name)
        before = revisions[0] if revisions else None
        if history.get("before_window") != before:
            raise ValueError("before-window value differs from raw response: " + name)
    expected_before = {number for number, history in enumerate(manifest["histories"])
                       if not history.get("missing") and not history["revisions"]}
    if before_numbers != expected_before:
        raise ValueError("missing or unexpected before-window responses")
    predecessors = {}
    for name, payload in responses.items():
        if "-parents-" in name:
            for page in payload["query"]["pages"]:
                for revision in page.get("revisions", []):
                    predecessors[revision["revid"]] = revision
    assert {str(k): v for k, v in predecessors.items()}.keys() == manifest["predecessors"].keys()
    return manifest, predecessors


def timeline(history, predecessors, window):
    """States with positive duration: (start second, revid, sha1); None before creation."""
    start, end = (seconds(w) for w in window)
    if any(seconds(r["timestamp"]) < start for r in history["revisions"]):
        raise ValueError("revision before the requested window")
    # The API's end bound is inclusive; the protocol window is half-open.
    revisions = sorted((seconds(r["timestamp"]), r["revid"], r.get("sha1")) for r in history["revisions"]
                       if seconds(r["timestamp"]) < end)
    states = []
    first = min(history["revisions"], key=lambda r: (seconds(r["timestamp"]), r["revid"])) if history["revisions"] else None
    before = None
    if first is not None and first["parentid"]:
        before = predecessors[first["parentid"]]
    elif first is None:
        before = history.get("before_window")
    if before is not None:
        states.append((start, before["revid"], before.get("sha1")))
    for time, revid, sha1 in revisions:
        if states and states[-1][0] == time:
            states[-1] = (time, revid, sha1)  # superseded within the same second
        else:
            states.append((time, revid, sha1))
    hidden = any(s[2] is None for s in states) or any("sha1hidden" in r for r in history["revisions"])
    return states, hidden, before is not None


class Page:
    def __init__(self, title, stratum, states, window):
        self.title, self.stratum = title, stratum
        self.times = [s[0] for s in states]
        self.revids = [s[1] for s in states]
        self.shas = [s[2] for s in states]
        self.end = seconds(window[1])
        # next_diff[i]: first later state with another sha1.
        self.next_diff = [len(states)] * len(states)
        for i in range(len(states) - 2, -1, -1):
            self.next_diff[i] = i + 1 if self.shas[i + 1] != self.shas[i] else self.next_diff[i + 1]

    def index(self, t):
        """State index current at second t, or -1 before the first state."""
        return bisect.bisect_right(self.times, t) - 1


def returns(page):
    """Return events: an sha1 reappears after at least one different state."""
    events, last_seen = [], {}
    for i, sha in enumerate(page.shas):
        if sha in last_seen and last_seen[sha] < i - 1 and any(s != sha for s in page.shas[last_seen[sha] + 1:i]):
            departure = next(k for k in range(last_seen[sha] + 1, i) if page.shas[k] != sha)
            events.append({"title": page.title, "from_revid": page.revids[last_seen[sha]],
                           "to_revid": page.revids[i], "departure_seconds": page.times[i] - page.times[departure]})
        last_seen[sha] = i
    return events


def hidden_change(pages, window, gaps, seed=7, resamples=2000):
    start, end = (seconds(w) for w in window)
    rows = []
    for stratum in STRATA:
        members = [p for p in pages if p.stratum == stratum]
        for gap in gaps:
            per_page = []
            for page in members:
                pairs = equal = hidden = id_hidden = 0
                t = start
                while t + gap < end:
                    i, j = page.index(t), page.index(t + gap)
                    if i >= 0:
                        pairs += 1
                        if page.shas[i] == page.shas[j]:
                            equal += 1
                            hidden += page.next_diff[i] <= j
                        id_hidden += i == j and page.next_diff[i] <= j
                    t += 3600
                per_page.append((pairs, equal, hidden, id_hidden))
            total = [sum(x[k] for x in per_page) for k in range(4)]
            rng = random.Random(seed)
            ratios = []
            for _ in range(resamples):
                sample = [per_page[rng.randrange(len(per_page))] for _ in per_page]
                e, h = sum(x[1] for x in sample), sum(x[2] for x in sample)
                ratios.append(h / e if e else 0.0)
            ratios.sort()
            rows.append({"stratum": stratum, "gap_seconds": gap, "pages": len(members), "pairs": total[0],
                         "equal_hash": total[1], "equal_hash_hidden_change": total[2],
                         "equal_revid_hidden_change": total[3],
                         "ratio": total[2] / total[1] if total[1] else 0.0,
                         "ci_low": ratios[int(0.025 * resamples)], "ci_high": ratios[int(0.975 * resamples) - 1],
                         "pages_with_hidden_change": sum(1 for x in per_page if x[2])})
    return rows


def bundles(pages, window, sizes, count, starts, gaps):
    start, end = (seconds(w) for w in window)
    rows = []
    for stratum, stratum_index in STRATA.items():
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
                        for method, outcome in run_methods(order, t0, gap, offsets[gap]).items():
                            key = (gap, method)
                            tally = tallies.setdefault(key, [0, 0, 0, 0])
                            tally[0] += 1
                            if outcome["certified"]:
                                tally[1] += 1
                                tally[2] += not outcome["g1"]
                                tally[3] += not outcome["g2"]
            for (gap, method), (runs, certified, g1, g2) in sorted(tallies.items()):
                rows.append({"stratum": stratum, "n": n, "gap_seconds": gap, "method": method,
                             "eligible_pages": len(eligible), "runs": runs, "certified": certified,
                             "certified_violating_g1": g1, "certified_violating_g2": g2})
    return rows


def run_methods(order, t0, gap, offsets):
    n = len(order)
    double = order + order[::-1]
    exact = order[:-1] + [order[-1]] + order[-2::-1]
    results = {}
    for method, sequence in (("hash_bridge", double), ("id_bridge", double), ("id_exact", exact)):
        reads = {}
        for j, page in enumerate(sequence):
            s = t0 + j * gap
            u = s + offsets[j]
            i = page.index(u)
            reads.setdefault(id(page), []).append({"page": page, "s": s, "e": s + 1, "u": u, "state": i})
        field = (lambda p, i: p.shas[i]) if method == "hash_bridge" else (lambda p, i: p.revids[i])
        certified = all(field(r[0]["page"], r[0]["state"]) == field(r[-1]["page"], r[-1]["state"]) for r in reads.values())
        twice = [r for r in reads.values() if len(r) > 1]
        once = [r for r in reads.values() if len(r) == 1]
        if certified and method != "id_exact":
            low, high = max(r[0]["e"] for r in reads.values()), min(r[-1]["s"] for r in reads.values())
            certified = low < high
            claim = (low, high)
        elif certified:
            firsts = {k: r[0]["e"] for k, r in reads.items()}
            lasts = {k: r[-1]["s"] for k, r in reads.items()}
            certified = all(firsts[a] <= lasts[b] for a in reads for b in reads if a != b)
            claim = (max(r[0]["e"] for r in twice), min(r[-1]["s"] for r in twice))
        if not certified:
            results[method] = {"certified": False}
            continue
        target = {k: r[0]["page"].shas[r[0]["state"]] for k, r in reads.items()}
        def holds(t):
            return all(r[0]["page"].shas[r[0]["page"].index(t)] == target[k] for k, r in reads.items())
        if method == "id_exact" and once:
            g1 = holds(once[0][0]["u"])
        else:
            g1 = any(holds(t) for t in instants_in(reads, claim))
        g2 = all(r[0]["page"].next_diff[r[0]["state"]] > r[-1]["page"].index(r[-1]["u"]) for r in twice)
        results[method] = {"certified": True, "g1": g1, "g2": g2}
    return results


def instants_in(reads, claim):
    """Candidate instants in [low, high): low and every state change inside."""
    low, high = claim
    points = {low}
    for r in reads.values():
        page = r[0]["page"]
        k = bisect.bisect_right(page.times, low)
        while k < len(page.times) and page.times[k] < high:
            points.add(page.times[k])
            k += 1
    return sorted(p for p in points if low <= p < high or p == low)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", type=Path, default=HERE / "data")
    parser.add_argument("--output", type=Path, default=HERE / "derived")
    args = parser.parse_args()
    protocol = json.loads((HERE / "protocol.json").read_text())
    manifest, predecessors = load(args.collection)
    window = protocol["window"]
    pages, excluded = [], []
    for history in manifest["histories"]:
        title = history.get("title") or json.dumps(history["selector"])
        if history.get("missing"):
            excluded.append({"title": title, "stratum": history["stratum"], "reason": "missing page"})
            continue
        states, hidden, existed = timeline(history, predecessors, window)
        if hidden:
            excluded.append({"title": title, "stratum": history["stratum"], "reason": "hidden or missing sha1"})
            continue
        if not states:
            excluded.append({"title": title, "stratum": history["stratum"], "reason": "no state in window"})
            continue
        pages.append(Page(title, history["stratum"], states, window))
    duplicates = len(pages) - len({(p.stratum, p.title) for p in pages})
    assert duplicates == 0, "duplicate page within a stratum"
    m1 = protocol["measurements"]["M1_hidden_change"]
    m2 = protocol["measurements"]["M2_bundles"]
    descriptive = []
    all_returns = []
    for stratum in STRATA:
        members = [p for p in pages if p.stratum == stratum]
        events = [e for p in members for e in returns(p)]
        all_returns += [dict(e, stratum=stratum) for e in events]
        durations = sorted(e["departure_seconds"] for e in events)
        descriptive.append({"stratum": stratum, "pages": len(members),
                            "pages_existing_at_window_start": sum(1 for p in members if p.times[0] == seconds(window[0])),
                            "states": sum(len(p.times) for p in members),
                            "pages_with_return": sum(1 for p in members if returns(p)),
                            "return_events": len(events),
                            "median_departure_seconds": durations[len(durations) // 2] if durations else None})
    hidden_rows = hidden_change(pages, window, m1["gaps_seconds"])
    bundle_rows = bundles(pages, window, m2["bundle_sizes"], m2["bundles_per_size"], m2["starts_per_bundle"],
                          m2["gaps_seconds"])
    args.output.mkdir(parents=True, exist_ok=True)
    for name, rows in (("descriptive.csv", descriptive), ("hidden-change.csv", hidden_rows),
                       ("bundles.csv", bundle_rows), ("returns.csv", all_returns), ("excluded.csv", excluded)):
        with (args.output / name).open("w", newline="") as stream:
            if rows:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
    summary = {"schema": 1, "collection_sha256": hashlib.sha256((args.collection / "collection.json").read_bytes()).hexdigest(),
               "protocol_sha256": manifest["protocol_sha256"], "requests": len(manifest["responses"]),
               "pages_analyzed": len(pages), "excluded": len(excluded), "descriptive": descriptive}
    (args.output / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
