"""The secret scan behind phylax's block_secrets guard: engine choice, one scan, the catch log.

git_guards.py calls scan() with the repo's top folder, the git environment to scan in (a
temporary GIT_INDEX_FILE for a commit that stages more), and either a staged scan or git log
options for a push. Engines: ggshield (GitGuardian's detectors, the same as the GitGuardian PR
check) for a commit when GITGUARDIAN_API_KEY is set and ggshield is installed; gitleaks
otherwise, and always for a push, since ggshield takes one range per call. Scanners report
secrets redacted; nothing here prints or logs a secret's value.

Runs on the system python3, so it stays compatible with 3.9 (macOS's).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

SCAN_TIMEOUT = 20
LOG_MAX = 256 * 1024


class ScanError(Exception):
    """The scanner did not run, timed out, or answered in a way that is not a verdict."""


class Finding:
    def __init__(self, file: str, line: int | None, rule: str, commit: str = "") -> None:
        self.file = file
        self.line = line
        self.rule = rule
        self.commit = commit

    def where(self) -> str:
        at = f"{self.file}:{self.line}" if self.line else self.file
        return f"{at} ({self.rule}" + (f", commit {self.commit[:12]})" if self.commit else ")")

    def as_dict(self) -> dict:
        return {"file": self.file, "line": self.line, "rule": self.rule, "commit": self.commit}


def engine(kind: str) -> tuple[str, str] | None:
    """(name, path) of the scanner for a "commit" or "push", or None when none is installed."""
    if kind == "commit" and os.environ.get("GITGUARDIAN_API_KEY"):
        path = shutil.which("ggshield")
        if path:
            return "ggshield", path
    path = shutil.which("gitleaks")
    return ("gitleaks", path) if path else None


def scan(
    kind: str, top: Path, git_env: dict[str, str], log_opts: str | None, tmp: Path
) -> tuple[str, list[Finding]]:
    """Scan the staged changes (log_opts None) or the commits log_opts names.

    Returns the engine's name and its findings; raises ScanError when no scanner is installed
    or the scan gives no verdict, so the guard refuses rather than passing unscanned work.
    """
    found = engine(kind)
    if found is None:
        raise ScanError("no secret scanner is installed (install gitleaks)")
    name, path = found
    env = {**os.environ, **git_env}
    if name == "ggshield":
        return name, _ggshield(path, top, env)
    return name, _gitleaks(path, top, env, log_opts, tmp)


def _run(argv: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=SCAN_TIMEOUT
        )
    except subprocess.TimeoutExpired as exc:
        raise ScanError(f"{Path(argv[0]).name} timed out after {SCAN_TIMEOUT}s") from exc
    except OSError as exc:
        raise ScanError(f"{Path(argv[0]).name} could not run: {exc}") from exc


def _tail(proc: subprocess.CompletedProcess) -> str:
    text = (proc.stderr or proc.stdout or "").strip().splitlines()
    return text[-1][:200] if text else f"exit {proc.returncode}"


def _gitleaks(
    path: str, top: Path, env: dict[str, str], log_opts: str | None, tmp: Path
) -> list[Finding]:
    report = tmp / "gitleaks.json"
    which = ["--staged"] if log_opts is None else ["--log-opts", log_opts]
    argv = [
        path,
        "git",
        *which,
        "--no-banner",
        "--no-color",
        "--redact",
        "--log-level",
        "error",
        "--exit-code",
        "1",
        "--report-format",
        "json",
        "--report-path",
        str(report),
        str(top),
    ]
    proc = _run(argv, top, env)
    if proc.returncode == 0:
        return []
    try:
        rows = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        rows = None
    # gitleaks exits 1 for a leak and for its own errors alike; only a report with rows is a leak.
    if proc.returncode != 1 or not isinstance(rows, list) or not rows:
        raise ScanError(f"gitleaks gave no verdict: {_tail(proc)}")
    return [
        Finding(
            str(r.get("File") or "?"),
            r.get("StartLine") or None,
            str(r.get("RuleID") or "secret"),
            str(r.get("Commit") or ""),
        )
        for r in rows
        if isinstance(r, dict)
    ]


def _ggshield(path: str, top: Path, env: dict[str, str]) -> list[Finding]:
    proc = _run([path, "secret", "scan", "--json", "pre-commit"], top, env)
    if proc.returncode == 0:
        return []
    try:
        out = json.loads(proc.stdout)
    except ValueError:
        out = None
    findings: list[Finding] = []
    for entity in (out or {}).get("entities_with_incidents") or []:
        for incident in entity.get("incidents") or []:
            lines = [o.get("line_start") for o in incident.get("occurrences") or []]
            findings.append(
                Finding(
                    str(entity.get("filename") or "?"),
                    next((n for n in lines if isinstance(n, int)), None),
                    str(incident.get("type") or incident.get("detector") or "secret"),
                )
            )
    if not findings:
        raise ScanError(f"ggshield gave no verdict: {_tail(proc)}")
    return findings


def log_path() -> Path:
    state = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return Path(state) / "phylax" / "secret-gate.jsonl"


def log_event(event: dict) -> None:
    """Append one JSON line (a catch or a scan that gave no verdict); the file stays under
    LOG_MAX by moving it to .1 first. A log that cannot be written never changes the verdict."""
    path = log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > LOG_MAX:
            os.replace(path, path.with_suffix(".jsonl.1"))
        line = json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **event})
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass
