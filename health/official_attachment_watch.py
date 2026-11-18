#!/usr/bin/env python3
"""Verify every known/discovered north surgery tender attachment at its original gov.il URL.

A third-party read-through is used ONLY to discover links while the government
HTML page is blocked. All successful documents must be retrieved and parsed
directly from www.gov.il. No result claims full publication-page coverage.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import openpyxl
import requests
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent / "state"
ROOT.mkdir(parents=True, exist_ok=True)
OUT = ROOT / "official_attachment_status.json"
SNAP = ROOT / "official_attachment_last_verified.json"
DISCOVERY = ROOT / "official_notice_discovery.json"
ACCESS = ROOT / "northern_tender_status.json"
PREFIX = ("https://www.gov.il/BlobFolder/publicsharing/"
          "competitive-procedure-surgical-positions-northern-district/he/")
OFFICIAL_PAGE = "https://www.gov.il/he/pages/competitive-procedure-surgical-positions-northern-district"
KNOWN = [
    PREFIX + "files_invitation-to-tender_competitive-procedure-surgical-positions-northern-district.pdf",
    PREFIX + "files_invitation-to-tender_competitive-procedure-surgical-positions-northern-district-%20faq.pdf",
    PREFIX + "files_invitation-to-tender_cfb-072006-a.xlsx",
    PREFIX + "files_invitation-to-tender_cfb-072006-b.xlsx",
]
MAX_DOCUMENTS = 20
MAX_BYTES = 20_000_000


def load(path):
    try:
        val = json.loads(path.read_text(encoding="utf-8"))
        return val if isinstance(val, dict) else {}
    except (ValueError, OSError):
        return {}


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def allow_url(url):
    if not isinstance(url, str):
        return False
    parsed = urlparse(url)
    return (parsed.scheme == "https" and parsed.netloc == "www.gov.il"
            and url.startswith(PREFIX) and parsed.path.lower().endswith((".pdf", ".xlsx"))
            and len(url) <= 800 and not parsed.query)


def discover_links(discovery):
    """Reader and index are hints, never official publication-page verification."""
    items = set(KNOWN)
    for u in discovery.get("candidate_official_urls", []):
        if allow_url(u):
            items.add(u)
    for source in discovery.get("source_statuses", []):
        if source.get("source") != "public-reader" or source.get("http_status") != 200:
            continue
        txt = source.get("reader_full_text", "")
        for match in re.findall(r"https://www\.gov\.il/BlobFolder/[^\s\]<>\"']+", txt):
            clean = match.strip(".,)\\").replace("&amp;", "&")
            if allow_url(clean):
                items.add(clean)
    return sorted(items)[:MAX_DOCUMENTS]


def download_original(session, url):
    rec = {"url": url, "original_government_host": True, "verified": False}
    try:
        with session.get(url, timeout=50, stream=True, allow_redirects=True) as response:
            rec["http_status"] = response.status_code
            rec["final_host"] = urlparse(response.url).hostname
            if response.status_code != 200 or rec["final_host"] != "www.gov.il":
                rec["error"] = "Original government URL not directly accessible"
                return rec
            data = bytearray()
            for part in response.iter_content(65536):
                data.extend(part)
                if len(data) > MAX_BYTES:
                    raise ValueError("Attachment exceeds size limit")
        content = bytes(data)
        rec["bytes"] = len(content)
        rec["sha256"] = hashlib.sha256(content).hexdigest()
        if url.lower().endswith(".pdf"):
            if not content.startswith(b"%PDF-"):
                raise ValueError("Non-PDF returned at PDF URL")
            pdf = PdfReader(io.BytesIO(content))
            if not pdf.pages:
                raise ValueError("PDF has no pages")
            rec["format"] = "pdf"
            rec["page_count"] = len(pdf.pages)
            rec["page_text_lengths"] = [len(p.extract_text() or "") for p in pdf.pages]
            if sum(rec["page_text_lengths"]) < 100:
                raise ValueError("PDF has no extractable text; manual review needed")
            terms = ("הגשה", "ערבות", "שאלות הבהרה", "מועד", "כירורגיה בינונית",
                     "הרדמה", "תיקון", "16.12.2026")
            matches = []
            for pnum, page in enumerate(pdf.pages, 1):
                plain = re.sub(r"\s+", " ", page.extract_text() or "")
                for term in terms:
                    idx = plain.find(term)
                    if idx >= 0:
                        matches.append({"page": pnum, "term": term,
                                        "excerpt": plain[max(0, idx - 60):idx + 200]})
                if len(matches) >= 24:
                    break
            rec["relevant_passages"] = matches[:24]
        else:
            if not zipfile.is_zipfile(io.BytesIO(content)):
                raise ValueError("Non-XLSX returned at XLSX URL")
            book = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
            rec["format"] = "xlsx"
            rec["sheet_names"] = book.sheetnames
            rec["sheet_dimensions"] = [
                {"name": s.title, "max_row": s.max_row, "max_column": s.max_column}
                for s in book.worksheets
            ]
            book.close()
        rec["verified"] = True
    except Exception as exc:
        rec["error"] = type(exc).__name__ + ": " + str(exc)[:180]
    return rec


def main():
    now = datetime.now(timezone.utc).isoformat()
    discovery = load(DISCOVERY)
    access = load(ACCESS)
    old = load(SNAP)
    old_files = {d["url"]: d for d in old.get("documents", []) if d.get("verified") and d.get("url")}
    reader_ok = any(s.get("source") == "public-reader" and s.get("http_status") == 200
                    for s in discovery.get("source_statuses", []))
    urls = discover_links(discovery)
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0", "Accept-Language": "he-IL,he;q=0.9"})
    direct_status = None
    page_ok = False
    page_discovered_urls = []
    try:
        page_response = session.get(OFFICIAL_PAGE, timeout=25)
        direct_status = page_response.status_code
        if (direct_status == 200 and urlparse(page_response.url).hostname == "www.gov.il"
                and "כירורג" in page_response.text):
            page_ok = True
            discovered = re.findall(r'https://www[.]gov[.]il/BlobFolder/[^\s"<>]+', page_response.text)
            page_discovered_urls = [u for raw in discovered if allow_url(u := raw.strip("'").strip(")"))]
            urls = sorted(set(urls) | set(page_discovered_urls))[:MAX_DOCUMENTS]
    except requests.RequestException:
        pass
    documents = [download_original(session, u) for u in urls]
    verified = {d["url"]: d for d in documents if d.get("verified")}
    changed = [u for u, d in verified.items()
               if u in old_files and old_files[u].get("sha256") != d.get("sha256")]
    added = [u for u in verified if u not in old_files]
    unavailable = [d["url"] for d in documents if not d.get("verified")]
    merged = {**old_files, **verified}
    report = {
        "checked_at_utc": now,
        "source": "official gov.il original attachments; third-party page discovery only",
        "official_publication_page_accessible": page_ok,
        "official_publication_html_status": direct_status,
        "official_page_document_links_found": page_discovered_urls,
        "secondary_reader_accessible": reader_ok,
        "candidate_count": len(urls),
        "documents": documents,
        "verified_attachment_count": len(verified),
        "expected_known_attachment_count": len(KNOWN),
        "all_known_attachments_verified": all(u in verified for u in KNOWN),
        "newly_verified_urls": added,
        "modified_verified_urls": changed,
        "unverified_attachment_urls": unavailable,
        "attention_required": bool((added or changed) and bool(old_files)),
        "first_snapshot_created": not bool(old_files),
        "all_publication_links_verified": bool(page_ok and not unavailable and page_discovered_urls),
        "coverage_complete": bool(page_ok and not unavailable and page_discovered_urls),
        "warning": ("Direct government publication HTML remains unavailable. A third-party "
                    "reader may omit or delay new links; independently retrieved gov.il "
                    "attachments are verified, but complete coverage is NOT established.")
                   if not page_ok else None,
        "work_cloud_browser_used": False,
    }
    save(OUT, report)
    save(SNAP, {
        "last_checked_at_utc": now,
        "documents": [merged[u] for u in sorted(merged)],
        "historical_records_may_be_stale": True,
    })
    print(json.dumps({
        "checked_at_utc": now, "reader_ok": reader_ok,
        "direct_page_ok": page_ok,
        "verified": len(verified), "known_docs_verified": report["all_known_attachments_verified"],
        "new_verified": len(added), "changed": len(changed), "unavailable": unavailable,
        "coverage_complete": report["coverage_complete"]
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
