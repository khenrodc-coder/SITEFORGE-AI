"""Turns a website configuration into real website files.

The page markup comes only from our own templates in app/templates/site/.
The configuration is passed to them as data and HTML-escaped on output, so
nothing the AI (or a user) writes can become code. The configuration is
validated again here, so the renderer is safe even if called with raw data.
"""
import hashlib
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from jinja2 import FileSystemLoader
from jinja2.sandbox import SandboxedEnvironment
from markupsafe import Markup, escape

from app.services.site_schema import validate_site_config

SITE_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "site"

SERIF_FONTS = {"Playfair Display", "Merriweather", "Lora"}
RADIUS_VALUES = {            # (normal, large)
    "none": ("0px", "0px"),
    "sm": ("6px", "10px"),
    "md": ("12px", "18px"),
    "lg": ("18px", "26px"),
    "xl": ("26px", "36px"),
}


# ---------------------------------------------------------------- color maths
def _hex_to_rgb(color):
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def _rgb_to_hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(c))) for c in rgb)


def mix(color_a, color_b, amount):
    """Blend two colors. amount=0 gives color_a, amount=1 gives color_b."""
    a, b = _hex_to_rgb(color_a), _hex_to_rgb(color_b)
    return _rgb_to_hex(tuple(a[i] + (b[i] - a[i]) * amount for i in range(3)))


def luminance(color):
    def channel(value):
        value /= 255
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in _hex_to_rgb(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(color_a, color_b):
    lighter, darker = sorted((luminance(color_a), luminance(color_b)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def ensure_contrast(color, backgrounds, minimum=4.5):
    """Darken or lighten `color` until it is readable on every background."""
    average = sum(luminance(bg) for bg in backgrounds) / len(backgrounds)
    target = "#000000" if average > 0.4 else "#ffffff"
    for step in range(21):
        candidate = mix(color, target, step / 20)
        if all(contrast(candidate, bg) >= minimum for bg in backgrounds):
            return candidate
    return target


def best_text_on(background):
    """White or black, whichever is easier to read on `background`."""
    white, black = "#ffffff", "#0f172a"
    if contrast(white, background) >= 4.5:
        return white
    return black if contrast(black, background) >= contrast(white, background) else white


def build_palette(theme, style_id):
    """Every color the site uses, derived from the primary color and the mode."""
    primary = theme["primary"]
    if theme["mode"] == "dark":
        bg, surface, text, muted, border = "#0b1220", "#111a2e", "#f1f5f9", "#cbd5e1", "#26324d"
        soft = mix(bg, primary, 0.22)
    elif style_id == "elegant":
        bg, surface, text, muted, border = "#faf7f2", "#f3eee6", "#0f172a", "#475569", "#e0d8ca"
        soft = mix(bg, primary, 0.12)
    else:
        bg, surface, text, muted, border = "#ffffff", "#f8fafc", "#0f172a", "#475569", "#e2e8f0"
        soft = mix(bg, primary, 0.12)

    on_primary = best_text_on(primary)
    palette = {
        "primary": primary,
        "primary_text": ensure_contrast(primary, [bg, surface, soft]),
        "primary_soft": soft,
        "on_primary": on_primary,
        "cta_button_text": ensure_contrast(primary, [on_primary]),
        "bg": bg, "surface": surface, "text": text, "muted": muted, "border": border,
    }
    if style_id == "bold":
        palette.update(hero_bg=mix(primary, "#000000", 0.78), hero_text="#ffffff", hero_muted="#e2e8f0")
    else:
        palette.update(hero_bg=soft, hero_text=text, hero_muted=muted)
    return palette


# ---------------------------------------------------------------- CSS / fonts
def font_stack(name):
    fallback = 'Georgia, "Times New Roman", serif' if name in SERIF_FONTS \
        else 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif'
    return f'"{name}", {fallback}'


def fonts_url(theme):
    names = []
    for name in (theme["font_heading"], theme["font_body"]):
        if name not in names:
            names.append(name)
    families = "&".join(f"family={quote_plus(name)}:wght@400;700" for name in names)
    return f"https://fonts.googleapis.com/css2?{families}&display=swap"


def build_variables_css(theme, style_id):
    """The :root block. Every value comes from validated, whitelisted data."""
    p = build_palette(theme, style_id)
    radius, radius_large = RADIUS_VALUES[theme["radius"]]
    pairs = [
        ("primary", p["primary"]), ("primary-text", p["primary_text"]), ("primary-soft", p["primary_soft"]),
        ("on-primary", p["on_primary"]), ("cta-button-text", p["cta_button_text"]),
        ("bg", p["bg"]), ("surface", p["surface"]), ("text", p["text"]), ("muted", p["muted"]),
        ("border", p["border"]), ("hero-bg", p["hero_bg"]), ("hero-text", p["hero_text"]),
        ("hero-muted", p["hero_muted"]), ("radius", radius), ("radius-lg", radius_large),
        ("font-heading", font_stack(theme["font_heading"])), ("font-body", font_stack(theme["font_body"])),
    ]
    body = ";".join(f"--{name}:{value}" for name, value in pairs)
    scheme = "dark" if theme["mode"] == "dark" else "light"
    return f":root{{{body};color-scheme:{scheme}}}\n"


@lru_cache(maxsize=1)
def _static_asset(name):
    return (SITE_TEMPLATE_DIR / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------- template helpers
def placeholder(seed, alt=""):
    """A decorative image stand-in (inline SVG) that differs for every `seed`."""
    digest = hashlib.sha256(str(seed).encode("utf-8")).digest()

    def pick(index, low, high):
        return round(low + digest[index] / 255 * (high - low), 1)

    label = f'role="img" aria-label="{escape(alt)}"' if alt else 'aria-hidden="true"'
    return Markup(
        f'<svg class="ph" viewBox="0 0 400 300" preserveAspectRatio="xMidYMid slice" {label} focusable="false">'
        '<rect width="400" height="300" style="fill:var(--primary-soft)"/>'
        f'<circle cx="{pick(0, 80, 320)}" cy="{pick(1, 60, 240)}" r="{pick(2, 60, 110)}" style="fill:var(--primary);opacity:.16"/>'
        f'<rect x="{pick(3, 10, 240)}" y="{pick(4, 10, 150)}" width="{pick(5, 90, 200)}" height="{pick(6, 70, 160)}" '
        f'rx="14" transform="rotate({pick(7, -25, 25)} 200 150)" style="fill:var(--primary);opacity:.11"/>'
        f'<circle cx="{pick(8, 40, 360)}" cy="{pick(9, 30, 270)}" r="{pick(10, 18, 46)}" style="fill:var(--primary);opacity:.24"/>'
        '<path d="M148 196 L188 132 L214 168 L234 142 L272 196 Z" style="fill:var(--primary);opacity:.5"/>'
        '<circle cx="246" cy="110" r="12" style="fill:var(--primary);opacity:.5"/>'
        '</svg>'
    )


def initials(name):
    return "".join(word[0] for word in str(name).split()[:2]).upper()


def tel_digits(phone):
    return re.sub(r"[^0-9+]", "", str(phone))


@lru_cache(maxsize=1)
def _environment():
    env = SandboxedEnvironment(
        loader=FileSystemLoader(str(SITE_TEMPLATE_DIR)),
        autoescape=True,          # every {{ value }} is HTML-escaped
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.globals["placeholder"] = placeholder
    env.filters["initials"] = initials
    env.filters["tel"] = tel_digits
    return env


# ---------------------------------------------------------------- main entry point
def render_website(config, year=None, preview=False):
    """Return {"files": {path: text}, "html": single_file_text} for a configuration.

    preview=True adds a base address that keeps in-page links working when the
    page is shown inside the sandboxed preview frame. It only affects "html".

    Raises SchemaError when the configuration is not valid.
    """
    config = validate_site_config(config)
    theme, meta = config["theme"], config["meta"]
    style_id = meta["design_style"]

    sections = []
    content_index = 0
    for entry in config["sections"]:
        view = dict(entry)
        view["alt"] = False
        if entry["type"] not in ("hero", "cta"):
            view["alt"] = content_index % 2 == 1
            content_index += 1
        sections.append(view)

    section_ids = [s["id"] for s in sections]
    fallback = "contact" if "contact" in section_ids else ("cta" if "cta" in section_ids else section_ids[0])

    css = build_variables_css(theme, style_id) + _static_asset("site.css")
    js = _static_asset("site.js")

    context = {
        "meta": meta,
        "theme": theme,
        "footer": config["footer"],
        "sections": sections,
        "nav_items": [s for s in sections if s["nav"]],
        "section_ids": section_ids,
        "fallback_target": fallback,
        "year": year or datetime.now().year,
        "fonts_url": fonts_url(theme),
        "css": Markup(css),
        "js": Markup(js),
    }
    template = _environment().get_template("base.html")
    return {
        "files": {
            "index.html": template.render(inline=False, preview=False, **context),
            "css/styles.css": css,
            "js/main.js": js,
        },
        "html": template.render(inline=True, preview=preview, **context),
    }
