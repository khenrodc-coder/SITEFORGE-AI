"""REST API routes (JSON). All addresses start with /api."""
import os

from flask import Blueprint, current_app, jsonify, request

from app.services.generation_request import validate_generation_request
from app.services.ollama_service import OllamaError, client_from_config
from app.services.website_brief import create_website_brief

api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.route("/health")
def health():
    """Report that the server is running. Never exposes secrets."""
    export_dir = current_app.config["GENERATED_WEBSITES_DIR"]
    return jsonify(
        {
            "status": "ok",
            "app": current_app.config["APP_NAME"],
            "version": current_app.config["APP_VERSION"],
            "checks": {
                "generated_websites_writable": os.access(export_dir, os.W_OK),
            },
        }
    )


@api_bp.route("/ai/status")
def ai_status():
    """Is Ollama running, and is the configured model installed?"""
    try:
        return jsonify(client_from_config(current_app.config).status())
    except OllamaError as exc:
        return jsonify({"reachable": False, "model": current_app.config["OLLAMA_MODEL"],
                        "model_installed": False, "installed_models": [], "message": exc.message})


@api_bp.route("/generate", methods=["POST"])
def generate():
    """Validate a website description and ask the local model to plan the website.

    Requiring a JSON body also protects against cross-site form posts, because
    a plain HTML form on another site cannot send application/json.
    """
    if not request.is_json:
        return jsonify({"error": "unsupported_media_type",
                        "message": "Send the request as JSON."}), 415

    data = request.get_json(silent=True)
    cleaned, errors = validate_generation_request(data)
    if errors:
        return jsonify({"error": "validation_failed",
                        "message": "Please fix the highlighted fields.",
                        "fields": errors}), 400

    try:
        client = client_from_config(current_app.config)
        brief = create_website_brief(client, cleaned)
    except OllamaError as exc:
        return jsonify({"error": exc.code, "message": exc.message}), exc.http_status

    return jsonify({"status": "ok", "model": client.model, "brief": brief})
