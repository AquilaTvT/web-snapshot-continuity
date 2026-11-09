"""Generate paper/numbers.tex and data/derived/paper-numbers.json from derived evidence.

Every number printed in the manuscript comes from this file. Missing evidence
is an error, never a default value.
"""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_csv(path):
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


def percent(value, digits=1):
    return f"{100 * value:.{digits}f}\\%"


def share(value):
    """One decimal from 1%, two decimals below, and a bound under 0.01%."""
    p = 100 * value
    if p >= 1:
        return f"{p:.1f}\\%"
    if p >= 0.01:
        return f"{p:.2f}\\%"
    return "<0.01\\%"


def families(entries):
    names = set()
    for entry in entries:
        name = entry["platform"]
        for prefix in ("Express", "MediaWiki", "OCI", "Garage", "SeaweedFS", "Apache", "nginx", "OpenStack Swift"):
            if name.startswith(prefix):
                name = prefix
        names.add(name.split(" (")[0])
    return sorted(names)


def addendum_methods(rows):
    return {r["method"] for r in rows}


def main():
    numbers = {}
    probes = json.loads((ROOT / "experiments/reactivation_probes/derived/summary.json").read_text())
    findings = probes["findings"]
    numbers["nProbeRequests"] = str(findings["requests_total"])
    numbers["nSThree"] = str(findings["s3_implementations"])
    assert len(findings["delete_current_returned"]) == findings["s3_implementations"]
    assert len(findings["delete_marker_returned"]) == findings["s3_implementations"]
    numbers["nLockReturned"] = str(len(findings["object_lock_marker_returned"]))
    # The manuscript spells these counts as words; keep them tied to the evidence.
    assert findings["s3_implementations"] == 8 and len(findings["object_lock_marker_returned"]) == 7
    assert len(findings["suspended_identifier_unchanged"]) == 8 and len(findings["copy_restore_fresh"]) == 7
    audit = json.loads((ROOT / "research/platform-identifiers-round9.sources.json").read_text())
    counts = audit["summary_counts"]["by_primary_class"]
    assert sum(counts.values()) == len(audit["entries"])
    numbers["nAuditIdentifiers"] = str(len(audit["entries"]))
    numbers["nAuditPlatforms"] = str(len(families(audit["entries"])))
    numbers["nAuditSources"] = str(len(audit["sources"]))
    numbers["nAuditReactivating"] = str(counts["ii"])
    numbers["nAuditDerived"] = str(counts["i"] + counts["i*"])
    numbers["nAuditFresh"] = str(counts["iii"])
    numbers["nAuditNotUnique"] = str(counts["n/u"])
    # Undocumented semantics (iv) or no versioning at all (n/a); the classes must add up.
    numbers["nAuditOther"] = str(counts["iv"] + counts["n/a"])
    assert sum(int(numbers[k]) for k in ("nAuditReactivating", "nAuditDerived", "nAuditFresh",
                                         "nAuditNotUnique", "nAuditOther")) == len(audit["entries"])
    profile = json.loads((ROOT / "experiments/publication_profile/derived/summary.json").read_text())
    numbers["nProfileRequests"] = str(profile["counts"]["s3_requests"])
    # Six HTTP cases, spelled out in the text: four answer 304 because the validator came back
    # with the content, the two with fresh modification times answer 200; macOS and Linux agree.
    stacks = {name: read_csv(ROOT / "data/derived" / name) for name in ("http_stacks.csv", "http_stacks_linux.csv")}
    outcome = {name: sorted((r["case"], r["conditional_status"]) for r in rows) for name, rows in stacks.items()}
    assert outcome["http_stacks.csv"] == outcome["http_stacks_linux.csv"]
    statuses = dict(outcome["http_stacks_linux.csv"])
    assert len(statuses) == 6 and sorted(c for c, v in statuses.items() if v == "200") == ["apache-fresh", "python-fresh"]
    assert sum(1 for v in statuses.values() if v == "304") == 4
    certification = json.loads((ROOT / "data/derived/certification-audit.json").read_text())
    numbers["nScheduleChecks"] = f"{certification['sequential_schedules_vs_brute_force']:,}"
    numbers["nRandomChecks"] = f"{certification['random_overlapping_windows_vs_brute_force']:,}"
    numbers["nMachineChecks"] = str(certification["explicit_state_machines_vs_rule"])
    numbers["nCnfChecks"] = str(certification["cnf_instances_for_hardness_construction"])
    revisions = ROOT / "experiments/revision_bundles/derived"
    summary = json.loads((revisions / "summary.json").read_text())
    descriptive = {row["stratum"]: row for row in summary["descriptive"]}
    numbers["nPages"] = str(summary["pages_analyzed"])
    numbers["nVitalPages"] = str(descriptive["vital"]["pages"])
    numbers["nRandomPages"] = str(descriptive["random"]["pages"])
    numbers["nRevisionRequests"] = str(summary["requests"])
    numbers["nStates"] = f"{sum(int(row['states']) for row in descriptive.values()):,}"
    numbers["nReturnEvents"] = f"{sum(int(row['return_events']) for row in descriptive.values()):,}"
    numbers["vitalPagesWithReturn"] = percent(int(descriptive["vital"]["pages_with_return"]) / int(descriptive["vital"]["pages"]), 0)
    numbers["randomPagesWithReturn"] = percent(int(descriptive["random"]["pages_with_return"]) / int(descriptive["random"]["pages"]), 0)
    numbers["vitalMedianDeparture"] = str(descriptive["vital"]["median_departure_seconds"])
    numbers["randomMedianDeparture"] = str(descriptive["random"]["median_departure_seconds"])
    hidden = {(row["stratum"], int(row["gap_seconds"])): row for row in read_csv(revisions / "hidden-change.csv")}
    for (stratum, gap), name in (((("vital", 3600)), "hiddenVitalHour"), (("vital", 86400), "hiddenVitalDay"),
                                 (("vital", 604800), "hiddenVitalWeek"), (("random", 86400), "hiddenRandomDay"),
                                 (("random", 604800), "hiddenRandomWeek"), (("vital", 60), "hiddenVitalMinute")):
        row = hidden[stratum, gap]
        numbers[name] = share(float(row["ratio"]))
        low, high = share(float(row["ci_low"])), share(float(row["ci_high"]))
        numbers[name + "CI"] = low.replace("\\%", "") + "--" + high
        assert int(row["equal_revid_hidden_change"]) == 0
    bundles = read_csv(revisions / "bundles.csv")
    def pick(method, **conditions):
        out = [r for r in bundles if r["method"] == method
               and all(r[k] == str(v) for k, v in conditions.items())]
        assert out, (method, conditions)
        return out
    def total(rows, field):
        return sum(int(r[field]) for r in rows)
    hash_rows = pick("hash_bridge")
    certified, false_g1, false_g2 = (total(hash_rows, f) for f in
                                     ("certified", "certified_violating_g1", "certified_violating_g2"))
    numbers["hashCertificates"] = f"{certified:,}"
    numbers["falseHashShare"] = percent(false_g2 / certified, 2)
    numbers["falseHashGOne"] = f"{false_g1:,}"
    numbers["falseHashGTwo"] = f"{false_g2:,}"
    # A bridge certificate that misses the combination also breaks continuity (G1 false implies
    # G2 false), so the text counts the G1 failures among the G2 failures.
    assert all(int(r["certified_violating_g1"]) <= int(r["certified_violating_g2"]) for r in hash_rows)
    for method in ("id_bridge", "id_exact"):
        rows = pick(method)
        assert total(rows, "certified_violating_g1") + total(rows, "certified_violating_g2") == 0, method
    # In every condition the hash rule's surplus over revision IDs is exactly its false certificates.
    surplus_equals_false = True
    for r in hash_rows:
        twin = pick("id_bridge", stratum=r["stratum"], n=r["n"], gap_seconds=r["gap_seconds"])[0]
        surplus_equals_false &= int(r["certified"]) - int(twin["certified"]) == int(r["certified_violating_g2"])
    assert surplus_equals_false
    numbers["idCertificates"] = f"{total(pick('id_bridge'), 'certified'):,}"
    numbers["exactCertificates"] = f"{total(pick('id_exact'), 'certified'):,}"
    numbers["nBundleRuns"] = f"{total(pick('id_exact'), 'runs'):,}"
    eight = {m: pick(m, stratum="vital", n=8, gap_seconds=3600)[0] for m in ("hash_bridge", "id_bridge", "id_exact")}
    numbers["vitalEightHash"] = f"{int(eight['hash_bridge']['certified']):,}"
    numbers["vitalEightFalse"] = str(int(eight["hash_bridge"]["certified_violating_g2"]))
    numbers["vitalEightFalseShare"] = percent(int(eight["hash_bridge"]["certified_violating_g2"])
                                              / int(eight["hash_bridge"]["certified"]))
    numbers["vitalEightGOne"] = str(int(eight["hash_bridge"]["certified_violating_g1"]))
    numbers["vitalEightIdBridge"] = f"{int(eight['id_bridge']['certified']):,}"
    numbers["vitalEightExact"] = f"{int(eight['id_exact']['certified']):,}"
    touching = {m: pick(m, gap_seconds=1) for m in ("hash_bridge", "id_bridge", "id_exact")}
    assert total(touching["hash_bridge"], "certified") == total(touching["id_bridge"], "certified") == 0
    numbers["touchingRuns"] = f"{total(touching['id_exact'], 'runs'):,}"
    numbers["touchingExact"] = f"{total(touching['id_exact'], 'certified'):,}"
    # The exact rule never certifies fewer runs than the double collect with the same field.
    for r in pick("id_exact"):
        twin = pick("id_bridge", stratum=r["stratum"], n=r["n"], gap_seconds=r["gap_seconds"])[0]
        assert int(r["certified"]) >= int(twin["certified"]), r
    # Constants written out in the text and captions.
    protocol = json.loads((ROOT / "experiments/revision_bundles/protocol.json").read_text())
    m2 = protocol["measurements"]["M2_bundles"]
    assert m2["bundle_sizes"] == [2, 4, 8] and m2["gaps_seconds"] == [1, 60, 3600]
    assert m2["request_window_seconds"] == 1 and m2["bundles_per_size"] * m2["starts_per_bundle"] == 4000
    assert all(int(r["runs"]) == 4000 for r in bundles)
    assert [protocol["strata"][k]["sample_size"] for k in ("vital", "random")] == [150, 150]
    trace = read_csv(ROOT / "figure-artifacts/05-certification-rule/plot-data.csv")
    claimed = [r for r in trace if r["panel"] == "a" and r["kind"] == "claimed"]
    assert len(claimed) == 1 and round((float(claimed[0]["end"]) - float(claimed[0]["start"])) * 1000) == 18
    # Post hoc addendum (protocol-addendum.json): closed-interval baselines, schedule ablation, one off-center hash.
    addendum = read_csv(revisions / "addendum.csv")
    def add(method, **conditions):
        out = [r for r in addendum if r["method"] == method and all(r[k] == str(v) for k, v in conditions.items())]
        assert out, (method, conditions)
        return out
    for name, method in (("closedHash", "hash_double_closed"), ("closedId", "id_double_closed"),
                         ("exactHash", "hash_exact"), ("mixedTrust", "mixed_offcenter_trusting"),
                         ("mixedTheorem", "mixed_offcenter_theorem"), ("dropCenter", "id_drop_center"),
                         ("exactId", "id_exact")):
        rows_m = add(method)
        numbers[name + "Certificates"] = f"{total(rows_m, 'certified'):,}"
        numbers[name + "FalseGTwo"] = f"{total(rows_m, 'certified_violating_g2'):,}"
        numbers[name + "FalseGOne"] = f"{total(rows_m, 'certified_violating_g1'):,}"
    assert numbers["exactIdCertificates"] == numbers["exactCertificates"]
    assert numbers["mixedTheoremCertificates"] == "0"
    for prefix in ("closedId", "dropCenter", "exactId"):
        assert numbers[prefix + "FalseGTwo"] == numbers[prefix + "FalseGOne"] == "0", prefix
    # Under both schedules the hash surplus over revision IDs is exactly its continuity failures.
    for hashed, ids in (("hash_double_closed", "id_double_closed"), ("hash_exact", "id_exact")):
        for r in add(hashed):
            twin = add(ids, stratum=r["stratum"], n=r["n"], gap_seconds=r["gap_seconds"])[0]
            assert int(r["certified"]) - int(twin["certified"]) == int(r["certified_violating_g2"]), (hashed, r)
            assert int(r["certified_violating_g1"]) <= int(r["certified_violating_g2"])
    # The exact rule never certifies fewer runs than the closed double collect on the same draws.
    for r in add("id_exact"):
        twin = add("id_double_closed", stratum=r["stratum"], n=r["n"], gap_seconds=r["gap_seconds"])[0]
        assert int(r["certified"]) >= int(twin["certified"]), r
    more = sum(int(r["certified"]) > int(add("id_double_closed", stratum=r["stratum"], n=r["n"],
                                              gap_seconds=r["gap_seconds"])[0]["certified"]) for r in add("id_exact"))
    numbers["exactMoreConditions"] = str(more)
    numbers["nConditions"] = str(len(add("id_exact")))
    eight = {m: add(m, stratum="vital", n=8, gap_seconds=3600)[0]
             for m in ("id_double_closed", "id_drop_center", "id_exact", "hash_double_closed", "hash_exact",
                       "mixed_offcenter_trusting")}
    base8, drop8, exact8 = (int(eight[m]["certified"]) for m in ("id_double_closed", "id_drop_center", "id_exact"))
    assert str(base8) == numbers["vitalEightIdBridge"].replace(",", "")
    numbers["vitalEightDropCenter"] = f"{drop8:,}"
    numbers["vitalEightCenterGain"] = str(drop8 - base8)
    numbers["vitalEightShorterGain"] = str(exact8 - drop8)
    numbers["vitalEightExactHash"] = f"{int(eight['hash_exact']['certified']):,}"
    numbers["vitalEightExactHashFalse"] = str(int(eight["hash_exact"]["certified_violating_g2"]))
    numbers["vitalEightMixedFalse"] = str(int(eight["mixed_offcenter_trusting"]["certified_violating_g2"]))
    assert int(eight["hash_double_closed"]["certified"]) == int(numbers["vitalEightHash"].replace(",", ""))
    assert int(eight["hash_double_closed"]["certified_violating_g2"]) == int(numbers["vitalEightFalse"])
    # Second post hoc addendum (protocol-addendum-2.json): what each certificate asserts, and the
    # schedule that reads the hash-only page once, at the center.
    second = read_csv(revisions / "addendum-2.csv")
    def sec(method, **conditions):
        out = [r for r in second if r["method"] == method and all(r[k] == str(v) for k, v in conditions.items())]
        assert out, (method, conditions)
        return out
    for r in second:
        assert int(r["fictitious"]) <= int(r["claim_violations"]) <= int(r["continuity_violations"]), r
        assert int(r["fictitious"]) == 0, r       # the text says no certificate was fictitious
        if r["method"] in addendum_methods(addendum):
            twin = add(r["method"], stratum=r["stratum"], n=r["n"], gap_seconds=r["gap_seconds"])[0]
            assert twin["certified"] == r["certified"] and twin["certified_violating_g2"] == r["continuity_violations"]
            assert twin["certified_violating_g1"] == r["preregistered_g1_violations"]
    numbers["nFictitious"] = str(sum(int(r["fictitious"]) for r in second))
    numbers["closedHashClaim"] = f"{total(sec('hash_double_closed'), 'claim_violations'):,}"
    numbers["exactHashClaim"] = f"{total(sec('hash_exact'), 'claim_violations'):,}"
    numbers["mixedTrustClaim"] = f"{total(sec('mixed_offcenter_trusting'), 'claim_violations'):,}"
    centered = sec("mixed_center_theorem")
    assert total(centered, "continuity_violations") == total(centered, "claim_violations") == 0
    numbers["mixedCenterCertificates"] = f"{total(centered, 'certified'):,}"
    numbers["mixedCenterShare"] = percent(total(centered, "certified") / total(centered, "runs"), 1)
    numbers["vitalEightMixedCenter"] = f"{int(sec('mixed_center_theorem', stratum='vital', n=8, gap_seconds=3600)[0]['certified']):,}"
    numbers["vitalEightClaim"] = str(int(sec("hash_double_closed", stratum="vital", n=8, gap_seconds=3600)[0]["claim_violations"]))
    numbers["vitalEightExactHashClaim"] = str(int(sec("hash_exact", stratum="vital", n=8, gap_seconds=3600)[0]["claim_violations"]))
    closed_certified = total(add("hash_double_closed"), "certified")
    numbers["closedHashFalseShare"] = percent(total(add("hash_double_closed"), "certified_violating_g2") / closed_certified, 2)
    hidden_week = hidden["vital", 604800]
    numbers["vitalWeekEqualPairs"] = f"{int(hidden_week['equal_hash']):,}"
    numbers["vitalWeekHiddenPairs"] = f"{int(hidden_week['equal_hash_hidden_change']):,}"
    audit_record = json.loads((ROOT / "data/derived/certification-audit.json").read_text())
    numbers["nSweepChecks"] = str(audit_record["worst_case_sweep_vs_brute_force"])
    numbers["nFixedChecks"] = f"{audit_record['fixed_instant_schedules_vs_brute_force']:,}"
    numbers["nRepairChecks"] = f"{audit_record['repair_contracts_vs_all_labelings']:,}"
    numbers["nRefinementChecks"] = f"{audit_record['finite_refinements_vs_component_criterion']:,}"
    assert audit_record["s3_finite_epochs_checked"] > 0
    assert audit_record["minimum_sequential_captures_fixed_instant"] == {"1": 2, "2": 4, "3": 6}
    assert audit_record["minimum_sequential_captures"] == {"1": 1, "2": 3, "3": 5, "4": 7}
    excluded = read_csv(revisions / "excluded.csv")
    numbers["nSampledPages"] = str(int(summary["pages_analyzed"]) + len(excluded))
    numbers["nExcludedHidden"] = str(sum(1 for r in excluded if r["reason"] == "hidden or missing sha1"))
    numbers["nExcludedAbsent"] = str(sum(1 for r in excluded if r["reason"] == "no state in window"))
    # The figure descriptions (alt text) spell out plotted values; they must match the evidence.
    # The check needs the paper's source, which the anonymous artifact does not include.
    source = ROOT / "paper/temporal.tex"
    if source.exists():
        tex = source.read_text()
        described = tex[tex.index("\\label{fig:rule}") + 1:tex.index("\\label{fig:revisions}")]
        described = described[described.index("\\Description{"):]
        plotted = [numbers["hiddenVitalWeek"].replace("\\%", " percent"),
                   numbers["hiddenRandomWeek"].replace("\\%", " percent"),
                   numbers["vitalEightIdBridge"], numbers["vitalEightDropCenter"], numbers["vitalEightExact"],
                   numbers["vitalEightFalse"], numbers["vitalEightExactHashFalse"], numbers["vitalEightMixedCenter"],
                   "4,000"]
        assert all(value in described for value in plotted), [v for v in plotted if v not in described]
        assert "18 microseconds" in tex and "18\\,\\textmu s" in tex
    lines = ["% Generated by scripts/paper_numbers.py; do not edit."]
    lines += [f"\\newcommand{{\\{name}}}{{{value}}}" for name, value in sorted(numbers.items())]
    (ROOT / "paper/numbers.tex").write_text("\n".join(lines) + "\n")
    (ROOT / "output").mkdir(exist_ok=True)
    (ROOT / "output/paper-numbers.json").write_text(json.dumps(numbers, indent=1, sort_keys=True) + "\n")
    print(json.dumps(numbers, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
