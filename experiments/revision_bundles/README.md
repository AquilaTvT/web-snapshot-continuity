# Trace-driven certification on complete revision histories

This study asks how often equal content hashes hide an intervening change, and
what certification rules built on content hashes, on revision IDs, or on the
exact pairwise test certify on real histories. `protocol.json` fixes the frames,
window, capture schedules, methods and ground-truth definitions. It was
committed to the repository before any revision metadata for this study was
requested; `data/collection.json` records its SHA-256 (`79c8be55…`), which
`derive.py` checks, and the analysis follows it.

## Data

`collect.py` queried the English Wikipedia Action API on 2026-11-05 with serial
requests at least 2 s apart, `maxlag=5`, and a descriptive User-Agent without
personal contact data. HTTP 429 responses were retried after the advertised or
a growing delay. The run was interrupted three times by worker restarts (after
287, 318 and 359 saved responses) and each time resumed with `--resume`, which
replays the saved responses through the same request code and fetches only
the missing ones; the manifest records the final resume. Every successful
response is stored unchanged under
`data/raw/` and listed with its URL, retrieval time and SHA-256 in
`data/collection.json`. Only revision IDs, parent IDs, timestamps, SHA-1 values
and sizes were requested; no user names, edit comments or page text.

* **Vital stratum.** The namespace-0 links of `Wikipedia:Vital articles/Level 3`
  at collection time (page revision recorded in the manifest), sorted, then 150
  titles drawn with `random.Random(20261105).sample`.
* **Random stratum.** The first 150 distinct pages returned by `list=random`
  (namespace 0, non-redirects). The returned list is frozen; a re-collection
  draws a different list.
* **Window.** 2024-01-01T00:00:00Z to 2025-01-01T00:00:00Z. The parent of each
  page's first in-window revision is fetched by ID so that the state at window
  start is known; a page without one is absent until its first revision.

## Analysis

`derive.py` verifies every response hash, rebuilds all histories from the raw
files and compares them with the manifest, then computes the protocol's
measurements exactly. A revision superseded within the same second has no
positive duration; pages with hidden or missing SHA-1 values are excluded and
listed in `derived/excluded.csv`.

* `derived/descriptive.csv`: pages, states, pages with a content-hash return,
  return events and the median departure duration per stratum.
  `derived/returns.csv` lists every return with its revision IDs.
* `derived/hidden-change.csv` (M1): hourly capture instants over the window and
  revisit gaps of 1 min, 1 h, 1 d and 7 d. For every pair at which the page
  exists, `equal_hash` counts equal SHA-1 values and
  `equal_hash_hidden_change` counts those with a different state in between;
  the ratio has a page-clustered percentile bootstrap interval (2,000
  resamples, seed 7). `equal_revid_hidden_change` is the same count for equal
  revision IDs.
* `derived/bundles.csv` (M2): for each stratum, bundle sizes 2, 4 and 8, 400
  bundles of pages existing throughout the window and 10 start times each,
  sequential captures with 1 s request windows whose starts are 1 s, 1 min or
  1 h apart (at 1 s, consecutive windows touch).
  The double-collect rules (`hash_bridge`, `id_bridge`) read 1..n, n..1 and
  intersect the half-open bridges; `id_exact` reads 1..n-1, n, n-1..1 and
  applies the pairwise test. For certified runs, G1 asks whether the claimed
  common time (or the single read's instant) really had every page at its
  observed content, and G2 whether every twice-read page kept its observed
  content between its two reads.

## Post hoc addendum

`protocol-addendum.json` was written after the preregistered results were known,
following a review that the preregistered double-collect rules use half-open
bridges (`max first-window end < min last-window start`), which reject touching
windows although one common instant suffices. `addendum.py` evaluates, on
exactly the preregistered draws (same bundles, read orders, start times and read
instants), closed-bridge double collects with content hashes and with revision
IDs, the 2n-request schedule with the center page's second request removed, the
exact palindrome with content hashes, and the exact palindrome with one
off-center hash-only page, certified by trusting it or by the exact test with
one reusable field (Theorem 3 of the paper; the frozen addendum protocols,
written when the paper numbered it differently, call it Theorem 2(ii)). It
first reproduces the three preregistered methods count for count, then writes
`derived/addendum.csv`. The preregistered results are unchanged and remain in
`derived/bundles.csv`.

## Second post hoc addendum

`protocol-addendum-2.json` was written on 2026-11-07, after the preregistered
results and the first addendum were known and before `addendum2.py` was run. It
answers two review points. First, the G1 check measures different assertions
for different methods (an existential check over the claimed interval for
double collects, the single read's instant for the exact test), so
`addendum2.py` records for every certified run three nested assertions:
*continuity* (G2: every twice-read page kept its content between its reads),
the certificate's *claim* (every page has its observed content throughout the
asserted closed interval, or at the single read of the exact test) and
*existence* (the combination held at some instant of the capture; a
certificate that fails it is fictitious), together with the preregistered G1.
It asserts on every run that a fictitious certificate violates its claim and
that a violated claim implies a continuity violation. Second, it adds the
schedule that the field contract suggests: the page that offers only a content
hash is read once, at the center of the revisit order
(`mixed_center_theorem`). The script first reproduces all 162 rows of
`addendum.csv` and then writes `derived/addendum-2.csv`.

## Reproduce

Offline, from the repository root (standard library only):

```sh
python3 -B experiments/revision_bundles/derive.py --output /tmp/revision-derived
```

The six derived files are byte-identical to `derived/`. `python3 -B experiments/revision_bundles/addendum.py --output /tmp/revision-derived` reproduces `addendum.csv` (about 10 s), and `python3 -B experiments/revision_bundles/addendum2.py --output /tmp/revision-derived` reproduces `addendum-2.csv` (about 20 s). A new collection needs
network access and writes a new directory; it cannot reproduce the random
stratum's page list:

```sh
python3 experiments/revision_bundles/collect.py --output /tmp/revisions-new \
  --user-agent "descriptive-client-name/1.0 (purpose; contact)"
```

## Scope

Revision metadata describe the raw source text of each page, not rendered
HTML, templates, caches or deployment. Timestamps have one-second resolution.
The vital frame is curated and the random frame follows MediaWiki's
`page_random` ordering; neither is a sample of the Web. Captures are replayed
against the frozen histories; no request was sent to Wikipedia at the
simulated times. Revision IDs are append-only in the frozen history; the study
does not observe administrative deletion and undeletion, which can make an
older revision current again.
