"""MySQL connection handling.

* Connections come from a pool and are created the first time they are needed,
  so the application starts (and everything except saving works) even when
  MySQL is not running.
* Driver errors are turned into DatabaseError messages that are safe to show
  to the user. Details are written to the server log, never sent to the browser.
"""
import logging
import threading
from contextlib import contextmanager

log = logging.getLogger(__name__)

MSG_DRIVER = "The MySQL driver is not installed. Run: pip install -r requirements.txt"
MSG_OFF = "The database is turned off. Set DATABASE_ENABLED=1 in your .env file to save projects."
MSG_UNREACHABLE = ("SiteForge could not reach MySQL. Check that MySQL is running and that "
                   "the MYSQL_ settings in your .env file are correct.")
MSG_ACCESS = "MySQL refused the user name or password. Check MYSQL_USER and MYSQL_PASSWORD in your .env file."
MSG_NO_DATABASE = "The database does not exist yet. Run database\\schema.sql in MySQL first."
MSG_NO_TABLES = "The database tables are missing. Run database\\schema.sql in MySQL first."
MSG_PACKET = ("This website is too large for the database's packet limit. "
              "Raise max_allowed_packet in the MySQL settings, or remove some pictures.")
MSG_OTHER = "The database reported an error. Check the SiteForge server log for details."


class DatabaseError(Exception):
    """A database problem. `message` is safe to show to the user."""

    code = "database_error"
    http_status = 500

    def __init__(self, message):
        super().__init__(message)
        self.message = message


class DatabaseUnavailableError(DatabaseError):
    code = "database_unavailable"
    http_status = 503


class NotFoundError(DatabaseError):
    code = "not_found"
    http_status = 404


class DamagedDataError(DatabaseError):
    code = "project_damaged"
    http_status = 422


def translate_error(exc):
    """Turn a driver exception into a DatabaseError with a helpful, safe message."""
    errno = getattr(exc, "errno", None)
    if errno in (1044, 1045):
        return DatabaseUnavailableError(MSG_ACCESS)
    if errno == 1049:
        return DatabaseUnavailableError(MSG_NO_DATABASE)
    if errno in (2002, 2003, 2006, 2013, 2055):
        return DatabaseUnavailableError(MSG_UNREACHABLE)
    if errno == 1146:
        return DatabaseError(MSG_NO_TABLES)
    if errno == 1153:
        return DatabaseError(MSG_PACKET)
    if "no such table" in str(exc).lower():          # the in-memory database used by the tests
        return DatabaseError(MSG_NO_TABLES)
    return DatabaseError(MSG_OTHER)


def _is_driver_error(exc):
    return hasattr(exc, "errno") or type(exc).__module__.split(".")[0] in ("mysql", "sqlite3")


class DisabledConnector:
    """Used when DATABASE_ENABLED=0."""

    def __call__(self):
        raise DatabaseUnavailableError(MSG_OFF)


class MySQLConnector:
    """Creates connections from a pool. The pool is built on first use and rebuilt if that failed."""

    def __init__(self, host, port, user, password, database, pool_size=5, timeout=5):
        self.settings = {
            "host": host, "port": port, "user": user, "password": password, "database": database,
            "connection_timeout": timeout, "charset": "utf8mb4", "collation": "utf8mb4_unicode_ci",
            "autocommit": False,
        }
        self.pool_size = max(1, min(int(pool_size), 32))
        self._pool = None
        self._lock = threading.Lock()

    def __call__(self):
        try:
            from mysql.connector import pooling
        except ImportError as exc:
            raise DatabaseUnavailableError(MSG_DRIVER) from exc

        with self._lock:
            if self._pool is None:
                try:
                    self._pool = pooling.MySQLConnectionPool(
                        pool_name="siteforge", pool_size=self.pool_size, pool_reset_session=True, **self.settings)
                except Exception as exc:
                    log.warning("Could not create the MySQL connection pool for %s:%s: %s",
                                self.settings["host"], self.settings["port"], exc)
                    raise translate_error(exc) from exc
            pool = self._pool
        try:
            return pool.get_connection()
        except Exception as exc:
            log.warning("Could not get a MySQL connection from the pool: %s", exc)
            raise translate_error(exc) from exc


class Database:
    """Gives out connections and transactions. `connect` is any function returning a DB-API connection."""

    def __init__(self, connect, enabled=True):
        self._connect = connect
        self.enabled = enabled

    @contextmanager
    def connection(self):
        connection = self._connect()
        try:
            ping = getattr(connection, "ping", None)
            if ping is not None:
                try:
                    ping(reconnect=True, attempts=1, delay=0)     # revive a connection MySQL closed
                except Exception as exc:
                    log.warning("MySQL ping failed: %s", exc)
                    raise translate_error(exc) from exc
            yield connection
        except DatabaseError:
            raise
        except Exception as exc:
            if _is_driver_error(exc):
                log.exception("Database error")
                raise translate_error(exc) from exc
            raise
        finally:
            try:
                connection.rollback()               # end any read transaction so a pooled connection is never stale
            except Exception:
                pass
            try:
                connection.close()                  # returns it to the pool
            except Exception:
                pass

    @contextmanager
    def transaction(self):
        """Everything inside happens together or not at all."""
        with self.connection() as connection:
            try:
                yield connection
                connection.commit()
            except BaseException:
                try:
                    connection.rollback()
                except Exception:
                    pass
                raise

    def status(self):
        """Report the state of the database without ever raising."""
        try:
            with self.connection() as connection:
                cursor = connection.cursor()
                cursor.execute("SELECT id FROM projects LIMIT 1")
                cursor.fetchall()
                cursor.close()
            return {"enabled": self.enabled, "connected": True, "message": "Connected."}
        except DatabaseError as exc:
            return {"enabled": self.enabled, "connected": False, "message": exc.message}


def build_database(config):
    """Create the Database for a Flask config."""
    if not config.get("DATABASE_ENABLED", True):
        return Database(DisabledConnector(), enabled=False)
    return Database(MySQLConnector(
        config["MYSQL_HOST"], config["MYSQL_PORT"], config["MYSQL_USER"], config["MYSQL_PASSWORD"],
        config["MYSQL_DATABASE"], config.get("DB_POOL_SIZE", 5), config.get("DB_CONNECT_TIMEOUT", 5)))
