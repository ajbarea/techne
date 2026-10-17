// Shared by every sister docs site. The canonical copy is in techne
// (plugins/techne/skills/docs-site/templates/shared/); edit it there and run the
// docs-site sync, never in a site. overrides/main.html loads it.
//
// Two behaviors every page gets:
// - a header button that hides the navigation and table of contents, remembered per
//   reader; overrides/main.html sets data-sidebars before first paint, so a hidden
//   state does not flash the panels in;
// - a table wider than its column becomes a labelled region that takes keyboard
//   focus, so it can be scrolled.
(function () {
  "use strict";
  var KEY = "sidebars";
  var root = document.documentElement;

  function hidden() {
    return root.getAttribute("data-sidebars") === "hidden";
  }

  function remember(value) {
    try {
      if (value) localStorage.setItem(KEY, value);
      else localStorage.removeItem(KEY);
    } catch (e) {
      /* storage blocked: the toggle still works for this page */
    }
  }

  function label(button) {
    var on = hidden();
    button.setAttribute("aria-pressed", on ? "true" : "false");
    button.setAttribute("aria-label", on ? "Show side panels" : "Hide side panels");
    button.title = on ? "Show side panels" : "Hide side panels";
  }

  function mount() {
    if (document.querySelector(".sidebars-toggle")) return;
    var search = document.querySelector(".md-header__inner .md-search");
    var anchor = search || document.querySelector(".md-header__inner .md-header__source");
    if (!anchor) return;
    var button = document.createElement("button");
    button.type = "button";
    button.className = "sidebars-toggle md-header__button";
    button.innerHTML =
      '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 4h18a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1zm1 2v12h4V6H4zm6 0v12h6V6h-6zm8 0v12h2V6h-2z"/></svg>';
    button.addEventListener("click", function () {
      if (hidden()) {
        root.removeAttribute("data-sidebars");
        remember(null);
      } else {
        root.setAttribute("data-sidebars", "hidden");
        remember("hidden");
      }
      label(button);
    });
    label(button);
    anchor.parentNode.insertBefore(button, anchor);
  }

  // Zensical's script wraps each table in .md-typeset__scrollwrap, the box that scrolls.
  function focusableTables() {
    var boxes = document.querySelectorAll(".md-typeset__scrollwrap");
    for (var i = 0; i < boxes.length; i++) {
      var box = boxes[i];
      if (box.scrollWidth > box.clientWidth + 1) {
        box.setAttribute("tabindex", "0");
        box.setAttribute("role", "region");
        box.setAttribute("aria-label", tableName(box));
      } else {
        box.removeAttribute("tabindex");
        box.removeAttribute("role");
        box.removeAttribute("aria-label");
      }
    }
  }

  function tableName(box) {
    var caption = box.querySelector("caption");
    if (caption) return caption.textContent.trim();
    for (var e = box.previousElementSibling; e; e = e.previousElementSibling) {
      if (/^H[1-6]$/.test(e.tagName)) {
        var heading = e.cloneNode(true);
        var link = heading.querySelector(".headerlink");
        if (link) link.remove();
        return heading.textContent.trim() + " table";
      }
    }
    return "Table";
  }

  function init() {
    mount();
    focusableTables();
  }

  window.addEventListener("resize", focusableTables);
  if (window.document$ && typeof window.document$.subscribe === "function") {
    window.document$.subscribe(init);
  } else if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
