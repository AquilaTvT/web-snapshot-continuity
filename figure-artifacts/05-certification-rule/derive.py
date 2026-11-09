"""Rebuild plot-data.csv: panel a from the native MinIO trace, panel b from construction.json.

Panel a uses the recorded two-page bundle case (requests 31-50 of trace.json):
every plotted state, capture window, version ID and mutation window is read
from the raw responses here, and the claims are checked: equal IDs at both
captures of each page, overlapping equality bridges, and no stable phase or
possible instant with the captured pair (eligible, 10). Panel b checks the
pairwise test on a palindrome of 2n-1 captures: every revisited resource is
present between its first-window end and last-window start in every consistent
history, the singly read resource's window lies inside all of those intervals,
and so its read instant, which differs between histories, is a common instant.
Standard library only.
"""
from pathlib import Path
from fractions import Fraction as F
import base64, csv, hashlib, json

ROOT = Path(__file__).resolve().parent
TRACE_SHA256 = "5f3536c69d2b9171986042547126409286535a04bd2d02c05f871d70dc023537"
raw = (ROOT / "trace.json").read_bytes()
assert hashlib.sha256(raw).hexdigest() == TRACE_SHA256, "trace.json is not the archived MinIO execution"
trace = json.loads(raw)
records = {r["index"]: r for r in trace["requests"]}
case = next(c for c in trace["cases"] if c["name"] == "two_object_bundle")


def info(i):
    r = records[i]
    headers = {k.lower(): v for k, v in r["response"]["headers"].items()}
    body = base64.b64decode(r["response"]["body_base64"])
    assert hashlib.sha256(body).hexdigest() == r["response"]["body_sha256"]
    start, end = (F(x, 10**6) for x in r["read_window_ns"])  # milliseconds
    return dict(status=r["response"]["status"], vid=headers.get("x-amz-version-id"),
                body=body.decode().strip(), start=start, end=end, label=r["label"], method=r["request"]["method"])


def find(label):
    return next(i for i, r in records.items() if r["label"] == label)


key_of = {"admission": "bundle-admission", "fee": "bundle-fee"}
puts = {"admission": find("bundle: initial admission"), "fee": find("bundle: initial fee")}
mutations = {"admission": [find("bundle: change admission first"), find("bundle: restore admission second")],
             "fee": [find("bundle: change fee second"), find("bundle: restore fee first")]}
captures = {"admission": [find("bundle: capture A1"), find("bundle: capture A2")],
            "fee": [find("bundle: capture B1"), find("bundle: capture B2")]}
assert case["captures"] == [captures["admission"][0], captures["fee"][0], captures["fee"][1], captures["admission"][1]]
alias = {}
rows = []
origin = info(puts["admission"])["end"]
for page in ("admission", "fee"):
    first, change, restore = info(puts[page]), info(mutations[page][0]), info(mutations[page][1])
    assert first["status"] == change["status"] == 200 and restore["status"] == 204 and restore["method"] == "DELETE"
    # The restore deletes the changed version by ID; the original ID becomes current again.
    assert records[mutations[page][1]]["request"]["url"].endswith("versionId=" + change["vid"])
    states = [(first["end"], change["start"], first["vid"]), (change["end"], restore["start"], change["vid"]),
              (restore["end"], info(captures["admission"][1])["end"], first["vid"])]
    bodies = {first["vid"]: info(captures[page][0])["body"] if page == "admission" else "100",
              change["vid"]: "ineligible" if page == "admission" else "10"}
    for vid in (first["vid"], change["vid"]):
        alias.setdefault(vid, "αβγδ"[len(alias)])
    for start, end, vid in states:
        rows.append(dict(panel="a", kind="segment", resource=page, start=float(start), end=float(end),
                         value=bodies[vid], identifier=alias[vid], native_id=vid, target=""))
    for i in mutations[page]:
        m = info(i)
        rows.append(dict(panel="a", kind="mutation", resource=page, start=float(m["start"]), end=float(m["end"]),
                         value=m["method"], identifier="", native_id=m["vid"], target=""))
    for i in captures[page]:
        c = info(i)
        assert c["status"] == 200
        rows.append(dict(panel="a", kind="capture", resource=page, start=float(c["start"]), end=float(c["end"]),
                         value=c["body"], identifier=alias[c["vid"]], native_id=c["vid"], target="1"))
# Claims for panel a.
cap = {p: [info(i) for i in captures[p]] for p in captures}
assert cap["admission"][0]["vid"] == cap["admission"][1]["vid"] and cap["admission"][0]["body"] == "eligible"
assert cap["fee"][0]["vid"] == cap["fee"][1]["vid"] and cap["fee"][0]["body"] == "10"
low = max(cap[p][0]["end"] for p in cap); high = min(cap[p][1]["start"] for p in cap)
assert low < high, "equality bridges must overlap"
# Admission leaves 'eligible' no later than its change completes and returns no earlier than its restore starts;
# fee holds '10' no earlier than its change starts and no later than its restore completes.
adm_out = (info(mutations["admission"][0])["end"], info(mutations["admission"][1])["start"])
fee_ten = (info(mutations["fee"][0])["start"], info(mutations["fee"][1])["end"])
assert adm_out[0] <= fee_ten[0] and fee_ten[1] <= adm_out[1], "the pair (eligible, 10) must be impossible at any instant"
for phase in case["phases"]:
    a, b = (info(i)["body"] for i in phase["observations"])
    assert (a, b) != ("eligible", "10")
rows.append(dict(panel="a", kind="claimed", resource="", start=float(low), end=float(high), value="", identifier="",
                 native_id="", target=""))
# Panel b: construction.
design = json.loads((ROOT / "construction.json").read_text())["panels"]["b"]
for resource, spec in design["resources"].items():
    for start, end, value, ident in spec["segments"]:
        rows.append(dict(panel="b", kind="segment", resource=resource, start=start, end=end, value=value,
                         identifier=ident, native_id="", target="1"))
windows = {}
for resource, start, end in design["captures"]:
    windows.setdefault(resource, []).append((F(str(start)), F(str(end))))
    rows.append(dict(panel="b", kind="capture", resource=resource, start=start, end=end, value="",
                     identifier="", native_id="", target="1"))
n = len(windows)
assert sum(map(len, windows.values())) == 2 * n - 1 and sorted(map(len, windows.values())) == [1] + [2] * (n - 1)
first = {r: w[0][1] for r, w in windows.items()}; last = {r: w[-1][0] for r, w in windows.items()}
assert all(first[i] <= last[j] for i in windows for j in windows if i != j)
twice = [r for r in windows if len(windows[r]) == 2]
lo, hi = max(first[r] for r in twice), min(last[r] for r in twice)
single = next(r for r in windows if len(windows[r]) == 1)
assert lo <= windows[single][0][0] and windows[single][0][1] <= hi
for r in twice:
    # Certain presence of a revisited resource with a sound field, in every consistent history.
    rows.append(dict(panel="b", kind="presence", resource=r, start=float(first[r]), end=float(last[r]), value="",
                     identifier="", native_id="", target="1"))
# The interval on which every revisited resource is present in every history.
rows.append(dict(panel="b", kind="revisited_common", resource="", start=float(lo), end=float(hi), value="",
                 identifier="", native_id="", target=""))
schematic = json.loads((ROOT / "construction.json").read_text())["panels"]["b"]["schematic_read"]
assert schematic["resource"] == single
t_star = F(str(schematic["instant"]))
s_win, e_win = windows[single][0]
assert s_win < t_star < e_win, "the schematic read instant must lie strictly inside the single window"
rows.append(dict(panel="b", kind="schematic_read", resource=single, start=float(t_star), end=float(t_star), value="",
                 identifier="", native_id="", target=""))
with (ROOT / "plot-data.csv").open("w", newline="") as stream:
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
print("plot-data.csv", len(rows), "rows; bridges overlap", float(high - low) * 1000, "microseconds")
