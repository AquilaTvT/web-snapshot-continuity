"""Write the supplement's data tables and number macros from the derived evidence.

Every count printed in the supplement's tables comes from a derived file here,
so the tables cannot drift from the data. Output: paper/supplement/generated/.
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "paper" / "supplement" / "generated"
REV = ROOT / "experiments" / "revision_bundles" / "derived"

GAP = {1: "1\\,s", 60: "1\\,min", 3600: "1\\,h"}
METHOD = {
    "hash_bridge": "content hash, $2n$, half-open$^{\\ast}$",
    "id_bridge": "revision ID, $2n$, half-open$^{\\ast}$",
    "id_exact": "revision ID, exact, $2n{-}1^{\\ast}$",
    "hash_double_closed": "content hash, $2n$, closed",
    "id_double_closed": "revision ID, $2n$, closed",
    "id_drop_center": "revision ID, center read once",
    "hash_exact": "content hash, exact, $2n{-}1$",
    "mixed_offcenter_trusting": "hash page at the ends, trusted",
    "mixed_offcenter_theorem": "hash page at the ends, Theorem~3",
    "mixed_center_theorem": "hash page at the center, Theorem~3",
}
ORDER = ["hash_bridge", "id_bridge", "id_exact", "hash_double_closed", "id_double_closed",
         "id_drop_center", "hash_exact", "mixed_offcenter_trusting", "mixed_offcenter_theorem",
         "mixed_center_theorem"]


def rows(path: Path) -> list[dict]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def num(value) -> str:
    return f"{int(value):,}"


def pct(value: float) -> str:
    value *= 100
    if value < 0.01:
        return "${<}0.01$"
    return f"{value:.2f}"


def table(name: str, spec: str, head: str, body: list[str]) -> None:
    lines = [f"\\begin{{tabular}}{{{spec}}}", "\\toprule", head + " \\\\", "\\midrule"]
    lines += [line + " \\\\" for line in body]
    lines += ["\\bottomrule", "\\end{tabular}"]
    (OUT / f"{name}.tex").write_text("\n".join(lines) + "\n")


def hidden_change() -> None:
    body = []
    for r in rows(REV / "hidden-change.csv"):
        body.append(" & ".join([r["stratum"], GAP[int(r["gap_seconds"])] if int(r["gap_seconds"]) < 86400
                                else f"{int(r['gap_seconds']) // 86400}\\,d", num(r["pairs"]), num(r["equal_hash"]),
                                num(r["equal_hash_hidden_change"]),
                                f"{pct(float(r['ratio']))} ({pct(float(r['ci_low']))}--{pct(float(r['ci_high']))})",
                                f"{r['pages_with_hidden_change']} of {r['pages']}"]))
        assert int(r["equal_revid_hidden_change"]) == 0
    table("tab-hidden-change", "@{}llrrrlr@{}",
          "Stratum & Gap & Pairs & Equal hash & Hidden & Share, \\% (95\\% CI) & Pages", body)


def preregistered() -> None:
    methods = ("hash_bridge", "id_bridge", "id_exact")
    totals = defaultdict(lambda: [0, 0, 0, 0])
    by_n = {}
    for r in rows(REV / "bundles.csv"):
        key = (r["stratum"], int(r["gap_seconds"]), r["method"])
        for k, field in enumerate(("runs", "certified", "certified_violating_g1", "certified_violating_g2")):
            totals[key][k] += int(r[field])
        if r["stratum"] == "vital" and r["gap_seconds"] == "3600":
            by_n[(int(r["n"]), r["method"])] = r
    def cells(values):
        return " & ".join(num(v) for v in values)
    body = []
    for stratum in ("vital", "random"):
        for gap in (1, 60, 3600):
            body.append(f"{stratum}, {GAP[gap]}, all $n$ & " + " & ".join(
                cells(totals[(stratum, gap, m)][1:]) for m in methods))
    body.append("\\midrule\n" + " \\\\\n".join(
        f"vital, 1\\,h, $n={n}$ & " + " & ".join(
            cells([by_n[(n, m)]["certified"], by_n[(n, m)]["certified_violating_g1"],
                   by_n[(n, m)]["certified_violating_g2"]]) for m in methods) for n in (2, 4, 8)))
    head = ("Condition & \\multicolumn{3}{c}{Content hash, $2n$, half-open} & "
            "\\multicolumn{3}{c}{Revision ID, $2n$, half-open} & \\multicolumn{3}{c}{Revision ID, exact, $2n{-}1$} \\\\ "
            "\\cmidrule(lr){2-4}\\cmidrule(lr){5-7}\\cmidrule(l){8-10}\n"
            " & Certified & G1 & G2 & Certified & G1 & G2 & Certified & G1 & G2")
    table("tab-preregistered", "@{}lrrrrrrrrr@{}", head, body)


def addendum() -> None:
    methods = ["hash_double_closed", "id_double_closed", "id_drop_center", "id_exact", "hash_exact",
               "mixed_offcenter_trusting", "mixed_offcenter_theorem"]
    cert = defaultdict(int)
    for r in rows(REV / "addendum.csv"):
        cert[(r["stratum"], int(r["gap_seconds"]), r["method"])] += int(r["certified"])
    body = []
    for stratum in ("vital", "random"):
        for gap in (1, 60, 3600):
            body.append(f"{stratum} & {GAP[gap]} & " + " & ".join(num(cert[(stratum, gap, m)]) for m in methods))
    head = ("Stratum & Gap & \\multicolumn{2}{c}{Double collect} & \\multicolumn{3}{c}{Revisit order} & "
            "\\multicolumn{2}{c}{Hash page at the ends} \\\\ \\cmidrule(lr){3-4}\\cmidrule(lr){5-7}\\cmidrule(l){8-9}\n"
            " & & hash & ID & ID, center once & ID & hash & trusted & Theorem~3")
    table("tab-addendum", "@{}llrrrrrrr@{}", head, body)


def assertions() -> None:
    fields = ("runs", "certified", "continuity_violations", "claim_violations",
              "preregistered_g1_violations", "fictitious")
    total = defaultdict(lambda: [0] * len(fields))
    eight = {}
    center = {}
    for r in rows(REV / "addendum-2.csv"):
        for k, field in enumerate(fields):
            total[r["method"]][k] += int(r[field])
        if r["stratum"] == "vital" and r["n"] == "8" and r["gap_seconds"] == "3600":
            eight[r["method"]] = [int(r[field]) for field in fields]
        if r["method"] in ("mixed_center_theorem", "id_exact"):
            center[(r["stratum"], int(r["n"]), int(r["gap_seconds"]), r["method"])] = r
    for r in rows(REV / "addendum-2.csv"):
        if r["method"] == "mixed_center_theorem":
            assert all(int(r[f]) == 0 for f in fields[2:]), r
    body = [f"{METHOD[m]} & " + " & ".join(num(v) for v in total[m][1:]) + " & "
            + " & ".join(num(v) for v in eight[m][1:]) for m in ORDER]
    head = ("Method & \\multicolumn{5}{c}{All conditions, 72{,}000 runs} & "
            "\\multicolumn{5}{c}{Eight vital pages, 1\\,h, 4{,}000 runs} \\\\ "
            "\\cmidrule(lr){2-6}\\cmidrule(l){7-11}\n"
            " & Certified & Continuity & Claim & G1 & Fictitious & Certified & Continuity & Claim & G1 & Fictitious")
    table("tab-assertions", "@{}lrrrrrrrrrr@{}", head, body)
    body = []
    for stratum in ("vital", "random"):
        for n in (2, 4, 8):
            body.append(f"{stratum} & {n} & " + " & ".join(
                f"{num(center[(stratum, n, gap, 'mixed_center_theorem')]['certified'])} / "
                f"{num(center[(stratum, n, gap, 'id_exact')]['certified'])}" for gap in (1, 60, 3600)))
    table("tab-hash-center", "@{}lrrrr@{}",
          f"Stratum & $n$ & {GAP[1]} & {GAP[60]} & {GAP[3600]}", body)
    return total


def contracts() -> None:
    body = []
    for r in rows(ROOT / "data" / "derived" / "contracts-summary.csv"):
        outcome = {"return": "hidden return", "read_fidelity": "unfaithful read"}[r["failure"]] \
            if r["safe_in_model"] != "True" else "safe"
        if r["safe_in_model"] == "True":
            shortest = "--"
        else:
            shortest = r["shortest_counterexample_edges"]
        name = r["name"].replace("_", "\\_")
        body.append(f"\\texttt{{{name}}} & {r['states']} & {r['edges']} & {outcome} & {shortest}")
        assert r["verified"] == "True"
    table("tab-contracts", "@{}lrrlr@{}", "Model & States & Edges & Verdict & Shortest violation", body)


def http() -> None:
    mac = rows(ROOT / "data" / "derived" / "http_stacks.csv")
    linux = {r["case"]: r for r in rows(ROOT / "data" / "derived" / "http_stacks_linux.csv")}
    label = {"express-weak": "Express, weak ETag", "express-strong": "Express, strong ETag",
             "python-fresh": "Python, advancing mtime", "python-restored": "Python, restored mtime",
             "apache-fresh": "Apache, advancing mtime", "apache-restored": "Apache, restored mtime"}
    body = []
    for r in mac:
        other = linux[r["case"]]
        same = all(other[k] == r[k] for k in r if k != "case")
        body.append(f"{label[r['case']]} & {'yes' if r['endpoint_validator_equal'] == 'True' else 'no'} & "
                    f"{r['conditional_status']} & {'yes' if r['target_bundle_ever_present'] == 'True' else 'no'} & "
                    f"{'same' if same else 'differs'}")
    table("tab-http", "@{}lllll@{}", "Configuration & Repeats & Status & Pair served & Linux", body)


def probes() -> None:
    summary = json.loads((ROOT / "experiments" / "reactivation_probes" / "derived" / "summary.json").read_text())
    body = []
    import re
    for key, impl in summary["implementations"].items():
        # The first dotted release number (or MinIO's RELEASE tag) in the recorded version string.
        match = re.search(r"RELEASE\.[0-9TZ-]+|v?\d+\.\d+(\.\d+)?", impl["version"])
        assert match, impl["version"]
        version = match.group(0).lstrip("v")
        body.append(f"{impl['implementation'].split(' (')[0]} & \\texttt{{{version}}} & {impl['requests']}")
    table("tab-probe-versions", "@{}llr@{}", "Implementation & Version & Requests", body)


def numbers(total) -> None:
    audit = json.loads((ROOT / "data" / "derived" / "certification-audit.json").read_text())
    summary = json.loads((REV / "summary.json").read_text())
    desc = {d["stratum"]: d for d in summary["descriptive"]}
    macros = {
        "sReturnEventsVital": num(desc["vital"]["return_events"]),
        "sReturnEventsRandom": num(desc["random"]["return_events"]),
        "sReturnEvents": num(desc["vital"]["return_events"] + desc["random"]["return_events"]),
        "sPagesReturnVital": str(desc["vital"]["pages_with_return"]),
        "sPagesReturnRandom": str(desc["random"]["pages_with_return"]),
        "sMedianVital": str(desc["vital"]["median_departure_seconds"]),
        "sMedianRandom": str(desc["random"]["median_departure_seconds"]),
        "sStatesVital": num(desc["vital"]["states"]),
        "sStatesRandom": num(desc["random"]["states"]),
        "sScheduleChecks": num(audit["sequential_schedules_vs_brute_force"]),
        "sScheduleCertified": num(audit["sequential_schedules_certified"]),
        "sWindowChecks": num(audit["random_overlapping_windows_vs_brute_force"]),
        "sMachineChecks": num(audit["explicit_state_machines_vs_rule"]),
        "sCnfChecks": num(audit["cnf_instances_for_hardness_construction"]),
        "sSweepChecks": num(audit["worst_case_sweep_vs_brute_force"]),
        "sSweepDeterministic": num(audit["worst_case_sweep_observation_deterministic"]),
        "sNoWorstCase": num(audit["random_contracts_without_worst_case"]),
        "sPatternChecks": num(audit["polynomial_worst_case_vs_enumeration"]),
        "sFixedChecks": num(audit["fixed_instant_schedules_vs_brute_force"]),
        "sFixedCertified": num(audit["fixed_instant_schedules_fixing_an_instant"]),
        "sRepairChecks": num(audit["repair_contracts_vs_all_labelings"]),
        "sRepairSound": num(audit["repair_contracts_with_a_sound_field"]),
        "sRefinementChecks": num(audit["finite_refinements_vs_component_criterion"]),
        "sRefinementFailing": num(audit["finite_refinements_of_contracts_without_a_sound_field"]),
        "sEpochChecks": num(audit["s3_finite_epochs_checked"]),
        "sHashExactContinuity": num(total["hash_exact"][2]),
        "sHashExactClaim": num(total["hash_exact"][3]),
        "sTrustedContinuity": num(total["mixed_offcenter_trusting"][2]),
        "sIdCenterOnce": num(total["id_drop_center"][1]),
        "sTouchingChecks": num(audit["touching_window_schedules_vs_brute_force"]),
        "sTouchingCertified": num(audit["touching_window_schedules_certified"]),
        "sTouchingRandom": num(audit["random_touching_windows_vs_brute_force"]),
    }
    # The bundle pools: pages present at the start of the window (and hence, without
    # deletions in the replay, throughout it).
    bundles = rows(REV / "bundles.csv")
    pools = {r["stratum"]: int(r["eligible_pages"]) for r in bundles}
    assert {(r["stratum"], int(r["eligible_pages"])) for r in bundles} == set(pools.items())
    macros["sPoolVital"] = str(pools["vital"])
    macros["sPoolRandom"] = str(pools["random"])
    macros["sPoolRandomLate"] = str(desc["random"]["pages"] - pools["random"])
    assert desc["vital"]["pages"] == pools["vital"]
    # Preregistered double collects: hashes certify more runs than revision IDs by exactly
    # their G2 violations, which is zero in some conditions.
    by = {(r["method"], r["stratum"], r["n"], r["gap_seconds"]): r for r in bundles}
    surplus = []
    for (method, stratum, n, gap), r in by.items():
        if method == "hash_bridge":
            twin = by[("id_bridge", stratum, n, gap)]
            extra = int(r["certified"]) - int(twin["certified"])
            assert extra == int(r["certified_violating_g2"]) >= 0
            surplus.append(extra)
    macros["sPreregConditions"] = str(len(surplus))
    macros["sPreregMore"] = str(sum(x > 0 for x in surplus))
    macros["sPreregEqual"] = str(sum(x == 0 for x in surplus))
    minimum = audit["minimum_sequential_captures"]
    fixed = audit["minimum_sequential_captures_fixed_instant"]
    macros["sMinimumCaptures"] = ", ".join(str(minimum[k]) for k in sorted(minimum, key=int))
    macros["sMinimumFixed"] = ", ".join(str(fixed[k]) for k in sorted(fixed, key=int))
    lines = [f"\\newcommand{{\\{k}}}{{{v}}}" for k, v in sorted(macros.items())]
    (OUT / "supp-numbers.tex").write_text("% Generated by scripts/supplement_tables.py; do not edit.\n"
                                          + "\n".join(lines) + "\n")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for stale in OUT.glob("*.tex"):
        stale.unlink()
    hidden_change()
    preregistered()
    addendum()
    total = assertions()
    contracts()
    http()
    probes()
    numbers(total)
    print("supplement tables:", ", ".join(sorted(p.name for p in OUT.glob("*.tex"))))


if __name__ == "__main__":
    main()
