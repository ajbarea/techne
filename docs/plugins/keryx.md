---
description: keryx plugin, a spoken gist of each Claude Code reply in a local voice. Runs on WSL2 under Windows and lives in its own repository.
---

# keryx

keryx speaks a one- or two-sentence gist of each Claude Code reply in a local voice, shortened by a local Ollama model. It lives in its own repository, [ajbarea/keryx](https://github.com/ajbarea/keryx), and its skill (`keryx:pronounce`, which teaches it how to say a word) is documented there.

## Use it when

You want each reply read aloud while you work, on WSL2 under Windows.

## Install

```text
/plugin marketplace add ajbarea/techne
/plugin install keryx@techne
```

## Needs

WSL2 on Windows, uv, Ollama with its summarizer model, and Windows audio through `powershell.exe`.

## Set up

Run `keryx status`. It prints each check with its fix. The [keryx docs](https://ajbarea.github.io/keryx/) cover commands and troubleshooting, and Claude can follow its [setup runbook](https://github.com/ajbarea/keryx/blob/main/AGENTS.md).

## Skills

| Skill | Use it to |
|---|---|
| `keryx:pronounce` | Teach keryx how to say a word it mispronounces, such as a repo name. See the [keryx docs](https://ajbarea.github.io/keryx/). |

## Troubleshooting

The [keryx docs](https://ajbarea.github.io/keryx/) list the commands and fixes. Run `keryx status` first.
