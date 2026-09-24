// Starter talk deck for techne:slides. Copy it beside the talk as build.js, then:
//   npm i pptxgenjs && node build.js talk.pptx
// Replace the bracketed text on every slide. Delete the layouts the talk does not need.
const pptxgen = require("pptxgenjs");
const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.333 x 7.5 in
pres.title = "[Talk title]";
pres.author = "[Presenter]";

const W = 13.333, M = 0.65;
// Every text colour clears 7:1 on the background it sits on (AAA), including on cards.
const C = {
  bg: "FAFAF8", ink: "111111", body: "3A3A32", muted: "4F4F48", faint: "8A8A82",
  rule: "E4E3DB", card: "F0EFE9", blue: "00527F", orange: "8F3A00",
  dark: "111111", darkMuted: "C8C8C0", darkOrange: "F28C3C",
};
const F = "Calibri", MONO = "Consolas";

function master(name, bg, tOpts, numColor) {
  pres.defineSlideMaster({
    title: name, background: { color: bg },
    objects: [{ placeholder: { options: Object.assign({ name: "title", type: "title", fontFace: F, color: C.ink, bold: true, valign: "top", align: "left", margin: 0 }, tOpts), text: "" } }],
    slideNumber: { x: M, y: 6.95, w: 0.8, h: 0.3, fontFace: F, fontSize: 14, color: numColor },
  });
}
master("CONTENT", C.bg, { x: M, y: 0.75, w: W - 2 * M, h: 0.95, fontSize: 32 }, C.muted);
master("TITLE", C.bg, { x: M, y: 1.35, w: 10, h: 1.2, fontSize: 66, fontFace: MONO, bold: false }, C.muted);
master("STATEMENT", C.bg, { x: M, y: 1.0, w: W - 2 * M, h: 1.9, fontSize: 40 }, C.muted);
master("DISC", C.dark, { x: 0.9, y: 2.7, w: 11.2, h: 2.2, fontSize: 38, color: "FFFFFF", bold: false }, "A8A8A0");

// Every slide gets its title through the placeholder, so screen readers and the outline see it.
function base(m, t, size) {
  const s = pres.addSlide({ masterName: m });
  if (t) s.addText(t, size ? { placeholder: "title", fontSize: size } : { placeholder: "title" });
  return s;
}
// Small label above the title: "<part number> · <agenda part> · <this slide's topic>".
function kicker(s, t, color) {
  s.addText(t.toUpperCase(), {
    x: M, y: 0.4, w: W - 2 * M, h: 0.32, fontFace: F, fontSize: 14, bold: true, color: color || C.muted,
    charSpacing: 1, margin: 0, isTextBox: true,
  });
}
function text(s, t, x, y, w, h, o = {}) {
  s.addText(t, {
    x, y, w, h, fontFace: o.mono ? MONO : F, fontSize: o.size || 18, color: o.color || C.body, bold: o.bold,
    italic: o.italic, align: o.align || "left", valign: o.valign || "top", margin: 0, isTextBox: true,
    paraSpaceAfter: o.psa || 0, lineSpacingMultiple: o.lsm || 1.1,
  });
}
function box(s, x, y, w, h, fill, line) {
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x, y, w, h, rectRadius: 0.08, fill: { color: fill || C.card }, line: line ? { color: line, width: 1.25 } : { type: "none" },
  });
}
function arrow(s, x1, y1, x2, y2, color, dash) {
  s.addShape(pres.shapes.LINE, {
    x: Math.min(x1, x2), y: Math.min(y1, y2), w: Math.abs(x2 - x1), h: Math.abs(y2 - y1),
    flipH: x2 < x1, flipV: y2 < y1,
    line: { color: color || C.faint, width: 1.5, endArrowType: "triangle", dashType: dash || "solid" },
  });
}
function hline(s, x, y, w, color, dash) {
  s.addShape(pres.shapes.LINE, { x, y, w, h: 0, line: { color: color || C.rule, width: 1, dashType: dash || "solid" } });
}
// Card: bold label plus one plain line, or a short list.
function card(s, x, y, w, h, label, body, o = {}) {
  box(s, x, y, w, h, o.fill);
  s.addText([
    { text: label, options: { bold: true, color: o.labelColor || C.blue, fontSize: o.lsize || 17, breakLine: true } },
  ].concat(Array.isArray(body)
    ? body.map((b, i) => ({ text: b, options: { color: C.body, fontSize: o.bsize || 15, bullet: { indent: 16 }, breakLine: i < body.length - 1 } }))
    : [{ text: body, options: { color: C.body, fontSize: o.bsize || 15 } }]), { x: x + 0.22, y: y + 0.18, w: w - 0.44, h: h - 0.36, fontFace: F, valign: "top", margin: 0, paraSpaceAfter: 6, lineSpacingMultiple: 1.1, isTextBox: true });
}
// Muted line at the foot of a slide: a one-line definition, or the source's name for the idea.
function footnote(s, t, y) {
  text(s, t, M, y || 6.1, W - 2 * M, 0.5, { size: 15, color: C.muted });
}
function discussion(num, q, examples, script) {
  const s = base("DISC", q);
  s.addText(`DISCUSSION ${String(num).padStart(2, "0")}`, {
    x: 0.9, y: 2.2, w: 6, h: 0.35, fontFace: F, fontSize: 14, bold: true, color: C.darkOrange, charSpacing: 1, margin: 0, isTextBox: true,
  });
  text(s, examples, 0.9, 5.0, 11, 0.9, { size: 18, color: C.darkMuted });
  s.addNotes(script);
  return s;
}
function backup(tag, t) {
  const s = base("CONTENT", t, 28);
  kicker(s, "Backup · " + tag);
  return s;
}

// ---------- TITLE ----------
{
  const s = base("TITLE", "[name]");
  kicker(s, "[Venue · Track · Date]");
  text(s, "[What the work does, in one plain sentence a newcomer understands]", M, 2.75, 10.5, 0.9, { size: 26, color: C.ink });
  hline(s, M, 3.95, 1.3, C.faint);
  text(s, "[Authors]", M, 4.25, 11, 0.4, { size: 18, color: C.ink });
  text(s, "[Affiliations]", M, 4.7, 11, 0.4, { size: 15, color: C.muted });
  text(s, "[Status, for example: under submission, not for redistribution]", M, 5.95, 11, 0.35, { size: 14, color: C.orange });
  s.addNotes("[Script. The words you say out loud on this slide, first person, full sentences. For example: Hi, I'm ... Today I want to show you ... Start with one sentence that says what the work does.]");
}

// ---------- AGENDA ----------
{
  const s = base("CONTENT", "[Four parts, with three stops to talk]");
  kicker(s, "Agenda");
  const parts = [
    ["[The problem]", "[What goes wrong today, in plain words]", ""],
    ["[The idea]", "[The one move the work makes]", "Discussion 1"],
    ["[What we found]", "[What held, where it failed, what is untested]", "Discussion 2"],
    ["[What's next]", "[Where it goes, and the lessons]", "Discussion 3"],
  ];
  parts.forEach(([name, what, stop], i) => {
    const y = 1.95 + i * 1.1;
    text(s, String(i + 1), M, y, 0.6, 0.7, { size: 30, bold: true, color: C.blue });
    text(s, name, M + 0.75, y + 0.02, 3.2, 0.5, { size: 22, bold: true, color: C.ink });
    text(s, what, M + 3.9, y + 0.06, 5.35, 0.8, { size: 17 });
    if (stop) {
      box(s, 10.3, y + 0.02, 2.4, 0.5, C.dark);
      text(s, stop, 10.3, y + 0.02, 2.4, 0.5, { size: 14, bold: true, color: "FFFFFF", align: "center", valign: "middle" });
    }
    if (i < parts.length - 1) hline(s, M, y + 0.95, 12.0, C.rule);
  });
  s.addNotes("[Script: walk the room through the parts, say that the small label at the top of each slide shows which part we are in, and that the discussion questions need no background.]");
}

// ---------- CLAIM + CARDS ----------
{
  const s = base("CONTENT", "[The slide's claim, as one short sentence]");
  kicker(s, "1 · [The problem] · [Topic]");
  card(s, M, 2.1, 3.85, 2.2, "[Plain label]", "[One plain line that backs the claim.]", { bsize: 18, lsize: 20 });
  card(s, M + 4.05, 2.1, 3.85, 2.2, "[Plain label]", "[One plain line.]", { bsize: 18, lsize: 20 });
  card(s, M + 8.1, 2.1, 3.85, 2.2, "[What it costs]", "[One plain line.]", { bsize: 18, lsize: 20, labelColor: C.orange });
  text(s, "[The sentence to remember from this slide.]", M, 4.75, 12, 0.5, { size: 20, bold: true, color: C.ink });
  footnote(s, "[Term]: [what it means, in one line].", 5.45);
  footnote(s, "Paper term: [the source's name for the plain idea above].", 5.95);
  s.addNotes("[Script: say the claim, walk the three cards left to right, and say what the term means the first time you use it. End with the sentence that leads into the next slide.]");
}

// ---------- VOCABULARY ----------
{
  const s = base("CONTENT", "[Four terms the talk leans on]");
  kicker(s, "1 · [The problem] · Vocabulary");
  const terms = [
    ["[Term]", "[What it means, in everyday words.]"],
    ["[Term]", "[What it means.]"],
    ["[Acronym]", "[Spelled out: what it is.]"],
    ["[Term]", "[What it means.]"],
  ];
  const cw = 2.85, ch = 2.4, gx = 0.2;
  terms.forEach(([a, b], i) => card(s, M + i * (cw + gx), 2.1, cw, ch, a, b, { bsize: 18, lsize: 20 }));
  s.addNotes("[Script: one sentence per term, and say which one matters most for the rest of the talk.]");
}

// ---------- CONCRETE CASE, THEN THE RULE ----------
{
  const s = base("CONTENT", "[One real case shows the problem]");
  kicker(s, "1 · [The problem] · [An example]");
  const cx = 9.4, cy = 3.2;
  const sources = [["[Source A]", "[what it holds]"], ["[Source B]", "[what it holds]"], ["[Source C]", "[what it holds]"]];
  sources.forEach(([a, b], i) => {
    const y = 1.95 + i * 1.25;
    box(s, M, y, 3.4, 0.95, "FFFFFF", C.rule);
    s.addText([{ text: a, options: { bold: true, color: C.ink, fontSize: 16, breakLine: true } }, { text: b, options: { color: C.muted, fontSize: 14 } }],
      { x: M + 0.15, y: y + 0.1, w: 3.1, h: 0.75, fontFace: F, margin: 0, valign: "middle", isTextBox: true });
    arrow(s, M + 3.5, y + 0.48, cx - 0.1, cy + 0.45, C.faint, "dash");
  });
  s.addShape(pres.shapes.OVAL, { x: cx, y: cy, w: 2.2, h: 0.9, fill: { color: C.blue }, line: { type: "none" } });
  text(s, "[the one thing]", cx, cy, 2.2, 0.9, { size: 16, color: "FFFFFF", bold: true, align: "center", valign: "middle" });
  text(s, "[Name the general pattern this case stands for.]", M, 5.85, 12, 0.5, { size: 20, bold: true, color: C.ink });
  s.addNotes("[Script: tell the case as a small story first, then name the pattern it stands for.]");
}

// ---------- DISCUSSION ----------
discussion(1, "[A short personal question anyone can answer without the paper?]",
  "[Two or three example answers to get the room started?]",
  "[Script: read the question, give one example answer of your own, take two or three from the room, then close with the sentence that ties it back to the talk.]");

// ---------- LIMITS ----------
{
  const s = base("CONTENT", "[What the evidence shows, and what it does not yet]");
  kicker(s, "3 · [What we found] · Limits");
  card(s, M, 2.0, 5.9, 2.6, "What we tested", ["[Plain line]", "[Plain line]"], { bsize: 20, lsize: 22 });
  card(s, 6.8, 2.0, 5.9, 2.6, "What we have not tested yet", ["[Plain line]", "[Plain line]"], { bsize: 20, lsize: 22, labelColor: C.orange });
  text(s, "[What it would take to test the rest.]", M, 5.0, 12, 0.5, { size: 19, bold: true, color: C.ink });
  s.addNotes("[Script: say the limits plainly, in your own words.]");
}

// ---------- CLOSING ----------
{
  const s = base("STATEMENT", "[The one message to remember, as a contrast:\nnot this, but this]");
  hline(s, M, 3.4, 1.3, C.faint);
  text(s, "WHAT CARRIES OVER", M, 3.7, 6, 0.3, { size: 14, bold: true, color: C.muted });
  const P = ["[Lesson that applies beyond this project]", "[Lesson]", "[Lesson]"];
  s.addText(P.map((t, i) => ({ text: t, options: { bullet: true, breakLine: i < P.length - 1 } })),
    { x: M, y: 4.1, w: 12, h: 2.0, fontFace: F, fontSize: 20, color: C.ink, paraSpaceAfter: 6, margin: 0, isTextBox: true, valign: "top" });
  s.addNotes("[Script: say the closing contrast, then thank the room and invite questions.]");
}

// ---------- BACKUP ----------
{
  const s = base("CONTENT", "Backup slides");
  kicker(s, "For questions only");
  text(s, "[The numbers behind each claim.]", M, 1.9, 12, 0.5, { size: 18, color: C.muted });
}
{
  const s = backup("[Source table]", "[What the table shows, as a claim]");
  const hdr = ["[Column]", "[Column]", "[Column]"].map((t) => ({ text: t, options: { bold: true, color: C.ink } }));
  const rows = [["[row]", "[value]", "[value]"], ["[row]", "[value]", "[value]"]];
  s.addTable([hdr, ...rows.map((r) => r.map((t) => ({ text: t, options: { color: C.body } })))], {
    x: M, y: 1.8, w: 7.8, colW: [3.0, 2.4, 2.4], fontFace: F, fontSize: 16, rowH: 0.5,
    border: { type: "solid", pt: 0.5, color: C.rule }, margin: [0.06, 0.12, 0.06, 0.12], // inches, not points
  });
}

pres.writeFile({ fileName: process.argv[2] || "talk.pptx" });
