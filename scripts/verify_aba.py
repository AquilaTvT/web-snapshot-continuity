#!/usr/bin/env python3
"""Check the archived MDN source-file A-B-A witness, without network access."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path


def verify(path: Path) -> dict:
    record = json.loads(path.read_text(encoding="utf-8"))
    states = record["states"]
    if [s["label"] for s in states] != ["A", "B", "A2"]:
        raise ValueError("Expected exactly three chronological states A, B, A2")
    report = []
    for state in states:
        raw = state["content_utf8"].encode("utf-8")
        git_object = b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw
        digest = hashlib.sha1(git_object).hexdigest()
        if digest != state["blob_sha1"]:
            raise ValueError(f"Blob mismatch at {state['label']}: {digest}")
        report.append({"label": state["label"], "bytes": len(raw), "git_blob_sha1": digest,
                       "sha256": hashlib.sha256(raw).hexdigest()})
    contents = [s["content_utf8"] for s in states]
    if not (contents[0] == contents[2] and contents[0] != contents[1]):
        raise ValueError("Source bytes do not form A-B-A")
    dates = [datetime.fromisoformat(s["commit_date"].replace("Z", "+00:00")) for s in states]
    if not dates[0] < dates[1] < dates[2]:
        raise ValueError("Commit dates are not ordered")
    if [c["sha"] for c in record["history_newest_first"]] != [s["commit_sha"] for s in reversed(states)]:
        raise ValueError("Path-history response does not match the three selected states")
    return {"status": "verified", "scope": record["measurement_unit"], "states": report,
            "A_equals_A2_bytes": True, "A_differs_from_B_bytes": True,
            "consecutive_in_recorded_path_history": True,
            "deployment_observed": False, "semantic_change_established": False}


def main() -> None:
    default = Path(__file__).resolve().parents[1] / "data" / "raw" / "aba-source.json"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=default)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = json.dumps(verify(args.input), indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
    print(report, end="")


if __name__ == "__main__":
    main()
