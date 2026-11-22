"""Design styles and color schemes offered in the builder.

The ids here are the only values the server accepts from the browser.
"""

DEFAULT_STYLE = "modern"
DEFAULT_COLOR_SCHEME = "blue"

_DESIGN_STYLES = (
    {"id": "modern", "name": "Modern", "icon": "fa-shapes",
     "description": "Clean lines, generous space, confident type."},
    {"id": "minimal", "name": "Minimal", "icon": "fa-feather",
     "description": "Quiet and spare. Content does the talking."},
    {"id": "bold", "name": "Bold", "icon": "fa-bolt",
     "description": "Large type and strong contrast that stands out."},
    {"id": "elegant", "name": "Elegant", "icon": "fa-gem",
     "description": "Refined and calm, with a premium feel."},
    {"id": "playful", "name": "Playful", "icon": "fa-face-smile",
     "description": "Friendly shapes and a lively, approachable tone."},
    {"id": "corporate", "name": "Corporate", "icon": "fa-building",
     "description": "Structured and trustworthy for professional services."},
)

_COLOR_SCHEMES = (
    {"id": "blue", "name": "Blue", "primary": "#2563eb"},
    {"id": "emerald", "name": "Emerald", "primary": "#059669"},
    {"id": "violet", "name": "Violet", "primary": "#7c3aed"},
    {"id": "rose", "name": "Rose", "primary": "#e11d48"},
    {"id": "amber", "name": "Amber", "primary": "#d97706"},
    {"id": "slate", "name": "Slate", "primary": "#334155"},
)


def get_design_styles():
    return [dict(item) for item in _DESIGN_STYLES]


def get_color_schemes():
    return [dict(item) for item in _COLOR_SCHEMES]


def style_ids():
    return {item["id"] for item in _DESIGN_STYLES}


def color_scheme_ids():
    return {item["id"] for item in _COLOR_SCHEMES}
