"""Saving and loading projects in MySQL.

All SQL lives here. Values always travel as parameters (%s), never pasted into
the SQL text, so nothing a user types can change a query. The SQL is written
in a plain, portable style (no MySQL-only syntax) so the same code can be
tested against an in-memory database.

A project has one or more versions (rows in generated_websites). Saving edits
updates the current version; saving a freshly generated website adds a new
version. Only the newest MAX_VERSIONS versions are kept.
"""
import json
from datetime import datetime

from app.services.database import DamagedDataError, NotFoundError
from app.services.site_schema import SchemaError, clean_text, validate_site_config

MAX_VERSIONS = 10
NAME_MAX = 150
MODEL_MAX = 100
PROMPT_PREVIEW_MAX = 200
MAX_PAGE = 100


def current_user_id():
    """Accounts do not exist yet, so every project belongs to nobody (NULL).

    When login is added, return the signed-in user's id here and every query
    below will only see that user's projects.
    """
    return None


def _owner(user_id, alias="p"):
    """Return (sql, params) that limit a query to one owner."""
    if user_id is None:
        return f"{alias}.user_id IS NULL", ()
    return f"{alias}.user_id = %s", (user_id,)


def _iso(value):
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    if isinstance(value, str):
        return value.replace(" ", "T")[:19]
    return None


def _project_dict(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "category": row["category"],
        "status": row["status"],
        "created_at": _iso(row["created_at"]),
        "updated_at": _iso(row["updated_at"]),
        "version_count": row.get("version_count"),
        "primary_color": row.get("primary_color"),
    }


def _version_dict(row):
    return {
        "id": row["id"],
        "version": row["version"],
        "prompt": row["prompt"],
        "model_name": row["model_name"],
        "status": row["status"],
        "created_at": _iso(row["created_at"]),
    }


def _config_from_stored(value):
    """Read the stored JSON and validate it again, because a database can be edited by hand."""
    try:
        if isinstance(value, (bytes, bytearray)):
            value = value.decode("utf-8")
        data = json.loads(value) if isinstance(value, str) else value
        return validate_site_config(data)
    except (ValueError, TypeError, SchemaError) as exc:
        raise DamagedDataError("This project's saved data is damaged and cannot be opened.") from exc


def _dump(config):
    return json.dumps(config, ensure_ascii=False, separators=(",", ":"))


def clean_name(value, fallback=""):
    return clean_text(value, NAME_MAX) or clean_text(fallback, NAME_MAX)


# ------------------------------------------------------------------ low-level helpers
def _fetch_project(cursor, project_id, user_id):
    owner_sql, owner_params = _owner(user_id)
    cursor.execute(
        "SELECT p.id, p.name, p.category, p.status, p.created_at, p.updated_at "
        f"FROM projects p WHERE p.id = %s AND {owner_sql}",
        (project_id,) + owner_params,
    )
    return cursor.fetchone()


def _write_settings(cursor, project_id, config):
    theme, meta = config["theme"], config["meta"]
    values = (meta["design_style"], meta["color_scheme"], theme["primary"], theme["font_heading"], theme["font_body"])
    cursor.execute("SELECT id FROM project_settings WHERE project_id = %s", (project_id,))
    if cursor.fetchone():
        cursor.execute(
            "UPDATE project_settings SET design_style = %s, color_scheme = %s, primary_color = %s, "
            "font_heading = %s, font_body = %s, updated_at = CURRENT_TIMESTAMP WHERE project_id = %s",
            values + (project_id,),
        )
    else:
        cursor.execute(
            "INSERT INTO project_settings (design_style, color_scheme, primary_color, font_heading, font_body, project_id) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            values + (project_id,),
        )


def _insert_version(cursor, project_id, version, config, model):
    cursor.execute(
        "INSERT INTO generated_websites (project_id, version, prompt, config_json, model_name, status) "
        "VALUES (%s, %s, %s, %s, %s, 'success')",
        (project_id, version, config["meta"]["prompt"] or config["meta"]["tagline"], _dump(config),
         clean_text(model, MODEL_MAX) or None),
    )


def _project_with_counts(cursor, project_id):
    cursor.execute(
        "SELECT p.id, p.name, p.category, p.status, p.created_at, p.updated_at, s.primary_color AS primary_color, "
        "(SELECT COUNT(*) FROM generated_websites g WHERE g.project_id = p.id) AS version_count "
        "FROM projects p LEFT JOIN project_settings s ON s.project_id = p.id WHERE p.id = %s",
        (project_id,),
    )
    return _project_dict(cursor.fetchone())


def _latest_version_row(cursor, project_id, version=None):
    sql = ("SELECT id, version, prompt, config_json, model_name, status, created_at "
           "FROM generated_websites WHERE project_id = %s")
    params = (project_id,)
    if version is not None:
        sql += " AND version = %s"
        params += (version,)
    cursor.execute(sql + " ORDER BY version DESC LIMIT 1", params)
    return cursor.fetchone()


# ------------------------------------------------------------------ public functions
def list_projects(db, limit=24, offset=0, user_id=None):
    """Projects, most recently changed first."""
    limit = max(1, min(int(limit), MAX_PAGE))
    offset = max(0, int(offset))
    owner_sql, owner_params = _owner(user_id)
    with db.connection() as connection:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT p.id, p.name, p.category, p.status, p.created_at, p.updated_at, s.primary_color AS primary_color, "
            "(SELECT COUNT(*) FROM generated_websites g WHERE g.project_id = p.id) AS version_count "
            "FROM projects p LEFT JOIN project_settings s ON s.project_id = p.id "
            f"WHERE {owner_sql} AND p.status <> 'archived' "
            "ORDER BY p.updated_at DESC, p.id DESC LIMIT %s OFFSET %s",
            owner_params + (limit, offset),
        )
        rows = cursor.fetchall()
        cursor.close()
    return [_project_dict(row) for row in rows]


def get_project(db, project_id, version=None, user_id=None):
    """Return {"project", "version", "config"} for a project (newest version unless one is asked for)."""
    with db.connection() as connection:
        cursor = connection.cursor(dictionary=True)
        if not _fetch_project(cursor, project_id, user_id):
            raise NotFoundError("That project no longer exists.")
        row = _latest_version_row(cursor, project_id, version)
        if row is None:
            raise NotFoundError("That version of the project no longer exists.")
        project = _project_with_counts(cursor, project_id)
        cursor.close()
    return {"project": project, "version": _version_dict(row), "config": _config_from_stored(row["config_json"])}


def create_project(db, name, config, model="", user_id=None):
    """Save a website as a new project (version 1). `config` must already be validated."""
    meta = config["meta"]
    with db.transaction() as connection:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "INSERT INTO projects (user_id, name, description, category, status) VALUES (%s, %s, %s, %s, 'generated')",
            (user_id, clean_name(name, meta["site_name"]), meta["prompt"] or None, meta["category"]),
        )
        project_id = cursor.lastrowid
        _write_settings(cursor, project_id, config)
        _insert_version(cursor, project_id, 1, config, model)
        project = _project_with_counts(cursor, project_id)
        cursor.close()
    return {"project": project, "version": {"version": 1}}


def save_project(db, project_id, config, name=None, version=None, new_version=False, model="", user_id=None):
    """Save changes to a project.

    new_version=True stores the website as the next version (used after generating again).
    Otherwise the given version (default: the newest) is updated in place.
    """
    meta = config["meta"]
    with db.transaction() as connection:
        cursor = connection.cursor(dictionary=True)
        project = _fetch_project(cursor, project_id, user_id)
        if not project:
            raise NotFoundError("That project no longer exists.")

        cursor.execute("SELECT MAX(version) AS latest FROM generated_websites WHERE project_id = %s", (project_id,))
        latest = cursor.fetchone()["latest"] or 0

        if new_version:
            saved_version = latest + 1
            _insert_version(cursor, project_id, saved_version, config, model)
            cursor.execute(
                "DELETE FROM generated_websites WHERE project_id = %s AND version <= %s",
                (project_id, saved_version - MAX_VERSIONS),
            )
        else:
            saved_version = version if version is not None else latest
            cursor.execute(
                "SELECT id FROM generated_websites WHERE project_id = %s AND version = %s", (project_id, saved_version))
            if not cursor.fetchone():
                raise NotFoundError("That version of the project no longer exists.")
            cursor.execute(
                "UPDATE generated_websites SET config_json = %s, prompt = %s WHERE project_id = %s AND version = %s",
                (_dump(config), meta["prompt"] or meta["tagline"], project_id, saved_version),
            )

        cursor.execute(
            "UPDATE projects SET name = %s, description = %s, category = %s, status = 'generated', "
            "updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            (clean_name(name, project["name"]), meta["prompt"] or None, meta["category"], project_id),
        )
        _write_settings(cursor, project_id, config)
        result = _project_with_counts(cursor, project_id)
        cursor.close()
    return {"project": result, "version": {"version": saved_version}}


def rename_project(db, project_id, name, user_id=None):
    with db.transaction() as connection:
        cursor = connection.cursor(dictionary=True)
        if not _fetch_project(cursor, project_id, user_id):
            raise NotFoundError("That project no longer exists.")
        cursor.execute(
            "UPDATE projects SET name = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            (clean_name(name), project_id),
        )
        result = _project_with_counts(cursor, project_id)
        cursor.close()
    return {"project": result}


def duplicate_project(db, project_id, user_id=None):
    """Copy the newest version of a project into a new project."""
    original = get_project(db, project_id, user_id=user_id)
    base = original["project"]["name"]
    suffix = " (copy)"
    name = base[: NAME_MAX - len(suffix)].rstrip() + suffix
    return create_project(db, name, original["config"], original["version"]["model_name"] or "", user_id=user_id)


def delete_project(db, project_id, user_id=None):
    """Delete a project. Its versions and settings go with it."""
    with db.transaction() as connection:
        cursor = connection.cursor(dictionary=True)
        if not _fetch_project(cursor, project_id, user_id):
            raise NotFoundError("That project no longer exists.")
        cursor.execute("DELETE FROM projects WHERE id = %s", (project_id,))
        cursor.close()


def list_history(db, limit=30, user_id=None):
    """Every saved generation, newest first."""
    limit = max(1, min(int(limit), MAX_PAGE))
    owner_sql, owner_params = _owner(user_id)
    with db.connection() as connection:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT g.id, g.project_id, p.name AS project_name, g.version, g.prompt, g.model_name, g.status, g.created_at "
            "FROM generated_websites g JOIN projects p ON p.id = g.project_id "
            f"WHERE {owner_sql} AND p.status <> 'archived' "
            "ORDER BY g.created_at DESC, g.id DESC LIMIT %s",
            owner_params + (limit,),
        )
        rows = cursor.fetchall()
        cursor.close()
    entries = []
    for row in rows:
        prompt = row["prompt"] or ""
        entries.append({
            "id": row["id"], "project_id": row["project_id"], "project_name": row["project_name"],
            "version": row["version"],
            "prompt": prompt if len(prompt) <= PROMPT_PREVIEW_MAX else prompt[:PROMPT_PREVIEW_MAX].rstrip() + "...",
            "model_name": row["model_name"], "status": row["status"], "created_at": _iso(row["created_at"]),
        })
    return entries
