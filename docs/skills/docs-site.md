# `techne:docs-site`

Maintains the Zensical-powered documentation site: nav ordering in `zensical.toml`, the docs GitHub Pages workflow, CSS and JS assets, and link/anchor integrity across `docs/**/*.md`.

## When to use

- Site config or theme needs an audit.
- Deploy workflow drifted from the template.
- Cross-page links or anchors are broken.
- Adding a new page and the nav needs updating.
- Colors, fonts, or CSS overrides aren't rendering correctly.

## Scope

**Site mechanics**, not prose. For prose accuracy, see [`techne:docsync`](docsync.md).

Covers:
- `zensical.toml` nav structure and config
- `.github/workflows/docs.yml` deploy health
- `docs/stylesheets/`, `docs/javascripts/` asset integrity
- Internal links and anchors across `docs/**/*.md`
- Theme variables and color palette consistency

## Usage

```bash
# Full site audit
techne:docs-site

# Audit specific aspect
techne:docs-site --links-only
techne:docs-site --config-only
techne:docs-site --theme-only
```

## Configuration

Optional `.claude/skill-context.md`:

```yaml
docs-site:
  site_name: "techne"
  check_external_links: false  # only check internal links
  ignore_paths:
    - "docs/superpowers/plans/**"
    - "docs/superpowers/specs/**"
```

## What it audits

- **Nav structure**: does every linked file in `zensical.toml` exist? Is the hierarchy correct?
- **Deploy workflow**: `actions/checkout`, `actions/setup-python`, action versions up-to-date?
- **Assets**: CSS/JS files referenced in `zensical.toml` present and syntactically valid?
- **Links**: internal cross-page links and anchor refs work without 404s.
- **Theme**: color variables defined, fonts loaded, dark/light mode consistent.

## What it fixes

- Stale nav entries pointing at moved/deleted pages.
- Broken cross-page links and dead anchors.
- Workflow YAML drift (action version pins, output paths).
- Missing or misnamed CSS/JS files.

## Troubleshooting

**"Anchor not found"**: The markdown section heading may have changed. The skill will suggest the correct anchor or allow you to update manually.

**"CSS not loading"**: Check that the path in `zensical.toml` `extra_css` matches the actual file location relative to `docs/`.

**"Deploy failed after my changes"**: Run `techne:docs-site` to audit the workflow and config. The skill will surface and fix YAML issues.

## See also

- [`techne:docsync`](docsync.md) — verify prose accuracy (commands, paths, config keys in docs).
- [`techne:deslop`](deslop.md) — clean up slop in markdown and docstrings.

## Reads

- `<repo>/zensical.toml`
- `<repo>/docs/**/*.md`
- `<repo>/docs/{stylesheets,javascripts,assets}/`
- `<repo>/.github/workflows/docs.yml`
