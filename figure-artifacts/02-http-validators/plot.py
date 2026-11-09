from pathlib import Path
import csv,json,hashlib,os,tempfile
cache=Path(tempfile.gettempdir())/"acm-web-figure-cache"
cache.mkdir(exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR",str(cache/"matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME",str(cache))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
ROOT=Path(__file__).resolve().parent
plt.rcParams.update({"font.family":"DejaVu Sans","font.size":8,
 "axes.labelsize":8,"axes.titlesize":8,"xtick.labelsize":7,"ytick.labelsize":7,
 "axes.linewidth":0.6,"lines.linewidth":1.2,"pdf.fonttype":42,"ps.fonttype":42,
 "svg.hashsalt":"web-history-figures-v2","savefig.facecolor":"white"})
BLUE="#25627a";ORANGE="#c06a2b";GRAY="#d9dfe2";INK="#26323a"
def read(name):
 with (ROOT/name).open(newline="") as stream:return list(csv.DictReader(stream))
def save(fig):
 fig.savefig(ROOT/"figure.pdf",metadata={"Creator":"Matplotlib","CreationDate":None,"ModDate":None})
 fig.savefig(ROOT/"figure.svg",metadata={"Creator":"Matplotlib","Date":None})
 fig.savefig(ROOT/"preview.png",dpi=220)
 plt.close(fig)


rows=read('plot-data.csv')
names={'express-weak':'Express / weak ETag','express-strong':'Express / strong ETag','python-fresh':'Python / new mtime','python-restored':'Python / restored mtime','apache-fresh':'Apache / new mtime','apache-restored':'Apache / restored mtime'}
fig,ax=plt.subplots(figsize=(7,2.1));fig.subplots_adjust(left=.02,right=.98,bottom=.04,top=.82)
ax.set_xlim(0,1);ax.set_ylim(-.65,len(rows)-.25);ax.axis('off');xs=[.015,.47,.70,.90]
for x,title in zip(xs,['Controlled configuration','Same validator','Conditional status','Target ever coexisted']):
 ax.text(x,len(rows)-.05,title,ha='left' if x==xs[0] else 'center',va='bottom',fontsize=7.5)
for i,row in enumerate(rows):
 y=len(rows)-1-i
 if i%2==0:ax.add_patch(Rectangle((0,y-.42),1,.84,facecolor='#f1f4f5',edgecolor='none'))
 ax.text(xs[0],y,names[row['case']],va='center',fontsize=8)
 values=[('yes' if row['endpoint_validator_equal']=='True' else 'no'),row['conditional_status'],('yes' if row['target_bundle_ever_present']=='True' else 'no')]
 for x,value in zip(xs[1:],values):ax.text(x,y,value,ha='center',va='center',fontsize=8,color=BLUE if value in ['yes','304'] else INK)
ax.axhline(len(rows)-.50,color=INK,lw=.65)
save(fig)
