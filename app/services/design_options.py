"""Design styles, color schemes, and fonts offered in the builder.

The ids here are the only values the server accepts from the browser or the AI.
"""

DEFAULT_STYLE = "modern"
DEFAULT_COLOR_SCHEME = "blue"

# Google Fonts that generated websites may use.
FONTS = (
    "Space Grotesk", "DM Sans", "Inter", "Archivo", "Playfair Display", "Lato",
    "Fredoka", "Nunito", "IBM Plex Sans", "Merriweather", "Poppins",
    "Montserrat", "Lora", "Work Sans",
)
RADII = ("none", "sm", "md", "lg", "xl")
THEME_MODES = ("light", "dark")

_DESIGN_STYLES = (
    {"id": "modern", "name": "Modern", "icon": "fa-shapes",
     "description": "Clean lines, generous space, confident type.",
     "tone": "clear, confident and friendly",
     "font_heading": "Space Grotesk", "font_body": "DM Sans", "radius": "md"},
    {"id": "minimal", "name": "Minimal", "icon": "fa-feather",
     "description": "Quiet and spare. Content does the talking.",
     "tone": "calm, brief and understated",
     "font_heading": "Inter", "font_body": "Inter", "radius": "sm"},
    {"id": "bold", "name": "Bold", "icon": "fa-bolt",
     "description": "Large type and strong contrast that stands out.",
     "tone": "punchy, direct and energetic",
     "font_heading": "Archivo", "font_body": "Inter", "radius": "sm"},
    {"id": "elegant", "name": "Elegant", "icon": "fa-gem",
     "description": "Refined and calm, with a premium feel.",
     "tone": "refined, warm and polished",
     "font_heading": "Playfair Display", "font_body": "Lato", "radius": "sm"},
    {"id": "playful", "name": "Playful", "icon": "fa-face-smile",
     "description": "Friendly shapes and a lively, approachable tone.",
     "tone": "light, cheerful and approachable",
     "font_heading": "Fredoka", "font_body": "Nunito", "radius": "xl"},
    {"id": "corporate", "name": "Corporate", "icon": "fa-building",
     "description": "Structured and trustworthy for professional services.",
     "tone": "professional, trustworthy and precise",
     "font_heading": "IBM Plex Sans", "font_body": "IBM Plex Sans", "radius": "sm"},
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


def get_style(style_id):
    for item in _DESIGN_STYLES:
        if item["id"] == style_id:
            return dict(item)
    return None


def get_color_scheme(scheme_id):
    for item in _COLOR_SCHEMES:
        if item["id"] == scheme_id:
            return dict(item)
    return None


def style_ids():
    return {item["id"] for item in _DESIGN_STYLES}


def color_scheme_ids():
    return {item["id"] for item in _COLOR_SCHEMES}
