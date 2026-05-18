# Configuration

## `~/.claude/techne.toml`

`techne:sisters` (and any future cross-repo skill) reads `~/.claude/techne.toml` at runtime. User-controlled config that lists the active sister repos to compare against.

### Schema

```toml
github_user = "ajbarea"
workspace_root = "/home/ajbar/ajsoftworks"

[[sisters]]
name = "phalanx-fl"
status = "active"

[[sisters]]
name = "vFL"
status = "active"

[[sisters]]
name = "kourai-khryseai"
status = "active"
```

### Fields

| Field | Type | Required | Notes |
|---|---|---|---|
| `github_user` | string | yes | Your GitHub username; used to construct repo URLs. |
| `workspace_root` | string | yes | Absolute path to the parent directory containing your sister repos. |
| `sisters[].name` | string | yes | Directory name under `workspace_root`. |
| `sisters[].status` | string | no | Defaults to `"active"`. Set to `"backburner"` to skip without removing. |

### Status semantics

- **`active`**: included in cross-repo audits, drift checks, sync sweeps.
- **`backburner`**: skipped but not deleted. Used for repos you want to remember without actively maintaining.

## Per-skill configuration

Most skills read additional repo-local config when needed (e.g. `techne:audit` looks for a `Makefile`; `techne:docs-site` looks for `zensical.toml`). See each skill's page for specifics.

## How it fits together

```
~/.claude/techne.toml      ← user-controlled sister-repo registry
~/.claude/plugins/...      ← installed techne skills
<repo>/.claude/...         ← per-repo overrides (skill-context, etc.)
<repo>/Makefile, logs/, zensical.toml, ... ← what individual skills read
```
