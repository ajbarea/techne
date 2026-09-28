"""Screenshot a Zensical site in both schemes at desktop and phone width, and measure it.

    uv run --quiet --no-project --with playwright --with pillow \\
        python visual_qa.py http://127.0.0.1:8000/ --out qa/ [--pages 12] [--path getting-started/]

Every page in the sitemap (or the --path list) is loaded in light and dark at 1280 and 390
wide, scrolled so reveals and lazy images fire, and captured full-page. One contact sheet per
page puts the four captures side by side; report.json and the printed summary carry what the
eye misses:

- a dark surface in light mode, or a light one in dark mode (area over 5000 px2)
- sideways scroll at phone width
- text under the WCAG AA contrast ratio (axe-core's color-contrast rule)
- broken images, page errors, failed same-origin requests
- markup that did not render: attr-list braces, :icon: shortcodes, admonition bangs, raw math
- landing sections still invisible after scrolling

Uses the system Chrome (channel="chrome"), so nothing is downloaded but the Python packages
and axe-core from jsdelivr.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

from PIL import Image  # ty: ignore[unresolved-import]
from playwright.sync_api import Page, sync_playwright  # ty: ignore[unresolved-import]

AXE = "https://cdn.jsdelivr.net/npm/axe-core@4.13.0/axe.min.js"
VIEWPORTS = {"desktop": (1280, 800), "phone": (390, 844)}
SCHEMES = {"light": "default", "dark": "slate"}
SHEET_HEIGHT = 3200

MEASURE = r"""
() => {
  const probe = document.createElement("canvas").getContext("2d");
  const rgba = (c) => {
    probe.fillStyle = "#000"; probe.fillStyle = c;
    probe.fillRect(0, 0, 1, 1);
    probe.clearRect(0, 0, 1, 1); probe.fillStyle = c; probe.fillRect(0, 0, 1, 1);
    const [r, g, b, a] = probe.getImageData(0, 0, 1, 1).data;
    return [r, g, b, a / 255];
  };
  const lum = ([r, g, b]) => [r, g, b].map((v) => {
    v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  }).reduce((s, v, i) => s + v * [0.2126, 0.7152, 0.0722][i], 0);
  const scheme = document.body.getAttribute("data-md-color-scheme");
  const surfaces = [];
  for (const el of document.querySelectorAll("body *")) {
    const cs = getComputedStyle(el);
    if (cs.display === "none" || cs.visibility === "hidden" || +cs.opacity === 0) continue;
    const box = el.getBoundingClientRect();
    if (box.width * box.height < 5000 || box.width < 40 || box.height < 24) continue;
    const c = rgba(cs.backgroundColor);
    if (c[3] < 0.6) continue;
    const L = lum(c);
    const wrong = scheme === "slate" ? L > 0.6 : L < 0.08;
    if (wrong && !el.closest(".md-button, button, code, pre, img, video, canvas, svg"))
      surfaces.push(`${el.tagName.toLowerCase()}.${[...el.classList].slice(0, 2).join(".")} ` +
        `${Math.round(box.width)}x${Math.round(box.height)} ${cs.backgroundColor}`);
  }
  const main = document.querySelector(".md-content") || document.body;
  const text = main.innerText;
  const raw = [
    [/\{\s*\.[a-z][\w-]*[^}\n]*\}/, "attr-list braces"],
    [/:(octicons|material|fontawesome|simple)-[a-z0-9-]+:/, "icon shortcode"],
    [/^!!!\s/m, "admonition bang"],
  ].filter(([re]) => re.test(text)).map(([, name]) => name);
  const math = [...main.querySelectorAll(".arithmatex")]
    .filter((e) => !e.querySelector(".katex, mjx-container")).length;
  if (math) raw.push(`${math} unrendered math`);
  return {
    scheme,
    overflow: document.scrollingElement.scrollWidth - window.innerWidth,
    surfaces: [...new Set(surfaces)].slice(0, 6),
    raw,
    brokenImages: [...document.images].filter((i) => i.complete && i.naturalWidth === 0)
      .map((i) => i.getAttribute("src")),
    hiddenSections: [...document.querySelectorAll(".landing-section")]
      .filter((s) => +getComputedStyle(s).opacity < 0.1).length,
  };
}
"""


def sitemap_paths(base: str) -> list[str]:
    """Page paths relative to the site root, wherever the build is being served.

    The sitemap lists deployed URLs (https://host/repo/page/); the shortest one is the root,
    so every page path is its URL minus that root.
    """
    with urllib.request.urlopen(base + "sitemap.xml", timeout=20) as r:
        locs = re.findall(r"<loc>([^<]+)</loc>", r.read().decode())
    if not locs:
        return [""]
    root = min(locs, key=len)
    return [loc[len(root) :] if loc.startswith(root) else "" for loc in locs]


def schemes_offered(page: Page) -> list[str]:
    offered = page.evaluate(
        "() => [...document.querySelectorAll('[data-md-color-scheme]')]"
        ".map(e => e.getAttribute('data-md-color-scheme'))"
        ".concat([...document.querySelectorAll('input[name=__palette]')]"
        ".map(i => i.getAttribute('data-md-color-scheme')))"
    )
    names = [k for k, v in SCHEMES.items() if v in offered]
    return names or ["light"]


def capture(page: Page, url: str, scheme: str, errors: list[str]) -> dict:
    page.goto(url, wait_until="networkidle", timeout=45000)
    page.evaluate(
        "(s) => { document.body.setAttribute('data-md-color-scheme', s); }", SCHEMES[scheme]
    )
    page.evaluate(
        """async () => {
          for (let y = 0; y < document.body.scrollHeight; y += 300) {
            window.scrollTo(0, y); await new Promise((r) => setTimeout(r, 120));
          }
          window.scrollTo(0, 0); await new Promise((r) => setTimeout(r, 600));
        }"""
    )
    found = page.evaluate(MEASURE)
    try:
        page.add_script_tag(url=AXE)
        axe = page.evaluate(
            """async () => (await axe.run(document, { runOnly: ["color-contrast"] }))
              .violations.flatMap((v) => v.nodes.map((n) => n.target.join(" ")))"""
        )
    except Exception as exc:  # a CSP or offline run still gets the rest
        axe = [f"axe unavailable: {exc.__class__.__name__}"]
    found["contrast"] = axe[:8]
    found["contrastCount"] = len(axe)
    found["errors"] = sorted(set(errors))[:6]
    return found


def sheet(shots: list[Path], out: Path) -> None:
    images = [Image.open(p) for p in shots]
    scale = [min(1.0, 640 / im.width) if im.width > 640 else 1.0 for im in images]
    tiles = [
        im.crop((0, 0, im.width, min(im.height, int(SHEET_HEIGHT / s)))).resize(
            (int(im.width * s), int(min(im.height, SHEET_HEIGHT / s) * s))
        )
        for im, s in zip(images, scale, strict=True)
    ]
    width = sum(t.width for t in tiles) + 16 * (len(tiles) - 1)
    canvas = Image.new("RGB", (width, max(t.height for t in tiles)), (128, 128, 128))
    x = 0
    for t in tiles:
        canvas.paste(t, (x, 0))
        x += t.width + 16
    canvas.save(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("base", help="site root URL, with trailing slash")
    parser.add_argument("--out", type=Path, default=Path("qa"))
    parser.add_argument("--path", action="append", help="page path under the root; repeatable")
    parser.add_argument("--pages", type=int, default=0, help="first N sitemap pages only")
    args = parser.parse_args()
    base = args.base if args.base.endswith("/") else args.base + "/"
    paths = args.path or sitemap_paths(base)
    if args.pages:
        paths = paths[: args.pages]
    args.out.mkdir(parents=True, exist_ok=True)
    found_origin = re.match(r"https?://[^/]+", base)
    if not found_origin:
        parser.error("base must be an http(s) URL")
    origin = found_origin.group(0)

    report: dict[str, dict] = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome")
        for path in paths:
            slug = path.strip("/").replace("/", "_") or "home"
            shots: list[Path] = []
            probe = browser.new_page()
            probe.goto(base + path, wait_until="domcontentloaded")
            offered = schemes_offered(probe)
            probe.close()
            for scheme in offered:
                for device, (w, h) in VIEWPORTS.items():
                    ctx = browser.new_context(
                        viewport={"width": w, "height": h},
                        color_scheme="dark" if scheme == "dark" else "light",
                        is_mobile=device == "phone",
                        has_touch=device == "phone",
                    )
                    page = ctx.new_page()
                    errors: list[str] = []
                    page.on("pageerror", lambda e, errs=errors: errs.append(str(e)[:120]))
                    page.on(
                        "response",
                        lambda r, errs=errors: (
                            r.status >= 400
                            and r.url.startswith(origin)
                            and errs.append(f"{r.status} {r.url[len(origin) :]}")
                        ),
                    )
                    shot = args.out / f"{slug}-{scheme}-{device}.png"
                    try:
                        found = capture(page, base + path, scheme, errors)
                        # Frozen animations: a particle canvas redraws every frame, and a
                        # full-page capture of a moving page never settles.
                        page.screenshot(
                            path=str(shot), full_page=True, animations="disabled", timeout=90000
                        )
                        shots.append(shot)
                    except Exception as exc:  # one bad page must not end the run
                        found = {"errors": [f"capture failed: {exc.__class__.__name__}"]}
                    report[f"{path or '/'} {scheme} {device}"] = found
                    ctx.close()
            if shots:
                sheet(shots, args.out / f"{slug}-sheet.png")
        browser.close()

    (args.out / "report.json").write_text(json.dumps(report, indent=2))
    problems = 0
    for key, f in report.items():
        issues = []
        if f.get("overflow", 0) > 1:
            issues.append(f"scrolls sideways by {f['overflow']}px")
        if f.get("surfaces"):
            issues.append(f"wrong-scheme surfaces {f['surfaces']}")
        if f.get("contrastCount"):
            issues.append(f"{f['contrastCount']} low-contrast {f['contrast'][:3]}")
        for name in ("raw", "brokenImages", "errors"):
            if f.get(name):
                issues.append(f"{name} {f[name]}")
        if f.get("hiddenSections"):
            issues.append(f"{f['hiddenSections']} sections left hidden")
        if issues:
            problems += 1
            print(f"{key}: " + "; ".join(issues))
    print(f"{len(report)} captures, {problems} with findings; sheets in {args.out}/")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
