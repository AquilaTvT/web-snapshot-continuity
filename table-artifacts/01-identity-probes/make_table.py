"""Write table.tex from matrix.csv, caption.txt and legend.txt, checking the caption against summary.json."""
from pathlib import Path
import csv

ROOT = Path(__file__).resolve().parent
NAMES = {"minio": ("MinIO", "2025-09-07"), "ceph": ("Ceph RGW", "19.2.0"), "seaweedfs": ("SeaweedFS", "3.97"),
         "versitygw": ("Versity GW", "1.10.0"), "rustfs": ("RustFS", "1.0.4"),
         "cloudserver": ("CloudServer", "9.0.27"), "localstack": ("LocalStack", "4.9.2"),
         "moto": ("moto", "5.1.15"), "fake-gcs-server": ("GCS emulator", "1.56.1")}
COLUMNS = ("delete_current", "delete_marker", "object_lock_marker", "suspended_null", "copy_restore", "reupload")
SYMBOL = {"returned": r"{\large$\bullet$}", "identifier unchanged": r"{\large$\bullet$}",
          "no identifier": r"{\large$\bullet$}", "fresh": r"{\large$\circ$}", "absent": r"{\large$\circ$}",
          "not restored": r"$\times$", "unsupported": r"$\times$", "not applicable": "--"}

rows = list(csv.DictReader((ROOT / "matrix.csv").open(newline="")))
cells = {(r["server"], r["probe"]): r for r in rows}
for (server, probe), r in cells.items():
    assert r["outcome"] in SYMBOL, (server, probe, r["outcome"])
lines = []
for server, (name, version) in NAMES.items():
    if server == "fake-gcs-server":
        lines.append(r"\midrule")
    symbols = [SYMBOL[cells[server, probe]["outcome"]] for probe in COLUMNS]
    lines.append(f"{name} {version} & " + " & ".join(symbols) + r" \\")
caption = (ROOT / "caption.txt").read_text().strip()
import json
summary = json.loads((ROOT / "summary.json").read_text())["findings"]
assert f"{summary['requests_total']} recorded" in caption and summary["s3_implementations"] == 8, "caption out of date"
legend = (ROOT / "legend.txt").read_text().strip()
table = "\n".join([
    r"\begin{table}[t]",
    r"\caption{" + caption + "}",
    r"\label{tab:probes}",
    r"\small",
    r"\setlength{\tabcolsep}{3.6pt}",
    r"\begin{tabular}{@{}lcccccc@{}}",
    r"\toprule",
    r" & \multicolumn{3}{c}{Undo by deletion} & Rewrite & \multicolumn{2}{c}{Restore bytes}\\",
    r"\cmidrule(lr){2-4}\cmidrule(lr){5-5}\cmidrule(l){6-7}",
    r"Server & Delete & Marker & Lock & Susp. & Copy & Upload\\",
    r"\midrule",
    *lines,
    r"\bottomrule",
    r"\end{tabular}",
    r"",
    r"\smallskip\parbox{\columnwidth}{\footnotesize " + legend + "}",
    r"\end{table}",
    ""])
(ROOT / "table.tex").write_text(table)
print(table)
