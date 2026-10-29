Part of #183.

**Why:** AJ talks only to Heph, but every worker runs keryx, so each one speaks and loads the summarizer and voice models.

**What changed**

| Session | keryx |
|---|---|
| Heph (started without worker settings) | on, as before |
| every worker | off: `KERYX_ENABLED=false` in `worker-settings.json` `env` |

Takes effect at each worker's next launch.

**Status:** ready for review. The wall's Voices setting (Heph only / Everyone / Off) follows in its own PR.

| Check | Result |
|---|---|
| `claude -p --settings` with that `env` | the session's command saw `KERYX_ENABLED=false` |

<details><summary>Details</summary>

- keryx's hook returns before contacting its daemon when `KERYX_ENABLED` is off (keryx `src/keryx/__main__.py:143`), and the environment overrides its config file (`__main__.py:175`).
- Claude Code applies a settings file's `env` to every session started with it ([settings docs](https://code.claude.com/docs/en/settings#environment-variables)).
- `fleet/test_fleet.sh` asserts the installed worker settings carry it.
</details>

