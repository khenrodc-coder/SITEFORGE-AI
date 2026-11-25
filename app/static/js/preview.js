/* SiteForge AI website preview.
 *
 * Shows a website configuration inside a sandboxed frame. The frame has
 * sandbox="allow-scripts" and no "allow-same-origin", so the generated page can
 * run its own menu script but cannot read or change anything in SiteForge.
 * The page is only ever given to the frame as text (srcdoc), never inserted
 * into this document.
 *
 * When the preview is rebuilt (for example after an edit) the new version is
 * loaded in a hidden second frame, scrolled to the same place, and then swapped
 * in, so the preview neither flashes nor jumps to the top. The only messages
 * exchanged with the frame are small numbers (the scroll position).
 *
 * Other scripts can use:
 *   SiteForgePreview.show(config, { quiet: true })   rebuild without a loading screen
 *   SiteForgePreview.refresh()                       rebuild from the last configuration
 *   SiteForgePreview.setDevice("desktop" | "tablet" | "mobile")
 * and can listen for the events  siteforge:rendered  and  siteforge:previewerror.
 */
(function () {
  "use strict";

  var section = document.getElementById("preview-section");
  if (!section) { return; }

  var card = document.getElementById("preview-card");
  var stage = document.getElementById("preview-stage");
  var viewport = document.getElementById("preview-viewport");
  var busy = document.getElementById("preview-busy");
  var errorBox = document.getElementById("preview-error");
  var errorMessage = document.getElementById("preview-error-message");
  var info = document.getElementById("preview-info");
  var heading = document.getElementById("preview-title");
  var refreshButton = document.getElementById("preview-refresh");
  var fullscreenButton = document.getElementById("preview-fullscreen");
  var deviceButtons = Array.prototype.slice.call(section.querySelectorAll("[data-device]"))
    .filter(function (element) { return element.tagName === "BUTTON"; });

  var frame = document.getElementById("preview-frame");   // the frame people currently see
  var pendingFrame = null;                                  // the next version, loading out of sight

  // width = the screen width the website is laid out for; height = a typical screen height.
  var DEVICES = {
    desktop: { label: "Desktop", width: 1280, height: null },
    tablet: { label: "Tablet", width: 768, height: 1024 },
    mobile: { label: "Mobile", width: 375, height: 812 }
  };

  var currentDevice = "desktop";
  var currentConfig = null;
  var renderToken = 0;
  var hasContent = false;
  var lastScrollY = 0;
  var swapTimer = null;
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

  var lastSize = null;

  function applySize(target) {
    if (!lastSize || !target) { return; }
    target.style.width = lastSize.frameWidth + "px";
    target.style.height = lastSize.frameHeight + "px";
    target.style.transform = "scale(" + lastSize.scale + ")";
  }

  function layout() {
    var device = DEVICES[currentDevice];
    var inner = stageInnerSize();
    if (!inner.width || !inner.height) { return; }

    // Shrink the whole page to fit when the screen is narrower than the device,
    // so the website keeps the layout of the chosen device width.
    var scale = Math.min(1, inner.width / device.width);
    var viewportHeight = device.height ? Math.min(inner.height, device.height * scale) : inner.height;

    lastSize = { scale: scale, frameWidth: device.width, frameHeight: Math.round(viewportHeight / scale) };
    viewport.style.width = Math.round(device.width * scale) + "px";
    viewport.style.height = Math.round(viewportHeight) + "px";
    viewport.setAttribute("data-device", currentDevice);
    applySize(frame);
    applySize(pendingFrame);

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

  /* ---------- frames ---------- */
  function createFrame() {
    var created = document.createElement("iframe");
    created.setAttribute("sandbox", "allow-scripts");          // set before anything is loaded
    created.setAttribute("referrerpolicy", "no-referrer");
    created.setAttribute("title", "Website preview");
    created.className = "preview-frame";
    created.style.visibility = "hidden";
    return created;
  }

  function discardPending() {
    window.clearTimeout(swapTimer);
    if (pendingFrame) {
      pendingFrame.remove();
      pendingFrame = null;
    }
  }

  function setBusy(isBusy) {
    busy.classList.toggle("is-hidden", !isBusy);
  }

  function revealSection() {
    var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    section.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
    heading.focus({ preventScroll: true });
  }

  function swapTo(next) {
    if (next !== pendingFrame) { return; }
    window.clearTimeout(swapTimer);
    var reveal = next.revealWhenReady;
    var old = frame;
    old.removeAttribute("id");
    next.id = "preview-frame";
    next.style.visibility = "visible";
    old.remove();
    frame = next;
    pendingFrame = null;
    hasContent = true;
    setBusy(false);
    layout();
    document.dispatchEvent(new CustomEvent("siteforge:rendered"));
    if (reveal) { revealSection(); }
  }

  window.addEventListener("message", function (event) {
    var data = event.data;
    if (!data || typeof data.siteforge !== "string") { return; }

    if (data.siteforge === "scroll" && frame && event.source === frame.contentWindow) {
      if (typeof data.y === "number" && isFinite(data.y)) { lastScrollY = Math.max(0, data.y); }
      return;
    }
    if (!pendingFrame || event.source !== pendingFrame.contentWindow) { return; }

    if (data.siteforge === "ready") {
      if (hasContent && lastScrollY > 0) {
        pendingFrame.contentWindow.postMessage({ siteforge: "restore", y: lastScrollY }, "*");
      } else {
        swapTo(pendingFrame);
      }
    } else if (data.siteforge === "restored") {
      swapTo(pendingFrame);
    }
  });

  /* ---------- rendering ---------- */
  function reportFailure(message, problems, quiet) {
    if (!(quiet && hasContent)) {
      // Nothing to fall back on: show the error on the preview itself.
      errorMessage.textContent = message;     // text only
      errorBox.classList.remove("is-hidden");
      setBusy(false);
    }
    // Otherwise keep showing the last good version; the editor explains what is wrong.
    document.dispatchEvent(new CustomEvent("siteforge:previewerror", {
      detail: { message: message, problems: problems || [] }
    }));
  }

  function render(options) {
    if (!currentConfig) { return; }
    var quiet = Boolean(options && options.quiet);
    var reveal = Boolean(options && options.reveal);
    var token = ++renderToken;

    if (!quiet || !hasContent) {
      errorBox.classList.add("is-hidden");
      setBusy(true);
    }

    fetch("/api/render", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ config: currentConfig, preview: true, files: false })
    })
      .then(function (response) {
        return response.json()
          .catch(function () { return {}; })
          .then(function (data) { return { ok: response.ok, data: data }; });
      })
      .then(function (result) {
        if (token !== renderToken) { return; }          // a newer render replaced this one
        if (!result.ok || typeof result.data.html !== "string") {
          var error = new Error(result.data.message || "The preview could not be built.");
          error.problems = result.data.problems;
          throw error;
        }

        discardPending();
        var next = createFrame();
        next.revealWhenReady = reveal;
        pendingFrame = next;
        applySize(next);
        viewport.insertBefore(next, frame.nextSibling);

        // If the page's own script does not answer, swap anyway once it has loaded.
        next.addEventListener("load", function () {
          swapTimer = window.setTimeout(function () { swapTo(next); }, 700);
        });
        next.srcdoc = result.data.html;
      })
      .catch(function (error) {
        if (token !== renderToken) { return; }
        reportFailure(error.message || "The preview could not be built.", error.problems, quiet);
      });
  }

  function show(config, options) {
    currentConfig = config;
    section.classList.remove("hidden");
    if (options && options.reveal) { lastScrollY = 0; }
    layout();
    render(options);
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
  refreshButton.addEventListener("click", function () { render({}); });
  document.getElementById("preview-retry").addEventListener("click", function () { render({}); });
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

  window.SiteForgePreview = {
    show: show,
    refresh: function () { render({}); },
    setDevice: setDevice
  };
})();
