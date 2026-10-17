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

  // A fixed label, with aria-pressed carrying the state (ARIA toggle button pattern).
  function label(button) {
    button.setAttribute("aria-pressed", hidden() ? "true" : "false");
    button.setAttribute("aria-label", "Hide side panels");
    button.title = hidden() ? "Show side panels" : "Hide side panels";
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
  // A ResizeObserver re-checks a box whenever its width changes: a window resize, or
  // the side panels hiding or showing.
  var observer =
    "ResizeObserver" in window
      ? new ResizeObserver(function (entries) {
          for (var i = 0; i < entries.length; i++) region(entries[i].target);
        })
      : null;

  function region(box) {
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

  function focusableTables() {
    if (observer) observer.disconnect();
    var boxes = document.querySelectorAll(".md-typeset__scrollwrap");
    for (var i = 0; i < boxes.length; i++) {
      region(boxes[i]);
      if (observer) observer.observe(boxes[i]);
    }
  }

  // The table's caption, else the nearest heading before it in the article (inside an
  // admonition or tab too), numbered when one heading holds several tables.
  function tableName(box) {
    var caption = box.querySelector("caption");
    if (caption) return caption.textContent.trim();
    var article = box.closest("article") || document.body;
    var heading = null;
    var headings = article.querySelectorAll("h1, h2, h3, h4, h5, h6");
    for (var i = 0; i < headings.length; i++) {
      if (headings[i].compareDocumentPosition(box) & Node.DOCUMENT_POSITION_FOLLOWING) {
        heading = headings[i];
      }
    }
    if (!heading) return "Table";
    var copy = heading.cloneNode(true);
    var link = copy.querySelector(".headerlink");
    if (link) link.remove();
    var name = copy.textContent.trim() + " table";
    var boxes = article.querySelectorAll(".md-typeset__scrollwrap");
    var count = 0;
    var index = 0;
    for (var j = 0; j < boxes.length; j++) {
      var before = boxes[j] === box || (heading.compareDocumentPosition(boxes[j]) & Node.DOCUMENT_POSITION_FOLLOWING);
      var next = nextHeading(headings, heading);
      var inside = !next || (boxes[j].compareDocumentPosition(next) & Node.DOCUMENT_POSITION_FOLLOWING);
      if (before && inside) {
        count++;
        if (boxes[j] === box) index = count;
      }
    }
    return count > 1 ? name + " " + index : name;
  }

  function nextHeading(headings, heading) {
    for (var i = 0; i < headings.length - 1; i++) if (headings[i] === heading) return headings[i + 1];
    return null;
  }

  function init() {
    mount();
    focusableTables();
  }

  if (!observer) window.addEventListener("resize", focusableTables);
  if (window.document$ && typeof window.document$.subscribe === "function") {
    window.document$.subscribe(init);
  } else if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
