/* SiteForge AI front-end script. Each feature below only runs if its elements are on the page. */
(function () {
  "use strict";

  /* ---------- Server status (dashboard) ---------- */
  function initHealthCheck() {
    var badge = document.getElementById("status-badge");
    if (!badge) { return; }

    var text = document.getElementById("status-text");
    var refresh = document.getElementById("status-refresh");

    function setBadge(kind, label, icon) {
      badge.className = "status-badge status-" + kind;
      badge.querySelector("i").className = "fa-solid " + icon;
      text.textContent = label;
    }

    function setField(id, value) {
      document.getElementById(id).textContent = value;   // textContent keeps output safe
    }

    function checkHealth() {
      setBadge("checking", "Checking...", "fa-circle-notch fa-spin");
      fetch("/api/health", { headers: { Accept: "application/json" } })
        .then(function (response) {
          if (!response.ok) { throw new Error("HTTP " + response.status); }
          return response.json();
        })
        .then(function (data) {
          setBadge("ok", "Online", "fa-circle-check");
          setField("status-app", data.app);
          setField("status-version", data.version);
          setField("status-export", data.checks.generated_websites_writable ? "Yes" : "No");
        })
        .catch(function () {
          setBadge("error", "Unreachable", "fa-circle-xmark");
        });
    }

    if (refresh) { refresh.addEventListener("click", checkHealth); }
    checkHealth();
  }

  /* ---------- Landing page mobile menu ---------- */
  function initSiteMenu() {
    var toggle = document.querySelector("[data-menu-toggle]");
    if (!toggle) { return; }
    var menu = document.getElementById(toggle.getAttribute("data-menu-toggle"));
    if (!menu) { return; }

    function setOpen(open) {
      menu.classList.toggle("hidden", !open);
      toggle.setAttribute("aria-expanded", String(open));
    }

    toggle.addEventListener("click", function () {
      setOpen(toggle.getAttribute("aria-expanded") !== "true");
    });
    menu.addEventListener("click", function (event) {
      if (event.target.closest("a")) { setOpen(false); }
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && toggle.getAttribute("aria-expanded") === "true") {
        setOpen(false);
        toggle.focus();
      }
    });
  }

  /* ---------- Dashboard sidebar drawer (mobile) ---------- */
  function initSidebar() {
    var sidebar = document.getElementById("app-sidebar");
    var overlay = document.getElementById("sidebar-overlay");
    var toggle = document.querySelector("[data-sidebar-toggle]");
    if (!sidebar || !overlay || !toggle) { return; }

    function setOpen(open) {
      sidebar.classList.toggle("is-open", open);
      overlay.classList.toggle("hidden", !open);
      toggle.setAttribute("aria-expanded", String(open));
      if (open) {
        var first = sidebar.querySelector("a, button");
        if (first) { first.focus(); }
      }
    }

    toggle.addEventListener("click", function () { setOpen(true); });

    document.querySelectorAll("[data-sidebar-close]").forEach(function (element) {
      element.addEventListener("click", function () {
        setOpen(false);
        toggle.focus();
      });
    });

    sidebar.addEventListener("click", function (event) {
      if (event.target.closest("nav a")) { setOpen(false); }
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && sidebar.classList.contains("is-open")) {
        setOpen(false);
        toggle.focus();
      }
    });

    window.matchMedia("(min-width: 1024px)").addEventListener("change", function (event) {
      if (event.matches) { setOpen(false); }
    });
  }

  /* ---------- AI engine status (dashboard) ---------- */
  function initAiStatus() {
    var badge = document.getElementById("ai-badge");
    if (!badge) { return; }

    var text = document.getElementById("ai-text");
    var refresh = document.getElementById("ai-refresh");

    function setBadge(kind, label, icon) {
      badge.className = "status-badge status-" + kind;
      badge.querySelector("i").className = "fa-solid " + icon;
      text.textContent = label;
    }

    function check() {
      setBadge("checking", "Checking...", "fa-circle-notch fa-spin");
      fetch("/api/ai/status", { headers: { Accept: "application/json" } })
        .then(function (response) {
          if (!response.ok) { throw new Error("HTTP " + response.status); }
          return response.json();
        })
        .then(function (data) {
          document.getElementById("ai-model").textContent = data.model || "-";
          document.getElementById("ai-message").textContent = data.message || "-";
          if (data.reachable && data.model_installed) {
            setBadge("ok", "Ready", "fa-circle-check");
          } else if (data.reachable) {
            setBadge("error", "Model missing", "fa-circle-xmark");
          } else {
            setBadge("error", "Ollama offline", "fa-circle-xmark");
          }
        })
        .catch(function () {
          setBadge("error", "Unreachable", "fa-circle-xmark");
          document.getElementById("ai-message").textContent = "Could not check the AI engine.";
        });
    }

    if (refresh) { refresh.addEventListener("click", check); }
    check();
  }

  initHealthCheck();
  initAiStatus();
  initSiteMenu();
  initSidebar();
})();
