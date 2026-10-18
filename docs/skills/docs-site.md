---
description: "Audit the Zensical docs site: nav, deploy workflow, CSS and JS assets, and link and anchor integrity."
---

# `techne:docs-site`

Audit and maintain the Zensical-powered documentation site as a build and deploy artifact: nav ordering, deploy workflow, CSS and JS assets, and link integrity across `docs/**/*.md`.

Part of [techne](../plugins/techne.md): `/plugin install techne@techne`.

## When to use

- "Does the site build and link correctly?"
- Adding a new docs page and the nav needs updating.
- Deploy workflow drifted (action version pins, build command, Pages permissions).
- Internal links or anchors are broken after a page rename.
- Assets under `docs/stylesheets/` or `docs/javascripts/` need an audit.
- A shared file (the `main.html` and footer overrides, `reveal.js`, the nav test) changed and every site needs the new copy.

## Usage

Invoke by name in Claude Code:

```
/techne:docs-site
```

The skill covers site mechanics, not prose accuracy. For prose drift (stale CLI commands, wrong paths, outdated config keys in docs), use [`techne:docsync`](docsync.md).

## Visual QA

A build that passes can still look wrong. `visual_qa.py` screenshots a served build and reports what a build cannot see:

```
uv run --quiet --no-project --with playwright==1.63.0 --with axe-playwright-python==0.1.8 --with pillow \
    python plugins/techne/skills/docs-site/scripts/visual_qa.py http://127.0.0.1:8000/<repo>/ --out qa/
```

Serve the build under its repo path, as GitHub Pages does. The script captures every sitemap page in light and dark at 1920, 1280 and 390 pixels wide in Playwright's Chromium and writes one contact sheet per page. It reports wrong-scheme surfaces, sideways scroll, AA contrast failures, broken images, page errors, unrendered markup, hidden sections, social tags written twice, code split inside a token in a table, and a table that scrolls at desktop width. It cannot see a cramped hero or a page that does not say what the project is, so open the sheets and look.

It also checks agent access and theme basics in `zensical.toml`: the `llmstxt` plugin and Copy as Markdown, a description per `llms.txt` entry, and a `media` query on each palette.

## Shared files

The files every sister site carries identically live once, in the skill's `templates/shared/`. Edit them there, then copy them into a site:

```
python3 plugins/techne/skills/docs-site/scripts/sync_shared.py <repo>
python3 plugins/techne/skills/docs-site/scripts/sync_shared.py --check <repo>
```

`--check` writes nothing and exits 1 on drift; [`techne:sisters`](sisters.md) runs it across the fleet. A site's own hand-written copy of a shared file is refused unless you pass `--force`. A site sets `extra.og_image` and `extra.brand_mark` in `zensical.toml` for its card artwork and footer mark. The shared stylesheet and script give every site the same table rules (code in a table never splits; a wide table scrolls inside its box), a 1440px layout on wide screens, and a header button that hides the side panels.

## Prerequisites

This skill reads the `## docs_site` section of `.claude/skill-context.md` for repo-specific CSS file list, JS file list, build command, site URL, and expected action pins. Without that section the skill falls back to generic defaults.

See [Conventions](../conventions.md) for the scaffolding template.

## See also

- [`techne:docsync`](docsync.md): verify prose claims (commands, paths, config keys) inside docs pages.
- [`techne:deslop`](deslop.md): clean up slop in doc prose after a site audit.
- [Conventions](../conventions.md): `## docs_site` section reference.

## Full instructions

[`SKILL.md` on GitHub](https://github.com/ajbarea/techne/blob/main/plugins/techne/skills/docs-site/SKILL.md) holds the full instructions Claude follows for this skill.
