"""Optional real-browser tests for the website editor (skipped if Playwright is not installed).

    pip install playwright
    python -m playwright install chromium
    python -m unittest tests.test_browser_editor -v
"""
import base64
import json
import logging
import tempfile
import threading
import time
import unittest
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
    HAVE_PLAYWRIGHT = True
except ImportError:                      # pragma: no cover
    HAVE_PLAYWRIGHT = False

from app import create_app
from tests.fake_ollama import FakeOllama
from tests.sample_sections import make_responder, valid_section

PROMPT = "A late-night ramen bar in Cebu City with a menu and reservations."
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


@unittest.skipUnless(HAVE_PLAYWRIGHT, "Playwright is not installed (optional browser tests)")
class EditorBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from werkzeug.serving import make_server
        logging.getLogger("werkzeug").setLevel(logging.ERROR)
        cls.fake = FakeOllama().start()
        app = create_app("testing")
        app.config["OLLAMA_BASE_URL"] = cls.fake.url
        app.config["OLLAMA_TIMEOUT"] = 5
        cls.server = make_server("127.0.0.1", 0, app, threaded=True)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        cls.pw = sync_playwright().start()
        try:
            cls.browser = cls.pw.chromium.launch()
        except Exception as exc:
            cls.pw.stop()
            cls.server.shutdown()
            cls.fake.stop()
            raise unittest.SkipTest(f"Chromium is not available: {exc}")
        cls.tmp = tempfile.TemporaryDirectory()
        cls.png_path = Path(cls.tmp.name) / "photo.png"
        cls.png_path.write_bytes(PNG)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.server.shutdown()
        cls.fake.stop()
        cls.tmp.cleanup()

    def setUp(self):
        self.fake.delay = 0
        self.fake.models = ["llama3.1:8b"]
        self.fake.requests.clear()
        self.fake.responder = make_responder(sections=("hero", "about", "menu", "contact"))

    # -------------------------------------------------------------- helpers
    def open_editor(self, accept_downloads=False):
        context = self.browser.new_context(viewport={"width": 1400, "height": 1000}, accept_downloads=accept_downloads)
        self.addCleanup(context.close)
        page = context.new_page()
        self.errors = []
        page.on("pageerror", lambda e: self.errors.append(str(e)) if "tailwind" not in str(e) else None)
        page.on("dialog", lambda d: d.accept())
        page.goto(self.base + "/builder", wait_until="domcontentloaded")
        page.fill("#prompt", PROMPT)
        self.click(page, "#generate-button")
        page.wait_for_function("document.getElementById('preview-busy').classList.contains('is-hidden')"
                               " && document.querySelectorAll('#editor-sections .sec').length > 0", timeout=20000)
        return page

    @staticmethod
    def click(page, selector):
        """Click through script so the test also works when the CDN stylesheet is missing."""
        page.locator(selector).first.dispatch_event("click")

    @staticmethod
    def frame(page):
        return page.query_selector("#preview-frame").content_frame()

    def eventually(self, check, timeout=10, message="condition was never met"):
        end = time.time() + timeout
        last = None
        while time.time() < end:
            try:
                last = check()
                if last:
                    return last
            except Exception as exc:               # the frame may be swapping
                last = exc
            time.sleep(0.1)
        self.fail(f"{message} (last value: {last!r})")

    def site_text(self, page, selector):
        return lambda: self.frame(page).inner_text(selector)

    def open_section(self, page, section_id):
        if page.get_attribute(f'.sec[data-sec-id="{section_id}"] .sec-toggle', "aria-expanded") != "true":
            self.click(page, f'.sec[data-sec-id="{section_id}"] .sec-toggle')

    def field(self, page, section_id, name):
        self.open_section(page, section_id)
        return page.locator(f'.sec[data-sec-id="{section_id}"] [data-field="{name}"]').first

    def section_ids_in_preview(self, page):
        return self.frame(page).evaluate("[...document.querySelectorAll('main > section')].map(s => s.id)")

    # -------------------------------------------------------------- tests
    def test_editor_appears_with_the_sections(self):
        page = self.open_editor()
        names = page.evaluate("[...document.querySelectorAll('#editor-sections .sec-name')].map(e => e.textContent)")
        self.assertEqual(names, ["Home", "About", "Menu", "Contact"])
        self.assertEqual(page.get_attribute("#tab-content", "aria-selected"), "true")
        self.assertEqual(self.errors, [])

    def test_editing_a_heading_updates_the_preview(self):
        page = self.open_editor()
        self.field(page, "hero", "headline").fill("Noodles worth the queue")
        self.eventually(lambda: self.frame(page).inner_text("h1") == "Noodles worth the queue")

    def test_editing_a_paragraph_updates_the_preview(self):
        page = self.open_editor()
        self.open_section(page, "about")
        first = page.locator('.sec[data-sec-id="about"] fieldset:has(legend:text("Paragraphs")) textarea').first
        first.fill("We started with one pot and one very loud grandmother.")
        self.eventually(lambda: "very loud grandmother" in self.frame(page).inner_text("#about"))

    def test_changing_the_main_color(self):
        page = self.open_editor()
        page.evaluate("document.getElementById('tab-design').click()")
        page.fill('[data-field="primary"]', "#e11d48")
        self.eventually(lambda: self.frame(page).evaluate(
            "getComputedStyle(document.documentElement).getPropertyValue('--primary').trim()") == "#e11d48")
        self.assertEqual(page.input_value('[data-field="primary-picker"]'), "#e11d48")

    def test_color_presets_and_a_bad_color_code(self):
        page = self.open_editor()
        page.evaluate("document.getElementById('tab-design').click()")
        self.click(page, '.swatch[aria-label="Emerald"]')
        self.eventually(lambda: self.frame(page).evaluate(
            "getComputedStyle(document.documentElement).getPropertyValue('--primary').trim()") == "#059669")
        self.assertEqual(page.get_attribute('.swatch[aria-label="Emerald"]', "aria-pressed"), "true")
        page.fill('[data-field="primary"]', "#12")
        self.assertIn("Use a color like", page.inner_text("#editor-design"))

    def test_fonts_mode_style_and_corners(self):
        page = self.open_editor()
        page.evaluate("document.getElementById('tab-design').click()")
        page.select_option('[data-field="font_heading"]', "Playfair Display")
        self.eventually(lambda: "Playfair Display" in self.frame(page).evaluate(
            "getComputedStyle(document.documentElement).getPropertyValue('--font-heading')"))
        self.click(page, '[data-mode="dark"]')
        self.eventually(lambda: self.frame(page).evaluate("document.body.dataset.mode") == "dark")
        page.select_option('[data-field="design_style"]', "bold")
        self.eventually(lambda: self.frame(page).evaluate("document.body.dataset.style") == "bold")
        page.select_option('[data-field="radius"]', "xl")
        self.eventually(lambda: self.frame(page).evaluate(
            "getComputedStyle(document.documentElement).getPropertyValue('--radius').trim()") == "26px")
        self.click(page, '[data-act="reset-style"]')       # back to the bold style's own fonts
        self.eventually(lambda: "Archivo" in self.frame(page).evaluate(
            "getComputedStyle(document.documentElement).getPropertyValue('--font-heading')"))

    def test_removing_a_section_needs_confirmation_and_respects_the_minimum(self):
        page = self.open_editor()
        self.click(page, '.sec[data-sec-id="menu"] [data-act="remove"]')
        self.assertIn("menu", self.section_ids_in_preview(page))                  # one click only arms it
        self.assertEqual(page.inner_text('.sec[data-sec-id="menu"] [data-act="remove"]'), "Sure?")
        self.click(page, '.sec[data-sec-id="menu"] [data-act="remove"]')
        self.eventually(lambda: self.section_ids_in_preview(page) == ["hero", "about", "contact"])
        nav = self.frame(page).evaluate("[...document.querySelectorAll('.site-nav a')].map(a => a.textContent)")
        self.assertNotIn("Menu", nav)
        self.assertTrue(page.is_disabled('.sec[data-sec-id="about"] [data-act="remove"]'))   # three is the minimum
        self.assertEqual(page.locator('.sec[data-sec-id="hero"] [data-act="remove"]').count(), 0)   # no removing the hero

    def test_moving_sections(self):
        page = self.open_editor()
        self.click(page, '.sec[data-sec-id="about"] [data-act="down"]')
        self.eventually(lambda: self.section_ids_in_preview(page) == ["hero", "menu", "about", "contact"])
        self.assertTrue(page.is_disabled('.sec[data-sec-id="menu"] [data-act="up"]'))      # cannot go above the hero
        self.assertTrue(page.is_disabled('.sec[data-sec-id="hero"] [data-act="down"]'))
        self.click(page, '.sec[data-sec-id="about"] [data-act="up"]')
        self.eventually(lambda: self.section_ids_in_preview(page) == ["hero", "about", "menu", "contact"])

    def test_adding_a_section_with_the_ai(self):
        page = self.open_editor()
        self.fake.responder = make_responder(sections=("hero", "about", "menu", "contact"))
        page.select_option('[data-field="new-section"]', "faq")
        self.click(page, '[data-act="add"]')
        self.eventually(lambda: "faq" in self.section_ids_in_preview(page), timeout=15)
        self.assertEqual(self.section_ids_in_preview(page), ["hero", "about", "menu", "faq", "contact"])
        self.assertIn("Question 0?", self.frame(page).inner_text("#faq"))
        self.assertEqual(page.locator('[data-field="new-section"] option[value="faq"]').count(), 0)

    def test_rewriting_a_section_with_an_instruction(self):
        page = self.open_editor()
        good = make_responder(sections=("hero", "about", "menu", "contact"))

        def responder(body):
            text = good(body)
            if "Section to write: hero" in body["messages"][1]["content"]:
                data = json.loads(text)
                data["headline"] = "Rewritten by the model"
                return json.dumps(data)
            return text

        self.fake.responder = responder
        self.field(page, "hero", "hint").fill("Make it shorter")
        self.click(page, '.sec[data-sec-id="hero"] [data-act="rewrite"]')
        self.eventually(lambda: self.frame(page).inner_text("h1") == "Rewritten by the model", timeout=15)
        self.assertIn("Extra instruction for the hero section: Make it shorter",
                      self.fake.requests[-1]["messages"][1]["content"])

    def test_the_editor_is_locked_while_the_ai_works_and_cancel_unlocks_it(self):
        page = self.open_editor()
        self.fake.delay = 1.0
        page.select_option('[data-field="new-section"]', "faq")
        self.click(page, '[data-act="add"]')
        self.eventually(lambda: page.get_attribute("#editor-panel", "aria-busy") == "true")
        self.assertTrue(page.is_disabled('[data-field="new-section"]'))
        self.assertTrue(page.is_disabled("#editor-discard"))
        self.click(page, "#editor-add .job-line button")
        self.eventually(lambda: page.get_attribute("#editor-panel", "aria-busy") == "false")
        self.assertFalse(page.is_disabled('[data-field="new-section"]'))
        self.assertIn("Cancelled", page.inner_text("#editor-status"))
        time.sleep(1.2)                                         # let the cancelled job finish
        self.assertNotIn("faq", self.section_ids_in_preview(page))

    def test_uploading_and_removing_a_picture(self):
        page = self.open_editor()
        self.open_section(page, "hero")
        self.assertEqual(self.frame(page).locator("#hero img").count(), 0)
        page.set_input_files('.sec[data-sec-id="hero"] [data-field="image-file"]', str(self.png_path))
        self.eventually(lambda: self.frame(page).locator("#hero img.ph").count() == 1)
        src = self.frame(page).get_attribute("#hero img.ph", "src")
        self.assertTrue(src.startswith("data:image/"))
        self.assertTrue(page.locator('.sec[data-sec-id="hero"] img.thumb').count() == 1)
        self.click(page, '.sec[data-sec-id="hero"] .tool-btn:has-text("Use placeholder")')
        self.eventually(lambda: self.frame(page).locator("#hero img").count() == 0)
        self.assertEqual(self.errors, [])

    def test_a_non_picture_is_refused(self):
        page = self.open_editor()
        self.open_section(page, "hero")
        bad = Path(self.tmp.name) / "notes.txt"
        bad.write_text("hello")
        page.set_input_files('.sec[data-sec-id="hero"] [data-field="image-file"]', str(bad))
        self.eventually(lambda: "Choose a PNG" in page.inner_text('.sec[data-sec-id="hero"]'))

    def test_a_required_field_left_empty_keeps_the_last_good_preview(self):
        page = self.open_editor()
        headline = self.field(page, "hero", "headline")
        headline.fill("")
        self.eventually(lambda: "was not updated" in page.inner_text("#editor-error"))
        self.assertIn("headline", page.inner_text("#editor-error"))
        self.assertIn("Slow-simmered", self.frame(page).inner_text("h1"))        # still the old, good version
        headline.fill("Back again")
        self.eventually(lambda: self.frame(page).inner_text("h1") == "Back again")
        self.eventually(lambda: page.inner_text("#editor-error") == "")

    def test_the_preview_keeps_its_scroll_position_while_editing(self):
        page = self.open_editor()
        self.frame(page).evaluate("window.scrollTo({top: 1100, behavior: 'instant'})")
        time.sleep(0.4)
        self.field(page, "about", "title").fill("Our long story")
        self.eventually(lambda: self.frame(page).inner_text("#about h2") == "Our long story")
        self.assertGreater(self.frame(page).evaluate("window.scrollY"), 900)

    def test_editing_a_list(self):
        page = self.open_editor()
        self.fake.responder = make_responder(sections=("hero", "features", "menu", "contact"))
        page.reload(wait_until="domcontentloaded")
        page.fill("#prompt", PROMPT)
        self.click(page, "#generate-button")
        page.wait_for_function("document.querySelectorAll('#editor-sections .sec').length > 0", timeout=20000)
        self.eventually(lambda: "features" in self.section_ids_in_preview(page))
        self.open_section(page, "features")
        group = '.sec[data-sec-id="features"] fieldset:has(> legend:text-is("Items"))'
        self.assertEqual(self.frame(page).locator("#features li.card").count(), 3)
        self.click(page, f'{group} > button')                                    # "Add item"
        page.locator(f'{group} details[open] [data-field="title"]').fill("Fresh noodles")
        page.locator(f'{group} details[open] [data-field="description"]').fill("Pulled by hand every morning.")
        self.eventually(lambda: self.frame(page).locator("#features li.card").count() == 4)
        self.assertIn("Fresh noodles", self.frame(page).inner_text("#features"))
        self.assertTrue(page.is_disabled(f'{group} details:first-child [data-act="remove"]') is False)

    def test_the_editor_never_overflows_sideways(self):
        for width in (1400, 390):
            context = self.browser.new_context(viewport={"width": width, "height": 900})
            self.addCleanup(context.close)
            page = context.new_page()
            page.goto(self.base + "/builder", wait_until="domcontentloaded")
            page.fill("#prompt", PROMPT)
            self.click(page, "#generate-button")
            page.wait_for_function("document.querySelectorAll('#editor-sections .sec').length > 0", timeout=20000)
            for section_id in ("hero", "about", "menu", "contact"):
                self.open_section(page, section_id)
            page.locator('.sec[data-sec-id="menu"] details > summary').first.dispatch_event("click")
            for tab in ("tab-content", "tab-design"):
                page.evaluate("id => document.getElementById(id).click()", tab)
                overflow = page.evaluate("""() => {
                    const panel = document.getElementById('editor-panel');
                    const box = panel.getBoundingClientRect();
                    return [...panel.querySelectorAll('input, select, textarea, button, fieldset, details, p')]
                        .filter(e => e.offsetParent !== null && e.getBoundingClientRect().right > box.right + 1)
                        .map(e => e.tagName + ' ' + (e.dataset.field || e.className)).slice(0, 5);
                }""")
                self.assertEqual(overflow, [], f"width {width}, tab {tab}")
            self.assertTrue(page.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"page at {width}")

    def test_discarding_changes(self):
        page = self.open_editor()
        self.field(page, "hero", "headline").fill("Something else entirely")
        self.eventually(lambda: self.frame(page).inner_text("h1") == "Something else entirely")
        self.click(page, "#editor-discard")
        self.assertIn("Sure", page.inner_text("#editor-discard"))
        self.click(page, "#editor-discard")
        self.eventually(lambda: "Slow-simmered" in self.frame(page).inner_text("h1"))
        self.assertIn("discarded", page.inner_text("#editor-status"))

    def test_download_contains_the_edits(self):
        page = self.open_editor(accept_downloads=True)
        page.evaluate("document.querySelector('[data-field=\"site_name\"]').focus()")
        page.fill('#editor-site [data-field="site_name"]', "Midnight Noodle Club")
        self.eventually(lambda: self.frame(page).inner_text(".brand") == "Midnight Noodle Club")
        self.assertEqual(page.evaluate("window.SiteForgeEditor.hasUnsavedChanges()"), True)
        with page.expect_download() as download:
            self.click(page, "#download-site")
        self.assertEqual(download.value.suggested_filename, "midnight-noodle-club.html")
        text = Path(download.value.path()).read_text(encoding="utf-8")
        self.assertIn("Midnight Noodle Club", text)
        self.assertNotIn("postMessage", text)                                    # the preview helper is not exported
        self.assertEqual(page.evaluate("window.SiteForgeEditor.hasUnsavedChanges()"), False)

    def test_generating_again_asks_before_replacing_edits(self):
        page = self.open_editor()
        messages = []
        page.on("dialog", lambda d: messages.append(d.message))
        self.field(page, "hero", "headline").fill("My careful edit")
        time.sleep(0.6)
        self.click(page, "#generate-button")
        time.sleep(0.5)
        self.assertTrue(any("replaces the one you have now" in m for m in messages))


if __name__ == "__main__":
    unittest.main()
