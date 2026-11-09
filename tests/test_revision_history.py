"""Small exhaustive and malformed-input checks for the revision audit."""
import hashlib
import itertools
import unittest

from src.revision_history import audit_rows, verify_byte_witness


def rows_for(values):
    return [{"revid": index + 1, "parentid": index,
             "timestamp": f"2024-01-01T00:00:{index:02d}Z",
             "sha1": hashlib.sha1(value.encode()).hexdigest()}
            for index, value in enumerate(values)]


class RevisionHistoryTests(unittest.TestCase):
    def test_exhaustive_return_witnesses(self):
        for length in range(1, 7):
            for values in itertools.product("abc", repeat=length):
                rows = rows_for(values)
                result = audit_rows(rows)
                # Enumerate endpoint pairs rather than running the last-seen
                # algorithm: these are consecutive occurrences of one body.
                expected = [(i, i + 1, j) for i in range(length) for j in range(i + 2, length)
                            if values[i] == values[j]
                            and all(values[k] != values[i] for k in range(i + 1, j))]
                actual = [tuple(w["indices"]) for w in result["returns"]]
                self.assertEqual(sorted(actual), sorted(expected))
                self.assertTrue(result["consecutive_parent_links"])

    def test_repeated_unchanged_revisions_and_clock_ties(self):
        rows = rows_for("aabba")
        rows[3]["timestamp"] = rows[2]["timestamp"]
        result = audit_rows(rows)
        self.assertEqual(result["hash_return_count"], 1)
        self.assertEqual(result["returns"][0]["revision_ids"], [2, 3, 5])
        self.assertEqual(result["content_runs"], 3)
        self.assertEqual(result["equal_timestamp_pairs"], 1)
        rows[2]["parentid"] = 99
        self.assertFalse(audit_rows(rows)["consecutive_parent_links"])

    def test_malformed_metadata_is_not_treated_as_new_content(self):
        with self.assertRaises(ValueError):
            audit_rows([])
        for field, replacement in (("sha1", ""), ("sha1", "hidden"),
                                   ("timestamp", "2024-01-01"), ("parentid", -1),
                                   ("revid", True), ("revid", 0)):
            rows = rows_for("aba")
            rows[1][field] = replacement
            with self.subTest(field=field, value=replacement), self.assertRaises(ValueError):
                audit_rows(rows)
        rows = rows_for("aba")
        rows[1]["revid"] = rows[0]["revid"]
        with self.assertRaises(ValueError):
            audit_rows(rows)
        rows = rows_for("aba")
        rows[2]["timestamp"] = "2023-01-01T00:00:00Z"
        with self.assertRaises(ValueError):
            audit_rows(rows)

    def test_byte_witness_cannot_be_replaced_by_hash_claim(self):
        self.assertTrue(verify_byte_witness([1, 2, 3], {1: b"a", 2: b"b", 3: b"a"}))
        self.assertFalse(verify_byte_witness([1, 2, 3], {1: b"a", 2: b"b", 3: b"c"}))
        self.assertFalse(verify_byte_witness([1, 2, 3], {1: b"a", 2: b"a", 3: b"a"}))
        self.assertFalse(verify_byte_witness([1, 2, 3], {1: "a", 2: "b", 3: "a"}))
        self.assertFalse(verify_byte_witness([1, 2, 1], {1: b"a", 2: b"b"}))
        self.assertFalse(verify_byte_witness([1, 2, 3], {1: b"a", 2: b"b"}))


if __name__ == "__main__":
    unittest.main()
