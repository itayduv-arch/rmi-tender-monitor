"""Read-only test of the official document API with all required document fields."""
import hashlib
import json
from pathlib import Path
import requests

url="https://apps.land.gov.il/MichrazimSite/api/MichrazDetailsApi/GetFileContent"
document={
    "DocName":"פרסום דחיית מועדים.pdf", "FileType":"application/pdf",
    "MahutMismachID":0,"MichrazID":20250470,
    "PirsumType":3,"RowID":135312,"Size":None,
    "Teur":"פרסום דחיית מועדים","UpdateDate":"2026-10-12T00:00:00+03:00","Url":None
}
options=[
    ("POST document object", "POST", {"json":document}),
    ("GET complete link", "GET", {"params":{
        "michrazId":20250470,"rowId":135312,"size":"null","typePirsum":3,
        "fileName":document["DocName"],"teur":document["Teur"],"fileType":"application/pdf"}}),
    ("GET IDs only", "GET", {"params":{"michrazID":20250470,"rowID":135312}}),
]
S=requests.Session()
S.headers.update({"User-Agent":"Mozilla/5.0 (compatible; RMI-monitor/1.0)",
                 "Origin":"https://apps.land.gov.il","Referer":"https://apps.land.gov.il/MichrazimSite/"})
results=[]
for label,method,kwargs in options:
    try:
        r=S.request(method,url,timeout=25,allow_redirects=False,**kwargs)
        ispdf=r.ok and r.content[:4]==b"%PDF"
        results.append({"test":label,"code":r.status_code,"length":len(r.content),
                        "content_type":r.headers.get("content-type"),
                        "is_pdf":ispdf,
                        "sha256":hashlib.sha256(r.content).hexdigest() if ispdf else None,
                        "error_preview":None if ispdf else r.text[:140]})
        if ispdf:break
    except Exception as ex:
        results.append({"test":label,"error":f"{type(ex).__name__}: {str(ex)[:140]}"})
Path("reports").mkdir(exist_ok=True)
Path("reports/document-api-probe.json").write_text(json.dumps({"source":url,"results":results},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print("Official PDF document retrieval", "SUCCESS" if any(x.get("is_pdf") for x in results) else "NOT_VERIFIED", "attempts", len(results))
