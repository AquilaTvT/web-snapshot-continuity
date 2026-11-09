"""Recompute plotted values from the source inputs in this directory."""
from pathlib import Path
import csv,json,hashlib,re
from fractions import Fraction
ROOT=Path(__file__).resolve().parent
def read(name):
 with (ROOT/name).open(newline="") as stream:return list(csv.DictReader(stream))
def write(name,rows):
 with (ROOT/name).open("w",newline="") as stream:
  writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
def population():
 import xml.etree.ElementTree as ET
 raw=ROOT/"rfc-index.xml"
 assert hashlib.sha256(raw.read_bytes()).hexdigest()=="dd963eda48804cfe9f2b225016c01e8ed9a7b60699d47f4c24fe0b8f4f3fe04c"
 ns={"r":"https://www.rfc-editor.org/rfc-index"};rows=[]
 for entry in ET.parse(raw).findall("r:rfc-entry",ns):
  title=entry.findtext("r:title",namespaces=ns)
  if "http" not in re.findall(r"[a-z0-9]+",title.lower()):continue
  obsolete=[x.text for x in entry.findall("r:obsoleted-by/r:doc-id",ns)]
  rows.append(dict(id=entry.findtext("r:doc-id",namespaces=ns),title=title,status=entry.findtext("r:current-status",namespaces=ns),obsoleted_by=";".join(obsolete),positive=int(not obsolete)))
 rows.sort(key=lambda x:int(x["id"][3:]));write("population.csv",rows);return rows

rows=[]
for case in ["express-weak","express-strong","python-fresh","python-restored","apache-fresh","apache-restored"]:
 source=json.loads((ROOT/(case+".json")).read_text());obs=source["observations"];a0,b1,b2,a3,conditional=obs
 assert all(x["status"]==200 for x in obs[:4])
 for observation in obs:
  assert hashlib.sha256(observation["body"].encode()).hexdigest()==observation["body_sha256"]
 assert a0["body"]==a3["body"]==source["target"]["a"] and b1["body"]==b2["body"]==source["target"]["b"]
 validator=source["validator"];same=a0[validator]==a3[validator]
 ever=any(step["state"]==source["target"] for step in source["mutation_trace"])
 assert not ever
 row=dict(case=case,validator=validator,endpoint_validator_equal=same,conditional_status=conditional["status"],target_bundle_ever_present=ever,consumer_endpoint_rule_would_accept=same and b1[validator]==b2[validator])
 assert all(source[key]==value for key,value in row.items());rows.append(row)
write("plot-data.csv",rows)
