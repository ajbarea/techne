# keryx

keryx speaks a one- or two-sentence gist of each Claude Code reply in a local voice, shortened by a local Ollama model. It runs on WSL2 under Windows, and lives in its own repository, [ajbarea/keryx](https://github.com/ajbarea/keryx).

## Install

```bash
/plugin marketplace add ajbarea/techne
/plugin install keryx@techne
```

keryx needs uv, Ollama with its summarizer model, and Windows audio through `powershell.exe`. Run `keryx status` to check setup: it prints each check with its fix. The [keryx docs](https://ajbarea.github.io/keryx/) cover commands and troubleshooting, and Claude can follow its [setup runbook](https://github.com/ajbarea/keryx/blob/main/AGENTS.md).
