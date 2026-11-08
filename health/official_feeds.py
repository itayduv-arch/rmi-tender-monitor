#!/usr/bin/env python3
"""Independent official publication feeds; a readable RSS is not exhaustive notice coverage."""
import json, re
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET
import requests

OUT=Path(__file__).resolve().parent/'state'/'official_feeds.json'
OUT.parent.mkdir(exist_ok=True)
s=requests.Session()
s.headers.update({'User-Agent':'Mozilla/5.0 (compatible; HealthAccessMonitor/1.0)','Accept':'application/rss+xml, application/xml, application/json, */*'})
RSS={
 'moh_publications':'https://www.gov.il/he/api/PublicationApi/rss/104cb0f4-d65a-4692-b590-94af928c19c0',
}
TERMS=('כירורגיה בינונית','מרפאה כירורגית','מרפאות כירורגיות','עמדות ניתוח','ועדת פרויקטים','ועדת הקצאה','אישור הקמה','הרדמה כללית')
rpt={'checked_at_utc':datetime.now(timezone.utc).isoformat(),'feeds':{},'open_data':{},'coverage_complete':False,'actionable_notices_verified':[],'notes':['RSS and open-data metadata are discovery channels, not substitutes for signed current licence or tender submission documents.']}
for label,url in RSS.items():
 d={'url':url,'official_origin':True,'feed_parsed':False,'matching_items':[]}
 try:
  r=s.get(url,timeout=30)
  d['status']=r.status_code
  d['content_type']=r.headers.get('content-type','')
  if r.status_code==200 and len(r.content)<5_000_000:
   root=ET.fromstring(r.content)
   nodes=root.findall('.//item')
   if not nodes:
    nodes=root.findall('.//{http://www.w3.org/2005/Atom}entry')
   d['feed_parsed']=True
   d['item_count']=len(nodes)
   d['first_titles']=[]
   def tx(node,name):
    el=node.find(name)
    return ''.join(el.itertext()).strip() if el is not None else ''
   for n in nodes[:120]:
    title=tx(n,'title') or tx(n,'{http://www.w3.org/2005/Atom}title')
    desc=tx(n,'description') or tx(n,'{http://www.w3.org/2005/Atom}summary')
    link=tx(n,'link')
    if not link:
     a=n.find('{http://www.w3.org/2005/Atom}link')
     link=a.attrib.get('href','') if a is not None else ''
    date=tx(n,'pubDate') or tx(n,'{http://www.w3.org/2005/Atom}updated')
    if len(d['first_titles'])<8: d['first_titles'].append(title[:180])
    hits=[term for term in TERMS if term in title+' '+re.sub('<[^>]+>',' ',desc)]
    if hits:
     d['matching_items'].append({'title':title[:280],'link':link,'published':date,'keywords':hits})
 except Exception as e:
  d['error']=type(e).__name__+': '+str(e)[:220]
 rpt['feeds'][label]=d

# Official CKAN package discovery is a secondary sanity check, NOT a real-time tender publication list.
api='https://data.gov.il/api/3/action/package_search'
rpt['open_data']['endpoint']=api
try:
 r=s.get(api,params={'q':'מכרזים','rows':25},timeout=25,headers={'Accept':'application/json'})
 rpt['open_data']['status']=r.status_code
 if r.status_code==200 and 'json' in r.headers.get('Content-Type','').lower():
  j=r.json()
  rpt['open_data']['success']=j.get('success')
  found=j.get('result',{}).get('results',[])
  rpt['open_data']['candidate_datasets']=[{'id':p.get('id'),'name':p.get('name'),'title':p.get('title'),'modified':p.get('metadata_modified')} for p in found[:15]]
 else:rpt['open_data']['error']='no readable official JSON response'
except Exception as e:
 rpt['open_data']['error']=type(e).__name__+': '+str(e)[:180]

# Flag relevant leads only as candidates; the automation still must open the official tender document.
rpt['discovery_candidates']=[{'source':k,**x} for k,v in rpt['feeds'].items() for x in v.get('matching_items',[])]
OUT.write_text(json.dumps(rpt,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({'checked_at_utc':rpt['checked_at_utc'],'feed_status':{k:(v.get('status'),v.get('feed_parsed'),v.get('item_count'),len(v.get('matching_items',[]))) for k,v in rpt['feeds'].items()},'ckan_status':rpt['open_data'].get('status'),'discovery_candidates':len(rpt['discovery_candidates']),'coverage_complete':rpt['coverage_complete']},ensure_ascii=False))
