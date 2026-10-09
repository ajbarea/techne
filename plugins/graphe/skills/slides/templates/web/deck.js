// Deck behaviour: values and figures bound from data/deck-data.js, the agenda and chapter rail
// built from each slide's data-chapter, then reveal.js started. Everything here runs before
// Reveal.initialize, so fragments it creates are counted like hand-written ones.
(function () {
  "use strict";

  const DATA = window.DECK_DATA || {};
  const SVG = "http://www.w3.org/2000/svg";
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const phone = matchMedia("(max-width: 600px)").matches;

  function lookup(path) {
    const value = path.split(".").reduce((o, k) => (o == null ? undefined : o[k]), DATA);
    if (value === undefined) console.error(`deck: no data at ${path}`);
    return value;
  }

  function svg(name, attrs, parent, text) {
    const node = document.createElementNS(SVG, name);
    for (const [k, v] of Object.entries(attrs || {})) node.setAttribute(k, v);
    if (text !== undefined) node.textContent = text;
    if (parent) parent.appendChild(node);
    return node;
  }

  function html(name, attrs, parent, text) {
    const node = document.createElement(name);
    for (const [k, v] of Object.entries(attrs || {})) node.setAttribute(k, v);
    if (text !== undefined) node.textContent = text;
    if (parent) parent.appendChild(node);
    return node;
  }

  // <span data-value="results.failShare" data-format="pct"></span>
  function bindValues() {
    for (const node of document.querySelectorAll("[data-value]")) {
      const v = lookup(node.dataset.value);
      if (v === undefined) {
        node.textContent = `[missing ${node.dataset.value}]`;
      } else if (node.dataset.format === "pct") {
        node.textContent = `${Math.round(v * 100)}%`;
      } else if (typeof v === "number") {
        node.textContent = v.toLocaleString("en-US");
      } else {
        node.textContent = String(v);
      }
    }
  }

  // <div class="dots" data-dots="results.failShare" data-total="100">: one dot per unit,
  // the share filled. A count drawn as marks, so it traces to the data like a typed number.
  function buildDots() {
    for (const box of document.querySelectorAll("[data-dots]")) {
      const total = Number(box.dataset.total || 100);
      const share = lookup(box.dataset.dots);
      if (typeof share !== "number") continue;
      const hit = Math.round(share * total);
      const cols = Number(box.dataset.cols || 20);
      const rows = Math.ceil(total / cols);
      const fig = svg("svg", {
        viewBox: `0 0 ${cols * 20} ${rows * 20}`,
        role: "img",
        "aria-label": `${hit} of ${total} filled`,
      });
      for (let i = 0; i < total; i++) {
        svg("circle", {
          cx: (i % cols) * 20 + 10,
          cy: Math.floor(i / cols) * 20 + 10,
          r: 7,
          class: i < hit ? "dot hit" : "dot",
          style: `--i:${i}`,
        }, fig);
      }
      box.appendChild(fig);
    }
  }

  // <div class="relmap" data-source="related">: rivals placed by the two axes in the data,
  // ours added as the slide's last fragment, and the "how ours differs" lines beside it.
  // A list still being filled in leaves its slide empty instead of stopping the deck.
  function usable(rel, source) {
    if (rel && Array.isArray(rel.works) && rel.works.length) return true;
    console.error(`deck: ${source} has no works to draw`);
    return false;
  }

  function buildMap(box) {
    const rel = lookup(box.dataset.source);
    if (!usable(rel, box.dataset.source)) return;
    if (!rel.axes || !rel.axes.x || !rel.axes.y) {
      console.error(`deck: ${box.dataset.source} has no axes for the map`);
      return;
    }
    const { x, y } = rel.axes;
    const W = 720, H = 420, left = 175, top = 20, bottom = 60;
    const cw = (W - left) / x.levels.length;
    const rh = (H - top - bottom) / y.levels.length;
    const fig = svg("svg", {
      viewBox: `0 0 ${W} ${H}`,
      role: "img",
      "aria-label": `Related work by ${x.label} and ${y.label}`,
    });
    y.levels.forEach((lv, r) => {
      const cy = top + r * rh;
      svg("rect", { x: left, y: cy, width: W - left, height: rh, class: r % 2 ? "band" : "band alt" }, fig);
      svg("text", { x: left - 12, y: cy + rh / 2, class: "axis-level", "text-anchor": "end" }, fig, lv);
    });
    x.levels.forEach((lv, c) => {
      svg("text", { x: left + c * cw + cw / 2, y: H - bottom + 26, class: "axis-level", "text-anchor": "middle" }, fig, lv);
    });
    svg("text", { x: left + (W - left) / 2, y: H - 8, class: "axis-label", "text-anchor": "middle" }, fig, x.label);
    svg("text", { x: 14, y: top + (H - top - bottom) / 2, class: "axis-label", transform: `rotate(-90 14 ${top + (H - top - bottom) / 2})`, "text-anchor": "middle" }, fig, y.label);

    const cell = new Map();
    for (const w of rel.works) {
      const c = x.levels.indexOf(w.x);
      const r = y.levels.indexOf(w.y);
      if (c < 0 || r < 0) {
        console.error(`deck: ${w.id} sits outside the map axes (${w.x}, ${w.y})`);
        continue;
      }
      const key = `${c},${r}`;
      const n = cell.get(key) || 0;
      cell.set(key, n + 1);
      const cx = left + c * cw + 30;
      const cy = top + r * rh + rh / 2 + (n - 0.5) * 26;
      const g = svg("g", {
        class: w.ours ? "work ours fragment" : "work",
        tabindex: "0",
        role: "img",
        "aria-label": `${w.label}: ${w.oneLine}`,
      }, fig);
      svg("title", {}, g, `${w.label}: ${w.oneLine}`);
      svg("circle", { cx, cy, r: w.ours ? 11 : 8 }, g);
      svg("text", { x: cx + 16, y: cy + 6 }, g, w.label);
    }
    html("div", { class: "map" }, box).appendChild(fig);

    const rivals = rel.works.filter((w) => w.differs);
    if (rivals.length && box.dataset.differs !== "off") {
      const list = html("ul", { class: "differs" }, box);
      for (const w of rivals) {
        const li = html("li", { class: "fragment" }, list);
        html("b", {}, li, w.label);
        li.append(` ${w.differs}`);
      }
    }
  }

  // <div class="timeline" data-source="related">: one lane per group, one dot per work,
  // ours drawn last. Dots pop in by year when the slide opens, unless motion is reduced.
  function buildTimeline(box) {
    const rel = lookup(box.dataset.source);
    if (!usable(rel, box.dataset.source)) return;
    const works = [...rel.works].sort((a, b) => a.year - b.year);
    const groups = [...new Set(works.map((w) => w.group))];
    const y0 = works[0].year, y1 = works[works.length - 1].year;
    const W = 1100, left = 200, right = 60, lane = 70, top = 30;
    const H = top + groups.length * lane + 50;
    const px = (year) => left + ((year - y0) / Math.max(1, y1 - y0)) * (W - left - right);
    const fig = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": `Related work from ${y0} to ${y1}` });
    groups.forEach((g, i) => {
      const cy = top + i * lane + lane / 2;
      svg("line", { x1: left, x2: W - right, y1: cy, y2: cy, class: "lane" }, fig);
      svg("text", { x: left - 16, y: cy + 6, class: "axis-level", "text-anchor": "end" }, fig, g);
    });
    for (let year = y0; year <= y1; year++) {
      svg("text", { x: px(year), y: H - 12, class: "axis-level", "text-anchor": "middle" }, fig, String(year));
    }
    works.forEach((w, i) => {
      const cy = top + groups.indexOf(w.group) * lane + lane / 2;
      const g = svg("g", {
        class: w.ours ? "work ours pop" : "work pop",
        style: `--i:${i}`,
        tabindex: "0",
        role: "img",
        "aria-label": `${w.year}, ${w.label}: ${w.oneLine}`,
      }, fig);
      svg("title", {}, g, `${w.label} (${w.year}): ${w.oneLine}`);
      svg("circle", { cx: px(w.year), cy, r: w.ours ? 12 : 9 }, g);
      svg("text", { x: px(w.year), y: cy - 18, "text-anchor": "middle" }, g, w.label);
    });
    box.appendChild(fig);
  }

  function chapters() {
    const seen = new Map();
    for (const s of document.querySelectorAll(".reveal .slides section[data-chapter]")) {
      if (!seen.has(s.dataset.chapter)) seen.set(s.dataset.chapter, s);
    }
    return seen;
  }

  // <ol class="agenda" data-auto>: the chapter names, so agenda and rail never disagree.
  function buildAgenda(chs) {
    for (const ol of document.querySelectorAll("ol.agenda[data-auto]")) {
      for (const name of chs.keys()) html("li", {}, ol, name);
    }
  }

  function buildRail(chs) {
    if (!chs.size) return;
    const rail = html("nav", { class: "rail", "aria-label": "Chapters" }, document.querySelector(".reveal"));
    for (const [name, slide] of chs) {
      const b = html("button", { type: "button" }, rail, name);
      b.addEventListener("click", () => {
        const i = Reveal.getIndices(slide);
        Reveal.slide(i.h, i.v);
      });
    }
    const sync = () => {
      const current = Reveal.getCurrentSlide();
      const c = current && current.dataset.chapter;
      rail.hidden = !c;
      for (const b of rail.children) b.setAttribute("aria-current", b.textContent === c ? "step" : "false");
    };
    Reveal.on("slidechanged", sync);
    sync();
  }

  bindValues();
  buildDots();
  document.querySelectorAll(".relmap[data-source]").forEach(buildMap);
  document.querySelectorAll(".timeline[data-source]").forEach(buildTimeline);
  const chs = chapters();
  buildAgenda(chs);
  if (phone) {
    document.documentElement.classList.add("phone");
    // A wide figure keeps a readable size and pans sideways instead of shrinking its labels.
    for (const fig of document.querySelectorAll(".reveal .slides svg[viewBox]")) {
      const w = fig.viewBox.baseVal.width;
      if (w > 480) {
        fig.style.minWidth = `${Math.round(w * 0.8)}px`;
        fig.parentElement.classList.add("pan");
      }
    }
  }

  Reveal.initialize({
    hash: true,
    width: phone ? 480 : 1280,
    height: phone ? 860 : 720,
    margin: 0.04,
    center: false,
    slideNumber: "c/t",
    transition: reduce ? "none" : "fade",
    transitionSpeed: "fast",
    backgroundTransition: "none",
    autoAnimate: !reduce,
    pdfSeparateFragments: false,
    // A phone gets a portrait canvas and scroll view, and deck.css stacks the columns, so text
    // stays readable instead of a 16:9 slide shrunk to a third of its size.
    ...(phone ? { view: "scroll" } : {}),
    scrollActivationWidth: null,
    plugins: [RevealNotes],
  }).then(() => {
    if (!phone) buildRail(chs);
  });
})();
