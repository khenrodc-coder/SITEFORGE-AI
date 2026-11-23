"""REST API routes (JSON). All addresses start with /api."""
import os

from flask import Blueprint, current_app, jsonify, request

from app.services.generation_request import validate_generation_request
from app.services.job_manager import JobBusyError
from app.services.ollama_service import OllamaError, client_from_config
from app.services.website_generator import generate_website

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

    # Fail fast, with a helpful message, if Ollama is off or the model is missing.
    try:
        client = client_from_config(current_app.config)
    except OllamaError as exc:
        return jsonify({"error": exc.code, "message": exc.message}), exc.http_status
    status = client.status()
    if not status["reachable"]:
        return jsonify({"error": "ollama_unavailable", "message": status["message"]}), 503
    if not status["model_installed"]:
        return jsonify({"error": "model_not_installed", "message": status["message"]}), 503

    manager = current_app.extensions["job_manager"]
    try:
        job = manager.start(lambda running_job: generate_website(client, cleaned, running_job))
    except JobBusyError:
        return jsonify({"error": "generation_busy",
                        "message": "Another website is still being generated. Wait for it to finish or cancel it, then try again."}), 409

    return jsonify({"job_id": job.id, "status": job.status}), 202


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
