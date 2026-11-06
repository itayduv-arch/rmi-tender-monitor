#!/usr/bin/env python3
"""Read-only public facility licence cross-check: live registry API + official 2025 PDF."""
import io, json, hashlib
from datetime import datetime,timezone
from pathlib import Path
import requests
from pypdf import PdfReader

base=Path(__file__).resolve().parent
url='https://registries.health.gov.il/api/Institutions/GetInstitutions'
report='https://www.gov.il/BlobFolder/reports/licensed-inpatient-hospital-beds-dec-2025/he/files_publications_units_info_beds2025_dec2025.pdf'
s=requests.Session()
s.headers.update({'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36','Accept':'application/json, text/plain, */*','Content-Type':'application/json','Origin':'https://registries.health.gov.il','Referer':'https://registries.health.gov.il/Institutions/Institutions/1'})
d={'checked_at_utc':datetime.now(timezone.utc).isoformat(),'source':'official Ministry of Health registries API and official 2025 report','api_url':url,'report_url':report,'current_facilities':[],'pdf_matching_pages':[],'notes':[]}
def collect(o,out):
 if isinstance(o,dict):
  if 'instituteCode' in o and 'instituteName' in o:
   out.append(o)
  else:
   for v in o.values():collect(v,out)
 elif isinstance(o,list):
  for v in o:collect(v,out)

try:
 r=s.post(url,json={'maxResult':5000,'pageNumber':0},timeout=80)
 d['api_status']=r.status_code
 obj=r.json()
 d['api_top_keys']=list(obj.keys())[:20] if isinstance(obj,dict) else []
 ret=obj.get('returnObject',{}) if isinstance(obj,dict) else {}
 d['api_return_keys']=list(ret.keys())[:30] if isinstance(ret,dict) else []
 d['api_return_types']={k:type(v).__name__ for k,v in ret.items()} if isinstance(ret,dict) else {}
 data=[];collect(obj,data)
 d['api_received_records']=len(data)
 filtered=[]
 for a in data:
  t=a.get('instituteTypeName','')
  district=a.get('districtName','')
  if 'כירורג' in t and any(v in district for v in ('תל-אביב','מרכז','תל אביב')):
   filtered.append({k:a.get(k) for k in ('instituteCode','instituteName','instituteTypeName','cityName','districtName','fullAddress','startDate','endDate','status','ownershipName')})
 d['current_facilities']=filtered
 d['api_records_from_current_report_at_least_one']=len(filtered)>0
 if len(data)<100:d['notes'].append('Registry may be paginated; low record count needs pagination validation before coverage claim')
except Exception as e:d['api_error']=type(e).__name__+': '+str(e)[:400]

try:
 r=s.get(report,timeout=65)
 d['pdf_status']=r.status_code
 d['pdf_valid']=r.content.startswith(b'%PDF-')
 if d['pdf_valid']:
  pdf=PdfReader(io.BytesIO(r.content))
  d['pdf_pages']=len(pdf.pages)
  d['pdf_sha256']=hashlib.sha256(r.content).hexdigest()
  for i,page in enumerate(pdf.pages):
   t=page.extract_text() or ''
   cues=[w for w in ('כירורגיה בינונית','מרפאות כירורגיות','מדילי','שוורץ','מדיקה','לונגר','רמת אביב','ט.א.י') if w in t]
   if cues:
    d['pdf_matching_pages'].append({'page':i+1,'matched':cues,'excerpt':t[:4500]})
except Exception as e:d['pdf_error']=type(e).__name__+': '+str(e)[:400]

f=base/'state'/'facilities.json'
f.parent.mkdir(exist_ok=True)
f.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({'api_status':d.get('api_status'),'api_records':d.get('api_received_records'),'surgery_central_clinics':len(d.get('current_facilities',[])),'pdf_status':d.get('pdf_status'),'pdf_valid':d.get('pdf_valid'),'pdf_pages':d.get('pdf_pages'),'pdf_matching_pages':[(x['page'],x['matched']) for x in d.get('pdf_matching_pages',[])]},ensure_ascii=False))
