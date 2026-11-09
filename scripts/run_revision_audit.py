"""Reconstruct the natural-revision audit from frozen API responses, offline."""
import csv
import hashlib
import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.revision_history import audit_rows, parse_timestamp, verify_byte_witness

RAW = ROOT / "data/raw/revision-histories-2024"
API = "https://en.wikipedia.org/w/api.php"


def load_record(raw, record, expected_query):
    """Check a frozen response and the exact collection request it records."""
    if not isinstance(record, dict) or not isinstance(record.get("url"), str):
        raise ValueError("Malformed response provenance")
    name = record.get("file")
    if (not isinstance(name, str) or not name or Path(name).name != name
            or "\\" in name or (raw / name).resolve().parent != raw.resolve()):
        raise ValueError("Response filename is not local")
    payload = (raw / name).read_bytes()
    if (hashlib.sha256(payload).hexdigest() != record.get("sha256")
            or type(record.get("bytes")) is not int or len(payload) != record["bytes"]):
        raise ValueError("Frozen API response changed")
    url = urlparse(record.get("url", ""))
    if (url.scheme + "://" + url.netloc + url.path != API or url.fragment
            or url.params
            or parse_qs(url.query, keep_blank_values=True, strict_parsing=True)
            != {key: [str(value)] for key, value in expected_query.items()}):
        raise ValueError("Recorded request does not match the declared collection")
    response = json.loads(payload)
    if (not isinstance(response, dict) or "error" in response or "warnings" in response
            or not isinstance(response.get("query"), dict)
            or "badrevids" in response["query"]):
        raise ValueError("API did not provide an unqualified revision response")
    return response


def load_pages(raw=RAW):
    raw = Path(raw)
    collection = json.loads((raw / "collection.json").read_text())
    if (not isinstance(collection, dict) or type(collection.get("schema")) is not int
            or collection["schema"] != 1 or collection.get("api") != API):
        raise ValueError("Unsupported source collection")
    window = collection.get("window")
    if (not isinstance(window, list) or len(window) != 2
            or parse_timestamp(window[0]) > parse_timestamp(window[1])):
        raise ValueError("Invalid collection window")
    entries = collection.get("pages")
    if (not isinstance(entries, list) or not entries or any(not isinstance(entry, dict) for entry in entries)
            or not isinstance(collection.get("titles"), list)
            or any(not isinstance(title, str) or not title for title in collection["titles"])
            or [entry.get("requested_title") for entry in entries] != collection.get("titles")
            or len(set(collection["titles"])) != len(entries)):
        raise ValueError("Collection titles do not identify one entry per page")
    loaded = []
    seen_pages, seen_files, seen_ids = set(), set(), set()
    for entry in entries:
        if (type(entry.get("pageid")) is not int or entry["pageid"] <= 0
                or entry["pageid"] in seen_pages
                or not isinstance(entry.get("returned_title"), str)
                or not entry["returned_title"]
                or not isinstance(entry.get("requested_title"), str)
                or not entry["requested_title"]
                or not isinstance(entry.get("batches"), list) or not entry["batches"]
                or type(entry.get("revision_count")) is not int or entry["revision_count"] <= 0):
            raise ValueError("Malformed or duplicate page identity")
        seen_pages.add(entry["pageid"])
        rows, previous_continue = [], None
        seen_continuations = set()
        base_query = {"action": "query", "prop": "revisions", "titles": entry["requested_title"],
                      "redirects": "1", "rvprop": "ids|timestamp|sha1|size", "rvlimit": "500",
                      "rvdir": "newer", "rvstart": window[0], "rvend": window[1],
                      "formatversion": "2", "format": "json"}
        for number, batch in enumerate(entry["batches"]):
            if not isinstance(batch, dict) or not isinstance(batch.get("file"), str):
                raise ValueError("Malformed response batch")
            if batch["file"] in seen_files:
                raise ValueError("Duplicate response batch")
            seen_files.add(batch["file"])
            if number and not previous_continue:
                raise ValueError("Unexpected extra batch after enumeration ended")
            response = load_record(raw, batch, {**base_query, **(previous_continue or {})})
            pages = response["query"].get("pages")
            if (not isinstance(pages, list) or len(pages) != 1 or not isinstance(pages[0], dict)
                    or type(pages[0].get("pageid")) is not int
                    or pages[0]["pageid"] != entry["pageid"]
                    or pages[0].get("title") != entry["returned_title"]
                    or any(key in pages[0] for key in ("missing", "invalid"))
                    or not isinstance(pages[0].get("revisions"), list)):
                raise ValueError("Page identity changed")
            rows.extend(pages[0]["revisions"])
            previous_continue = response.get("continue")
            if previous_continue is not None:
                if (not isinstance(previous_continue, dict) or not previous_continue
                        or not set(previous_continue) <= {"continue", "rvcontinue"}
                        or any(not isinstance(value, str) for value in previous_continue.values())):
                    raise ValueError("Malformed API continuation")
                key = json.dumps(previous_continue, sort_keys=True)
                if key in seen_continuations:
                    raise ValueError("Repeated API continuation")
                seen_continuations.add(key)
        if previous_continue or len(rows) != entry["revision_count"]:
            raise ValueError("The requested API enumeration was not completed")
        audit_rows(rows)
        for row in rows:
            # MediaWiki's rvstart/rvend range includes its endpoints.
            if (not window[0] <= row["timestamp"] <= window[1]
                    or type(row.get("size")) is not int or row["size"] < 0
                    or row["revid"] in seen_ids):
                raise ValueError("Revision violates the declared window, size, or page identity")
            seen_ids.add(row["revid"])
        loaded.append((entry, rows))
    return collection, loaded


def load_witness_contents(raw, pages):
    """Verify exactly the first recorded hash-return triple for each page."""
    raw = Path(raw)
    witness_file = raw / "witness-content.json"
    metadata_file = raw / "witness-collection.json"
    contents, content_metadata = {}, {}
    if not witness_file.exists() and not metadata_file.exists():
        return contents, content_metadata
    if not witness_file.exists() or not metadata_file.exists():
        raise ValueError("Incomplete source-text provenance pair")
    selected, expected_ids, row_by_id, page_by_id = [], set(), {}, {}
    for entry, rows in pages:
        returns = audit_rows(rows)["returns"]
        if returns:
            ids = returns[0]["revision_ids"]
            selected.append({"title": entry["returned_title"], "revision_ids": ids})
            expected_ids.update(ids)
            row_by_id.update({row["revid"]: row for row in rows})
            page_by_id[entry["pageid"]] = (entry["returned_title"], set(ids))
    metadata = json.loads(metadata_file.read_text())
    if (not isinstance(metadata, dict) or metadata.get("file") != witness_file.name
            or metadata.get("witnesses") != selected or not expected_ids):
        raise ValueError("Source-text selection differs from the declared first returns")
    ids = sorted(expected_ids)
    query = {"action": "query", "prop": "revisions", "revids": "|".join(map(str, ids)),
             "rvprop": "ids|timestamp|sha1|content", "rvslots": "main",
             "formatversion": "2", "format": "json"}
    response = load_record(raw, metadata, query)
    if response.get("continue") or metadata.get("revision_urls") != [
            f"https://en.wikipedia.org/w/index.php?oldid={value}" for value in ids]:
        raise ValueError("Incomplete content response or inconsistent revision attribution")
    response_pages = response["query"].get("pages")
    if not isinstance(response_pages, list):
        raise ValueError("Source-text pages missing")
    seen_pages = set()
    for page in response_pages:
        if not isinstance(page, dict):
            raise ValueError("Malformed source-text page")
        page_id = page.get("pageid")
        if (type(page_id) is not int or page_id not in page_by_id or page_id in seen_pages
                or page.get("title") != page_by_id[page_id][0]
                or any(key in page for key in ("missing", "invalid"))
                or not isinstance(page.get("revisions"), list)):
            raise ValueError("Source-text page identity changed")
        seen_pages.add(page_id)
        for revision in page["revisions"]:
            audit_rows([revision])
            revision_id = revision["revid"]
            if revision_id not in page_by_id[page_id][1] or revision_id in contents:
                raise ValueError("Unexpected or duplicate source-text revision")
            for field in ("sha1", "parentid", "timestamp"):
                if revision[field] != row_by_id[revision_id][field]:
                    raise ValueError("Metadata and source-text requests disagree")
            slots = revision.get("slots")
            if not isinstance(slots, dict):
                raise ValueError("Source content slots missing")
            slot = slots.get("main", {})
            if (not isinstance(slot, dict) or not isinstance(slot.get("content"), str)
                    or any(key in slot for key in ("texthidden", "sha1hidden", "suppressed"))
                    or slot.get("contentmodel") != "wikitext"
                    or slot.get("contentformat") != "text/x-wiki"):
                raise ValueError("Missing, hidden, or unsupported source content")
            value = slot["content"].encode("utf-8")
            if (hashlib.sha1(value).hexdigest() != revision["sha1"]
                    or len(value) != row_by_id[revision_id]["size"]):
                raise ValueError("Source bytes disagree with the recorded hash or size")
            contents[revision_id] = value
            content_metadata[revision_id] = revision
    if set(contents) != expected_ids:
        raise ValueError("Not all selected source-text revisions were returned")
    return contents, content_metadata


def main():
    collection, pages = load_pages()
    contents, content_metadata = load_witness_contents(RAW, pages)
    results, selected = [], []
    for entry, rows in pages:
        result = {"title": entry["returned_title"], "pageid": entry["pageid"], **audit_rows(rows)}
        if result["returns"]:
            witness = result["returns"][0]
            row_by_id = {row["revid"]: row for row in rows}
            for revision_id in witness["revision_ids"]:
                if revision_id in content_metadata:
                    for field in ("sha1", "parentid", "timestamp"):
                        if content_metadata[revision_id][field] != row_by_id[revision_id][field]:
                            raise ValueError("Metadata and source-text requests disagree")
            verified = verify_byte_witness(witness["revision_ids"], contents)
            if contents and not verified:
                raise ValueError("Selected source-text return is not byte verified")
            selected.append({"title": result["title"], **witness, "byte_verified": verified})
        results.append(result)
    report = {
        "scope": collection["scope"], "selection": collection["selection"],
        "window": collection["window"], "page_count": len(results),
        "revision_count": sum(x["revisions"] for x in results),
        "hash_return_count": sum(x["hash_return_count"] for x in results),
        "byte_verified_witnesses": sum(x["byte_verified"] for x in selected),
        "limits": ["Purposive six-page sample; no population prevalence estimate.",
                   "Hash-return counts are distinct from the selected byte-verified witnesses.",
                   "Revision source text does not include templates, rendered HTML, caches, or deployment times.",
                   "Parent-link continuity is not proof of all historical deletions or suppressed content.",
                   "Label minima apply to the supplied path, not every permitted future history."],
        "selected_witnesses": selected, "pages": results,
    }
    out = ROOT / "data/derived"
    (out / "revision-audit.json").write_text(json.dumps(report, indent=2) + "\n")
    fields = [key for key in results[0] if key != "returns"]
    with (out / "revision-summary.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows({key: row[key] for key in fields} for row in results)
    print(json.dumps({key: report[key] for key in ("page_count", "revision_count", "hash_return_count", "byte_verified_witnesses")}, indent=2))


if __name__ == "__main__":
    main()
