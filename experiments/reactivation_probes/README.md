# Current-key identity probes across S3-compatible servers

`run.py` runs one fixed probe sequence against a locally started server and
records every request and response byte for byte. `run_gcs.py` runs the
corresponding generation probes against a local GCS JSON-API emulator.
`derive.py` reclassifies every outcome offline from the raw records; the
runner's case summaries are only used to locate request indices and are
checked against the raw response they name.

All servers ran on loopback in a fresh temporary store with public fixture
credentials. No cloud account or cloud service was used. These are local
executions of each implementation, not measurements of Amazon S3 or Google
Cloud Storage.

## Recorded executions

Executed on 2026-11-05, Linux x86_64, Python 3.13.18, one run per
implementation, 445 requests in total.

| Server | Version and distribution | Requests |
|---|---|---:|
| MinIO | RELEASE.2025-09-07T16-13-09Z, official linux-amd64 binary (SHA-256 matches `../versioned_objects/server-release.json`) | 51 |
| Ceph RADOS Gateway | 19.2.0 squid, `quay.io/ceph/demo:latest-squid`, single-node mon/mgr/osd/rgw cluster | 51 |
| SeaweedFS | 3.97, official `linux_amd64.tar.gz` release | 53 |
| Versity S3 Gateway | v1.10.0, `go install github.com/versity/versitygw/cmd/versitygw@v1.10.0`, posix backend with `--versioning-dir` | 51 |
| RustFS | 1.0.4, `rustfs/rustfs:latest` (image digest in the trace) | 51 |
| Scality CloudServer | 9.0.27, `ghcr.io/scality/cloudserver:9.0.27`, memory backend | 51 |
| LocalStack | 4.9.2, `localstack/localstack:4.9`, S3 service only | 52 |
| moto | 5.1.15, PyPI `moto[server]==5.1.15`, server mode | 51 |
| fake-gcs-server | v1.56.1, `go install github.com/fsouza/fake-gcs-server@v1.56.1`, memory backend | 34 |

Executable SHA-256 values or image digests, the server version string and the
client platform are stored in each trace's `implementation` and `client`
fields. Server logs are kept as a short tail where the runner captured them.

## Probes

Every probe uses a new key and three current-name captures: before the
change, during it and after the restoring operation.

| Probe | Operations | What the last capture shows |
|---|---|---|
| `delete_current` | put A, put B, delete B by version ID; then a conditional GET with the first ETag | whether A returns under its original ID |
| `delete_marker` | put A, insert a delete marker, delete the marker by version ID | whether A returns under its original ID after a 404 |
| `object_lock_marker` | the same in a bucket created with Object Lock, A written with COMPLIANCE retention; also a direct deletion of A's version | whether retention prevents the return |
| `suspended_null` | enable then suspend versioning; put A, B, A | whether the identifier changes across the rewrite |
| `copy_restore` | put A, put B, copy A's version onto the key (retried with replaced metadata, then with a bucket-relative source, if refused) | whether restored bytes get a fresh ID |
| `reupload` | put A, put B, put A; conditional GET with the first ETag | fresh ID and whether the content ETag repeats |

The GCS emulator probes delete the live generation by number, delete the live
object without a generation, copy an old generation onto the live name, and
upload old bytes again.

## Results

`derived/matrix.csv` has one row per server and probe with the raw evidence
indices; `derived/summary.json` lists the findings.

* All eight S3 servers make the displaced version ID current again after
  `delete_current` and after `delete_marker`.
* Seven do so after inserting and removing a marker over a COMPLIANCE-retained
  version; direct deletion of the retained version was refused by all seven.
  SeaweedFS 3.97 answered the retained PUT with 500 InternalError, so the probe
  did not run there.
* All eight keep the identifier (`null` or absent) unchanged across the
  suspended-versioning rewrite.
* Copy restoration allocates a fresh ID on seven servers. SeaweedFS refused a
  same-key version copy in all three request forms; LocalStack refused the plain
  form ("copy an object to itself") and accepted it with replaced metadata.
* Re-uploading A allocates a fresh ID everywhere but repeats A's ETag, and the
  conditional GET with the first ETag returns 304 after both the reupload and
  the delete-current return.
* The GCS emulator never promotes an older generation: deleting the live
  generation leaves 404, and copy and upload allocate new generations.

## Reproduce

Offline, from the repository root:

```sh
python3 -B experiments/reactivation_probes/derive.py --output /tmp/reactivation-derived
cmp /tmp/reactivation-derived/matrix.csv experiments/reactivation_probes/derived/matrix.csv
```

A fresh execution needs the server programs and loopback ports; Docker is
needed for Ceph, RustFS, CloudServer and LocalStack. Pass the directory that
holds `minio`, `versitygw`, `weed` and `fake-gcs-server`:

```sh
python3 -B experiments/reactivation_probes/run.py --server minio \
  --tools /path/to/bin --output /tmp/probes/minio.json
python3 -B experiments/reactivation_probes/run_gcs.py \
  --emulator /path/to/bin/fake-gcs-server \
  --output /tmp/probes/fake-gcs-server.json
```

Replace `minio` by `ceph`, `seaweedfs`, `versitygw`, `rustfs`,
`cloudserver`, `localstack` or `moto`. moto is started from a virtual
environment two levels above the tools directory (`moto-venv/bin/python`).
New runs produce new identifiers, signatures and times; compare outcomes, not
bytes. The runner refuses to overwrite a trace.

## Scope

A probe establishes what one implementation did for one sequence. It does not
establish every API path, concurrency interleaving or administrative
operation, and it does not test the corresponding cloud service. The
classification needs only the recorded responses; the theorem that turns a
returned identifier into a failed continuity certificate is in the paper.
