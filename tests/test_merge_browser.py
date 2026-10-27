import unittest
from scripts.merge_browser import merge

class BrowserMergeTests(unittest.TestCase):
 def snapshot(self):
  return {"tenders":{"470/2025":{"MichrazID":20250470}},
          "changes":[],"notes":[]}
 def valid(self,state="official_page_explicitly_not_open"):
  return {"results":[{"number":"470/2025","official_url":"https://apps.land.gov.il/MichrazimSite/#/michraz/20250470",
           "browser_timezone":"Asia/Jerusalem","body_has_tender_number":True,
           "http_status":200,"errors":[],"readiness":state,
           "negative_message_visible":state=="official_page_explicitly_not_open",
           "visible_links":[]}]}
 def test_not_open_message_is_saved(self):
  x=merge(self.snapshot(),self.valid(),None)
  self.assertTrue(x["browser_coverage_complete"])
  self.assertEqual(x["tenders"]["470/2025"]["browser_form_state"],"official_page_explicitly_not_open")
 def test_unavailable_or_wrong_host_never_claims_open(self):
  bad=self.valid("visible_enabled_submission_entry_requires_manual_form_confirmation")
  bad["results"][0]["official_url"]="https://other.example.com/fake"
  x=merge(self.snapshot(),bad,None)
  self.assertEqual(x["tenders"]["470/2025"]["browser_form_state"],"unverified")
  self.assertFalse(x["browser_coverage_complete"])
 def test_future_positive_ui_flags_manual_confirmation(self):
  x=merge(self.snapshot(),self.valid("visible_enabled_submission_entry_requires_manual_form_confirmation"),None)
  self.assertEqual(x["changes_count"],0)
  self.assertTrue(any("verify actual form" in s for s in x["notes"]))
 def test_first_ui_baseline_does_not_create_change(self):
  x=merge(self.snapshot(),self.valid(),{"tenders":{"470/2025":{}}})
  self.assertEqual(x["changes_count"],0)
 def test_page_status_change_is_detected(self):
  prev={"tenders":{"470/2025":{"browser_checked_official_page":True,
             "browser_form_state":"official_page_explicitly_not_open"}}}
  x=merge(self.snapshot(),self.valid("visible_enabled_submission_entry_requires_manual_form_confirmation"),prev)
  self.assertTrue(any(e.get("field")=="official_browser_form_state" for e in x["changes"]))
if __name__=="__main__":
 unittest.main()
