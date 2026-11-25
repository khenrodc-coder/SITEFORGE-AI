"""REST API routes (JSON). All addresses start with /api."""
import os

from flask import Blueprint, current_app, jsonify, request

from app.services.generation_request import validate_generation_request
from app.services.job_manager import JobBusyError
from app.services.ollama_service import OllamaError, client_from_config
from app.services.site_schema import (
    MAX_SECTIONS,
    SECTION_SPECS,
    SchemaError,
    clean_text,
    export_schema,
    validate_site_config,
)
from app.services.website_generator import generate_website, write_single_section
from app.services.website_renderer import render_website

api_bp = Blueprint("api", __name__, url_prefix="/api")

# Websites that contain uploaded pictures are larger than the normal 1 MB request limit.
LARGE_REQUEST_LIMIT = 12 * 1024 * 1024
HINT_MAX_LENGTH = 200


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


def _ready_client():
    """Return (client, None), or (None, error_response) when Ollama is off or the model is missing."""
    try:
        client = client_from_config(current_app.config)
    except OllamaError as exc:
        return None, (jsonify({"error": exc.code, "message": exc.message}), exc.http_status)
    status = client.status()
    if not status["reachable"]:
        return None, (jsonify({"error": "ollama_unavailable", "message": status["message"]}), 503)
    if not status["model_installed"]:
        return None, (jsonify({"error": "model_not_installed", "message": status["message"]}), 503)
    return client, None


def _start_job(target):
    manager = current_app.extensions["job_manager"]
    try:
        job = manager.start(target)
    except JobBusyError:
        return jsonify({"error": "generation_busy",
                        "message": "The AI is still busy with another request. Wait for it to finish or cancel it, then try again."}), 409
    return jsonify({"job_id": job.id, "status": job.status}), 202


@api_bp.route("/generate", methods=["POST"])
def generate():
    """Validate a website description and start generating it in the background.

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

    client, problem = _ready_client()
    if problem:
        return problem
    return _start_job(lambda running_job: generate_website(client, cleaned, running_job))


@api_bp.route("/generate/<job_id>")
def generate_status(job_id):
    """Progress of a generation job. Includes the result once it is done."""
    job = current_app.extensions["job_manager"].get(job_id)
    if job is None:
        return jsonify({"error": "job_not_found", "message": "That generation job no longer exists."}), 404
    return jsonify(job.snapshot())


@api_bp.route("/generate/<job_id>/cancel", methods=["POST"])
def generate_cancel(job_id):
    """Ask a running generation job to stop."""
    job = current_app.extensions["job_manager"].get(job_id)
    if job is None:
        return jsonify({"error": "job_not_found", "message": "That generation job no longer exists."}), 404
    job.request_cancel()
    return jsonify(job.snapshot())


@api_bp.route("/render", methods=["POST"])
def render():
    """Turn a website configuration into website files.

    The configuration is validated first, so only safe, known data is rendered.
    Send "files": false to skip the separate files when only the page is needed.
    """
    request.max_content_length = LARGE_REQUEST_LIMIT
    if not request.is_json:
        return jsonify({"error": "unsupported_media_type",
                        "message": "Send the request as JSON."}), 415

    body = request.get_json(silent=True)
    config = body.get("config") if isinstance(body, dict) else None
    preview = isinstance(body, dict) and body.get("preview") is True
    with_files = not (isinstance(body, dict) and body.get("files") is False)
    try:
        rendered = render_website(config, preview=preview, with_files=with_files)
    except SchemaError as exc:
        return jsonify({"error": "invalid_configuration",
                        "message": "The website data is not valid.",
                        "problems": exc.problems[:10]}), 400
    return jsonify(rendered)


@api_bp.route("/schema")
def schema():
    """Describes every section type and option, so the editor can build its forms."""
    return jsonify(export_schema())


@api_bp.route("/sections/write", methods=["POST"])
def write_section_endpoint():
    """Ask the AI to write one section: a new one, or a rewrite of an existing one.

    Runs as a background job like a full generation. Poll /api/generate/<job_id>.
    """
    request.max_content_length = LARGE_REQUEST_LIMIT
    if not request.is_json:
        return jsonify({"error": "unsupported_media_type",
                        "message": "Send the request as JSON."}), 415

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "validation_failed", "message": "The request must be a JSON object."}), 400

    section_type = body.get("type")
    if not isinstance(section_type, str) or section_type not in SECTION_SPECS:
        return jsonify({"error": "validation_failed", "message": "That section type does not exist.",
                        "fields": {"type": "Choose a section type from the list."}}), 400

    try:
        config = validate_site_config(body.get("config"))
    except SchemaError as exc:
        return jsonify({"error": "invalid_configuration",
                        "message": "The website has problems that must be fixed first.",
                        "problems": exc.problems[:10]}), 400

    exists = any(section["type"] == section_type for section in config["sections"])
    if not exists and len(config["sections"]) >= MAX_SECTIONS:
        return jsonify({"error": "validation_failed",
                        "message": f"A website can have at most {MAX_SECTIONS} sections."}), 400

    hint = body.get("hint")
    hint = clean_text(hint, HINT_MAX_LENGTH) if isinstance(hint, str) else ""

    client, problem = _ready_client()
    if problem:
        return problem
    return _start_job(lambda job: write_single_section(client, config, section_type, hint, job))
