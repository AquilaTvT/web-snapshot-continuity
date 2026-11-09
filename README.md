# Uniqueness Is Not Continuity: artifact

This repository accompanies the submission *Uniqueness Is Not Continuity:
When Server Metadata Certifies a Web Snapshot*. It is anonymous for review.

* `Uniqueness Is Not Continuity - Supplementary Material.pdf`: complete statements
  and proofs in the paper's numbering, the protocols and full results of the
  local executions and the edit-history replay, and reproduction notes. Its
  Table 1 maps every result of the paper to the code and data below.
* `paper/`: the supplement's LaTeX sources and `paper/numbers.tex`, which
  holds every number printed in the paper. `scripts/paper_numbers.py` writes
  it from the derived evidence, and `scripts/supplement_tables.py` writes the
  supplement's tables.
* `src/`, `tests/`, `scripts/`: the implementations and their checks.
* `experiments/`, `data/`: protocols, collectors, frozen raw inputs and derived
  results. `research/platform-identifiers-round9.*` is the documentation audit
  behind the identifier counts of Section 4.
* `figure-artifacts/`, `table-artifacts/`: one self-contained directory per
  figure or table.

## Check the paper's numbers and rebuild the supplement

With Python 3.12 or later (standard library only):

```sh
python3 -m unittest discover -s tests
python3 scripts/paper_numbers.py
```

The second command recomputes every number printed in the paper, checks
their consistency and rewrites `paper/numbers.tex`, which should not change.
With TeX Live's XeLaTeX (2023 or later), poppler and the Linux
Libertine O and Biolinum O fonts installed (for example the Debian package
`fonts-linuxlibertine`):

```sh
python3 scripts/build_supplement.py
```

`build_supplement.py` regenerates the supplement's tables, fails on any layout
or reference warning and writes `output/pdf/Uniqueness Is Not Continuity - Supplementary Material.pdf`,
byte-identical to the copy at the top of this repository. The supplement uses
the unmodified acmart 2.21 class in `paper/`; `paper/vendor/acmart/` keeps its
upstream sources and licence.

`MANIFEST.sha256` lists the SHA-256 of every file in this repository.
`SOURCES.md` gives the provenance and licences of every input; of the records
under `research/` that it mentions, this repository includes the documentation
audit and `research/supplement-earlier-rounds.md`.

## Code and data

Run the following from the repository root with Python 3.12 or later:

```sh
python3 -m unittest discover -s tests -v
python3 scripts/verify_aba.py
python3 scripts/run_contracts.py
python3 scripts/run_validator_synthesis.py
python3 scripts/run_experiments.py
python3 scripts/run_revision_audit.py
python3 scripts/check_label_objective.py --output data/derived/label-objective-audit.json
```

The evidence the paper uses is reproduced offline with:

```sh
python3 scripts/check_certification.py
python3 -B experiments/reactivation_probes/derive.py
python3 -B experiments/revision_bundles/derive.py
python3 -B experiments/revision_bundles/addendum.py
python3 -B experiments/revision_bundles/addendum2.py
```

`check_certification.py` re-runs the exhaustive and randomized checks of the
common-instant test, the fixed-instant test, its counterexample constructor,
the worst-case sweep, the coNP construction, the component criterion for
repairable fields and its finite refinements, and writes
`data/derived/certification-audit.json`. The derivations reclassify the nine
native probe traces and rebuild the revision-history measurements and both
post hoc addenda from the frozen API responses, binding every page's initial
state to its raw response; their outputs are byte-identical to the archived
`derived/` directories.

These commands use local inputs and the Python standard library. The tests independently check interval operations, contract certificates, label synthesis, source-history provenance, and intermediate HTTP state transitions. The MDN check compares the supplied bytes and hashes; it does not contact the current website. Software versions are recorded with each experiment.

## Rebuild a figure independently

Each directory under `figure-artifacts/` contains its own sources, exact plotted values, derivation, drawing code, caption, dependencies, vector outputs, preview, and hash manifest. Copying one directory is sufficient to verify its data and redraw it.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r figure-artifacts/01-observation-ambiguity/requirements.txt
.venv/bin/python figure-artifacts/01-observation-ambiguity/derive.py
.venv/bin/python figure-artifacts/01-observation-ambiguity/plot.py
```

Replace the directory name to run another figure. `derive.py` checks or reconstructs `plot-data.csv` from the supplied source inputs. `plot.py` reads that table and writes `figure.pdf`, `figure.svg`, and `preview.png`. Neither step needs network access after installing the plotting dependency. Figures 05 and 06 (the manuscript figures) need no Python package: `plot.py` writes TikZ and PGFPlots code (`figure.tex`, with the shared style in `figstyle.tex`) and typesets it with XeLaTeX (TeX Live with fontspec, unicode-math, PGF/TikZ and PGFPlots 1.18) and poppler's `pdftocairo`, `pdftoppm`, `pdfinfo`, `pdffonts` and `pdftotext`. Their typefaces are shipped in each directory's `fonts/` folder, `plot.py` checks page width, font embedding, type sizes and clipping, and fixed `SOURCE_DATE_EPOCH` makes rebuilds byte-identical. To assemble and run all figure directories from the repository root:

```sh
.venv/bin/python scripts/build_figure_artifacts.py
```

The builder coordinates the per-figure derivation and plotting programs. The derivations remain beside their inputs; they are not hidden inside a paper build.

| Directory | Input and verification |
|---|---|
| `01-observation-ambiguity` | Explicit constructed histories and capture records; verifies identical observations with different coexistence conclusions |
| `02-http-validators` | Six frozen framework traces; recomputes the displayed endpoint and conditional-response outcomes |
| `03-versioned-heads` | Native MinIO current-key reads; reconstructs four operation histories with full version-ID mappings |
| `04-publication-policy` | Native owner, Object Lock and restricted-publisher contrasts; full trace, exact principals, IDs and windows |
| `05-certification-rule` | Main-paper Figure 1: the recorded MinIO two-page return (full trace copy) and a constructed read in the revisit order, with the certain-presence intervals and a schematic read instant |
| `06-revision-histories` | Main-paper Figure 2: the complete frozen revision collection and unmodified copies of its preregistered analysis and both post hoc addenda |

`table-artifacts/01-identity-probes/` holds main-paper Table 1: the nine probe
traces, the offline classifier, `matrix.csv`, `make_table.py` and the generated
`table.tex`. Run `python3 -B derive.py` and `python3 make_table.py` inside a
copy of the directory.

## Replay the controlled HTTP executions

The frozen traces can be checked offline. Re-executing servers also requires permission to bind ephemeral loopback ports:

```sh
python3 scripts/run_http_demo.py
npm ci --prefix experiments/http_stacks
python3 scripts/run_stack_experiments.py
```

`run_http_demo.py` runs the small controlled example. `run_stack_experiments.py` runs Express with weak and strong ETags, Python's static server with fresh and restored modification times, and Apache with both timestamp policies. Node dependencies are pinned in `experiments/http_stacks/package-lock.json`; `node_modules` is not included and is recreated by `npm ci`.

The live Apache configuration loads shared modules from `--apache-modules` (default `/usr/libexec/apache2`, macOS) and accepts modules compiled into the binary; `--apache` selects the executable. On Debian or Ubuntu use `--apache /usr/sbin/apache2 --apache-modules /usr/lib/apache2/modules` with a new `--output` and `--derived`. The frozen macOS and Linux traces and their tests do not require Apache installation. The experiment records software versions, request methods and headers, response bodies and hashes, validators, statuses, and every controlled intermediate mutation. Static rollback withdraws the second target before restoring the first. A regression test replays the old opposite order and detects its transient mixed bundle.

## Data and interpretation

`data/raw/` retains MDN source states, public revision responses and framework traces. `data/derived/` retains construction results, contract outcomes, synthesis certificates and revision audits. Figure directories duplicate only the inputs needed for independent reproduction. `SOURCES.md` and notices document provenance and third-party terms. Third-party paper PDFs are not included.

The HTTP experiments demonstrate controlled validator behavior. A 304 response is not itself a server defect. Equal endpoint content or validators do not prove intervening continuity without the relevant history contract. The MDN example concerns source history, not measured deployment behavior.

`MANIFEST.sha256` records the bytes as packaged. Per-figure manifests cover local inputs and outputs. Rebuilding intentionally changes generated files if the inputs or software change; retain the original manifest when comparing a new run against the delivered archive.

## Natural source-revision evidence

`python3 scripts/run_revision_audit.py` verifies the frozen API responses and
rebuilds `data/derived/revision-audit.json` and `revision-summary.csv` offline.
The six fixed pages contain 634 recorded revisions and 131 nonadjacent content
hash returns; the first return per page is independently checked against three
source texts, giving six byte-verified witnesses. Counts of hash returns must
not be described as 131 byte-verified cases. Consecutive parent links are checked,
but historical deletions, template expansion, rendering, cache state, and actual
serving times are outside this collection.

The two `collect_revision_*.py` scripts document acquisition and refuse to
overwrite a frozen snapshot. Network recollection is unnecessary for reproducing
the saved result. A new collection requires a descriptive `--user-agent` with
operator contact in accordance with Wikimedia policy. Source text is supplied
under its own attribution and license, retained next to the data.

## Native object-version and SDK experiments

`experiments/versioned_objects/` contains a pinned native MinIO server runner, complete loopback request/response records, offline contract derivation and a release download script. The server binary is an external dependency, not bundled. See that directory's README for exact commands and for the distinction between recorded-path results and the documented API obstruction. These are local executions, not AWS cloud measurements.

`experiments/gcs_selector/` contains an official `google-cloud-storage==3.17.1` SDK fixture, all 21 dependency pins, six original requests, source provenance and a verification command. It tests SDK request construction against a simulated loopback origin; it does not test the GCS service. The frozen captures and semantic summary can be inspected without the SDK.

Successful endpoint reads are explicitly scoped by `Contract.certifiable_endpoints`; all internal states remain in reachability. A 404 without a continuity token is not silently removed. Label synthesis remains the full-endpoint (`R=V`) problem.

`experiments/reactivation_probes/` runs one fixed probe sequence against eight
S3-compatible servers (MinIO, Ceph RGW, SeaweedFS, Versity Gateway, RustFS,
Scality CloudServer, LocalStack, moto) and a GCS JSON-API emulator on loopback,
445 recorded requests. Servers are obtained from their upstream distributions;
Docker is needed for four of them. Its README lists versions, digests and the
exact rerun commands. `experiments/revision_bundles/` holds the protocol
committed before collection, the collector (with a replaying `--resume` mode
used after an interruption), the frozen responses and the analysis. Linux
replications of the six HTTP stacks are in `data/raw/http-stacks-linux/`;
`scripts/run_stack_experiments.py --apache /usr/sbin/apache2 --apache-modules
/usr/lib/apache2/modules --output <new directory> --derived <new csv>` reruns
them on Debian or Ubuntu and refuses to overwrite existing traces.

`experiments/publication_profile/` contains the additional eight-case, 60-request native permission experiment, its independent verifier and the separately preserved incomplete first attempt. The management client is hash-pinned but not bundled. See that directory for commands and scope: finite native refusals do not establish all allowed API interleavings. The main manuscript uses figures 05 and 06 and Table 1 (`table-artifacts/01-identity-probes`); figures 01–04 remain complete independent mechanism controls.
