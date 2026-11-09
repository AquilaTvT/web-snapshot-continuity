"""Rebuild plot-data.csv from the frozen revision collection in this directory.

analysis.py, analysis_addendum.py and analysis_addendum2.py are unmodified
copies of experiments/revision_bundles/derive.py, addendum.py and
addendum2.py. They check every raw response hash, rebuild the histories from
the raw files and compute the preregistered measurements (protocol.json) and
the two post hoc addenda (protocol-addendum.json, protocol-addendum-2.json).
This script selects the plotted rows: panel a, hidden-change shares by
stratum and revisit gap; panel b, eight vital pages with request starts one
hour apart, by method, with the continuity, claim and existence checks of the
second addendum. Standard library only.
"""
from pathlib import Path
import csv
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
with tempfile.TemporaryDirectory() as directory:
    out = Path(directory)
    subprocess.run([sys.executable, "-B", str(ROOT / "analysis.py"), "--collection", str(ROOT / "collection"),
                    "--output", directory], check=True, stdout=subprocess.DEVNULL)
    subprocess.run([sys.executable, "-B", str(ROOT / "analysis_addendum.py"), "--collection",
                    str(ROOT / "collection"), "--output", directory, "--base", str(ROOT / "analysis.py"),
                    "--preregistered", str(out / "bundles.csv")], check=True, stdout=subprocess.DEVNULL)
    subprocess.run([sys.executable, "-B", str(ROOT / "analysis_addendum2.py"), "--collection",
                    str(ROOT / "collection"), "--output", directory, "--base", str(ROOT / "analysis.py"),
                    "--first", str(ROOT / "analysis_addendum.py"), "--reproduce", str(out / "addendum.csv")],
                   check=True, stdout=subprocess.DEVNULL)
    hidden = list(csv.DictReader(open(out / "hidden-change.csv", newline="")))
    second = list(csv.DictReader(open(out / "addendum-2.csv", newline="")))
rows = []
for r in hidden:
    assert int(r["equal_revid_hidden_change"]) == 0
    rows.append(dict(panel="a", stratum=r["stratum"], gap_seconds=r["gap_seconds"], n="", method="content hash",
                     pairs=r["pairs"], count=r["equal_hash"], hits=r["equal_hash_hidden_change"], value=r["ratio"],
                     ci_low=r["ci_low"], ci_high=r["ci_high"], runs="", certified="", continuity_violations="",
                     claim_violations="", preregistered_g1_violations="", fictitious=""))
methods = ("id_double_closed", "id_drop_center", "id_exact", "hash_double_closed", "hash_exact",
           "mixed_center_theorem", "mixed_offcenter_theorem")
pick = {r["method"]: r for r in second
        if r["stratum"] == "vital" and r["n"] == "8" and r["gap_seconds"] == "3600" and r["method"] in methods}
for method in methods:
    r = pick[method]
    if method.startswith("id_") or method.startswith("mixed_"):
        assert r["continuity_violations"] == r["claim_violations"] == r["fictitious"] == "0", method
    rows.append(dict(panel="b", stratum="vital", gap_seconds="3600", n="8", method=method, pairs="", count="",
                     hits="", value=int(r["certified"]) / int(r["runs"]), ci_low="", ci_high="", runs=r["runs"],
                     certified=r["certified"], continuity_violations=r["continuity_violations"],
                     claim_violations=r["claim_violations"],
                     preregistered_g1_violations=r["preregistered_g1_violations"], fictitious=r["fictitious"]))
# The certificates that content hashes add to revision IDs are exactly the ones that broke continuity.
for hashed, ids in (("hash_double_closed", "id_double_closed"), ("hash_exact", "id_exact")):
    assert int(pick[hashed]["certified"]) - int(pick[ids]["certified"]) == int(pick[hashed]["continuity_violations"])
assert pick["mixed_offcenter_theorem"]["certified"] == "0"
with (ROOT / "plot-data.csv").open("w", newline="") as stream:
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
print("plot-data.csv", len(rows), "rows")
