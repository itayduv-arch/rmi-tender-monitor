#!/usr/bin/env python3
"""Diagnostic: try live institution result details instead of assuming index or API list has a current licence."""
import json, re
from datetime import datetime, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright

out={'checked_at_utc':datetime.now(timezone.utc).isoformat(),'source':'official Ministry of Health institutions web interface','candidates':[],'current_certificate_verified':False,'general_anaesthesia_verified':False,'notes':[]}
names=[('53708','מדילי'),('53747','טי.אל.וי'),('53733','שוורץ')]
try:
 with sync_playwright() as p:
  browser=p.chromium.launch(headless=True,args=['--no-sandbox'])
  context=browser.new_context(locale='he-IL',viewport={'width':1380,'height':900})
  page=context.new_page()
  for code,name in names:
   rec={'instituteCode':code,'name_query':name,'detail_readable':False,'licence_certificate_attached':False}
   traffic=[]
   def watch(response):
    if ('registries.health.gov.il/api/' in response.url and len(traffic)<35):
     traffic.append({'method':response.request.method,'status':response.status,'endpoint':response.url.split('?')[0]})
   page.on('response',watch)
   try:
    resp=page.goto('https://registries.health.gov.il/Institutions/Institutions/1',wait_until='domcontentloaded',timeout=45000)
    page.wait_for_timeout(3000)
    rec['list_status']=resp.status if resp else None
    field=page.locator('input[placeholder="הזן שם מוסד"]')
    rec['name_search_available']=field.count()>0
    if field.count():
     field.first.fill(name)
     buttons=page.get_by_role('button',name='חיפוש',exact=True)
     rec['search_button_count']=buttons.count()
     if buttons.count()>0:
      buttons.last.click()
     else:
      field.first.press('Enter')
     page.wait_for_timeout(2600)
     body=page.locator('body').inner_text(timeout=16000)
     rec['search_results_excerpt']=body[:1400]
     rec['name_visible']=name in body
     m=re.search(r'נמצאו\\s*([0-9,]+)\\s*תוצאות',body)
     if m:rec['reported_result_count']=m.group(1)
     btn=page.get_by_role('button',name='למידע נוסף',exact=True)
     rec['more_info_buttons']=btn.count()
     if rec['name_visible'] and btn.count() and btn.count()<=8:
      btn.first.click()
      page.wait_for_timeout(1000)
      more=page.locator('body').inner_text(timeout=10000)
      rec['detail_excerpt']=more[-3800:]
      rec['detail_readable']=True
      rec['detail_url']=page.url
      rec['licence_certificate_attached']=('תעודת רישום' in more and '.pdf' in more.lower())
   except Exception as e:rec['error']=type(e).__name__+': '+str(e)[:240]
   rec['official_api_endpoints_observed']=traffic[:25]
   out['candidates'].append(rec)
  context.close();browser.close()
except Exception as e:out['browser_error']=type(e).__name__+': '+str(e)[:240]
out['notes'].append('A readable record does not prove current intermediate-surgery class, anaesthesia authorisation or sale status.')
path=Path(__file__).resolve().parent/'state'/'registry_details.json'
path.parent.mkdir(exist_ok=True)
path.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({'checked_at_utc':out['checked_at_utc'],'queries':[{k:r.get(k) for k in ('instituteCode','name_visible','reported_result_count','more_info_buttons','detail_readable','licence_certificate_attached','error')} for r in out['candidates']],'current_certificate_verified':out['current_certificate_verified']},ensure_ascii=False,indent=2))
