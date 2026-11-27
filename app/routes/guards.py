"""Shared protection for the JSON API."""
from flask import jsonify, request

# Websites that contain uploaded pictures are larger than the normal 1 MB request limit.
LARGE_REQUEST_LIMIT = 12 * 1024 * 1024

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class ApiError(Exception):
    """Raise this inside an API function to send a JSON error to the browser."""

    def __init__(self, status, error, message, **extra):
        super().__init__(message)
        self.status = status
        self.error = error
        self.message = message
        self.extra = extra


def handle_api_error(exc):
    body = {"error": exc.error, "message": exc.message}
    body.update(exc.extra)
    return jsonify(body), exc.status


def require_same_site_request():
    """Refuse state-changing requests that another website could have triggered.

    A page on another site can send a form post, but it cannot send JSON or add
    the X-SiteForge-Request header without the browser first asking this server
    for permission (which it never gives). So one of the two must be present.
    """
    if request.method in _SAFE_METHODS:
        return None
    if request.is_json or request.headers.get("X-SiteForge-Request") == "1":
        return None
    if request.content_length:
        raise ApiError(415, "unsupported_media_type", "Send the request as JSON.")
    raise ApiError(403, "forbidden", "This request was not allowed.")


def read_json_object():
    """The JSON body as a dict. Allows the larger limit used for websites with pictures."""
    request.max_content_length = LARGE_REQUEST_LIMIT
    if not request.is_json:
        raise ApiError(415, "unsupported_media_type", "Send the request as JSON.")
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ApiError(400, "validation_failed", "The request must be a JSON object.")
    return body
