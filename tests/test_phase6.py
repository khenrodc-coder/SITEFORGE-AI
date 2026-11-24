"""Phase 6 tests: color maths, rendering of every section, safety, accessibility, API."""
import copy
import itertools
import re
import unittest
from html.parser import HTMLParser

from app import create_app
from app.services.design_options import get_color_schemes, get_design_styles
from app.services.site_schema import SECTION_SPECS, SchemaError
from app.services.website_renderer import (
    build_palette,
    contrast,
    ensure_contrast,
    fonts_url,
    initials,
    luminance,
    mix,
    placeholder,
    render_website,
    tel_digits,
)
from tests.sample_sections import valid_section
from tests.test_phase5 import sample_config

VOID = {"meta", "link", "br", "img", "input", "hr", "path", "circle", "rect", "source"}


def make_config(types, **overrides):
    config = copy.deepcopy(sample_config())
    config["sections"] = [{"id": t, "type": t, "nav": SECTION_SPECS[t]["nav"],
                           "nav_label": SECTION_SPECS[t]["label"], "data": valid_section(t)} for t in types]
    for key, value in overrides.items():
        section, _, field = key.partition("__")
        if section in ("meta", "theme"):
            config[section][field] = value
    return config


ALL_ROWS = (("hero", "about", "features", "menu", "gallery", "projects", "products", "testimonials", "contact"),
            ("hero", "team", "pricing", "faq", "cta", "posts", "contact"))


class PageInspector(HTMLParser):
    """Collects facts about a generated page and checks that tags are balanced."""

    def __init__(self):
        super().__init__()
        self.stack, self.errors = [], []
        self.ids, self.hrefs, self.tags, self.scripts = [], [], [], 0
        self.h1 = 0
        self.svgs_without_label = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.tags.append(tag)
        if tag == "script":
            self.scripts += 1
        if tag == "h1":
            self.h1 += 1
        if "id" in a:
            self.ids.append(a["id"])
        if tag == "a" and "href" in a:
            self.hrefs.append(a["href"])
        if tag == "svg" and not ("aria-label" in a or a.get("aria-hidden") == "true"):
            self.svgs_without_label += 1
        if tag not in VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"unexpected </{tag}> (open: {self.stack[-3:]})")
        else:
            self.stack.pop()


def inspect(html):
    page = PageInspector()
    page.feed(html)
    if page.stack:
        page.errors.append(f"unclosed tags: {page.stack}")
    return page


# ------------------------------------------------------------------ color maths
class ColorTests(unittest.TestCase):
    def test_contrast_extremes(self):
        self.assertAlmostEqual(contrast("#000000", "#ffffff"), 21, places=0)
        self.assertAlmostEqual(contrast("#ffffff", "#ffffff"), 1, places=2)

    def test_luminance_order(self):
        self.assertLess(luminance("#000000"), luminance("#777777"))
        self.assertLess(luminance("#777777"), luminance("#ffffff"))

    def test_mix(self):
        self.assertEqual(mix("#000000", "#ffffff", 0), "#000000")
        self.assertEqual(mix("#000000", "#ffffff", 1), "#ffffff")
        self.assertEqual(mix("#000000", "#ffffff", 0.5), "#808080")

    def test_ensure_contrast_darkens_for_light_backgrounds(self):
        fixed = ensure_contrast("#d97706", ["#ffffff"])
        self.assertGreaterEqual(contrast(fixed, "#ffffff"), 4.5)

    def test_ensure_contrast_lightens_for_dark_backgrounds(self):
        fixed = ensure_contrast("#334155", ["#0b1220"])
        self.assertGreaterEqual(contrast(fixed, "#0b1220"), 4.5)

    def test_every_palette_is_readable(self):
        """All color, style and mode combinations meet WCAG AA text contrast."""
        for scheme, style, mode in itertools.product(get_color_schemes(), get_design_styles(), ("light", "dark")):
            theme = {"primary": scheme["primary"], "mode": mode}
            p = build_palette(theme, style["id"])
            where = f"{scheme['id']}/{style['id']}/{mode}"
            for fg, bgs in (
                ("text", ["bg", "surface"]), ("muted", ["bg", "surface", "primary_soft"]),
                ("primary_text", ["bg", "surface", "primary_soft"]),
                ("hero_text", ["hero_bg"]), ("hero_muted", ["hero_bg"]),
                ("on_primary", ["primary"]), ("cta_button_text", ["on_primary"]),
            ):
                for bg in bgs:
                    self.assertGreaterEqual(contrast(p[fg], p[bg]), 4.5, f"{fg} on {bg} in {where}")
            if style["id"] == "bold":
                self.assertGreaterEqual(contrast(p["hero_bg"], "#ffffff"), 4.5, where)   # bold hero button


# ------------------------------------------------------------------ helpers
class HelperTests(unittest.TestCase):
    def test_placeholder_differs_by_seed_and_is_deterministic(self):
        self.assertEqual(str(placeholder("a", "x")), str(placeholder("a", "x")))
        self.assertNotEqual(str(placeholder("a", "x")), str(placeholder("b", "x")))

    def test_placeholder_accessibility(self):
        self.assertIn('role="img"', str(placeholder("a", "A bowl of ramen")))
        self.assertIn('aria-hidden="true"', str(placeholder("a", "")))

    def test_placeholder_escapes_alt(self):
        svg = str(placeholder("a", '"><script>alert(1)</script>'))
        self.assertNotIn("<script>", svg)

    def test_initials_and_tel(self):
        self.assertEqual(initials("maya reyes"), "MR")
        self.assertEqual(initials("Cher"), "C")
        self.assertEqual(tel_digits("+63 (32) 555-0100"), "+63325550100")
        self.assertRegex(tel_digits("javascript:alert(1)<script>"), r"^[0-9+]*$")

    def test_fonts_url(self):
        self.assertIn("family=Playfair+Display:wght@400;700", fonts_url({"font_heading": "Playfair Display", "font_body": "Lato"}))
        self.assertEqual(fonts_url({"font_heading": "Inter", "font_body": "Inter"}).count("family="), 1)


# ------------------------------------------------------------------ rendering
class RenderTests(unittest.TestCase):
    def test_every_section_type_renders_valid_html(self):
        rendered_types = set()
        for row in ALL_ROWS:
            html = render_website(make_config(row))["html"]
            page = inspect(html)
            self.assertEqual(page.errors, [], row)
            for section_type in row:
                self.assertIn(f'id="{section_type}"', html)
                rendered_types.add(section_type)
        self.assertEqual(rendered_types, set(SECTION_SPECS))

    def test_output_files(self):
        out = render_website(sample_config(), year=2026)
        self.assertEqual(set(out["files"]), {"index.html", "css/styles.css", "js/main.js"})
        index = out["files"]["index.html"]
        self.assertIn('href="css/styles.css"', index)
        self.assertIn('src="js/main.js"', index)
        self.assertNotIn("<style>", index)
        self.assertIn("&copy; 2026", index)

    def test_single_file_is_self_contained(self):
        html = render_website(sample_config())["html"]
        self.assertIn("<style>", html)
        self.assertIn(":root{--primary:#2563eb", html)
        self.assertNotIn('href="css/styles.css"', html)
        self.assertNotIn('src="js/main.js"', html)
        self.assertEqual(inspect(html).scripts, 1)

    def test_page_structure_and_accessibility(self):
        html = render_website(make_config(ALL_ROWS[0]))["html"]
        page = inspect(html)
        self.assertEqual(page.h1, 1)
        self.assertEqual(len(page.ids), len(set(page.ids)), "duplicate ids")
        self.assertEqual(page.svgs_without_label, 0)
        for needle in ('<html lang="en">', 'name="viewport"', 'class="skip-link"', 'id="main"',
                       'aria-label="Main"', "<footer", 'name="description"'):
            self.assertIn(needle, html)

    def test_all_links_go_somewhere_safe(self):
        for row in ALL_ROWS:
            html = render_website(make_config(row))["html"]
            page = inspect(html)
            for href in page.hrefs:
                if href.startswith("#"):
                    self.assertIn(href[1:], page.ids, f"{href} has no target")
                else:
                    self.assertRegex(href, r"^(mailto:|tel:\+?\d+$)", href)

    def test_navigation_matches_sections(self):
        html = render_website(make_config(ALL_ROWS[0]))["html"]
        nav = re.search(r'<nav class="site-nav".*?</nav>', html, re.S).group(0)
        self.assertNotIn('href="#hero"', nav)          # hero is not a menu item
        for section_type in ("about", "features", "menu", "contact"):
            self.assertIn(f'href="#{section_type}"', nav)

    def test_is_deterministic(self):
        self.assertEqual(render_website(sample_config(), year=2026), render_website(sample_config(), year=2026))

    def test_different_choices_give_different_pages(self):
        pages = set()
        for style in ("modern", "bold", "elegant", "playful"):
            config = make_config(ALL_ROWS[0])
            config["meta"]["design_style"] = style
            pages.add(render_website(config)["html"])
        self.assertEqual(len(pages), 4)

    def test_hero_layouts_differ(self):
        seen = {}
        for layout in ("centered", "split", "minimal"):
            config = make_config(("hero", "about", "features", "contact"))
            config["sections"][0]["data"]["layout"] = layout
            html = render_website(config)["html"]
            seen[layout] = html
            self.assertIn(f"hero--{layout}", html)
        self.assertNotIn('class="hero-media"', seen["minimal"])
        self.assertIn('class="hero-media"', seen["split"])

    def test_dark_mode(self):
        config = make_config(("hero", "about", "features", "contact"))
        config["theme"]["mode"] = "dark"
        html = render_website(config)["html"]
        self.assertIn('data-mode="dark"', html)
        self.assertIn("color-scheme:dark", html)

    def test_theme_values_reach_css(self):
        config = make_config(("hero", "about", "features", "contact"))
        config["theme"].update(primary="#e11d48", font_heading="Playfair Display", radius="xl")
        css = render_website(config)["files"]["css/styles.css"]
        self.assertIn("--primary:#e11d48", css)
        self.assertIn('"Playfair Display", Georgia', css)
        self.assertIn("--radius:26px", css)

    def test_contact_form_needs_an_email(self):
        config = make_config(("hero", "about", "features", "contact"))
        self.assertIn('class="contact-form"', render_website(config)["html"])
        config["sections"][3]["data"]["email"] = ""
        self.assertNotIn('class="contact-form"', render_website(config)["html"])

    def test_products_link_to_contact_only_when_present(self):
        with_contact = render_website(make_config(("hero", "products", "features", "contact")))["html"]
        without = render_website(make_config(("hero", "products", "features", "about")))["html"]
        self.assertIn("Enquire", with_contact)
        self.assertNotIn("Enquire", without)

    def test_invalid_configuration_is_refused(self):
        bad = sample_config()
        bad["theme"]["primary"] = "red;background:url(//evil)"
        with self.assertRaises(SchemaError):
            render_website(bad)
        with self.assertRaises(SchemaError):
            render_website(None)


# ------------------------------------------------------------------ safety
class RenderSafetyTests(unittest.TestCase):
    def render_with_hostile_text(self, payload):
        config = make_config(ALL_ROWS[0])
        config["meta"]["site_name"] = payload
        config["meta"]["tagline"] = payload
        for section in config["sections"]:
            self.poison(section["data"], payload)
        return render_website(config)["html"]

    def poison(self, value, payload):
        if isinstance(value, dict):
            for key, item in list(value.items()):
                if isinstance(item, str) and key not in ("icon", "layout", "target", "email", "phone", "price"):
                    value[key] = payload
                else:
                    self.poison(item, payload)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                if isinstance(item, str):
                    value[index] = payload
                else:
                    self.poison(item, payload)

    def test_markup_in_text_never_becomes_markup(self):
        for payload in ('Hi <script>alert(1)</script>', 'Hi <img src=x onerror=alert(1)>',
                        'Hi "><svg onload=alert(1)>', "Hi </title><script>alert(1)</script>"):
            html = self.render_with_hostile_text(payload)
            page = inspect(html)
            self.assertEqual(page.scripts, 1, payload)            # only the site's own script
            self.assertNotRegex(html, r"<img[^>]+onerror", payload)
            self.assertNotRegex(html, r"<svg[^>]+onload", payload)
            self.assertEqual(page.errors, [], payload)

    def test_template_engine_escapes_by_default(self):
        from app.services.website_renderer import _environment
        env = _environment()
        self.assertEqual(env.from_string("{{ x }}").render(x="<script>alert(1)</script>"),
                         "&lt;script&gt;alert(1)&lt;/script&gt;")
        self.assertEqual(env.from_string('<a title="{{ x }}">').render(x='" onclick="alert(1)'),
                         '<a title="&#34; onclick=&#34;alert(1)">')

    def test_template_sandbox_blocks_dangerous_access(self):
        from jinja2.exceptions import SecurityError
        from app.services.website_renderer import _environment
        with self.assertRaises(SecurityError):
            _environment().from_string("{{ x.__class__.__mro__ }}").render(x="")

    def test_quotes_and_ampersands_are_escaped_in_attributes(self):
        html = self.render_with_hostile_text('" onmouseover="alert(1)" x="&')
        self.assertNotRegex(html, r'\sonmouseover="')
        self.assertNotIn('alt="" onmouseover', html)

    def test_hostile_contact_details_cannot_break_links(self):
        config = make_config(("hero", "about", "features", "contact"))
        config["sections"][3]["data"]["email"] = 'a"b@example.com'
        config["sections"][3]["data"]["phone"] = '+1 555 0100"><script>alert(1)</script>'
        html = render_website(config)["html"]
        self.assertEqual(inspect(html).scripts, 1)
        self.assertNotIn("<script>alert", html)

    def test_site_script_has_no_dynamic_code_execution(self):
        js = render_website(sample_config())["files"]["js/main.js"]
        for banned in ("eval(", "new Function", "document.write", "innerHTML", "outerHTML"):
            self.assertNotIn(banned, js)

    def test_no_external_scripts_or_remote_images(self):
        html = render_website(make_config(ALL_ROWS[0]))["html"]
        self.assertNotRegex(html, r"<script[^>]+src=\"https?:")
        self.assertNotRegex(html, r"<img\b")
        hosts = set(re.findall(r"https?://([^/\"')\s]+)", html))
        self.assertLessEqual(hosts, {"fonts.googleapis.com", "fonts.gstatic.com", "cdnjs.cloudflare.com"})


# ------------------------------------------------------------------ whole pipeline
class PipelineTests(unittest.TestCase):
    def test_generated_website_renders(self):
        from app.services.ollama_service import OllamaClient
        from app.services.website_generator import generate_website
        from tests.fake_ollama import FakeOllama
        from tests.sample_sections import make_responder

        fake = FakeOllama().start()
        try:
            fake.responder = make_responder(sections=("hero", "features", "menu", "gallery", "contact"))
            client = OllamaClient(fake.url, "llama3.1:8b", timeout=5)
            request = {"prompt": "A late-night ramen bar in Cebu City with a menu.", "category": "auto",
                       "design_style": "elegant", "color_scheme": "rose"}
            config = generate_website(client, request)["config"]
        finally:
            fake.stop()
        html = render_website(config)["html"]
        page = inspect(html)
        self.assertEqual(page.errors, [])
        self.assertIn("Kuya&#39;s Ramen", html)
        self.assertIn('data-style="elegant"', html)
        self.assertIn("--primary:#e11d48", html)

    def test_menu_button_does_not_need_the_icon_font(self):
        html = render_website(sample_config())["html"]
        toggle = re.search(r'<button class="nav-toggle".*?</button>', html, re.S).group(0)
        self.assertNotIn("fa-", toggle)


# ------------------------------------------------------------------ API
class RenderApiTests(unittest.TestCase):
    def setUp(self):
        self.client = create_app("testing").test_client()

    def test_render_endpoint(self):
        response = self.client.post("/api/render", json={"config": sample_config()})
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn("<!DOCTYPE html>", data["html"])
        self.assertEqual(set(data["files"]), {"index.html", "css/styles.css", "js/main.js"})

    def test_invalid_config_gives_400_with_problems(self):
        bad = sample_config()
        bad["meta"]["category"] = "nope"
        response = self.client.post("/api/render", json={"config": bad})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "invalid_configuration")
        self.assertTrue(response.get_json()["problems"])

    def test_bad_bodies(self):
        self.assertEqual(self.client.post("/api/render", data="x").status_code, 415)
        for body in ({}, {"config": None}, {"config": "text"}, [1, 2]):
            self.assertEqual(self.client.post("/api/render", json=body).status_code, 400)
        self.assertEqual(self.client.post("/api/render", data="{bad", content_type="application/json").status_code, 400)

    def test_get_not_allowed(self):
        self.assertEqual(self.client.get("/api/render").status_code, 405)

    def test_builder_has_download_button(self):
        html = self.client.get("/builder").get_data(as_text=True)
        self.assertIn('id="download-site"', html)
        self.assertIn('id="download-status"', html)


if __name__ == "__main__":
    unittest.main()
