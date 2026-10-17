#!/usr/bin/env python3
"""A plugin's saved API keys, handed to Claude Code's Bash commands.

Usage: plugin_keys.py start | end         (SessionStart and SessionEnd hooks)
       plugin_keys.py template            (print a .env file to fill in)
       plugin_keys.py store <file> [--plugin ID]

The plugin's own `.claude-plugin/plugin.json` is the only key table. Every `userConfig` option
with `sensitive: true` and type `string` is a key, and its environment variable is the option name
in capitals. The option's `description` says what the key adds and where to get it. Keys that only
work together are listed in `metadata.keyGroups`, a list of lists of option names (Claude Code
ignores `metadata`). The plugin root is the parent of the folder holding this script.

Hooks. Claude Code gives a hook every plugin option as CLAUDE_PLUGIN_OPTION_<NAME>, but Bash-tool
commands never see them. CLAUDE_ENV_FILE reaches every Bash command in the session, subagents
included, but Claude Code leaves those files on disk at mode 0644 and never deletes them, so no
value goes in one. `start` writes the values to a private (0600) file in the plugin's data folder
and appends only a line that sources it to CLAUDE_ENV_FILE; `end` deletes that file. A variable
already set in the Bash environment wins. A hook prints nothing and always exits 0; a value is
never echoed.

The file is `<session_id>.<owner_pid>.sh`, where the owner is the hook's parent: hooks.json runs
the script with `exec`, so that parent is the Claude Code process that ran the hook command. One
conversation can be open in two processes, so a session id alone is not a safe name. `end`
deletes only its own process's file. `start` prunes files whose owner process is gone; a session
that idles for days keeps its file.

Store. `store` saves a filled-in .env file with `claude plugin configure <id> --values-stdin`
and never prints a value. Exit codes: 0 stored, 1 nothing stored (the file holds no values), 2 any
error (usage, unreadable or unparsable file, `claude` missing or failing, configure failure).

Runs on the system python3 (3.9 or newer, standard library only).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shlex
import shutil
import stat
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import NamedTuple

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
MARKETPLACE = "techne"
ENV_NAME = re.compile(r"[A-Z][A-Z0-9_]*")
SUBDIR = "session-keys"
# Windows cannot probe a pid without os.kill, which there terminates the process, so a file whose
# owner cannot be probed (Windows, or a name that does not parse) is pruned by age instead. A
# session that idles longer than this and is still open loses its keys until its next start.
MAX_AGE_SECONDS = 30 * 24 * 60 * 60
SAFE_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
FILE_NAME = re.compile(r"(?P<sid>[A-Za-z0-9_-]{1,128})\.(?P<pid>[0-9]{1,10})\.sh")
SHARED_BITS = stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH


class Key(NamedTuple):
    option: str  # the plugin.json userConfig name
    env: str  # the variable the plugin's scripts read
    title: str
    description: str  # what the key adds and where to get it
    group: str = ""  # keys with the same group only work together

    @property
    def why(self) -> str:
        """The description as a clause: no final period, and a lower-case first letter."""
        text = self.description.strip().rstrip(".")
        if text[1:2].islower():
            text = text[:1].lower() + text[1:]
        return text


def read_manifest(plugin_root: Path) -> dict:
    try:
        data = json.loads((plugin_root / ".claude-plugin" / "plugin.json").read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def plugin_name(plugin_root: Path) -> str:
    name = read_manifest(plugin_root).get("name")
    return name if isinstance(name, str) else plugin_root.name


def group_name(envs: Sequence[str]) -> str:
    """The shared prefix of the members' variable names, or all of them joined."""
    prefix = os.path.commonprefix(list(envs)).rstrip("_")
    return prefix if len(prefix) > 1 else "_".join(envs)


def load_keys(plugin_root: Path | None = None) -> list[Key]:
    """The plugin's keys, in manifest order. A missing or unreadable manifest gives none."""
    manifest = read_manifest(plugin_root or ROOT)
    options = manifest.get("userConfig")
    if not isinstance(options, dict):
        return []
    keyed = {}
    for option, spec in options.items():
        env = option.upper() if isinstance(option, str) else ""
        if (
            isinstance(spec, dict)
            and spec.get("sensitive") is True
            and spec.get("type") == "string"
            and ENV_NAME.fullmatch(env)
        ):
            keyed[option] = (env, spec)
    group_of: dict[str, str] = {}
    meta = manifest.get("metadata")
    groups = meta.get("keyGroups") if isinstance(meta, dict) else None
    for members in groups if isinstance(groups, list) else []:
        names = [m for m in members if m in keyed] if isinstance(members, list) else []
        if len(names) > 1:
            label = group_name([keyed[m][0] for m in names])
            for member in names:
                group_of.setdefault(member, label)
    return [
        Key(
            option,
            env,
            str(spec.get("title") or option),
            str(spec.get("description") or ""),
            group_of.get(option, ""),
        )
        for option, (env, spec) in keyed.items()
    ]


def group_names(keys: Sequence[Key]) -> list[str]:
    return list(dict.fromkeys(k.group for k in keys if k.group))


def configure_hint(plugin_root: Path | None = None) -> str:
    return f"/plugin configure {plugin_name(plugin_root or ROOT)}@{MARKETPLACE}"


def doctor_entries(
    keys: Sequence[Key], environ: Mapping[str, str], hint: str
) -> list[tuple[str, bool, str]]:
    """(name, present, detail) for a setup doctor: one per ungrouped key, one per group."""
    store = f"store it with {hint}, then restart"

    def entry(name: str, why: str, present: bool) -> tuple[str, bool, str]:
        return name, present, "set" if present else f"not set; {why}; {store}"

    found = [entry(k.env, k.why, bool(environ.get(k.env))) for k in keys if not k.group]
    for group in group_names(keys):
        members = [k for k in keys if k.group == group]
        envs = [k.env for k in members]
        need = "both" if len(envs) == 2 else "all of"
        why = f"{members[0].why}; needs {need} {' and '.join(envs)}"
        found.append(entry(group, why, all(environ.get(env) for env in envs)))
    return found


# the session hook


def session_id(raw: str) -> str | None:
    """The id from the hook's stdin JSON, or None unless it is safe to use in a file name."""
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    sid = data.get("session_id") if isinstance(data, dict) else None
    return sid if isinstance(sid, str) and SAFE_ID.fullmatch(sid) else None


def export_lines(keys: Sequence[Key], environ: Mapping[str, str]) -> list[str]:
    """One line per saved key. A variable already set in the Bash environment is kept."""
    lines = []
    for key in keys:
        value = environ.get(f"CLAUDE_PLUGIN_OPTION_{key.option.upper()}", "")
        if not value or "\n" in value or "\r" in value or "\0" in value:
            continue
        lines.append(f'[ -n "${{{key.env}-}}" ] || export {key.env}={shlex.quote(value)}\n')
    return lines


def private_dir(data_dir: str) -> str:
    path = os.path.join(data_dir, SUBDIR)
    os.makedirs(path, mode=0o700, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def pid_alive(pid: int) -> bool:
    """Whether a process with this pid exists. POSIX only: on Windows os.kill terminates it."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, OverflowError):
        return False
    except OSError:  # PermissionError: it exists but belongs to another user
        return True
    return True


def stale(name: str, path: str, now: float) -> bool:
    match = FILE_NAME.fullmatch(name)
    if match and os.name != "nt":
        return not pid_alive(int(match.group("pid")))
    return now - os.lstat(path).st_mtime > MAX_AGE_SECONDS


def prune(directory: str, now: float) -> None:
    for name in os.listdir(directory):
        path = os.path.join(directory, name)
        try:
            if not stat.S_ISDIR(os.lstat(path).st_mode) and stale(name, path, now):
                os.remove(path)
        except OSError:
            pass


def remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def write_private(path: str, text: str) -> None:
    """Create the file at mode 0600 under a fresh temp name, then move it into place.

    The temp name is created exclusively and never through a symlink; if it exists the write
    fails, and the hook exits 0 without a file.
    """
    temp = f"{path}.{secrets.token_hex(8)}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(temp, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(text)
        os.replace(temp, path)
    except BaseException:
        remove(temp)
        raise


def has_line(target: str, line: str) -> bool:
    try:
        with open(target, encoding="utf-8", errors="replace") as src:
            return line in src.read().splitlines()
    except FileNotFoundError:
        return False


def file_name(sid: str) -> str:
    return f"{sid}.{os.getppid()}.sh"


def start(keys: Sequence[Key], sid: str, directory: str, environ: Mapping[str, str]) -> None:
    prune(directory, time.time())
    path = os.path.join(directory, file_name(sid))
    lines = export_lines(keys, environ)
    target = environ.get("CLAUDE_ENV_FILE")
    if not lines or not target:
        remove(path)
        return
    write_private(path, "".join(lines))
    quoted = shlex.quote(path)
    source = f"if [ -f {quoted} ]; then . {quoted}; fi"
    if not has_line(target, source):
        with open(target, "a", encoding="utf-8") as out:
            out.write(source + "\n")


def run_hook(mode: str, stdin_text: str, environ: Mapping[str, str], plugin_root: Path) -> int:
    data_dir = environ.get("CLAUDE_PLUGIN_DATA")
    sid = session_id(stdin_text)
    if not data_dir or sid is None:
        return 0
    try:
        directory = private_dir(data_dir)
        if mode == "start":
            start(load_keys(plugin_root), sid, directory, environ)
        else:
            remove(os.path.join(directory, file_name(sid)))
    except (OSError, ValueError):
        pass  # a hook never blocks a session
    return 0


# the store command


class StoreError(Exception):
    """A message safe to print: it never contains a value."""


def template(keys: Sequence[Key]) -> str:
    blocks = []
    for k in keys:
        head, _, tail = k.why.partition("; ")
        partners = [o.env for o in keys if o.group == k.group and o is not k] if k.group else []
        head += f", with {' and '.join(partners)}" if partners else ""
        comment = f"{head}; {tail}" if tail else head
        blocks.append(f"# {comment[0].upper()}{comment[1:]}\n{k.env}=\n\n")
    return "".join(blocks)


def unquote(raw: str, number: int, name: str) -> str:
    """The value after `=`: quoted text, or unquoted text up to an inline ` #` comment."""
    text = raw.lstrip()
    if text[:1] in ("'", '"'):
        end = text.find(text[0], 1)
        if end < 0:
            raise StoreError(f"line {number}: unterminated quote for {name}")
        rest = text[end + 1 :]
        if rest.strip() and not (rest[0] in " \t" and rest.strip().startswith("#")):
            raise StoreError(f"line {number}: text after the closing quote for {name}")
        return text[1:end]
    return re.split(r"[ \t]#", raw, maxsplit=1)[0].strip()


def parse(text: str, keys: Sequence[Key]) -> dict[str, str]:
    """Env var name to non-empty value. An unknown name raises, naming the line, not the value."""
    known = {k.env for k in keys}
    found: dict[str, str] = {}
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export ") or line.startswith("export\t"):
            line = line[len("export") :].lstrip()
        name, sep, value = line.partition("=")
        name = name.strip()
        if not sep or name not in known:
            what = f"unknown name {name!r}" if sep else "not a NAME=value line"
            raise StoreError(f"line {number}: {what}")
        value = unquote(value, number, name)
        if value:
            found[name] = value
    return found


def half_groups(
    keys: Sequence[Key], found: Mapping[str, str]
) -> dict[str, tuple[list[str], list[str]]]:
    """Group name to (given, missing) env names, for each group given without all its members."""
    out = {}
    for group in group_names(keys):
        members = [k.env for k in keys if k.group == group]
        given = [env for env in members if env in found]
        if given and len(given) < len(members):
            out[group] = (given, [env for env in members if env not in found])
    return out


def find_plugin_id(listing: str, wanted: str | None, name: str) -> str:
    if wanted:
        return wanted
    try:
        entries = json.loads(listing)
    except ValueError:
        raise StoreError("could not read `claude plugin list --json`; pass --plugin <id>") from None
    installs = [
        e for e in entries if isinstance(e, dict) and str(e.get("id", "")).startswith(name + "@")
    ]
    enabled = sorted({e["id"] for e in installs if e.get("enabled", True)})
    every = sorted({e["id"] for e in installs})
    for ids in (enabled, every):
        if len(ids) == 1:
            return ids[0]
        if len(ids) > 1:
            break
    if not every:
        raise StoreError(f"{name} is not installed; install it or pass --plugin <id>")
    listed = ", ".join(enabled or every)
    raise StoreError(f"several {name} installs ({listed}); pass --plugin <id>")


def redact(text: str, values: Sequence[str]) -> str:
    forms = {form for v in values for form in (v, json.dumps(v)[1:-1])}
    for form in sorted(forms, key=len, reverse=True):
        text = text.replace(form, "***")
    return text


def run_claude(argv: Sequence[str], stdin: str | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(argv, input=stdin, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise StoreError(f"`{' '.join(argv[:3])}` failed to run: {type(exc).__name__}") from None


def warn_if_shared(path: Path) -> None:
    if os.name == "posix" and path.stat().st_mode & SHARED_BITS:
        print(f"warning: {path} can be read or changed by others; run chmod 600", file=sys.stderr)


def store(path: Path, plugin: str | None, plugin_root: Path) -> int:
    keys = load_keys(plugin_root)
    name = plugin_name(plugin_root)
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"error: cannot read {path}: {type(exc).__name__}", file=sys.stderr)
        return 2
    warn_if_shared(path)
    try:
        found = parse(text, keys)
    except StoreError as exc:
        print(f"error: {path}: {exc}", file=sys.stderr)
        return 2
    if not found:
        print(f"No values in {path}; nothing stored.")
        return 1
    partial = half_groups(keys, found)
    for given, missing in partial.values():
        print(
            f"warning: {' and '.join(given)} given without {' and '.join(missing)}", file=sys.stderr
        )
    if not shutil.which("claude"):
        print("error: `claude` is not on PATH; install Claude Code first", file=sys.stderr)
        return 2
    try:
        listing = run_claude(["claude", "plugin", "list", "--json"]) if not plugin else None
        plugin_id = find_plugin_id(listing.stdout if listing else "", plugin, name)
    except StoreError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    option_of = {k.env: k.option for k in keys}
    values = {option_of[env]: value for env, value in found.items()}
    try:
        done = run_claude(
            ["claude", "plugin", "configure", plugin_id, "--values-stdin"], stdin=json.dumps(values)
        )
    except StoreError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if done.returncode != 0:
        print(f"error: claude plugin configure exited {done.returncode}", file=sys.stderr)
        print(redact(done.stderr or "", list(values.values())).strip(), file=sys.stderr)
        return 2
    print(f"Stored in Claude Code's secure storage for {plugin_id}: {', '.join(found)}")
    for group, (_, missing) in partial.items():
        print(f"{group} stays skipped until {' and '.join(missing)} is saved too.")
    print("Restart Claude Code to apply it.")
    print(f"Delete {path} now, or keep it somewhere private; it holds the keys in plain text.")
    return 0


def main(argv: Sequence[str], stdin_text: str | None, environ: Mapping[str, str]) -> int:
    """Run a subcommand. `stdin_text` is read only by the hooks, so pass None to skip it."""
    mode = argv[1] if len(argv) > 1 else ""
    if mode in ("start", "end"):
        return run_hook(mode, stdin_text or "", environ, ROOT)
    if mode == "template":
        print(template(load_keys(ROOT)), end="")
        return 0
    if mode == "store":
        ap = argparse.ArgumentParser(prog="plugin_keys.py store")
        ap.add_argument("file", help=".env file holding the keys")
        ap.add_argument("--plugin", help=f"plugin id, such as {plugin_name(ROOT)}@{MARKETPLACE}")
        args = ap.parse_args(list(argv[2:]))
        return store(Path(args.file).expanduser(), args.plugin, ROOT)
    print(__doc__.split("\n\n")[1], file=sys.stderr)
    return 2


if __name__ == "__main__":
    hook_mode = len(sys.argv) > 1 and sys.argv[1] in ("start", "end")
    text = None
    if hook_mode:
        try:
            text = sys.stdin.read()
        except (OSError, ValueError):
            text = ""
    code = main(sys.argv, text, os.environ)
    sys.exit(0 if hook_mode else code)
