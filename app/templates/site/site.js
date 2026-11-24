/* Website behaviour: mobile menu, active menu link, and the contact form. No libraries. */
(function () {
  "use strict";

  document.documentElement.classList.add("js");

  /* ---- mobile menu ---- */
  var toggle = document.querySelector(".nav-toggle");
  var nav = document.getElementById("site-nav");
  if (toggle && nav) {
    var setOpen = function (open) {
      nav.classList.toggle("is-open", open);
      toggle.setAttribute("aria-expanded", String(open));
    };
    toggle.addEventListener("click", function () {
      setOpen(toggle.getAttribute("aria-expanded") !== "true");
    });
    nav.addEventListener("click", function (event) {
      if (event.target.closest("a")) { setOpen(false); }
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && nav.classList.contains("is-open")) {
        setOpen(false);
        toggle.focus();
      }
    });
  }

  /* ---- highlight the menu link of the section being read ---- */
  var links = Array.prototype.slice.call(document.querySelectorAll(".site-nav a[href^='#']"));
  if (links.length && "IntersectionObserver" in window) {
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) { return; }
        links.forEach(function (link) {
          if (link.getAttribute("href") === "#" + entry.target.id) {
            link.setAttribute("aria-current", "true");
          } else {
            link.removeAttribute("aria-current");
          }
        });
      });
    }, { rootMargin: "-40% 0px -55% 0px" });
    links.forEach(function (link) {
      var target = document.getElementById(link.getAttribute("href").slice(1));
      if (target) { observer.observe(target); }
    });
  }

  /* ---- contact form: opens the visitor's email app with the message filled in ---- */
  var form = document.querySelector(".contact-form");
  if (form) {
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var name = form.elements["name"].value.trim();
      var from = form.elements["email"].value.trim();
      var message = form.elements["message"].value.trim();
      var status = form.querySelector(".form-status");
      if (!name || !from || !message) {
        status.textContent = "Please fill in your name, email, and message.";
        return;
      }
      var body = message + "\n\n" + name + "\n" + from;
      var address = form.getAttribute("data-mailto");
      window.location.href = "mailto:" + encodeURIComponent(address).replace("%40", "@") +
        "?subject=" + encodeURIComponent("Message from " + name) + "&body=" + encodeURIComponent(body);
      status.textContent = "Opening your email app...";
    });
  }
})();
