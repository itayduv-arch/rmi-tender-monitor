#!/usr/bin/env python3
"""Read-only connectivity probe for the official Israel Land Authority tender API.

This is an API access pilot, NOT a declaration that any tender is open.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

BASE = "https://apps.land.gov.il/MichrazimSite/"
API = BASE + "api/"
TENDER = os.environ.get("TENDER_NUMBER", "470/2025")
OUTPUT = Path("reports/last-check.json")
TIMEOUT = 35
ALLOWED_HOST = "apps.land.gov.il"


def verify_origin(response: requests.Response) -> None:
    if urlparse(response.url).hostname != ALLOWED_HOST:
        raise RuntimeError(f"Unexpected redirect outside official host: {response.url}")


def preview(value: object, limit: int = 80000) -> dict:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return {"data": serialized[:limit], "truncated": len(serialized) > limit}


def extract_items(obj: object) -> list:
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        for key in ("results", "Results", "data", "Data", "items", "Items", "Michrazim", "michrazim"):
            child = obj.get(key)
            if isinstance(child, list):
                return child
        # Other wrappers are possible; do not fabricate a count.
    return []


def find_id(item: dict) -> int | None:
    for key in ("MichrazID", "michrazID", "MichrazId", "michrazId", "MICHRAZID"):
        val = item.get(key)
        if isinstance(val, (str, int)) and str(val).isdigit():
            return int(val)
    return None


def main() -> int:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    result = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "official_host": ALLOWED_HOST,
        "tender_number_requested": TENDER,
        "verified_open_for_submission": None,
        "status": "not_checked",
        "notes": ["A matching search result or future deadline is NOT proof that submissions are open."],
    }
    exit_code = 0
    try:
        session = requests.Session()
        session.headers.update({
            "User-Agent": "RMI-Tender-Monitor/0.1 (read-only research)",
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://apps.land.gov.il",
            "Referer": BASE,
        })
        homepage = session.get(BASE, timeout=TIMEOUT)
        verify_origin(homepage)
        result["homepage_http_code"] = homepage.status_code
        homepage.raise_for_status()

        # RMI IDs in search results use YYYYNNNN (e.g. 300/2022 -> 20220300).
        # Try the tender detail endpoint directly, even if SearchApi ignores filters.
        tender_part, year_part = TENDER.split("/")
        internal_id = int(year_part + str(int(tender_part)).zfill(4))
        result["direct_details_requested_id"] = internal_id
        try:
            direct = session.get(
                API + "MichrazDetailsApi/Get",
                params={"michrazID": internal_id},
                timeout=TIMEOUT,
            )
            verify_origin(direct)
            result["direct_details_http_code"] = direct.status_code
            if direct.ok:
                direct_data = direct.json()
                result["official_direct_details_preview"] = preview(direct_data)
                result["direct_details_response_type"] = type(direct_data).__name__
                if isinstance(direct_data, dict):
                    result["direct_details_keys"] = list(direct_data)[:50]
                result["status"] = "official_api_direct_details_reachable"
        except (requests.RequestException, ValueError) as err:
            result["direct_details_note"] = f"{type(err).__name__}: {str(err)[:500]}"

        payload = {
            "MisMichraz": TENDER,
            "ActiveQuickSearch": False,
            "ActiveMichraz": False,
        }
        response = session.post(API + "SearchApi/Search", json=payload, timeout=TIMEOUT)
        verify_origin(response)
        result["api_http_code"] = response.status_code
        response.raise_for_status()
        raw = response.json()  # Fail clearly if HTML challenge/login is returned.
        result["api_reachable"] = True
        result["response_shape"] = type(raw).__name__
        if isinstance(raw, dict):
            result["response_keys"] = list(raw)[:40]
        result["official_response_preview"] = preview(raw)
        records = extract_items(raw)
        result["records_detected"] = len(records) if isinstance(raw, list) or records else None

        matching = [
            rec for rec in records if isinstance(rec, dict)
            and TENDER in json.dumps(rec, ensure_ascii=False, default=str)
        ]
        result["matching_record_count"] = len(matching)
        if result["status"] == "not_checked":
            result["status"] = "official_api_reachable"
        if matching:
            tender_id = find_id(matching[0])
            if tender_id is not None:
                result["tender_internal_id"] = tender_id
                details = session.get(
                    API + "MichrazDetailsApi/Get",
                    params={"michrazID": tender_id},
                    timeout=TIMEOUT,
                )
                verify_origin(details)
                result["details_http_code"] = details.status_code
                if details.ok:
                    result["official_details_preview"] = preview(details.json())
                    result["status"] = "official_api_details_reachable"
                else:
                    result["notes"].append("Search succeeded, details did not. Investigate status code.")

        result["notes"].append(
            "Submission status is UNVERIFIED until the official form or official eligibility/announcements are checked."
        )
    except Exception as exc:
        exit_code = 1
        result["status"] = "access_error"
        result["error_type"] = type(exc).__name__
        result["error"] = str(exc)[:1000]
        result["notes"].append("No conclusion about tender opening or change can be drawn from a failed check.")
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Tender: {TENDER}; status: {result['status']}; official API reachable: {result.get('api_reachable', False)}")
    print(f"Report saved to {OUTPUT}")
    if result.get("error"):
        print(f"Problem: {result['error']}", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
