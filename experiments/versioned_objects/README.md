# Version identifiers and current-object continuity

`run_minio.py` runs actual, signed HTTP requests against an unmodified MinIO
server on loopback, using a new temporary persistent store and public fixture
credentials. It does not contact Amazon S3 or Google Cloud. Supply the official
pinned server executable; the runner checks its release and platform SHA-256.
`server-release.json` records the official release/asset URLs, byte lengths,
platform hashes and AGPL-3.0 license. The binary is downloaded separately and is
not redistributed in this artifact.

From the repository root, verify the frozen evidence offline (Python standard
library only; no MinIO process or network needed):

```sh
python3 -B experiments/versioned_objects/derive.py --self-test
python3 -B experiments/versioned_objects/derive.py --trace experiments/versioned_objects/data/trace.json --output /tmp/versioned-objects-derived
```

The first command checks small graph/interval logic and is **not** a server
experiment. The second requires the successful, complete six-case trace; it
never creates sample HTTP observations or fills in a missing run. Derived
output is written only after all trace validation, audits, and independent
checks pass. With unchanged source, the seven resulting files can be compared
byte for byte with the frozen `derived/` directory.

To execute a fresh server run, use the official download helper (requires
`curl`, its TLS trust store, and network access), then a new output directory:

```sh
python3 experiments/versioned_objects/download_server.py --output /tmp/continuity-minio
python3 -B experiments/versioned_objects/run_minio.py --minio /tmp/continuity-minio --output /tmp/versioned-objects-rerun/data
python3 -B experiments/versioned_objects/derive.py --trace /tmp/versioned-objects-rerun/data/trace.json --output /tmp/versioned-objects-rerun/derived
```

The downloader supports the four platforms listed in `server-release.json`,
resumes a partial `.download` file, and verifies the final SHA-256 before making
the file executable. The server run needs loopback-listener permissions and
temporary disk space. No cloud credentials or cloud account are needed. A
fresh run generates new opaque IDs and times; compare its semantic assertions,
not its raw bytes, with the frozen experiment.

## Recorded execution

The frozen trace was executed on 2026-11-04 with Python 3.12.10 on Darwin arm64:

* MinIO `RELEASE.2025-09-07T16-13-09Z`, commit
  `07c3a429bfed433e49018cb0f78a52145d4bedeb`, Go 1.24.6.
* Server executable SHA-256:
  `7c3b3039b76e55a1b80935848ed83998d5e8d317374f87851f46a019ff5c0aa4`.
* Six cases, 51 actual signed HTTP requests; all runner assertions passed.
* Frozen `data/trace.json` SHA-256:
  `5f3536c69d2b9171986042547126409286535a04bd2d02c05f871d70dc023537`.
* Eleven audited models: nine recorded-path models and two declared API
  obstruction models. Four safety-certificate sets (eight invariants) and
  seven negative witnesses all pass their separate checkers.

The bundle's raw-equality baseline produces admission's bridge
`[29904875, 36247041)` ns and fee's bridge `[33206125, 33224291)` ns on the
runner's monotone clock. Their overlap is 18,166 ns; the target pair is absent
from all five stable phases. The contract-aware decision is to abstain under
the unrestricted current-key mutation scope. Fee's finite capture-window
check still passes, as explained below. These intervals are trace coordinates,
not server timestamps or a performance measurement.

This is execution against the local MinIO binary, **not an Amazon S3 cloud
experiment**. AWS documentation independently defines the recovery operation;
the local execution supplies request/response evidence for this pinned MinIO
implementation. It does not establish behavior of every S3-compatible server.

## Cases and resources

| Case | Executed operation sequence | Interpretation |
| --- | --- | --- |
| `delete_current` | Put A, put B, delete B by version ID, read current | Old A and its native ID can be selected again. |
| `copy_restore` | Put A, put B, copy old A to current | Restored bytes have a newly allocated ID. |
| `reupload_restore` | Put A, put B, upload A again | Matching bytes alone do not mean matching native ID. |
| `delete_marker` | Put A, create delete marker, remove that marker | The 404 remains an internal absence between successful equal-ID endpoints. |
| `pinned_selector` | Read `?versionId=A`, put B, read current, read `?versionId=A` | Pinned and unqualified URLs are different resources. The current B read is excluded from the pinned-resource path. |
| `two_object_bundle` | Change admission, change fee, restore fee, restore admission | Five stable pairs and four client captures distinguish real coexistence from an equality baseline's overlapping bridges. |

These are controlled mechanisms, not random samples or production failure
rates. Same-body tests use the exact decoded bytes; SHA-256 records input
integrity. Native opaque identifiers remain unchanged in JSON/CSV. Aliases
`v0`, `v1`, ... are assigned by first appearance in response order and their
complete mapping is in `version-id-map.csv`.

## What the derivation establishes

`derive.py` imports `src/history_contracts.py`. `Contract.certifiable_endpoints`
contains only successful 200 states; internal 404 delete-marker states are not
dropped from the transition graph. A 404 state's model `body` and `actual` are
the explicit absence symbol; its error XML is preserved unchanged in the raw
trace and observations CSV. This symbol is not an object payload or a measured
response body. Non-endpoint model `body` values do not authorize a bridge.
The auditor emits a return witness or a
safety invariant. Separate `verify_witness`/`verify_certificate` functions check
the actual path edges/body departure or invariant closure, without trusting the
auditor's Boolean result. They do not independently prove shortestness.

Two different model classes are preserved:

* **Finite recorded paths:** the ordered responses for one resource, with
  residence/stuttering. A positive invariant is only a statement about that
  declared path model. Different endpoint IDs in copy/reupload cases fail the
  equality baseline; passing their finite path does not establish an API-wide
  no-return contract. Two point reads alone are not a complete history.
* **Declared API reactivation obstructions:** the S3 operation rule permits a
  retained current version to be hidden by a new version and selected again
  when the new version is deleted. A three-state submodel suffices to refute an
  unrestricted current-key equality contract; it is not a complete API model.
  Endpoints use an actually observed body and opaque ID. The unread internal
  state's validator is explicitly a model-only placeholder, never invented
  HTTP evidence. The executed `delete_current` example and the
  [AWS restore documentation](https://docs.aws.amazon.com/AmazonS3/latest/userguide/RestoringPreviousVersions.html)
  identify the operation pattern.

For the bundle, admission really departs between its captures. Fee is stable
between its two captures in this recorded schedule. Its capture-window path
therefore has a positive finite invariant; this is kept in the output. An
unrestricted current-key API still permits fee's ID to be selected again in a
different permitted execution. Hence the generic native-ID contract cannot
authorize either bridge merely from equality. The report does not falsely say
that a fee interruption occurred in this run.

The raw-equality consumer is an explicit research baseline, not an identified
archive implementation. Its claimed bridge is `[first_response_end,
second_request_start)` on the runner's monotone clock. The bundle report checks
that its two baseline bridges overlap while the target pair is absent from all
five stable phases. That absence relies on this runner's single writer,
acknowledged atomic one-key mutations in A,B,B,A order, and readback after every
mutation. The two GETs forming a phase are not an atomic multi-object snapshot.
The derivation checks request order and mutation placement; it cannot prove the
absence of external writers from a transcript alone.

The pinned-selector case can have a bridge only for the declared retained
version resource/path. It supplies no historical-current-key guarantee and
does not establish the provider's entire version-specific API, deletion,
authorization, or retention behavior.

## Files

* `data/trace.json`: original request/response bytes (base64), native headers,
  actual status, request selectors, operation/capture references and monotone
  windows. Request authorization uses only public local fixture credentials.
* `derived/models.json`: exact finite contracts, endpoint scopes, source record
  mappings, and the distinction between recorded evidence and API assumptions.
* `derived/audit.json`: auditor output, full invariants or witnesses, and
  independent verification outcomes.
* `derived/results.json`: case decisions, interval overlap, evidence scopes and
  input/code hashes.
* `derived/summary.csv`, `observations.csv`, `phases.csv`,
  `version-id-map.csv`: exact plot-ready records and reversible ID aliases.

No installed dependency or absolute workspace path is required by derive.
Copying this directory alone is insufficient: include `src/history_contracts.py`
at the same repository-relative location. Re-derivation from the same trace and
code is deterministic. A fresh server run has new IDs, request signatures and
times, so its raw or derived bytes need not equal a previous run.

## Evidence boundary with GCS

The positive GCS comparison is separately documented in
`research/main-use-round7.md`. Its cloud operation rules are official-document
evidence, not a Google Cloud server experiment. The separate
`experiments/gcs_selector/` harness executes the real Python SDK against injected
local responses to inspect current-name versus generation-pinned request
selection; those responses are fixtures. Neither source should be merged into
this MinIO trace or represented as a three-provider cloud benchmark.

MinIO execution, AWS documented API behavior, GCS documented operation scope,
and SDK request-construction evidence establish different facts. This artifact
preserves those distinctions and does not claim a new storage vulnerability.
