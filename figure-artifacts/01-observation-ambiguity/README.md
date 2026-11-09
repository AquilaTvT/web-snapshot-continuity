# 01-observation-ambiguity

Identical captures do not identify historical coexistence. White markers are the same four observations in both constructed histories. Intervals are left-closed and right-open. Blue segments contain the target representation. A change epoch distinguishes these histories only under a non-reuse and atomic-read contract.

Copy this directory anywhere. Run:

```sh
python3 -m pip install -r requirements.txt
python3 derive.py
python3 plot.py
```

`derive.py` rebuilds the exact `plot-data.csv` from the source files here, with explicit consistency assertions. `plot.py` reads that CSV and creates vector PDF/SVG and a PNG preview. No parent-directory import or network access is used.

Mathematical construction. No observed incidence, sampling, or aggregation.

`MANIFEST.sha256` covers every packaged file. `figure.json` records source hashes, provenance and final physical size. Font size is specified at that size; scale neither panel arbitrarily for submission.
