#!/usr/bin/env python3
"""Public, read-only Ministry of Health access diagnostic; not a licence certification."""
import hashlib,io,json,re
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlparse
import requests

URLS={
 'institutions':'https://registries.health.gov.il/Institutions/Institutions/1',
 'registries_home':'https://registries.health.gov.il/Institutions',
 'gov_2025_page':'https://www.gov.il/he/pages/licensed-inpatient-hospital-beds-dec-2025',
 'gov_2024_pdf':'https://www.gov.il/BlobFolder/reports/licensed-inpatient-hospital-beds/he/files_publications_units_info_beds2024_dec2024.pdf',
 'medika_pdf':'https://www.gov.il/BlobFolder/dynamiccollectorresultitem/medika-18092024/he/files_publications_units_general_medicine_medika-18092024.pdf',
 'inspections':'https://www.gov.il/he/departments/dynamiccollectors/inspections-db',
 'tender_portal':'https://mr.gov.il/ilgstorefront/he/search?s=TENDER',
}
s=requests.Session()
s.headers.update({'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36','Accept-Language':'he-IL,he;q=0.9,en-US;q=0.8'})
result={'checked_at_utc':datetime.now(timezone.utc).isoformat(),'source':'github-actions-ubuntu-24.04-read-only','http':{},'browser':{},'verification':{'licence_validity_confirmed':False,'important':'HTTP 200 or rendered HTML is NOT licence-level verification.'}}
for label,url in URLS.items():
 d={'url':url}
 try:
  with s.get(url,timeout=30,allow_redirects=True,stream=True) as r:
   d.update(status=r.status_code,final_url=r.url,content_type=r.headers.get('Content-Type',''))
   body=bytearray()
   for chunk in r.iter_content(65536):
    body.extend(chunk)
    if len(body)>=12*1024*1024: break
   d['bytes_read']=len(body)
   d['is_pdf']=body[:5]==b'%PDF-'
   if d['is_pdf']:
    d['sha256']=hashlib.sha256(body).hexdigest()
    try:
     from pypdf import PdfReader
     pdf=PdfReader(io.BytesIO(body))
     d['pages']=len(pdf.pages)
     txt=' '.join((pdf.pages[i].extract_text() or '') for i in range(min(3,len(pdf.pages))))
     d['extract_chars_first_3_pages']=len(txt)
     d['text_mentions_surgery']=any(w in txt for w in ('כירורגיה','ניתוח','Surgery'))
    except Exception as e:d['pdf_parse_error']=str(e)[:200]
   else:
    html=body.decode('utf-8',errors='replace')
    m=re.search(r'<title[^>]*>(.*?)</title>',html,re.I|re.S)
    d['html_title']=(m.group(1).strip() if m else '')[:130]
    d['has_pdf_link']='.pdf' in html.lower()
    d['has_medili']='מדילי' in html
 except Exception as e:d['error']=type(e).__name__+': '+str(e)[:250]
 result['http'][label]=d
try:
 from playwright.sync_api import sync_playwright
 with sync_playwright() as p:
  browser=p.chromium.launch(headless=True,args=['--no-sandbox'])
  context=browser.new_context(locale='he-IL',viewport={'width':1380,'height':900})
  for label in ('institutions','inspections','gov_2025_page'):
   url=URLS[label]; page=context.new_page(); events=[];d={'url':url}
   def handle_response(r):
    u=r.url
    if len(events)<35 and any(h in urlparse(u).netloc for h in ('health.gov.il','gov.il')) and any(w in u.lower() for w in ('api/','search','get','graphql')):
     events.append({'status':r.status,'url':u.split('?')[0][:250],'type':r.headers.get('content-type','')[:100]})
   page.on('response',handle_response)
   try:
    resp=page.goto(url,wait_until='domcontentloaded',timeout=45000)
    page.wait_for_timeout(7500)
    body=page.locator('body').inner_text(timeout=10000)
    d['browser_document_status']=resp.status if resp else None
    d['page_url']=page.url;d['body_text_length']=len(body);d['body_excerpt']=body[:1100]
    d['input_placeholders']=page.locator('input').evaluate_all('(els)=>els.map(e=>e.placeholder||e.getAttribute("aria-label")||"").filter(Boolean).slice(0,25)')
    d['buttons']=page.locator('button').evaluate_all('(els)=>els.map(e=>e.innerText.trim()).filter(Boolean).slice(0,30)')
    if label=='institutions':
     el=page.locator('input[placeholder*="מוסד"]')
     if el.count():
      el.first.fill('מדילי');el.first.press('Enter');page.wait_for_timeout(5500)
      after=page.locator('body').inner_text(timeout=10000)
      d['after_medili_enter_text_length']=len(after);d['after_medili_excerpt']=after[:1500]
      d['medili_visible']='מדילי' in after
    d['api_requests']=events
   except Exception as e:d['error']=type(e).__name__+': '+str(e)[:250]
   result['browser'][label]=d
   page.close()
  context.close();browser.close()
except Exception as e:result['browser_error']=type(e).__name__+': '+str(e)[:300]
out=Path(__file__).resolve().parent/'state'/'latest.json'
out.parent.mkdir(exist_ok=True)
out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'checked_at_utc':result['checked_at_utc'],'http':{k:(v.get('status'),v.get('is_pdf'),v.get('pages')) for k,v in result['http'].items()},'browser':{k:(v.get('browser_document_status'),v.get('body_text_length'),v.get('medili_visible'),v.get('error')) for k,v in result['browser'].items()}},ensure_ascii=False,indent=2))
