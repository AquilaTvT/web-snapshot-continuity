"""Independent adversarial checks of frozen revision provenance and selection."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import urlencode

from scripts.run_revision_audit import API, load_pages, load_witness_contents
from src.revision_history import audit_rows, verify_byte_witness


class RevisionProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.raw = Path(self.temp.name)
        self.bodies = [b"alpha", b"alpha", b"beta", b"alpha", b"gamma", b"alpha"]
        self.rows = [{"revid": i + 1, "parentid": i,
                      "timestamp": f"2024-01-01T00:00:0{i}Z",
                      "sha1": hashlib.sha1(body).hexdigest(), "size": len(body)}
                     for i, body in enumerate(self.bodies)]
        self.base = {"action": "query", "prop": "revisions", "titles": "Example", "redirects": "1",
                     "rvprop": "ids|timestamp|sha1|size", "rvlimit": "500", "rvdir": "newer",
                     "rvstart": "2024-01-01T00:00:00Z", "rvend": "2025-01-01T00:00:00Z",
                     "formatversion": "2", "format": "json"}
        continuation = {"continue": "||", "rvcontinue": "20240101000003|4"}
        batch1 = self.record("first.json", {"query": {"pages": [self.page(self.rows[:3])]},
                                             "continue": continuation}, self.base)
        batch2 = self.record("second.json", {"batchcomplete": True,
                            "query": {"pages": [self.page(self.rows[3:])]}}, {**self.base, **continuation})
        self.collection = {"schema": 1, "api": API, "titles": ["Example"],
                           "window": [self.base["rvstart"], self.base["rvend"]],
                           "pages": [{"requested_title": "Example", "returned_title": "Example",
                                      "pageid": 10, "batches": [batch1, batch2], "revision_count": 6}]}
        self.save_collection()
        ids = [2, 3, 4]
        revisions = []
        for revision_id in ids:
            row = dict(self.rows[revision_id - 1])
            row["slots"] = {"main": {"contentmodel": "wikitext", "contentformat": "text/x-wiki",
                                     "content": self.bodies[revision_id - 1].decode()}}
            revisions.append(row)
        query = {"action": "query", "prop": "revisions", "revids": "2|3|4",
                 "rvprop": "ids|timestamp|sha1|content", "rvslots": "main",
                 "formatversion": "2", "format": "json"}
        self.metadata = self.record("witness-content.json", {"batchcomplete": True,
                                   "query": {"pages": [self.page(revisions)]}}, query)
        self.metadata.update({"witnesses": [{"title": "Example", "revision_ids": ids}],
                              "revision_urls": [f"https://en.wikipedia.org/w/index.php?oldid={i}" for i in ids]})
        self.save_metadata()

    @staticmethod
    def page(rows):
        return {"pageid": 10, "title": "Example", "revisions": rows}

    def record(self, name, payload, query):
        data = (json.dumps(payload) + "\n").encode()
        (self.raw / name).write_bytes(data)
        return {"file": name, "url": API + "?" + urlencode(query),
                "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}

    def save_collection(self):
        (self.raw / "collection.json").write_text(json.dumps(self.collection))

    def save_metadata(self):
        (self.raw / "witness-collection.json").write_text(json.dumps(self.metadata))

    def mutate_payload(self, record, mutation):
        path = self.raw / record["file"]
        payload = json.loads(path.read_text())
        mutation(payload)
        data = (json.dumps(payload) + "\n").encode()
        path.write_bytes(data)
        record.update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())

    def test_first_return_and_bytes_are_independent_of_later_hash_returns(self):
        _, pages = load_pages(self.raw)
        report = audit_rows(pages[0][1])
        self.assertEqual([item["revision_ids"] for item in report["returns"]], [[2, 3, 4], [4, 5, 6]])
        self.assertEqual(report["declared_path_minimum_auxiliary_labels"], 3)
        contents, _ = load_witness_contents(self.raw, pages)
        self.assertEqual(set(contents), {2, 3, 4})
        self.assertTrue(verify_byte_witness([2, 3, 4], contents))
        self.assertFalse(verify_byte_witness([4, 5, 6], contents))

    def test_semantic_request_change_is_not_covered_by_response_hash(self):
        for field, value in (("rvdir", "older"), ("rvstart", "2023-01-01T00:00:00Z"),
                             ("titles", "Other"), ("rvprop", "ids|timestamp"), ("continue", "stray")):
            with self.subTest(field=field):
                batch = self.collection["pages"][0]["batches"][0]
                batch["url"] = API + "?" + urlencode({**self.base, field: value})
                self.save_collection()
                with self.assertRaises(ValueError):
                    load_pages(self.raw)
        batch["url"] = "https://example.org/w/api.php?" + urlencode(self.base)
        self.save_collection()
        with self.assertRaises(ValueError):
            load_pages(self.raw)

    def test_broken_continuation_and_truncated_enumeration(self):
        batches = self.collection["pages"][0]["batches"]
        batches[1]["url"] = API + "?" + urlencode({**self.base, "continue": "||", "rvcontinue": "wrong"})
        self.save_collection()
        with self.assertRaises(ValueError):
            load_pages(self.raw)
        self.collection["pages"][0]["batches"] = batches[:1]
        self.collection["pages"][0]["revision_count"] = 3
        self.save_collection()
        with self.assertRaises(ValueError):
            load_pages(self.raw)

    def test_parent_gap_is_reported_without_claiming_complete_history(self):
        batch = self.collection["pages"][0]["batches"][1]
        self.mutate_payload(batch, lambda response: response["query"]["pages"][0]["revisions"][0].update(parentid=99))
        self.save_collection()
        _, pages = load_pages(self.raw)
        result = audit_rows(pages[0][1])
        self.assertFalse(result["consecutive_parent_links"])
        self.assertEqual(result["hash_return_count"], 2)
        with self.assertRaises(ValueError):
            load_witness_contents(self.raw, pages)

    def test_outside_window_or_hidden_revision_rejected_even_with_updated_manifest(self):
        batch = self.collection["pages"][0]["batches"][1]
        self.mutate_payload(batch, lambda response: response["query"]["pages"][0]["revisions"][-1].update(timestamp="2025-02-01T00:00:00Z"))
        self.save_collection()
        with self.assertRaises(ValueError):
            load_pages(self.raw)
        self.mutate_payload(batch, lambda response: response["query"]["pages"][0]["revisions"][-1].update(timestamp="2024-01-01T00:00:05Z", sha1hidden=True))
        self.save_collection()
        with self.assertRaises(ValueError):
            load_pages(self.raw)

    def test_witness_selection_cannot_be_changed_to_a_convenient_later_return(self):
        _, pages = load_pages(self.raw)
        self.metadata["witnesses"][0]["revision_ids"] = [4, 5, 6]
        self.save_metadata()
        with self.assertRaises(ValueError):
            load_witness_contents(self.raw, pages)

    def test_duplicate_content_revision_is_not_silently_overwritten(self):
        _, pages = load_pages(self.raw)
        self.mutate_payload(self.metadata, lambda response: response["query"]["pages"][0]["revisions"].append(
            response["query"]["pages"][0]["revisions"][0]))
        self.save_metadata()
        with self.assertRaises(ValueError):
            load_witness_contents(self.raw, pages)

    def test_missing_selected_bytes_do_not_turn_into_unverified_success(self):
        _, pages = load_pages(self.raw)
        self.mutate_payload(self.metadata, lambda response: response["query"]["pages"][0]["revisions"].pop())
        self.save_metadata()
        with self.assertRaises(ValueError):
            load_witness_contents(self.raw, pages)
        (self.raw / "witness-content.json").unlink()
        with self.assertRaises(ValueError):
            load_witness_contents(self.raw, pages)

    def test_source_page_identity_and_suppression_are_checked(self):
        _, pages = load_pages(self.raw)
        self.mutate_payload(self.metadata, lambda response: response["query"]["pages"][0].update(pageid=11))
        self.save_metadata()
        with self.assertRaises(ValueError):
            load_witness_contents(self.raw, pages)
        self.mutate_payload(self.metadata, lambda response: response["query"]["pages"][0].update(pageid=10))
        self.mutate_payload(self.metadata, lambda response: response["query"]["pages"][0]["revisions"][0]["slots"]["main"].update(texthidden=True))
        self.save_metadata()
        with self.assertRaises(ValueError):
            load_witness_contents(self.raw, pages)

    def test_malformed_core_inputs_fail_without_accepting_alias_ids(self):
        for ids in (None, [True, 2, 3], [[], 2, 3], [0, 2, 3], [1, 1, 3]):
            with self.subTest(ids=ids):
                self.assertFalse(verify_byte_witness(ids, {1: b"a", 2: b"b", 3: b"a"}))
        for field, value in (("sha1", None), ("timestamp", None), ("sha1hidden", False), ("parentid", 1)):
            row = dict(self.rows[0], **{field: value})
            with self.subTest(field=field), self.assertRaises(ValueError):
                audit_rows([row])


if __name__ == "__main__":
    unittest.main()
