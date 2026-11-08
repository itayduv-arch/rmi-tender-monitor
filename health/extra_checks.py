#!/usr/bin/env python3
"""Read-only fallback health-source checks. Never treats index/search as licensing approval."""
import io
import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
from pypdf import PdfReader

BASE = Path(__file__).resolve().parent / "state"
BASE.mkdir(exist_ok=True)
DOCS = {
    "projects_procedure_2025": "https://www.gov.il/BlobFolder/policy/project-committee-work-activity-procedures/he/files_committees_projects-committee_project-committee-work-activity-procedures-2025-09504825.pdf",
    "southern_allocation_historical": "https://www.gov.il/BlobFolder/publicsharing/competitive-procedure-surgical-positions-southern-district/he/files_invitation-to-tender_competitive-procedure-surgical-positions-southern-district.pdf",
    "medili_2017_historical": "https://www.gov.il/BlobFolder/reports/mandili-15022017/he/files_publications_units_general_medicine_mandili_15022017.pdf",
    "medili_2019_historical": "https://www.gov.il/BlobFolder/reports/medili-23012019/he/files_publications_units_general_medicine_medili_23012019.pdf",
    "schwartz_2019_historical_dental": "https://www.gov.il/BlobFolder/reports/swhartz-27022019/he/files_publications_units_general_medicine_swhartz_27022019.pdf",
    "medika_2024_inspection_historical": "https://www.gov.il/BlobFolder/dynamiccollectorresultitem/medika-18092024/he/files_publications_units_general_medicine_medika-18092024.pdf",
}
s = requests.Session()
s.headers.update({"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36", "Accept-Language": "he,en;q=0.8"})
out = {
    "checked_at_utc": datetime.now(timezone.utc).isoformat(),
    "classification": "access-and-evidence-diagnostics-not-current-licence-proof",
    "direct_official_documents": {},
    "official_listing_page": {},
    "mr_portal": {},
    "licence_status_conflicts": [],
    "licence_current_confirmed_by_documents": False,
    "general_anaesthesia_current_confirmed": False,
    "allocation_publications_full_coverage": False,
    "limitations": [],
}
for key, url in DOCS.items():
    d = {"url": url, "historical_only": True}
    try:
        r = s.get(url, timeout=35)
        d["status"] = r.status_code
        d["is_official_pdf"] = r.status_code == 200 and r.content[:5] == b"%PDF-"
        if d["is_official_pdf"]:
            pdf = PdfReader(io.BytesIO(r.content))
            d["pages"] = len(pdf.pages)
            snippets = []
            for i, page in enumerate(pdf.pages):
                t = re.sub(r"\s+", " ", page.extract_text() or "")
                for phrase in ("הרדמה כללית", "מרדים", "חדרי ניתוח", "כירורגיה בינונית"):
                    at = t.find(phrase)
                    if at >= 0 and len(snippets) < 6:
                        snippets.append({"page": i + 1, "term": phrase, "excerpt": t[max(0, at - 85):at + 175]})
            d["historical_evidence_mentions"] = snippets
    except Exception as e:
        d["error"] = type(e).__name__ + ": " + str(e)[:160]
    out["direct_official_documents"][key] = d

for key, url in {
    "committee_projects": "https://www.gov.il/he/departments/units/projects-committee",
    "inspections_index": "https://www.gov.il/he/departments/dynamiccollectors/inspections-db",
    "beds2025_index": "https://www.gov.il/he/pages/licensed-inpatient-hospital-beds-dec-2025",
}.items():
    d = {"url": url}
    try:
        r = s.get(url, timeout=18)
        d["status"] = r.status_code
        d["readable"] = (r.status_code == 200 and "Sorry, you have been blocked" not in r.text and "Just a moment" not in r.text)
    except Exception as e:
        d["error"] = type(e).__name__ + ": " + str(e)[:150]
    out["official_listing_page"][key] = d

try:
    facilities = json.loads((BASE / "facilities.json").read_text(encoding="utf-8"))
    out["registry_api_complete"] = facilities.get("api_complete") is True
    out["registry_snapshot_at_utc"] = facilities.get("checked_at_utc")
    out["report2025_available"] = facilities.get("pdf_valid") is True
    checked = datetime.fromisoformat(facilities["checked_at_utc"])
    out["registry_snapshot_recent_48h"] = datetime.now(timezone.utc) - checked <= timedelta(hours=48)
    for f in facilities.get("current_facilities", []):
        end = (f.get("endDate") or "")[:10]
        if end and end < out["checked_at_utc"][:10] and f.get("status") == "בתוקף":
            out["licence_status_conflicts"].append({
                "instituteCode": f.get("instituteCode"), "name": f.get("instituteName"),
                "status": f.get("status"), "endDate": f.get("endDate"),
                "action": "Do not certify current validity. Require renewed ministry registration or written confirmation."
            })
except Exception as e:
    out["registry_error"] = type(e).__name__ + ": " + str(e)[:180]

# A successful response for 22,000 unrelated tenders is not evidence that a relevant search was performed.
# Log genuine query diagnostics using the rendered search UI, without claiming full coverage.
try:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(locale="he-IL")
        page = context.new_page()
        response = page.goto("https://mr.gov.il/ilgstorefront/he/search?s=TENDER", wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(1800)
        initial = page.title()
        out["mr_portal"]["listing_http_status"] = response.status if response else None
        out["mr_portal"]["listing_title"] = initial[:250]
        out["mr_portal"]["searches"] = []
        for term in ["כירורגיה בינונית", "הקצאת עמדות ניתוח", "מרפאות כירורגיות", "ועדת הקצאה", "אישור הקמה מרפאה כירורגית"]:
            rec = {"term": term, "query_verified": False}
            try:
                page.goto("https://mr.gov.il/ilgstorefront/he/search?s=TENDER", wait_until="domcontentloaded", timeout=40000)
                field = page.locator('input[placeholder*="חפש"]:visible')
                rec["visible_search_inputs"] = field.count()
                if field.count() == 0:
                    rec["error"] = "No discoverable visible search box"
                else:
                    field.first.fill(term)
                    field.first.press("Enter")
                    page.wait_for_timeout(2800)
                    rec["url_after_search"] = page.url
                    rec["title_after_search"] = page.title()[:220]
                    body = page.locator("body").inner_text(timeout=15000)
                    rec["body_excerpt"] = body[:700]
                    rec["relevant_links"] = page.locator('a[href*="/ilgstorefront/he/p/"]').evaluate_all(
                        '(els) => els.slice(0,20).map(e => ({text:(e.innerText||"").slice(0,180),url:e.href}))')
                    rec["query_verified"] = term in rec["title_after_search"] and (
                        rec["title_after_search"] != initial or term in rec["url_after_search"])
                    if not rec["query_verified"]:
                        rec["warning"] = "Search UI did not demonstrate a query-specific result set"
            except Exception as e:
                rec["error"] = type(e).__name__ + ": " + str(e)[:150]
            out["mr_portal"]["searches"].append(rec)
        context.close()
        browser.close()
except Exception as e:
    out["mr_portal"]["error"] = type(e).__name__ + ": " + str(e)[:180]

out["mr_portal"]["verified_query_search"] = any(x.get("query_verified") for x in out["mr_portal"].get("searches", []))
if not out["mr_portal"]["verified_query_search"]:
    out["limitations"].append("Government procurement query not independently validated; an open results page alone is insufficient.")
if not all(x.get("readable") for x in out["official_listing_page"].values()):
    out["limitations"].append("Some official publication-index HTML pages remain blocked; direct official PDFs are only partial substitutes.")
if out["licence_status_conflicts"]:
    out["limitations"].append("Licence end-date/status contradictions need official clarification.")
out["limitations"].append("Historical inspections do not confirm current general-anaesthesia activity or authorisation.")
(BASE / "source_checks.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({
    "checked_at_utc": out["checked_at_utc"],
    "direct_pdf_http": {k: v.get("status") for k,v in out["direct_official_documents"].items()},
    "mr_portal": {k:v for k,v in out["mr_portal"].items() if k != "searches"},
    "searches": [{k:v for k,v in x.items() if k in ("term","query_verified","error","warning")} for x in out["mr_portal"].get("searches",[])],
    "licence_conflicts": len(out["licence_status_conflicts"]),
    "full_coverage": out["allocation_publications_full_coverage"]
}, ensure_ascii=False, indent=2))
