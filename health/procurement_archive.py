#!/usr/bin/env python3
"""Read-only official monthly procurement ZIP diagnostic (NOT comprehensive MOH allocation coverage)."""
import csv, hashlib, html, io, json, re, zipfile
from xml.etree import ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
import requests

BASE=Path(__file__).resolve().parent/"state"
BASE.mkdir(exist_ok=True)
INDEX="https://mr.gov.il/ilgstorefront/he/news/details/230920201036"
HEADERS={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36","Accept-Language":"he-IL,he;q=0.9"}
KEYS=["כירורגיה בינונית","מרפאות כירורגיות","מרפאה כירורגית","הקצאת עמדות ניתוח","אישור הקמה","ועדת הקצאה","הרדמה כללית"]
out={"checked_at_utc":datetime.now(timezone.utc).isoformat(),"index_url":INDEX,
     "procurement_data_current":False,"allocation_publications_full_coverage":False,
     "retrieval_verified":False,"rows_parsed":0,"candidate_rows":[],"files":[],"limitations":[
        "Monthly procurement listings do not necessarily contain allocation committee publications on gov.il.",
        "Text matches are leads only: an original signed tender PDF and eligibility/location/deadline must be verified independently."]}
s=requests.Session();s.headers.update(HEADERS)
try:
    r=s.get(INDEX,timeout=40)
    out["index_status"]=r.status_code
    r.raise_for_status()
    links=re.findall(r"""(?:href|data-href)\s*=\s*["']([^"']+)["']""",r.text,flags=re.I)
    links=[html.unescape(x) for x in links]
    matches=[urljoin(r.url,x) for x in links if re.search(r"Tenders[-_%20]*\d{6,8}\.zip",x,re.I)]
    if not matches:
        # The 2026-11-01 official ZIP is a publicly indexed link, but can become stale.
        matches=re.findall(r"""(?:https?://[^"'\s<>]+|/[^"'\s<>]+)Tenders-\d{8}\.zip(?:\?[^"'\s<>]*)?""",r.text,re.I)
        matches=[urljoin(r.url,html.unescape(x)) for x in matches]
    out["candidate_archive_links_found"]=len(matches)
    if not matches:
        raise ValueError("No current official Tenders-*.zip URL found in the official procurement page")
    selected=matches[0]
    # Always keep source provenance on the official procurement domain.
    if urlparse(selected).hostname!="mr.gov.il":
        raise ValueError("Archive URL is not on mr.gov.il")
    out["archive_url"]=selected
    stamp=re.search(r"Tenders-(\d{8})\.zip",selected,re.I)
    out["report_stamp"]=stamp.group(1) if stamp else None
    r=s.get(selected,timeout=90)
    out["archive_http_status"]=r.status_code
    out["archive_content_type"]=r.headers.get("content-type","")
    r.raise_for_status()
    raw=r.content
    if len(raw)>30_000_000 or not zipfile.is_zipfile(io.BytesIO(raw)):
        raise ValueError("Archive is not a reasonable-size ZIP")
    out["archive_sha256"]=hashlib.sha256(raw).hexdigest()
    z=zipfile.ZipFile(io.BytesIO(raw))
    def record(row,file_name,row_number):
        if not row:return
        flat=" | ".join(str(x or "").strip() for x in row)
        if not flat:return
        out["rows_parsed"]+=1
        if any(k in flat for k in KEYS):
            out["candidate_rows"].append({"file":file_name,"row":row_number,
                                        "matched_terms":[k for k in KEYS if k in flat],
                                        "excerpt":flat[:1200]})
            if len(out["candidate_rows"])>1000:
                del out["candidate_rows"][1000:]
    for f in z.infolist():
        item={"name":f.filename,"bytes":f.file_size}
        if f.is_dir():continue
        ext=Path(f.filename).suffix.lower()
        if f.file_size>80_000_000:
            item["error"]="Unreasonably large uncompressed content"
            out["files"].append(item);continue
        try:
            if ext==".csv":
                data=z.read(f)
                decoded=None
                for enc in ("utf-8-sig","cp1255","utf-16","latin-1"):
                    try:decoded=data.decode(enc);item["encoding"]=enc;break
                    except UnicodeError:pass
                if decoded is None:raise ValueError("Unable to decode CSV")
                sep="\t" if decoded[:500].count("\t")>decoded[:500].count(",") else ","
                for n,row in enumerate(csv.reader(io.StringIO(decoded),delimiter=sep),1):
                    record(row,f.filename,n)
                item["parsed"]=True
            elif ext==".xlsx":
                from openpyxl import load_workbook
                book=load_workbook(io.BytesIO(z.read(f)),read_only=True,data_only=True)
                for sheet in book.worksheets:
                    for n,row in enumerate(sheet.iter_rows(values_only=True),1):
                        record(row,f.filename+"/"+sheet.title,n)
                book.close();item["parsed"]=True
            elif ext==".xls":
                data=z.read(f)
                if data.lstrip(b"\\xef\\xbb\\xbf \\t\\r\\n").startswith(b"<?xml"):
                    # Excel 2003 XML SpreadsheetML is often named .xls; xlrd cannot open it.
                    item["format"]="SpreadsheetML XML 2003"
                    n=0
                    source=io.BytesIO(data)
                    for event,elem in ET.iterparse(source,events=("end",)):
                        if elem.tag.split("}")[-1]=="Row":
                            n+=1
                            cells=[sub.text or "" for sub in elem.iter() if sub.tag.split("}")[-1]=="Data"]
                            record(cells,f.filename+"/XML-Spreadsheet",n)
                            elem.clear()
                    item["rows"]=n
                    item["parsed"]=n>0
                else:
                    import xlrd
                    book=xlrd.open_workbook(file_contents=data)
                    for sheet in book.sheets():
                        for n in range(sheet.nrows):
                            record(sheet.row_values(n),f.filename+"/"+sheet.name,n+1)
                    item["parsed"]=True
            else:
                item["skipped"]="Unsupported document type"
        except Exception as e:
            item["error"]=type(e).__name__+": "+str(e)[:250]
        out["files"].append(item)
    out["retrieval_verified"]=all(v.get("parsed") for v in out["files"]) and len(out["files"])>0 and out["rows_parsed"]>0
    out["procurement_data_current"]=False # Archive is monthly, not same-day government notices.
except Exception as e:
    out["error"]=type(e).__name__+": "+str(e)[:300]
out["candidate_count"]=len(out["candidate_rows"])
(BASE/"procurement_archive.json").write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps({"index_status":out.get("index_status"),"archive_http_status":out.get("archive_http_status"),
                  "archive":out.get("report_stamp"),"verified":out["retrieval_verified"],
                  "rows":out["rows_parsed"],"candidates":out["candidate_count"],"files":out["files"],
                  "error":out.get("error"),"coverage_complete":out["allocation_publications_full_coverage"]},ensure_ascii=False))
