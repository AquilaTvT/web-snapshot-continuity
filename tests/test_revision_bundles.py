import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "revision_bundles"))
import derive  # noqa: E402
import addendum  # noqa: E402
import addendum2  # noqa: E402


def stamp(day, second=0):
    return f"2024-01-{day:02d}T00:00:{second:02d}Z"


class RevisionBundleTest(unittest.TestCase):
    def make(self, directory, histories, predecessors):
        raw = Path(directory) / "raw"
        raw.mkdir()
        responses = []
        for number, (title, revisions) in enumerate(histories):
            payload = {"query": {"pages": [{"pageid": 100 + number, "title": title, "revisions": revisions}]}}
            data = json.dumps(payload).encode()
            name = f"raw/{len(responses):05d}-history-{number:03d}.json"
            (Path(directory) / name).write_bytes(data)
            responses.append({"file": name, "sha256": hashlib.sha256(data).hexdigest()})
        payload = {"query": {"pages": [{"pageid": 1, "revisions": list(predecessors.values())}]}}
        data = json.dumps(payload).encode()
        name = f"raw/{len(responses):05d}-parents-000.json"
        (Path(directory) / name).write_bytes(data)
        responses.append({"file": name, "sha256": hashlib.sha256(data).hexdigest()})
        manifest = {"protocol_sha256": hashlib.sha256((ROOT / "experiments/revision_bundles/protocol.json").read_bytes()).hexdigest(),
                    "histories": [{"selector": {}, "pageid": 100 + k, "title": t, "revisions": r, "stratum": "vital"}
                                  for k, (t, r) in enumerate(histories)],
                    "predecessors": {str(k): v for k, v in predecessors.items()}, "responses": responses}
        (Path(directory) / "collection.json").write_text(json.dumps(manifest))
        return derive.load(Path(directory))

    def test_timeline_returns_and_hidden_change(self):
        before = {"revid": 1, "parentid": 0, "timestamp": "2023-12-01T00:00:00Z", "sha1": "a"}
        revisions = [
            {"revid": 2, "parentid": 1, "timestamp": stamp(2), "sha1": "b"},
            {"revid": 3, "parentid": 2, "timestamp": stamp(2, 30), "sha1": "a"},   # revert after 30 s
            {"revid": 4, "parentid": 3, "timestamp": stamp(5), "sha1": "a"},       # null revision
            {"revid": 5, "parentid": 4, "timestamp": stamp(5), "sha1": "c"},       # same second
            {"revid": 9, "parentid": 5, "timestamp": "2025-01-01T00:00:00Z", "sha1": "z"},  # outside
        ]
        with tempfile.TemporaryDirectory() as directory:
            manifest, predecessors = self.make(directory, [("P", revisions)], {1: before})
            window = ["2024-01-01T00:00:00Z", "2025-01-01T00:00:00Z"]
            states, hidden, existed = derive.timeline(manifest["histories"][0], predecessors, window)
        self.assertTrue(existed)
        self.assertFalse(hidden)
        self.assertEqual([s[1] for s in states], [1, 2, 3, 5])
        page = derive.Page("P", "vital", states, window)
        events = derive.returns(page)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["departure_seconds"], 30)
        start = derive.seconds(window[0])
        day = 86400
        i, j = page.index(start + day - 3600), page.index(start + 3 * day - 3600)
        self.assertEqual(page.shas[i], page.shas[j])
        self.assertLessEqual(page.next_diff[i], j)        # equal hash, hidden change
        self.assertNotEqual(page.revids[i], page.revids[j])  # revision IDs differ

    def test_methods_on_a_constructed_bundle(self):
        # Page A departs and returns while page B holds a value only during A's departure.
        a = derive.Page("A", "vital", [(0, 1, "a"), (100, 2, "x"), (200, 3, "a")], ["2024-01-01T00:00:00Z", "2025-01-01T00:00:00Z"])
        b = derive.Page("B", "vital", [(0, 4, "b"), (90, 5, "y"), (210, 6, "b")], ["2024-01-01T00:00:00Z", "2025-01-01T00:00:00Z"])
        outcome = derive.run_methods([a, b], 50, 50, [0.0] * 4)
        # Reads: A at 50, B at 100, B at 150, A at 200 (double collect).
        self.assertTrue(outcome["hash_bridge"]["certified"])
        self.assertFalse(outcome["hash_bridge"]["g1"])   # (a, y) never holds in [101, 150)
        self.assertFalse(outcome["hash_bridge"]["g2"])
        self.assertFalse(outcome["id_bridge"]["certified"])
        self.assertFalse(outcome["id_exact"]["certified"])

    def test_failure_notions_are_nested(self):
        window = ["2024-01-01T00:00:00Z", "2025-01-01T00:00:00Z"]
        a = derive.Page("A", "vital", [(0, 1, "a"), (100, 2, "x"), (200, 3, "a")], window)
        # B holds y exactly while A is away: the certified combination (a, y) never held.
        b = derive.Page("B", "vital", [(0, 4, "b"), (100, 5, "y"), (200, 6, "b")], window)
        groups = addendum.capture(addendum.plan_double([a, b]), 50, 50, [0.0] * 4)
        outcome = addendum.bridge(groups, addendum.sha, closed=True)
        self.assertTrue(outcome["certified"])
        self.assertFalse(outcome["g2"])
        claim, g1, held = addendum2.assess(groups, True, True)
        self.assertEqual((claim, g1, held), (False, False, False))
        # B also holds y before A departs: the claimed interval fails, the capture does not.
        b2 = derive.Page("B", "vital", [(0, 4, "b"), (90, 5, "y"), (210, 6, "b")], window)
        groups = addendum.capture(addendum.plan_double([a, b2]), 50, 50, [0.0] * 4)
        claim, g1, held = addendum2.assess(groups, True, True)
        self.assertEqual((claim, g1, held), (False, False, True))
        # The field-aware schedule reads the hash-only page once, at the center.
        result = addendum2.run(addendum, [a, b2], 50, 50, [0.0] * 4)
        self.assertIn("mixed_center_theorem", result)


if __name__ == "__main__":
    unittest.main()
