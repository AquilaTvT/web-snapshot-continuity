"""Fetch the first content-return witness per frozen page for byte comparison."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.collect_revision_histories import request
from scripts.run_revision_audit import load_pages, load_witness_contents
from src.revision_history import audit_rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--user-agent", required=True)
    args = parser.parse_args()
    target = args.snapshot / "witness-content.json"
    metadata_target = args.snapshot / "witness-collection.json"
    if target.exists() or metadata_target.exists():
        raise SystemExit("Witness files already exist; refusing to overwrite.")
    _, pages = load_pages(args.snapshot)
    selected = []
    for entry, rows in pages:
        result = audit_rows(rows)
        if result["returns"]:
            selected.append({"title": entry["returned_title"],
                             "revision_ids": result["returns"][0]["revision_ids"]})
    ids = sorted({value for witness in selected for value in witness["revision_ids"]})
    if not ids or len(ids) > 50:
        raise SystemExit("Expected between 1 and 50 selected revision IDs.")
    params = {"action": "query", "prop": "revisions", "revids": "|".join(map(str, ids)),
              "rvprop": "ids|timestamp|sha1|content", "rvslots": "main",
              "formatversion": "2", "format": "json"}
    _, metadata = request(params, target, args.user_agent)
    metadata["selection"] = "First return per fixed page in API order, with consecutive appearances of the repeated hash and the first differing intermediate revision."
    metadata["witnesses"] = selected
    metadata["source_text_license"] = "CC BY-SA 4.0; unmodified revision source text. Attribution through each source revision and its page history."
    metadata["revision_urls"] = [f"https://en.wikipedia.org/w/index.php?oldid={value}" for value in ids]
    metadata_target.write_text(json.dumps(metadata, indent=2) + "\n")
    contents, _ = load_witness_contents(args.snapshot, pages)
    if len(contents) != len(ids):
        raise ValueError("The selected source revisions were not fully verified")
    print("Fetched", len(ids), "revisions for", len(selected), "witnesses")


if __name__ == "__main__":
    main()
