"""Phase 9 tests: saving, opening, renaming, duplicating and deleting projects."""
import base64
import copy
import json
import logging
import sqlite3
import sys
import types
import unittest
from unittest import mock

from app import create_app
from app.services import project_repository as repo
from app.services.database import (
    MSG_ACCESS,
    MSG_DRIVER,
    MSG_NO_TABLES,
    MSG_OFF,
    MSG_OTHER,
    MSG_PACKET,
    MSG_UNREACHABLE,
    DamagedDataError,
    Database,
    DatabaseError,
    DatabaseUnavailableError,
    DisabledConnector,
    MySQLConnector,
    NotFoundError,
    translate_error,
)
from tests.sqlite_support import DDL, mysql_schema_tables, sqlite_database
from tests.test_phase5 import sample_config
from tests.test_phase6 import make_config

GUARD = {"X-SiteForge-Request": "1"}
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def valid(config=None):
    from app.services.site_schema import validate_site_config
    return validate_site_config(config or sample_config())


def set_time(connection, project_id, stamp):
    connection.run("UPDATE projects SET updated_at = ? WHERE id = ?", (stamp, project_id))


# ------------------------------------------------------------------ schema
class SchemaDriftTests(unittest.TestCase):
    def test_test_database_has_the_same_columns_as_schema_sql(self):
        _, connection = sqlite_database()
        for table, info in mysql_schema_tables().items():
            columns = [row[1] for row in connection.run(f"PRAGMA table_info({table})")]
            self.assertEqual(sorted(columns), sorted(info["columns"]), table)

    def test_schema_has_the_four_required_tables(self):
        self.assertEqual(set(mysql_schema_tables()), {"users", "projects", "generated_websites", "project_settings"})

    def test_schema_script_is_safe_to_run_twice(self):
        from tests.sqlite_support import SCHEMA_SQL
        text = SCHEMA_SQL.read_text(encoding="utf-8")
        self.assertEqual(text.count("CREATE TABLE IF NOT EXISTS"), 4)
        self.assertNotIn("DROP ", text.upper())


# ------------------------------------------------------------------ repository
class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.db, self.conn = sqlite_database()
        self.config = valid()

    def create(self, name="Kuya's Ramen", config=None, model="llama3.1:8b"):
        return repo.create_project(self.db, name, config or self.config, model)

    def count(self, table):
        return self.conn.run(f"SELECT COUNT(*) FROM {table}")[0][0]

    def test_create_stores_project_settings_and_first_version(self):
        saved = self.create()
        self.assertEqual(saved["project"]["name"], "Kuya's Ramen")
        self.assertEqual(saved["project"]["category"], "restaurant")
        self.assertEqual(saved["project"]["version_count"], 1)
        self.assertEqual(saved["project"]["primary_color"], "#2563eb")
        self.assertEqual(saved["version"], {"version": 1})
        self.assertEqual((self.count("projects"), self.count("generated_websites"), self.count("project_settings")), (1, 1, 1))

    def test_open_returns_exactly_what_was_saved(self):
        pid = self.create()["project"]["id"]
        opened = repo.get_project(self.db, pid)
        self.assertEqual(opened["config"], self.config)
        self.assertEqual(opened["version"]["version"], 1)
        self.assertEqual(opened["version"]["model_name"], "llama3.1:8b")
        self.assertEqual(opened["project"]["id"], pid)

    def test_name_falls_back_to_the_site_name_and_is_cleaned(self):
        self.assertEqual(self.create(name="")["project"]["name"], "Kuya's Ramen")
        self.assertEqual(self.create(name="<b>Bold</b> <script>x</script>move")["project"]["name"], "Bold x move")
        self.assertEqual(len(self.create(name="n" * 400)["project"]["name"]), 150)

    def test_sql_injection_in_a_name_is_just_text(self):
        evil = "x'); DROP TABLE projects; --"
        pid = self.create(name=evil)["project"]["id"]
        self.assertEqual(repo.get_project(self.db, pid)["project"]["name"], evil)
        self.assertEqual(self.count("projects"), 1)

    def test_saving_edits_updates_in_place(self):
        pid = self.create()["project"]["id"]
        edited = copy.deepcopy(self.config)
        edited["sections"][0]["data"]["headline"] = "A brand new headline"
        edited["theme"]["primary"] = "#e11d48"
        edited["meta"]["color_scheme"] = "rose"
        result = repo.save_project(self.db, pid, valid(edited), name="Renamed")
        self.assertEqual(result["version"], {"version": 1})
        self.assertEqual(result["project"]["version_count"], 1)
        self.assertEqual(result["project"]["name"], "Renamed")
        self.assertEqual(result["project"]["primary_color"], "#e11d48")
        opened = repo.get_project(self.db, pid)
        self.assertEqual(opened["config"]["sections"][0]["data"]["headline"], "A brand new headline")
        self.assertEqual((self.count("generated_websites"), self.count("project_settings")), (1, 1))

    def test_saving_without_a_name_keeps_the_old_one(self):
        pid = self.create(name="Keep me")["project"]["id"]
        self.assertEqual(repo.save_project(self.db, pid, self.config)["project"]["name"], "Keep me")

    def test_a_new_generation_becomes_a_new_version(self):
        pid = self.create()["project"]["id"]
        second = repo.save_project(self.db, pid, self.config, new_version=True, model="m2")
        self.assertEqual(second["version"], {"version": 2})
        self.assertEqual(second["project"]["version_count"], 2)
        self.assertEqual(repo.get_project(self.db, pid)["version"]["version"], 2)                # newest by default
        self.assertEqual(repo.get_project(self.db, pid, version=1)["version"]["version"], 1)

    def test_an_older_version_can_be_edited_without_touching_the_newer_one(self):
        pid = self.create()["project"]["id"]
        newer = copy.deepcopy(self.config)
        newer["sections"][0]["data"]["headline"] = "Version two"
        repo.save_project(self.db, pid, valid(newer), new_version=True)
        older = copy.deepcopy(self.config)
        older["sections"][0]["data"]["headline"] = "Version one edited"
        repo.save_project(self.db, pid, valid(older), version=1)
        self.assertEqual(repo.get_project(self.db, pid, version=1)["config"]["sections"][0]["data"]["headline"], "Version one edited")
        self.assertEqual(repo.get_project(self.db, pid, version=2)["config"]["sections"][0]["data"]["headline"], "Version two")

    def test_only_the_newest_versions_are_kept(self):
        pid = self.create()["project"]["id"]
        for _ in range(repo.MAX_VERSIONS + 2):
            result = repo.save_project(self.db, pid, self.config, new_version=True)
        self.assertEqual(result["version"], {"version": repo.MAX_VERSIONS + 3})
        versions = [r[0] for r in self.conn.run("SELECT version FROM generated_websites ORDER BY version")]
        self.assertEqual(len(versions), repo.MAX_VERSIONS)
        self.assertEqual(versions[-1], repo.MAX_VERSIONS + 3)
        self.assertEqual(versions[0], 4)

    def test_unknown_project_or_version(self):
        pid = self.create()["project"]["id"]
        for call in (lambda: repo.get_project(self.db, 999),
                     lambda: repo.get_project(self.db, pid, version=7),
                     lambda: repo.save_project(self.db, 999, self.config),
                     lambda: repo.save_project(self.db, pid, self.config, version=7),
                     lambda: repo.rename_project(self.db, 999, "x"),
                     lambda: repo.duplicate_project(self.db, 999),
                     lambda: repo.delete_project(self.db, 999)):
            with self.assertRaises(NotFoundError):
                call()

    def test_rename(self):
        pid = self.create()["project"]["id"]
        self.assertEqual(repo.rename_project(self.db, pid, "  New <i>name</i>  ")["project"]["name"], "New name")

    def test_duplicate_makes_an_independent_copy(self):
        original = self.create(name="Original")
        copy_id = repo.duplicate_project(self.db, original["project"]["id"])["project"]["id"]
        self.assertNotEqual(copy_id, original["project"]["id"])
        duplicate = repo.get_project(self.db, copy_id)
        self.assertEqual(duplicate["project"]["name"], "Original (copy)")
        self.assertEqual(duplicate["config"], self.config)
        self.assertEqual(duplicate["project"]["version_count"], 1)
        edited = copy.deepcopy(self.config)
        edited["sections"][0]["data"]["headline"] = "Only the copy changes"
        repo.save_project(self.db, copy_id, valid(edited))
        untouched = repo.get_project(self.db, original["project"]["id"])["config"]
        self.assertEqual(untouched["sections"][0]["data"]["headline"], self.config["sections"][0]["data"]["headline"])

    def test_duplicate_uses_the_newest_version_and_a_copy_of_a_copy_still_fits(self):
        pid = self.create(name="n" * 150)["project"]["id"]
        newer = copy.deepcopy(self.config)
        newer["sections"][0]["data"]["headline"] = "Newest"
        repo.save_project(self.db, pid, valid(newer), new_version=True)
        copy_id = repo.duplicate_project(self.db, pid)["project"]["id"]
        opened = repo.get_project(self.db, copy_id)
        self.assertEqual(opened["config"]["sections"][0]["data"]["headline"], "Newest")
        self.assertEqual(len(opened["project"]["name"]), 150)
        self.assertTrue(opened["project"]["name"].endswith(" (copy)"))
        again = repo.duplicate_project(self.db, copy_id)["project"]["name"]
        self.assertLessEqual(len(again), 150)

    def test_delete_removes_everything_that_belongs_to_the_project(self):
        keep = self.create(name="Keep")["project"]["id"]
        gone = self.create(name="Gone")["project"]["id"]
        repo.save_project(self.db, gone, self.config, new_version=True)
        repo.delete_project(self.db, gone)
        self.assertEqual((self.count("projects"), self.count("generated_websites"), self.count("project_settings")), (1, 1, 1))
        self.assertEqual(repo.get_project(self.db, keep)["project"]["name"], "Keep")
        with self.assertRaises(NotFoundError):
            repo.get_project(self.db, gone)

    def test_list_is_newest_change_first_and_pages(self):
        ids = [self.create(name=f"P{i}")["project"]["id"] for i in range(5)]
        for index, pid in enumerate(ids):
            set_time(self.conn, pid, f"2026-11-0{index + 1} 10:00:00")
        set_time(self.conn, ids[0], "2026-11-20 10:00:00")                   # touched most recently
        names = [p["name"] for p in repo.list_projects(self.db)]
        self.assertEqual(names, ["P0", "P4", "P3", "P2", "P1"])
        self.assertEqual([p["name"] for p in repo.list_projects(self.db, limit=2)], ["P0", "P4"])
        self.assertEqual([p["name"] for p in repo.list_projects(self.db, limit=2, offset=2)], ["P3", "P2"])
        self.assertEqual(len(repo.list_projects(self.db, limit=10_000)), 5)       # clamped
        self.assertEqual(len(repo.list_projects(self.db, limit=-5)), 1)

    def test_equal_times_fall_back_to_newest_id(self):
        first, second = self.create(name="A")["project"]["id"], self.create(name="B")["project"]["id"]
        for pid in (first, second):
            set_time(self.conn, pid, "2026-11-01 10:00:00")
        self.assertEqual([p["name"] for p in repo.list_projects(self.db)], ["B", "A"])

    def test_archived_projects_are_hidden(self):
        pid = self.create()["project"]["id"]
        self.conn.run("UPDATE projects SET status = 'archived' WHERE id = ?", (pid,))
        self.assertEqual(repo.list_projects(self.db), [])
        self.assertEqual(repo.list_history(self.db), [])

    def test_projects_of_different_owners_are_separate(self):
        self.conn.run("INSERT INTO users (email, password_hash, display_name) VALUES ('a@b.c', 'x', 'A')")
        mine = repo.create_project(self.db, "Mine", self.config, user_id=1)["project"]["id"]
        nobodys = self.create(name="Nobody's")["project"]["id"]
        self.assertEqual([p["name"] for p in repo.list_projects(self.db, user_id=1)], ["Mine"])
        self.assertEqual([p["name"] for p in repo.list_projects(self.db, user_id=None)], ["Nobody's"])
        for call in (lambda: repo.get_project(self.db, mine),
                     lambda: repo.rename_project(self.db, mine, "x"),
                     lambda: repo.delete_project(self.db, mine),
                     lambda: repo.save_project(self.db, mine, self.config),
                     lambda: repo.duplicate_project(self.db, mine)):
            with self.assertRaises(NotFoundError):
                call()
        with self.assertRaises(NotFoundError):
            repo.get_project(self.db, nobodys, user_id=1)
        self.assertEqual([h["project_name"] for h in repo.list_history(self.db, user_id=1)], ["Mine"])

    def test_history(self):
        a = self.create(name="A")["project"]["id"]
        repo.save_project(self.db, a, self.config, new_version=True, model="m2")
        b = self.create(name="B")["project"]["id"]
        history = repo.list_history(self.db)
        self.assertEqual([(h["project_name"], h["version"]) for h in history], [("B", 1), ("A", 2), ("A", 1)])
        self.assertEqual(history[1]["model_name"], "m2")
        self.assertTrue(all(h["status"] == "success" and h["project_id"] in (a, b) for h in history))
        self.assertEqual(len(repo.list_history(self.db, limit=2)), 2)

    def test_history_shortens_long_prompts(self):
        config = copy.deepcopy(self.config)
        config["meta"]["prompt"] = "w " * 400
        self.create(config=valid(config))
        prompt = repo.list_history(self.db)[0]["prompt"]
        self.assertLessEqual(len(prompt), repo.PROMPT_PREVIEW_MAX + 3)
        self.assertTrue(prompt.endswith("..."))

    def test_unicode_and_pictures_survive(self):
        config = make_config(("hero", "about", "features", "contact"))
        config["meta"]["site_name"] = "Kuya's Ramen \u1e9e \u20b1 \U0001F35C"
        config["sections"][0]["data"]["image"] = "data:image/png;base64," + base64.b64encode(PNG[:8] + b"0" * 300_000).decode()
        pid = self.create(config=valid(config))["project"]["id"]
        opened = repo.get_project(self.db, pid)["config"]
        self.assertEqual(opened["meta"]["site_name"], "Kuya's Ramen \u1e9e \u20b1 \U0001F35C")
        self.assertEqual(opened["sections"][0]["data"]["image"], valid(config)["sections"][0]["data"]["image"])

    def test_stored_values_fit_the_mysql_columns(self):
        """MySQL refuses text longer than its column. Check what we store against schema.sql."""
        config = copy.deepcopy(self.config)
        config["meta"]["site_name"] = "s" * 60
        pid = self.create(name="n" * 500, config=valid(config), model="m" * 500)["project"]["id"]
        repo.save_project(self.db, pid, valid(config), new_version=True, model="m" * 500)
        lengths = mysql_schema_tables()
        checks = {
            "projects": ("SELECT name, category FROM projects", ("name", "category")),
            "generated_websites": ("SELECT model_name FROM generated_websites", ("model_name",)),
            "project_settings": ("SELECT design_style, color_scheme, primary_color, font_heading, font_body FROM project_settings",
                                 ("design_style", "color_scheme", "primary_color", "font_heading", "font_body")),
        }
        for table, (sql, columns) in checks.items():
            for row in self.conn.run(sql):
                for column, value in zip(columns, row):
                    self.assertLessEqual(len(value), lengths[table]["lengths"][column], f"{table}.{column}")

    def test_a_failed_save_leaves_nothing_behind(self):
        with mock.patch.object(repo, "_insert_version", side_effect=sqlite3.OperationalError("disk full")):
            with self.assertLogs("app.services.database", level="ERROR"), self.assertRaises(DatabaseError):
                self.create()
        self.assertEqual((self.count("projects"), self.count("project_settings"), self.count("generated_websites")), (0, 0, 0))

    def test_a_failed_new_version_does_not_change_the_project(self):
        pid = self.create()["project"]["id"]
        with mock.patch.object(repo, "_write_settings", side_effect=sqlite3.OperationalError("boom")):
            with self.assertLogs("app.services.database", level="ERROR"), self.assertRaises(DatabaseError):
                repo.save_project(self.db, pid, self.config, new_version=True, name="Changed")
        self.assertEqual(self.count("generated_websites"), 1)
        self.assertEqual(repo.get_project(self.db, pid)["project"]["name"], "Kuya's Ramen")

    def test_damaged_stored_data_is_reported_not_trusted(self):
        pid = self.create()["project"]["id"]
        for bad in ("{not json", json.dumps({"version": 1}), json.dumps([1, 2]), "null"):
            self.conn.run("UPDATE generated_websites SET config_json = ?", (bad,))
            with self.assertRaises(DamagedDataError):
                repo.get_project(self.db, pid)
        self.assertEqual(len(repo.list_projects(self.db)), 1)                          # the list still works

    def test_stored_data_is_cleaned_again_when_opened(self):
        pid = self.create()["project"]["id"]
        tampered = copy.deepcopy(self.config)
        tampered["sections"][0]["data"]["headline"] = "<script>alert(1)</script>Hello"
        tampered["sections"][0]["data"]["primary_cta"]["target"] = "javascript:alert(1)"
        self.conn.run("UPDATE generated_websites SET config_json = ?", (json.dumps(tampered),))
        hero = repo.get_project(self.db, pid)["config"]["sections"][0]["data"]
        self.assertNotIn("<", hero["headline"])
        self.assertIn(hero["primary_cta"]["target"], {"hero", "about", "menu", "contact"})

    def test_drivers_may_return_bytes_or_already_parsed_json(self):
        text = json.dumps(self.config)
        self.assertEqual(repo._config_from_stored(text.encode("utf-8")), self.config)
        self.assertEqual(repo._config_from_stored(bytearray(text.encode("utf-8"))), self.config)
        self.assertEqual(repo._config_from_stored(self.config), self.config)

    def test_dates_are_iso_text(self):
        from datetime import datetime
        self.assertEqual(repo._iso(datetime(2026, 11, 25, 10, 30, 5, 999)), "2026-11-25T10:30:05")
        self.assertEqual(repo._iso("2026-11-25 10:30:05"), "2026-11-25T10:30:05")
        self.assertIsNone(repo._iso(None))


# ------------------------------------------------------------------ connection layer
class FakeDriverError(Exception):
    def __init__(self, errno, message="driver says no"):
        super().__init__(message)
        self.errno = errno


class DatabaseLayerTests(unittest.TestCase):
    def test_disabled_database(self):
        db = Database(DisabledConnector(), enabled=False)
        self.assertEqual(db.status(), {"enabled": False, "connected": False, "message": MSG_OFF})
        with self.assertRaises(DatabaseUnavailableError):
            with db.connection():
                pass

    def test_status_when_ready(self):
        db, _ = sqlite_database()
        self.assertEqual(db.status(), {"enabled": True, "connected": True, "message": "Connected."})

    def test_status_when_the_tables_are_missing(self):
        db, _ = sqlite_database(with_schema=False)
        status = db.status()
        self.assertFalse(status["connected"])
        self.assertEqual(status["message"], MSG_NO_TABLES)

    def test_error_messages_are_friendly_and_safe(self):
        cases = {1045: (DatabaseUnavailableError, MSG_ACCESS), 1044: (DatabaseUnavailableError, MSG_ACCESS),
                 2003: (DatabaseUnavailableError, MSG_UNREACHABLE), 2006: (DatabaseUnavailableError, MSG_UNREACHABLE),
                 1146: (DatabaseError, MSG_NO_TABLES), 1153: (DatabaseError, MSG_PACKET),
                 1062: (DatabaseError, MSG_OTHER)}
        for errno, (kind, message) in cases.items():
            error = translate_error(FakeDriverError(errno, "Access denied for user 'root'@'localhost' (using password: YES)"))
            self.assertIs(type(error), kind, errno)
            self.assertEqual(error.message, message)
            self.assertNotIn("root", error.message)

    def test_driver_errors_inside_a_connection_become_database_errors(self):
        db, _ = sqlite_database()
        with self.assertLogs("app.services.database", level="ERROR"):
            with self.assertRaises(DatabaseUnavailableError) as caught:
                with db.connection():
                    raise FakeDriverError(1045)
        self.assertEqual(caught.exception.message, MSG_ACCESS)

    def test_programming_mistakes_are_not_hidden(self):
        db, _ = sqlite_database()
        with self.assertRaises(ZeroDivisionError):
            with db.connection():
                1 / 0

    def test_connections_are_always_returned(self):
        db, conn = sqlite_database()
        with db.connection():
            pass
        with self.assertRaises(ZeroDivisionError):
            with db.connection():
                1 / 0
        self.assertEqual(conn.closed_calls, 2)

    def test_transactions_commit_or_roll_back(self):
        db, conn = sqlite_database()
        with db.transaction() as connection:
            connection.cursor().execute("INSERT INTO users (email, password_hash, display_name) VALUES (%s, %s, %s)", ("a@b.c", "x", "A"))
        self.assertEqual(conn.run("SELECT COUNT(*) FROM users")[0][0], 1)
        with self.assertRaises(RuntimeError):
            with db.transaction() as connection:
                connection.cursor().execute("INSERT INTO users (email, password_hash, display_name) VALUES (%s, %s, %s)", ("d@e.f", "x", "D"))
                raise RuntimeError("stop")
        self.assertEqual(conn.run("SELECT COUNT(*) FROM users")[0][0], 1)

    def test_no_transaction_is_left_open_when_a_connection_goes_back(self):
        calls = []

        class Connection:
            def rollback(self):
                calls.append("rollback")

            def close(self):
                calls.append("close")

        with Database(lambda: Connection()).connection():
            pass
        self.assertEqual(calls, ["rollback", "close"])

    def test_stale_connections_are_revived_before_use(self):
        calls = []

        class Connection:
            def ping(self, reconnect=False, attempts=1, delay=0):
                calls.append((reconnect, attempts, delay))

            def close(self):
                calls.append("closed")

        with Database(lambda: Connection()).connection():
            pass
        self.assertEqual(calls, [(True, 1, 0), "closed"])                       # no rollback method here: skipped quietly

    def test_a_dead_connection_is_reported(self):
        class Connection:
            def ping(self, **kwargs):
                raise FakeDriverError(2013)

            def close(self):
                pass

        with self.assertRaises(DatabaseUnavailableError):
            with Database(lambda: Connection()).connection():
                pass


class FakePoolModule:
    """Stands in for mysql.connector so the settings we pass can be checked without MySQL."""

    def __init__(self):
        self.created = []
        self.fail_with = None
        self.module_tree = {}

    def install(self, case):
        outer = self

        class Pool:
            def __init__(self, **kwargs):
                if outer.fail_with:
                    raise outer.fail_with
                outer.created.append(kwargs)

            def get_connection(self):
                return "connection"

        pooling = types.ModuleType("mysql.connector.pooling")
        pooling.MySQLConnectionPool = Pool
        connector = types.ModuleType("mysql.connector")
        connector.pooling = pooling
        package = types.ModuleType("mysql")
        package.connector = connector
        patch = mock.patch.dict(sys.modules, {"mysql": package, "mysql.connector": connector,
                                              "mysql.connector.pooling": pooling})
        patch.start()
        case.addCleanup(patch.stop)


class MySQLConnectorTests(unittest.TestCase):
    def make(self, **overrides):
        settings = dict(host="db.local", port=3307, user="siteforge", password="s3cret-pw", database="siteforge_ai",
                        pool_size=4, timeout=3)
        settings.update(overrides)
        return MySQLConnector(**settings)

    def test_pool_settings(self):
        fake = FakePoolModule()
        fake.install(self)
        self.assertEqual(self.make()(), "connection")
        settings = fake.created[0]
        for key, value in dict(host="db.local", port=3307, user="siteforge", password="s3cret-pw",
                               database="siteforge_ai", pool_size=4, connection_timeout=3, charset="utf8mb4",
                               collation="utf8mb4_unicode_ci", autocommit=False, pool_reset_session=True).items():
            self.assertEqual(settings[key], value, key)

    def test_one_pool_is_shared(self):
        fake = FakePoolModule()
        fake.install(self)
        connector = self.make()
        connector(), connector(), connector()
        self.assertEqual(len(fake.created), 1)

    def test_pool_size_is_limited(self):
        fake = FakePoolModule()
        fake.install(self)
        self.make(pool_size=500)()
        self.make(pool_size=0)()
        self.assertEqual([c["pool_size"] for c in fake.created], [32, 1])

    def test_failure_is_translated_and_retried_later(self):
        fake = FakePoolModule()
        fake.install(self)
        connector = self.make()
        fake.fail_with = FakeDriverError(1045, "Access denied for user 'siteforge' (using password: YES)")
        with self.assertLogs("app.services.database", level="WARNING") as logs:
            with self.assertRaises(DatabaseUnavailableError) as caught:
                connector()
        self.assertEqual(caught.exception.message, MSG_ACCESS)
        fake.fail_with = None
        self.assertEqual(connector(), "connection")                         # MySQL came back: no restart needed
        self.assertNotIn("s3cret-pw", " ".join(logs.output))
        self.assertNotIn("s3cret-pw", caught.exception.message)

    def test_unreachable_server(self):
        fake = FakePoolModule()
        fake.install(self)
        fake.fail_with = FakeDriverError(2003, "Can't connect to MySQL server on 'db.local:3307'")
        with self.assertLogs("app.services.database", level="WARNING"):
            with self.assertRaises(DatabaseUnavailableError) as caught:
                self.make()()
        self.assertEqual(caught.exception.message, MSG_UNREACHABLE)

    def test_missing_driver(self):
        with mock.patch.dict(sys.modules, {"mysql": None, "mysql.connector": None, "mysql.connector.pooling": None}):
            with self.assertRaises(DatabaseUnavailableError) as caught:
                self.make()()
        self.assertEqual(caught.exception.message, MSG_DRIVER)

    def test_build_database_follows_the_settings(self):
        from app.services.database import build_database
        config = {"DATABASE_ENABLED": False}
        self.assertFalse(build_database(config).enabled)
        config = dict(DATABASE_ENABLED=True, MYSQL_HOST="h", MYSQL_PORT=3306, MYSQL_USER="u", MYSQL_PASSWORD="p",
                      MYSQL_DATABASE="d")
        self.assertTrue(build_database(config).enabled)


# ------------------------------------------------------------------ API
class ProjectApiTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app("testing")
        self.db, self.conn = sqlite_database()
        self.app.extensions["database"] = self.db
        self.client = self.app.test_client()
        self.config = sample_config()

    def create(self, **extra):
        body = dict({"config": self.config, "name": "Kuya's Ramen", "model": "llama3.1:8b"}, **extra)
        response = self.client.post("/api/projects", json=body)
        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        return response.get_json()

    def test_full_life_of_a_project(self):
        created = self.create()
        pid = created["project"]["id"]
        self.assertEqual(created["version"], {"version": 1})
        self.assertNotIn("config", created)                                      # responses stay small

        listing = self.client.get("/api/projects").get_json()["projects"]
        self.assertEqual([p["name"] for p in listing], ["Kuya's Ramen"])

        opened = self.client.get(f"/api/projects/{pid}").get_json()
        self.assertEqual(opened["config"], valid(self.config))
        self.assertEqual(opened["version"]["version"], 1)

        edited = copy.deepcopy(self.config)
        edited["sections"][0]["data"]["headline"] = "Edited headline"
        saved = self.client.put(f"/api/projects/{pid}", json={"config": edited, "name": "Better name"}).get_json()
        self.assertEqual(saved["project"]["name"], "Better name")
        self.assertEqual(saved["project"]["version_count"], 1)

        newer = self.client.put(f"/api/projects/{pid}", json={"config": edited, "new_version": True}).get_json()
        self.assertEqual(newer["version"], {"version": 2})

        renamed = self.client.patch(f"/api/projects/{pid}", json={"name": "Final name"}, headers=GUARD).get_json()
        self.assertEqual(renamed["project"]["name"], "Final name")

        duplicate = self.client.post(f"/api/projects/{pid}/duplicate", headers=GUARD)
        self.assertEqual(duplicate.status_code, 201)
        self.assertEqual(duplicate.get_json()["project"]["name"], "Final name (copy)")
        self.assertEqual(len(self.client.get("/api/projects").get_json()["projects"]), 2)

        history = self.client.get("/api/history").get_json()["history"]
        self.assertEqual(len(history), 3)

        deleted = self.client.delete(f"/api/projects/{pid}", headers=GUARD)
        self.assertEqual(deleted.get_json(), {"deleted": pid})
        self.assertEqual(self.client.get(f"/api/projects/{pid}").status_code, 404)
        self.assertEqual(len(self.client.get("/api/projects").get_json()["projects"]), 1)

    def test_open_a_specific_version(self):
        pid = self.create()["project"]["id"]
        edited = copy.deepcopy(self.config)
        edited["sections"][0]["data"]["headline"] = "Second"
        self.client.put(f"/api/projects/{pid}", json={"config": edited, "new_version": True})
        first = self.client.get(f"/api/projects/{pid}?version=1").get_json()
        self.assertNotEqual(first["config"]["sections"][0]["data"]["headline"], "Second")
        self.assertEqual(self.client.get(f"/api/projects/{pid}?version=9").status_code, 404)
        for bad in ("0", "-1", "abc"):
            self.assertEqual(self.client.get(f"/api/projects/{pid}?version={bad}").status_code, 400, bad)

    def test_default_name_is_the_site_name(self):
        created = self.client.post("/api/projects", json={"config": self.config}).get_json()
        self.assertEqual(created["project"]["name"], "Kuya's Ramen")

    def test_names_are_cleaned(self):
        created = self.create(name="<img src=x onerror=alert(1)>Tidy <b>name</b>")
        self.assertEqual(created["project"]["name"], "Tidy name")

    def test_invalid_input_is_refused(self):
        bad = copy.deepcopy(self.config)
        bad["theme"]["primary"] = "red"
        response = self.client.post("/api/projects", json={"config": bad})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "invalid_configuration")
        self.assertTrue(response.get_json()["problems"])
        for body in ({}, {"config": None}, {"config": "text"}, [1]):
            self.assertEqual(self.client.post("/api/projects", json=body).status_code, 400)
        self.assertEqual(self.client.get("/api/projects").get_json()["projects"], [])

    def test_blank_rename_is_refused(self):
        pid = self.create()["project"]["id"]
        for name in ("", "   ", "<b></b>", None, 5):
            response = self.client.patch(f"/api/projects/{pid}", json={"name": name}, headers=GUARD)
            self.assertEqual(response.status_code, 400, name)
        self.assertEqual(self.client.get(f"/api/projects/{pid}").get_json()["project"]["name"], "Kuya's Ramen")

    def test_bad_version_in_save(self):
        pid = self.create()["project"]["id"]
        for version in (0, -3, "1", True, 1.5):
            response = self.client.put(f"/api/projects/{pid}", json={"config": self.config, "version": version})
            self.assertEqual(response.status_code, 400, version)

    def test_unknown_projects(self):
        for call in (lambda: self.client.get("/api/projects/999"),
                     lambda: self.client.put("/api/projects/999", json={"config": self.config}),
                     lambda: self.client.patch("/api/projects/999", json={"name": "x"}, headers=GUARD),
                     lambda: self.client.delete("/api/projects/999", headers=GUARD),
                     lambda: self.client.post("/api/projects/999/duplicate", headers=GUARD),
                     lambda: self.client.get("/api/projects/abc"),
                     lambda: self.client.get("/api/projects/99999999999999999999")):
            response = call()
            self.assertEqual(response.status_code, 404)

    def test_changing_things_requires_a_same_site_request(self):
        pid = self.create()["project"]["id"]
        for call in (lambda: self.client.delete(f"/api/projects/{pid}"),
                     lambda: self.client.post(f"/api/projects/{pid}/duplicate"),
                     lambda: self.client.patch(f"/api/projects/{pid}")):
            self.assertEqual(call().status_code, 403)
        # a form post from another website
        response = self.client.post(f"/api/projects/{pid}/duplicate", data={"x": "1"})
        self.assertEqual(response.status_code, 415)
        self.assertEqual(self.client.post("/api/projects", data="x", content_type="text/plain").status_code, 415)
        self.assertEqual(len(self.client.get("/api/projects").get_json()["projects"]), 1)    # nothing changed
        self.assertEqual(self.client.delete(f"/api/projects/{pid}", headers=GUARD).status_code, 200)

    def test_reading_needs_no_header(self):
        for path in ("/api/projects", "/api/history", "/api/db/status"):
            self.assertEqual(self.client.get(path).status_code, 200)

    def test_listing_limits(self):
        for index in range(3):
            self.create(name=f"P{index}")
        self.assertEqual(len(self.client.get("/api/projects?limit=2").get_json()["projects"]), 2)
        self.assertEqual(len(self.client.get("/api/projects?limit=99999").get_json()["projects"]), 3)
        self.assertEqual(len(self.client.get("/api/projects?limit=abc").get_json()["projects"]), 3)
        self.assertEqual(len(self.client.get("/api/history?limit=1").get_json()["history"]), 1)

    def test_pictures_make_it_through(self):
        config = make_config(("hero", "about", "features", "contact"))
        picture = "data:image/png;base64," + base64.b64encode(PNG[:8] + b"0" * 400_000).decode()
        for section in config["sections"][:2]:
            section["data"]["image"] = picture
        pid = self.client.post("/api/projects", json={"config": config}).get_json()["project"]["id"]
        opened = self.client.get(f"/api/projects/{pid}").get_json()["config"]
        self.assertEqual(opened["sections"][0]["data"]["image"], picture)
        self.assertEqual(opened["sections"][1]["data"]["image"], picture)

    def test_saving_accepts_large_requests_but_not_huge_ones(self):
        response = self.client.post("/api/projects", json={"config": self.config, "pad": "y" * (5 * 1024 * 1024)})
        self.assertEqual(response.status_code, 201)
        response = self.client.post("/api/projects", json={"config": self.config, "pad": "y" * (13 * 1024 * 1024)})
        self.assertEqual(response.status_code, 413)

    def test_database_status(self):
        self.assertEqual(self.client.get("/api/db/status").get_json()["connected"], True)

    def test_a_driver_failure_is_reported_without_details(self):
        with mock.patch.object(repo, "_insert_version", side_effect=sqlite3.OperationalError("secret table detail")):
            with self.assertLogs("app.services.database", level="ERROR"):
                response = self.client.post("/api/projects", json={"config": self.config})
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("secret", response.get_data(as_text=True))
        self.assertEqual(response.get_json()["error"], "database_error")

    def test_everything_reports_a_clear_message_when_the_database_is_off(self):
        client = create_app("testing").test_client()                 # the testing config switches it off
        for response in (client.get("/api/projects"), client.get("/api/history"), client.get("/api/projects/1"),
                         client.post("/api/projects", json={"config": self.config}),
                         client.delete("/api/projects/1", headers=GUARD)):
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.get_json()["error"], "database_unavailable")
            self.assertEqual(response.get_json()["message"], MSG_OFF)
        status = client.get("/api/db/status").get_json()
        self.assertEqual((status["enabled"], status["connected"]), (False, False))

    def test_missing_tables_give_setup_advice(self):
        self.app.extensions["database"], _ = sqlite_database(with_schema=False)
        response = self.client.get("/api/projects")
        self.assertEqual(response.status_code, 500)
        self.assertIn("schema.sql", response.get_json()["message"])

    def test_the_other_features_work_without_a_database(self):
        client = create_app("testing").test_client()
        self.assertEqual(client.get("/api/health").status_code, 200)
        self.assertEqual(client.post("/api/render", json={"config": self.config}).status_code, 200)
        self.assertEqual(client.get("/api/schema").status_code, 200)

    def test_health_still_hides_secrets(self):
        body = self.client.get("/api/health").get_data(as_text=True).lower()
        for word in ("password", "secret", "mysql"):
            self.assertNotIn(word, body)


# ------------------------------------------------------------------ pages and scripts
class PageTests(unittest.TestCase):
    def setUp(self):
        self.client = create_app("testing").test_client()

    def test_dashboard_has_live_project_and_history_areas(self):
        html = self.client.get("/dashboard").get_data(as_text=True)
        for needle in ('id="projects-list"', 'id="projects-empty"', 'id="projects-error"', 'id="projects-retry"',
                       'id="history-list"', 'id="history-empty"', 'id="db-badge"', 'id="db-refresh"',
                       'id="category-data"', "js/dashboard.js"):
            self.assertIn(needle, html)

    def test_category_names_are_embedded_safely(self):
        html = self.client.get("/dashboard").get_data(as_text=True)
        block = html.split('id="category-data">')[1].split("</script>")[0]
        names = {c["id"]: c["name"] for c in json.loads(block)}
        self.assertEqual(names["restaurant"], "Restaurant")
        self.assertEqual(len(names), 8)

    def test_builder_has_the_project_bar(self):
        html = self.client.get("/builder").get_data(as_text=True)
        for needle in ('id="project-bar"', 'id="project-name"', 'id="project-save"', 'id="project-download"',
                       'id="project-status"', 'id="project-error"', 'id="project-open-message"', "js/projects.js"):
            self.assertIn(needle, html)

    def test_dashboard_page_does_not_load_builder_scripts(self):
        html = self.client.get("/dashboard").get_data(as_text=True)
        for name in ("builder.js", "editor.js", "projects.js", "preview.js"):
            self.assertNotIn(name, html)

    def test_project_pages_open_through_the_builder_address(self):
        for path in ("/builder?project=5", "/builder?project=5&version=2", "/builder?project=<script>"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("<script>alert", response.get_data(as_text=True))


class ScriptSafetyTests(unittest.TestCase):
    def setUp(self):
        client = create_app("testing").test_client()
        self.sources = {}
        for name in ("dashboard", "projects", "builder", "editor", "preview"):
            response = client.get(f"/static/js/{name}.js")
            self.sources[name] = response.get_data(as_text=True)
            response.close()

    def test_nothing_from_the_server_is_inserted_as_html(self):
        for name, source in self.sources.items():
            for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
                self.assertNotIn(banned, source, f"{name}.js uses {banned}")

    def test_changing_requests_carry_the_same_site_header(self):
        for name in ("dashboard", "projects"):
            self.assertIn('"X-SiteForge-Request": "1"', self.sources[name], name)
        for name in ("builder", "editor"):                       # their cancel requests have no body
            self.assertIn('"X-SiteForge-Request": "1"', self.sources[name], name)

    def test_the_address_is_read_as_a_number(self):
        self.assertIn(r"/^\d{1,15}$/", self.sources["projects"])


if __name__ == "__main__":
    unittest.main()
