"""Phase 3 tests: builder page, request validation, /api/generate."""
import unittest

from app import create_app
from app.services.design_options import (
    color_scheme_ids,
    get_color_schemes,
    get_design_styles,
    style_ids,
)
from app.services.generation_request import (
    PROMPT_MAX_LENGTH,
    PROMPT_MIN_LENGTH,
    validate_generation_request,
)

GOOD_PROMPT = "A late-night ramen bar in Cebu City with a menu and reservations."


def good_request(**changes):
    data = {"prompt": GOOD_PROMPT, "category": "restaurant",
            "design_style": "modern", "color_scheme": "blue"}
    data.update(changes)
    return data


class OptionTests(unittest.TestCase):
    def test_option_lists(self):
        self.assertEqual(len(get_design_styles()), 6)
        self.assertEqual(len(get_color_schemes()), 6)
        self.assertEqual(len(style_ids()), 6)
        self.assertEqual(len(color_scheme_ids()), 6)
        for scheme in get_color_schemes():
            self.assertRegex(scheme["primary"], r"^#[0-9a-f]{6}$")


class ValidationTests(unittest.TestCase):
    def test_valid_request(self):
        cleaned, errors = validate_generation_request(good_request())
        self.assertEqual(errors, {})
        self.assertEqual(cleaned["category"], "restaurant")

    def test_defaults_when_choices_missing(self):
        cleaned, errors = validate_generation_request({"prompt": GOOD_PROMPT})
        self.assertEqual(errors, {})
        self.assertEqual(cleaned["category"], "auto")
        self.assertEqual(cleaned["design_style"], "modern")
        self.assertEqual(cleaned["color_scheme"], "blue")

    def test_prompt_length_limits(self):
        _, errors = validate_generation_request(good_request(prompt="too short"))
        self.assertIn("prompt", errors)
        _, errors = validate_generation_request(good_request(prompt="x" * (PROMPT_MAX_LENGTH + 1)))
        self.assertIn("prompt", errors)
        _, errors = validate_generation_request(good_request(prompt="x" * PROMPT_MIN_LENGTH))
        self.assertEqual(errors, {})

    def test_whitespace_only_prompt_rejected(self):
        _, errors = validate_generation_request(good_request(prompt=" " * 50))
        self.assertIn("prompt", errors)

    def test_control_characters_removed(self):
        cleaned, _ = validate_generation_request(good_request(prompt="Ramen bar\x00 with a menu\x07 and hours"))
        self.assertNotIn("\x00", cleaned["prompt"])
        self.assertNotIn("\x07", cleaned["prompt"])

    def test_unknown_choices_rejected(self):
        for field, value in (("category", "hacker"), ("design_style", "neon"), ("color_scheme", "pink")):
            _, errors = validate_generation_request(good_request(**{field: value}))
            self.assertIn(field, errors)

    def test_wrong_types_rejected(self):
        for bad in (123, None, ["a"], {"a": 1}):
            _, errors = validate_generation_request(good_request(prompt=bad))
            self.assertIn("prompt", errors)
            _, errors = validate_generation_request(good_request(category=bad))
            self.assertIn("category", errors)
        _, errors = validate_generation_request(["not", "a", "dict"])
        self.assertIn("request", errors)


class BuilderPageTests(unittest.TestCase):
    def setUp(self):
        self.client = create_app("testing").test_client()

    def test_form_has_all_controls(self):
        html = self.client.get("/builder").get_data(as_text=True)
        for needle in ('id="generator-form"', 'id="prompt"', 'id="generate-button"',
                       'name="category"', 'name="design_style"', 'name="color_scheme"',
                       'data-state="loading"', 'data-state="error"', "js/builder.js"):
            self.assertIn(needle, html)
        self.assertEqual(html.count('name="category"'), 9)       # auto + 8 types
        self.assertEqual(html.count('name="design_style"'), 6)
        self.assertEqual(html.count('name="color_scheme"'), 6)

    def test_defaults_are_checked(self):
        html = self.client.get("/builder").get_data(as_text=True)
        self.assertRegex(html, r'value="modern"[^>]*checked')
        self.assertRegex(html, r'value="blue"[^>]*checked')

    def test_builder_script_served(self):
        response = self.client.get("/static/js/builder.js")
        self.assertEqual(response.status_code, 200)
        response.close()


class GenerateApiTests(unittest.TestCase):
    def setUp(self):
        self.client = create_app("testing").test_client()

    def test_non_json_rejected(self):
        response = self.client.post("/api/generate", data={"prompt": GOOD_PROMPT})
        self.assertEqual(response.status_code, 415)
        self.assertEqual(response.get_json()["error"], "unsupported_media_type")

    def test_malformed_json_gives_validation_error(self):
        response = self.client.post("/api/generate", data="{bad", content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "validation_failed")

    def test_invalid_fields_return_field_messages(self):
        response = self.client.post("/api/generate", json=good_request(prompt="short", design_style="neon"))
        self.assertEqual(response.status_code, 400)
        fields = response.get_json()["fields"]
        self.assertIn("prompt", fields)
        self.assertIn("design_style", fields)

    def test_valid_request_with_ollama_offline_reports_unavailable(self):
        response = self.client.post("/api/generate", json=good_request())
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["error"], "ollama_unavailable")

    def test_get_not_allowed(self):
        self.assertEqual(self.client.get("/api/generate").status_code, 405)

    def test_oversized_body_rejected(self):
        response = self.client.post("/api/generate", json=good_request(prompt="x" * (2 * 1024 * 1024)))
        self.assertEqual(response.status_code, 413)


if __name__ == "__main__":
    unittest.main()
