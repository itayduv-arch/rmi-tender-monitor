#!/usr/bin/env python3
"""Preserve the latest *verified* official northern surgical tender PDF text.

Reads only the output from health/probe.py, which retrieves the ministry PDF and
publication page directly. Never treats a 403 response as proof that no tender exists.
A last-good snapshot is preserved when official sources become unavailable.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "state"
LATEST = ROOT / "latest.json"
STATUS = ROOT / "northern_tender_status.json"
SNAPSHOT = ROOT / "northern_tender_last_verified.json"


def read_json(path: Path) -> dict:
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
        return result if isinstance(result, dict) else {}
    except (FileNotFoundError, ValueError, OSError):
        return {}


def write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    report = read_json(LATEST)
    http = report.get("http") or {}
    browser = report.get("browser") or {}
    pdf = http.get("northern_competitive_procedure_pdf") or {}
    page = http.get("northern_competitive_procedure_page") or {}
    browser_page = browser.get("northern_competitive_procedure_page") or {}
    prev = read_json(SNAPSHOT)
    text_pages = pdf.get("extracted_text_by_page") or []
    text_length = sum(len(p.get("text", "")) for p in text_pages if isinstance(p, dict))
    valid_pdf = (
        pdf.get("status") == 200
        and pdf.get("is_pdf") is True
        and isinstance(pdf.get("sha256"), str)
        and pdf.get("pages", 0) >= 1
        and len(text_pages) == pdf.get("pages")
        and text_length > 2500
    )
    changed = (
        valid_pdf
        and bool(prev.get("sha256"))
        and prev["sha256"] != pdf.get("sha256")
    )
    first_saved = valid_pdf and not prev.get("sha256")
    if valid_pdf and (changed or first_saved):
        write_json(
            SNAPSHOT,
            {
                "verified_at_utc": report.get("checked_at_utc"),
                "official_pdf_url": pdf.get("url"),
                "sha256": pdf["sha256"],
                "pages": pdf["pages"],
                "text_length": text_length,
                "text_by_page": text_pages,
                "note": (
                    "Extracted from the Ministry of Health PDF. This is a dated "
                    "snapshot, NOT evidence that tender deadlines or terms are unchanged."
                ),
            },
        )
        prev = read_json(SNAPSHOT)

    http_ok = page.get("status") == 200
    browser_ok = browser_page.get("browser_document_status") == 200
    new_links = browser_page.get("page_relevant_links", []) if browser_ok else []
    state = {
        "checked_at_utc": report.get("checked_at_utc") or datetime.now(timezone.utc).isoformat(),
        "official_publication_url": page.get("url"),
        "publication_http_status": page.get("status"),
        "publication_browser_status": browser_page.get("browser_document_status"),
        "publication_page_accessible": bool(http_ok or browser_ok),
        "publication_page_links_verified": bool(browser_ok),
        "publication_page_candidate_links": new_links,
        "official_pdf_url": pdf.get("url"),
        "pdf_http_status": pdf.get("status"),
        "pdf_accessible_and_parsed": bool(valid_pdf),
        "pdf_current_sha256": pdf.get("sha256") if valid_pdf else None,
        "pdf_version_changed_since_last_success": bool(changed),
        "first_successful_snapshot_created": bool(first_saved),
        "last_verified_pdf_sha256": prev.get("sha256"),
        "last_verified_pdf_at_utc": prev.get("verified_at_utc"),
        "last_verified_pdf_pages": prev.get("pages"),
        "last_verified_snapshot_path": "health/state/northern_tender_last_verified.json",
        "coverage_complete": bool((http_ok or browser_ok) and valid_pdf),
        "source_page_cannot_be_checked_for_amendments": not (http_ok or browser_ok),
        "action_needed": (
            "Review changed official PDF and any amended deadlines/conditions"
            if changed else
            "Official publication page is blocked; check indexed notices and amendments separately"
            if not (http_ok or browser_ok) else
            "Review publication links for amended documents"
            if new_links else
            "No local content hash change detected in the currently monitored PDF"
        ),
        "warning": (
            "PDF inaccessible. Historical last-success copy retained, never treat it as current."
            if not valid_pdf else
            "Publication HTML blocked. New amendments on that page cannot be ruled out."
            if not (http_ok or browser_ok) else None
        ),
    }
    write_json(STATUS, state)
    print(json.dumps(
        {
            "page_status": state["publication_http_status"],
            "pdf_verified": valid_pdf,
            "pdf_changed": bool(changed),
            "snapshot_date": prev.get("verified_at_utc"),
            "coverage_complete": state["coverage_complete"],
            "warning": state["warning"],
        },
        ensure_ascii=False,
    ))


if __name__ == "__main__":
    main()
