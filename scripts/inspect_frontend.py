"""Diagnostic for official RMI frontend routes; stores short excerpts, not the full site."""
from pathlib import Path
from urllib.parse import urljoin, urlparse
import json, re, requests
BASE="https://apps.land.gov.il/MichrazimSite/"
S=requests.Session()
S.headers.update({"User-Agent":"Mozilla/5.0 (compatible; RMI-monitor/1.0)","Referer":BASE})
out={"homepage":"","scripts":[],"matches":[],"errors":[]}
try:
 r=S.get(BASE,timeout=25);r.raise_for_status();out["homepage"]=r.url
 body=r.text
 scripts=re.findall(r'<script[^>]+src=["\']([^"\']+)',body,re.I)
 out["scripts"]=scripts[:50]
 for script in scripts[:30]:
  u=urljoin(BASE,script)
  if urlparse(u).hostname!="apps.land.gov.il":
   continue
  try:
   resp=S.get(u,timeout=25)
   if not resp.ok:continue
   text=resp.text
   for term in ["GetFileContent","MichrazDetailsApi","RowID","GetFile"]:
    idx=text.find(term)
    if idx>=0:
     out["matches"].append({"asset":script,"term":term,"context":text[max(0,idx-260):idx+400]})
  except Exception as e:out["errors"].append({"asset":script,"exception":str(e)[:250]})
except Exception as e:out["errors"].append(str(e)[:200])
Path("reports").mkdir(exist_ok=True)
Path("reports/frontend-inspection.json").write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n")
print("Official site scripts:",len(out["scripts"]),"matches:",len(out["matches"]),"errors:",len(out["errors"]))
