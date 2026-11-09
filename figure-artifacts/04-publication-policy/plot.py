"""Plot exact current-key observations; no invented measurements or timing axes."""
from pathlib import Path
import csv
import hashlib
import json
import os
import tempfile

cache = Path(tempfile.gettempdir())/"acm-web-figure-cache"
cache.mkdir(exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR",str(cache/"matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME",str(cache))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent
plt.rcParams.update({"font.family":"DejaVu Sans","font.size":8,
    "pdf.fonttype":42,"ps.fonttype":42,"svg.hashsalt":"publication-policy-v1"})


def main():
    meta=json.loads((ROOT/"figure.json").read_text())
    digest=hashlib.sha256((ROOT/"trace.json").read_bytes()).hexdigest()
    assert digest==meta["data_sources"]["trace.json"]
    assert digest==json.loads((ROOT/"derivation.json").read_text())["trace_sha256"]
    with (ROOT/"plot-data.csv").open() as stream:
        rows=list(csv.DictReader(stream))
    cases=[("owner_deny","Owner + bucket deny"), ("object_lock","Owner + Object Lock"),
           ("restricted_delete","Publisher: remove B"), ("restricted_copy","Publisher: copy A")]
    assert len(rows)==12
    fig=plt.figure(figsize=(3.35,2.8))
    ax=fig.add_axes((0,0,1,1));ax.set(xlim=(0,1),ylim=(0,1));ax.axis("off")
    ink="#23313b"
    ax.text(.025,.952,"Current publication under different permissions",fontsize=8.4,fontweight="bold",color=ink)
    centers=(.535,.72,.905)
    for x,label in zip(centers,("Initial","Changed","Result")):
        ax.text(x,.858,label,ha="center",fontsize=8,color=ink)
    for order,(case,title) in enumerate(cases):
        y=.745-.17*order
        if order==2:
            ax.plot([.025,.975],[y+.083,y+.083],color="#aeb7bd",lw=.6)
        ax.text(.025,y,title,va="center",fontsize=8,color=ink)
        selected=sorted([r for r in rows if r["case"]==case],key=lambda r:int(r["step"]))
        for x,r in zip(centers,selected):
            absent=r["body_symbol"]=="ABSENT"
            color={"A":"#e5eef2","B":"#f6e9d9","ABSENT":"#eeeeee"}[r["body_symbol"]]
            ax.add_patch(plt.Rectangle((x-.06,y-.046),.12,.092,facecolor=color,edgecolor="#9ca8b0",lw=.6))
            value="404" if absent else r["body_symbol"]+"/"+r["version_alias"]
            ax.text(x,y,value,ha="center",va="center",fontsize=8.5,color=ink)
        for left,right in zip(centers,centers[1:]):
            ax.annotate("",xy=(right-.067,y),xytext=(left+.067,y),arrowprops={"arrowstyle":"->","lw":.65,"color":ink,"shrinkA":0,"shrinkB":0})
    ax.text(.5,.112,"Body / version ID; aliases are local to each row.",ha="center",fontsize=8,color=ink)
    ax.text(.5,.052,"Rejected deletion keeps B; copying A creates γ.",ha="center",fontsize=8,color=ink)
    for extension in ("pdf","svg"):
        metadata={"Creator":"Matplotlib","CreationDate":None,"ModDate":None} if extension=="pdf" else {"Creator":"Matplotlib","Date":None}
        fig.savefig(ROOT/("figure."+extension),metadata=metadata)
    fig.savefig(ROOT/"preview.png",dpi=220)
    plt.close(fig)
    (ROOT/"MANIFEST.sha256").write_text("".join(hashlib.sha256(p.read_bytes()).hexdigest()+"  "+p.name+"\n" for p in sorted(ROOT.iterdir()) if p.is_file() and p.name!="MANIFEST.sha256"))


if __name__ == "__main__":
    main()
