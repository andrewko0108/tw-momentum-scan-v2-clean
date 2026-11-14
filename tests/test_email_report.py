"""Email report formatting and safety tests. No real SMTP email is sent."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import email_report


class TestEmailReport(unittest.TestCase):
    def _metadata(self, coverage="full-market coverage checks passed"):
        return {
            "as_of": "2026-11-13",
            "execution": "2026-11-13",
            "coverage": coverage,
            "counts": {"watchlist": 12, "added": 3, "removed": 1, "continuous": 6},
            "etf": {"status": "unavailable"},
        }

    def test_prepared_mail_has_subject_body_and_html_attachment(self):
        html = "<!DOCTYPE html><html><body>一、觀察清單 二、新增、剔除清單 三、連續收益</body></html>"
        message = email_report.prepare_message(
            "andrewko0108@gmail.com",
            "andrewko0108@gmail.com",
            html,
            "# 當日觀察清單",
            self._metadata(),
        )
        self.assertIn("2026-11-13", message["Subject"])
        self.assertEqual(message["To"], "andrewko0108@gmail.com")
        attachments = list(message.iter_attachments())
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0].get_filename(), "momentum-report.html")
        self.assertIn("一、觀察清單", attachments[0].get_content())

    def test_rejects_partial_market_coverage_before_smtp(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p/"report.html").write_text(
                "<html>一、觀察清單 二、新增、剔除清單 三、連續收益</html>", encoding="utf-8")
            (p/"report.md").write_text("# 今日觀察清單", encoding="utf-8")
            (p/"metadata.json").write_text(
                json.dumps(self._metadata("offline sample")), encoding="utf-8")
            with patch.object(email_report.smtplib, "SMTP_SSL") as smtp:
                with self.assertRaisesRegex(RuntimeError, "verified full-market"):
                    email_report.send_report(
                        p/"report.html", p/"metadata.json", p/"report.md",
                        sender="andrewko0108@gmail.com",
                        password="dummy-app-password",
                        recipient="andrewko0108@gmail.com")
                smtp.assert_not_called()

    def test_no_report_does_not_send(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            with patch("sys.argv", ["email_report.py",
                                    "--report", str(p/"report.html"),
                                    "--metadata", str(p/"metadata.json"),
                                    "--markdown", str(p/"report.md")]):
                with patch.object(email_report.smtplib, "SMTP_SSL") as smtp:
                    self.assertEqual(email_report.main(), 0)
                    smtp.assert_not_called()


if __name__ == "__main__":
    unittest.main()
