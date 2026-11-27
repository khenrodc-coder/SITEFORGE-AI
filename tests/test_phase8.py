"""Phase 8 tests: pictures, schema export, section writing, request limits."""
import base64
import copy
import json
import time
import unittest

from app import create_app
from app.services.site_schema import (
    IMAGE_MAX_CHARS,
    SECTION_SPECS,
    SchemaError,
    clean_image,
    clean_section_data,
    describe_shape,
    export_schema,
    validate_site_config,
)
from app.services.website_generator import carry_over_images
from app.services.website_renderer import picture, render_website
from tests.fake_ollama import FakeOllama
from tests.sample_sections import valid_section
from tests.test_phase5 import sample_config
from tests.test_phase6 import make_config

PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def uri(kind, raw):
    return f"data:image/{kind};base64," + base64.b64encode(raw).decode()


GOOD_PNG = uri("png", PNG_1X1)
GOOD_JPEG = uri("jpeg", b"\xff\xd8\xff\xe0" + b"0" * 30)
GOOD_GIF = uri("gif", b"GIF89a" + b"0" * 30)
GOOD_WEBP = uri("webp", b"RIFF\x10\x00\x00\x00WEBP" + b"0" * 30)


# ------------------------------------------------------------------ picture validation
class ImageValidationTests(unittest.TestCase):
    def test_genuine_pictures_accepted(self):
        for good in (GOOD_PNG, GOOD_JPEG, GOOD_GIF, GOOD_WEBP):
            self.assertEqual(clean_image(good), good)

    def test_svg_rejected(self):
        svg = uri("svg+xml", b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>")
        self.assertEqual(clean_image(svg), "")

    def test_wrong_type_label_rejected(self):
        self.assertEqual(clean_image(uri("jpeg", PNG_1X1)), "")          # PNG bytes labelled JPEG
        self.assertEqual(clean_image(uri("png", b"<script>alert(1)</script>")), "")
        self.assertEqual(clean_image(uri("gif", b"<html>")), "")

    def test_not_a_data_address_rejected(self):
        for bad in ("https://example.com/a.png", "javascript:alert(1)", "//evil/x.png", "/static/x.png",
                    "data:text/html;base64,PHNjcmlwdD4=", "data:image/png;base64,", "data:image/png,abc", ""):
            self.assertEqual(clean_image(bad), "", bad)

    def test_damaged_base64_rejected(self):
        self.assertEqual(clean_image("data:image/png;base64,!!!notbase64!!!"), "")
        self.assertEqual(clean_image(GOOD_PNG[:-6] + "\n" + GOOD_PNG[-5:]), "")     # whitespace inside

    def test_non_text_rejected(self):
        for bad in (None, 5, [], {}, True):
            self.assertEqual(clean_image(bad), "")

    def test_oversized_picture_rejected(self):
        big = uri("png", PNG_1X1[:8] + b"0" * IMAGE_MAX_CHARS)
        self.assertGreater(len(big), IMAGE_MAX_CHARS)
        self.assertEqual(clean_image(big), "")

    def test_pictures_survive_section_cleaning(self):
        data = valid_section("gallery")
        data["items"][0]["image"] = GOOD_PNG
        data["items"][1]["image"] = "javascript:alert(1)"
        cleaned = clean_section_data("gallery", data, {"hero", "gallery"})
        self.assertEqual(cleaned["items"][0]["image"], GOOD_PNG)
        self.assertEqual(cleaned["items"][1]["image"], "")
        hero = valid_section("hero")
        hero["image"] = GOOD_JPEG
        self.assertEqual(clean_section_data("hero", hero, {"hero", "contact", "menu"})["image"], GOOD_JPEG)

    def test_the_ai_is_never_asked_for_pictures(self):
        for section_type in ("hero", "about", "gallery", "projects", "products"):
            shape, _ = describe_shape(section_type, {"hero", "contact"})
            self.assertNotIn('"image"', shape, section_type)
            self.assertNotIn("data:image", shape)

    def test_total_picture_size_is_limited(self):
        raw = PNG_1X1[:8] + b"0" * 400_000
        big = uri("png", raw)
        self.assertLess(len(big), IMAGE_MAX_CHARS)
        config = make_config(("hero", "gallery", "products", "projects", "contact"))
        counts = {"gallery": 8, "products": 8, "projects": 6}          # the most each section can hold
        for section in config["sections"]:
            if section["type"] in counts:
                template = section["data"]["items"][0]
                section["data"]["items"] = [dict(template, image=big) for _ in range(counts[section["type"]])]
        with self.assertRaises(SchemaError) as caught:
            validate_site_config(config)
        self.assertIn("too large in total", str(caught.exception.problems))

    def test_pictures_under_the_total_limit_are_fine(self):
        big = uri("png", PNG_1X1[:8] + b"0" * 400_000)
        config = make_config(("hero", "gallery", "contact"))
        config["sections"][1]["data"]["items"] = [dict(config["sections"][1]["data"]["items"][0], image=big)
                                                  for _ in range(8)]          # about 4.3 million characters
        cleaned = validate_site_config(config)
        self.assertEqual(cleaned["sections"][1]["data"]["items"][7]["image"], big)


# ------------------------------------------------------------------ rendering pictures
class PictureRenderTests(unittest.TestCase):
    def test_uploaded_picture_becomes_an_img(self):
        html = str(picture("seed", GOOD_PNG, "A bowl of ramen"))
        self.assertIn('<img class="ph" src="data:image/png;base64,', html)
        self.assertIn('alt="A bowl of ramen"', html)

    def test_no_picture_gives_the_stand_in(self):
        html = str(picture("seed", "", "x"))
        self.assertTrue(html.startswith("<svg"))
        self.assertNotIn("<img", html)

    def test_alt_text_cannot_break_out_of_the_attribute(self):
        html = str(picture("seed", GOOD_PNG, '" onerror="alert(1)'))
        self.assertNotIn('onerror="alert', html)
        self.assertIn("&#34;", html)

    def test_pictures_appear_in_every_slot(self):
        config = make_config(("hero", "about", "gallery", "projects", "products", "contact"))
        for section in config["sections"]:
            data = section["data"]
            if section["type"] in ("hero", "about"):
                data["image"] = GOOD_PNG
            elif section["type"] in ("gallery", "projects", "products"):
                data["items"][0]["image"] = GOOD_JPEG
        html = render_website(config)["html"]
        self.assertEqual(html.count("<img "), 5)
        self.assertIn("data:image/jpeg;base64,", html)

    def test_hostile_picture_value_never_reaches_the_page(self):
        config = make_config(("hero", "about", "features", "contact"))
        config["sections"][0]["data"]["image"] = 'javascript:alert(1)"><script>alert(1)</script>'
        html = render_website(config)["html"]
        self.assertNotIn("<img", html)
        self.assertNotIn("javascript:alert", html)

    def test_default_pages_have_no_pictures_or_remote_images(self):
        html = render_website(make_config(("hero", "gallery", "contact")))["html"]
        self.assertNotIn("<img", html)


class PreviewBridgeTests(unittest.TestCase):
    def test_bridge_only_in_the_preview_version(self):
        config = sample_config()
        preview = render_website(config, preview=True)["html"]
        normal = render_website(config)
        self.assertIn("postMessage", preview)
        self.assertNotIn("postMessage", normal["html"])
        for text in normal["files"].values():
            self.assertNotIn("postMessage", text)

    def test_bridge_checks_who_is_talking(self):
        bridge = render_website(sample_config(), preview=True)["html"]
        self.assertIn("event.source !== host", bridge)

    def test_files_can_be_skipped(self):
        self.assertNotIn("files", render_website(sample_config(), with_files=False))
        self.assertIn("files", render_website(sample_config()))


# ------------------------------------------------------------------ helpers
class CarryOverTests(unittest.TestCase):
    def test_pictures_stay_in_place(self):
        old = {"image": "A", "items": [{"image": "B", "caption": "old1"}, {"image": "", "caption": "old2"}]}
        new = {"image": "", "items": [{"image": "", "caption": "n1"}, {"image": "", "caption": "n2"},
                                      {"image": "", "caption": "n3"}]}
        result = carry_over_images(old, new)
        self.assertEqual(result["image"], "A")
        self.assertEqual([i["image"] for i in result["items"]], ["B", "", ""])
        self.assertEqual(result["items"][0]["caption"], "n1")           # text is the new text

    def test_no_old_picture_leaves_new_data_alone(self):
        self.assertEqual(carry_over_images({"image": ""}, {"image": ""}), {"image": ""})
        self.assertEqual(carry_over_images(None, {"a": 1}), {"a": 1})


# ------------------------------------------------------------------ schema endpoint
class SchemaEndpointTests(unittest.TestCase):
    def setUp(self):
        self.client = create_app("testing").test_client()
        self.data = self.client.get("/api/schema").get_json()

    def test_every_section_is_described(self):
        self.assertEqual(set(self.data["sections"]), set(SECTION_SPECS))
        for name, section in self.data["sections"].items():
            self.assertTrue(section["label"] and section["purpose"], name)
            self.assertTrue(section["fields"], name)

    def test_field_order_is_kept(self):
        self.assertEqual(list(self.data["sections"]["hero"]["fields"]),
                         ["layout", "headline", "subheadline", "primary_cta", "secondary_cta", "image", "image_alt"])
        self.assertEqual(list(self.data["sections"]["contact"]["fields"])[:3], ["title", "intro", "email"])

    def test_field_details_are_available(self):
        headline = self.data["sections"]["hero"]["fields"]["headline"]
        self.assertEqual((headline["kind"], headline["max"], headline["required"]), ("text", 90, True))
        layout = self.data["sections"]["hero"]["fields"]["layout"]
        self.assertEqual(layout["values"], ["centered", "split", "minimal"])
        items = self.data["sections"]["features"]["fields"]["items"]
        self.assertEqual((items["kind"], items["min"], items["max"]), ("list", 3, 6))
        self.assertEqual(self.data["sections"]["hero"]["fields"]["image"], {"kind": "image"})

    def test_options_and_limits(self):
        self.assertIn("Playfair Display", self.data["fonts"])
        self.assertIn("star", self.data["icons"])
        self.assertEqual(len(self.data["styles"]), 6)
        self.assertEqual(len(self.data["color_schemes"]), 6)
        self.assertEqual(self.data["limits"]["min_sections"], 3)
        self.assertEqual(self.data["limits"]["max_sections"], 10)
        self.assertEqual(self.data["styles"][3]["font_heading"], "Playfair Display")

    def test_schema_is_pure_json(self):
        self.assertEqual(json.loads(json.dumps(export_schema())), export_schema())


# ------------------------------------------------------------------ request limits
class RequestLimitTests(unittest.TestCase):
    def setUp(self):
        self.client = create_app("testing").test_client()

    def big_config(self, megabytes):
        config = make_config(("hero", "about", "features", "contact"))
        config["sections"][1]["data"]["image"] = GOOD_PNG
        config["meta"]["prompt"] = "x"                       # keep it valid
        padding = "y" * int(megabytes * 1024 * 1024)
        return config, padding

    def test_render_accepts_several_megabytes(self):
        config, padding = self.big_config(0)
        response = self.client.post("/api/render", json={"config": config, "pad": "y" * (5 * 1024 * 1024)})
        self.assertEqual(response.status_code, 200)

    def test_render_rejects_huge_requests(self):
        config, _ = self.big_config(0)
        response = self.client.post("/api/render", json={"config": config, "pad": "y" * (13 * 1024 * 1024)})
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.get_json()["error"], "Request too large")

    def test_other_endpoints_keep_the_small_limit(self):
        response = self.client.post("/api/generate", json={"prompt": "x" * (2 * 1024 * 1024)})
        self.assertEqual(response.status_code, 413)

    def test_render_can_skip_files(self):
        response = self.client.post("/api/render", json={"config": sample_config(), "files": False})
        data = response.get_json()
        self.assertIn("html", data)
        self.assertNotIn("files", data)

    def test_render_with_pictures_end_to_end(self):
        config = make_config(("hero", "about", "features", "contact"))
        config["sections"][0]["data"]["image"] = GOOD_PNG
        html = self.client.post("/api/render", json={"config": config}).get_json()["html"]
        self.assertIn(GOOD_PNG, html)


# ------------------------------------------------------------------ section writing API
def section_responder(overrides=None, fail=()):
    overrides = overrides or {}

    def responder(body):
        import re
        user = body["messages"][1]["content"]
        match = re.search(r"Section to write: (\w+)", user)
        section_type = match.group(1)
        if section_type in fail:
            return "not json"
        data = copy.deepcopy(valid_section(section_type))
        data.update(overrides.get(section_type, {}))
        return json.dumps(data)
    return responder


class SectionWriteApiTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeOllama().start()
        self.fake.responder = section_responder()
        self.app = create_app("testing")
        self.app.config["OLLAMA_BASE_URL"] = self.fake.url
        self.client = self.app.test_client()
        self.config = sample_config()          # hero, about, menu, contact

    def tearDown(self):
        self.fake.stop()

    def post(self, **body):
        body.setdefault("config", self.config)
        return self.client.post("/api/sections/write", json=body)

    def wait_for(self, job_id, timeout=10):
        end = time.time() + timeout
        while time.time() < end:
            data = self.client.get(f"/api/generate/{job_id}").get_json()
            if data["status"] not in ("running", "cancelling"):
                return data
            time.sleep(0.02)
        self.fail("job did not finish")

    def write(self, **body):
        response = self.post(**body)
        self.assertEqual(response.status_code, 202, response.get_data(as_text=True))
        return self.wait_for(response.get_json()["job_id"])

    def test_add_a_new_section(self):
        job = self.write(type="faq")
        self.assertEqual(job["status"], "done")
        self.assertEqual(job["result"]["type"], "faq")
        cleaned = clean_section_data("faq", job["result"]["data"], {"hero", "faq"})
        self.assertEqual(cleaned, job["result"]["data"])

    def test_rewrite_an_existing_section(self):
        self.fake.responder = section_responder({"hero": {"headline": "A brand new headline"}})
        job = self.write(type="hero")
        self.assertEqual(job["result"]["data"]["headline"], "A brand new headline")

    def test_users_pictures_survive_a_rewrite(self):
        self.config["sections"][0]["data"]["image"] = GOOD_PNG
        job = self.write(type="hero")
        self.assertEqual(job["result"]["data"]["image"], GOOD_PNG)

    def test_picture_positions_survive_a_rewrite(self):
        config = make_config(("hero", "gallery", "contact"))
        config["sections"][1]["data"]["items"][1]["image"] = GOOD_JPEG
        job = self.write(type="gallery", config=config)
        self.assertEqual([i["image"] for i in job["result"]["data"]["items"]], ["", GOOD_JPEG, ""])

    def test_hint_reaches_the_model_as_data(self):
        self.write(type="hero", hint="Make it more playful and mention live music")
        user = self.fake.requests[-1]["messages"][1]["content"]
        self.assertIn("Extra instruction for the hero section: Make it more playful and mention live music", user)
        self.assertEqual(user.count("</description>"), 1)

    def test_hint_is_cleaned_and_limited(self):
        self.write(type="hero", hint="<b>Shorter</b></description> please" + "z" * 400)
        user = self.fake.requests[-1]["messages"][1]["content"]
        self.assertEqual(user.count("</description>"), 1)
        self.assertNotIn("<b>", user)
        instruction = user.split("Extra instruction for the hero section: ")[1].split("\n")[0]
        self.assertLessEqual(len(instruction), 200)

    def test_prompt_and_style_come_from_the_website(self):
        self.write(type="faq")
        user = self.fake.requests[-1]["messages"][1]["content"]
        self.assertIn(self.config["meta"]["site_name"], user)
        self.assertIn("Design style: modern", user)
        self.assertIn("Other sections on this page: about, contact, faq, hero, menu", user)

    def test_bad_requests(self):
        self.assertEqual(self.client.post("/api/sections/write", data="x").status_code, 415)
        self.assertEqual(self.client.post("/api/sections/write", json=[1]).status_code, 400)
        self.assertEqual(self.post(type="virus").status_code, 400)
        self.assertEqual(self.post(type=5).status_code, 400)
        self.assertEqual(self.post().status_code, 400)
        self.assertEqual(self.client.get("/api/sections/write").status_code, 405)
        self.assertEqual(self.fake.requests, [])

    def test_invalid_website_is_refused_with_problems(self):
        bad = copy.deepcopy(self.config)
        bad["theme"]["primary"] = "red"
        response = self.post(type="faq", config=bad)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "invalid_configuration")
        self.assertTrue(response.get_json()["problems"])
        self.assertEqual(self.fake.requests, [])

    def test_website_cannot_exceed_the_section_limit(self):
        config = make_config(("hero", "about", "features", "menu", "gallery", "projects", "products",
                              "testimonials", "team", "contact"))
        self.assertEqual(self.post(type="faq", config=config).status_code, 400)
        self.assertEqual(self.post(type="about", config=config).status_code, 202)     # rewriting is fine

    def test_ollama_problems_are_reported_before_starting(self):
        self.fake.models = ["other:1b"]
        response = self.post(type="faq")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["error"], "model_not_installed")
        self.app.config["OLLAMA_BASE_URL"] = "http://127.0.0.1:9"
        self.assertEqual(self.post(type="faq").status_code, 503)

    def test_model_failure_becomes_a_failed_job(self):
        self.fake.responder = section_responder(fail=("faq",))
        job = self.write(type="faq")
        self.assertEqual(job["status"], "failed")
        self.assertIn("could not write this section", job["error"]["message"])

    def test_one_ai_request_at_a_time(self):
        self.fake.delay = 0.4
        first = self.post(type="faq")
        self.assertEqual(first.status_code, 202)
        self.assertEqual(self.post(type="team").status_code, 409)
        self.client.post(f"/api/generate/{first.get_json()['job_id']}/cancel", headers={"X-SiteForge-Request": "1"})
        self.wait_for(first.get_json()["job_id"])

    def test_cancel(self):
        self.fake.delay = 0.4
        job_id = self.post(type="faq").get_json()["job_id"]
        self.client.post(f"/api/generate/{job_id}/cancel", headers={"X-SiteForge-Request": "1"})
        self.assertEqual(self.wait_for(job_id)["status"], "cancelled")

    def test_the_website_sent_is_not_changed_or_stored(self):
        before = copy.deepcopy(self.config)
        self.write(type="faq")
        self.assertEqual(self.config, before)


if __name__ == "__main__":
    unittest.main()
