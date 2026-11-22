"""Phase 1 tests. Run with:  python -m unittest discover -s tests -v"""
import unittest

from app import create_app


class Phase1RouteTests(unittest.TestCase):
    def setUp(self):
        self.client = create_app("testing").test_client()

    def test_home_page_loads(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"SiteForge AI", response.data)

    def test_health_endpoint_returns_json(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["status"], "ok")
        self.assertTrue(data["checks"]["generated_websites_writable"])

    def test_health_does_not_leak_secrets(self):
        body = self.client.get("/api/health").get_data(as_text=True).lower()
        for word in ("password", "secret", "mysql"):
            self.assertNotIn(word, body)

    def test_unknown_page_gives_html_404(self):
        response = self.client.get("/does-not-exist")
        self.assertEqual(response.status_code, 404)
        self.assertIn(b"Page not found", response.data)

    def test_unknown_api_route_gives_json_404(self):
        response = self.client.get("/api/does-not-exist")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()["error"], "Page not found")

    def test_wrong_method_gives_405(self):
        self.assertEqual(self.client.post("/api/health").status_code, 405)

    def test_security_headers_present(self):
        headers = self.client.get("/").headers
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["X-Frame-Options"], "SAMEORIGIN")

    def test_static_files_served(self):
        for path in ("/static/css/styles.css", "/static/js/main.js"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            response.close()


if __name__ == "__main__":
    unittest.main()
