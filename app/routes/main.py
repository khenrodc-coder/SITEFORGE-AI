"""Routes that return full HTML pages."""
from flask import Blueprint, render_template, request

from app.services.design_options import (
    DEFAULT_COLOR_SCHEME,
    DEFAULT_STYLE,
    get_color_schemes,
    get_design_styles,
)
from app.services.generation_request import (
    AUTO_CATEGORY,
    PROMPT_MAX_LENGTH,
    PROMPT_MIN_LENGTH,
)
from app.services.template_catalog import get_categories, get_category

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def index():
    """Public landing page."""
    return render_template("landing.html")


@main_bp.route("/dashboard")
def dashboard():
    """Project dashboard: new project, templates, history."""
    return render_template(
        "dashboard.html",
        active_page="dashboard",
        categories=get_categories(),
    )


@main_bp.route("/builder")
def builder():
    """Website builder. Only a known website type is accepted from the address."""
    category = get_category(request.args.get("category", ""))
    return render_template(
        "builder.html",
        active_page="builder",
        category=category,
        selected_category=category["id"] if category else AUTO_CATEGORY,
        categories=get_categories(),
        design_styles=get_design_styles(),
        color_schemes=get_color_schemes(),
        selected_style=DEFAULT_STYLE,
        selected_color=DEFAULT_COLOR_SCHEME,
        prompt_min=PROMPT_MIN_LENGTH,
        prompt_max=PROMPT_MAX_LENGTH,
    )
