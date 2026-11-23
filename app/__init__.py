"""SiteForge AI application package (Flask application factory)."""
from datetime import datetime

from flask import Flask, jsonify, render_template, request

from app.services.job_manager import JobManager
from config import get_config


def create_app(config_name=None):
    """Build and configure the Flask application."""
    app = Flask(__name__)
    app.config.from_object(get_config(config_name))

    app.extensions["job_manager"] = JobManager()

    # Make sure the export folder exists.
    app.config["GENERATED_WEBSITES_DIR"].mkdir(parents=True, exist_ok=True)

    from app.routes import register_blueprints

    register_blueprints(app)
    register_error_handlers(app)
    register_security_headers(app)

    @app.context_processor
    def inject_template_globals():
        return {"app_name": app.config["APP_NAME"], "current_year": datetime.now().year}

    return app


def register_error_handlers(app):
    """Return JSON for /api/ requests and friendly HTML pages otherwise."""

    def respond(status, title, message):
        if request.path.startswith("/api/"):
            return jsonify({"error": title, "message": message}), status
        return render_template("errors/error.html", status=status, title=title, message=message), status

    @app.errorhandler(400)
    def bad_request(_):
        return respond(400, "Bad request", "The request could not be understood.")

    @app.errorhandler(404)
    def not_found(_):
        return respond(404, "Page not found", "The page you are looking for does not exist.")

    @app.errorhandler(405)
    def method_not_allowed(_):
        return respond(405, "Method not allowed", "This action is not allowed on this address.")

    @app.errorhandler(415)
    def unsupported_media(_):
        return respond(415, "Unsupported content type", "Send the request as JSON.")

    @app.errorhandler(413)
    def too_large(_):
        return respond(413, "Request too large", "The submitted data is too large.")

    @app.errorhandler(500)
    def server_error(_):
        return respond(500, "Server error", "Something went wrong on our side. Please try again.")


def register_security_headers(app):
    """Add basic protective headers to every response."""

    @app.after_request
    def add_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return response
