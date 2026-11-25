/* SiteForge AI website editor.
 *
 * Builds its forms from the schema published at /api/schema, so every section
 * type is editable and the forms always match what the server accepts.
 * The configuration being edited lives in `state.config`. After each change
 * the live preview is rebuilt; the server validates everything again, so this
 * script never has to be trusted. All page elements are created with
 * createElement and textContent, never with HTML strings.
 *
 * Other scripts can use window.SiteForgeEditor:
 *   getConfig()  hasUnsavedChanges()  markExported()  load(config)
 */
(function () {
  "use strict";

  var panel = document.getElementById("editor-panel");
  if (!panel) { return; }

  function byId(id) { return document.getElementById(id); }

  var nodes = {
    status: byId("editor-status"), error: byId("editor-error"), discard: byId("editor-discard"),
    site: byId("editor-site"), sections: byId("editor-sections"), add: byId("editor-add"),
    design: byId("editor-design"),
    tabContent: byId("tab-content"), tabDesign: byId("tab-design"),
    panelContent: byId("panel-content"), panelDesign: byId("panel-design")
  };

  var DEBOUNCE_MS = 450;
  var POLL_MS = 1500;
  var MAX_POLL_FAILURES = 3;
  var HEX_COLOR = /^#[0-9a-fA-F]{6}$/;

  var schema = null;
  var schemaPromise = null;
  var state = { config: null, original: null, exported: true, busy: false, open: {} };
  var commitTimer = null;
  var counter = 0;

  /* ---------- friendly names ---------- */
  var LABELS = {
    site_name: "Website name", tagline: "Tagline", headline: "Headline", subheadline: "Subheadline",
    primary_cta: "Main button", secondary_cta: "Second button", label: "Button text", target: "Links to",
    image: "Picture", image_alt: "Picture description (for screen readers)", layout: "Layout",
    title: "Title", intro: "Intro text", body: "Paragraphs", highlights: "Highlights", items: "Items",
    icon: "Icon", description: "Description", categories: "Categories", name: "Name", price: "Price",
    caption: "Caption", category: "Category", badge: "Badge", quote: "Quote", role: "Role", bio: "About them",
    members: "People", plans: "Plans", period: "Billing period", features: "Included features",
    highlighted: "Highlight this plan", cta_label: "Button text", question: "Question", answer: "Answer",
    email: "Email", phone: "Phone", address: "Address", hours: "Opening hours", days: "Days", time: "Hours",
    show_form: "Show a contact form", button_label: "Button text", text: "Text", excerpt: "Excerpt", date: "Date"
  };
  var TYPE_NAMES = {
    hero: "Opening banner", about: "About", features: "Features", menu: "Menu", gallery: "Gallery",
    projects: "Projects", products: "Products", testimonials: "Testimonials", team: "Team", pricing: "Pricing",
    faq: "FAQ", contact: "Contact", cta: "Call to action", posts: "Blog posts"
  };
  var RADIUS_NAMES = { none: "Square", sm: "Slightly rounded", md: "Rounded", lg: "Very rounded", xl: "Extra rounded" };

  function labelFor(name) {
    if (LABELS[name]) { return LABELS[name]; }
    var spaced = name.replace(/_/g, " ");
    return spaced.charAt(0).toUpperCase() + spaced.slice(1);
  }

  function capitalize(text) { return text.charAt(0).toUpperCase() + text.slice(1); }

  /* ---------- small helpers ---------- */
  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (name) {
      var value = attrs[name];
      if (value === null || value === undefined || value === false) { return; }
      if (name === "class") { node.className = value; }
      else if (name === "text") { node.textContent = value; }
      else if (name.slice(0, 2) === "on") { node.addEventListener(name.slice(2), value); }
      else if (value === true) { node.setAttribute(name, ""); }
      else { node.setAttribute(name, String(value)); }
    });
    (children || []).forEach(function (child) {
      if (child) { node.appendChild(typeof child === "string" ? document.createTextNode(child) : child); }
    });
    return node;
  }

  function icon(name) { return el("i", { class: "fa-solid fa-" + name, "aria-hidden": "true" }); }
  function clone(value) { return JSON.parse(JSON.stringify(value)); }
  function nextId(prefix) { counter += 1; return prefix + counter; }

  function setStatus(message) { nodes.status.textContent = message || ""; }
  function setError(message) { nodes.error.textContent = message || ""; }

  function humanizeProblems(problems) {
    return (problems || []).slice(0, 3).map(function (problem) {
      return problem.replace(/\[(\d+)\]/g, function (_, n) { return " " + (parseInt(n, 10) + 1); }).replace(/\./g, " > ");
    }).join("; ");
  }

  function apiError(data, fallback) {
    var message = (data && data.message) || fallback;
    if (data && data.problems && data.problems.length) { message += " (" + humanizeProblems(data.problems) + ")"; }
    var error = new Error(message);
    error.fatal = true;
    return error;
  }

  function parseResponse(response) {
    return response.json()
      .catch(function () { return {}; })
      .then(function (data) { return { ok: response.ok, status: response.status, data: data }; });
  }

  function findSection(type) {
    return state.config.sections.filter(function (section) { return section.type === type; })[0] || null;
  }

  function sectionLabel(section) {
    return section.nav_label || (schema.sections[section.type] && schema.sections[section.type].label) || section.type;
  }

  function imageChars(value) {
    if (Array.isArray(value)) { return value.reduce(function (sum, item) { return sum + imageChars(item); }, 0); }
    if (value && typeof value === "object") {
      return Object.keys(value).reduce(function (sum, key) {
        var item = value[key];
        return sum + (key === "image" && typeof item === "string" ? item.length : imageChars(item));
      }, 0);
    }
    return 0;
  }

  /* ---------- schema ---------- */
  function loadSchema() {
    if (schemaPromise) { return schemaPromise; }
    schemaPromise = fetch("/api/schema", { headers: { Accept: "application/json" } })
      .then(function (response) {
        if (!response.ok) { throw new Error("schema"); }
        return response.json();
      })
      .then(function (data) { schema = data; return data; })
      .catch(function (error) { schemaPromise = null; throw error; });
    return schemaPromise;
  }

  function blankValue(spec) {
    switch (spec.kind) {
      case "enum": case "bool": return spec["default"];
      case "icon": return "star";
      case "target": return state.config.sections[0].id;
      case "object":
        var entry = {};
        Object.keys(spec.fields).forEach(function (name) { entry[name] = blankValue(spec.fields[name]); });
        return entry;
      case "list":
        var list = [];
        for (var i = 0; i < spec.min; i += 1) { list.push(blankValue(spec.item)); }
        return list;
      default: return "";
    }
  }

  /* ---------- committing changes to the preview ---------- */
  function commit(immediate) {
    state.exported = false;
    window.clearTimeout(commitTimer);
    var run = function () {
      if (window.SiteForgePreview) { window.SiteForgePreview.show(state.config, { quiet: true }); }
      document.dispatchEvent(new CustomEvent("siteforge:configchanged", { detail: { config: state.config } }));
    };
    if (immediate) { run(); } else { commitTimer = window.setTimeout(run, DEBOUNCE_MS); }
  }

  function setBusy(on) {
    state.busy = on;
    panel.setAttribute("aria-busy", String(on));
    Array.prototype.forEach.call(panel.querySelectorAll("input, select, textarea, button"), function (control) {
      if (control.hasAttribute("data-keep")) { return; }
      if (on) {
        control.setAttribute("data-was-disabled", control.disabled ? "1" : "0");
        control.disabled = true;
      } else if (control.hasAttribute("data-was-disabled")) {
        control.disabled = control.getAttribute("data-was-disabled") === "1";
        control.removeAttribute("data-was-disabled");
      }
    });
  }

  /* ---------- form fields ---------- */
  function fieldShell(id, labelText, control, extras) {
    return el("div", { class: "field" }, [el("label", { "for": id, text: labelText }), control].concat(extras || []));
  }

  function textField(spec, parent, key, label) {
    var id = nextId("ed-");
    var isLong = spec.max > 150;
    var input = el(isLong ? "textarea" : "input", {
      id: id, type: isLong ? null : "text", maxlength: spec.max, "data-field": key,
      "aria-required": spec.required ? "true" : null, rows: isLong ? (spec.max > 300 ? 5 : 3) : null
    });
    input.value = parent[key] || "";
    var extras = [];
    if (isLong) {
      var count = el("span", { class: "field-note", text: input.value.length + " / " + spec.max });
      extras.push(count);
      input.addEventListener("input", function () { count.textContent = input.value.length + " / " + spec.max; });
    }
    input.addEventListener("input", function () { parent[key] = input.value; commit(); });
    return fieldShell(id, label + (spec.required ? " *" : ""), input, extras);
  }

  function simpleInput(spec, parent, key, label, type, maxLength) {
    var id = nextId("ed-");
    var input = el("input", { id: id, type: type, maxlength: maxLength, "data-field": key });
    input.value = parent[key] || "";
    input.addEventListener("input", function () { parent[key] = input.value; commit(); });
    return fieldShell(id, label, input);
  }

  function selectField(options, parent, key, label, current) {
    var id = nextId("ed-");
    var select = el("select", { id: id, "data-field": key }, options.map(function (option) {
      return el("option", { value: option.value, text: option.label });
    }));
    var found = options.some(function (option) { return option.value === current; });
    select.value = found ? current : options[0].value;
    if (!found) { parent[key] = select.value; }
    select.addEventListener("change", function () { parent[key] = select.value; commit(true); });
    return fieldShell(id, label, select);
  }

  function enumField(spec, parent, key, label) {
    var options = spec.values.map(function (value) { return { value: value, label: capitalize(value) }; });
    return selectField(options, parent, key, label, parent[key]);
  }

  function iconField(spec, parent, key, label) {
    var field = selectField(schema.icons.map(function (name) {
      return { value: name, label: capitalize(name.replace(/-/g, " ")) };
    }), parent, key, label, parent[key]);
    var select = field.querySelector("select");
    var preview = icon(select.value);
    preview.style.marginLeft = "0.25rem";
    select.addEventListener("change", function () { preview.className = "fa-solid fa-" + select.value; });
    field.querySelector("label").appendChild(preview);
    return field;
  }

  function targetField(spec, parent, key, label) {
    var options = state.config.sections.map(function (section) {
      return { value: section.id, label: sectionLabel(section) };
    });
    return selectField(options, parent, key, label, parent[key]);
  }

  function boolField(spec, parent, key, label) {
    var id = nextId("ed-");
    var box = el("input", { id: id, type: "checkbox", "data-field": key });
    box.checked = Boolean(parent[key]);
    box.addEventListener("change", function () { parent[key] = box.checked; commit(true); });
    return el("div", { class: "field-check" }, [box, el("label", { "for": id, text: label })]);
  }

  /* ---------- pictures ---------- */
  function supportsWebp() {
    var canvas = document.createElement("canvas");
    canvas.width = canvas.height = 1;
    return canvas.toDataURL("image/webp").indexOf("data:image/webp") === 0;
  }

  function shrinkToDataUri(image) {
    var webp = supportsWebp();
    var sizes = [1600, 1200, 900, 640];
    var qualities = [0.85, 0.72, 0.6];
    for (var s = 0; s < sizes.length; s += 1) {
      var scale = Math.min(1, sizes[s] / Math.max(image.naturalWidth, image.naturalHeight));
      var canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
      canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
      var context = canvas.getContext("2d");
      if (!webp) { context.fillStyle = "#ffffff"; context.fillRect(0, 0, canvas.width, canvas.height); }
      context.drawImage(image, 0, 0, canvas.width, canvas.height);
      for (var q = 0; q < qualities.length; q += 1) {
        var uri = canvas.toDataURL(webp ? "image/webp" : "image/jpeg", qualities[q]);
        if (uri.length <= schema.limits.image_max_chars) { return uri; }
      }
    }
    throw new Error("That picture is too large, even after shrinking it. Try a smaller one.");
  }

  function prepareImage(file, currentValue) {
    return new Promise(function (resolve, reject) {
      if (!/^image\/(png|jpeg|webp|gif)$/.test(file.type)) {
        reject(new Error("Choose a PNG, JPEG, WebP, or GIF picture."));
        return;
      }
      if (file.size > 25 * 1024 * 1024) { reject(new Error("That file is larger than 25 MB.")); return; }
      var url = URL.createObjectURL(file);
      var image = new Image();
      image.onload = function () {
        URL.revokeObjectURL(url);
        try {
          var uri = shrinkToDataUri(image);
          var total = imageChars(state.config) - (currentValue || "").length + uri.length;
          if (total > schema.limits.total_image_max_chars) {
            throw new Error("The pictures in this website are already very large. Remove one before adding another.");
          }
          resolve(uri);
        } catch (error) { reject(error); }
      };
      image.onerror = function () {
        URL.revokeObjectURL(url);
        reject(new Error("That file could not be read as a picture."));
      };
      image.src = url;
    });
  }

  function imageField(spec, parent, key, label) {
    var picture = el("div", { class: "image-row" });
    var note = el("p", { class: "field-note", role: "status" });
    var fileInput = el("input", { type: "file", accept: "image/png,image/jpeg,image/webp,image/gif", hidden: true, tabindex: "-1", "data-field": key + "-file" });
    var chooseText = el("span");
    var choose = el("button", { type: "button", class: "tool-btn tool-btn--sm" }, [icon("upload"), chooseText]);
    var remove = el("button", { type: "button", class: "tool-btn tool-btn--sm" }, [icon("trash-can"), el("span", { text: "Use placeholder" })]);
    var thumbHolder = el("div");

    function paint() {
      thumbHolder.textContent = "";
      var value = parent[key];
      if (value && value.indexOf("data:image/") === 0) {
        var thumb = el("img", { class: "thumb", alt: "Uploaded picture preview" });
        thumb.src = value;
        thumbHolder.appendChild(thumb);
      } else {
        thumbHolder.appendChild(el("div", { class: "image-empty", text: "Placeholder" }));
      }
      chooseText.textContent = value ? "Replace picture" : "Upload picture";
      remove.hidden = !value;
    }

    choose.addEventListener("click", function () { fileInput.click(); });
    fileInput.addEventListener("change", function () {
      var file = fileInput.files && fileInput.files[0];
      fileInput.value = "";
      if (!file) { return; }
      note.className = "field-note";
      note.textContent = "Preparing the picture...";
      prepareImage(file, parent[key]).then(function (uri) {
        parent[key] = uri;
        paint();
        note.textContent = "Picture added.";
        commit(true);
      }).catch(function (error) {
        note.className = "field-note is-error";
        note.textContent = error.message;
      });
    });
    remove.addEventListener("click", function () {
      parent[key] = "";
      paint();
      note.className = "field-note";
      note.textContent = "Picture removed.";
      commit(true);
    });

    picture.appendChild(thumbHolder);
    picture.appendChild(el("div", { class: "item-actions" }, [choose, remove]));
    paint();
    return el("div", { class: "field" }, [el("span", { class: "field-label", text: label }), picture, fileInput, note]);
  }

  /* ---------- groups and lists ---------- */
  function buildFields(fields, parent) {
    var holder = document.createDocumentFragment();
    Object.keys(fields).forEach(function (name) {
      holder.appendChild(buildField(fields[name], parent, name, labelFor(name)));
    });
    return holder;
  }

  function objectField(spec, parent, key, label) {
    var group = el("fieldset", { class: "group" }, [el("legend", { text: label })]);
    if (!parent[key] || typeof parent[key] !== "object") { parent[key] = blankValue(spec); }
    group.appendChild(buildFields(spec.fields, parent[key]));
    return group;
  }

  function itemTitle(entry, index) {
    var keys = ["name", "title", "question", "caption", "quote", "days", "label"];
    for (var i = 0; i < keys.length; i += 1) {
      if (entry && typeof entry[keys[i]] === "string" && entry[keys[i]].trim()) {
        return entry[keys[i]].trim().slice(0, 50);
      }
    }
    return "Item " + (index + 1);
  }

  function listField(spec, parent, key, label) {
    if (!Array.isArray(parent[key])) { parent[key] = blankValue(spec); }
    var items = parent[key];
    var isText = spec.item.kind === "text";
    var wrapper = el("fieldset", { class: "group" }, [el("legend", { text: label })]);
    var holder = el("div", { class: "list" });
    var addButton = el("button", { type: "button", class: "tool-btn tool-btn--sm", style: "margin-top:0.6rem" },
      [icon("plus"), el("span", { text: "Add " + label.toLowerCase().replace(/ies$/, "y").replace(/s$/, "") })]);
    wrapper.appendChild(holder);
    wrapper.appendChild(addButton);

    function move(index, delta, action) {
      var target = index + delta;
      if (target < 0 || target >= items.length) { return; }
      var moved = items.splice(index, 1)[0];
      items.splice(target, 0, moved);
      render(target);
      commit(true);
      var row = holder.children[target];
      var button = row && row.querySelector('[data-act="' + action + '"]');
      if (button && !button.disabled) { button.focus(); }
    }

    function removeAt(index) {
      items.splice(index, 1);
      render();
      commit(true);
      addButton.focus();
    }

    function actionButtons(index) {
      var up = el("button", { type: "button", class: "icon-btn", "data-act": "up", "aria-label": "Move up", disabled: index === 0 }, [icon("arrow-up")]);
      var down = el("button", { type: "button", class: "icon-btn", "data-act": "down", "aria-label": "Move down", disabled: index === items.length - 1 }, [icon("arrow-down")]);
      var del = el("button", { type: "button", class: "icon-btn icon-btn--danger", "data-act": "remove", "aria-label": "Remove", disabled: items.length <= spec.min }, [icon("trash-can")]);
      up.addEventListener("click", function () { move(index, -1, "up"); });
      down.addEventListener("click", function () { move(index, 1, "down"); });
      del.addEventListener("click", function () { removeAt(index); });
      return [up, down, del];
    }

    function render(openIndex) {
      holder.textContent = "";
      items.forEach(function (entry, index) {
        if (isText) {
          var field = textField(spec.item, items, index, "Item " + (index + 1));
          holder.appendChild(el("div", { class: "list-text" }, [field].concat(actionButtons(index))));
          return;
        }
        var summary = el("summary", { text: itemTitle(entry, index) });
        var details = el("details", { class: "item" }, [summary]);
        if (index === openIndex) { details.setAttribute("open", ""); }
        var body = el("div", { class: "item-body" }, [el("div", { class: "item-actions" }, actionButtons(index))]);
        body.appendChild(spec.item.kind === "object" ? buildFields(spec.item.fields, entry)
          : buildField(spec.item, items, index, "Value"));
        details.appendChild(body);
        details.addEventListener("input", function () { summary.textContent = itemTitle(entry, index); });
        holder.appendChild(details);
      });
      addButton.disabled = items.length >= spec.max;
    }

    addButton.addEventListener("click", function () {
      items.push(blankValue(spec.item));
      var index = items.length - 1;
      render(index);
      var firstInput = holder.children[index].querySelector("input, textarea, select");
      if (firstInput) { firstInput.focus(); }
      commit(true);
    });

    render();
    return wrapper;
  }

  function buildField(spec, parent, key, label) {
    switch (spec.kind) {
      case "text": return textField(spec, parent, key, label);
      case "enum": return enumField(spec, parent, key, label);
      case "bool": return boolField(spec, parent, key, label);
      case "icon": return iconField(spec, parent, key, label);
      case "email": return simpleInput(spec, parent, key, label, "email", 120);
      case "phone": return simpleInput(spec, parent, key, label, "tel", 24);
      case "price": return simpleInput(spec, parent, key, label, "text", 16);
      case "target": return targetField(spec, parent, key, label);
      case "image": return imageField(spec, parent, key, label);
      case "object": return objectField(spec, parent, key, label);
      case "list": return listField(spec, parent, key, label);
      default: return el("div");
    }
  }

  /* ---------- confirm-by-second-click buttons ---------- */
  function armConfirm(button, confirmText, onConfirm, announce) {
    var original = Array.prototype.slice.call(button.childNodes);
    var originalClass = button.className;
    var originalLabel = button.getAttribute("aria-label");
    var timer = null;

    function reset() {
      window.clearTimeout(timer);
      button.removeAttribute("data-armed");
      button.className = originalClass;
      if (originalLabel) { button.setAttribute("aria-label", originalLabel); }
      button.textContent = "";
      original.forEach(function (node) { button.appendChild(node); });
    }

    button.addEventListener("click", function () {
      if (button.getAttribute("data-armed") === "1") {
        reset();
        onConfirm();
        return;
      }
      button.setAttribute("data-armed", "1");
      button.className = originalClass + " icon-btn--confirm tool-btn--confirm";
      button.textContent = confirmText;
      if (originalLabel) { button.setAttribute("aria-label", confirmText + " " + originalLabel); }
      setStatus(announce);
      timer = window.setTimeout(reset, 4000);
    });
  }

  /* ---------- AI writing of sections ---------- */
  function startWrite(type, hint, ui, done) {
    if (state.busy) {
      setError("The AI is already working on something. Wait for it to finish.");
      return;
    }
    setError("");
    setBusy(true);
    ui.line.hidden = false;
    ui.text.textContent = "Asking the AI...";

    var jobId = null;
    var timer = null;
    var cancelled = false;
    var failures = 0;

    function cancelJob(id) {
      fetch("/api/generate/" + encodeURIComponent(id) + "/cancel", { method: "POST" }).catch(function () {});
    }
    function finish() {
      window.clearTimeout(timer);
      ui.line.hidden = true;
      setBusy(false);
    }
    function fail(error) {
      finish();
      setError(error.message);
    }

    ui.cancel.onclick = function () {
      cancelled = true;
      window.clearTimeout(timer);
      if (jobId) { cancelJob(jobId); }
      finish();
      setStatus("Cancelled.");
    };

    function poll() {
      fetch("/api/generate/" + encodeURIComponent(jobId), { headers: { Accept: "application/json" } })
        .then(parseResponse)
        .then(function (result) {
          if (cancelled) { return; }
          if (!result.ok) { throw apiError(result.data, "The AI job was lost. Please try again."); }
          failures = 0;
          var job = result.data;
          if (job.status === "done") {
            finish();
            done(job.result);
          } else if (job.status === "failed") {
            throw apiError(job.error, "The AI could not finish. Please try again.");
          } else if (job.status === "cancelled") {
            finish();
          } else {
            ui.text.textContent = ((job.progress && job.progress.label) || "Working") + "...";
            timer = window.setTimeout(poll, POLL_MS);
          }
        })
        .catch(function (error) {
          if (cancelled) { return; }
          failures += 1;
          if (error.fatal || failures >= MAX_POLL_FAILURES) { fail(error); }
          else { timer = window.setTimeout(poll, POLL_MS); }
        });
    }

    fetch("/api/sections/write", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ config: state.config, type: type, hint: hint })
    })
      .then(parseResponse)
      .then(function (result) {
        if (cancelled) {
          if (result.ok && result.data.job_id) { cancelJob(result.data.job_id); }
          return;
        }
        if (!result.ok) { throw apiError(result.data, "The AI could not start. Please try again."); }
        jobId = result.data.job_id;
        poll();
      })
      .catch(function (error) {
        if (!cancelled) {
          fail(error.fatal ? error : new Error("Could not reach the server. Check that it is running."));
        }
      });
  }

  function jobLine() {
    var text = el("span", { role: "status" });
    var cancel = el("button", { type: "button", class: "tool-btn tool-btn--sm", "data-keep": "", text: "Cancel" });
    var line = el("div", { class: "job-line", hidden: true }, [icon("circle-notch"), text, cancel]);
    line.firstChild.className = "fa-solid fa-circle-notch fa-spin";
    return { line: line, text: text, cancel: cancel };
  }

  function insertSection(created) {
    var list = state.config.sections;
    var at = list.length;
    while (at > 1 && (list[at - 1].type === "contact" || list[at - 1].type === "cta")) { at -= 1; }
    list.splice(at, 0, created);
  }

  function applyWritten(result) {
    var spec = schema.sections[result.type];
    var existing = findSection(result.type);
    if (existing) {
      existing.data = result.data;
      state.open[existing.id] = true;
      setStatus("Rewrote the " + sectionLabel(existing) + " section.");
    } else {
      var created = { id: result.type, type: result.type, nav: spec.nav, nav_label: spec.label, data: result.data };
      insertSection(created);
      state.open[created.id] = true;
      setStatus("Added the " + spec.label + " section.");
    }
    renderSections();
    renderAdd();
    commit(true);
  }

  /* ---------- sections ---------- */
  function moveSection(index, delta, action) {
    var list = state.config.sections;
    var target = index + delta;
    if (index < 1 || target < 1 || target >= list.length) { return; }
    var moved = list.splice(index, 1)[0];
    list.splice(target, 0, moved);
    renderSections();
    commit(true);
    setStatus("Moved " + sectionLabel(moved) + " " + action + ".");
    var holder = nodes.sections.querySelector('[data-sec-id="' + moved.id + '"]');
    var button = holder && holder.querySelector('[data-act="' + action + '"]');
    if (button && !button.disabled) { button.focus(); }
    else if (holder) { holder.querySelector(".sec-toggle").focus(); }
  }

  function removeSection(index) {
    var removed = state.config.sections.splice(index, 1)[0];
    delete state.open[removed.id];
    renderSections();
    renderAdd();
    commit(true);
    setStatus("Removed the " + sectionLabel(removed) + " section.");
    var heading = nodes.sections.querySelector(".sec-toggle");
    if (heading) { heading.focus(); }
  }

  function sectionBody(section) {
    var spec = schema.sections[section.type];
    var body = el("div", { class: "sec-body" });

    var labelId = nextId("ed-");
    var labelInput = el("input", { id: labelId, type: "text", maxlength: 30, "data-field": "nav_label" });
    labelInput.value = section.nav_label || "";
    labelInput.addEventListener("input", function () {
      section.nav_label = labelInput.value;
      var name = body.parentNode && body.parentNode.querySelector(".sec-name");
      if (name) { name.textContent = sectionLabel(section); }
      commit();
    });
    body.appendChild(fieldShell(labelId, "Menu name", labelInput));

    var showId = nextId("ed-");
    var show = el("input", { id: showId, type: "checkbox", "data-field": "nav" });
    show.checked = Boolean(section.nav);
    show.addEventListener("change", function () { section.nav = show.checked; commit(true); });
    body.appendChild(el("div", { class: "field-check" }, [show, el("label", { "for": showId, text: "Show in the menu" })]));

    body.appendChild(buildFields(spec.fields, section.data));

    var hintId = nextId("ed-");
    var hint = el("input", { id: hintId, type: "text", maxlength: 200, "data-field": "hint", placeholder: "Optional: what should change?" });
    var ui = jobLine();
    var rewrite = el("button", { type: "button", class: "tool-btn tool-btn--sm tool-btn--primary", "data-act": "rewrite" },
      [icon("wand-magic-sparkles"), el("span", { text: "Rewrite with AI" })]);
    rewrite.addEventListener("click", function () {
      startWrite(section.type, hint.value, ui, applyWritten);
    });
    body.appendChild(el("div", { class: "sec-ai" }, [
      el("h4", { text: "Rewrite this section with AI" }),
      el("p", { class: "field-note", text: "Replaces the text of this section. Your pictures stay." }),
      el("div", { class: "field" }, [el("label", { "for": hintId, text: "Instruction" }), hint]),
      el("div", { class: "item-actions", style: "margin-top:0.6rem" }, [rewrite]),
      ui.line
    ]));
    return body;
  }

  function sectionBlock(section, index) {
    var list = state.config.sections;
    var isHero = index === 0;
    var bodyId = "sec-body-" + section.id;
    var isOpen = Boolean(state.open[section.id]);

    var toggle = el("button", { type: "button", class: "sec-toggle", "aria-expanded": String(isOpen), "aria-controls": bodyId }, [
      icon("chevron-right"),
      el("span", { class: "sec-name", text: sectionLabel(section) }),
      el("span", { class: "sec-type", text: TYPE_NAMES[section.type] || section.type })
    ]);
    var name = sectionLabel(section);
    var up = el("button", { type: "button", class: "icon-btn", "data-act": "up", "aria-label": "Move " + name + " up", disabled: isHero || index === 1 }, [icon("arrow-up")]);
    var down = el("button", { type: "button", class: "icon-btn", "data-act": "down", "aria-label": "Move " + name + " down", disabled: isHero || index === list.length - 1 }, [icon("arrow-down")]);
    var head = el("div", { class: "sec-head" }, [toggle, up, down]);
    up.addEventListener("click", function () { moveSection(index, -1, "up"); });
    down.addEventListener("click", function () { moveSection(index, 1, "down"); });

    if (!isHero) {
      var remove = el("button", { type: "button", class: "icon-btn icon-btn--danger", "data-act": "remove", "aria-label": "Remove " + name, disabled: list.length <= schema.limits.min_sections }, [icon("trash-can")]);
      armConfirm(remove, "Sure?", function () { removeSection(index); }, "Select the button again to remove " + name + ".");
      head.appendChild(remove);
    }

    var holder = el("div", { class: "sec", "data-sec-id": section.id }, [head]);
    var body = el("div", { id: bodyId, hidden: !isOpen });
    holder.appendChild(body);
    if (isOpen) { body.appendChild(sectionBody(section)); }

    toggle.addEventListener("click", function () {
      var open = toggle.getAttribute("aria-expanded") !== "true";
      toggle.setAttribute("aria-expanded", String(open));
      state.open[section.id] = open;
      body.hidden = !open;
      body.textContent = "";
      if (open) { body.appendChild(sectionBody(section)); }
    });
    return holder;
  }

  function renderSections() {
    nodes.sections.textContent = "";
    nodes.sections.appendChild(el("h3", { text: "Sections" }));
    state.config.sections.forEach(function (section, index) {
      nodes.sections.appendChild(sectionBlock(section, index));
    });
  }

  function renderAdd() {
    nodes.add.textContent = "";
    var used = {};
    state.config.sections.forEach(function (section) { used[section.type] = true; });
    var available = Object.keys(schema.sections).filter(function (type) { return !used[type]; });

    nodes.add.appendChild(el("h3", { text: "Add a section" }));
    if (state.config.sections.length >= schema.limits.max_sections || !available.length) {
      nodes.add.appendChild(el("p", { class: "field-note", text: "This website has all the sections it can hold." }));
      return;
    }

    var selectId = nextId("ed-");
    var select = el("select", { id: selectId, "data-field": "new-section" }, available.map(function (type) {
      return el("option", { value: type, text: TYPE_NAMES[type] || type });
    }));
    var purpose = el("p", { class: "field-note" });
    function showPurpose() { purpose.textContent = "The AI will write " + schema.sections[select.value].purpose + "."; }
    select.addEventListener("change", showPurpose);
    showPurpose();

    var ui = jobLine();
    var addButton = el("button", { type: "button", class: "tool-btn tool-btn--sm tool-btn--primary", "data-act": "add" },
      [icon("plus"), el("span", { text: "Add with AI" })]);
    addButton.addEventListener("click", function () { startWrite(select.value, "", ui, applyWritten); });

    nodes.add.appendChild(el("div", { class: "field" }, [el("label", { "for": selectId, text: "Section type" }), select, purpose]));
    nodes.add.appendChild(el("div", { class: "item-actions", style: "margin-top:0.6rem" }, [addButton]));
    nodes.add.appendChild(ui.line);
  }

  function renderSite() {
    nodes.site.textContent = "";
    nodes.site.appendChild(el("h3", { text: "Website" }));
    nodes.site.appendChild(textField({ max: 60, required: true }, state.config.meta, "site_name", "Website name"));
    nodes.site.appendChild(textField({ max: 140, required: true }, state.config.meta, "tagline", "Tagline"));
    nodes.site.appendChild(textField({ max: 140, required: false }, state.config.footer, "tagline", "Footer text"));
  }

  /* ---------- design ---------- */
  function renderDesign() {
    var box = nodes.design;
    var meta = state.config.meta;
    var theme = state.config.theme;
    box.textContent = "";

    box.appendChild(el("h3", { text: "Style" }));
    var styleField = selectField(schema.styles.map(function (style) {
      return { value: style.id, label: style.name };
    }), meta, "design_style", "Design style", meta.design_style);
    box.appendChild(styleField);
    box.appendChild(el("p", { class: "field-note", text: "Changes the overall look. Fonts and corners stay as they are unless you reset them." }));
    var reset = el("button", { type: "button", class: "tool-btn tool-btn--sm", style: "margin-top:0.5rem", "data-act": "reset-style" },
      [icon("rotate-left"), el("span", { text: "Use this style's fonts and corners" })]);
    reset.addEventListener("click", function () {
      var style = schema.styles.filter(function (item) { return item.id === meta.design_style; })[0];
      if (!style) { return; }
      theme.font_heading = style.font_heading;
      theme.font_body = style.font_body;
      theme.radius = style.radius;
      renderDesign();
      commit(true);
      setStatus("Fonts and corners reset to the " + style.name + " style.");
    });
    box.appendChild(reset);

    box.appendChild(el("h3", { text: "Main color" }));
    var swatches = el("div", { class: "swatches", role: "group", "aria-label": "Color presets" });
    var picker = el("input", { type: "color", id: nextId("ed-"), "aria-label": "Pick any color", "data-field": "primary-picker" });
    var hexId = nextId("ed-");
    var hex = el("input", { id: hexId, type: "text", maxlength: 7, "data-field": "primary" });
    var hexNote = el("p", { class: "field-note" });
    picker.value = theme.primary;
    hex.value = theme.primary;

    function applyColor(value, presetId) {
      theme.primary = value.toLowerCase();
      if (presetId) { meta.color_scheme = presetId; }
      picker.value = theme.primary;
      hex.value = theme.primary;
      hexNote.textContent = "";
      Array.prototype.forEach.call(swatches.children, function (button) {
        button.setAttribute("aria-pressed", String(button.getAttribute("data-color") === theme.primary));
      });
      commit();
    }

    schema.color_schemes.forEach(function (scheme) {
      var button = el("button", {
        type: "button", class: "swatch", style: "background-color:" + scheme.primary,
        "aria-label": scheme.name, "aria-pressed": String(theme.primary === scheme.primary), "data-color": scheme.primary
      });
      button.addEventListener("click", function () { applyColor(scheme.primary, scheme.id); });
      swatches.appendChild(button);
    });
    picker.addEventListener("input", function () { applyColor(picker.value, null); });
    hex.addEventListener("input", function () {
      if (HEX_COLOR.test(hex.value)) { applyColor(hex.value, null); hexNote.className = "field-note"; }
      else { hexNote.className = "field-note is-error"; hexNote.textContent = "Use a color like #2563eb."; }
    });
    box.appendChild(swatches);
    box.appendChild(el("div", { class: "color-row" }, [picker, el("div", { class: "field" }, [el("label", { "for": hexId, text: "Color code" }), hex])]));
    box.appendChild(hexNote);

    box.appendChild(el("h3", { text: "Mode" }));
    var seg = el("div", { class: "seg", role: "group", "aria-label": "Light or dark" });
    schema.modes.forEach(function (mode) {
      var button = el("button", { type: "button", class: "seg-btn", "aria-pressed": String(theme.mode === mode), "data-mode": mode, text: capitalize(mode) });
      button.addEventListener("click", function () {
        theme.mode = mode;
        Array.prototype.forEach.call(seg.children, function (other) {
          other.setAttribute("aria-pressed", String(other === button));
        });
        commit(true);
      });
      seg.appendChild(button);
    });
    box.appendChild(seg);

    box.appendChild(el("h3", { text: "Fonts and corners" }));
    var fontOptions = schema.fonts.map(function (name) { return { value: name, label: name }; });
    box.appendChild(selectField(fontOptions, theme, "font_heading", "Heading font", theme.font_heading));
    box.appendChild(selectField(fontOptions, theme, "font_body", "Body font", theme.font_body));
    box.appendChild(selectField(schema.radii.map(function (name) {
      return { value: name, label: RADIUS_NAMES[name] || name };
    }), theme, "radius", "Corners", theme.radius));
  }

  /* ---------- tabs ---------- */
  function selectTab(name) {
    var content = name === "content";
    nodes.tabContent.setAttribute("aria-selected", String(content));
    nodes.tabDesign.setAttribute("aria-selected", String(!content));
    nodes.tabContent.tabIndex = content ? 0 : -1;
    nodes.tabDesign.tabIndex = content ? -1 : 0;
    nodes.panelContent.hidden = !content;
    nodes.panelDesign.hidden = content;
  }

  [nodes.tabContent, nodes.tabDesign].forEach(function (tab) {
    tab.setAttribute("data-keep", "");
    tab.addEventListener("click", function () { selectTab(tab === nodes.tabContent ? "content" : "design"); });
    tab.addEventListener("keydown", function (event) {
      var keys = { ArrowLeft: "content", ArrowRight: "design", Home: "content", End: "design" };
      if (!keys[event.key]) { return; }
      event.preventDefault();
      selectTab(keys[event.key]);
      (keys[event.key] === "content" ? nodes.tabContent : nodes.tabDesign).focus();
    });
  });

  /* ---------- loading and discarding ---------- */
  function renderAll() {
    renderSite();
    renderSections();
    renderAdd();
    renderDesign();
  }

  function load(config) {
    return loadSchema().then(function () {
      window.clearTimeout(commitTimer);
      state.config = clone(config);
      state.original = clone(config);
      state.exported = false;
      state.open = {};
      setStatus("");
      setError("");
      renderAll();
      selectTab("content");
      if (state.busy) { setBusy(false); }
    }).catch(function () {
      setError("The editor could not load. Reload the page and try again.");
    });
  }

  armConfirm(nodes.discard, "Sure? Discard", function () {
    state.config = clone(state.original);
    renderAll();
    commit(true);
    setError("");
    setStatus("All changes discarded.");
  }, "Select the button again to discard every change you made.");

  /* ---------- events ---------- */
  document.addEventListener("siteforge:generated", function (event) {
    if (event.detail && event.detail.config) { load(event.detail.config); }
  });
  document.addEventListener("siteforge:rendered", function () { setError(""); });
  document.addEventListener("siteforge:previewerror", function (event) {
    var detail = event.detail || {};
    var reason = humanizeProblems(detail.problems) || detail.message || "The website data is not valid.";
    setError("The preview was not updated: " + reason);
  });

  window.addEventListener("beforeunload", function (event) {
    if (state.config && !state.exported) {
      event.preventDefault();
      event.returnValue = "";
    }
  });

  window.SiteForgeEditor = {
    getConfig: function () { return state.config; },
    hasUnsavedChanges: function () { return Boolean(state.config) && !state.exported; },
    markExported: function () { state.exported = true; },
    load: load
  };
})();
