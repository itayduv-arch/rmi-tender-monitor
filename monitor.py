#!/usr/bin/env python3
"""Daily, read-only RMI API monitoring. Only apps.land.gov.il is an authority."""
from __future__ import annotations
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
import requests

ROOT = "https://apps.land.gov.il"
BASE = ROOT + "/MichrazimSite/"
API = BASE + "api/"
WATCH = {"470/2025": "הוד השרון", "182/2025": "גנות", "149/2025": "צופית"}
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
LAST_RUN_REPORT_VERSION = 2

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

def compare(previous: dict | None, current: dict, label: str) -> list[dict]:
    if previous is None:
        return []  # First successful observation establishes a baseline, not a change event.
    changed = []
    for key in sorted(set(previous) | set(current)):
        if key in ("fingerprint", "official_url", "location_label"):
            continue
        if previous.get(key) != current.get(key):
            if key == "documents":
                before = {str(d.get("RowID")): d for d in previous.get("documents", [])}
                after = {str(d.get("RowID")): d for d in current.get("documents", [])}
                changed.append({"tender": label, "field": "documents", "added": [v for k, v in after.items() if k not in before], "removed": [v for k, v in before.items() if k not in after], "modified": [after[k] for k in after.keys() & before.keys() if after[k] != before[k]]})
            elif key not in ("document_count",):
                changed.append({"tender": label, "field": key, "previous": previous.get(key), "current": current.get(key)})
    return changed

def discover(items: list[dict], prev: dict | None) -> dict:
    # Codes and neighborhood strings are only candidate discovery clues, never proof of a new tender.
    # 587 is the settlement code for Savyon; verify every candidate via official tender details.
    candidates = {"סביון": [], "כפר אז״ר": []}
    for row in items:
        t = row.get("KodYeudMichraz")
        if t not in (1, 2):  # residential low-rise / dense; confirm purpose via detail API
            continue
        name = str(row.get("Shchuna") or "").replace('"', "").replace("״", "").replace("׳", "")
        # Exclude misleading names such as "צומת סביון" in a different municipality.
        if row.get("KodYeshuv") == 587:
            candidates["סביון"].append(row)
        if "כפר אז" in name or "כפר-אז" in name:
            candidates["כפר אז״ר"].append(row)
    selected: dict[str, list[dict]] = {}
    for city, records in candidates.items():
        latest = sorted(records, key=lambda x: str(x.get("PirsumDate") or ""), reverse=True)[:25]
        selected[city] = [{k: rec.get(k) for k in ("MichrazID", "MichrazName", "Shchuna", "KodYeshuv", "KodYeudMichraz", "PirsumDate", "SgiraDate", "PublishedChoveret")} for rec in latest]
    return {"candidates": selected,
            "coverage_warning": "Kfar Azar may not be named in the neighborhood field: absence is NOT proof no tender exists. Candidate list is not an eligibility check.",
            "candidate_count": {k: len(v) for k, v in candidates.items()}}

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
            if old is not None:
                for item in candidates:
                    if item["MichrazID"] not in before_ids:
                        out["changes"].append({"tender": item.get("MichrazName"), "city": city, "field": "new_location_candidate", "official_candidate": item})
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
            out["tenders"][number] = tender
            old_tender = (old or {}).get("tenders", {}).get(number)
            out["changes"].extend(compare(old_tender, tender, number))
            time.sleep(0.5)
        except Exception as exc:
            out["status"] = "partial"
            out["errors"].append({"part": f"tender:{number}", "type": type(exc).__name__, "message": str(exc)[:400]})
    if not out["tenders"]:
        out["status"] = "failed"
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
