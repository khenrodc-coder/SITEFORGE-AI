"""The website types SiteForge AI supports.

The dashboard shows these as starting points. From Phase 5 the AI generator
uses the same ids to pick sections and layouts.
"""

_CATEGORIES = (
    {
        "id": "business",
        "name": "Business",
        "icon": "fa-briefcase",
        "description": "Services, team, and contact details for a company or local shop.",
        "sections": ["Hero", "Services", "About", "Testimonials", "Contact"],
    },
    {
        "id": "portfolio",
        "name": "Portfolio",
        "icon": "fa-palette",
        "description": "Projects and skills for a designer, developer, or other professional.",
        "sections": ["Hero", "Projects", "Skills", "About", "Contact"],
    },
    {
        "id": "restaurant",
        "name": "Restaurant",
        "icon": "fa-utensils",
        "description": "Menu, opening hours, and reservations for a food business.",
        "sections": ["Hero", "Menu", "Gallery", "Hours", "Reservations"],
    },
    {
        "id": "ecommerce",
        "name": "E-commerce storefront",
        "icon": "fa-bag-shopping",
        "description": "A visual storefront with collections and product grids.",
        "sections": ["Hero", "Collections", "Products", "Reviews", "Newsletter"],
    },
    {
        "id": "agency",
        "name": "Agency",
        "icon": "fa-people-group",
        "description": "Present your services, case studies, and team.",
        "sections": ["Hero", "Services", "Case studies", "Team", "Contact"],
    },
    {
        "id": "landing",
        "name": "Landing page",
        "icon": "fa-rocket",
        "description": "One focused page that promotes a product, event, or offer.",
        "sections": ["Hero", "Benefits", "Features", "Pricing", "FAQ"],
    },
    {
        "id": "blog",
        "name": "Blog",
        "icon": "fa-pen-nib",
        "description": "A reading-first layout with featured and recent posts.",
        "sections": ["Featured post", "Recent posts", "Categories", "About", "Subscribe"],
    },
    {
        "id": "personal",
        "name": "Personal website",
        "icon": "fa-user",
        "description": "A simple home for your story, interests, and links.",
        "sections": ["Intro", "About", "Highlights", "Links", "Contact"],
    },
)


def get_categories():
    """Return a copy of every website type, in display order."""
    return [dict(category) for category in _CATEGORIES]


def get_category(category_id):
    """Return one website type by id, or None if the id is unknown."""
    for category in _CATEGORIES:
        if category["id"] == category_id:
            return dict(category)
    return None
