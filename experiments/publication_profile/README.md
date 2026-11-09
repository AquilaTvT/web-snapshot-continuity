# Publication permissions and current-version continuity

This experiment executes the existing manuscript's operation boundary on an unmodified native MinIO server. It adds no snapshot protocol. Both programs are official, hash-pinned releases; all credentials in the trace are public local fixtures, not cloud credentials.

The completed execution contains **8 cases, 60 signed S3 requests and 5 management commands**. It uses fresh temporary storage and loopback HTTP. No AWS or Google Cloud account is contacted. The management client config is isolated under the same temporary directory; user configuration is never used.

| Case | Recorded result | What it establishes |
|---|---|---|
| Owner with bucket deny | Deleting B succeeds, original A/ID returns | This MinIO root identity is not constrained by the installed bucket policy |
| Restricted publisher, data version | DELETE 403; B stays current; copying A returns A with a new ID | Tested deletion is blocked without removing copy restoration |
| Restricted publisher, delete marker | Marker insertion 204; current GET 404; marker removal 403; copying A returns a new ID | The policy also covers marker deletion |
| Restricted publisher, batch deletion | HTTP 200 with two per-object AccessDenied errors | Transport success is not operation success |
| Restricted configuration | Versioning suspension, policy replacement, lifecycle installation each return 403 | The tested identity cannot change these configurations |
| Stable two-object bundle | Repeated current IDs; positive conservative bridge intersection despite an unrelated write | One concrete positive capture under the declared contract |
| Multipart uploads | A initiated first; B completed first; both completions allocate fresh IDs; A is finally current here | PutObject permission includes more than single-request PUT; this is MinIO's recorded ordering |
| Compliance retention | Data deletion returns 400/InvalidRequest with WORM protection; marker insert/remove returns 204; original A/ID returns across 404 | Retained data does not imply uninterrupted current publication |

The first attempt stopped at the retention response because the harness expected HTTP 403; MinIO returned HTTP 400 with an explicit WORM-protection message. `data/attempt-01-incomplete.json` preserves that unmodified evidence. The completed run checks the actual 400/InvalidRequest refusal and continues through marker removal. It is a separate fresh server run, not an edited trace. The incomplete attempt is not counted in the 60-request completed execution.

## Scope and proof obligation

The positive mathematical premise is that each immutable current identity cannot become current again after departure. A fixed total order on immutable data/marker records, with record insertion only and maximum-record selection, suffices. This is an elementary sufficient invariant, not a claim that all safe histories require that order.

The measured publisher has one explicit IAM policy. Root is quiescent during the restricted cases. There is no lifecycle or replication configuration, bucket/authority reset, other writer, or administrative rollback. The experiment does not verify all possible operations admitted by an IAM action. In particular, the two single-part multipart uploads do not establish a unified ordering for all multipart/copy/delete races. AWS's documented initiation ordering must not be inferred from this local compatible server's completion observations. Denying all version deletion also disables noncurrent-version garbage collection; the policy is conservative, not minimal.

The stable bundle is a constructed control, not a production workload, throughput result, or estimate of how often a useful bundle is accepted. The owner-policy control is not an AWS vulnerability. Object Lock behavior is consistent with the documented exclusion of delete markers from WORM retention.

## Offline verification

```sh
python3 experiments/publication_profile/derive.py \
  --trace experiments/publication_profile/data/trace.json \
  --output /tmp/publication-profile-derived --self-test
```

The independent derivation reconstructs observations, refusal semantics, version identity relations, principals, raw-byte hashes and request signatures. Fixture signatures are checkable consistency evidence, not cryptographic provenance against a party possessing these public keys. The full trace is copied unchanged into `figure-artifacts/04-publication-policy/`; the figure's own independent derivation selects exact request indices and full version IDs.

## Run the actual native service again

Use Python 3.12, curl, and a supported macOS/Linux platform. Download the two pinned programs:

```sh
python3 experiments/versioned_objects/download_server.py \
  --output /tmp/continuity-minio
python3 experiments/versioned_objects/download_server.py \
  --release-file experiments/publication_profile/mc-release.json \
  --output /tmp/continuity-mc
python3 experiments/publication_profile/run.py \
  --minio /tmp/continuity-minio --mc /tmp/continuity-mc \
  --output /tmp/publication-profile-run
python3 experiments/publication_profile/derive.py \
  --trace /tmp/publication-profile-run/trace.json \
  --output /tmp/publication-profile-derived --self-test
```

Only downloading needs external network access. Running needs local loopback sockets. Choose a fresh output directory: the runner refuses to overwrite an existing raw trace. It always preserves partial evidence on failure and terminates its own server. New runs have different IDs, signatures, dates and windows; compare semantic findings, not byte identity. The checked release manifests cover four platforms; only the recorded Darwin/arm64 execution is claimed here. The official server/client release pages carry their upstream licensing information; neither executable is redistributed in the artifact.

Primary references: [Object Lock](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock-managing.html), [multipart operations and permissions](https://docs.aws.amazon.com/AmazonS3/latest/userguide/mpuoverview.html), [pinned MinIO authorization implementation](https://github.com/minio/minio/blob/07c3a429bfed433e49018cb0f78a52145d4bedeb/cmd/auth-handler.go). Pinned consumer-source and prior-theory audits are in the full delivery's Round 8 research notes.
