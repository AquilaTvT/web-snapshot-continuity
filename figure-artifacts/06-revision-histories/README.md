# 06-revision-histories

Main-paper Figure 2.

`collection/` is a byte-identical copy of the frozen revision collection
(`experiments/revision_bundles/data/`: manifest and 362 raw API responses).
`analysis.py`, `analysis_addendum.py` and `analysis_addendum2.py` are unmodified
copies of `experiments/revision_bundles/derive.py`, `addendum.py` and
`addendum2.py`; `protocol.json` is the preregistered protocol and
`protocol-addendum.json` and `protocol-addendum-2.json` are its two post hoc
addenda. `derive.py` runs all three analyses on `collection/` (every response
hash is checked, the histories are rebuilt from the raw files, and each
analysis reproduces the one before it), asserts that revision IDs break no
assertion and that the certificates content hashes add are exactly those that
broke continuity, and writes `plot-data.csv`:

* panel a, preregistered M1: for each stratum and revisit gap, equal-hash pairs,
  those with an intervening change, the ratio and its page-clustered bootstrap
  interval (an interval whose lower end is zero is drawn to the axis and ends in
  an arrow, because zero has no place on a log axis);
* panel b, addenda: eight vital pages with request starts 1 h apart, 4,000 runs
  per method, issued certificates and, for each, continuity violations, claim
  violations, preregistered-G1 violations and fictitious certificates, for the
  closed double collect with revision IDs and with content hashes, the
  center-read-once ablation, the exact palindrome with revision IDs and with
  content hashes, and the palindrome whose hash-only page is read at the center
  (or first and last, which Theorem 3 refuses).

Visual encoding, shared with Figure 1: blue for revision IDs (a sound field),
red for content hashes (a reusable field); the diamond marks the schedule with
one hash-only page at the center. Request counts are in parentheses, and the
grey numbers in panel b are the runs gained by reading the center once (+29)
and by the shorter schedule (+122).

Copy this directory anywhere and run:

```sh
python3 derive.py
python3 plot.py
```

Both scripts use only the Python standard library (`requirements.txt` lists
the TeX and poppler tools instead); `derive.py` takes about 30 s. `plot.py`
reads only `plot-data.csv` and writes the figure as PGFPlots and TikZ code
(`figure.tex`; `figstyle.tex` holds the colours and type sizes shared with
Figure 1). XeLaTeX sets it in the acmart typefaces shipped in `fonts/` (Linux
Libertine O, Libertinus Math) at the column width of the acmart sigconf layout,
241.15 pt (3.34 x 2.42 in), so the paper includes it unscaled and its text
matches the body: 7–8 pt, with exponents at 6 pt. `pdftocairo` and `pdftoppm`
then write `figure.svg` and `preview.png`. Before finishing, `plot.py` checks
the page width, font embedding and type sizes, and, from a 600 dpi rendering,
that no ink touches the page edge and no text box leaves the page. Rebuilds are
byte-identical. `MANIFEST.sha256` covers every file, including those under
`collection/` and `fonts/`.
