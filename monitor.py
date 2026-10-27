#!/usr/bin/env python3
"""Daily, read-only RMI API monitoring. Only apps.land.gov.il is an authority."""
from __future__ import annotations
import hashlib
import io
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
import requests
from pypdf import PdfReader

ROOT = "https://apps.land.gov.il"
BASE = ROOT + "/MichrazimSite/"
API = BASE + "api/"
WATCH = {"470/2025": "הוד השרון", "182/2025": "גנות", "149/2025": "צופית"}
# Location code lists help to discover candidates, not establish tender status.
# Confirm every potential tender from official RMI details before notifying users.
LOCATION_CODES = {
    "סביון": 587, "כפר מעש": 230, "מגשימים": 722, "גת רימון": 128,
    "בני עטרות": 448, "כפר סירקין": 249, "מזור": 606,
    "נופך": 257, "רינתיה": 616, "גבעת חן": 207,
    "ירקונה": 183, "רמות השבים": 206,
    "רשפון": 247, "כפר שמריהו": 267,
}

STATE = Path("state/latest.json")
ARTIFACT = Path("reports/latest-run.json")
DOCUMENT_FIELDS = ("RowID", "DocName", "Teur", "UpdateDate", "PirsumType", "MahutMismachID", "FileType")
DETAIL_FIELDS = (
    "MichrazID", "MichrazName", "PirsumDate", "PtichaDate", "SgiraDate",
    "UpdateDate", "StatusMichraz", "StatusMichrazMurchav", "ReadyForHagasha",
    "YechidotDiur", "KodYeudMichraz", "KodYeshuv", "Shchuna", "Uchlusiyot",
    "HagashaMekuvenet", "MechirSafMichraz", "SchumArvut", "SchumHishtatfut",
    "MichrazFullDocument", "KhalYaadRashi", "MaxToWin", "MatziaCanLimit",
)
REQUEST_TIMEOUT = 40
LAST_RUN_REPORT_VERSION = 3

def tender_id(number: str) -> int:
    n, year = number.split("/")
    return int(year) * 10000 + int(n)

def digest(obj: object) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()

def official_request(session: requests.Session, method: str, url: str, **kwargs) -> requests.Response:
    if urlparse(url).hostname != "apps.land.gov.il":
        raise ValueError("Refusing non-RMI URL")
    response = session.request(method, url, timeout=REQUEST_TIMEOUT, allow_redirects=False, **kwargs)
    if response.is_redirect or response.is_permanent_redirect:
        raise RuntimeError("Official RMI API unexpectedly redirected")
    if urlparse(response.url).hostname != "apps.land.gov.il":
        raise RuntimeError("Response URL was not on apps.land.gov.il")
    response.raise_for_status()
    return response

def parse_api(r: requests.Response) -> object:
    v = r.json()
    if v is None:
        raise ValueError("Official RMI API returned null")
    return v

def flatten_search(v: object) -> list[dict]:
    if isinstance(v, list):
        return [x for x in v if isinstance(x, dict)]
    if isinstance(v, dict):
        for key in ("results", "Results", "data", "Data", "Items", "items"):
            if isinstance(v.get(key), list):
                return [x for x in v[key] if isinstance(x, dict)]
    raise ValueError("Unrecognized official search response shape")

def normalize_doc(d: dict) -> dict:
    return {key: d.get(key) for key in DOCUMENT_FIELDS}

def normalize_tender(raw: dict, number: str, city: str) -> dict:
    if raw.get("MichrazID") != tender_id(number) or raw.get("MichrazName") != number:
        raise ValueError(f"RMI returned wrong identity for {number}")
    result = {key: raw.get(key) for key in DETAIL_FIELDS}
    result["location_label"] = city
    result["official_url"] = BASE + "#/michraz/" + str(tender_id(number))
    message = raw.get("MessageDetails") or {}
    result["official_message"] = message.get("messageText") if isinstance(message, dict) else None
    docs = raw.get("MichrazDocList") or []
    result["documents"] = sorted([normalize_doc(d) for d in docs if isinstance(d, dict)], key=lambda x: x.get("RowID") or 0)
    result["document_count"] = len(result["documents"])
    # Definitively closed/not yet open from explicit RMI message; do not invent open status
    note = result["official_message"] or ""
    if any(word in note for word in ("טרם נפתח", "אינו פתוח", "לא ניתן להגיש", "נסגר", "בוטל")):
        result["submission_state"] = "not_open_according_to_official_message"
    elif raw.get("ReadyForHagasha") is True and raw.get("HagashaMekuvenet") is True:
        result["submission_state"] = "likely_open_requires_form_confirmation"
    else:
        result["submission_state"] = "unverified"
    result["fingerprint"] = digest({key: val for key, val in result.items() if key != "fingerprint"})
    return result

def collect_official_pdfs(session: requests.Session, raw: dict) -> tuple[dict, list[dict]]:
    """Download public documents using the exact official site's POST schema."""
    id_ = raw["MichrazID"]
    objects = [("full_publication", raw.get("MichrazFullDocument"))]
    objects += [(str(doc.get("RowID")), doc) for doc in (raw.get("MichrazDocList") or []) if isinstance(doc, dict)]
    verified: dict = {}
    errors: list[dict] = []
    for key, doc in objects:
        if not isinstance(doc, dict):
            continue
        if doc.get("MichrazID") != id_:
            errors.append({"key": key, "problem": "Document belonged to unexpected tender"})
            continue
        try:
            res = official_request(session, "POST", API + "MichrazDetailsApi/GetFileContent", json=doc)
            if not res.content.startswith(b"%PDF"):
                raise ValueError(f"RMI document response was not a PDF; HTTP {res.status_code}")
            if len(res.content) > 40_000_000:
                raise ValueError("Unexpectedly large PDF; manual review needed")
            entry = {"sha256": hashlib.sha256(res.content).hexdigest(), "bytes": len(res.content),
                     "document_title": doc.get("Teur") or doc.get("DocName"),
                     "document_update_date": doc.get("UpdateDate")}
            # Extracted text is just a clue. Scanned or RTL-heavy documents need manual visual review.
            try:
                reader = PdfReader(io.BytesIO(res.content))
                entry["pages"] = len(reader.pages)
                samples = []
                for p in reader.pages[:min(len(reader.pages), 8)]:
                    if sum(len(t) for t in samples) > 3500:
                        break
                    samples.append(p.extract_text() or "")
                entry["text_excerpt_unreviewed"] = " ".join(samples)[:3500]
                entry["text_extraction_succeeded"] = bool(entry["text_excerpt_unreviewed"].strip())
            except Exception as error:
                entry["text_extraction_succeeded"] = False
                entry["text_extraction_error"] = type(error).__name__
            verified[key] = entry
        except Exception as ex:
            errors.append({"key": key, "document": doc.get("DocName"), "problem": f"{type(ex).__name__}: {str(ex)[:220]}"})
        time.sleep(0.15)
    return verified, errors


def compare(previous: dict | None, current: dict, label: str) -> list[dict]:
    if previous is None:
        return []  # First successful observation establishes a baseline, not a change event.
    changed = []
    for key in sorted(set(previous) | set(current)):
        if key in ("fingerprint", "official_url", "location_label", "pdf_errors", "pdf_count_expected", "pdf_count_verified"):
            continue
        if previous.get(key) != current.get(key):
            if key == "pdf_checks":
                # A transient network error must not be mistaken for a changed document.
                older, newer = previous.get("pdf_checks") or {}, current.get("pdf_checks") or {}
                for identifier in sorted(older.keys() & newer.keys()):
                    if older[identifier].get("sha256") != newer[identifier].get("sha256"):
                        changed.append({"tender": label, "field": "pdf_document_content_sha256",
                                        "document_key": identifier,
                                        "previous_hash": older[identifier].get("sha256"),
                                        "current_hash": newer[identifier].get("sha256")})
            elif key == "documents":
                before = {str(d.get("RowID")): d for d in previous.get("documents", [])}
                after = {str(d.get("RowID")): d for d in current.get("documents", [])}
                changed.append({"tender": label, "field": "documents", "added": [v for k, v in after.items() if k not in before], "removed": [v for k, v in before.items() if k not in after], "modified": [after[k] for k in after.keys() & before.keys() if after[k] != before[k]]})
            elif key not in ("document_count",):
                changed.append({"tender": label, "field": key, "previous": previous.get(key), "current": current.get(key)})
    return changed

def discover(items: list[dict], prev: dict | None) -> dict:
    """Broad tender discovery by locality code. RMI details remain authoritative."""
    candidates = {city: [] for city in LOCATION_CODES}
    candidates["כפר אז״ר"] = []
    for row in items:
        # Official category IDs 1 and 2 are clues only; retain both and label category.
        purpose = row.get("KodYeudMichraz")
        if purpose not in (1, 2):
            continue
        code = row.get("KodYeshuv")
        name = str(row.get("Shchuna") or "").replace('"', "").replace("״", "").replace("׳", "")
        for city, location_code in LOCATION_CODES.items():
            if str(code) == str(location_code):
                candidates[city].append(row)
        # Kfar Azar can appear as a neighborhood inside a larger municipality.
        if "כפר אז" in name or "כפר-אז" in name:
            candidates["כפר אז״ר"].append(row)

    selected = {}
    for city, records in candidates.items():
        # Persist the most recent records for the first-run baseline.
        latest = sorted(records, key=lambda x: str(x.get("PirsumDate") or ""), reverse=True)[:30]
        selected[city] = [
            {k: rec.get(k) for k in ("MichrazID", "MichrazName", "Shchuna",
                                    "KodYeshuv", "KodYeudMichraz", "PirsumDate",
                                    "SgiraDate", "PublishedChoveret")}
            for rec in latest
        ]
    return {
        "candidates": selected,
        "candidate_count": {k: len(v) for k, v in candidates.items()},
        "coverage_warning": (
            "Location codes are only discovery clues. Not every residential-category tender "
            "is a self-build plot or open for individual bids. Kfar Azar may not appear "
            "in a neighborhood name: zero candidates does not prove no tender exists."
        ),
    }

def main() -> int:
    old = None
    if STATE.exists():
        try:
            old = json.loads(STATE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            old = None
    checked = datetime.now(timezone.utc).isoformat()
    out: dict = {"schema_version": LAST_RUN_REPORT_VERSION, "checked_at_utc": checked,
                 "source_host": "apps.land.gov.il", "api_base": API, "status": "ok",
                 "tenders": {}, "discovery": None, "changes": [], "errors": [],
                 "notes": ["No submission-open claim without direct official confirmation of an active application form.",
                           "A newly detected tender is a candidate until its official details have been verified."]}
    session = requests.Session()
    session.headers.update({"User-Agent": "RMI-Tender-Monitor/1.0", "Accept": "application/json, text/plain, */*",
                            "Content-Type": "application/json", "Origin": ROOT, "Referer": BASE})
    try:
        search = parse_api(official_request(session, "POST", API+"SearchApi/Search",
                                            json={"ActiveQuickSearch": False, "ActiveMichraz": False}))
        items = flatten_search(search)
        if len(items) < 100:
            raise ValueError(f"Unexpectedly small search response: {len(items)}")
        out["search_rows"] = len(items)
        out["discovery"] = discover(items, old.get("discovery") if old else None)
        past_candidates = (old or {}).get("discovery", {}).get("candidates", {})
        if not isinstance(past_candidates, dict):
            past_candidates = {}
        for city, candidates in out["discovery"]["candidates"].items():
            before_ids = {x.get("MichrazID") for x in past_candidates.get(city, [])}
            if old is not None and city in past_candidates:
                for item in candidates:
                    if item["MichrazID"] not in before_ids:
                        out["changes"].append({"tender": item.get("MichrazName"), "city": city, "field": "new_location_candidate_unverified", "official_candidate": item})
    except Exception as exc:
        out["errors"].append({"part": "all_tenders_search", "type": type(exc).__name__, "message": str(exc)[:400]})
        out["status"] = "partial"
    for number, city in WATCH.items():
        try:
            raw = parse_api(official_request(session, "GET", API+"MichrazDetailsApi/Get",
                                             params={"michrazID": tender_id(number)}))
            if not isinstance(raw, dict):
                raise ValueError("Tender detail response is not an object")
            tender = normalize_tender(raw, number, city)
            pdf, pdf_errors = collect_official_pdfs(session, raw)
            tender["pdf_checks"] = pdf
            tender["pdf_errors"] = pdf_errors
            tender["pdf_count_expected"] = len(raw.get("MichrazDocList") or []) + (1 if raw.get("MichrazFullDocument") else 0)
            tender["pdf_count_verified"] = len(pdf)
            out["tenders"][number] = tender
            old_tender = (old or {}).get("tenders", {}).get(number)
            out["changes"].extend(compare(old_tender, tender, number))
            time.sleep(0.5)
        except Exception as exc:
            out["status"] = "partial"
            out["errors"].append({"part": f"tender:{number}", "type": type(exc).__name__, "message": str(exc)[:400]})
    if not out["tenders"]:
        out["status"] = "failed"
    out["pdf_complete"] = len(out["tenders"]) == len(WATCH) and all(
        t["pdf_count_verified"] == t["pdf_count_expected"] for t in out["tenders"].values())
    if out["status"] == "ok":
        out["verified_coverage"] = "All three named tender detail endpoints and complete RMI search were readable."
    else:
        out["verified_coverage"] = "Partial/failed official access; do not assume missing tender status is unchanged."
    out["changes_count"] = len(out["changes"])
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    STATE.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(json.dumps(out, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    # Do not overwrite latest good data with partial results; failed runs still have downloadable artifacts.
    if out["status"] == "ok":
        STATE.write_text(json.dumps(out, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print("OFFICIAL RMI CHECK", json.dumps({
        "checked_at_utc": checked, "status": out["status"], "search_rows": out.get("search_rows"),
        "tenders": {k: {"submission": v["submission_state"], "next_open": v.get("PtichaDate"), "close": v.get("SgiraDate"), "documents": v.get("document_count")} for k,v in out["tenders"].items()},
        "location_candidates": (out.get("discovery") or {}).get("candidate_count"),
        "changes_count": out["changes_count"], "errors": out["errors"],
    }, ensure_ascii=False))
    return 0 if out["status"] == "ok" else 1

if __name__ == "__main__":
    sys.exit(main())
