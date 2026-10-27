import unittest
from monitor import tender_id, normalize_tender, compare, discover

class MonitorTests(unittest.TestCase):
    def make(self):
        return {"MichrazID": 20250470, "MichrazName": "470/2025",
                "MessageDetails": {"messageText":"המכרז טרם נפתח להגשת הצעות"},
                "ReadyForHagasha": None, "HagashaMekuvenet": True,
                "MichrazDocList":[{"RowID":135312,"DocName":"הודעת דחייה.pdf","UpdateDate":"2026-10-12T00:00:00+03:00"}]}

    def test_number_to_internal_id(self):
        self.assertEqual(tender_id("470/2025"), 20250470)
        self.assertEqual(tender_id("149/2025"), 20250149)

    def test_not_open_from_rmi_message(self):
        obj = normalize_tender(self.make(),"470/2025","הוד השרון")
        self.assertEqual(obj["submission_state"],"not_open_according_to_official_message")
        self.assertEqual(obj["document_count"],1)

    def test_api_success_not_equivalent_to_open(self):
        obj=self.make()
        obj["MessageDetails"]={"messageText":"אין הודעה"}
        self.assertEqual(normalize_tender(obj,"470/2025","הוד השרון")["submission_state"],"unverified")

    def test_new_docs_are_reported(self):
        before = normalize_tender(self.make(),"470/2025","הוד השרון")
        after_data=self.make()
        after_data["MichrazDocList"].append({"RowID":135400,"DocName":"חוברת המכרז.pdf","UpdateDate":"2026-11-16T00:00:00+02:00"})
        after=normalize_tender(after_data,"470/2025","הוד השרון")
        result=compare(before,after,"470/2025")
        self.assertTrue(any(x["field"]=="documents" and x["added"][0]["RowID"]==135400 for x in result))

    def test_first_baseline_is_not_an_alert(self):
        t=normalize_tender(self.make(),"470/2025","הוד השרון")
        self.assertEqual(compare(None,t,"470/2025"),[])

    def test_wrong_tender_refused(self):
        data=self.make()
        with self.assertRaises(ValueError):
            normalize_tender(data,"182/2025","גנות")

    def test_location_discovery_reports_incomplete_coverage(self):
        rows=[{"MichrazID":20260123,"MichrazName":"123/2026","KodYeshuv":587,"KodYeudMichraz":1},
              {"MichrazID":20260456,"MichrazName":"456/2026","KodYeudMichraz":1,"Shchuna":"כפר אז״ר"}]
        x=discover(rows,None)
        self.assertEqual(x["candidate_count"]["סביון"],1)
        self.assertEqual(x["candidate_count"]["כפר אז״ר"],1)
        self.assertIn("NOT proof",x["coverage_warning"])

if __name__ == "__main__":
    unittest.main()
