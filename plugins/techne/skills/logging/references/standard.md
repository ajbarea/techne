<!-- budget: 1800 words -->
# Logging standard

What a repo's logs must do so that a bug can be found from the logs alone, on a laptop and in a
CI run. `scripts/logcheck.py` checks the parts a program can check; the rest is what a reviewer
reads for. Sources are listed at the end; each was read on 2026-10-26 or 2026-10-28.

`# research(2026-10)`

## Where this lives, and why

The standard is a skill of its own, `techne:logging`, next to the other quality checks: comments
have `deslop`, documentation has `docsync`, tests have `audit`. A logging review reads source
code, linter configs and workflow files, on any branch and before CI runs, so it does not fit
`ci-audit`, which reads one finished run's log. `sisters` runs the same script across every
sister (its check 16), and `ci-audit` points at this file when a failed run's log does not name
the cause. One script and one rule list serve all three, so a rule cannot drift between them.

Code-level rules belong to each stack's own linter, which already runs in `make lint` and CI:
ruff's `G` and `LOG` families, clippy's print lints, ESLint's `no-console` or Biome's
`noConsole`. The script checks that those gates are switched on and covers what no linter
checks: secrets reaching a log call, log files without a cap, error text on stdout, CI logs that
vanish with the runner, and committed log files.

## Every stack

- **Two audiences, two outputs.** A CLI prints its results to stdout for the user. Diagnostics go
  to stderr, or to a log file, never mixed into stdout.
- **Structured in files, readable on a terminal.** A log file holds one JSON object per line, so
  a script or an agent can filter it. A terminal shows the same events as plain lines. OWASP:
  "Do not use unstructured text log formats."
- **Every event says when, where, who and what** (OWASP): a UTC timestamp, the logger or module,
  the run or session id, the event and its outcome. A message names the value that was wrong and
  what was expected, not only that something failed.
- **Levels:**

  | Level | Belongs here | Example |
  |---|---|---|
  | DEBUG | Detail for diagnosing one problem; off by default | the request sent, the branch taken |
  | INFO | The program doing what it should, once per unit of work | "synced 12 repos in 4.1 s" |
  | WARNING | Unexpected, but the work continues | a retry, a fallback, a deprecated key |
  | ERROR | One piece of work failed; the program goes on | a repo that could not be read |
  | CRITICAL | The program cannot continue | the config does not parse |

  An exception is logged once, where it is handled, with its traceback; a function that re-raises
  does not also log it.
- **Never log a secret.** Passwords, tokens, API keys, auth session tokens, connection strings,
  keys and cookies are removed, masked or hashed before they reach a log call (OWASP; CWE-532).
  A run or Claude Code session id is a correlation id, not a credential, and is logged. Log a
  length, a fingerprint or `set`/`unset` instead. Personal data (names, email addresses, file
  paths under a home folder) is logged only when the event needs it. User input is length-capped
  and has CR and LF escaped, which a JSON encoder does.
- **One id across processes.** A run that spans processes (a hook, a CLI, a backend) carries one
  id in every line. When OpenTelemetry is in use, that is the W3C `traceparent` trace id, passed
  to a child process in the `TRACEPARENT` environment variable (OpenTelemetry's environment
  carrier spec, a release candidate). Without it, generate one id at the entry point, pass it
  down in an environment variable named after the repo (`KLEPSYDRA_RUN_ID`), and log it as
  `run_id`. A Claude Code hook already has `session_id` in its input; log that.
- **Files have a cap.** A log file rotates by size or by time and keeps a fixed number of old
  files. Nothing is kept forever.
- **Logs never enter git.** `*.log` and the log folder are in `.gitignore`.

## Where log files go

| OS | User log folder | Python (`platformdirs.user_log_dir`) |
|---|---|---|
| Linux, WSL | `$XDG_STATE_HOME/<app>/log`, default `~/.local/state/<app>/log` | same |
| macOS | `~/Library/Logs/<app>` | same |
| Windows | `%LOCALAPPDATA%\<app>\Logs` | `%LOCALAPPDATA%\<author>\<app>\Logs` |

The XDG spec names logs as state data. On WSL, a Linux program writes to the Linux file system,
not the mounted Windows drive, which is slower across the boundary (Microsoft's WSL guidance). A Tauri app's
`LogDir` target uses `%LOCALAPPDATA%\<bundle id>\logs` on Windows, `~/.local/share/<bundle
id>/logs` on Linux and `~/Library/Logs/<bundle id>` on macOS. A repo's own development runs
write to `logs/` in the repo (the dev-runner convention), ignored by git and pruned after 30
days by `make clean`.

## Python

- **stdlib `logging` by default; structlog when a service needs bound context** (a request or
  run id carried into every line). structlog 26.1 recommends JSON in production and pretty
  output when stderr is a terminal, and logging to stdout or stderr for a supervisor to collect.
- `logger = logging.getLogger(__name__)` in every module. A library adds only a `NullHandler`
  and never logs to the root logger; the application configures handlers once, at its entry
  point.
- Pass values as arguments, `logger.info("synced %d repos", n)`, so formatting is deferred and
  a structured handler keeps the fields apart. Use `logger.exception` inside `except`.
- ruff selects `G` and `LOG`: they reject f-strings and `.format` in log calls (G001 to G004),
  `warn` (G010), root-logger calls (LOG015), and `exception` outside a handler (LOG004) or
  with `exc_info=False` (LOG007). → `lint-python`.
- A file handler is `RotatingFileHandler(maxBytes=..., backupCount=...)`, with both set: if
  either is 0, it never rotates. `TimedRotatingFileHandler` needs `backupCount`. A plain
  `FileHandler` or `basicConfig(filename=...)` grows without a cap. `WatchedFileHandler` is
  for a file that `logrotate` rotates. → `unbounded-log-file`.
- A slow handler (network, email) sits behind `QueueHandler` and `QueueListener`.
- A script without a logger prints a refusal or warning with `print(..., file=sys.stderr)`. A
  `print()` to stdout in the run of prints right before `return 1`, `sys.exit(1)` or
  `raise SystemExit(1)` is the failure's message on the wrong stream. A checker's findings
  are its result and stay on stdout, with a `logcheck: ignore` saying so.
  → `stderr-for-errors`.

## Rust

- `tracing` with `tracing-subscriber` (0.3.23): an `EnvFilter` read from `RUST_LOG`, a
  plain-text layer on stderr and a JSON layer for the file.
- Files through `tracing-appender` (0.2.5): `RollingFileAppender::builder()` with a rotation and
  `.max_log_files(n)` and a rotation other than `Rotation::NEVER`. The `rolling::daily()` style
  constructors keep every file, and the appender has no size-based rotation. Keep the non-blocking writer's guard alive until exit, or
  the last lines are lost. → `unbounded-log-file`.
- A Tauri app may use `tauri-plugin-log` (2.10.1, built on the `log` crate) instead; then set
  `max_file_size` and `RotationStrategy::KeepSome(n)`, since `KeepAll` keeps every file.
  `tracing` events reach it only through a bridge.
- Under `[lints.clippy]`, `print_stdout`, `print_stderr` and `dbg_macro` are `warn`, so a stray
  `eprintln!` fails lint; a CLI's usage text takes an `#[allow]` where it prints. Set
  `allow-print-in-tests` and `allow-dbg-in-tests` in `clippy.toml`. → `lint-rust`.

## TypeScript and JavaScript

- Raw `console.log`, `console.info` and `console.debug` do not ship to a browser (ESLint
  `no-console`). Turn on `no-console` with `allow: ["warn", "error"]`, or Biome's
  `noConsole` (off by default). → `lint-js`.
- The app logs through one small level-gated module: debug lines appear in development and are
  dropped from production builds; `warn` and `error` stay. A Node service uses pino, whose
  `redact` paths do not work in a browser, so browser code removes secrets before the call.
- A Tauri front end sends its lines to the backend log with `@tauri-apps/plugin-log`, so one
  file holds both sides.

## Shell

- Error and warning text goes to stderr, `echo "error: ..." >&2`, through one `err()` helper
  (Google's shell style guide). The check reads text that starts `error:`, `FAIL:` or the like,
  and any `echo` or `printf` right before `exit N` with N non-zero, on the same line or the
  next. → `stderr-for-errors`.
- A script that runs in CI prints its own errors as annotations (below).
- A secret is never echoed. Shell secrets are environment variables, named in capitals; the
  check reads only those. Piping one to a command (`printf '%s' "$TOKEN" | gh auth login
  --with-token`) or writing it to `$GITHUB_ENV` is fine. → `secret-in-log`.
- `set -x` is off in any script that handles a secret.

## GitHub Actions

- **Annotations name the cause.** A step reports a failure with
  `::error file=<path>,line=<n>,title=<short>::<message>`, which shows on the run summary and
  the PR's changed lines. Tools that can emit them should: `logcheck.py --format github`, and
  ruff through `RUFF_OUTPUT_FORMAT: github` in the workflow's `env:` (ruff 0.16 and later apply
  it to `format --check` too), so each step stays the command `make lint` runs locally.
  → in a workflow, `stderr-for-errors` asks for `::error::`.
- **Groups keep the log readable.** Wrap long output in `::group::<title>` and `::endgroup::`.
- **Masking.** `::add-mask::<value>` before a value derived from a secret is printed; each value
  is masked once per job. Never `echo` a secret, masked or not. → `secret-in-log`.
- **Debug on demand.** Extra detail goes to `::debug::`, shown when the `ACTIONS_STEP_DEBUG`
  secret is `true`, or when a run is re-run with debug logging; it is not printed by default.
- **Logs outlive the runner.** A job that writes a log file uploads it with
  `actions/upload-artifact` (v7) under `if: failure()` (or `always()`), with a
  `retention-days` short enough for the repo's storage. Run logs and artifacts are kept 90 days
  by default. → `ci-logs-not-uploaded`.
- **Step summaries** (`$GITHUB_STEP_SUMMARY`) hold a short table of results: at most 1 MiB per
  step, and 20 per job are shown.
- **Skips are visible.** pytest runs with `-ra`, so each skip reason is in the log next to the
  failures, and an audit can count skips. `-rs` alone replaces pytest's default `fE` and drops
  the FAILED lines from the short summary (pytest 9.1).

## Sources

- OWASP Logging Cheat Sheet: https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html
- Python logging HOWTO (3.15): https://docs.python.org/3/howto/logging.html
- Python logging handlers: https://docs.python.org/3/library/logging.handlers.html
- structlog 26.1.0, logging best practices: https://www.structlog.org/en/stable/logging-best-practices.html
- ruff rules, flake8-logging and flake8-logging-format: https://docs.astral.sh/ruff/rules/
- ruff CLI, `RUFF_OUTPUT_FORMAT`: https://docs.astral.sh/ruff/configuration/#full-command-line-interface
- pytest output, `-r` summary characters: https://docs.pytest.org/en/stable/how-to/output.html
- platformdirs platform paths: https://platformdirs.readthedocs.io/en/latest/platforms.html
- XDG Base Directory spec 0.8: https://specifications.freedesktop.org/basedir/latest/
- Microsoft, WSL file systems: https://learn.microsoft.com/en-us/windows/wsl/filesystems
- tracing-appender 0.2.5 Builder: https://docs.rs/tracing-appender/latest/tracing_appender/rolling/struct.Builder.html
- tracing-subscriber 0.3.23 EnvFilter: https://docs.rs/tracing-subscriber/latest/tracing_subscriber/filter/struct.EnvFilter.html
- Tauri logging plugin: https://v2.tauri.app/plugin/logging/
- tauri-plugin-log 2.10.1 RotationStrategy: https://docs.rs/tauri-plugin-log/latest/tauri_plugin_log/enum.RotationStrategy.html
- Cargo `[lints]`: https://doc.rust-lang.org/cargo/reference/manifest.html#the-lints-section
- ESLint no-console: https://eslint.org/docs/rules/no-console
- Biome noConsole: https://biomejs.dev/linter/rules/no-console/
- pino redaction (10.3.1): https://cdn.jsdelivr.net/npm/pino@10.3.1/docs/redaction.md
- Google shell style guide: https://google.github.io/styleguide/shellguide.html
- GitHub workflow commands: https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-commands
- actions/upload-artifact: https://github.com/actions/upload-artifact
- GitHub artifact and log retention: https://docs.github.com/en/organizations/managing-organization-settings/configuring-the-retention-period-for-github-actions-artifacts-and-logs-in-your-organization
- W3C Trace Context: https://www.w3.org/TR/trace-context/
- OpenTelemetry environment variables as context carriers: https://opentelemetry.io/docs/specs/otel/context/env-carriers/
