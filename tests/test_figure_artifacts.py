import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIGURES = ROOT / "figure-artifacts"
TABLES = ROOT / "table-artifacts"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FigureArtifactTests(unittest.TestCase):
    def directories(self):
        found = sorted(p for p in list(FIGURES.glob("[0-9]*")) + list(TABLES.glob("[0-9]*")) if p.is_dir())
        self.assertTrue(found)
        return found

    def test_manifests_cover_the_files_they_list(self):
        for directory in self.directories():
            lines = (directory / "MANIFEST.sha256").read_text().splitlines()
            self.assertTrue(lines, directory.name)
            for line in lines:
                digest, name = line.split("  ", 1)
                self.assertEqual(sha256(directory / name), digest, f"{directory.name}/{name}")

    def test_recorded_source_hashes_and_captions(self):
        for directory in self.directories():
            if not (directory / "figure.json").exists():
                continue
            meta = json.loads((directory / "figure.json").read_text())
            for name, digest in meta.get("data_sources", {}).items():
                self.assertEqual(sha256(directory / name), digest, f"{directory.name}/{name}")
            if (directory / "caption.txt").exists():
                self.assertEqual((directory / "caption.txt").read_text().strip(), meta["caption"], directory.name)

    def test_figure_two_ships_the_replay_code_and_data_unchanged(self):
        figure = FIGURES / "06-revision-histories"
        replay = ROOT / "experiments" / "revision_bundles"
        pairs = {"analysis.py": "derive.py", "analysis_addendum.py": "addendum.py",
                 "analysis_addendum2.py": "addendum2.py", "protocol.json": "protocol.json",
                 "protocol-addendum.json": "protocol-addendum.json",
                 "protocol-addendum-2.json": "protocol-addendum-2.json"}
        for copy, source in pairs.items():
            self.assertEqual((figure / copy).read_bytes(), (replay / source).read_bytes(), copy)
        shipped = sorted(p.relative_to(figure / "collection") for p in (figure / "collection").rglob("*") if p.is_file())
        original = sorted(p.relative_to(replay / "data") for p in (replay / "data").rglob("*") if p.is_file())
        self.assertEqual(shipped, original)
        for name in original:
            self.assertEqual(sha256(figure / "collection" / name), sha256(replay / "data" / name), str(name))


if __name__ == "__main__":
    unittest.main()
