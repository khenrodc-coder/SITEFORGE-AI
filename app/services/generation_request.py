"""Validation of the data the builder sends to /api/generate.

Nothing from the browser is trusted. This module cleans the text and checks
every choice against the known lists before any other code sees it.
"""
import re

from app.services.design_options import (
    DEFAULT_COLOR_SCHEME,
    DEFAULT_STYLE,
    color_scheme_ids,
    style_ids,
)
from app.services.template_catalog import get_category

PROMPT_MIN_LENGTH = 20
PROMPT_MAX_LENGTH = 1000
AUTO_CATEGORY = "auto"   # "let the AI decide"

# Control characters other than tab and newline.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _clean_prompt(text):
    text = _CONTROL_CHARS.sub("", text).replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def validate_generation_request(data):
    """Return (cleaned_data, errors).

    errors is a dict of {field_name: message}. When it is not empty,
    cleaned_data is None.
    """
    if not isinstance(data, dict):
        return None, {"request": "The request must be a JSON object."}

    errors = {}
    cleaned = {}

    prompt = data.get("prompt")
    if not isinstance(prompt, str):
        errors["prompt"] = "Describe the website you want."
    else:
        prompt = _clean_prompt(prompt)
        if len(prompt) < PROMPT_MIN_LENGTH:
            errors["prompt"] = f"Describe your website in at least {PROMPT_MIN_LENGTH} characters."
        elif len(prompt) > PROMPT_MAX_LENGTH:
            errors["prompt"] = f"Keep the description under {PROMPT_MAX_LENGTH} characters."
        else:
            cleaned["prompt"] = prompt

    category = data.get("category", AUTO_CATEGORY)
    if category == AUTO_CATEGORY or (isinstance(category, str) and get_category(category)):
        cleaned["category"] = category
    else:
        errors["category"] = "Choose a website type from the list."

    style = data.get("design_style", DEFAULT_STYLE)
    if isinstance(style, str) and style in style_ids():
        cleaned["design_style"] = style
    else:
        errors["design_style"] = "Choose a design style from the list."

    color = data.get("color_scheme", DEFAULT_COLOR_SCHEME)
    if isinstance(color, str) and color in color_scheme_ids():
        cleaned["color_scheme"] = color
    else:
        errors["color_scheme"] = "Choose a color scheme from the list."

    if errors:
        return None, errors
    return cleaned, {}
