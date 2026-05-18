# `techne:docs-site`

Maintains the Zensical-powered documentation site: nav ordering in `zensical.toml`, the docs GitHub Pages workflow, CSS and JS assets, and link/anchor integrity across `docs/**/*.md`.

## When to use

- Site config or theme needs an audit.
- Deploy workflow drifted.
- Cross-page links or anchors are broken.
- Adding a new page and the nav needs updating.

## Scope

Site mechanics, not prose. For prose accuracy, see [`techne:docsync`](docsync.md).

## What it audits

- `zensical.toml` nav structure (does every linked file exist?).
- `.github/workflows/docs.yml` (Pages deploy still healthy?).
- `docs/stylesheets/`, `docs/javascripts/` (referenced assets resolve?).
- Internal links and anchors across `docs/**/*.md`.

## What it fixes

- Stale nav entries pointing at moved/deleted pages.
- Broken cross-page links and dead anchors.
- Workflow YAML drift (action version pins, output paths).

## Reads

- `<repo>/zensical.toml`
- `<repo>/docs/**/*.md`
- `<repo>/docs/{stylesheets,javascripts,assets}/`
- `<repo>/.github/workflows/docs.yml`
