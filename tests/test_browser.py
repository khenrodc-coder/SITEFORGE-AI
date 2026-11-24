"""Optional real-browser tests (they skip themselves if Playwright is not installed).

To run them:
    pip install playwright
    python -m playwright install chromium
    python -m unittest tests.test_browser -v

They start the real application with a fake AI model, so Ollama is not needed.
"""
import logging
import threading
import unittest

try:
    from playwright.sync_api import sync_playwright
    HAVE_PLAYWRIGHT = True
except ImportError:                      # pragma: no cover
    HAVE_PLAYWRIGHT = False

from app import create_app
from tests.fake_ollama import FakeOllama
from tests.sample_sections import make_responder

PROMPT = "A late-night ramen bar in Cebu City with a menu and reservations."


@unittest.skipUnless(HAVE_PLAYWRIGHT, "Playwright is not installed (optional browser tests)")
class PreviewBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from werkzeug.serving import make_server
        logging.getLogger("werkzeug").setLevel(logging.ERROR)

        cls.fake = FakeOllama().start()
        cls.fake.responder = make_responder(sections=("hero", "about", "menu", "contact"))
        app = create_app("testing")
        app.config["OLLAMA_BASE_URL"] = cls.fake.url
        app.config["OLLAMA_TIMEOUT"] = 5
        cls.server = make_server("127.0.0.1", 0, app, threaded=True)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

        cls.pw = sync_playwright().start()
        try:
            cls.browser = cls.pw.chromium.launch()
        except Exception as exc:         # browser not downloaded
            cls.pw.stop()
            cls.server.shutdown()
            cls.fake.stop()
            raise unittest.SkipTest(f"Chromium is not available: {exc}")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.server.shutdown()
        cls.fake.stop()

    # -------------------------------------------------------------- helpers
    def new_page(self, width=1400, height=900):
        page = self.browser.new_page(viewport={"width": width, "height": height})
        self.addCleanup(page.close)
        self.errors = []
        # The Tailwind CDN script may be unreachable offline; that is not an app error.
        page.on("pageerror", lambda e: self.errors.append(str(e)) if "tailwind" not in str(e) else None)
        return page

    @staticmethod
    def click(page, selector):
        """Click through script so the test also works when the CDN stylesheet is missing."""
        page.evaluate("s => document.querySelector(s).click()", selector)

    def generate(self, page):
        page.goto(self.base + "/builder", wait_until="domcontentloaded")
        page.fill("#prompt", PROMPT)
        self.click(page, "#generate-button")
        page.wait_for_function("document.getElementById('preview-busy').classList.contains('is-hidden')"
                               " && !document.getElementById('preview-section').classList.contains('hidden')",
                               timeout=20000)

    @staticmethod
    def site_frame(page):
        return next(f for f in page.frames if f != page.main_frame)

    @staticmethod
    def frame_width(page):
        return page.evaluate("parseFloat(document.getElementById('preview-frame').style.width)")

    # -------------------------------------------------------------- tests
    def test_preview_is_hidden_until_a_website_exists(self):
        page = self.new_page()
        page.goto(self.base + "/builder", wait_until="domcontentloaded")
        self.assertTrue(page.evaluate("document.getElementById('preview-section').classList.contains('hidden')"))

    def test_preview_shows_the_generated_website(self):
        page = self.new_page()
        self.generate(page)
        frame = self.site_frame(page)
        self.assertIn("Slow-simmered", frame.inner_text("h1"))
        self.assertEqual(frame.locator("main > section").count(), 4)
        self.assertEqual(self.errors, [])

    def test_frame_is_really_isolated(self):
        page = self.new_page()
        self.generate(page)
        frame = self.site_frame(page)
        self.assertEqual(page.get_attribute("#preview-frame", "sandbox"), "allow-scripts")
        self.assertEqual(frame.evaluate("window.origin"), "null")        # opaque origin
        self.assertEqual(frame.evaluate("(() => { try { parent.document.title; return 'readable'; }"
                                        " catch (e) { return 'blocked'; } })()"), "blocked")
        self.assertEqual(frame.evaluate("(() => { try { localStorage.length; return 'readable'; }"
                                        " catch (e) { return 'blocked'; } })()"), "blocked")
        self.assertEqual(frame.evaluate("(() => { try { top.location.href = 'https://example.com'; return 'moved'; }"
                                        " catch (e) { return 'blocked'; } })()"), "blocked")

    def test_device_buttons_change_the_real_layout(self):
        page = self.new_page()
        self.generate(page)
        frame = self.site_frame(page)

        self.assertEqual(self.frame_width(page), 1280)
        self.assertFalse(frame.locator(".nav-toggle").is_visible())      # desktop menu is spread out

        self.click(page, '[data-device="tablet"]')
        self.assertEqual(self.frame_width(page), 768)
        self.assertEqual(page.get_attribute('[data-device="tablet"]', "aria-pressed"), "true")
        self.assertEqual(page.get_attribute('[data-device="desktop"]', "aria-pressed"), "false")
        self.assertIn("Tablet", page.inner_text("#preview-info"))

        self.click(page, '[data-device="mobile"]')
        self.assertEqual(self.frame_width(page), 375)
        self.assertTrue(frame.locator(".nav-toggle").is_visible())       # the website itself went mobile
        self.assertEqual(frame.evaluate("document.documentElement.scrollWidth <= innerWidth"), True)

        self.click(page, '[data-device="desktop"]')
        self.assertEqual(self.frame_width(page), 1280)

    def test_wide_pages_are_scaled_to_fit_a_small_window(self):
        page = self.new_page(width=700, height=900)
        self.generate(page)
        stage_width = page.evaluate("document.getElementById('preview-stage').clientWidth")
        viewport_width = page.evaluate("document.getElementById('preview-viewport').getBoundingClientRect().width")
        self.assertLessEqual(viewport_width, stage_width)
        self.assertIn("scale(", page.evaluate("document.getElementById('preview-frame').style.transform"))
        self.assertIn("shown at", page.inner_text("#preview-info"))
        self.assertEqual(page.evaluate("document.documentElement.scrollWidth <= innerWidth"), True)

    def test_links_inside_the_preview_scroll_the_preview(self):
        page = self.new_page()
        self.generate(page)
        frame = self.site_frame(page)
        self.assertEqual(frame.evaluate("window.scrollY"), 0)
        frame.locator('.site-nav a[href="#menu"]').first.click()
        page.wait_for_timeout(900)
        self.assertGreater(frame.evaluate("window.scrollY"), 100)
        self.assertEqual(page.evaluate("window.location.hash"), "")      # SiteForge itself did not navigate

    def test_refresh_rebuilds_the_preview(self):
        page = self.new_page()
        self.generate(page)
        renders = []
        page.on("request", lambda r: renders.append(r.url) if r.url.endswith("/api/render") else None)
        self.site_frame(page).evaluate("window.__marker = 'old page'")
        self.click(page, "#preview-refresh")
        page.wait_for_function("document.getElementById('preview-busy').classList.contains('is-hidden')")
        page.wait_for_timeout(300)
        self.assertEqual(len(renders), 1)
        self.assertIsNone(self.site_frame(page).evaluate("window.__marker || null"))   # a fresh document

    def test_full_screen_toggles(self):
        page = self.new_page()
        self.generate(page)
        self.click(page, "#preview-fullscreen")
        page.wait_for_timeout(300)
        is_full = page.evaluate("document.fullscreenElement === document.getElementById('preview-card')"
                                " || document.getElementById('preview-card').classList.contains('is-expanded')")
        self.assertTrue(is_full)
        self.assertEqual(page.inner_text("#preview-fullscreen"), "Exit full screen")
        self.click(page, "#preview-fullscreen")
        page.wait_for_timeout(300)
        self.assertEqual(page.inner_text("#preview-fullscreen"), "Full screen")
        self.assertFalse(page.evaluate("document.getElementById('preview-card').classList.contains('is-expanded')"))

    def test_preview_error_can_be_retried(self):
        page = self.new_page()
        self.generate(page)
        page.route("**/api/render", lambda route: route.fulfill(
            status=400, content_type="application/json",
            body='{"error":"invalid_configuration","message":"The website data is not valid."}'))
        self.click(page, "#preview-refresh")
        page.wait_for_function("!document.getElementById('preview-error').classList.contains('is-hidden')")
        self.assertIn("not valid", page.inner_text("#preview-error-message"))
        page.unroute("**/api/render")
        self.click(page, "#preview-retry")
        page.wait_for_function("document.getElementById('preview-error').classList.contains('is-hidden')"
                               " && document.getElementById('preview-busy').classList.contains('is-hidden')")
        self.assertIn("Slow-simmered", self.site_frame(page).inner_text("h1"))


if __name__ == "__main__":
    unittest.main()
