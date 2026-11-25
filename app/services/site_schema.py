"""The website configuration format: section definitions and validation.

A generated website is plain data ("the configuration"). It is never code.
Every value that comes from the AI, or later from the editor or the database,
goes through this module, which:

* keeps only known fields (everything else is dropped),
* strips HTML tags and control characters from all text,
* cuts text to its maximum length,
* replaces unknown icons, layouts, and link targets with safe defaults,
* only allows links that point to a section of the same page.

The renderer (Phase 6) can therefore trust whatever this module returns.
"""
import base64
import binascii
import json
import re

from app.services.design_options import (
    FONTS,
    RADII,
    THEME_MODES,
    color_scheme_ids,
    get_color_schemes,
    get_design_styles,
    style_ids,
)
from app.services.template_catalog import get_category

CONFIG_VERSION = 1
MIN_SECTIONS = 3
MAX_SECTIONS = 10

ICONS = (
    "star", "bolt", "shield-halved", "heart", "leaf", "clock", "users", "chart-line",
    "lightbulb", "wrench", "truck", "phone", "envelope", "location-dot", "camera",
    "palette", "code", "mug-hot", "utensils", "bag-shopping", "gift", "globe", "lock",
    "rocket", "award", "check", "hammer", "graduation-cap", "handshake", "book-open",
)
DEFAULT_ICON = "star"

# Uploaded pictures are stored inside the configuration as data addresses.
IMAGE_MAX_CHARS = 700_000            # per picture (about 500 KB of image data)
TOTAL_IMAGE_MAX_CHARS = 8_000_000    # all pictures of one website together
_IMAGE_TYPES = ("png", "jpeg", "webp", "gif")        # SVG is left out on purpose: it can contain scripts
_IMAGE_SIGNATURES = {
    "png": lambda head: head.startswith(b"\x89PNG\r\n\x1a\n"),
    "jpeg": lambda head: head.startswith(b"\xff\xd8\xff"),
    "gif": lambda head: head[:6] in (b"GIF87a", b"GIF89a"),
    "webp": lambda head: head[:4] == b"RIFF" and head[8:12] == b"WEBP",
}


class SchemaError(ValueError):
    """Raised when data cannot be turned into a valid configuration."""

    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("; ".join(self.problems[:5]))


# ---------------------------------------------------------------- text cleaning
_TAG = re.compile(r"<[^>]*>")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_EMAIL = re.compile(r"^[^@\s<>]{1,64}@[^@\s<>]{1,120}\.[^@\s<>]{2,}$")
_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_SECTION_ID = re.compile(r"^[a-z][a-z0-9-]{0,30}$")


def clean_text(value, max_length):
    """Return safe single-line text, or "" when the value is not text."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return ""
    text = _TAG.sub(" ", str(value))
    text = text.replace("<", " ").replace(">", " ")
    text = _CONTROL.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_length:
        text = text[:max_length].rstrip()
    return text


def clean_image(value):
    """Return the picture if it is a genuine PNG, JPEG, WebP, or GIF data address, otherwise ""."""
    if not isinstance(value, str) or len(value) > IMAGE_MAX_CHARS:
        return ""
    for kind in _IMAGE_TYPES:
        prefix = f"data:image/{kind};base64,"
        if value.startswith(prefix):
            try:
                raw = base64.b64decode(value[len(prefix):], validate=True)
            except (binascii.Error, ValueError):
                return ""
            return value if _IMAGE_SIGNATURES[kind](raw[:16]) else ""
    return ""


def _image_chars(value):
    """Total length of all pictures stored anywhere inside `value`."""
    if isinstance(value, dict):
        return sum(len(v) if key == "image" and isinstance(v, str) else _image_chars(v) for key, v in value.items())
    if isinstance(value, list):
        return sum(_image_chars(item) for item in value)
    return 0


# ---------------------------------------------------------------- field builders
def text(max_length, required=True):
    return {"kind": "text", "max": max_length, "required": required}


def enum(values, default):
    return {"kind": "enum", "values": tuple(values), "default": default}


def boolean(default=False):
    return {"kind": "bool", "default": default}


def obj(**fields):
    return {"kind": "object", "fields": fields}


def items(item, minimum, maximum):
    return {"kind": "list", "item": item, "min": minimum, "max": maximum}


ICON = {"kind": "icon"}
EMAIL = {"kind": "email"}
PHONE = {"kind": "phone"}
PRICE = {"kind": "price"}
TARGET = {"kind": "target"}
IMAGE = {"kind": "image"}

# ---------------------------------------------------------------- section types
SECTION_SPECS = {
    "hero": {
        "label": "Home", "nav": False, "max_tokens": 450,
        "purpose": "the opening banner: a strong headline, one supporting sentence, and calls to action",
        "fields": {
            "layout": enum(["centered", "split", "minimal"], "split"),
            "headline": text(90),
            "subheadline": text(220),
            "primary_cta": obj(label=text(30), target=TARGET),
            "secondary_cta": obj(label=text(30, required=False), target=TARGET),
            "image": IMAGE,
            "image_alt": text(120, required=False),
        },
    },
    "about": {
        "label": "About", "nav": True, "max_tokens": 500,
        "purpose": "who is behind the website and what they stand for",
        "fields": {
            "layout": enum(["text", "split"], "split"),
            "title": text(60),
            "body": items(text(400), 1, 3),
            "highlights": items(text(60), 0, 4),
            "image": IMAGE,
            "image_alt": text(120, required=False),
        },
    },
    "features": {
        "label": "Features", "nav": True, "max_tokens": 650,
        "purpose": "the main services, benefits, skills, or features",
        "fields": {
            "layout": enum(["grid", "list"], "grid"),
            "title": text(60),
            "intro": text(200, required=False),
            "items": items(obj(icon=ICON, title=text(50), description=text(160)), 3, 6),
        },
    },
    "menu": {
        "label": "Menu", "nav": True, "max_tokens": 900,
        "purpose": "a menu of food or drinks grouped into categories, with prices",
        "fields": {
            "title": text(60),
            "intro": text(200, required=False),
            "categories": items(obj(
                name=text(40),
                items=items(obj(name=text(60), description=text(120, required=False), price=PRICE), 2, 6),
            ), 1, 4),
        },
    },
    "gallery": {
        "label": "Gallery", "nav": True, "max_tokens": 450,
        "purpose": "a photo gallery with short captions",
        "fields": {
            "title": text(60),
            "intro": text(200, required=False),
            "items": items(obj(caption=text(80), image=IMAGE, image_alt=text(120, required=False)), 3, 8),
        },
    },
    "projects": {
        "label": "Work", "nav": True, "max_tokens": 650,
        "purpose": "selected projects, case studies, or past work",
        "fields": {
            "layout": enum(["grid", "list"], "grid"),
            "title": text(60),
            "intro": text(200, required=False),
            "items": items(obj(
                title=text(60), category=text(40, required=False),
                description=text(200), image=IMAGE, image_alt=text(120, required=False),
            ), 3, 6),
        },
    },
    "products": {
        "label": "Shop", "nav": True, "max_tokens": 800,
        "purpose": "products for sale with a short description and price",
        "fields": {
            "title": text(60),
            "intro": text(200, required=False),
            "items": items(obj(
                name=text(60), description=text(140, required=False), price=PRICE,
                badge=text(20, required=False), image=IMAGE, image_alt=text(120, required=False),
            ), 3, 8),
        },
    },
    "testimonials": {
        "label": "Reviews", "nav": True, "max_tokens": 450,
        "purpose": "short quotes from customers or clients",
        "fields": {
            "title": text(60),
            "items": items(obj(quote=text(260), name=text(50), role=text(60, required=False)), 2, 4),
        },
    },
    "team": {
        "label": "Team", "nav": True, "max_tokens": 600,
        "purpose": "the people behind the business",
        "fields": {
            "layout": enum(["grid", "list"], "grid"),
            "title": text(60),
            "intro": text(200, required=False),
            "members": items(obj(name=text(50), role=text(60), bio=text(200, required=False)), 2, 6),
        },
    },
    "pricing": {
        "label": "Pricing", "nav": True, "max_tokens": 800,
        "purpose": "two to four pricing plans",
        "fields": {
            "title": text(60),
            "intro": text(200, required=False),
            "plans": items(obj(
                name=text(40), price=PRICE, period=text(20, required=False),
                description=text(120, required=False),
                features=items(text(80), 2, 6),
                highlighted=boolean(False),
                cta_label=text(30, required=False),
            ), 2, 4),
        },
    },
    "faq": {
        "label": "FAQ", "nav": True, "max_tokens": 700,
        "purpose": "answers to common questions",
        "fields": {
            "title": text(60),
            "items": items(obj(question=text(120), answer=text(400)), 3, 6),
        },
    },
    "contact": {
        "label": "Contact", "nav": True, "max_tokens": 450,
        "purpose": "how to reach the business: email, phone, address, and opening hours",
        "fields": {
            "title": text(60),
            "intro": text(200, required=False),
            "email": EMAIL,
            "phone": PHONE,
            "address": text(160, required=False),
            "hours": items(obj(days=text(40), time=text(40)), 0, 7),
            "show_form": boolean(True),
        },
    },
    "cta": {
        "label": "Get started", "nav": False, "max_tokens": 250,
        "purpose": "a closing call to action that asks the visitor to take one step",
        "fields": {
            "headline": text(90),
            "text": text(220, required=False),
            "button_label": text(30),
            "target": TARGET,
        },
    },
    "posts": {
        "label": "Posts", "nav": True, "max_tokens": 700,
        "purpose": "featured and recent blog posts with a short excerpt",
        "fields": {
            "layout": enum(["grid", "list"], "list"),
            "title": text(60),
            "intro": text(200, required=False),
            "items": items(obj(
                title=text(100), excerpt=text(220),
                category=text(30, required=False), date=text(20, required=False),
            ), 3, 6),
        },
    },
}


# ---------------------------------------------------------------- cleaning engine
def _fallback_target(own_type, targets):
    """Where a broken button should point instead."""
    for preferred in ("contact", "cta"):
        if preferred in targets and preferred != own_type:
            return preferred
    for candidate in sorted(targets):
        if candidate != own_type:
            return candidate
    return own_type


def _clean(spec, value, path, context, problems):
    kind = spec["kind"]

    if kind == "text":
        cleaned = clean_text(value, spec["max"])
        if not cleaned and spec["required"]:
            problems.append(f"{path} is required")
        return cleaned

    if kind == "enum":
        return value if isinstance(value, str) and value in spec["values"] else spec["default"]

    if kind == "bool":
        return value if isinstance(value, bool) else spec["default"]

    if kind == "icon":
        return value if isinstance(value, str) and value in ICONS else DEFAULT_ICON

    if kind == "email":
        cleaned = clean_text(value, 120)
        return cleaned if _EMAIL.match(cleaned) else ""

    if kind == "phone":
        cleaned = re.sub(r"[^0-9+()\-\s.]", "", clean_text(value, 40)).strip()[:24]
        return cleaned if sum(ch.isdigit() for ch in cleaned) >= 5 else ""

    if kind == "price":
        return clean_text(value, 16)

    if kind == "image":
        return clean_image(value)

    if kind == "target":
        cleaned = clean_text(value, 40).lstrip("#")
        return cleaned if cleaned in context["targets"] else context["fallback"]

    if kind == "object":
        source = value if isinstance(value, dict) else {}
        if not isinstance(value, dict):
            problems.append(f"{path} must be an object")
        return {
            name: _clean(sub, source.get(name), f"{path}.{name}", context, problems)
            for name, sub in spec["fields"].items()
        }

    if kind == "list":
        if not isinstance(value, list):
            problems.append(f"{path} must be a list")
            return []
        result = []
        for index, entry in enumerate(value):
            local_problems = []
            cleaned = _clean(spec["item"], entry, f"{path}[{index}]", context, local_problems)
            if local_problems:
                continue                      # drop broken entries instead of failing everything
            if spec["item"]["kind"] == "text" and not cleaned:
                continue
            result.append(cleaned)
            if len(result) >= spec["max"]:
                break
        if len(result) < spec["min"]:
            problems.append(f"{path} needs at least {spec['min']} entries")
        return result

    raise ValueError(f"unknown field kind: {kind}")   # a bug in this file, not bad input


def clean_section_data(section_type, raw, targets):
    """Validate and clean the content of one section. Raises SchemaError."""
    if section_type not in SECTION_SPECS:
        raise SchemaError([f"unknown section type: {section_type}"])
    context = {"targets": set(targets), "fallback": _fallback_target(section_type, set(targets))}
    problems = []
    spec = {"kind": "object", "fields": SECTION_SPECS[section_type]["fields"]}
    cleaned = _clean(spec, raw, section_type, context, problems)
    if problems:
        raise SchemaError(problems)
    return cleaned


# ---------------------------------------------------------------- prompt helper
def describe_shape(section_type, targets):
    """Return (shape_text, notes) describing the JSON the model must write."""
    notes = []

    def walk(spec, path):
        kind = spec["kind"]
        if kind == "text":
            return f"text, up to {spec['max']} characters" + ("" if spec["required"] else " (may be empty)")
        if kind == "enum":
            return "one of: " + ", ".join(spec["values"])
        if kind == "icon":
            return "one of: " + ", ".join(ICONS)
        if kind == "bool":
            return "true or false"
        if kind == "email":
            return "email address"
        if kind == "phone":
            return "phone number"
        if kind == "price":
            return "price with currency symbol, such as $12.50 (may be empty)"
        if kind == "target":
            return "one of: " + ", ".join(sorted(targets))
        if kind == "object":
            return {name: walk(sub, f"{path}.{name}" if path else name)
                    for name, sub in spec["fields"].items() if sub["kind"] != "image"}
        if kind == "list":
            notes.append(f'"{path}": {spec["min"]} to {spec["max"]} entries')
            return [walk(spec["item"], path)]
        raise ValueError(kind)

    shape = walk({"kind": "object", "fields": SECTION_SPECS[section_type]["fields"]}, "")
    return json.dumps(shape, indent=1), notes


# ---------------------------------------------------------------- whole configuration
def _clean_meta(raw, problems):
    source = raw if isinstance(raw, dict) else {}
    if not isinstance(raw, dict):
        problems.append("meta must be an object")

    meta = {
        "site_name": clean_text(source.get("site_name"), 60),
        "tagline": clean_text(source.get("tagline"), 140),
        "category": source.get("category"),
        "design_style": source.get("design_style"),
        "color_scheme": source.get("color_scheme"),
        "prompt": clean_text(source.get("prompt"), 1000),
        "language": "en",
    }
    if not meta["site_name"]:
        problems.append("meta.site_name is required")
    if not meta["tagline"]:
        problems.append("meta.tagline is required")
    if not (isinstance(meta["category"], str) and get_category(meta["category"])):
        problems.append("meta.category is not a known website type")
    if meta["design_style"] not in style_ids():
        problems.append("meta.design_style is not a known style")
    if meta["color_scheme"] not in color_scheme_ids():
        problems.append("meta.color_scheme is not a known color scheme")
    return meta


def _clean_theme(raw, problems):
    source = raw if isinstance(raw, dict) else {}
    if not isinstance(raw, dict):
        problems.append("theme must be an object")

    primary = source.get("primary")
    if not (isinstance(primary, str) and _HEX_COLOR.match(primary)):
        problems.append("theme.primary must be a color like #2563eb")
        primary = ""
    theme = {
        "primary": primary.lower(),
        "font_heading": source.get("font_heading"),
        "font_body": source.get("font_body"),
        "radius": source.get("radius"),
        "mode": source.get("mode", "light"),
    }
    for key in ("font_heading", "font_body"):
        if theme[key] not in FONTS:
            problems.append(f"theme.{key} is not an allowed font")
    if theme["radius"] not in RADII:
        problems.append("theme.radius is not allowed")
    if theme["mode"] not in THEME_MODES:
        problems.append("theme.mode is not allowed")
    return theme


def validate_site_config(raw):
    """Check a complete website configuration and return a cleaned copy.

    Used after generation, and again whenever a configuration is loaded
    from the editor or the database. Raises SchemaError.
    """
    if not isinstance(raw, dict):
        raise SchemaError(["the configuration must be an object"])

    problems = []
    if raw.get("version") != CONFIG_VERSION:
        problems.append(f"version must be {CONFIG_VERSION}")

    meta = _clean_meta(raw.get("meta"), problems)
    theme = _clean_theme(raw.get("theme"), problems)

    raw_sections = raw.get("sections")
    if not isinstance(raw_sections, list) or not (MIN_SECTIONS <= len(raw_sections) <= MAX_SECTIONS):
        problems.append(f"sections must be a list of {MIN_SECTIONS} to {MAX_SECTIONS} sections")
        raw_sections = []

    # First pass: identity of every section, so buttons can be checked against real ids.
    skeleton = []
    seen_ids = set()
    seen_types = set()
    for index, entry in enumerate(raw_sections):
        if not isinstance(entry, dict):
            problems.append(f"sections[{index}] must be an object")
            continue
        section_type = entry.get("type")
        section_id = entry.get("id")
        if section_type not in SECTION_SPECS:
            problems.append(f"sections[{index}].type is not a known section type")
            continue
        if section_type in seen_types:
            problems.append(f"sections[{index}]: each section type may appear only once")
            continue
        if not (isinstance(section_id, str) and _SECTION_ID.match(section_id)) or section_id in seen_ids:
            problems.append(f"sections[{index}].id is missing, invalid, or repeated")
            continue
        seen_types.add(section_type)
        seen_ids.add(section_id)
        skeleton.append((entry, section_type, section_id))

    if skeleton and skeleton[0][1] != "hero":
        problems.append("the first section must be the hero")

    sections = []
    for entry, section_type, section_id in skeleton:
        spec = SECTION_SPECS[section_type]
        nav = entry.get("nav", spec["nav"])
        try:
            data = clean_section_data(section_type, entry.get("data"), seen_ids)
        except SchemaError as exc:
            problems.extend(f"{section_id}: {problem}" for problem in exc.problems)
            continue
        sections.append({
            "id": section_id,
            "type": section_type,
            "nav": nav if isinstance(nav, bool) else spec["nav"],
            "nav_label": clean_text(entry.get("nav_label"), 30) or spec["label"],
            "data": data,
        })

    image_total = sum(_image_chars(section["data"]) for section in sections)
    if image_total > TOTAL_IMAGE_MAX_CHARS:
        problems.append("the pictures are too large in total; remove or shrink some")

    footer_source = raw.get("footer") if isinstance(raw.get("footer"), dict) else {}
    footer = {"tagline": clean_text(footer_source.get("tagline"), 140) or meta["tagline"]}

    if problems:
        raise SchemaError(problems)
    return {"version": CONFIG_VERSION, "meta": meta, "theme": theme, "sections": sections, "footer": footer}


# ---------------------------------------------------------------- export for the editor
def _plain(value):
    """Turn tuples into lists so the structure can be sent as JSON."""
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def export_schema():
    """Everything the editor needs to build its forms, as plain JSON-ready data."""
    return {
        "version": CONFIG_VERSION,
        "sections": {
            name: {"label": spec["label"], "nav": spec["nav"], "purpose": spec["purpose"],
                   "fields": _plain(spec["fields"])}
            for name, spec in SECTION_SPECS.items()
        },
        "icons": list(ICONS),
        "fonts": list(FONTS),
        "radii": list(RADII),
        "modes": list(THEME_MODES),
        "styles": [{key: item[key] for key in ("id", "name", "font_heading", "font_body", "radius")}
                   for item in get_design_styles()],
        "color_schemes": get_color_schemes(),
        "limits": {
            "min_sections": MIN_SECTIONS,
            "max_sections": MAX_SECTIONS,
            "image_max_chars": IMAGE_MAX_CHARS,
            "total_image_max_chars": TOTAL_IMAGE_MAX_CHARS,
        },
    }
