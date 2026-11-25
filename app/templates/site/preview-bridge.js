/* Preview only. Lets SiteForge keep the scroll position when the preview is rebuilt.
 * It sends and accepts plain numbers and nothing else. It is not part of the downloaded website. */
(function () {
  "use strict";
  var host = window.parent;
  if (!host || host === window) { return; }

  var waiting = false;
  window.addEventListener("scroll", function () {
    if (waiting) { return; }
    waiting = true;
    window.requestAnimationFrame(function () {
      waiting = false;
      host.postMessage({ siteforge: "scroll", y: Math.round(window.scrollY) }, "*");
    });
  }, { passive: true });

  window.addEventListener("message", function (event) {
    if (event.source !== host) { return; }
    var data = event.data;
    if (!data || data.siteforge !== "restore" || typeof data.y !== "number" || !isFinite(data.y)) { return; }
    var root = document.documentElement;
    root.style.scrollBehavior = "auto";
    window.scrollTo(0, Math.max(0, Math.min(data.y, 1000000)));
    root.style.scrollBehavior = "";
    host.postMessage({ siteforge: "restored" }, "*");
  });

  host.postMessage({ siteforge: "ready" }, "*");
})();
