"""Recompute plotted values from the source inputs in this directory."""
from pathlib import Path
import csv,json
ROOT=Path(__file__).resolve().parent
def read(name):
 with (ROOT/name).open(newline="") as stream:return list(csv.DictReader(stream))
def write(name,rows):
 with (ROOT/name).open("w",newline="") as stream:
  writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
design=json.loads((ROOT/"construction.json").read_text());rows=[]
for world,resources in design["worlds"].items():
 for resource,segments in resources.items():
  for start,end,target in segments:rows.append(dict(world=world,resource=resource,start=start,end=end,target=target))
write("plot-data.csv",rows);write("observations.csv",design["observations"])
for world,resources in design["worlds"].items():
 for observation in design["observations"]:
  hits=[s for s in resources[observation["resource"]] if s[0]<=observation["time"]<s[1]]
  assert len(hits)==1 and hits[0][2]==observation["target"]
