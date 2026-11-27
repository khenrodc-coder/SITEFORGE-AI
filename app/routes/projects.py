"""Project management: save, open, rename, duplicate, delete, and history."""
from flask import Blueprint, current_app, jsonify, request

from app.routes.guards import ApiError, read_json_object, require_same_site_request
from app.services import project_repository as repository
from app.services.database import DatabaseError
from app.services.site_schema import SchemaError, clean_text, validate_site_config

projects_bp = Blueprint("projects", __name__, url_prefix="/api")
projects_bp.before_request(require_same_site_request)


def _db():
    return current_app.extensions["database"]


@projects_bp.errorhandler(DatabaseError)
def handle_database_error(exc):
    return jsonify({"error": exc.code, "message": exc.message}), exc.http_status


def _valid_config(body):
    try:
        return validate_site_config(body.get("config"))
    except SchemaError as exc:
        raise ApiError(400, "invalid_configuration", "The website data is not valid.",
                       problems=exc.problems[:10]) from exc


def _name(body, fallback=""):
    name = repository.clean_name(body.get("name") if isinstance(body.get("name"), str) else "", fallback)
    if not name:
        raise ApiError(400, "validation_failed", "Give the project a name.", fields={"name": "Give the project a name."})
    return name


def _model(body):
    value = body.get("model")
    return clean_text(value, repository.MODEL_MAX) if isinstance(value, str) else ""


def _positive_int(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


@projects_bp.route("/db/status")
def database_status():
    """Is the database switched on, reachable, and set up?"""
    return jsonify(_db().status())


@projects_bp.route("/projects")
def list_projects():
    limit = request.args.get("limit", default=24, type=int)
    offset = request.args.get("offset", default=0, type=int)
    projects = repository.list_projects(_db(), limit=limit, offset=offset, user_id=repository.current_user_id())
    return jsonify({"projects": projects})


@projects_bp.route("/projects", methods=["POST"])
def create_project():
    body = read_json_object()
    config = _valid_config(body)
    name = _name(body, config["meta"]["site_name"])
    saved = repository.create_project(_db(), name, config, _model(body), user_id=repository.current_user_id())
    return jsonify(saved), 201


@projects_bp.route("/projects/<int(max=9223372036854775807):project_id>")
def get_project(project_id):
    version = request.args.get("version", type=int)
    if request.args.get("version") is not None and not _positive_int(version):
        raise ApiError(400, "validation_failed", "The version must be a positive number.")
    return jsonify(repository.get_project(_db(), project_id, version=version, user_id=repository.current_user_id()))


@projects_bp.route("/projects/<int(max=9223372036854775807):project_id>", methods=["PUT"])
def save_project(project_id):
    body = read_json_object()
    config = _valid_config(body)
    version = body.get("version")
    if version is not None and not _positive_int(version):
        raise ApiError(400, "validation_failed", "The version must be a positive number.")
    name = None
    if isinstance(body.get("name"), str) and body["name"].strip():
        name = _name(body)
    saved = repository.save_project(
        _db(), project_id, config, name=name, version=version, new_version=body.get("new_version") is True,
        model=_model(body), user_id=repository.current_user_id())
    return jsonify(saved)


@projects_bp.route("/projects/<int(max=9223372036854775807):project_id>", methods=["PATCH"])
def rename_project(project_id):
    body = read_json_object()
    name = _name(body)
    return jsonify(repository.rename_project(_db(), project_id, name, user_id=repository.current_user_id()))


@projects_bp.route("/projects/<int(max=9223372036854775807):project_id>", methods=["DELETE"])
def delete_project(project_id):
    repository.delete_project(_db(), project_id, user_id=repository.current_user_id())
    return jsonify({"deleted": project_id})


@projects_bp.route("/projects/<int(max=9223372036854775807):project_id>/duplicate", methods=["POST"])
def duplicate_project(project_id):
    saved = repository.duplicate_project(_db(), project_id, user_id=repository.current_user_id())
    return jsonify(saved), 201


@projects_bp.route("/history")
def history():
    limit = request.args.get("limit", default=30, type=int)
    return jsonify({"history": repository.list_history(_db(), limit=limit, user_id=repository.current_user_id())})
