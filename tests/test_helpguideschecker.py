import tempfile
import unittest
from pathlib import Path

from helpguideschecker import _safe_filename, compare_sites, crawl_site, write_markdown_reports


class CrawlAndCompareTests(unittest.TestCase):
    def test_compare_detects_missing_path_and_terms(self):
        help_pages = {
            "https://help.example.com/surveys": {"surveys", "questions", "create"},
        }
        app_pages = {
            "https://app.example.com/surveys": {"surveys", "questions"},
            "https://app.example.com/workflows": {"workflows", "automation"},
        }

        missing = compare_sites(app_pages, help_pages)

        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0]["app_url"], "https://app.example.com/workflows")
        self.assertTrue(missing[0]["path_missing"])
        self.assertIn("workflows", missing[0]["missing_feature_terms"])
        self.assertIn("automation", missing[0]["missing_feature_terms"])
        self.assertIn("workflows", missing[0]["missing_terms"])

    def test_compare_detects_missing_features_when_path_exists(self):
        help_pages = {
            "https://help.example.com/surveys": {"surveys", "questions", "create"},
        }
        app_pages = {
            "https://app.example.com/surveys": {"surveys", "questions", "logic"},
        }

        missing = compare_sites(app_pages, help_pages)

        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0]["app_url"], "https://app.example.com/surveys")
        self.assertFalse(missing[0]["path_missing"])
        self.assertEqual(missing[0]["missing_feature_terms"], ["logic"])
        self.assertEqual(missing[0]["missing_terms"], ["logic"])
        self.assertNotIn("create", missing[0]["missing_feature_terms"])

    def test_crawl_same_domain_only(self):
        pages = {
            "https://app.example.com": '<a href="/surveys">Surveys</a><a href="https://other.example.com/x">x</a>',
            "https://app.example.com/surveys": "<title>Survey builder</title><h1>Create survey</h1>",
        }

        crawled = crawl_site(
            "https://app.example.com",
            max_pages=10,
            fetcher=lambda url: pages.get(url, ""),
        )

        self.assertIn("https://app.example.com", crawled)
        self.assertIn("https://app.example.com/surveys", crawled)
        self.assertEqual(len(crawled), 2)
        self.assertNotIn("https://other.example.com/x", crawled)

    def test_write_markdown_reports_creates_expected_files_with_content(self):
        missing_details = [
            {
                "app_url": "https://app.example.com/workflows",
                "path_missing": True,
                "missing_feature_terms": ["workflows", "automation"],
                "missing_terms": ["workflows", "automation"],
            }
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            write_markdown_reports(missing_details, Path(temp_dir))
            summary = Path(temp_dir) / "summary.md"
            detail = Path(temp_dir) / _safe_filename("https://app.example.com/workflows")

            self.assertTrue(summary.exists())
            self.assertTrue(detail.exists())
            self.assertIn("Missing Help Guide Details", summary.read_text(encoding="utf-8"))
            self.assertIn(
                "Potentially undocumented features on this page",
                detail.read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
