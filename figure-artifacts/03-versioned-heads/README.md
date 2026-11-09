# 03-versioned-heads

This independent Figure 3 package freezes a real native MinIO trace with six
cases and 51 HTTP requests. Twelve current-key GETs from four cases are plotted;
16 native version IDs across the complete source are retained in the ID map.
Neither script supplies synthetic observations. Missing or invalid evidence
stops derivation and rendering.

Copy the completed native source trace without changing its bytes:

```sh
cp experiments/versioned_objects/data/trace.json figure-artifacts/03-versioned-heads/trace.json
```

Then copy this figure directory anywhere and run, from within that copy:

```sh
python3 -m pip install -r requirements.txt
python3 derive.py
python3 plot.py
```

Neither script imports a parent module, reads another directory, contacts a
server, or consumes the parent experiment's derived results. The raw trace
includes all six source cases; only the four current-key cases are plotted.
The independently checked pinned-selector control is recorded in
`derivation.json`, and its original requests remain in `trace.json`. The
two-object case remains in the raw trace and is explicitly not plotted here.

`derive.py` validates base64 payloads and SHA-256 digests on both sides of every
request, serialized monotone windows, current-versus-version selectors, the
acknowledged relevant PUT/DELETE operations, native IDs, and exact A/B payloads.
It derives twelve current GET rows in `plot-data.csv`; no
`expected_version_id_repeats` flag is used as a measured result. The source
hash is frozen in `figure.json` at the first successful derivation; a later
mismatching trace is rejected.

Greek aliases are row-local: equal Greek symbols in different rows do **not**
claim equal native IDs. `version-id-map.csv` provides the complete reversible
mapping from raw response IDs to global `v0,v1,...` aliases plus the plotted
row-local aliases. It includes IDs from unplotted controls and delete markers.
A marker-backed 404 is encoded as `ABSENT`, with its actual error XML preserved
in the CSV/raw trace. A marker's version ID is never labeled as an object-data
generation or used as a certifiable endpoint.

The 3.35 by 2.80 inch PDF/SVG has actual fonts of at least 8 pt. Do not shrink it
below the declared column width. `plot.py` writes `figure.pdf`,
`figure.svg`, `preview.png`, and `MANIFEST.sha256` covering all files here.
`figure.json` records provenance, source hash and physical dimensions.
Rebuilding with the same source, Python environment and Matplotlib version is
deterministic.

Evidence scope: controlled real HTTP requests against a native local MinIO
server. The figure does not represent an AWS service execution, estimate
production recurrence, or prove that copy/reupload workflows remain safe under
every later permitted operation. Same endpoint bytes or native version IDs are
read from their original responses; the figure is not a simulated cloud trace.

