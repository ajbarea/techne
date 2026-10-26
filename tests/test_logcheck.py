"""Tests for techne:logging's check, logcheck.py.

Each test builds a real git repository, since the check reads tracked files only, and asserts
on the rule ids the check reports. A rule is tested on the input that should trip it and on the
nearest input that should not, so a rule that cannot fail shows up as a red test.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import LOGCHECK_SCRIPT

GOOD_RUFF = '[tool.ruff.lint]\nselect = ["E", "G", "LOG"]\n'
GOOD_CARGO = (
    '[package]\nname = "x"\nversion = "0.1.0"\n\n[lints.clippy]\n'
    'print_stdout = "warn"\nprint_stderr = "warn"\ndbg_macro = "warn"\n'
)
GOOD_ESLINT = (
    "export default [{ rules: { 'no-console': ['error', { allow: ['warn', 'error'] }] } }];\n"
)


def make_repo(tmp_path: Path, files: dict[str, str], name: str = "r") -> Path:
    root = tmp_path / name
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    if files:
        subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    return root


def run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(LOGCHECK_SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=root,
        check=False,
    )


def findings(tmp_path: Path, files: dict[str, str]) -> list[tuple[str, int, str]]:
    """(path, line, rule) per finding, from the JSON output."""
    root = make_repo(tmp_path, files)
    out = run(root, "--format", "json")
    assert out.returncode in (0, 1), out.stderr
    return [(f["path"], f["line"], f["rule"]) for f in json.loads(out.stdout)]


def rules(tmp_path: Path, files: dict[str, str]) -> list[str]:
    return [rule for _, _, rule in findings(tmp_path, files)]


# --- lint-python: ruff selects the G and LOG families ---------------------------------------


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        ({"pyproject.toml": GOOD_RUFF}, []),
        ({"pyproject.toml": '[tool.ruff.lint]\nextend-select = ["G", "LOG"]\n'}, []),
        ({"pyproject.toml": '[tool.ruff.lint]\nselect = ["ALL"]\n'}, []),
        ({"pyproject.toml": '[tool.ruff]\nselect = ["G", "LOG"]\n'}, []),
        ({"ruff.toml": '[lint]\nselect = ["G", "LOG"]\n'}, []),
        ({".ruff.toml": 'select = ["G", "LOG"]\n'}, []),
        ({"pyproject.toml": '[project]\nname = "x"\n'}, ["lint-python"]),
        ({}, ["lint-python"]),
        ({"pyproject.toml": '[tool.ruff.lint]\nselect = ["E"]\n'}, ["lint-python"]),
        ({"pyproject.toml": '[tool.ruff.lint]\nselect = ["G004", "LOG"]\n'}, ["lint-python"]),
        (
            {"pyproject.toml": '[tool.ruff.lint]\nselect = ["ALL"]\nignore = ["G"]\n'},
            ["lint-python"],
        ),
    ],
    ids=[
        "select",
        "extend-select",
        "all",
        "legacy-top-level",
        "ruff-toml",
        "dot-ruff-toml",
        "no-ruff-table",
        "no-config",
        "missing-families",
        "single-code-not-family",
        "family-ignored",
    ],
)
def test_lint_python(tmp_path: Path, config: dict[str, str], expected: list[str]) -> None:
    assert rules(tmp_path, {"app.py": "x = 1\n", **config}) == expected


def test_lint_python_names_the_missing_families(tmp_path: Path) -> None:
    root = make_repo(
        tmp_path, {"app.py": "x = 1\n", "pyproject.toml": '[tool.ruff.lint]\nselect = ["G"]\n'}
    )
    out = run(root)
    assert '"LOG"' in out.stdout
    assert '"G"' not in out.stdout


def test_lint_python_uses_the_closest_ruff_config(tmp_path: Path) -> None:
    files = {
        "pyproject.toml": GOOD_RUFF,
        "app.py": "x = 1\n",
        "sub/pyproject.toml": '[tool.ruff.lint]\nselect = ["E"]\n',
        "sub/mod.py": "x = 1\n",
        # A pyproject without a ruff table does not stop the walk up.
        "other/pyproject.toml": '[project]\nname = "o"\n',
        "other/mod.py": "x = 1\n",
    }
    assert findings(tmp_path, files) == [("sub/pyproject.toml", 1, "lint-python")]


def test_lint_python_follows_extend(tmp_path: Path) -> None:
    files = {
        "pyproject.toml": GOOD_RUFF,
        "sub/ruff.toml": 'extend = "../pyproject.toml"\n',
        "sub/mod.py": "x = 1\n",
    }
    assert rules(tmp_path, files) == []


def test_no_python_no_lint_python(tmp_path: Path) -> None:
    assert rules(tmp_path, {"README.md": "hi\n"}) == []


# --- lint-rust: clippy's print and dbg lints are on ------------------------------------------


@pytest.mark.parametrize(
    ("files", "expected"),
    [
        ({"Cargo.toml": GOOD_CARGO}, []),
        ({"Cargo.toml": '[package]\nname = "x"\nversion = "0.1.0"\n'}, ["lint-rust"]),
        (
            {
                "Cargo.toml": GOOD_CARGO.replace('dbg_macro = "warn"', 'dbg_macro = "allow"'),
            },
            ["lint-rust"],
        ),
        (
            {
                "Cargo.toml": (
                    '[package]\nname = "x"\nversion = "0.1.0"\n\n[lints.clippy]\n'
                    'print_stdout = { level = "deny", priority = 1 }\n'
                    'print_stderr = "forbid"\ndbg_macro = "warn"\n'
                ),
            },
            [],
        ),
        (
            {
                "Cargo.toml": (
                    '[workspace]\nmembers = ["app"]\n\n[workspace.lints.clippy]\n'
                    'print_stdout = "warn"\nprint_stderr = "warn"\ndbg_macro = "warn"\n'
                ),
                "app/Cargo.toml": (
                    '[package]\nname = "app"\nversion = "0.1.0"\n\n[lints]\nworkspace = true\n'
                ),
            },
            [],
        ),
        (
            {
                "Cargo.toml": '[workspace]\nmembers = ["app"]\n',
                "app/Cargo.toml": '[package]\nname = "app"\nversion = "0.1.0"\n',
            },
            ["lint-rust"],
        ),
    ],
    ids=["all-warn", "no-lints", "allowed", "table-levels", "workspace-inherit", "member-bare"],
)
def test_lint_rust(tmp_path: Path, files: dict[str, str], expected: list[str]) -> None:
    assert rules(tmp_path, files) == expected


# --- lint-js: a lint rule bans console.log ----------------------------------------------------

JS_SRC = {"package.json": '{"name": "x"}\n', "src/app.ts": "export const x = 1;\n"}


@pytest.mark.parametrize(
    ("files", "expected"),
    [
        ({**JS_SRC, "eslint.config.js": GOOD_ESLINT}, []),
        (JS_SRC, ["lint-js"]),
        (
            {
                **JS_SRC,
                "eslint.config.mjs": "export default [{ rules: { 'no-console': 'off' } }];\n",
            },
            ["lint-js"],
        ),
        (
            {**JS_SRC, "eslint.config.js": "export default [{ rules: { 'no-console': 0 } }];\n"},
            ["lint-js"],
        ),
        (
            {
                **JS_SRC,
                "biome.json": (
                    '{"linter": {"rules": {"suspicious": {"noConsole": '
                    '{"level": "error", "options": {"allow": ["warn", "error"]}}}}}}\n'
                ),
            },
            [],
        ),
        (
            {
                **JS_SRC,
                "biome.jsonc": '{"linter": {"rules": {"suspicious": {"noConsole": "warn"}}}}\n',
            },
            [],
        ),
        (
            {
                **JS_SRC,
                "biome.json": '{"linter": {"rules": {"suspicious": {"noConsole": "off"}}}}\n',
            },
            ["lint-js"],
        ),
        (
            {
                "package.json": (
                    '{"name": "x", "eslintConfig": {"rules": {"no-console": "warn"}}}\n'
                ),
                "src/app.ts": "export const x = 1;\n",
            },
            [],
        ),
        ({"package.json": '{"name": "x"}\n', "src/app.test.ts": "export {};\n"}, []),
        ({"src/app.js": "export const x = 1;\n"}, []),
        ({"tool/package.json": '{"name": "t"}\n', "web/app.js": "export {};\n"}, []),
        ({"package.json": '{"name": "x"}\n', "types/index.d.ts": "export {};\n"}, []),
        (
            {
                "eslint.config.js": GOOD_ESLINT,
                "app/package.json": '{"name": "a"}\n',
                "app/src/main.ts": "export {};\n",
            },
            [],
        ),
    ],
    ids=[
        "eslint-on",
        "no-config",
        "eslint-off",
        "eslint-zero",
        "biome-on",
        "biome-jsonc",
        "biome-off",
        "package-eslintconfig",
        "tests-only",
        "no-package-json",
        "source-outside-package",
        "declarations-only",
        "config-above-package",
    ],
)
def test_lint_js(tmp_path: Path, files: dict[str, str], expected: list[str]) -> None:
    assert rules(tmp_path, files) == expected


def test_lint_js_reports_each_package_once(tmp_path: Path) -> None:
    files = {
        "a/package.json": '{"name": "a"}\n',
        "a/x.ts": "export {};\n",
        "a/y.ts": "export {};\n",
        "b/package.json": '{"name": "b"}\n',
        "b/x.ts": "export {};\n",
        "b/eslint.config.js": GOOD_ESLINT,
    }
    assert findings(tmp_path, files) == [("a/package.json", 1, "lint-js")]


# --- secret-in-log ----------------------------------------------------------------------------

PY_OK = {"pyproject.toml": GOOD_RUFF}


@pytest.mark.parametrize(
    ("line", "hit"),
    [
        ('logger.info("key %s", api_key)', True),
        ('log.debug(f"t={token}")', True),
        ('logging.warning("%s", self.password)', True),
        ("print(secret)", True),
        ('self._logger.error("%s", os.environ["GITHUB_TOKEN"])', True),
        ('logger.info("%s", headers["Authorization"])', True),
        ('logger.info("%s", accessToken)', True),
        ('logger.info("n=%d", len(token))', False),
        ('logger.info("set=%s", token is not None)', False),
        ('logger.info("%d", max_tokens)', False),
        ('logger.info("%s", token_count)', False),
        ('logger.info("%s", token_path)', False),
        ('logger.info("%s", pad_token_id)', False),
        ('logger.info("session %s", session_id)', False),
        ("send(token)", False),
        ("parser.error(token)", False),
        ('logger.info("token refreshed")', False),
        ('logger.info("%s", password)  # logcheck: ignore[secret-in-log]', False),
        ('logger.info("%s", password)  # logcheck: ignore', False),
        ('logger.info("%s", password)  # logcheck: ignore[stderr-for-errors]', True),
    ],
)
def test_secret_in_log_python(tmp_path: Path, line: str, hit: bool) -> None:
    files = {**PY_OK, "app.py": f"import logging, os\n{line}\n"}
    assert findings(tmp_path, files) == ([("app.py", 2, "secret-in-log")] if hit else [])


def test_secret_in_log_python_multiline_suppressed_on_any_line(tmp_path: Path) -> None:
    src = 'logger.info(\n    "%s",\n    password,  # logcheck: ignore[secret-in-log]\n)\n'
    assert rules(tmp_path, {**PY_OK, "app.py": src}) == []


def test_secret_in_log_skips_tests_and_unparsable_python(tmp_path: Path) -> None:
    files = {
        **PY_OK,
        "tests/test_app.py": "print(password)\n",
        "app_test.py": "print(password)\n",
        "broken.py": "def (:\n",
    }
    assert rules(tmp_path, files) == []


RS_OK = {"Cargo.toml": GOOD_CARGO}


@pytest.mark.parametrize(
    ("line", "hit"),
    [
        ('info!("token {}", token);', True),
        ('eprintln!("{api_key}");', True),
        ('tracing::warn!(token = %tok, "refreshed");', True),
        ('info!("len {}", token.len());', False),
        ('info!("k {}", redact(&api_key));', False),
        ('info!("k {} {}", redact(&api_key), api_key);', True),
        ('info!("token refreshed");', False),
        ('info!("{}", max_tokens);', False),
    ],
)
def test_secret_in_log_rust(tmp_path: Path, line: str, hit: bool) -> None:
    files = {**RS_OK, "src/lib.rs": f"pub fn f() {{\n    {line}\n}}\n"}
    assert findings(tmp_path, files) == ([("src/lib.rs", 2, "secret-in-log")] if hit else [])


def test_rust_test_module_is_skipped(tmp_path: Path) -> None:
    src = (
        'pub fn f() {}\n\n#[cfg(test)]\nmod tests {\n    fn t() { println!("{}", password); }\n}\n'
    )
    assert rules(tmp_path, {**RS_OK, "src/lib.rs": src}) == []


def test_rust_macro_spanning_lines(tmp_path: Path) -> None:
    src = 'pub fn f() {\n    info!(\n        "k {}",\n        api_key\n    );\n}\n'
    assert findings(tmp_path, {**RS_OK, "src/lib.rs": src}) == [("src/lib.rs", 2, "secret-in-log")]


JS_OK = {**JS_SRC, "eslint.config.js": GOOD_ESLINT}


@pytest.mark.parametrize(
    ("line", "hit"),
    [
        ("console.error(password);", True),
        ("logger.info(`k ${apiKey}`);", True),
        ('console.warn("token refreshed");', False),
        ("console.error(tokenCount);", False),
        ("console.error(mask(password));", False),
    ],
)
def test_secret_in_log_js(tmp_path: Path, line: str, hit: bool) -> None:
    files = {**JS_OK, "src/app.ts": f"export const x = 1;\n{line}\n"}
    assert findings(tmp_path, files) == ([("src/app.ts", 2, "secret-in-log")] if hit else [])


@pytest.mark.parametrize(
    ("line", "hit"),
    [
        ('echo "token: $GITHUB_TOKEN"', True),
        ('printf "%s\\n" "${API_KEY}"', True),
        ('echo "::add-mask::$TOKEN"', False),
        ('echo "$PWD"', False),
        ('echo "$CLAUDE_SESSION_ID"', False),
        ('echo "token set"', False),
        ("echo 'literal $TOKEN'", False),
        ('echo "$TOKEN" | gh auth login --with-token', False),
        ('echo "TOKEN=$TOKEN" >> "$GITHUB_ENV"', False),
    ],
)
def test_secret_in_log_shell(tmp_path: Path, line: str, hit: bool) -> None:
    files = {"scripts/run.sh": f"#!/usr/bin/env bash\n{line}\n"}
    assert findings(tmp_path, files) == ([("scripts/run.sh", 2, "secret-in-log")] if hit else [])


def test_secret_in_log_workflow(tmp_path: Path) -> None:
    wf = (
        "on: push\njobs:\n  a:\n    runs-on: ubuntu-latest\n    env:\n"
        "      TOKEN: ${{ secrets.NPM_TOKEN }}\n    steps:\n"
        '      - run: echo "${{ secrets.NPM_TOKEN }}"\n'
    )
    assert findings(tmp_path, {".github/workflows/ci.yml": wf}) == [
        (".github/workflows/ci.yml", 8, "secret-in-log")
    ]


# --- unbounded-log-file -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("line", "hit"),
    [
        ('logging.FileHandler("app.log")', True),
        ('RotatingFileHandler("a.log")', True),
        ('RotatingFileHandler("a.log", maxBytes=1_000_000, backupCount=3)', False),
        ('RotatingFileHandler("a.log", "a", 1_000_000, 3)', False),
        ('RotatingFileHandler("a.log", maxBytes=0, backupCount=3)', True),
        ('logging.handlers.TimedRotatingFileHandler("a.log", when="D")', True),
        ('TimedRotatingFileHandler("a.log", when="D", backupCount=7)', False),
        ('logging.basicConfig(filename="a.log")', True),
        ("logging.basicConfig(level=logging.INFO)", False),
        ('logging.handlers.WatchedFileHandler("a.log")', False),
        ('cfg = {"class": "logging.FileHandler", "filename": "a.log"}', True),
        (
            'cfg = {"class": "logging.handlers.RotatingFileHandler", "maxBytes": 10, '
            '"backupCount": 2}',
            False,
        ),
    ],
)
def test_unbounded_log_file_python(tmp_path: Path, line: str, hit: bool) -> None:
    files = {**PY_OK, "app.py": f"import logging\n{line}\n"}
    assert findings(tmp_path, files) == ([("app.py", 2, "unbounded-log-file")] if hit else [])


@pytest.mark.parametrize(
    ("src", "hit"),
    [
        ('let a = tracing_appender::rolling::daily("logs", "app.log");', True),
        ('let a = rolling::never("logs", "app.log");', True),
        (
            "let a = RollingFileAppender::builder()\n        .rotation(Rotation::DAILY)\n"
            '        .max_log_files(7)\n        .build("logs");',
            False,
        ),
        (
            "let a = RollingFileAppender::builder()\n        .rotation(Rotation::DAILY)\n"
            '        .build("logs");',
            True,
        ),
        ("let b = Builder::new().rotation_strategy(RotationStrategy::KeepAll);", True),
        ("let b = Builder::new().rotation_strategy(RotationStrategy::KeepSome(5));", False),
    ],
)
def test_unbounded_log_file_rust(tmp_path: Path, src: str, hit: bool) -> None:
    files = {**RS_OK, "src/lib.rs": f"pub fn f() {{\n    {src}\n}}\n"}
    assert findings(tmp_path, files) == ([("src/lib.rs", 2, "unbounded-log-file")] if hit else [])


# --- stderr-for-errors ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("line", "hit"),
    [
        ('echo "error: no repo"', True),
        ('echo "error: no repo" >&2', False),
        ('echo "error: no repo" 1>&2', False),
        ("printf 'FAIL: %s\\n' \"$x\"", True),
        ('echo "no errors found"', False),
        ('echo "$0: error: bad"', True),
        ('echo "Warning: low disk"', True),
        ('echo "::error::bad"', False),
        ('echo "FAIL  $x"', False),
        ('echo "FAIL: $f uses <skill-dir>"', True),
        ('echo "FAIL: $f" > report.txt', False),
        ('echo "failed to start"', False),
        ('echo "error: x"  # logcheck: ignore[stderr-for-errors]', False),
    ],
)
def test_stderr_for_errors_shell(tmp_path: Path, line: str, hit: bool) -> None:
    files = {"run.sh": f"#!/bin/sh\n{line}\n"}
    assert findings(tmp_path, files) == ([("run.sh", 2, "stderr-for-errors")] if hit else [])


def test_continued_command_is_read_whole(tmp_path: Path) -> None:
    src = (
        "#!/bin/sh\nprintf 'FAIL: %s\\n' \\\n    \"$x\" >&2\nprintf 'FAIL: %s\\n' \\\n    \"$x\"\n"
    )
    assert findings(tmp_path, {"run.sh": src}) == [("run.sh", 4, "stderr-for-errors")]


def test_shebang_script_without_extension_is_scanned(tmp_path: Path) -> None:
    files = {"bin/tool": '#!/usr/bin/env bash\necho "error: x"\n', "bin/data": 'echo "error: x"\n'}
    assert findings(tmp_path, files) == [("bin/tool", 2, "stderr-for-errors")]


def test_stderr_for_errors_workflow_asks_for_an_annotation(tmp_path: Path) -> None:
    wf = (
        "on: push\njobs:\n  a:\n    runs-on: ubuntu-latest\n    steps:\n"
        '      - run: |\n          echo "error: bad"\n          echo "::error::bad"\n'
    )
    root = make_repo(tmp_path, {".github/workflows/ci.yml": wf})
    out = run(root)
    assert ".github/workflows/ci.yml:7: stderr-for-errors:" in out.stdout
    assert "::error::" in out.stdout
    assert ":8:" not in out.stdout


# --- ci-logs-not-uploaded ---------------------------------------------------------------------

WF_HEAD = "on: push\njobs:\n"
WRITES = (
    "  test:\n    runs-on: ubuntu-latest\n    steps:\n"
    "      - run: make test 2>&1 | tee logs/test.log\n"
)


def upload(cond: str | None) -> str:
    step = "      - uses: actions/upload-artifact@v7\n"
    if cond is not None:
        step += f"        if: {cond}\n"
    return step + "        with:\n          name: logs\n          path: logs/\n"


@pytest.mark.parametrize(
    ("body", "hit"),
    [
        (WRITES, True),
        (WRITES + upload("failure()"), False),
        (WRITES + upload("${{ always() }}"), False),
        (WRITES + upload("'!cancelled()'"), False),
        (WRITES + upload(None), True),
        (
            WRITES + "  other:\n    runs-on: ubuntu-latest\n    steps:\n" + upload("failure()"),
            True,
        ),
        (
            "  test:\n    runs-on: ubuntu-latest\n    steps:\n"
            "      - run: pytest --log-file=pytest.log\n",
            True,
        ),
        ("  test:\n    runs-on: ubuntu-latest\n    steps:\n      - run: make test\n", False),
    ],
    ids=[
        "no-upload",
        "on-failure",
        "always",
        "not-cancelled",
        "success-only",
        "other-job-uploads",
        "log-file-flag",
        "no-log-written",
    ],
)
def test_ci_logs_not_uploaded(tmp_path: Path, body: str, hit: bool) -> None:
    got = findings(tmp_path, {".github/workflows/ci.yml": WF_HEAD + body})
    assert [r for _, _, r in got] == (["ci-logs-not-uploaded"] if hit else [])


# --- log-file-tracked -------------------------------------------------------------------------


def test_log_file_tracked(tmp_path: Path) -> None:
    files = {
        "build.log": "x\n",
        "tests/fixtures/run.log": "x\n",
        "fixtures/a.log": "x\n",
        "datasets/logs/a.log": "x\n",
        "datasets/logs/run-1/b.log": "x\n",
    }
    root = make_repo(tmp_path, files)
    (root / "untracked.log").write_text("x\n")
    out = run(root, "--format", "json")
    got = [(f["path"], f["rule"], f["message"]) for f in json.loads(out.stdout)]
    assert [(p, r) for p, r, _ in got] == [
        ("build.log", "log-file-tracked"),
        ("datasets/logs/a.log", "log-file-tracked"),
    ]
    assert got[0][2] == "a log file is committed → delete it and ignore *.log"
    assert "2 log files are committed under datasets/logs/" in got[1][2]
    assert '"- skip: datasets/logs/"' in got[1][2]


# --- scope: vendored paths and the skill-context section --------------------------------------


def test_vendored_paths_are_skipped(tmp_path: Path) -> None:
    files = {
        **JS_OK,
        "node_modules/x/index.js": "console.log(password);\n",
        "dist/app.js": "console.log(password);\n",
        "site/app.js": "console.log(password);\n",
        "vendor/x.sh": 'echo "error: x"\n',
    }
    assert rules(tmp_path, files) == []


def test_skill_context_ignores_rules_and_skips_paths(tmp_path: Path) -> None:
    files = {
        **JS_SRC,
        "legacy/run.sh": '#!/bin/sh\necho "error: x"\n',
        "run.sh": '#!/bin/sh\necho "error: x"\n',
        ".claude/skill-context.md": (
            "## repo\n\nA repo.\n\n## logging\n\n"
            "- ignore: lint-js (the site ships no runtime JS logging)\n"
            "- skip: legacy/\n\n## audit\n\n- ignore: stderr-for-errors\n"
        ),
    }
    assert findings(tmp_path, files) == [("run.sh", 2, "stderr-for-errors")]


# --- the command line -------------------------------------------------------------------------


def test_clean_repo_exits_zero(tmp_path: Path) -> None:
    root = make_repo(
        tmp_path, {**PY_OK, "app.py": "import logging\nlogger = logging.getLogger(__name__)\n"}
    )
    out = run(root)
    assert out.returncode == 0
    assert out.stdout.strip() == "logging standard ✓"


def test_findings_exit_one_sorted(tmp_path: Path) -> None:
    root = make_repo(
        tmp_path,
        {
            "b.sh": '#!/bin/sh\necho "error: b"\n',
            "a.sh": '#!/bin/sh\necho "x"\necho "error: a"\necho "error: c"\n',
        },
    )
    out = run(root)
    assert out.returncode == 1
    lines = out.stdout.strip().splitlines()
    assert [ln.split(" ", 1)[0] for ln in lines[:-1]] == ["a.sh:3:", "a.sh:4:", "b.sh:2:"]
    assert lines[-1] == "3 findings"


def test_not_a_repo_exits_two(tmp_path: Path) -> None:
    out = run(tmp_path)
    assert out.returncode == 2
    assert "not a git repository" in out.stderr


def test_github_format_escapes(tmp_path: Path) -> None:
    root = make_repo(tmp_path, {"a,b.sh": '#!/bin/sh\necho "error: 100%"\n'})
    out = run(root, "--format", "github")
    line = out.stdout.strip().splitlines()[0]
    assert line.startswith("::warning file=a%2Cb.sh,line=2,title=logcheck stderr-for-errors::")
    assert out.returncode == 1


def test_summary_covers_every_repo_and_exits_zero(tmp_path: Path) -> None:
    good = make_repo(tmp_path, {**PY_OK, "app.py": "x = 1\n"}, name="good")
    bad = make_repo(
        tmp_path, {"run.sh": '#!/bin/sh\necho "error: x"\necho "fail: y"\n'}, name="bad"
    )
    out = run(tmp_path, "--summary", str(good), str(bad), str(tmp_path / "missing"))
    assert out.returncode == 0
    assert out.stdout.splitlines() == [
        "good: logging standard ✓",
        "bad: 2 findings (stderr-for-errors 2) → run /techne:logging there",
        f"missing: not a git repository at {tmp_path / 'missing'}",
    ]


def test_undecodable_file_is_skipped(tmp_path: Path) -> None:
    root = make_repo(tmp_path, {})
    (root / "x.sh").write_bytes(b'#!/bin/sh\necho "error: \xff"\n')
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    assert run(root).returncode == 0


# --- review round 1: each case a reviewer reproduced ------------------------------------------


@pytest.mark.parametrize(
    ("path", "src"),
    [
        ("src/app.tsx", 'export const A = () => <p>Don\'t panic</p>;\nconsole.log("t", token);\n'),
        ("src/app.ts", 'const r = /"/g;\nconsole.log("t", token);\n'),
        ("src/lib.rs", 'pub fn f() {\n    let q = \'"\';\n    info!("{}", api_key);\n}\n'),
    ],
    ids=["jsx-apostrophe", "js-regex-quote", "rust-char-quote"],
)
def test_a_stray_quote_does_not_hide_later_calls(tmp_path: Path, path: str, src: str) -> None:
    files = {**JS_OK, **RS_OK, path: src}
    got = [(p, r) for p, _, r in findings(tmp_path, files)]
    assert got == [(path, "secret-in-log")]


def test_cfg_test_hides_only_the_item_it_marks(tmp_path: Path) -> None:
    src = (
        "#[cfg(test)]\nmod tests;\n\n#[cfg(test)]\nmod more {\n"
        '    fn t() { info!("{}", password); }\n}\n'
        'pub fn f() {\n    info!("{}", api_key);\n}\n'
    )
    assert findings(tmp_path, {**RS_OK, "src/lib.rs": src}) == [("src/lib.rs", 9, "secret-in-log")]


def test_skip_keeps_a_leading_dot(tmp_path: Path) -> None:
    wf = 'on: push\njobs:\n  a:\n    runs-on: x\n    steps:\n      - run: echo "error: x"\n'
    files = {
        ".github/workflows/ci.yml": wf,
        ".claude/skill-context.md": "## logging\n\n- skip: .github/\n",
    }
    assert rules(tmp_path, files) == []


def test_template_placeholders_and_unknown_rules_are_left_out_loudly(tmp_path: Path) -> None:
    files = {
        "out/run.sh": '#!/bin/sh\necho "error: x"\n',
        ".claude/skill-context.md": (
            "## logging\n- ignore: <rule>, ... (<why this repo opts out>)\n"
            "- skip: <path prefix the check leaves out, e.g. legacy/>\n- ignore: no-such-rule\n"
        ),
    }
    root = make_repo(tmp_path, files)
    out = run(root)
    assert "out/run.sh:2: stderr-for-errors" in out.stdout
    assert "placeholder" in out.stderr
    assert "'no-such-rule' is not a logcheck rule" in out.stderr


@pytest.mark.parametrize(
    ("line", "hit"),
    [
        ('print("set" if token else "unset")', False),
        ('logger.info("%s", token.startswith("ghp_"))', False),
        ('logger.info("%s", hash(token))', False),
        ('logger.info("%d", CHARS_PER_TOKEN)', False),
        ('log.info("login", password=pw)', True),
        ('log.info("login", password="***")', False),
        ('log.info("login", password=redact(pw))', False),
    ],
)
def test_secret_in_log_python_round_one(tmp_path: Path, line: str, hit: bool) -> None:
    files = {**PY_OK, "app.py": f"{line}\n"}
    assert findings(tmp_path, files) == ([("app.py", 1, "secret-in-log")] if hit else [])


@pytest.mark.parametrize(
    ("path", "line", "hit"),
    [
        ("src/lib.rs", 'info!(token = %redact(t), "x");', False),
        ("src/app.ts", "console.log({ token: redact(t) });", False),
        ("src/app.ts", "console.log({ token: t });", True),
        ("src/app.ts", "this.logger.info(token);", True),
        ("src/app.ts", "this.log.debug(apiKey);", True),
    ],
)
def test_field_names_and_member_loggers(tmp_path: Path, path: str, line: str, hit: bool) -> None:
    body = f"pub fn f() {{\n    {line}\n}}\n" if path.endswith(".rs") else f"export {{}};\n{line}\n"
    got = findings(tmp_path, {**JS_OK, **RS_OK, path: body})
    assert got == ([(path, 2, "secret-in-log")] if hit else [])


def test_shell_secret_names_are_environment_variables(tmp_path: Path) -> None:
    src = '#!/bin/sh\nfor token in a b; do\n  echo "$token"\ndone\necho "$API_TOKEN"\n'
    assert findings(tmp_path, {"run.sh": src}) == [("run.sh", 5, "secret-in-log")]


def test_a_symlink_or_device_is_not_read(tmp_path: Path) -> None:
    root = make_repo(tmp_path, {})
    (root / "zero.sh").symlink_to("/dev/zero")
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    out = subprocess.run(
        [sys.executable, str(LOGCHECK_SCRIPT)], cwd=root, capture_output=True, text=True,
        timeout=30, check=False,
    )  # fmt: skip
    assert out.returncode == 0


def test_a_file_too_deep_to_parse_is_named_not_fatal(tmp_path: Path) -> None:
    deep = "logger.info(" + " + ".join(["a"] * 5000) + ")\n"
    root = make_repo(tmp_path, {**PY_OK, "deep.py": deep, "run.sh": '#!/bin/sh\necho "error: x"\n'})
    out = run(root)
    assert "run.sh:2: stderr-for-errors" in out.stdout
    assert out.returncode == 1


@pytest.mark.parametrize(
    ("src", "hit"),
    [
        ('{ echo "error: x"; exit 1; } >&2', False),
        ('{\n  echo "error: x"\n  exit 1\n} >&2', False),
        ('cat <<EOT\necho "error: x"\nEOT', False),
        ('cat <<\'EOT\'\necho "error: x"\nEOT\necho "error: y"', True),
    ],
    ids=["group-one-line", "group-multi-line", "heredoc", "after-heredoc"],
)
def test_stderr_groups_and_heredocs(tmp_path: Path, src: str, hit: bool) -> None:
    got = rules(tmp_path, {"run.sh": f"#!/bin/sh\n{src}\n"})
    assert got == (["stderr-for-errors"] if hit else [])


def test_workflow_error_to_stderr_still_needs_an_annotation(tmp_path: Path) -> None:
    wf = 'on: push\njobs:\n  a:\n    runs-on: x\n    steps:\n      - run: echo "error: x" >&2\n'
    assert rules(tmp_path, {".github/workflows/ci.yml": wf}) == ["stderr-for-errors"]


def test_upload_before_the_log_is_written_does_not_count(tmp_path: Path) -> None:
    body = (
        "  test:\n    runs-on: x\n    steps:\n" + upload("failure()") + WRITES.split("steps:\n")[1]
    )
    got = findings(tmp_path, {".github/workflows/ci.yml": WF_HEAD + body})
    assert [r for _, _, r in got] == ["ci-logs-not-uploaded"]


@pytest.mark.parametrize(
    ("src", "hit"),
    [
        ('let a = rolling::Builder::new().rotation(Rotation::DAILY).build("l");', True),
        (
            "let a = rolling::Builder::new().rotation(Rotation::DAILY)"
            '.max_log_files(3).build("l");',
            False,
        ),
        (
            "let a = RollingFileAppender::builder().rotation(Rotation::NEVER)"
            '.max_log_files(5).build("l");',
            True,
        ),
    ],
)
def test_unbounded_rust_round_one(tmp_path: Path, src: str, hit: bool) -> None:
    files = {**RS_OK, "src/lib.rs": f"pub fn f() {{\n    {src}\n}}\n"}
    assert rules(tmp_path, files) == (["unbounded-log-file"] if hit else [])


def test_unbalanced_code_stays_fast(tmp_path: Path) -> None:
    src = "export {};\n" + "console.log(a, (b;\n" * 2000
    root = make_repo(tmp_path, {**JS_OK, "src/app.ts": src})
    out = subprocess.run(
        [sys.executable, str(LOGCHECK_SCRIPT)], cwd=root, capture_output=True, text=True,
        timeout=20, check=False,
    )  # fmt: skip
    assert out.returncode == 0


def test_a_symlink_to_a_file_outside_the_repo_is_not_followed(tmp_path: Path) -> None:
    outside = tmp_path / "outside.sh"
    outside.write_text('#!/bin/sh\necho "error: x"\n')
    root = make_repo(tmp_path, {})
    (root / "link.sh").symlink_to(outside)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    assert run(root).returncode == 0
