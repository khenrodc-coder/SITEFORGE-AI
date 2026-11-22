/* SiteForge AI builder page: form handling, loading and error states. */
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

  var minLength = parseInt(promptEl.getAttribute("data-min"), 10);
  var maxLength = parseInt(promptEl.getAttribute("data-max"), 10);
  var FIELDS = ["prompt", "category", "design_style", "color_scheme"];

  var controller = null;
  var timerId = null;

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
    window.clearInterval(timerId);
    if (isLoading) {
      var started = Date.now();
      elapsedEl.textContent = "0";
      timerId = window.setInterval(function () {
        elapsedEl.textContent = String(Math.floor((Date.now() - started) / 1000));
      }, 1000);
      showState("loading");
    }
  }

  function showError(message) {
    errorMessage.textContent = message;   // textContent keeps server text safe
    showState("error");
  }

  function showBrief(data) {
    var brief = data.brief || {};
    document.getElementById("brief-name").textContent = brief.site_name || "";
    document.getElementById("brief-tagline").textContent = brief.tagline || "";
    document.getElementById("brief-category").textContent = brief.category_name || "";
    document.getElementById("brief-model").textContent = data.model || "";
    showState("success");
  }

  function revealPanelOnSmallScreens() {
    if (!window.matchMedia("(max-width: 1279px)").matches) { return; }
    var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    panel.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
  }

  /* ---------- generation ---------- */
  function generate() {
    clearErrors();

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

    controller = new AbortController();
    setLoading(true);
    revealPanelOnSmallScreens();

    fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(payload),
      signal: controller.signal
    })
      .then(function (response) {
        return response.json()
          .catch(function () { return {}; })
          .then(function (data) { return { ok: response.ok, status: response.status, data: data }; });
      })
      .then(function (result) {
        setLoading(false);

        if (result.ok) {
          // The preview in Phase 7 listens for this event and displays the website.
          document.dispatchEvent(new CustomEvent("siteforge:generated", { detail: result.data }));
          showBrief(result.data);
          return;
        }

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

  panel.querySelector('[data-action="cancel"]').addEventListener("click", function () {
    if (controller) { controller.abort(); }
  });
  panel.querySelector('[data-action="retry"]').addEventListener("click", generate);

  updateCounter();
  showState("idle");
})();
