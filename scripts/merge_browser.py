"""Merge verified read-only official browser evidence into the daily tender snapshot."""
from __future__ import annotations
import json
import subprocess
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlparse

STATE=Path("state/latest.json")
RESULT=Path("reports/latest-run.json")
FORM=Path("reports/browser-forms.json")
VALID_STATES={
 "official_page_explicitly_not_open",
 "visible_enabled_submission_entry_requires_manual_form_confirmation",
 "unverified",
}

def merge(snapshot:dict, form_result:dict|None, previous:dict|None)->dict:
    checked_at=datetime.now(timezone.utc).isoformat()
    checked=set()
    if isinstance(form_result,dict):
        for row in form_result.get("results",[]):
            number=row.get("number")
            tender=snapshot.get("tenders",{}).get(number)
            if tender is None or number in checked:
                continue
            checked.add(number)
            expected=f"https://apps.land.gov.il/MichrazimSite/#/michraz/{tender['MichrazID']}"
            source=row.get("official_url","")
            valid=(source==expected and urlparse(source).hostname=="apps.land.gov.il" and
                   row.get("browser_timezone")=="Asia/Jerusalem" and
                   row.get("body_has_tender_number") is True and
                   row.get("http_status")==200 and not row.get("errors"))
            state=row.get("readiness") if valid and row.get("readiness") in VALID_STATES else "unverified"
            tender["browser_form_state"]=state
            tender["browser_checked_at_utc"]=checked_at
            tender["browser_checked_official_page"]=bool(valid)
            tender["browser_negative_message_visible"]=row.get("negative_message_visible") if valid else None
            tender["browser_visible_links"]=row.get("visible_links",[])[:12] if valid else []
            if state=="visible_enabled_submission_entry_requires_manual_form_confirmation":
                snapshot["notes"].append(f"Potential enabled submission entry for {number} visible in official browser; verify actual form before claiming open.")
            old=(previous or {}).get("tenders",{}).get(number,{})
            if old.get("browser_checked_official_page") and old.get("browser_form_state")!=state and valid:
                snapshot["changes"].append({"tender":number,"field":"official_browser_form_state",
                                           "previous":old.get("browser_form_state"),"current":state,
                                           "official_url":source})
    count=sum(v.get("browser_checked_official_page",False) for v in snapshot.get("tenders",{}).values())
    snapshot["browser_coverage_verified"]=count
    snapshot["browser_coverage_expected"]=len(snapshot.get("tenders",{}))
    snapshot["browser_coverage_complete"]=count==snapshot["browser_coverage_expected"]
    if not snapshot["browser_coverage_complete"]:
        snapshot["notes"].append("Official browser check incomplete: absence of detected form does not prove tenders are closed.")
    snapshot["changes_count"]=len(snapshot.get("changes",[]))
    return snapshot

def main():
    current=json.loads(STATE.read_text(encoding="utf-8"))
    old=None
    try:
        prior=subprocess.check_output(["git","show","HEAD:state/latest.json"],text=True,stderr=subprocess.DEVNULL)
        old=json.loads(prior)
    except (subprocess.CalledProcessError,OSError,ValueError):
        pass
    data=None
    if FORM.exists():
        try:
            data=json.loads(FORM.read_text(encoding="utf-8"))
        except (ValueError,OSError):
            pass
    current=merge(current,data,old)
    STATE.write_text(json.dumps(current,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    RESULT.write_text(json.dumps(current,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("Browser verified",current["browser_coverage_verified"],"/",current["browser_coverage_expected"],
          "form changes",sum(1 for x in current["changes"] if x.get("field")=="official_browser_form_state"))
    # Graceful degraded reporting, so verified API snapshot remains saved.
    return 0

if __name__=="__main__":
    raise SystemExit(main())
