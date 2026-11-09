"""Bind no-edit pages' initial states to their recorded API responses."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "revision_before_window_derive", ROOT / "experiments/revision_bundles/derive.py")
derive = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(derive)


class BeforeWindowProvenanceTest(unittest.TestCase):
    def test_manifest_cannot_replace_a_no_edit_pages_initial_state(self):
        before = {"revid": 17, "parentid": 16, "timestamp": "2023-12-01T00:00:00Z", "sha1": "a"}
        with tempfile.TemporaryDirectory() as directory:
            collection = Path(directory)
            (collection / "raw").mkdir()
            responses = []
            for stem, revisions in (("history", []), ("before", [before])):
                payload = {"query": {"pages": [{"pageid": 100, "title": "Stable page", "revisions": revisions}]}}
                data = json.dumps(payload).encode()
                name = f"raw/{len(responses):05d}-{stem}-000.json"
                (collection / name).write_bytes(data)
                responses.append({"file": name, "sha256": hashlib.sha256(data).hexdigest()})
            manifest = {
                "protocol_sha256": hashlib.sha256((derive.HERE / "protocol.json").read_bytes()).hexdigest(),
                "histories": [{"pageid": 100, "title": "Stable page", "stratum": "vital",
                               "revisions": [], "before_window": before}],
                "predecessors": {}, "responses": responses,
            }
            path = collection / "collection.json"
            path.write_text(json.dumps(manifest))
            observed, _ = derive.load(collection)
            self.assertEqual(observed["histories"][0]["before_window"]["sha1"], "a")

            # The byte-identical API responses still say "a". Changing only the
            # manifest must not substitute "b" as the page's year-long state.
            manifest["histories"][0]["before_window"]["sha1"] = "b"
            path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "before-window value"):
                derive.load(collection)


if __name__ == "__main__":
    unittest.main()
