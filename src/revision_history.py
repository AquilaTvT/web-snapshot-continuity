"""Audit recorded source revisions without inferring served-page histories."""
from collections import Counter
from datetime import datetime
import re


def parse_timestamp(stamp):
    if (not isinstance(stamp, str)
            or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", stamp)):
        raise ValueError("Expected a UTC revision timestamp")
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def audit_rows(rows):
    """Count returns between consecutive appearances of each content hash.

    A return has a different-hash intermediate revision. Adjacent unchanged
    revisions do not count. Missing revisions cannot invalidate an observed
    three-revision witness, but these counts describe only the supplied list.
    Hash witnesses and independently fetched byte witnesses are kept separate.
    """
    if not isinstance(rows, (list, tuple)) or not rows:
        raise ValueError("A nonempty recorded revision list is required")
    ids, timestamps = set(), []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Revision entries must be records")
        if any(key in row for key in ("sha1hidden", "texthidden", "suppressed")):
            raise ValueError("Hidden or suppressed revisions cannot be audited")
        if (type(row.get("revid")) is not int or row["revid"] <= 0
                or row["revid"] in ids or type(row.get("parentid")) is not int
                or row["parentid"] < 0 or row["parentid"] == row["revid"]):
            raise ValueError("Revision identities must be unique positive integers")
        ids.add(row["revid"])
        if (not isinstance(row.get("sha1"), str)
                or not re.fullmatch(r"[0-9a-f]{40}", row["sha1"])):
            raise ValueError("Missing, hidden, or malformed content digest")
        timestamps.append(parse_timestamp(row.get("timestamp")))
    if any(a > b for a, b in zip(timestamps, timestamps[1:])):
        raise ValueError("Revisions must be in nondecreasing timestamp order")

    last, returns, runs = {}, [], []
    for index, row in enumerate(rows):
        body = row["sha1"]
        if not runs or runs[-1]["sha1"] != body:
            runs.append({"sha1": body, "first": index, "last": index})
        else:
            runs[-1]["last"] = index
        if body in last and last[body] < index - 1:
            start = last[body]
            # Since this is the next appearance of this hash, the next row
            # differs. Retain explicit indices so a checker can test this.
            middle = start + 1
            assert rows[middle]["sha1"] != body
            returns.append({
                "indices": [start, middle, index],
                "revision_ids": [rows[j]["revid"] for j in (start, middle, index)],
                "timestamp_gap_seconds": int((timestamps[index] - timestamps[middle]).total_seconds()),
                "sha1": body,
            })
        last[body] = index
    episodes = Counter(run["sha1"] for run in runs)
    return {
        "revisions": len(rows), "distinct_content_hashes": len(episodes),
        "content_runs": len(runs), "hash_return_count": len(returns),
        "consecutive_parent_links": all(b["parentid"] == a["revid"] for a, b in zip(rows, rows[1:])),
        "equal_timestamp_pairs": sum(a == b for a, b in zip(timestamps, timestamps[1:])),
        "declared_path_minimum_auxiliary_labels": max(episodes.values()),
        "declared_path_minimum_strong_labels": len(runs),
        "revision_ids_distinct": True, "returns": returns,
    }


def verify_byte_witness(ids, content_by_id):
    """Check actual decoded source bytes, independently of hash equality."""
    if (not isinstance(ids, (tuple, list)) or len(ids) != 3
            or any(type(value) is not int or value <= 0 for value in ids)
            or len(set(ids)) != 3 or not isinstance(content_by_id, dict)):
        return False
    try:
        before, middle, after = (content_by_id[revision] for revision in ids)
    except KeyError:
        return False
    return (all(type(value) is bytes for value in (before, middle, after))
            and before == after and before != middle)
