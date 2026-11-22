"""Phase 2 tests: landing page, dashboard, builder entry page, template catalog."""
import unittest
from html.parser import HTMLParser

from app import create_app
from app.services.template_catalog import get_categories, get_category


class LinkCollector(HTMLParser):
    """Collects every href and every element id in a page."""

    def __init__(self):
        super().__init__()
        self.hrefs = []
        self.ids = set()

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "a" and attributes.get("href"):
            self.hrefs.append(attributes["href"])
        if attributes.get("id"):
            self.ids.add(attributes["id"])


def collect(html):
    parser = LinkCollector()
    parser.feed(html)
    return parser


class CatalogTests(unittest.TestCase):
    def test_eight_categories_with_unique_ids(self):
        categories = get_categories()
        self.assertEqual(len(categories), 8)
        self.assertEqual(len({c["id"] for c in categories}), 8)

    def test_lookup_known_and_unknown(self):
        self.assertEqual(get_category("restaurant")["name"], "Restaurant")
        self.assertIsNone(get_category("nope"))
        self.assertIsNone(get_category(""))

    def test_returned_data_is_a_copy(self):
        get_categories()[0]["name"] = "Changed"
        self.assertNotEqual(get_categories()[0]["name"], "Changed")


class PageTests(unittest.TestCase):
    def setUp(self):
        self.client = create_app("testing").test_client()

    def test_landing_has_all_sections(self):
        html = self.client.get("/").get_data(as_text=True)
        page = collect(html)
        for section_id in ("features", "examples", "how-it-works", "main"):
            self.assertIn(section_id, page.ids)

    def test_landing_links_all_resolve(self):
        html = self.client.get("/").get_data(as_text=True)
        page = collect(html)
        self.assertTrue(page.hrefs)
        for href in page.hrefs:
            if href.startswith("#"):
                self.assertIn(href[1:], page.ids, f"missing anchor target {href}")
            elif href.startswith("/"):
                response = self.client.get(href)
                self.assertEqual(response.status_code, 200, href)
                response.close()

    def test_dashboard_links_all_resolve(self):
        html = self.client.get("/dashboard").get_data(as_text=True)
        page = collect(html)
        for href in page.hrefs:
            path, _, fragment = href.partition("#")
            if path:
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200, href)
                response.close()
            if fragment:
                self.assertIn(fragment, page.ids, f"missing anchor target {href}")

    def test_dashboard_lists_every_template(self):
        html = self.client.get("/dashboard").get_data(as_text=True)
        for category in get_categories():
            self.assertIn(f"/builder?category={category['id']}", html)
        self.assertIn("New project", html)
        self.assertIn("status-badge", html)  # health widget kept from Phase 1

    def test_builder_preselects_valid_category(self):
        html = self.client.get("/builder?category=restaurant").get_data(as_text=True)
        self.assertRegex(html, r'value="restaurant"[^>]*checked')

    def test_builder_ignores_unknown_category(self):
        html = self.client.get("/builder?category=nonsense").get_data(as_text=True)
        self.assertNotIn("nonsense", html)
        self.assertRegex(html, r'value="auto"[^>]*checked')

    def test_builder_does_not_reflect_script_input(self):
        payload = "<script>alert(1)</script>"
        html = self.client.get("/builder", query_string={"category": payload}).get_data(as_text=True)
        self.assertNotIn(payload, html)

    def test_dashboard_marks_current_page(self):
        html = self.client.get("/dashboard").get_data(as_text=True)
        self.assertIn('aria-current="page"', html)


if __name__ == "__main__":
    unittest.main()
