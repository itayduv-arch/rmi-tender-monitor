"""Read-only Chromium smoke test of official RMI tender pages; never submits any form."""
import asyncio, json, re
from pathlib import Path
from urllib.parse import urlparse
from playwright.async_api import async_playwright

ROOT="https://apps.land.gov.il/MichrazimSite/"
TENDERS={"470/2025":20250470,"182/2025":20250182,"149/2025":20250149}
NEGATIVE=("טרם נפתח", "טרם פורסמה חוברת", "לא ניתן להגיש", "המכרז נסגר")
WORD_RE=re.compile(r"הגשת|להגיש|הרשמה|כניסה למערכת|טופס|הצעה|submit|apply|register",re.I)

async def test_one(browser, num, id_):
    page=await browser.new_page(locale="he-IL", timezone_id="Asia/Jerusalem", viewport={"width":1280,"height":1000}, accept_downloads=False)
    data={"number":num,"official_url":ROOT+f"#/michraz/{id_}", "readiness":"unverified","visible_links":[],"errors":[]}
    api=[]
    def on_response(response):
        if urlparse(response.url).hostname=="apps.land.gov.il" and "/api/" in response.url:
            api.append({"status":response.status,"path":urlparse(response.url).path})
    page.on("response",on_response)
    try:
        res=await page.goto(data["official_url"],wait_until="domcontentloaded",timeout=55000)
        data["http_status"]=res.status if res else None
        await page.wait_for_timeout(9000)
        body=await page.locator("body").inner_text(timeout=18000)
        data["body_excerpt"]=body[:2600]
        data["negative_message_visible"]=any(x in body for x in NEGATIVE)
        data["body_has_tender_number"]=num in body
        data["browser_timezone"]="Asia/Jerusalem"
        controls=await page.locator("a,button,[role='button'],input[type='submit']").all()
        for ctl in controls[:400]:
            try:
                if not await ctl.is_visible(timeout=600):
                    continue
                title=((await ctl.inner_text(timeout=700)) or await ctl.get_attribute("aria-label") or "").strip()
                if not WORD_RE.search(title):
                    continue
                href=await ctl.get_attribute("href")
                is_disabled=await ctl.is_disabled(timeout=700)
                data["visible_links"].append({"text":title[:140], "href":href, "disabled":is_disabled})
            except Exception:
                pass
        if data["negative_message_visible"]:
            data["readiness"]="official_page_explicitly_not_open"
        elif data["body_has_tender_number"] and any(
              (not ctrl["disabled"] and WORD_RE.search(ctrl["text"]) and
               any(q in ctrl["text"] for q in ("הגשת הצעה","להגשת הצעה","הגשת הצעות")))
              for ctrl in data["visible_links"]):
            data["readiness"]="visible_enabled_submission_entry_requires_manual_form_confirmation"
        else:
            data["readiness"]="unverified"
        await page.screenshot(path=f"reports/rmi-{id_}.png",full_page=True,timeout=22000)
    except Exception as ex:
        data["errors"].append(f"{type(ex).__name__}: {str(ex)[:500]}")
    data["official_api_calls"]=api[:45]
    await page.close()
    return data

async def main():
    Path("reports").mkdir(exist_ok=True)
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=True,args=["--disable-dev-shm-usage"])
        results=[]
        for tender,id_ in TENDERS.items():
            results.append(await test_one(browser,tender,id_))
        await browser.close()
    Path("reports/browser-forms.json").write_text(json.dumps({
        "purpose":"Read-only official browser UI verification, never a submission test",
        "results":results,
    },ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    for r in results:
        print(r["number"],r["readiness"],"number_seen=",r.get("body_has_tender_number"),
              "negative=",r.get("negative_message_visible"),"control_matches=",len(r["visible_links"]),
              "errors=",len(r["errors"]))

if __name__=="__main__":
    asyncio.run(main())
