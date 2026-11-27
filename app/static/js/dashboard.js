/* SiteForge AI dashboard: saved projects, generation history, and the database status card.
 * Everything from the server is shown with textContent, never as HTML. */
(function () {
  "use strict";

  var list = document.getElementById("projects-list");
  if (!list) { return; }

  function byId(id) { return document.getElementById(id); }

  var HEX_COLOR = /^#[0-9a-fA-F]{6}$/;
  var categoryNames = {};
  try {
    JSON.parse(byId("category-data").textContent).forEach(function (category) {
      categoryNames[category.id] = category.name;
    });
  } catch (error) { /* names fall back to the plain id */ }

  var message = byId("projects-message");
  var announcer = byId("projects-status");

  /* ---------- helpers ---------- */
  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (name) {
      var value = attrs[name];
      if (value === null || value === undefined || value === false) { return; }
      if (name === "class") { node.className = value; }
      else if (name === "text") { node.textContent = value; }
      else if (value === true) { node.setAttribute(name, ""); }
      else { node.setAttribute(name, String(value)); }
    });
    (children || []).forEach(function (child) {
      if (child) { node.appendChild(typeof child === "string" ? document.createTextNode(child) : child); }
    });
    return node;
  }

  function icon(name) { return el("i", { class: "fa-solid fa-" + name, "aria-hidden": "true" }); }

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
          throw error;
        }
        return data;
      });
    }, function () {
      throw new Error("Could not reach the server. Check that it is running.");
    });
  }

  function formatDate(iso) {
    var date = new Date(iso);
    if (!iso || isNaN(date.getTime())) { return ""; }
    return date.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
  }

  function plural(count, word) { return count + " " + word + (count === 1 ? "" : "s"); }

  function showOnly(prefix, which) {
    ["loading", "error", "empty", "list"].forEach(function (name) {
      var node = byId(prefix + "-" + name);
      if (node) { node.hidden = name !== which; }
    });
  }

  function announce(text) {
    message.textContent = "";
    announcer.textContent = "";
    window.setTimeout(function () { announcer.textContent = text; }, 30);
  }

  function showMessage(text) {
    message.textContent = text;
    message.hidden = !text;
  }

  /* ---------- projects ---------- */
  function builderLink(id, version) {
    return "/builder?project=" + encodeURIComponent(id) + (version ? "&version=" + encodeURIComponent(version) : "");
  }

  function confirmButton(label, confirmLabel, action) {
    var button = el("button", { type: "button", class: "tool-btn tool-btn--sm tool-btn--danger" }, [icon("trash-can"), el("span", { text: label })]);
    var timer = null;
    function reset() {
      window.clearTimeout(timer);
      button.className = "tool-btn tool-btn--sm tool-btn--danger";
      button.querySelector("span").textContent = label;
      button.removeAttribute("data-armed");
    }
    button.addEventListener("click", function () {
      if (button.getAttribute("data-armed") === "1") { reset(); action(button); return; }
      button.setAttribute("data-armed", "1");
      button.className = "tool-btn tool-btn--sm tool-btn--confirm";
      button.querySelector("span").textContent = confirmLabel;
      timer = window.setTimeout(reset, 4000);
    });
    return button;
  }

  function startRename(card, project, nameHolder) {
    var original = nameHolder.firstChild;
    var input = el("input", { type: "text", maxlength: 150, "aria-label": "Project name", class: "rename-input" });
    input.value = project.name;
    var save = el("button", { type: "button", class: "tool-btn tool-btn--sm tool-btn--primary" }, [el("span", { text: "Save" })]);
    var cancel = el("button", { type: "button", class: "tool-btn tool-btn--sm" }, [el("span", { text: "Cancel" })]);
    var form = el("div", { class: "rename-row" }, [input, save, cancel]);

    function close() { nameHolder.textContent = ""; nameHolder.appendChild(original); }
    function submit() {
      var value = input.value.trim();
      if (!value) { showMessage("Give the project a name."); input.focus(); return; }
      save.disabled = true;
      api("PATCH", "/api/projects/" + project.id, { name: value }).then(function (data) {
        project.name = data.project.name;
        original.textContent = project.name;
        close();
        announce("Renamed to " + project.name + ".");
        showMessage("");
        loadProjects(false);
      }).catch(function (error) {
        save.disabled = false;
        showMessage(error.message);
      });
    }

    save.addEventListener("click", submit);
    cancel.addEventListener("click", close);
    input.addEventListener("keydown", function (event) {
      if (event.key === "Enter") { event.preventDefault(); submit(); }
      if (event.key === "Escape") { close(); }
    });
    nameHolder.textContent = "";
    nameHolder.appendChild(form);
    input.focus();
    input.select();
  }

  function projectCard(project) {
    var color = HEX_COLOR.test(project.primary_color || "") ? project.primary_color : "#94a3b8";
    var link = el("a", { href: builderLink(project.id), class: "project-name", text: project.name });
    var nameHolder = el("h3", { class: "project-title" }, [link]);

    var category = categoryNames[project.category] || project.category || "";
    var details = [category, plural(project.version_count || 1, "version")].filter(Boolean).join(" \u00b7 ");

    var openLink = el("a", { href: builderLink(project.id), class: "tool-btn tool-btn--sm" }, [icon("pen-to-square"), el("span", { text: "Open" })]);
    var renameButton = el("button", { type: "button", class: "tool-btn tool-btn--sm" }, [icon("i-cursor"), el("span", { text: "Rename" })]);
    var duplicateButton = el("button", { type: "button", class: "tool-btn tool-btn--sm" }, [icon("clone"), el("span", { text: "Duplicate" })]);

    var card = el("li", { class: "project-card", "data-project-id": project.id }, [
      el("span", { class: "project-accent", style: "background-color:" + color, "aria-hidden": "true" }),
      el("div", { class: "project-body" }, [
        nameHolder,
        el("p", { class: "project-meta", text: details }),
        el("p", { class: "project-meta", text: "Updated " + formatDate(project.updated_at) })
      ]),
      el("div", { class: "project-actions" }, [openLink, renameButton, duplicateButton])
    ]);

    renameButton.addEventListener("click", function () { startRename(card, project, nameHolder); });

    duplicateButton.addEventListener("click", function () {
      duplicateButton.disabled = true;
      api("POST", "/api/projects/" + project.id + "/duplicate").then(function (data) {
        announce("Duplicated as " + data.project.name + ".");
        showMessage("");
        loadProjects(false);
        loadHistory();
      }).catch(function (error) {
        duplicateButton.disabled = false;
        showMessage(error.message);
      });
    });

    var remove = confirmButton("Delete", "Sure?", function () {
      remove.disabled = true;
      api("DELETE", "/api/projects/" + project.id).then(function () {
        announce("Deleted " + project.name + ".");
        showMessage("");
        loadProjects(false);
        loadHistory();
      }).catch(function (error) {
        remove.disabled = false;
        showMessage(error.message);
      });
    });
    card.querySelector(".project-actions").appendChild(remove);
    return card;
  }

  function loadProjects(showSpinner) {
    if (showSpinner !== false) { showOnly("projects", "loading"); }
    return api("GET", "/api/projects").then(function (data) {
      list.textContent = "";
      data.projects.forEach(function (project) { list.appendChild(projectCard(project)); });
      showOnly("projects", data.projects.length ? "list" : "empty");
    }).catch(function (error) {
      byId("projects-error-text").textContent = error.message;
      showOnly("projects", "error");
    });
  }

  /* ---------- history ---------- */
  function historyItem(entry) {
    var label = entry.project_name + " \u00b7 version " + entry.version;
    return el("li", { class: "history-item" }, [
      el("div", { class: "history-main" }, [
        el("p", { class: "history-title", text: label }),
        el("p", { class: "history-prompt", text: entry.prompt || "" }),
        el("p", { class: "project-meta", text: [formatDate(entry.created_at), entry.model_name].filter(Boolean).join(" \u00b7 ") })
      ]),
      el("a", { href: builderLink(entry.project_id, entry.version), class: "tool-btn tool-btn--sm",
        "aria-label": "Open " + label }, [icon("arrow-up-right-from-square"), el("span", { text: "Open" })])
    ]);
  }

  function loadHistory() {
    var historyList = byId("history-list");
    return api("GET", "/api/history").then(function (data) {
      historyList.textContent = "";
      data.history.forEach(function (entry) { historyList.appendChild(historyItem(entry)); });
      showOnly("history", data.history.length ? "list" : "empty");
    }).catch(function (error) {
      byId("history-error-text").textContent = error.message;
      showOnly("history", "error");
    });
  }

  /* ---------- database status ---------- */
  function checkDatabase() {
    var badge = byId("db-badge");
    function setBadge(kind, label, iconName) {
      badge.className = "status-badge status-" + kind;
      badge.querySelector("i").className = "fa-solid " + iconName;
      byId("db-text").textContent = label;
    }
    setBadge("checking", "Checking...", "fa-circle-notch fa-spin");
    return api("GET", "/api/db/status").then(function (data) {
      byId("db-message").textContent = data.message;
      if (data.connected) { setBadge("ok", "Connected", "fa-circle-check"); }
      else if (!data.enabled) { setBadge("error", "Turned off", "fa-circle-xmark"); }
      else { setBadge("error", "Not ready", "fa-circle-xmark"); }
    }).catch(function (error) {
      byId("db-message").textContent = error.message;
      setBadge("error", "Unreachable", "fa-circle-xmark");
    });
  }

  /* ---------- start ---------- */
  byId("projects-retry").addEventListener("click", function () { loadProjects(true); });
  byId("db-refresh").addEventListener("click", function () {
    checkDatabase().then(function () { loadProjects(true); loadHistory(); });
  });

  loadProjects(true);
  loadHistory();
  checkDatabase();
})();
