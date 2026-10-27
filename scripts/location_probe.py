"""Read-only diagnostic: understand how official RMI categorizes Kfar Azar / Ramat Gan."""
import json
from collections import Counter
from pathlib import Path
import requests
from monitor import API, BASE, ROOT, official_request, parse_api, flatten_search

s=requests.Session()
s.headers.update({"User-Agent":"RMI-Tender-Monitor/1.1","Referer":BASE,"Origin":ROOT})
data=flatten_search(parse_api(official_request(s,"POST",API+"SearchApi/Search",json={"ActiveQuickSearch":False,"ActiveMichraz":False})))
rg=[v for v in data if str(v.get("KodYeshuv"))=="8600"]
def normalized(v):
 return str(v or "").lower().replace('"',"").replace("״","").replace("׳","").replace(" ","").replace("-","").replace("'","")
a=["כפראזר","גניאזר","גניאזר","kfarazar"]
def matches(v):
 return any(k in normalized(v) for k in a)
place_keys= ("Shchuna","Yishuv","Yeshuv","ShmYeshuv","MichrazDescription","Teur","ShmMichraz","Street","ShemShchuna")
related=[row for row in data if any(matches(row.get(k)) for k in place_keys)]
res={
 "official_host":"apps.land.gov.il",
 "search_rows":len(data),
 "ramat_gan_rows":len(rg),
 "ramat_gan_residential_rows":len([v for v in rg if v.get("KodYeudMichraz") in (1,2)]),
 "ramat_gan_neighborhoods":Counter(str(v.get("Shchuna") or "").strip() for v in rg).most_common(80),
 "related_name_rows":[{k:v.get(k) for k in ("MichrazID","MichrazName","Shchuna","KodYeshuv","KodYeudMichraz","PirsumDate","SgiraDate")} for v in related[:100]],
 "ramat_gan_recent_residential":[{k:v.get(k) for k in ("MichrazID","MichrazName","Shchuna","KodYeshuv","KodYeudMichraz","PirsumDate","SgiraDate")} for v in sorted(rg,key=lambda v:str(v.get("PirsumDate") or ""),reverse=True) if v.get("KodYeudMichraz") in (1,2)][:70],
 "sample_row_keys":list(rg[0]) if rg else [],
}
Path("reports").mkdir(exist_ok=True)
Path("reports/location-diagnostic.json").write_text(json.dumps(res,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print("Ramat Gan",len(rg),"related name hits",len(related),"official search",len(data))
