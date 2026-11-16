#!/usr/bin/env python3
"""Discover official surgical-allocation notices even when gov.il HTML is blocked.

Independent search/index and public reader paths discover leads ONLY. A document is
verified only after successfully retrieving a valid PDF directly from www.gov.il.
This is NOT full government-publication coverage, and cannot fix a 403 on gov.il.
"""
from __future__ import annotations

import hashlib
import html
import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, unquote, urlparse
from xml.etree import ElementTree as ET

import requests
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent / "state"
ROOT.mkdir(exist_ok=True)
REPORT_PATH = ROOT / "official_notice_discovery.json"
SNAPSHOT_PATH = ROOT / "official_notice_discovery_seen.json"
OFFICIAL = "https://www.gov.il/he/pages/competitive-procedure-surgical-positions-northern-district"
PDF = "https://www.gov.il/BlobFolder/publicsharing/competitive-procedure-surgical-positions-northern-district/he/files_invitation-to-tender_competitive-procedure-surgical-positions-northern-district.pdf"
KEYWORDS = ("כירורג", "בינוני", "הקצאה", "עמדות ניתוח", "surgical-positions", "competitive-procedure", "הבהרות")
QUERIES = [
    'site:gov.il "competitive-procedure-surgical-positions-northern-district"',
    'site:gov.il/BlobFolder "עמדות כירורגיות בינוניות" "צפון"',
    'site:gov.il "ועדת ההקצאה" "כירורגיה בינונית" "2026"',
]
SOURCES = [
    ("public-reader", "https://r.jina.ai/" + OFFICIAL),
    ("bing-rss", "https://www.bing.com/search?format=rss&q=" + quote(QUERIES[0])),
    ("bing-rss-broad", "https://www.bing.com/search?format=rss&q=" + quote(QUERIES[2])),
    ("google-search", "https://www.google.com/search?q=" + quote(QUERIES[0]) + "&hl=he&num=30"),
    ("google-search-broad", "https://www.google.com/search?q=" + quote(QUERIES[1]) + "&hl=he&num=30"),
    ("google-news-rss", "https://news.google.com/rss/search?q=" + quote(QUERIES[2]) + "&hl=he&gl=IL&ceid=IL:he"),
]
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; PublicOfficialNoticeDiscovery/1.0)",
           "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8"}
s = requests.Session()
s.headers.update(HEADERS)


def load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def clean_url(u):
    u = html.unescape(unquote(u).replace("\\/", "/")).strip().strip("<>[]()\"'.,")
    u = u.split("#")[0]
    if u.startswith("//www.gov.il/"):
        u = "https:" + u
    if not u.startswith("https://www.gov.il/"):
        return None
    host = urlparse(u).hostname
    if host != "www.gov.il":
        return None
    return u[:700]


def links_from_text(source):
    # All output is treated as third-party indexing until original gov.il PDF is retrieved.
    result = set()
    source = html.unescape(source.replace("\\/", "/"))
    for raw in re.findall(r"https?://(?:www\.)?gov\.il/[^\s<>'\"\)\]]+", source, re.I):
        u = clean_url(raw)
        if u:
            result.add(u)
    for raw in re.findall(r"(?:https?%3A%2F%2F(?:www%2E)?gov%2Eil%2F)[^\s<>'\"&]+", source, re.I):
        u = clean_url(raw)
        if u:
            result.add(u)
    return result


out = {"checked_at_utc": datetime.now(timezone.utc).isoformat(),
       "official_page": OFFICIAL, "known_official_pdf": PDF,
       "source_statuses": [], "candidate_official_urls": [],
       "verified_official_pdfs": [], "new_candidate_urls": [],
       "new_verified_pdf_hashes": [],
       "publication_page_directly_accessible": False,
       "coverage_complete": False,
       "provenance_warning": "Public reader/search results are discovery-only. Official PDF must download successfully from www.gov.il to count as verified."}
candidates = {OFFICIAL, PDF}
for kind, url in SOURCES:
    item = {"source": kind, "url": url, "official_source": False}
    try:
        r = s.get(url, timeout=23, allow_redirects=True)
        item["http_status"] = r.status_code
        item["bytes"] = len(r.content)
        item["content_type"] = r.headers.get("content-type", "")[:100]
        if r.status_code == 200 and len(r.content) < 6_000_000:
            body = r.text
            parsed = links_from_text(body)
            candidates.update(parsed)
            item["indexed_official_urls"] = len(parsed)
            item["contains_known_notice_slug"] = "competitive-procedure-surgical-positions-northern-district" in body
            item["mentions_operative_terms"] = any(w in body for w in KEYWORDS)
            item["short_excerpt"] = re.sub(r"\s+", " ", body[:1800])[:650]
        else:
            item["error"] = "Non-200 or implausibly large response"
    except Exception as e:
        item["error"] = type(e).__name__ + ": " + str(e)[:170]
    out["source_statuses"].append(item)

# Check candidate PDF links via the ORIGINAL official host.
# Reader/index metadata never substitutes for an original signed PDF.
filter_urls = [u for u in candidates if
               u == PDF or
               ("gov.il/BlobFolder/" in u and ".pdf" in u.lower() and
                any(k in u.lower() for k in ("surgic", "competitive", "hirurg", "chirurg", "northern")))]
filter_urls.sort(key=lambda x: (x != PDF, x))
for url in filter_urls[:8]:
    d = {"url": url, "official_source": True, "pdf_verified": False}
    try:
        r = s.get(url, timeout=35, stream=True)
        d["http_status"] = r.status_code
        if r.status_code != 200:
            continue
        raw = bytearray()
        for chunk in r.iter_content(65536):
            raw.extend(chunk)
            if len(raw) > 12_000_000:
                raise ValueError("PDF too large")
        if not raw[:5] == b"%PDF-":
            raise ValueError("Original server did not return a PDF")
        pdf = PdfReader(io.BytesIO(raw))
        d["sha256"] = hashlib.sha256(raw).hexdigest()
        d["pages"] = len(pdf.pages)
        text = "\n".join((p.extract_text() or "") for p in pdf.pages[:4])
        d["has_relevant_text"] = any(w in text for w in ("כירורג", "כירורגיה", "תואירוגירכ", "הקצאה", "האצקה"))
        d["pdf_verified"] = bool(len(pdf.pages) and len(text)>200)
    except Exception as e:
        d["error"] = type(e).__name__ + ": " + str(e)[:140]
    finally:
        out["verified_official_pdfs"].append(d)

known = load(SNAPSHOT)
seen_urls = set(known.get("seen_urls", []))
seen_hashes = set(known.get("seen_sha256", []))
new_candidates = sorted(candidates - seen_urls)
new_hashes = [x for x in out["verified_official_pdfs"]
              if x.get("pdf_verified") and x.get("sha256") not in seen_hashes]
out["candidate_official_urls"] = sorted(candidates)
out["new_candidate_urls"] = new_candidates
out["new_verified_pdf_hashes"] = [{"url":x["url"],"sha256":x["sha256"]} for x in new_hashes]
out["first_run_baseline_created"] = not bool(known)
out["attention_required"] = bool((new_candidates or new_hashes) and bool(known))
out["source_index_coverage_proven"] = False

save(REPORT_PATH, out)
save(SNAPSHOT_PATH, {
    "last_checked_at_utc": out["checked_at_utc"],
    "seen_urls": sorted(seen_urls | candidates),
    "seen_sha256": sorted(seen_hashes | {x["sha256"] for x in out["verified_official_pdfs"] if x.get("pdf_verified")}),
})
print(json.dumps({"checked_at_utc":out["checked_at_utc"],
                  "sources":[(x["source"],x.get("http_status"),x.get("indexed_official_urls"),x.get("error"))
                             for x in out["source_statuses"]],
                  "official_candidates":len(out["candidate_official_urls"]),
                  "verified_pdfs":len([x for x in out["verified_official_pdfs"] if x["pdf_verified"]]),
                  "new_url_count":len(new_candidates),"attention_required":out["attention_required"],
                  "coverage_complete":False},ensure_ascii=False))
