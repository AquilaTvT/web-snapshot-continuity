"""Draw figure.pdf, figure.svg and preview.png from plot-data.csv only.

The figure is written as PGFPlots/TikZ (figure.tex) and typeset by XeLaTeX in
the paper's own faces, Linux Libertine O and Libertinus Math (shipped in
fonts/), at the exact column width of the acmart sigconf layout, so it is
included without scaling and its text matches the body. figstyle.tex holds the
shared colours and sizes: red for content hashes (a reusable field), blue for
revision IDs (a sound field). A confidence interval whose lower end is zero
cannot be drawn on a log axis; it runs to the axis and ends in an arrow. After
building, the script checks the page width, font embedding, that text is at
least 7 pt and exponents at least 6 pt, and that no ink touches the page edge.
Requires XeLaTeX with fontspec, unicode-math
and PGF/PGFPlots (TeX Live), and poppler's pdftocairo, pdftoppm, pdffonts and
pdftotext.
"""
from pathlib import Path
import csv
import math
import os
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent
WIDTH = 241.14749          # \columnwidth of acmart sigconf, in pt
rows = list(csv.DictReader((ROOT / "plot-data.csv").open(newline="")))


def f(x):
    return f"{x:.6g}"


def p(x):
    return f"{x:.2f}"


out = []
emit = out.append

# ---------------------------------------------------------------- panel (a)
YMIN, YMAX = 2.5e-5, 60.0
emit(r"\node[font=\figtitle, anchor=base west, inner sep=0pt] at (0.8,-7.6) "
     r"{\textbf{(a)}\enspace Equal-hash revisits that hid a change, by revisit gap};")
emit(r"""\begin{axis}[name=a, at={(36pt,-74pt)}, anchor=south west, scale only axis,
  width=172pt, height=55pt, xmode=log, ymode=log,
  xmin=40, xmax=1.0e6, ymin=%s, ymax=%s,
  xtick={60,3600,86400,604800}, xticklabels={1\,min,1\,h,1\,d,7\,d},
  ytick={1e-4,1e-3,1e-2,1e-1,1,10}, yticklabels={$10^{-4}$,$10^{-3}$,$10^{-2}$,$10^{-1}$,$1$,$10$},
  minor tick style={draw=none}, tick align=outside, tick style={rule, line width=0.4pt}, major tick length=2pt,
  axis line style={rule, line width=0.4pt}, axis lines*=left,
  ymajorgrids, grid style={black!9, line width=0.4pt},
  tick label style={font=\figsmall}, label style={font=\figlabel},
  ylabel={hidden change (\%%)}, ylabel style={yshift=-3pt},
  clip=false]""" % (f(YMIN), f(YMAX)))
styles = {"vital": ("solid", "*", "fails", "vital articles"),
          "random": ("dash pattern=on 2.6pt off 1.6pt", "square*", "white", "random articles")}
legend = []
for stratum, (dash, mark, fill, name) in styles.items():
    pts = sorted((r for r in rows if r["panel"] == "a" and r["stratum"] == stratum),
                 key=lambda r: int(r["gap_seconds"]))
    coords = " ".join(f"({int(r['gap_seconds'])},{f(100 * float(r['value']))})" for r in pts)
    for r in pts:
        x = int(r["gap_seconds"])
        lo, hi = 100 * float(r["ci_low"]), 100 * float(r["ci_high"])
        if lo > 0:
            emit(rf"\draw[fails, line width=0.55pt] (axis cs:{x},{f(lo)}) -- (axis cs:{x},{f(hi)});")
        else:     # the interval reaches zero, which a log axis cannot show
            emit(rf"\draw[fails, line width=0.55pt, -{{Stealth[length=2.6pt, width=2.4pt]}}] "
                 rf"(axis cs:{x},{f(hi)}) -- (axis cs:{x},{f(YMIN)});")
    emit(rf"\addplot[fails, line width=0.75pt, {dash}, mark={mark}, mark size=1.7pt, "
         rf"mark options={{solid, fill={fill}, draw=fails, line width=0.6pt}}] coordinates {{{coords}}};")
    last = pts[-1]
    value = 100 * float(last["value"])
    text = f"{value:.1f}\\%" if value >= 1 else f"{value:.2f}\\%"
    emit(rf"\node[font=\figsmall, anchor=west, inner sep=0pt] at (axis cs:{int(last['gap_seconds']) * 1.45},{f(value)}) "
         rf"{{{text}}};")
    legend.append((dash, mark, fill, name))
emit(r"\end{axis}")
# Legend in the upper left of panel (a), drawn by hand for exact spacing.
for k, (dash, mark, fill, name) in enumerate(legend):
    y = -23.0 - 8.6 * k
    emit(rf"\draw[fails, line width=0.75pt, {dash}] (44,{p(y)}) -- (58,{p(y)});")
    shape = r"circle (1.7pt)" if mark == "*" else r"+(-1.6pt,-1.6pt) rectangle +(1.6pt,1.6pt)"
    emit(rf"\filldraw[fill={fill}, draw=fails, line width=0.6pt] (51,{p(y)}) {shape};")
    emit(rf"\node[font=\figsmall, anchor=west, inner sep=0pt] at (61,{p(y)}) {{\strut {name}}};")

# ---------------------------------------------------------------- panel (b)
get = {r["method"]: r for r in rows if r["panel"] == "b"}
order = (("id_double_closed", "hash_double_closed", "double collect (16)"),
         ("id_drop_center", None, "center read once (15)"),
         ("id_exact", "hash_exact", "revisit order (15)"),
         ("mixed_center_theorem", None, "hash page at center (15)"))
XL, XR = 2500, 2880
top_b = -93.0
emit(rf"\node[font=\figtitle, anchor=base west, inner sep=0pt] at (0.8,{p(top_b)}) "
     r"{\textbf{(b)}\enspace Eight vital pages, request starts 1\,h apart};")
ax0, ax1 = 98.0, WIDTH - 10.0
xb = lambda v: ax0 + (v - XL) * (ax1 - ax0) / (XR - XL)
row_y = {0: top_b - 23.0, 1: top_b - 32.0, 2: top_b - 41.0, 3: top_b - 50.0}
y_axis = row_y[3] - 7.5
for v in (2500, 2600, 2700, 2800):
    emit(rf"\draw[black!9, line width=0.4pt] ({p(xb(v))},{p(y_axis)}) -- ({p(xb(v))},{p(row_y[0] + 6.0)});")
emit(rf"\draw[rule, line width=0.4pt] ({p(ax0)},{p(y_axis)}) -- ({p(ax1)},{p(y_axis)});")
for v in (2500, 2600, 2700, 2800):
    emit(rf"\draw[rule, line width=0.4pt] ({p(xb(v))},{p(y_axis)}) -- ({p(xb(v))},{p(y_axis - 2.0)});")
    emit(rf"\node[font=\figsmall, anchor=base, inner sep=0pt] at ({p(xb(v))},{p(y_axis - 9.0)}) {{{v:,}}};")
emit(rf"\node[font=\figlabel, anchor=base, inner sep=0pt] at ({p((ax0 + ax1) / 2)},{p(y_axis - 18.5)}) "
     r"{issued certificates (of 4,000)};")
previous = None
for k, (ids, hashed, label) in enumerate(order):
    y = row_y[k]
    emit(rf"\node[font=\figsmall, anchor=east, inner sep=0pt] at ({p(ax0 - 4.0)},{p(y)}) {{\strut {label}}};")
    base = int(get[ids]["certified"])
    mixed = ids.startswith("mixed")
    if hashed:
        extra = int(get[hashed]["certified"])
        assert extra - base == int(get[hashed]["continuity_violations"]), hashed
        emit(rf"\draw[fails, line width=1.0pt] ({p(xb(base))},{p(y)}) -- ({p(xb(extra))},{p(y)});")
        emit(rf"\filldraw[fill=white, draw=fails, line width=0.7pt] ({p(xb(extra))},{p(y)}) circle (1.9pt);")
        emit(rf"\node[font=\figsmall, text=fails, anchor=west, inner sep=0pt] at ({p(xb(extra) + 3.5)},{p(y)}) "
             rf"{{\strut $+${extra - base:,}}};")
    if mixed:
        emit(rf"\fill[sound] ({p(xb(base))},{p(y + 2.3)}) -- ({p(xb(base) + 2.3)},{p(y)}) -- "
             rf"({p(xb(base))},{p(y - 2.3)}) -- ({p(xb(base) - 2.3)},{p(y)}) -- cycle;")
    else:
        emit(rf"\fill[sound] ({p(xb(base))},{p(y)}) circle (1.9pt);")
    if hashed:
        emit(rf"\node[font=\figsmall, anchor=base, inner sep=0pt] at ({p(xb(base))},{p(y + 3.6)}) {{{base:,}}};")
    else:
        emit(rf"\node[font=\figsmall, anchor=west, inner sep=0pt] at ({p(xb(base) + 3.5)},{p(y)}) "
             rf"{{\strut {base:,}}};")
    if previous is not None and not mixed:
        emit(rf"\node[font=\figsmall, text=muted, anchor=east, inner sep=0pt] at ({p(xb(base) - 3.5)},{p(y)}) "
             rf"{{\strut $+${base - previous}}};")
    previous = base
# Legend of panel (b).
y_leg = top_b - 11.0
items = [(r"\fill[sound] (X,Y) circle (1.9pt);", "revision IDs"),
         (r"\filldraw[fill=white, draw=fails, line width=0.7pt] (X,Y) circle (1.9pt);", "content hashes"),
         (r"\fill[sound] (X,Y2) -- (X2,Y) -- (X,Y3) -- (X1,Y) -- cycle;", "one hash-only page")]
x = 40.0
for shape, name in items:
    shape = (shape.replace("(X,Y2)", f"({p(x)},{p(y_leg + 2.3)})").replace("(X2,Y)", f"({p(x + 2.3)},{p(y_leg)})")
             .replace("(X,Y3)", f"({p(x)},{p(y_leg - 2.3)})").replace("(X1,Y)", f"({p(x - 2.3)},{p(y_leg)})")
             .replace("(X,Y)", f"({p(x)},{p(y_leg)})"))
    emit(shape)
    emit(rf"\node[font=\figsmall, anchor=west, inner sep=0pt] at ({p(x + 4.0)},{p(y_leg)}) {{\strut {name}}};")
    x += {"revision IDs": 56.0, "content hashes": 64.0}.get(name, 0.0)
bottom = y_axis - 21.5

body = "\n".join(out)
tex = rf"""\documentclass{{standalone}}
\input{{figstyle.tex}}
\begin{{document}}
\begin{{tikzpicture}}[x=1pt, y=1pt]
\useasboundingbox (0,{p(bottom)}) rectangle ({p(WIDTH)},0);
{body}
\end{{tikzpicture}}
\end{{document}}
"""
(ROOT / "figure.tex").write_text(tex)


def build():
    env = dict(os.environ, OPENTYPEFONTS=str(ROOT / "fonts") + "//:", SOURCE_DATE_EPOCH="0", FORCE_SOURCE_DATE="1")
    with tempfile.TemporaryDirectory() as directory:
        for name in ("figure.tex", "figstyle.tex"):
            shutil.copy2(ROOT / name, directory)
        result = subprocess.run(["xelatex", "-interaction=nonstopmode", "-halt-on-error", "figure.tex"],
                                cwd=directory, env=env, capture_output=True, text=True)
        if result.returncode != 0:
            raise SystemExit(result.stdout[-3000:])
        shutil.copy2(Path(directory) / "figure.pdf", ROOT / "figure.pdf")
    subprocess.run(["pdftocairo", "-svg", str(ROOT / "figure.pdf"), str(ROOT / "figure.svg")], check=True)
    subprocess.run(["pdftoppm", "-r", "300", "-png", "-singlefile", str(ROOT / "figure.pdf"),
                    str(ROOT / "preview")], check=True)


def check():
    info = subprocess.run(["pdfinfo", str(ROOT / "figure.pdf")], capture_output=True, text=True).stdout
    size = next(l for l in info.splitlines() if l.startswith("Page size")).split()
    width, height = float(size[2]), float(size[4])          # PostScript points (bp)
    assert abs(width - WIDTH / 1.00375) < 0.05, ("page width differs from the column width", width)
    fonts = subprocess.run(["pdffonts", str(ROOT / "figure.pdf")], capture_output=True, text=True).stdout
    for line in fonts.splitlines()[2:]:
        assert " yes " in line and "Type 3" not in line, ("font not embedded or Type 3", line)
    with tempfile.TemporaryDirectory() as directory:
        stem = Path(directory) / "edge"
        subprocess.run(["pdftoppm", "-r", "600", "-gray", "-singlefile", str(ROOT / "figure.pdf"), str(stem)],
                       check=True)
        data = stem.with_suffix(".pgm").read_bytes()
    header, pixels = data.split(b"\n", 3)[:3], data.split(b"\n", 3)[3]
    w, h = map(int, header[1].split())
    border = [pixels[i] for i in range(w)] + [pixels[(h - 1) * w + i] for i in range(w)]
    border += [pixels[r * w] for r in range(h)] + [pixels[r * w + w - 1] for r in range(h)]
    assert min(border) > 250, "ink touches the page edge: something is clipped"
    words = subprocess.run(["pdftotext", "-bbox", str(ROOT / "figure.pdf"), "-"], capture_output=True,
                           text=True).stdout
    for m in re.finditer(r'xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)"', words):
        x0, y0, x1, y1 = map(float, m.groups())
        assert x0 >= 0.3 and y0 >= 0.3 and x1 <= width - 0.3 and y1 <= height - 0.3, ("text at the edge", m.group(0))
    styles = (ROOT / "figstyle.tex").read_text() + (ROOT / "figure.tex").read_text()
    assert not re.search(r"\\(tiny|scriptsize|footnotesize|small)\b", styles), "text below the figure sizes"
    sizes = {float(s) for s in re.findall(r"\\fontsize\{([\d.]+)\}", styles)}
    scripts = {float(a): (float(b), float(c)) for a, b, c in
               re.findall(r"\\DeclareMathSizes\{([\d.]+)\}\{[\d.]+\}\{([\d.]+)\}\{([\d.]+)\}", styles)}
    assert sizes and min(sizes) >= 7 and sizes <= scripts.keys(), ("text below 7 pt or without script sizes", sizes)
    assert min(min(v) for v in scripts.values()) >= 6, ("scripts below 6 pt", scripts)
    print(f"figure.pdf {width:.2f} x {height:.2f} pt; fonts embedded; text >= 7 pt, scripts >= 6 pt; "
          "no ink on the edge")


build()
check()
