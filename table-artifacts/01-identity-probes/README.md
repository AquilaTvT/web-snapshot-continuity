# 01-identity-probes

Main-paper Table 1. `traces/` holds the nine unmodified probe traces (445
recorded loopback requests). `derive.py` is the same offline classifier as
`experiments/reactivation_probes/derive.py`, reading `traces/` and writing
`matrix.csv` and `summary.json` here. `make_table.py` reads `matrix.csv`, `caption.txt` and
`legend.txt` and writes `table.tex`, which the manuscript inputs. Standard
library only; no network.

```sh
python3 -B derive.py
python3 make_table.py
```

Symbols, as in `legend.txt`: $\bullet$ an identifier read before the change is
current again after it (for the suspended-versioning probe: the identifier is
unchanged across a change of bytes), so equal identifiers would certify a false
continuity; $\circ$ the identifier differs, or no version is current; $\times$
the request failed; `--` no such operation. Every S3 upload repeats the first
ETag. `make_table.py` also checks the
caption's request and server counts against `summary.json`. The evidence column
of `matrix.csv` lists the request indices behind every cell. `MANIFEST.sha256`
covers every other file.
