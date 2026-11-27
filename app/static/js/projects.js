/* SiteForge AI builder: saving a website as a project, and opening a saved project.
 *
 * - A new website is saved as a new project.
 * - A saved project that is edited is updated in place.
 * - If a website is generated again while a project is open, saving stores it
 *   as the next version of that project.
 * Opening works from the address: /builder?project=5  or  /builder?project=5&version=2
 */
(function () {
  "use strict";

  var bar = document.getElementById("project-bar");
  if (!bar) { return; }

  function byId(id) { return document.getElementById(id); }

  var nameInput = byId("project-name");
  var saveButton = byId("project-save");
  var downloadButton = byId("project-download");
  var statusLine = byId("project-status");
  var errorLine = byId("project-error");
  var openMessage = byId("project-open-message");

  var state = { project: null, newVersion: false, model: "", saving: false };

  /* ---------- helpers ---------- */
  function setStatus(text) { statusLine.textContent = text || ""; }
  function setError(text) { errorLine.textContent = text || ""; }

  function api(method, url, body) {
    var options = { method: method, headers: { Accept: "application/json", "X-SiteForge-Request": "1" } };
    if (body !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }
    return fetch(url, options).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (data) {
        if (!response.ok) {
          var error = new Error(data.message || "Something went wrong. Please try again.");
          error.status = response.status;
          error.problems = data.problems;
          throw error;
        }
        return data;
      });
    }, function () {
      throw new Error("Could not reach the server. Check that it is running.");
    });
  }

  function problemText(error) {
    if (!error.problems || !error.problems.length) { return error.message; }
    return error.message + " (" + error.problems.slice(0, 3).join("; ") + ")";
  }

  function clock() {
    return new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  }

  function positiveInt(text) {
    return /^\d{1,15}$/.test(text || "") && parseInt(text, 10) > 0 ? parseInt(text, 10) : null;
  }

  /* ---------- saving ---------- */
  function save() {
    if (state.saving) { return; }
    var config = window.SiteForgeEditor && window.SiteForgeEditor.getConfig();
    if (!config) { setError("Generate or open a website first."); return; }

    var name = nameInput.value.trim() || config.meta.site_name;
    var request;
    if (state.project) {
      request = api("PUT", "/api/projects/" + state.project.id, {
        config: config, name: name, version: state.project.version,
        new_version: state.newVersion, model: state.model
      });
    } else {
      request = api("POST", "/api/projects", { config: config, name: name, model: state.model });
    }

    state.saving = true;
    saveButton.disabled = true;
    setError("");
    setStatus("Saving...");

    request.then(function (data) {
      state.project = { id: data.project.id, name: data.project.name, version: data.version.version };
      state.newVersion = false;
      nameInput.value = data.project.name;
      window.SiteForgeEditor.markExported();
      window.history.replaceState(null, "", "/builder?project=" + encodeURIComponent(data.project.id));
      document.title = data.project.name + " | SiteForge AI";
      setStatus("Saved at " + clock() + (data.project.version_count > 1 ? " (version " + data.version.version + ")" : "") + ".");
    }).catch(function (error) {
      if (error.status === 404) {
        state.project = null;
        setError("This project no longer exists, so nothing was saved. Press Save project again to save it as a new project.");
      } else {
        setError(problemText(error));
      }
      setStatus("Not saved.");
    }).then(function () {
      state.saving = false;
      saveButton.disabled = false;
    });
  }

  /* ---------- opening ---------- */
  function fillForm(meta) {
    var prompt = byId("prompt");
    prompt.value = meta.prompt || "";
    prompt.dispatchEvent(new Event("input", { bubbles: true }));
    [["category", meta.category], ["design_style", meta.design_style], ["color_scheme", meta.color_scheme]].forEach(function (pair) {
      var radio = document.querySelector('input[name="' + pair[0] + '"][value="' + pair[1] + '"]');
      if (radio) { radio.checked = true; }
    });
  }

  function openProject(id, version) {
    openMessage.textContent = "";
    var url = "/api/projects/" + id + (version ? "?version=" + version : "");
    return api("GET", url).then(function (data) {
      state.project = { id: data.project.id, name: data.project.name, version: data.version.version };
      state.newVersion = false;
      state.model = data.version.model_name || "";
      nameInput.value = data.project.name;
      fillForm(data.config.meta);
      document.title = data.project.name + " | SiteForge AI";
      var heading = document.querySelector("h1");
      if (heading) { heading.textContent = "Edit project"; }

      window.SiteForgePreview.show(data.config, { reveal: true });
      return window.SiteForgeEditor.load(data.config).then(function () {
        window.SiteForgeEditor.markExported();
        setStatus("Opened version " + data.version.version + " of " + data.project.name + ".");
      });
    }).catch(function (error) {
      openMessage.textContent = error.status === 404
        ? "That project could not be found. It may have been deleted."
        : error.message;
    });
  }

  /* ---------- events ---------- */
  saveButton.addEventListener("click", save);

  downloadButton.addEventListener("click", function () {
    if (window.SiteForgeBuilder) { window.SiteForgeBuilder.download(downloadButton, statusLine); }
  });

  nameInput.addEventListener("input", function () { setStatus("Unsaved changes."); });

  document.addEventListener("siteforge:generated", function (event) {
    var result = event.detail || {};
    state.model = result.model || "";
    if (state.project) {
      state.newVersion = true;
      setStatus("Generated again. Saving stores this as a new version of " + state.project.name + ".");
    } else {
      nameInput.value = result.config ? result.config.meta.site_name : "";
      setStatus("Not saved yet.");
    }
    setError("");
  });

  document.addEventListener("siteforge:configchanged", function () {
    if (!state.saving) { setStatus("Unsaved changes."); }
  });

  var params = new URLSearchParams(window.location.search);
  var projectId = positiveInt(params.get("project"));
  if (projectId) { openProject(projectId, positiveInt(params.get("version"))); }
})();
