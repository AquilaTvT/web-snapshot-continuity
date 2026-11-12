# 05-certification-rule

Main-paper Figure 1.

Panel a is drawn from the native MinIO execution in
`../../experiments/versioned_objects/` (`trace.json` here is a byte-identical
copy, SHA-256 checked by `derive.py`). It shows the recorded two-page bundle
case on the runner's monotone clock in milliseconds: every state interval,
write window, capture window and version ID comes from requests 31–50 of the
trace. Captures 1 and 4 read the admission page as `eligible` under the same
version ID because the restore deleted the newer version; captures 2 and 3 read
the fee page while it holds `10`. `derive.py` checks that the two equality
bridges overlap (the fee page's bridge, 18.166 µs, lies inside admission's) and
that `eligible` and `10` cannot hold at a common instant: admission's change
completes before fee's change starts, and fee's restore completes before
admission's restore starts. State boundaries are only known to lie in the
hatched write windows. The strip under the main axis magnifies the time axis
exactly sixty times around the instant both bridges claim (`plot.py` asserts
the ratio and that the 18 µs bridge lies inside the strip); the vertical line
marks that instant, and the cross marks admission's state there.

Panel b is an explicit construction (`construction.json`): three resources with
sound fields captured in the order R1, R2, R3, R2, R1. `derive.py` checks the
pairwise condition `first_end(i) <= last_start(j)` for all `i != j`, writes the
interval on which each revisited resource is present in every consistent
history (`presence` rows) and their common part (`revisited_common`), and checks
that R3's single window lies inside it. R3's read instant is unknown; the
hollow marker `t*` (`schematic_read`) is placed inside its window only to show
that every history has a common instant, at R3's read, while no instant is
shared by all histories (Corollary 4).

Visual encoding, shared with Figure 2: blue for what a sound field proves,
red for the inference that fails, grey for states the captures do not show,
hatching for write windows. Each panel has a one-line caption centred below
it; explanations are in the figure caption.

Copy this directory anywhere and run:

```sh
python3 derive.py
python3 plot.py
```

Both scripts use only the Python standard library (`requirements.txt` lists
the TeX and poppler tools instead). `plot.py` reads only `plot-data.csv` and
writes the figure as TikZ code (`figure.tex`; `figstyle.tex` holds the colours
and type sizes shared with Figure 2). XeLaTeX sets it in the acmart typefaces
shipped in `fonts/` (Linux Libertine O, Libertinus Math) at the column width of
the acmart sigconf layout, 241.15 pt (3.34 x 2.28 in), so the paper includes it
unscaled and its text matches the body: 7–8 pt, with sub- and superscripts at
6 pt. `pdftocairo` and `pdftoppm` then write `figure.svg` and `preview.png`.
Before finishing, `plot.py` checks that the page has the column width, that
every font is embedded and none is Type 3, that no text is set below those
sizes, and, from a 600 dpi rendering, that no ink touches the page edge and no
text box leaves the page. `SOURCE_DATE_EPOCH` is fixed inside the script, so
rebuilds are byte-identical. Greek letters are aliases; `plot-data.csv` keeps
the native version IDs. `MANIFEST.sha256` covers every other file, including
those under `fonts/`.
