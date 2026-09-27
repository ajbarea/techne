# `techne:docs-site`

Audit and maintain the Zensical-powered documentation site as a build and deploy artifact: nav ordering, deploy workflow, CSS and JS assets, and link integrity across `docs/**/*.md`.

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

## Shared files

The files every sister site carries identically live once, in the skill's `templates/shared/`. Edit them there, then copy them into a site:

```
uv run --quiet python plugins/techne/skills/docs-site/scripts/sync_shared.py <repo>
uv run --quiet python plugins/techne/skills/docs-site/scripts/sync_shared.py --check <repo>
```

`--check` writes nothing and exits 1 on drift; [`techne:sisters`](sisters.md) runs it across the fleet. A site sets `extra.og_image` and `extra.brand_mark` in `zensical.toml` for its card artwork and footer mark.

## Prerequisites

This skill reads the `## docs_site` section of `.claude/skill-context.md` for repo-specific CSS file list, JS file list, build command, site URL, and expected action pins. Without that section the skill falls back to generic defaults.

See [Conventions](../conventions.md) for the scaffolding template.

## See also

- [`techne:docsync`](docsync.md): verify prose claims (commands, paths, config keys) inside docs pages.
- [`techne:deslop`](deslop.md): clean up slop in doc prose after a site audit.
- [Conventions](../conventions.md): `## docs_site` section reference.
