"""Render only data derived from the frozen native MinIO trace beside this file."""
from pathlib import Path
import csv
import hashlib
import json
import os
import tempfile

cache = Path(tempfile.gettempdir()) / "acm-web-figure-cache"
cache.mkdir(exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(cache / "matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(cache))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

ROOT = Path(__file__).resolve().parent
plt.rcParams.update({"font.family":"DejaVu Sans", "font.size":8.3,
    "pdf.fonttype":42, "ps.fonttype":42, "svg.hashsalt":"web-versioned-heads-v1",
    "savefig.facecolor":"white"})
INK = "#26323a"


def main():
    required = ("trace.json", "plot-data.csv", "version-id-map.csv", "derivation.json")
    missing = [name for name in required if not (ROOT / name).is_file()]
    if missing:
        raise SystemExit("Missing real derived inputs: " + ", ".join(missing) + "; run derive.py after the native trace exists.")
    meta = json.loads((ROOT / "figure.json").read_text())
    actual_hash = hashlib.sha256((ROOT / "trace.json").read_bytes()).hexdigest()
    assert actual_hash == meta["data_sources"]["trace.json"]
    assert actual_hash == json.loads((ROOT / "derivation.json").read_text())["trace_sha256"]
    with (ROOT / "plot-data.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    cases = [("delete_current", "Delete current"), ("copy_restore", "Copy restore"),
             ("reupload_restore", "Reupload"), ("delete_marker", "Delete marker")]
    assert len(rows) == 12
    fig = plt.figure(figsize=(3.35, 2.8))
    ax = fig.add_axes((0,0,1,1)); ax.set(xlim=(0,1),ylim=(0,1)); ax.axis("off")
    ax.text(.045,.95,"Native MinIO current-key reads",fontsize=8.8,fontweight="bold",color=INK)
    centers = (.43, .65, .87)
    for x, label in zip(centers,("Initial", "Changed", "Restored")):
        ax.text(x,.855,label,ha="center",va="center",color=INK)
    for order,(name,label) in enumerate(cases):
        y=.735-.17*order
        ax.text(.045,y,label,va="center",fontsize=8.3,color=INK)
        selected=sorted((r for r in rows if r["case"]==name),key=lambda r:int(r["step"]))
        assert [r["step"] for r in selected]==["0","1","2"]
        for x,row in zip(centers,selected):
            absent = row["body_symbol"] == "ABSENT"
            assert (row["status"] == "404") == absent
            assert (row["certifiable_endpoint"] == "True") != absent
            color = "#edf3f5" if row["body_symbol"] == "A" else ("#f7eee5" if not absent else "#f0f0f0")
            ax.add_patch(FancyBboxPatch((x-.078,y-.052),.156,.104,
                boxstyle="round,pad=0.002,rounding_size=0.012",facecolor=color,
                edgecolor="#8b989f",linewidth=.65))
            value = "absent" if absent else row["body_symbol"]+"/"+row["version_alias"]
            ax.text(x,y+.013 if absent else y,value,ha="center",va="center",fontsize=8.5,color=INK)
            if absent:
                ax.text(x,y-.025,"404",ha="center",va="center",fontsize=8.0,color=INK)
        for left,right in zip(centers,centers[1:]):
            ax.annotate("",xy=(right-.083,y),xytext=(left+.083,y),
                arrowprops={"arrowstyle":"->","lw":.8,"color":INK,"shrinkA":0,"shrinkB":0})
    ax.text(.5,.105,"α, β, γ are row-local version-ID aliases.",ha="center",fontsize=8.0,color=INK)
    ax.text(.5,.047,"404 is internal absence, not an endpoint.",ha="center",fontsize=8.0,color=INK)
    fig.savefig(ROOT / "figure.pdf",metadata={"Creator":"Matplotlib","CreationDate":None,"ModDate":None})
    fig.savefig(ROOT / "figure.svg",metadata={"Creator":"Matplotlib","Date":None})
    fig.savefig(ROOT / "preview.png",dpi=220)
    plt.close(fig)
    (ROOT / "MANIFEST.sha256").write_text("".join(hashlib.sha256(p.read_bytes()).hexdigest()+"  "+p.name+"\n"
        for p in sorted(ROOT.iterdir()) if p.is_file() and p.name != "MANIFEST.sha256"))


if __name__ == "__main__":
    main()
