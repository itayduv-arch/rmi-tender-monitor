#!/usr/bin/env python3
"""Public Ministry-of-Health RSS mirror used as discovery-only when gov.il returns 403.

The original feed belongs to gov.il. The Feeder public page is third-party and cannot
prove completeness or authenticity of a tender; do not label results as verified.
"""
import html,json,re
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlparse
import requests

OUT=Path(__file__).resolve().parent/"state"/"moh_feed_mirror.json"
OUT.parent.mkdir(exist_ok=True)
MIRROR="https://feeder.co/discover/ff5b8f88c5/gov-il-he-departments-publications"
ORIGINAL="https://www.gov.il/he/api/PublicationApi/rss/104cb0f4-d65a-4692-b590-94af928c19c0"
KEYWORDS=["כירורג", "הרדמה כללית", "עמדות ניתוח", "הקצאה", "חדרי ניתוח", "ועדת פרויקטים", "ניתוחים בקהילה"]
out={"checked_at_utc":datetime.now(timezone.utc).isoformat(),
     "source_kind":"third-party public mirror of official Ministry of Health RSS; discovery only",
     "mirror":MIRROR,"original_official_feed":ORIGINAL,
     "live_official_feed_access":False,"coverage_complete":False,
     "items":[],"matching_items":[],"notes":["Do not treat Feeder titles as a Ministry of Health licence or signed allocation announcement. Open the linked official notice and documents when accessible."]}
try:
    r=requests.get(MIRROR,timeout=35,headers={"User-Agent":"Mozilla/5.0 (compatible; PublicHealthNoticeMonitor/1.0)"})
    out["mirror_http_status"]=r.status_code
    r.raise_for_status()
    source=r.text
    # Public HTML includes a 'Latest posts' section; limit extraction to that segment.
    anchor=re.search(r"Latest posts",source,re.I)
    tail=re.search(r"Get .{0,120} where you read",source,re.I)
    region=source[anchor.start():(tail.start() if tail and tail.start()>anchor.start() else anchor.start()+110000)] if anchor else source[:180000]
    candidates=re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>',region,re.I|re.S)
    seen=set()
    for rawurl,rawtitle in candidates:
        url=html.unescape(rawurl)
        if urlparse(url).hostname not in ("gov.il","www.gov.il") or "/api/" in url:
            continue
        title=html.unescape(re.sub("<[^>]+>"," ",rawtitle))
        title=re.sub(r"\s+"," ",title).strip()
        if not title or len(title)<8 or title.lower() in ("read full","לקרוא את הכול") or url in seen:
            continue
        seen.add(url)
        item={"title":title[:280],"official_url":url,"verified_original_document":False}
        out["items"].append(item)
        hits=[k for k in KEYWORDS if k in title]
        if hits:out["matching_items"].append({**item,"keyword_hits":hits})
    out["mirror_titles_extracted"]=len(out["items"])
    out["mirror_readable"]=len(out["items"])>0
except Exception as e:out["error"]=type(e).__name__+": "+str(e)[:240]
OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps({"mirror_http_status":out.get("mirror_http_status"),"mirror_readable":out.get("mirror_readable"),
"titles":len(out["items"]),"matches":len(out["matching_items"]),"error":out.get("error"),"coverage_complete":False},ensure_ascii=False))
