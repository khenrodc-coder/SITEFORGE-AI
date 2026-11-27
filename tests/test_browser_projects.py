"""Optional real-browser tests for saving and managing projects (skipped without Playwright).

    pip install playwright
    python -m playwright install chromium
    python -m unittest tests.test_browser_projects -v

The app runs against an in-memory test database and a fake AI model, so neither MySQL nor Ollama is needed.
"""
import copy
import logging
import threading
import time
import unittest
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
    HAVE_PLAYWRIGHT = True
except ImportError:                      # pragma: no cover
    HAVE_PLAYWRIGHT = False

from app import create_app
from app.services import project_repository as repo
from app.services.database import Database, DisabledConnector
from app.services.site_schema import validate_site_config
from tests.fake_ollama import FakeOllama
from tests.sample_sections import make_responder
from tests.sqlite_support import sqlite_database
from tests.test_phase5 import sample_config

PROMPT = "A late-night ramen bar in Cebu City with a menu and reservations."


@unittest.skipUnless(HAVE_PLAYWRIGHT, "Playwright is not installed (optional browser tests)")
class ProjectBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from werkzeug.serving import make_server
        logging.getLogger("werkzeug").setLevel(logging.ERROR)
        cls.fake = FakeOllama().start()
        cls.app = create_app("testing")
        cls.app.config["OLLAMA_BASE_URL"] = cls.fake.url
        cls.app.config["OLLAMA_TIMEOUT"] = 5
        cls.db, cls.conn = sqlite_database()
        cls.app.extensions["database"] = cls.db
        cls.server = make_server("127.0.0.1", 0, cls.app, threaded=True)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        cls.pw = sync_playwright().start()
        try:
            cls.browser = cls.pw.chromium.launch()
        except Exception as exc:
            cls.pw.stop()
            cls.server.shutdown()
            cls.fake.stop()
            raise unittest.SkipTest(f"Chromium is not available: {exc}")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.server.shutdown()
        cls.fake.stop()

    def setUp(self):
        self.conn.run("DELETE FROM projects")
        self.app.extensions["database"] = self.db
        self.fake.delay = 0
        self.fake.models = ["llama3.1:8b"]
        self.fake.requests.clear()
        self.fake.responder = make_responder(sections=("hero", "about", "menu", "contact"))

    # -------------------------------------------------------------- helpers
    def new_page(self, width=1400, accept_downloads=False):
        context = self.browser.new_context(viewport={"width": width, "height": 1000}, accept_downloads=accept_downloads)
        self.addCleanup(context.close)
        page = context.new_page()
        self.errors = []
        page.on("pageerror", lambda e: self.errors.append(str(e)) if "tailwind" not in str(e) else None)
        page.on("dialog", lambda d: d.accept())
        return page

    @staticmethod
    def click(page, selector):
        page.locator(selector).first.dispatch_event("click")

    @staticmethod
    def frame(page):
        return page.query_selector("#preview-frame").content_frame()

    def eventually(self, check, timeout=10, message="condition was never met"):
        end = time.time() + timeout
        last = None
        while time.time() < end:
            try:
                last = check()
                if last:
                    return last
            except Exception as exc:
                last = exc
            time.sleep(0.1)
        self.fail(f"{message} (last value: {last!r})")

    def generate(self, page):
        page.goto(self.base + "/builder", wait_until="domcontentloaded")
        page.fill("#prompt", PROMPT)
        self.click(page, "#generate-button")
        page.wait_for_function("document.getElementById('preview-busy').classList.contains('is-hidden')"
                               " && document.querySelectorAll('#editor-sections .sec').length > 0", timeout=20000)

    def make_project(self, name="Kuya's Ramen", headline=None):
        config = copy.deepcopy(sample_config())
        if headline:
            config["sections"][0]["data"]["headline"] = headline
        return repo.create_project(self.db, name, validate_site_config(config), "llama3.1:8b")["project"]["id"]

    def project_names(self):
        return [p["name"] for p in repo.list_projects(self.db)]

    def edit_headline(self, page, text):
        if page.get_attribute('.sec[data-sec-id="hero"] .sec-toggle', "aria-expanded") != "true":
            self.click(page, '.sec[data-sec-id="hero"] .sec-toggle')
        page.locator('.sec[data-sec-id="hero"] [data-field="headline"]').first.fill(text)

    # -------------------------------------------------------------- the builder
    def test_save_a_new_project(self):
        page = self.new_page()
        self.generate(page)
        self.assertEqual(page.input_value("#project-name"), "Kuya's Ramen")
        self.assertEqual(page.inner_text("#project-status"), "Not saved yet.")
        self.assertTrue(page.evaluate("window.SiteForgeEditor.hasUnsavedChanges()"))
        self.click(page, "#project-save")
        self.eventually(lambda: page.inner_text("#project-status").startswith("Saved at"))
        self.assertEqual(self.project_names(), ["Kuya's Ramen"])
        self.assertFalse(page.evaluate("window.SiteForgeEditor.hasUnsavedChanges()"))
        self.assertRegex(page.url, r"/builder\?project=\d+$")
        self.assertEqual(self.errors, [])

    def test_edit_save_and_reopen(self):
        page = self.new_page()
        self.generate(page)
        self.edit_headline(page, "Saved for later")
        self.eventually(lambda: self.frame(page).inner_text("h1") == "Saved for later")
        self.assertEqual(page.inner_text("#project-status"), "Unsaved changes.")
        page.fill("#project-name", "Midnight Noodles")
        self.click(page, "#project-save")
        self.eventually(lambda: page.inner_text("#project-status").startswith("Saved at"))
        self.assertEqual(self.project_names(), ["Midnight Noodles"])

        reopened = self.new_page()
        reopened.goto(page.url, wait_until="domcontentloaded")
        self.eventually(lambda: self.frame(reopened).inner_text("h1") == "Saved for later", timeout=15)
        self.assertEqual(reopened.input_value("#project-name"), "Midnight Noodles")
        self.assertEqual(reopened.input_value("#prompt"), PROMPT)                     # ready to regenerate
        self.assertEqual(reopened.evaluate("document.querySelector('input[name=category]:checked').value"), "restaurant")
        self.assertFalse(reopened.evaluate("window.SiteForgeEditor.hasUnsavedChanges()"))
        self.assertEqual(reopened.inner_text("h1"), "Edit project")
        self.assertIn("Midnight Noodles", reopened.title())
        names = reopened.evaluate("[...document.querySelectorAll('#editor-sections .sec-name')].map(e => e.textContent)")
        self.assertEqual(names, ["Home", "About", "Menu", "Contact"])

    def test_saving_again_updates_the_same_project(self):
        page = self.new_page()
        self.generate(page)
        self.click(page, "#project-save")
        self.eventually(lambda: page.inner_text("#project-status").startswith("Saved at"))
        self.edit_headline(page, "Second save")
        self.eventually(lambda: page.inner_text("#project-status") == "Unsaved changes.")
        self.click(page, "#project-save")
        self.eventually(lambda: "Saved at" in page.inner_text("#project-status") and page.inner_text("#project-status") != "Unsaved changes.")
        self.assertEqual(len(self.project_names()), 1)
        project_id = repo.list_projects(self.db)[0]["id"]
        saved = repo.get_project(self.db, project_id)
        self.assertEqual(saved["config"]["sections"][0]["data"]["headline"], "Second save")
        self.assertEqual(saved["project"]["version_count"], 1)

    def test_generating_again_inside_a_project_saves_a_new_version(self):
        page = self.new_page()
        self.generate(page)
        self.click(page, "#project-save")
        self.eventually(lambda: page.inner_text("#project-status").startswith("Saved at"))
        project_id = repo.list_projects(self.db)[0]["id"]

        self.fake.responder = make_responder(sections=("hero", "about", "menu", "contact"))
        page.fill("#prompt", "A different idea: a quiet tea house in Baguio with a menu.")
        self.click(page, "#generate-button")
        self.eventually(lambda: "new version" in page.inner_text("#project-status"), timeout=20)
        self.click(page, "#project-save")
        self.eventually(lambda: "(version 2)" in page.inner_text("#project-status"))
        saved = repo.get_project(self.db, project_id)
        self.assertEqual((saved["version"]["version"], saved["project"]["version_count"]), (2, 2))
        self.assertIn("tea house", saved["config"]["meta"]["prompt"])
        first = repo.get_project(self.db, project_id, version=1)
        self.assertEqual(first["config"]["meta"]["prompt"], PROMPT)
        self.assertEqual(len(self.project_names()), 1)

    def test_opening_an_older_version(self):
        project_id = self.make_project(headline="Version one")
        newer = copy.deepcopy(sample_config())
        newer["sections"][0]["data"]["headline"] = "Version two"
        repo.save_project(self.db, project_id, validate_site_config(newer), new_version=True)
        page = self.new_page()
        page.goto(f"{self.base}/builder?project={project_id}&version=1", wait_until="domcontentloaded")
        self.eventually(lambda: self.frame(page).inner_text("h1") == "Version one", timeout=15)
        self.assertIn("version 1", page.inner_text("#project-status"))
        page.goto(f"{self.base}/builder?project={project_id}", wait_until="domcontentloaded")
        self.eventually(lambda: self.frame(page).inner_text("h1") == "Version two", timeout=15)

    def test_a_missing_project_gives_a_clear_message(self):
        page = self.new_page()
        page.goto(self.base + "/builder?project=9999", wait_until="domcontentloaded")
        self.eventually(lambda: "could not be found" in page.inner_text("#project-open-message"))
        for bad in ("abc", "-3", "1e3", "0", "<script>alert(1)</script>"):
            page.goto(self.base + f"/builder?project={bad}", wait_until="domcontentloaded")
            time.sleep(0.2)
            self.assertEqual(page.inner_text("#project-open-message"), "", bad)         # ignored, never sent to the server
        self.assertEqual(self.errors, [])

    def test_a_project_that_was_deleted_meanwhile(self):
        page = self.new_page()
        self.generate(page)
        self.click(page, "#project-save")
        self.eventually(lambda: page.inner_text("#project-status").startswith("Saved at"))
        repo.delete_project(self.db, repo.list_projects(self.db)[0]["id"])
        self.edit_headline(page, "Edited after deletion")
        self.click(page, "#project-save")
        self.eventually(lambda: "no longer exists" in page.inner_text("#project-error"))
        self.assertEqual(page.inner_text("#project-status"), "Not saved.")
        self.click(page, "#project-save")                                              # now it creates a new project
        self.eventually(lambda: page.inner_text("#project-status").startswith("Saved at"))
        self.assertEqual(len(self.project_names()), 1)

    def test_saving_with_the_database_off_explains_what_to_do(self):
        page = self.new_page()
        self.generate(page)
        self.app.extensions["database"] = Database(DisabledConnector(), enabled=False)
        self.click(page, "#project-save")
        self.eventually(lambda: "turned off" in page.inner_text("#project-error"))
        self.assertEqual(page.inner_text("#project-status"), "Not saved.")
        self.assertTrue(page.evaluate("window.SiteForgeEditor.hasUnsavedChanges()"))
        self.assertFalse(page.is_disabled("#project-save"))                             # can try again
        self.app.extensions["database"] = self.db
        self.click(page, "#project-save")
        self.eventually(lambda: page.inner_text("#project-status").startswith("Saved at"))
        self.assertEqual(page.inner_text("#project-error"), "")

    def test_download_from_the_project_bar_includes_edits(self):
        page = self.new_page(accept_downloads=True)
        self.generate(page)
        self.edit_headline(page, "Download me")
        self.eventually(lambda: self.frame(page).inner_text("h1") == "Download me")
        with page.expect_download() as download:
            self.click(page, "#project-download")
        self.assertIn("Download me", Path(download.value.path()).read_text(encoding="utf-8"))
        self.assertIn("Downloaded", page.inner_text("#project-status"))

    def test_opened_projects_can_be_downloaded_without_generating(self):
        project_id = self.make_project(headline="From the database")
        page = self.new_page(accept_downloads=True)
        page.goto(f"{self.base}/builder?project={project_id}", wait_until="domcontentloaded")
        self.eventually(lambda: self.frame(page).inner_text("h1") == "From the database", timeout=15)
        with page.expect_download() as download:
            self.click(page, "#project-download")
        self.assertIn("From the database", Path(download.value.path()).read_text(encoding="utf-8"))

    # -------------------------------------------------------------- the dashboard
    def test_dashboard_lists_projects_and_history(self):
        first = self.make_project("Alpha")
        second = self.make_project("Beta")
        repo.save_project(self.db, first, validate_site_config(sample_config()), new_version=True, model="m2")
        self.conn.run("UPDATE projects SET updated_at = '2026-01-01 10:00:00' WHERE id = ?", (first,))
        page = self.new_page()
        page.goto(self.base + "/dashboard", wait_until="domcontentloaded")
        self.eventually(lambda: page.locator("#projects-list .project-card").count() == 2)
        self.assertEqual(page.evaluate("[...document.querySelectorAll('.project-name')].map(e => e.textContent)"), ["Beta", "Alpha"])
        card = page.locator(f'.project-card[data-project-id="{first}"]')
        self.assertIn("2 versions", card.inner_text())
        self.assertIn("Restaurant", card.inner_text())
        self.assertEqual(card.locator(".project-name").get_attribute("href"), f"/builder?project={first}")
        self.assertEqual(card.locator(".project-accent").evaluate("e => e.style.backgroundColor"), "rgb(37, 99, 235)")
        self.eventually(lambda: page.locator("#history-list .history-item").count() == 3)
        links = page.evaluate("[...document.querySelectorAll('#history-list a')].map(a => a.getAttribute('href'))")
        self.assertEqual(links, [f"/builder?project={first}&version=2", f"/builder?project={second}&version=1",
                                 f"/builder?project={first}&version=1"])
        self.eventually(lambda: page.inner_text("#db-text") == "Connected")
        self.assertEqual(self.errors, [])
        self.assertEqual(second, repo.list_projects(self.db)[0]["id"])

    def test_dashboard_empty_state(self):
        page = self.new_page()
        page.goto(self.base + "/dashboard", wait_until="domcontentloaded")
        self.eventually(lambda: not page.evaluate("document.getElementById('projects-empty').hidden"))
        self.eventually(lambda: not page.evaluate("document.getElementById('history-empty').hidden"))
        self.assertTrue(page.evaluate("document.getElementById('projects-list').hidden"))

    def test_rename_from_the_dashboard(self):
        project_id = self.make_project("Old name")
        page = self.new_page()
        page.goto(self.base + "/dashboard", wait_until="domcontentloaded")
        card = f'.project-card[data-project-id="{project_id}"]'
        self.eventually(lambda: page.locator(card).count() == 1)
        self.click(page, f'{card} button:has-text("Rename")')
        page.fill(f"{card} .rename-input", "A much better name")
        page.locator(f"{card} .rename-input").press("Enter")
        self.eventually(lambda: page.locator(f"{card} .project-name").count() == 1 and
                        page.inner_text(f"{card} .project-name") == "A much better name")
        self.assertEqual(self.project_names(), ["A much better name"])

    def test_rename_can_be_cancelled_and_cannot_be_blank(self):
        project_id = self.make_project("Keep this")
        page = self.new_page()
        page.goto(self.base + "/dashboard", wait_until="domcontentloaded")
        card = f'.project-card[data-project-id="{project_id}"]'
        self.eventually(lambda: page.locator(card).count() == 1)
        self.click(page, f'{card} button:has-text("Rename")')
        page.fill(f"{card} .rename-input", "   ")
        page.locator(f"{card} .rename-input").press("Enter")
        self.eventually(lambda: "Give the project a name" in page.inner_text("#projects-message"))
        page.locator(f"{card} .rename-input").press("Escape")
        self.eventually(lambda: page.inner_text(f"{card} .project-name") == "Keep this")
        self.assertEqual(self.project_names(), ["Keep this"])

    def test_duplicate_from_the_dashboard(self):
        self.make_project("Original")
        page = self.new_page()
        page.goto(self.base + "/dashboard", wait_until="domcontentloaded")
        self.eventually(lambda: page.locator("#projects-list .project-card").count() == 1)
        self.click(page, '#projects-list button:has-text("Duplicate")')
        self.eventually(lambda: page.locator("#projects-list .project-card").count() == 2)
        self.assertEqual(sorted(self.project_names()), ["Original", "Original (copy)"])

    def test_delete_needs_two_clicks(self):
        keep = self.make_project("Keep")
        gone = self.make_project("Delete me")
        page = self.new_page()
        page.goto(self.base + "/dashboard", wait_until="domcontentloaded")
        card = f'.project-card[data-project-id="{gone}"]'
        self.eventually(lambda: page.locator(card).count() == 1)
        self.click(page, f'{card} button:has-text("Delete")')
        self.assertEqual(len(self.project_names()), 2)                               # one click only arms it
        self.assertEqual(page.inner_text(f'{card} [data-armed="1"]'), "Sure?")
        self.click(page, f'{card} [data-armed="1"]')
        self.eventually(lambda: page.locator("#projects-list .project-card").count() == 1)
        self.assertEqual(self.project_names(), ["Keep"])
        self.assertEqual(repo.get_project(self.db, keep)["project"]["name"], "Keep")
        self.eventually(lambda: page.locator("#history-list .history-item").count() == 1)

    def test_deleting_the_last_project_shows_the_empty_state(self):
        self.make_project("Only one")
        page = self.new_page()
        page.goto(self.base + "/dashboard", wait_until="domcontentloaded")
        self.eventually(lambda: page.locator("#projects-list .project-card").count() == 1)
        self.click(page, '#projects-list button:has-text("Delete")')
        self.click(page, '#projects-list [data-armed="1"]')
        self.eventually(lambda: not page.evaluate("document.getElementById('projects-empty').hidden"))

    def test_the_dashboard_explains_a_database_problem_and_recovers(self):
        self.make_project("Visible later")
        self.app.extensions["database"] = Database(DisabledConnector(), enabled=False)
        page = self.new_page()
        page.goto(self.base + "/dashboard", wait_until="domcontentloaded")
        self.eventually(lambda: not page.evaluate("document.getElementById('projects-error').hidden"))
        self.assertIn("turned off", page.inner_text("#projects-error-text"))
        self.eventually(lambda: page.inner_text("#db-text") == "Turned off")
        self.assertIn("DATABASE_ENABLED", page.inner_text("#db-message"))
        self.app.extensions["database"] = self.db
        self.click(page, "#projects-retry")
        self.eventually(lambda: page.locator("#projects-list .project-card").count() == 1)

    def test_names_with_markup_are_shown_as_plain_text(self):
        self.conn.run("INSERT INTO projects (name, category, status) VALUES (?, 'blog', 'generated')",
                      ("<img src=x onerror=alert(1)>Sneaky <b>bold</b>",))
        page = self.new_page()
        page.goto(self.base + "/dashboard", wait_until="domcontentloaded")
        self.eventually(lambda: page.locator("#projects-list .project-card").count() == 1)
        self.assertEqual(page.locator("#projects-list img").count(), 0)
        self.assertEqual(page.locator("#projects-list b").count(), 0)
        self.assertIn("<img src=x", page.inner_text(".project-name"))
        self.assertEqual(self.errors, [])

    def test_the_project_cards_fit_a_phone(self):
        for index in range(3):
            self.make_project("A very long project name " * 4 + str(index))
        page = self.new_page(width=390)
        page.goto(self.base + "/dashboard", wait_until="domcontentloaded")
        self.eventually(lambda: page.locator("#projects-list .project-card").count() == 3)
        self.eventually(lambda: page.locator("#history-list .history-item").count() == 3)
        self.assertTrue(page.evaluate("document.documentElement.scrollWidth <= innerWidth"))


if __name__ == "__main__":
    unittest.main()
