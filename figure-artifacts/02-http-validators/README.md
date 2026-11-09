# 02-http-validators

Six controlled framework executions. Four configurations return 304 after the endpoint bytes and validator return. Fresh modification times distinguish the other two. Each full-body endpoint GET precedes the conditional GET; every intermediate single-file state is recorded. These are valid representation comparisons, not continuity guarantees or measured failure rates.

Copy this directory anywhere. Run:

```sh
python3 -m pip install -r requirements.txt
python3 derive.py
python3 plot.py
```

`derive.py` rebuilds the exact `plot-data.csv` from the source files here, with explicit consistency assertions. `plot.py` reads that CSV and creates vector PDF/SVG and a PNG preview. No parent-directory import or network access is used.

One row per configuration; raw request/response records and atomic mutation traces determine every plotted value.

`MANIFEST.sha256` covers every packaged file. `figure.json` records source hashes, provenance and final physical size. Font size is specified at that size; scale neither panel arbitrarily for submission.
