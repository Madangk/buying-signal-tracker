"""Run with:  python -m unittest discover tests"""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from signal_tracker.cli import main
from signal_tracker.report import slack_message
from signal_tracker.scoring import Scorer
from signal_tracker.sources import Job, get_jobs

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "examples" / "demo"
CONFIG = json.loads((ROOT / "config" / "signals.json").read_text())
TODAY = datetime(2026, 11, 15, tzinfo=timezone.utc)


def job(title, days_ago=5, dept=""):
    return Job("Acme", title, dept, "Bengaluru", "https://example.com", TODAY - timedelta(days=days_ago))


class TestMatching(unittest.TestCase):
    def setUp(self):
        self.s = Scorer(CONFIG, today=TODAY)

    def test_matches_data_role(self):
        m = self.s.match(job("Data Engineer"))
        self.assertEqual(m.signal, "Data platform hiring")
        self.assertEqual(m.score, 3)

    def test_seniority_boost(self):
        self.assertEqual(self.s.match(job("Senior Data Engineer")).score, 4.5)

    def test_highest_weight_signal_wins(self):
        m = self.s.match(job("Head of Data Engineering"))
        self.assertEqual(m.signal, "Data leadership hire")

    def test_irrelevant_role_ignored(self):
        self.assertIsNone(self.s.match(job("Account Executive")))

    def test_whole_words_only(self):
        # "etl" must not match inside "Netlify"; "sre" only as its own word
        self.assertIsNone(self.s.match(job("Netlify Support Specialist")))
        self.assertIsNotNone(self.s.match(job("SRE")))
        self.assertIsNotNone(self.s.match(job("ETL Developer")))

    def test_old_roles_ignored(self):
        self.assertIsNone(self.s.match(job("Data Engineer", days_ago=90)))

    def test_status_thresholds(self):
        hot = self.s.score_account("A", [job("Head of Data"), job("Senior Data Engineer"), job("Senior Data Engineer")])
        self.assertEqual(hot.status, "Hot")  # 7.5 + 4.5 + 4.5 = 16.5
        cold = self.s.score_account("B", [job("DevOps Engineer")])
        self.assertEqual(cold.status, "Cold")


class TestSources(unittest.TestCase):
    def test_each_job_board_format_parses(self):
        for name, source, token in [("Northwind Payments", "greenhouse", "northwindpayments"),
                                    ("Bluepeak Lending", "lever", "bluepeaklending"),
                                    ("Kestrel Commerce", "ashby", "kestrelcommerce")]:
            jobs = get_jobs(name, source, token, demo_dir=DEMO)
            self.assertTrue(jobs, source)
            self.assertTrue(all(j.title and j.url and j.posted_at for j in jobs), source)


class TestEndToEnd(unittest.TestCase):
    def test_demo_run_writes_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(main(["--demo", "--out", tmp]), 0)
            report = (Path(tmp) / "report.md").read_text()
            self.assertIn("Northwind Payments", report)
            self.assertIn("1 hot", report)
            self.assertTrue((Path(tmp) / "signals.csv").exists())

    def test_slack_message_lists_hot_accounts(self):
        s = Scorer(CONFIG, today=TODAY)
        r = s.score_account("Acme", [job("Head of Data"), job("Senior Data Engineer"), job("Senior Data Engineer")])
        self.assertIn("Acme", slack_message([r]))


if __name__ == "__main__":
    unittest.main()
