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
plt.rcParams.update({"font.family":"DejaVu Sans","font.size":8.3,
 "axes.labelsize":8.3,"axes.titlesize":8.5,"xtick.labelsize":8.3,"ytick.labelsize":8.3,
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


rows=read('plot-data.csv');observations=read('observations.csv')
fig=plt.figure(figsize=(3.35,3.1))
# Physical size is the final single-column size: no sub-8-pt labels.
for x,color,label in [(.07,BLUE,'Target'),(.36,GRAY,'Other')]:
 fig.add_artist(Rectangle((x,.946),.045,.021,transform=fig.transFigure,
                          facecolor=color,edgecolor='none'))
 fig.text(x+.06,.956,label,va='center',color=INK)
fig.add_artist(plt.Line2D([.685],[.956],transform=fig.transFigure,
                         marker='o',mfc='white',mec=INK,ms=4.5,mew=1,linestyle='none'))
fig.text(.715,.956,'Capture',va='center',color=INK)
fig.text(.5,.894,'Same captures and endpoint hashes',ha='center',color=INK)
positions=[(.14,.635,.815,.17),(.14,.265,.815,.17)]
for panel,(world,title) in enumerate([('unchanged','(a) Shared state exists'),
                                      ('returned','(b) No shared state')]):
 ax=fig.add_axes(positions[panel])
 fig.text(.07,.844-.37*panel,title,fontsize=8.5,fontweight='bold',color=INK)
 for row in rows:
  if row['world']!=world:continue
  y=1 if row['resource']=='a' else 0;start=float(row['start']);end=float(row['end'])
  ax.add_patch(Rectangle((start,y-.16),end-start,.32,facecolor=BLUE if row['target']=='1' else GRAY,edgecolor='white',linewidth=.5))
 for obs in observations:
  ax.plot(float(obs['time']),1 if obs['resource']=='a' else 0,'o',mfc='white',mec=INK,ms=4.5,mew=1,zorder=5,clip_on=False)
 ax.set(xlim=(0,4),ylim=(-.45,1.45),xticks=[0,1,2,3,4],yticks=[0,1],yticklabels=['B','A'])
 ax.spines[['top','right','left']].set_visible(False)
 ax.tick_params(axis='y',length=0,pad=7);ax.tick_params(axis='x',length=3,pad=2)
 if panel==1:ax.set_xlabel('Logical time',labelpad=3)
 # Derive the opposite coexistence answers and A's change count from the CSV.
 target={resource:[(float(r['start']),float(r['end'])) for r in rows
                   if r['world']==world and r['resource']==resource and r['target']=='1']
         for resource in ('a','b')}
 overlap=[(max(a,c),min(b,d)) for a,b in target['a'] for c,d in target['b']
          if max(a,c)<min(b,d)]
 assert overlap==([(0.,4.)] if world=='unchanged' else [])
 spans=sorted((float(r['start']),float(r['end']),r['target']) for r in rows
              if r['world']==world and r['resource']=='a')
 times=sorted(float(o['time']) for o in observations if o['resource']=='a')
 changes=sum(times[0]<right[0]<=times[-1] and left[2]!=right[2]
             for left,right in zip(spans,spans[1:]))
 assert changes==(0 if world=='unchanged' else 2)
 answer='[0, 4)' if overlap else 'empty'
 y=.55 if panel==0 else .125
 fig.text(.07,y,f'Overlap: {answer}',color=BLUE if panel==0 else ORANGE)
 fig.text(.55,y,f'A epoch: 0 → {changes}',color=INK)
fig.text(.5,.038,'Epochs need non-reuse and atomic reads.',ha='center',fontsize=8.0,color=INK)
save(fig)
