"""Valid example content for every section type, used to fake the AI model."""
import json
import re


def _items(factory, count):
    return [factory(i) for i in range(count)]


def valid_section(section_type):
    samples = {
        "hero": {"layout": "split", "headline": "Slow-simmered ramen, open past midnight",
                 "subheadline": "Twelve-hour broth and hand-pulled noodles in the heart of Cebu City.",
                 "primary_cta": {"label": "Reserve a table", "target": "contact"},
                 "secondary_cta": {"label": "See the menu", "target": "menu"},
                 "image_alt": "A steaming bowl of tonkotsu ramen"},
        "about": {"layout": "split", "title": "Our story",
                  "body": ["We opened in 2019 to serve honest ramen.", "Everything is made in house."],
                  "highlights": ["Family owned", "Open until 2 AM"], "image_alt": "The kitchen"},
        "features": {"layout": "grid", "title": "Why people come back", "intro": "Three things we care about.",
                     "items": _items(lambda i: {"icon": "utensils", "title": f"Feature {i}",
                                                "description": "A short and specific description."}, 3)},
        "menu": {"title": "The menu", "intro": "Made fresh every day.",
                 "categories": [{"name": "Ramen", "items": _items(
                     lambda i: {"name": f"Bowl {i}", "description": "Rich broth", "price": f"\u20b1{300 + i}"}, 3)}]},
        "gallery": {"title": "Gallery", "intro": "A look inside.",
                    "items": _items(lambda i: {"caption": f"Photo {i}", "image_alt": "A photo"}, 3)},
        "projects": {"layout": "grid", "title": "Selected work", "intro": "",
                     "items": _items(lambda i: {"title": f"Project {i}", "category": "Branding",
                                                "description": "What we did and why it mattered.",
                                                "image_alt": "Project image"}, 3)},
        "products": {"title": "Shop", "intro": "",
                     "items": _items(lambda i: {"name": f"Product {i}", "description": "Handmade",
                                                "price": "$24", "badge": "New", "image_alt": "Product"}, 3)},
        "testimonials": {"title": "Kind words",
                         "items": _items(lambda i: {"quote": "The best ramen in town.", "name": f"Guest {i}",
                                                    "role": "Regular"}, 2)},
        "team": {"layout": "grid", "title": "The team", "intro": "",
                 "members": _items(lambda i: {"name": f"Person {i}", "role": "Chef", "bio": "Loves broth."}, 2)},
        "pricing": {"title": "Plans", "intro": "",
                    "plans": _items(lambda i: {"name": f"Plan {i}", "price": "$9", "period": "month",
                                               "description": "For starters",
                                               "features": ["One", "Two"], "highlighted": i == 1,
                                               "cta_label": "Choose"}, 2)},
        "faq": {"title": "Questions",
                "items": _items(lambda i: {"question": f"Question {i}?", "answer": "A clear answer."}, 3)},
        "contact": {"title": "Visit us", "intro": "We would love to see you.",
                    "email": "hello@example.com", "phone": "+1 555 0100", "address": "123 Colon Street, Cebu City",
                    "hours": [{"days": "Mon to Sun", "time": "6 PM to 2 AM"}], "show_form": True},
        "cta": {"headline": "Hungry yet?", "text": "Book your table tonight.",
                "button_label": "Reserve now", "target": "contact"},
        "posts": {"layout": "list", "title": "Latest posts", "intro": "",
                  "items": _items(lambda i: {"title": f"Post {i}", "excerpt": "A short excerpt.",
                                             "category": "Travel", "date": "Nov 2026"}, 3)},
    }
    return samples[section_type]


def make_responder(sections=("hero", "about", "menu", "contact"), category="restaurant", fail_sections=()):
    """Fake model: answers the planning request and every section request."""
    def responder(body):
        user = body["messages"][1]["content"]
        match = re.search(r"Section to write: (\w+)", user)
        if match:
            section_type = match.group(1)
            if section_type in fail_sections:
                return "this is not json"
            return json.dumps(valid_section(section_type))
        return json.dumps({"site_name": "Kuya's Ramen",
                           "tagline": "Slow-simmered ramen, open past midnight.",
                           "category": category, "sections": list(sections)})
    return responder
