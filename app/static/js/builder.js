/* SiteForge AI builder page: starts a generation job, shows its progress, and displays the result. */
(function () {
  "use strict";

  var form = document.getElementById("generator-form");
  if (!form) { return; }

  var promptEl = document.getElementById("prompt");
  var counter = document.getElementById("prompt-counter");
  var submitButton = document.getElementById("generate-button");
  var panel = document.getElementById("result-panel");
  var statusLine = document.getElementById("form-status");
  var elapsedEl = document.getElementById("elapsed");
  var errorMessage = document.getElementById("error-message");
  var progressLabel = document.getElementById("progress-label");
  var progressBar = document.getElementById("progress-bar");

  var minLength = parseInt(promptEl.getAttribute("data-min"), 10);
  var maxLength = parseInt(promptEl.getAttribute("data-max"), 10);
  var FIELDS = ["prompt", "category", "design_style", "color_scheme"];
  var POLL_MS = 1500;
  var MAX_POLL_FAILURES = 3;

  var startController = null;   // cancels the request that starts a job
  var jobId = null;
  var lastResult = null;
  var pollTimer = null;
  var pollFailures = 0;
  var elapsedTimer = null;

  /* ---------- helpers ---------- */
  function checkedValue(name) {
    var input = form.querySelector('input[name="' + name + '"]:checked');
    return input ? input.value : "";
  }

  function showState(name) {
    ["idle", "loading", "error", "success"].forEach(function (state) {
      var element = panel.querySelector('[data-state="' + state + '"]');
      var visible = state === name;
      element.classList.toggle("hidden", !visible);
      element.classList.toggle("flex", visible);
    });
  }

  function setFieldError(field, message) {
    var element = document.getElementById(field + "-error");
    if (element) { element.textContent = message; }
    if (field === "prompt") { promptEl.setAttribute("aria-invalid", "true"); }
  }

  function clearErrors() {
    FIELDS.forEach(function (field) {
      var element = document.getElementById(field + "-error");
      if (element) { element.textContent = ""; }
    });
    promptEl.removeAttribute("aria-invalid");
    statusLine.textContent = "";
  }

  function updateCounter() {
    var length = promptEl.value.length;
    counter.textContent = length + " / " + maxLength;
    counter.classList.toggle("text-red-700", length > maxLength);
    counter.classList.toggle("font-medium", length > maxLength);
  }

  function setLoading(isLoading) {
    submitButton.disabled = isLoading;
    panel.setAttribute("aria-busy", String(isLoading));
    window.clearInterval(elapsedTimer);
    if (isLoading) {
      var started = Date.now();
      elapsedEl.textContent = "0";
      progressLabel.textContent = "Starting";
      progressBar.value = 0;
      elapsedTimer = window.setInterval(function () {
        elapsedEl.textContent = String(Math.floor((Date.now() - started) / 1000));
      }, 1000);
      showState("loading");
    }
  }

  function stopPolling() {
    window.clearTimeout(pollTimer);
    pollTimer = null;
  }

  function showError(message) {
    errorMessage.textContent = message;   // textContent keeps server text safe
    showState("error");
  }

  function revealPanelOnSmallScreens() {
    if (!window.matchMedia("(max-width: 1279px)").matches) { return; }
    var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    panel.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
  }

  function fail(message) {
    stopPolling();
    setLoading(false);
    jobId = null;
    showError(message);
  }

  /* ---------- result ---------- */
  function showJson(config) {
    // Pictures are long; leave them out of the readable view.
    var text = JSON.stringify(config, function (key, value) {
      return key === "image" && typeof value === "string" && value ? "[picture]" : value;
    }, 2);
    document.getElementById("result-json").textContent = text;
  }

  function showResult(result) {
    lastResult = result;
    document.getElementById("download-status").textContent = "";
    var config = result.config;
    var meta = config.meta;

    document.getElementById("brief-name").textContent = meta.site_name;
    document.getElementById("brief-tagline").textContent = meta.tagline;
    document.getElementById("brief-category").textContent = meta.category;
    document.getElementById("brief-model").textContent = result.model || "";

    var list = document.getElementById("result-sections");
    list.textContent = "";
    config.sections.forEach(function (section) {
      var item = document.createElement("li");
      item.className = "rounded-full bg-white px-3 py-1 text-xs font-medium text-slate-800 ring-1 ring-emerald-200";
      item.textContent = section.type;
      list.appendChild(item);
    });

    var warnings = result.warnings || [];
    var warningsBox = document.getElementById("result-warnings");
    var warningsList = document.getElementById("result-warnings-list");
    warningsList.textContent = "";
    warnings.forEach(function (warning) {
      var item = document.createElement("li");
      item.textContent = warning;
      warningsList.appendChild(item);
    });
    warningsBox.classList.toggle("hidden", warnings.length === 0);

    showJson(config);

    // The preview in Phase 7 listens for this event.
    document.dispatchEvent(new CustomEvent("siteforge:generated", { detail: result }));
    showState("success");
  }

  /* ---------- polling ---------- */
  function schedulePoll() {
    pollTimer = window.setTimeout(poll, POLL_MS);
  }

  function handleSnapshot(snapshot) {
    var progress = snapshot.progress || {};
    if (progress.label) { progressLabel.textContent = progress.label + "..."; }
    if (progress.total) { progressBar.value = Math.round((progress.done / progress.total) * 100); }

    if (snapshot.status === "done") {
      stopPolling();
      setLoading(false);
      jobId = null;
      showResult(snapshot.result);
    } else if (snapshot.status === "failed") {
      fail((snapshot.error && snapshot.error.message) || "Generation failed. Please try again.");
    } else if (snapshot.status === "cancelled") {
      stopPolling();
      setLoading(false);
      jobId = null;
      showState("idle");
      statusLine.textContent = "Generation cancelled.";
    } else {
      schedulePoll();
    }
  }

  function poll() {
    if (!jobId) { return; }
    fetch("/api/generate/" + encodeURIComponent(jobId), { headers: { Accept: "application/json" } })
      .then(function (response) {
        return response.json()
          .catch(function () { return {}; })
          .then(function (data) { return { ok: response.ok, data: data }; });
      })
      .then(function (result) {
        pollFailures = 0;
        if (!result.ok) {
          fail(result.data.message || "The generation was lost. Please try again.");
          return;
        }
        handleSnapshot(result.data);
      })
      .catch(function () {
        pollFailures += 1;
        if (pollFailures >= MAX_POLL_FAILURES) {
          fail("Lost contact with the server. Check that it is running, then try again.");
        } else {
          schedulePoll();
        }
      });
  }

  /* ---------- start ---------- */
  function generate() {
    clearErrors();
    stopPolling();

    if (window.SiteForgeEditor && window.SiteForgeEditor.hasUnsavedChanges() &&
        !window.confirm("Generating a new website replaces the one you have now, including your edits. Continue?")) {
      return;
    }

    var payload = {
      prompt: promptEl.value,
      category: checkedValue("category"),
      design_style: checkedValue("design_style"),
      color_scheme: checkedValue("color_scheme")
    };

    var trimmed = payload.prompt.trim();
    if (trimmed.length < minLength) {
      setFieldError("prompt", "Describe your website in at least " + minLength + " characters.");
      promptEl.focus();
      return;
    }
    if (trimmed.length > maxLength) {
      setFieldError("prompt", "Keep the description under " + maxLength + " characters.");
      promptEl.focus();
      return;
    }

    startController = new AbortController();
    pollFailures = 0;
    setLoading(true);
    revealPanelOnSmallScreens();

    fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(payload),
      signal: startController.signal
    })
      .then(function (response) {
        return response.json()
          .catch(function () { return {}; })
          .then(function (data) { return { ok: response.ok, status: response.status, data: data }; });
      })
      .then(function (result) {
        if (result.ok && result.data.job_id) {
          jobId = result.data.job_id;
          schedulePoll();
          return;
        }

        setLoading(false);
        if (result.status === 400 && result.data.fields) {
          showState("idle");
          var firstInvalid = null;
          Object.keys(result.data.fields).forEach(function (field) {
            setFieldError(field, result.data.fields[field]);
            firstInvalid = firstInvalid || field;
          });
          if (firstInvalid === "prompt") { promptEl.focus(); }
          return;
        }
        showError(result.data.message || "Something went wrong. Please try again.");
      })
      .catch(function (error) {
        setLoading(false);
        if (error && error.name === "AbortError") {
          showState("idle");
          statusLine.textContent = "Generation cancelled.";
          return;
        }
        showError("Could not reach the server. Check that it is running, then try again.");
      });
  }

  function cancel() {
    if (jobId) {
      var id = jobId;
      stopPolling();
      jobId = null;
      setLoading(false);
      showState("idle");
      statusLine.textContent = "Generation cancelled.";
      fetch("/api/generate/" + encodeURIComponent(id) + "/cancel", { method: "POST", headers: { "X-SiteForge-Request": "1" } })
        .catch(function () { /* the job stops on its own at the next step */ });
    } else if (startController) {
      startController.abort();
    }
  }

  /* ---------- download ---------- */
  function slugify(text) {
    var slug = String(text).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
    return slug.slice(0, 50) || "website";
  }

  function currentConfig() {
    var edited = window.SiteForgeEditor && window.SiteForgeEditor.getConfig();
    return edited || (lastResult && lastResult.config);
  }

  function downloadWebsite(button, status) {
    var config = currentConfig();
    if (!config) { return; }
    button.disabled = true;
    status.textContent = "Building your website file...";

    fetch("/api/render", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ config: config, files: false })
    })
      .then(function (response) {
        return response.json()
          .catch(function () { return {}; })
          .then(function (data) { return { ok: response.ok, data: data }; });
      })
      .then(function (result) {
        if (!result.ok) { throw new Error(result.data.message || "The website could not be built."); }
        var blob = new Blob([result.data.html], { type: "text/html" });
        var url = URL.createObjectURL(blob);
        var link = document.createElement("a");
        link.href = url;
        link.download = slugify(config.meta.site_name) + ".html";
        document.body.appendChild(link);
        link.click();
        link.remove();
        window.setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
        status.textContent = "Downloaded " + link.download;
        if (window.SiteForgeEditor) { window.SiteForgeEditor.markExported(); }
      })
      .catch(function (error) {
        status.textContent = error.message || "The website could not be built.";
      })
      .then(function () { button.disabled = false; });
  }

  /* ---------- events ---------- */
  form.addEventListener("submit", function (event) {
    event.preventDefault();
    generate();
  });

  promptEl.addEventListener("input", updateCounter);

  form.querySelectorAll("[data-example]").forEach(function (button) {
    button.addEventListener("click", function () {
      promptEl.value = button.getAttribute("data-example");
      var radio = form.querySelector('input[name="category"][value="' + button.getAttribute("data-category") + '"]');
      if (radio) { radio.checked = true; }
      updateCounter();
      clearErrors();
      promptEl.focus();
    });
  });

  document.addEventListener("siteforge:configchanged", function (event) {
    if (event.detail && event.detail.config) {
      showJson(event.detail.config);
      document.getElementById("brief-name").textContent = event.detail.config.meta.site_name;
      document.getElementById("brief-tagline").textContent = event.detail.config.meta.tagline;
    }
  });

  panel.querySelector('[data-action="cancel"]').addEventListener("click", cancel);
  panel.querySelector('[data-action="retry"]').addEventListener("click", generate);
  document.getElementById("download-site").addEventListener("click", function () {
    downloadWebsite(document.getElementById("download-site"), document.getElementById("download-status"));
  });
  window.SiteForgeBuilder = { download: downloadWebsite };

  updateCounter();
  showState("idle");
})();
