"""Optional diagnostic; never infer contents from metadata or error response."""
import json
from pathlib import Path
import requests

url = "https://apps.land.gov.il/MichrazimSite/api/MichrazDetailsApi/GetFileContent"
options = [
    ("GET", {"rowID": 135312}),
    ("GET", {"RowID": 135312}),
    ("GET", {"id": 135312}),
    ("GET", {"fileId": 135312}),
    ("GET", {"rowId": 135312, "michrazID": 20250470}),
]
session = requests.Session()
session.headers.update({
    "User-Agent": "RMI-Tender-Monitor/1.0", "Referer":"https://apps.land.gov.il/MichrazimSite/",
    "Origin":"https://apps.land.gov.il"
})
results = []
for verb, args in options:
    try:
        resp=session.get(url,params=args,timeout=18,allow_redirects=False)
        ok=resp.ok and resp.content.startswith(b"%PDF")
        results.append({"method":verb,"params":list(args),"http_code":resp.status_code,
                        "content_type":resp.headers.get("content-type"),
                        "length":len(resp.content),"is_pdf":ok,
                        "error_preview": None if ok else resp.text[:150]})
        if ok: break
    except Exception as exc:
        results.append({"method":verb,"params":list(args),"error":f"{type(exc).__name__}: {str(exc)[:130]}"})
Path("reports").mkdir(exist_ok=True)
Path("reports/document-api-probe.json").write_text(json.dumps({"source":url,"results":results},indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
print("Official document API PDF retrieval", "SUCCESS" if any(x.get("is_pdf") for x in results) else "NOT_VERIFIED", "attempts:",len(results))
