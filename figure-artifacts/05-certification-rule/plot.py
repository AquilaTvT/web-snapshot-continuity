"""Draw figure.pdf, figure.svg and preview.png from plot-data.csv only.

The figure is written as TikZ (figure.tex) and typeset by XeLaTeX in the
paper's own faces, Linux Libertine O and Libertinus Math (shipped in fonts/),
at the exact column width of the acmart sigconf layout, so it is included
without scaling and its text matches the body. figstyle.tex holds the shared
colours and sizes. After building, the script checks that the page has the
column width, that every font is embedded, that text is at least 7 pt and sub-
and superscripts at least 6 pt, and that no ink touches the page edge (nothing
is clipped). Requires XeLaTeX with fontspec, unicode-math and
TikZ/PGF (TeX Live), and poppler's pdftocairo, pdftoppm, pdffonts and pdftotext.
"""
from pathlib import Path
import csv
import os
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent
WIDTH = 241.14749          # \columnwidth of acmart sigconf, in pt
rows = list(csv.DictReader((ROOT / "plot-data.csv").open(newline="")))


def get(panel, kind, resource=None):
    return [r for r in rows if r["panel"] == panel and r["kind"] == kind
            and (resource is None or r["resource"] == resource)]


def f(x):
    return f"{x:.2f}"


GREEK = {"α": r"$\alpha$", "β": r"$\beta$", "γ": r"$\gamma$", "δ": r"$\delta$"}
TARGET = {"admission": "eligible", "fee": "10"}
X0, X1 = 41.0, WIDTH - 1.5               # plotting range shared by both panels
out = []
emit = out.append


def bar(x1, x2, y, h, target, text=None, center=None):
    style = "fill=sound!13, draw=sound" if target else "fill=black!6, draw=black!32"
    emit(rf"\filldraw[{style}, line width=0.4pt] ({f(x1)},{f(y - h / 2)}) rectangle ({f(x2)},{f(y + h / 2)});")
    if text:
        cx = (x1 + x2) / 2 if center is None else center
        color = "ink" if target else "muted"
        emit(rf"\node[font=\figsmall, text={color}, inner sep=0pt] at ({f(cx)},{f(y)}) {{\strut {text}}};")


def write(x1, x2, y, h):
    emit(rf"\fill[pattern={{Lines[angle=45,distance=1.9pt,line width=0.3pt]}}, pattern color=black!38] "
         rf"({f(x1)},{f(y - h / 2)}) rectangle ({f(x2)},{f(y + h / 2)});")


def bracket(x1, x2, y, left=True, right=True, tick=1.7, width=0.5):
    emit(rf"\draw[ink, line width={width}pt] ({f(x1)},{f(y)}) -- ({f(x2)},{f(y)});")
    if left:
        emit(rf"\draw[ink, line width={width}pt] ({f(x1)},{f(y - tick)}) -- ({f(x1)},{f(y + tick)});")
    if right:
        emit(rf"\draw[ink, line width={width}pt] ({f(x2)},{f(y - tick)}) -- ({f(x2)},{f(y + tick)});")


def number(x, y, text):
    emit(rf"\node[font=\figsmall, text=muted, anchor=base, inner sep=0pt] at ({f(x)},{f(y)}) {{{text}}};")


def title(y, label, text):
    emit(rf"\node[font=\figtitle, anchor=base west, inner sep=0pt] at (0.8,{f(y)}) {{\textbf{{{label}}}\enspace {text}}};")


def rowlabel(y, text):
    emit(rf"\node[font=\figlabel, anchor=east, inner sep=0pt] at ({f(X0 - 4)},{f(y)}) {{\strut {text}}};")


# ---------------------------------------------------------------- panel (a)
t0, t1 = 27.9, 36.75
xa = lambda t: X0 + (t - t0) * (X1 - X0) / (t1 - t0)
claim = get("a", "claimed")[0]
c_lo, c_hi = float(claim["start"]), float(claim["end"])
c_mid = (c_lo + c_hi) / 2
y_title_a = -7.6                       # coordinates run downward from the top edge (y = 0)
lanes = {"admission": -25.5, "fee": -50.5}
BAR = 8.6
for r in get("a", "segment"):
    s, e, page = float(r["start"]), float(r["end"]), r["resource"]
    label = r["value"] + r"\,\," + GREEK[r["identifier"]]
    if e - s < 1.6:
        label = GREEK[r["identifier"]] if page == "admission" else r["value"] + r"\,\," + GREEK[r["identifier"]]
    center = None
    if page == "admission" and s < c_mid < e:   # keep the label clear of the claimed instant
        center = (xa(s) + xa(c_mid) - 4.0) / 2
    bar(xa(s), xa(e), lanes[page], BAR, r["value"] == TARGET[page], label, center)
for r in get("a", "mutation"):
    write(xa(float(r["start"])), xa(float(r["end"])), lanes[r["resource"]], BAR)
captures = sorted((float(r["start"]), float(r["end"]), r["resource"]) for r in get("a", "capture"))
spans = {}
for k, (s, e, page) in enumerate(captures, start=1):
    spans.setdefault(page, []).append((s, e))
    yb = lanes[page] + BAR / 2 + 4.2
    bracket(xa(s), xa(e), yb)
    shift = {2: -2.2, 3: 2.2}.get(k, 0.0)
    number((xa(s) + xa(e)) / 2 + shift, yb + 2.6, str(k))
first, last = spans["admission"][0], spans["admission"][-1]
yb_adm = lanes["admission"] + BAR / 2 + 4.2
emit(rf"\draw[fails, line width=0.6pt, dash pattern=on 2.4pt off 1.5pt] ({f(xa(first[1]))},{f(yb_adm)}) -- "
     rf"({f(xa(last[0]))},{f(yb_adm)});")
xc = xa(c_mid)
y_axis = lanes["fee"] - BAR / 2 - 5.0
emit(rf"\draw[fails, line width=0.5pt] ({f(xc)},{f(y_axis + 1.2)}) -- ({f(xc)},{f(yb_adm - 2.2)});")
ya = lanes["admission"]
emit(rf"\draw[fails, line width=0.75pt] ({f(xc - 2.1)},{f(ya - 2.1)}) -- ({f(xc + 2.1)},{f(ya + 2.1)}) "
     rf"({f(xc - 2.1)},{f(ya + 2.1)}) -- ({f(xc + 2.1)},{f(ya - 2.1)});")
for page, y in lanes.items():
    rowlabel(y, page)
# Time axis in milliseconds and the magnified strip.
emit(rf"\draw[rule, line width=0.4pt] ({f(X0)},{f(y_axis)}) -- ({f(X1)},{f(y_axis)});")
for t in (28, 30, 32, 34, 36):
    emit(rf"\draw[rule, line width=0.4pt] ({f(xa(t))},{f(y_axis)}) -- ({f(xa(t))},{f(y_axis - 1.8)});")
    text = f"{t}\\,ms" if t == 36 else str(t)
    emit(rf"\node[font=\figsmall, anchor=base, inner sep=0pt] at ({f(xa(t))},{f(y_axis - 8.6)}) {{{text}}};")
ZOOM = 60                               # the strip stretches the time axis exactly this much
zlo = c_mid - (t1 - t0) / ZOOM / 2
zhi = c_mid + (t1 - t0) / ZOOM / 2
assert abs((t1 - t0) / (zhi - zlo) - ZOOM) < 1e-9
assert zlo < c_lo < c_hi < zhi                  # the bridge lies inside the magnified window
emit(rf"\fill[muted] ({f(xa(zlo))},{f(y_axis - 0.9)}) rectangle ({f(xa(zhi))},{f(y_axis + 0.9)});")
y_zoom = y_axis - 27.5
z_top = y_zoom + BAR / 2 + 11.0
emit(rf"\draw[black!22, line width=0.35pt] ({f(xa(zlo))},{f(y_axis - 0.9)}) -- ({f(X0)},{f(z_top)}) "
     rf"({f(xa(zhi))},{f(y_axis - 0.9)}) -- ({f(X1)},{f(z_top)});")
xz = lambda t: X0 + (t - zlo) * (X1 - X0) / (zhi - zlo)
for r in get("a", "segment", "fee"):
    s, e = max(float(r["start"]), zlo), min(float(r["end"]), zhi)
    if s < e:
        bar(xz(s), xz(e), y_zoom, BAR, r["value"] == TARGET["fee"])
yb_z = y_zoom + BAR / 2 + 4.2
for k, (s, e) in zip((2, 3), spans["fee"]):
    a, b = max(s, zlo), min(e, zhi)
    bracket(xz(a), xz(b), yb_z, left=a == s, right=b == e)
    number((xz(a) + xz(b)) / 2, yb_z + 2.6, str(k))
emit(rf"\draw[fails, line width=1.6pt] ({f(xz(c_lo))},{f(yb_z)}) -- ({f(xz(c_hi))},{f(yb_z)});")
emit(rf"\draw[fails, line width=0.5pt] ({f(xz(c_mid))},{f(y_zoom - BAR / 2 - 1.5)}) -- ({f(xz(c_mid))},{f(yb_z - 1.0)});")
emit(rf"\node[font=\figsmall, text=fails, anchor=base, inner sep=0pt] at ({f(xz(c_mid))},{f(yb_z + 2.6)}) "
     rf"{{18\,µs}};")
rowlabel(y_zoom, rf"fee $\times${ZOOM}")
y_zaxis = y_zoom - BAR / 2 - 2.0
emit(rf"\draw[rule, line width=0.4pt] ({f(X0)},{f(y_zaxis)}) -- ({f(X1)},{f(y_zaxis)});")
for t, text in ((33.16, "33.16"), (33.20, "33.20"), (33.24, "33.24\\,ms")):
    emit(rf"\draw[rule, line width=0.4pt] ({f(xz(t))},{f(y_zaxis)}) -- ({f(xz(t))},{f(y_zaxis - 1.8)});")
    emit(rf"\node[font=\figsmall, anchor=base, inner sep=0pt] at ({f(xz(t))},{f(y_zaxis - 8.6)}) {{{text}}};")
title(y_title_a, "(a)", "MinIO: same ID, broken continuity")

# ---------------------------------------------------------------- panel (b)
y_title_b = y_zaxis - 19.5
xb = lambda t: X0 + 3.0 + (t - 0.0) * (X1 - X0 - 6.0) / 10.0
lane_b = {"R1": y_title_b - 12.5, "R2": y_title_b - 24.0, "R3": y_title_b - 35.5}
common = get("b", "revisited_common")[0]
lo, hi = float(common["start"]), float(common["end"])
emit(rf"\fill[sound!9] ({f(xb(lo))},{f(lane_b['R2'] - 5.0)}) rectangle ({f(xb(hi))},{f(lane_b['R1'] + 5.0)});")
for r in get("b", "presence"):
    y = lane_b[r["resource"]]
    emit(rf"\draw[sound, line width=2.0pt] ({f(xb(float(r['start'])))},{f(y)}) -- ({f(xb(float(r['end'])))},{f(y)});")
for k, r in enumerate(get("b", "capture"), start=1):
    s, e, res = float(r["start"]), float(r["end"]), r["resource"]
    y = lane_b[res]
    bracket(xb(s), xb(e), y, tick=2.2)
    if res == "R3":
        number(xb(e) + 3.2, y + 2.4, str(k))
    else:
        number((xb(s) + xb(e)) / 2, y + 3.4, str(k))
star = float(get("b", "schematic_read")[0]["start"])
y3 = lane_b["R3"]
emit(rf"\draw[ink, line width=0.45pt, dash pattern=on 1.2pt off 1.2pt] ({f(xb(star))},{f(y3 + 2.4)}) -- "
     rf"({f(xb(star))},{f(lane_b['R1'] + 5.0)});")
emit(rf"\filldraw[fill=white, draw=ink, line width=0.6pt] ({f(xb(star))},{f(y3)}) circle (1.9pt);")
emit(rf"\node[font=\figlabel, anchor=north, inner sep=0pt] at ({f(xb(star))},{f(y3 - 3.0)}) {{$t^{{*}}$}};")
for res, y in lane_b.items():
    rowlabel(y, f"$R_{res[1]}$")
title(y_title_b, "(b)", "Sound outer reads cover the center read")
bottom = y3 - 11.5                      # below the t* label
H = -bottom

body = "\n".join(out)
tex = rf"""\documentclass{{standalone}}
\input{{figstyle.tex}}
\begin{{document}}
\begin{{tikzpicture}}[x=1pt, y=1pt]
\useasboundingbox (0,{f(bottom)}) rectangle ({f(WIDTH)},0);
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
        data = (stem.with_suffix(".pgm")).read_bytes()
    header, pixels = data.split(b"\n", 3)[:3], data.split(b"\n", 3)[3]
    w, h = map(int, header[1].split())
    border = [pixels[i] for i in range(w)] + [pixels[(h - 1) * w + i] for i in range(w)]
    border += [pixels[r * w] for r in range(h)] + [pixels[r * w + w - 1] for r in range(h)]
    assert min(border) > 250, "ink touches the page edge: something is clipped"
    words = subprocess.run(["pdftotext", "-bbox", str(ROOT / "figure.pdf"), "-"], capture_output=True,
                           text=True).stdout
    import re
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
