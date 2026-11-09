# Figure artifacts

Each numbered directory is independent: derive.py + plot.py + frozen inputs + precise plot-data.csv + PDF/SVG/preview + caption + metadata + SHA-256 manifest. Copy one directory, install its requirements, run derive.py then plot.py. No paper-generation code is required. Figures 05 and 06 are drawn in TikZ and PGFPlots and typeset with XeLaTeX in the acmart typefaces shipped in their fonts/ folders, at the paper's column width; they need TeX Live and poppler but no Python package. 01-04 are drawn with Matplotlib.

Main paper: 05 (Figure 1: a native MinIO return and reads in the revisit order) and 06 (Figure 2: complete revision histories). Table 1 is generated in ../table-artifacts/01-identity-probes. Earlier figures are retained as complete mechanism controls: 01 indistinguishable histories, 02 framework validators, 03 native current-key version histories, 04 native permission and retention contrasts.
