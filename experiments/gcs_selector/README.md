# GCS Python SDK selector fixture

This executes the official Google Cloud Storage Python SDK against a small simulated HTTP origin on `127.0.0.1`. It tests request construction and response-field extraction. **It does not contact or test the GCS service.** The server deliberately implements a current A → B transition with retained old A; that behavior is an input, not an experimental finding about a cloud service.

The archived run uses Python 3.12.10 and `google-cloud-storage==3.17.1`. `requirements.lock` fixes all 21 installed dependencies. No credentials or real identities are used. The explicit transport disables environment proxies and refuses requests outside the ephemeral loopback endpoint. The server closes when the run ends. In a sandbox that forbids local socket binding, execution needs the corresponding permission even though no external endpoint is used.

Reproduce from this directory:

```sh
uv --cache-dir /tmp/round7-uv-cache venv /tmp/round7-gcs-sdk-venv --python python3.12
uv --cache-dir /tmp/round7-uv-cache pip install --python /tmp/round7-gcs-sdk-venv/bin/python -r requirements.lock
/tmp/round7-gcs-sdk-venv/bin/python run.py --verify
```

`--verify` generates a new loopback exchange and compares the complete `summary.json`, the installed `blob.py` SHA-256, and exact dependency versions with the archived run. It does not overwrite artifacts. The archived `capture.json` preserves original absolute request URLs, headers, response fields, data, hashes, runtime and package versions. Runtime platform, ephemeral port and invocation UUIDs differ across runs and are not compared; all request targets, generation selectors, object generations and returned bytes in the semantic summary are compared. `--record` deliberately replaces the two archived outputs and is intended only when making a new capture.

There are three cases and exactly six GETs:

| Case | Observation after server current changes from 101/A to 202/B |
| --- | --- |
| Reuse an initially unbound Blob | SDK adds `generation=101`; simulated origin returns 101/A |
| Create a fresh unbound Blob | No selector; simulated origin returns 202/B |
| Explicit generation=101 control | Selector present on both requests; simulated origin returns 101/A |

All use full single-shot raw downloads, no ranges, no retry and no checksum verification. The latter two controls make each call one observable fixture request; they are not production recommendations. SDK request capture includes `accept-encoding: gzip`. No compressed-body case is claimed by this experiment.

Official source is Apache-2.0; it is installed as an external dependency, not vendored here. Its pinned source location and hash are in `source-manifest.json`. The `Blob` source extracted from the installed wheel matches that pinned official source (the temporary file transfer added one terminal newline, which was removed before equality/hash comparison). Other dependencies retain their respective upstream licenses. The fixture itself uses no copied SDK implementation.

The documented service-level positive claim, fresh-read conditions, namespace exclusions and manuscript-ready paragraph are in the full delivery at `research/main-use-round7.md`. In particular, the claim is restricted to a continuously existing flat-namespace bucket and ordinary finalized immutable objects; it excludes HNS renames, Rapid appendable objects and authority restoration. The local fixture establishes none of those service properties.
