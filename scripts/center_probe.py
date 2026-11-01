"""Read-only official RMI verification of potential central-Israel self-build tenders.

A third-party lead is only a search clue. Each result is accepted only if the
official apps.land.gov.il API returns the exact tender identity. No open-for-
submission claim is inferred from API success or a listed opening date.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
import requests
from monitor import API, BASE, ROOT, official_request, parse_api, flatten_search, tender_id, normalize_tender

LEADS = {
    "35/2026": "כפר סירקין",
    "153/2025": "בית עובד",
    "188/2026": "אבן יהודה",
    "82/2026": "רעננה",
    "155/2025": "משמר איילון",
    "146/2025": "משמר איילון",
    "183/2025": "גנות",
    "218/2025": "כפר מונש",
    "219/2025": "כפר מונש",
    "138/2025": "מבוא מודיעים",
    "99/2026": "נחלה",
}
OUT = Path("state/center-opportunities.json")
FIELDS = (
    "MichrazID", "MichrazName", "KodYeshuv", "Shchuna", "KodYeudMichraz",
    "PirsumDate", "PtichaDate", "SgiraDate", "PublishedChoveret",
    "YechidotDiur", "Mismach", "StatusMichraz", "StatusMichrazMurchav",
)
def main():
    ses = requests.Session()
    ses.headers.update({"User-Agent":"RMI-Tender-Monitor/1.0 (read-only)", "Origin":ROOT, "Referer":BASE})
    out = {"checked_at_utc":datetime.now(timezone.utc).isoformat(),
           "source_host":"apps.land.gov.il","status":"ok","tenders":{}, "errors":[],
           "warning":"City names are leads, not verified. Exact tender ID and original RMI documents determine location and status. API or a date alone does not establish that a submission form is open."}
    try:
        rows = flatten_search(parse_api(official_request(ses,"POST",API+"SearchApi/Search",
                                 json={"ActiveQuickSearch":False,"ActiveMichraz":False})))
        byid = {row.get("MichrazID"):row for row in rows if isinstance(row,dict)}
    except Exception as exc:
        out["status"]="partial"
        out["errors"].append({"part":"search","error":f"{type(exc).__name__}: {str(exc)[:300]}"})
        byid = {}
    for number, lead in LEADS.items():
        try:
            raw = parse_api(official_request(ses,"GET",API+"MichrazDetailsApi/Get",
                                params={"michrazID":tender_id(number)}))
            if not isinstance(raw,dict):
                raise ValueError("Not an RMI details object")
            t=normalize_tender(raw, number, lead)
            idx=byid.get(tender_id(number)) or {}
            out["tenders"][number]={
                "lead_location_unverified":lead,
                "official_url":t["official_url"],
                "official_detail_confirmed":True,
                "search_index_fields":{k:idx.get(k) for k in FIELDS},
                "details":{k:t.get(k) for k in (
                     "MichrazID","MichrazName","PirsumDate","PtichaDate","SgiraDate",
                     "KodYeshuv","Shchuna","KodYeudMichraz","YechidotDiur",
                     "MechirSafMichraz","SchumArvut","Uchlusiyot","KhalYaadRashi",
                     "StatusMichraz","StatusMichrazMurchav","ReadyForHagasha",
                     "HagashaMekuvenet","official_message","submission_state",
                     "documents","document_count","MichrazFullDocument"
                     )},
                "published_full_document_metadata_present":bool(raw.get("MichrazFullDocument")),
                "warning":"Documents are metadata only. Browser submission form and PDF content not verified in this probe."
            }
        except Exception as exc:
            out["status"]="partial"
            out["errors"].append({"part":number,"error":f"{type(exc).__name__}: {str(exc)[:300]}"})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("Official central tender probe",out["status"],"confirmed identities",len(out["tenders"]),"errors",len(out["errors"]))
    return 0 if out["status"]=="ok" else 1
if __name__=="__main__":
    raise SystemExit(main())
