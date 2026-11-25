"""Phase 7 tests: the preview markup, its sandbox, and the preview script."""
import re
import unittest
from html.parser import HTMLParser

from app import create_app


class FrameFinder(HTMLParser):
    def __init__(self):
        super().__init__()
        self.iframes = []
        self.buttons = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "iframe":
            self.iframes.append(attributes)
        if tag == "button":
            self.buttons.append(attributes)


class PreviewMarkupTests(unittest.TestCase):
    def setUp(self):
        self.client = create_app("testing").test_client()
        self.html = self.client.get("/builder").get_data(as_text=True)
        self.page = FrameFinder()
        self.page.feed(self.html)

    def test_exactly_one_preview_frame(self):
        self.assertEqual(len(self.page.iframes), 1)
        self.assertEqual(self.page.iframes[0]["id"], "preview-frame")

    def test_frame_is_sandboxed_without_same_origin(self):
        flags = set(self.page.iframes[0].get("sandbox", "").split())
        self.assertEqual(flags, {"allow-scripts"})
        for dangerous in ("allow-same-origin", "allow-top-navigation", "allow-popups", "allow-forms"):
            self.assertNotIn(dangerous, flags)

    def test_frame_has_title_and_no_remote_source(self):
        frame = self.page.iframes[0]
        self.assertTrue(frame.get("title"))
        self.assertNotIn("src", frame)          # content arrives only as text (srcdoc)
        self.assertEqual(frame.get("referrerpolicy"), "no-referrer")

    def test_device_buttons_and_controls_present(self):
        devices = [b["data-device"] for b in self.page.buttons if "data-device" in b]
        self.assertEqual(devices, ["desktop", "tablet", "mobile"])
        pressed = [b["aria-pressed"] for b in self.page.buttons if "data-device" in b]
        self.assertEqual(pressed, ["true", "false", "false"])
        ids = {b.get("id") for b in self.page.buttons}
        self.assertTrue({"preview-refresh", "preview-fullscreen", "preview-retry"} <= ids)

    def test_preview_starts_hidden_and_labelled(self):
        self.assertRegex(self.html, r'<section id="preview-section" class="[^"]*\bhidden\b')
        self.assertIn('aria-label="Preview size"', self.html)
        self.assertIn('aria-labelledby="preview-title"', self.html)

    def test_scripts_load_in_order(self):
        order = [m.group(1) for m in re.finditer(r'src="/static/js/([a-z]+)\.js"', self.html)]
        self.assertEqual(order, ["main", "builder", "preview", "editor"])

    def test_preview_only_on_builder_page(self):
        for path in ("/", "/dashboard"):
            html = self.client.get(path).get_data(as_text=True)
            self.assertNotIn("preview-frame", html)


class PreviewRenderTests(unittest.TestCase):
    def setUp(self):
        from tests.test_phase5 import sample_config
        self.client = create_app("testing").test_client()
        self.config = sample_config()

    def render(self, **extra):
        response = self.client.post("/api/render", json=dict({"config": self.config}, **extra))
        self.assertEqual(response.status_code, 200)
        return response.get_json()

    def test_preview_version_keeps_in_page_links_inside_the_frame(self):
        data = self.render(preview=True)
        self.assertIn('<base href="about:srcdoc">', data["html"])
        self.assertLess(data["html"].index("<base"), data["html"].index("<title>"))

    def test_download_version_has_no_base_address(self):
        for data in (self.render(), self.render(preview=False), self.render(preview="yes")):
            self.assertNotIn("<base", data["html"])
            self.assertNotIn("<base", data["files"]["index.html"])

    def test_preview_flag_never_changes_the_exported_files(self):
        self.assertEqual(self.render(preview=True)["files"], self.render()["files"])

    def test_preview_script_asks_for_the_preview_version(self):
        source = self.client.get("/static/js/preview.js").get_data(as_text=True)
        self.assertIn("preview: true", source)


class PreviewScriptTests(unittest.TestCase):
    def setUp(self):
        client = create_app("testing").test_client()
        response = client.get("/static/js/preview.js")
        self.assertEqual(response.status_code, 200)
        self.source = response.get_data(as_text=True)
        response.close()
        css = client.get("/static/css/styles.css")
        self.css = css.get_data(as_text=True)
        css.close()

    def test_page_is_never_inserted_into_the_document(self):
        for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
            self.assertNotIn(banned, self.source)

    def test_content_goes_in_as_srcdoc_only(self):
        self.assertIn("next.srcdoc = result.data.html", self.source)
        self.assertNotIn(".src =", self.source)
        self.assertNotIn("contentDocument", self.source)
        self.assertNotIn("contentWindow.document", self.source)

    def test_frames_created_by_the_script_are_sandboxed_the_same_way(self):
        values = re.findall(r'setAttribute\("sandbox",\s*"([^"]*)"\)', self.source)
        self.assertEqual(values, ["allow-scripts"])                     # every frame the script makes
        code = re.sub(r"/\*.*?\*/", "", self.source, flags=re.S)       # ignore the explanatory comment
        self.assertNotIn("allow-same-origin", code)
        self.assertNotIn("allow-top-navigation", code)
        self.assertIn('setAttribute("referrerpolicy", "no-referrer")', self.source)

    def test_messages_are_only_trusted_from_our_own_frames(self):
        self.assertIn("event.source === frame.contentWindow", self.source)
        self.assertIn("event.source !== pendingFrame.contentWindow", self.source)
        self.assertIn('typeof data.y === "number"', self.source)

    def test_all_three_devices_defined(self):
        for needle in ("width: 1280", "width: 768", "width: 375"):
            self.assertIn(needle, self.source)

    def test_preview_layout_does_not_depend_on_tailwind(self):
        for selector in (".preview-stage", ".preview-viewport", ".preview-frame", ".preview-overlay",
                         ".preview-card.is-expanded", ".seg-btn"):
            self.assertIn(selector, self.css)

    def test_existing_page_rules_kept(self):
        for selector in (".app-sidebar", ".status-badge", ".skip-link"):
            self.assertIn(selector, self.css)


if __name__ == "__main__":
    unittest.main()
