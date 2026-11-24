/* SiteForge AI website preview.
 *
 * Shows a website configuration inside a sandboxed frame. The frame has
 * sandbox="allow-scripts" and no "allow-same-origin", so the generated page can
 * run its own menu script but cannot read or change anything in SiteForge.
 * The page is only ever given to the frame as text (srcdoc), never inserted
 * into this document.
 *
 * Other scripts can use:  SiteForgePreview.show(config)   SiteForgePreview.refresh()
 *                         SiteForgePreview.setDevice("desktop" | "tablet" | "mobile")
 */
(function () {
  "use strict";

  var section = document.getElementById("preview-section");
  if (!section) { return; }

  var card = document.getElementById("preview-card");
  var stage = document.getElementById("preview-stage");
  var viewport = document.getElementById("preview-viewport");
  var frame = document.getElementById("preview-frame");
  var busy = document.getElementById("preview-busy");
  var errorBox = document.getElementById("preview-error");
  var errorMessage = document.getElementById("preview-error-message");
  var info = document.getElementById("preview-info");
  var heading = document.getElementById("preview-title");
  var refreshButton = document.getElementById("preview-refresh");
  var fullscreenButton = document.getElementById("preview-fullscreen");
  var deviceButtons = Array.prototype.slice.call(section.querySelectorAll("[data-device]"))
    .filter(function (element) { return element.tagName === "BUTTON"; });

  // width = the screen width the website is laid out for; height = a typical screen height.
  var DEVICES = {
    desktop: { label: "Desktop", width: 1280, height: null },
    tablet: { label: "Tablet", width: 768, height: 1024 },
    mobile: { label: "Mobile", width: 375, height: 812 }
  };

  var currentDevice = "desktop";
  var currentConfig = null;
  var renderToken = 0;
  var expanded = false;
  var nativeFullscreen = !!(card.requestFullscreen && document.fullscreenEnabled);

  /* ---------- sizing ---------- */
  function stageInnerSize() {
    var style = window.getComputedStyle(stage);
    var padX = parseFloat(style.paddingLeft) + parseFloat(style.paddingRight);
    var padY = parseFloat(style.paddingTop) + parseFloat(style.paddingBottom);
    return {
      width: Math.max(0, stage.clientWidth - padX),
      height: Math.max(0, stage.clientHeight - padY)
    };
  }

  function layout() {
    var device = DEVICES[currentDevice];
    var inner = stageInnerSize();
    if (!inner.width || !inner.height) { return; }

    // Shrink the whole page to fit when the screen is narrower than the device,
    // so the website keeps the layout of the chosen device width.
    var scale = Math.min(1, inner.width / device.width);
    var viewportHeight = device.height ? Math.min(inner.height, device.height * scale) : inner.height;

    viewport.style.width = Math.round(device.width * scale) + "px";
    viewport.style.height = Math.round(viewportHeight) + "px";
    frame.style.width = device.width + "px";
    frame.style.height = Math.round(viewportHeight / scale) + "px";
    frame.style.transform = "scale(" + scale + ")";
    viewport.setAttribute("data-device", currentDevice);

    info.textContent = device.label + ", " + device.width + " px wide" +
      (scale < 1 ? ", shown at " + Math.round(scale * 100) + "%" : "");
  }

  function setDevice(name) {
    if (!DEVICES[name]) { return; }
    currentDevice = name;
    deviceButtons.forEach(function (button) {
      button.setAttribute("aria-pressed", String(button.getAttribute("data-device") === name));
    });
    layout();
  }

  /* ---------- rendering ---------- */
  function setBusy(isBusy) {
    busy.classList.toggle("is-hidden", !isBusy);
  }

  function showError(message) {
    errorMessage.textContent = message;     // text only
    errorBox.classList.remove("is-hidden");
    setBusy(false);
  }

  function render(reveal) {
    if (!currentConfig) { return; }
    var token = ++renderToken;
    errorBox.classList.add("is-hidden");
    setBusy(true);

    fetch("/api/render", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ config: currentConfig, preview: true })
    })
      .then(function (response) {
        return response.json()
          .catch(function () { return {}; })
          .then(function (data) { return { ok: response.ok, data: data }; });
      })
      .then(function (result) {
        if (token !== renderToken) { return; }          // a newer render replaced this one
        if (!result.ok || typeof result.data.html !== "string") {
          throw new Error(result.data.message || "The preview could not be built.");
        }
        frame.addEventListener("load", function onLoad() {
          frame.removeEventListener("load", onLoad);
          if (token !== renderToken) { return; }
          setBusy(false);
          layout();
          if (reveal) { revealSection(); }
        });
        // The trailing comment makes every refresh a new document, so the frame always reloads.
        frame.srcdoc = result.data.html + "\n<!-- preview " + token + " -->";
      })
      .catch(function (error) {
        if (token !== renderToken) { return; }
        showError(error.message || "The preview could not be built.");
      });
  }

  function show(config, options) {
    currentConfig = config;
    section.classList.remove("hidden");
    layout();
    render(Boolean(options && options.reveal));
  }

  function revealSection() {
    var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    section.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
    heading.focus({ preventScroll: true });
  }

  /* ---------- full screen ---------- */
  function updateFullscreenButton() {
    var isFull = expanded || document.fullscreenElement === card;
    fullscreenButton.setAttribute("aria-pressed", String(isFull));
    fullscreenButton.querySelector("span").textContent = isFull ? "Exit full screen" : "Full screen";
    fullscreenButton.querySelector("i").className = isFull ? "fa-solid fa-compress" : "fa-solid fa-expand";
    layout();
  }

  function setExpanded(on) {
    expanded = on;
    card.classList.toggle("is-expanded", on);
    document.documentElement.style.overflow = on ? "hidden" : "";
    updateFullscreenButton();
  }

  function toggleFullscreen() {
    var isFull = expanded || document.fullscreenElement === card;
    if (isFull) {
      if (document.fullscreenElement === card) { document.exitFullscreen(); }
      if (expanded) { setExpanded(false); }
      return;
    }
    if (nativeFullscreen) {
      // If the browser refuses, fall back to filling the window.
      card.requestFullscreen().catch(function () { setExpanded(true); });
    } else {
      setExpanded(true);
    }
  }

  /* ---------- events ---------- */
  deviceButtons.forEach(function (button) {
    button.addEventListener("click", function () { setDevice(button.getAttribute("data-device")); });
  });
  refreshButton.addEventListener("click", function () { render(false); });
  document.getElementById("preview-retry").addEventListener("click", function () { render(false); });
  fullscreenButton.addEventListener("click", toggleFullscreen);

  document.addEventListener("fullscreenchange", updateFullscreenButton);
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && expanded) {
      setExpanded(false);
      fullscreenButton.focus();
    }
  });

  if ("ResizeObserver" in window) {
    new ResizeObserver(layout).observe(stage);
  } else {
    window.addEventListener("resize", layout);
  }

  document.addEventListener("siteforge:generated", function (event) {
    var result = event.detail;
    if (result && result.config) { show(result.config, { reveal: true }); }
  });

  window.SiteForgePreview = { show: show, refresh: function () { render(false); }, setDevice: setDevice };
})();
