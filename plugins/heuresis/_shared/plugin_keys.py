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
and never prints a value. Without --plugin it saves each key into every enabled installed plugin
that declares it: this plugin's own install and any other plugin whose manifest lists the key. A
name no installed plugin declares is an error. With --plugin it saves into that plugin only. Exit
codes: 0 stored, 1 nothing stored (the file holds no values), 2 any error (usage, unreadable or
unparsable file, `claude` missing or failing, a configure failure; the other plugins still get
their keys).

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
    description: str  # what the key adds and where to get it; the title when the manifest has none
    group: int = -1  # index into metadata.keyGroups; keys with the same index work together

    @property
    def sentence(self) -> str:
        """The description as a sentence: a capital first, a final period."""
        text = self.description.strip() or self.title
        text = text[:1].upper() + text[1:]
        return text if text[-1:] in (".", "!", "?") else text + "."


class Plugin(NamedTuple):
    name: str
    keys: list[Key]


def read_manifest(plugin_root: Path) -> dict:
    try:
        data = json.loads((plugin_root / ".claude-plugin" / "plugin.json").read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def one_line(value: object) -> str:
    return " ".join(str(value or "").split())


def load_plugin(plugin_root: Path | None = None) -> Plugin:
    """Read plugin.json once: the plugin's name and its keys in manifest order.

    A missing or unreadable manifest gives the folder name and no keys. A manifest that is
    readable but wrong raises ValueError: a sensitive string option whose capitalised name is not
    an environment variable name, or a keyGroups entry that is not a list of two or more distinct
    sensitive key option names, or a key listed in two groups.
    """
    root = plugin_root or ROOT
    manifest = read_manifest(root)
    name = manifest.get("name")
    name = name if isinstance(name, str) and name else root.name
    options = manifest.get("userConfig")
    if not isinstance(options, dict):
        return Plugin(name, [])
    keyed = {}
    for option, spec in options.items():
        if not (
            isinstance(spec, dict)
            and spec.get("sensitive") is True
            and spec.get("type") == "string"
        ):
            continue
        env = option.upper() if isinstance(option, str) else ""
        if not ENV_NAME.fullmatch(env):
            raise ValueError(f"userConfig option {option!r} is sensitive but not a valid key name")
        keyed[option] = (env, spec)
    group_of: dict[str, int] = {}
    meta = manifest.get("metadata")
    groups = meta.get("keyGroups") if isinstance(meta, dict) else None
    if groups is not None and not isinstance(groups, list):
        raise ValueError("metadata.keyGroups must be a list of lists of option names")
    for index, members in enumerate(groups or []):
        if not isinstance(members, list) or len(members) < 2:
            raise ValueError(f"keyGroups[{index}] needs at least two option names")
        for member in members:
            if not isinstance(member, str) or member not in keyed:
                raise ValueError(f"keyGroups[{index}]: {member!r} is not a sensitive key option")
            if member in group_of:
                raise ValueError(f"keyGroups: {member!r} is in more than one group")
            group_of[member] = index
    keys = []
    for option, (env, spec) in keyed.items():
        title = one_line(spec.get("title")) or option
        keys.append(
            Key(
                option,
                env,
                title,
                one_line(spec.get("description")) or title,
                group_of.get(option, -1),
            )
        )
    return Plugin(name, keys)


def load_keys(plugin_root: Path | None = None) -> list[Key]:
    return load_plugin(plugin_root).keys


def group_ids(keys: Sequence[Key]) -> list[int]:
    """The keyGroups indexes in use, in key order. A group is its index, never its label."""
    return list(dict.fromkeys(k.group for k in keys if k.group >= 0))


def members_of(keys: Sequence[Key], group: int) -> list[Key]:
    return [k for k in keys if k.group == group]


def shared_prefix(envs: Sequence[str]) -> str:
    """The leading `_`-separated words every name has, or "" when that is one letter or none."""
    split = [env.split("_") for env in envs]
    words = []
    for i in range(min(len(w) for w in split)):
        if len({w[i] for w in split}) > 1:
            break
        words.append(split[0][i])
    prefix = "_".join(words)
    return prefix if len(prefix) > 1 else ""


def group_labels(keys: Sequence[Key]) -> dict[int, str]:
    """A display label per group: the shared prefix when it is unique and is no key's name,
    else the members joined with `+`. A label is for people; code compares indexes."""
    ids = group_ids(keys)
    envs = {g: [k.env for k in members_of(keys, g)] for g in ids}
    prefixes = {g: shared_prefix(envs[g]) for g in ids}
    taken = {k.env for k in keys}
    labels = {}
    for g in ids:
        prefix = prefixes[g]
        unique = sum(1 for p in prefixes.values() if p == prefix) == 1
        labels[g] = prefix if prefix and unique and prefix not in taken else "+".join(envs[g])
    return labels


def configure_hint(name: str) -> str:
    return f"/plugin configure {name}@{MARKETPLACE}"


def doctor_entries(plugin: Plugin, environ: Mapping[str, str]) -> list[tuple[str, bool, str]]:
    """(name, present, detail) for a setup doctor: one per ungrouped key, one per group."""
    store = f"Store it with {configure_hint(plugin.name)}, then restart."
    keys = plugin.keys

    def entry(name: str, text: str, present: bool) -> tuple[str, bool, str]:
        return name, present, "set" if present else f"not set. {text} {store}"

    found = [entry(k.env, k.sentence, bool(environ.get(k.env))) for k in keys if k.group < 0]
    labels = group_labels(keys)
    for group in group_ids(keys):
        members = members_of(keys, group)
        envs = [k.env for k in members]
        need = "both" if len(envs) == 2 else "all of"
        text = f"{members[0].sentence} Needs {need} {' and '.join(envs)}."
        found.append(entry(labels[group], text, all(environ.get(env) for env in envs)))
    return found


def doctor_entries_for(
    plugin_root: Path, environ: Mapping[str, str]
) -> list[tuple[str, bool, str]]:
    """doctor_entries for the plugin at this root; a manifest that does not load is one line."""
    try:
        return doctor_entries(load_plugin(plugin_root), environ)
    except Exception:
        return [("search keys", False, "plugin.json unreadable")]


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


def start(keys: Sequence[Key], sid: str, data_dir: str, environ: Mapping[str, str]) -> None:
    lines = export_lines(keys, environ)
    if not lines and not os.path.isdir(os.path.join(data_dir, SUBDIR)):
        return  # nothing to write and nothing to clean up
    directory = private_dir(data_dir)
    prune(directory, time.time())
    path = os.path.join(directory, file_name(sid))
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
    """Always 0: whatever goes wrong, a hook never blocks a session."""
    try:
        data_dir = environ.get("CLAUDE_PLUGIN_DATA")
        sid = session_id(stdin_text)
        if not data_dir or sid is None:
            return 0
        directory = os.path.join(data_dir, SUBDIR)
        if mode == "start":
            start(load_keys(plugin_root), sid, data_dir, environ)
        elif os.path.isdir(directory):
            remove(os.path.join(directory, file_name(sid)))
    except Exception:
        pass
    return 0


# the store command


class StoreError(Exception):
    """A message safe to print: it never contains a value."""


def template(keys: Sequence[Key]) -> str:
    blocks = []
    for k in keys:
        lines = [k.description]
        partners = [o.env for o in members_of(keys, k.group) if o is not k] if k.group >= 0 else []
        if partners:
            lines.append(f"Save it together with {' and '.join(partners)}.")
        blocks.append("".join(f"# {line}\n" for line in lines) + f"{k.env}=\n\n")
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
) -> dict[int, tuple[list[str], list[str]]]:
    """Group index to (given, missing) env names, for each group given without all its members."""
    out = {}
    for group in group_ids(keys):
        members = [k.env for k in members_of(keys, group)]
        given = [env for env in members if env in found]
        if given and len(given) < len(members):
            out[group] = (given, [env for env in members if env not in found])
    return out


def real(path: object) -> str:
    try:
        return str(Path(str(path)).resolve())
    except (OSError, RuntimeError, ValueError):
        return ""


def parse_listing(listing: str) -> list[dict]:
    try:
        entries = json.loads(listing)
    except ValueError:
        raise StoreError("could not read `claude plugin list --json`; pass --plugin <id>") from None
    return [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []


def plugin_name_of(entry: dict) -> str | None:
    """The name part of an entry's id, or None when the id is not a non-empty string."""
    ident = entry.get("id")
    return ident.partition("@")[0] if isinstance(ident, str) and ident else None


def own_id(entries: Sequence[dict], name: str, plugin_root: Path) -> str:
    """The entry installed at this script's own plugin root, else the one enabled install of this
    plugin name that has an install path (a synced entry has an empty one)."""
    here = real(plugin_root)
    own = sorted(
        {
            e["id"]
            for e in entries
            if plugin_name_of(e) == name and e.get("installPath") and real(e["installPath"]) == here
        }
    )
    if len(own) == 1:
        return own[0]
    installs = [
        e
        for e in entries
        if plugin_name_of(e) == name and ("installPath" not in e or e["installPath"])
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


def find_plugin_id(listing: str, wanted: str | None, name: str, plugin_root: Path) -> str:
    """The id to configure: --plugin, else this plugin's own install."""
    return wanted or own_id(parse_listing(listing), name, plugin_root)


class Target(NamedTuple):
    id: str
    keys: list[Key]


def other_targets(entries: Sequence[dict], skip: str) -> list[Target]:
    """Every other enabled install whose manifest loads and declares at least one key."""
    found: dict[str, Target] = {}
    for e in entries:
        ident, path = e.get("id"), e.get("installPath")
        if (
            not isinstance(ident, str)
            or not ident
            or ident == skip
            or ident in found
            or not e.get("enabled", True)
            or not isinstance(path, str)
            or not path
        ):
            continue
        try:
            keys = load_plugin(Path(path)).keys
        except Exception:
            continue
        if keys:
            found[ident] = Target(ident, keys)
    return list(found.values())


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


def have_claude() -> bool:
    if shutil.which("claude"):
        return True
    print("error: `claude` is not on PATH; install Claude Code first", file=sys.stderr)
    return False


def store(path: Path, plugin: str | None, plugin_root: Path) -> int:
    try:
        name, keys = load_plugin(plugin_root)
    except ValueError as exc:
        print(f"error: plugin.json: {exc}", file=sys.stderr)
        return 2
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"error: cannot read {path}: {type(exc).__name__}", file=sys.stderr)
        return 2
    warn_if_shared(path)
    targets = [Target(plugin, keys)] if plugin else []
    if not plugin:
        if not have_claude():
            return 2
        try:
            entries = parse_listing(run_claude(["claude", "plugin", "list", "--json"]).stdout)
            ident = own_id(entries, name, plugin_root)
        except StoreError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        targets = [Target(ident, keys), *other_targets(entries, ident)]
    declared = {k.env: k for t in reversed(targets) for k in t.keys}
    try:
        found = parse(text, list(declared.values()))
    except StoreError as exc:
        print(f"error: {path}: {exc}", file=sys.stderr)
        return 2
    if not found:
        print(f"No values in {path}; nothing stored.")
        return 1
    if plugin and not have_claude():
        return 2
    secrets_ = list(found.values())
    stored = failed = False
    for target in targets:
        subset = {env: v for env, v in found.items() if env in {k.env for k in target.keys}}
        if not subset:
            continue
        partial = half_groups(target.keys, subset)
        for given, missing in partial.values():
            msg = f"{' and '.join(given)} given without {' and '.join(missing)}"
            print(f"warning: {target.id}: {msg}", file=sys.stderr)
        option_of = {k.env: k.option for k in target.keys}
        values = {option_of[env]: v for env, v in subset.items()}
        try:
            done = run_claude(
                ["claude", "plugin", "configure", target.id, "--values-stdin"],
                stdin=json.dumps(values),
            )
        except StoreError as exc:
            print(f"error: {target.id}: {exc}", file=sys.stderr)
            failed = True
            continue
        if done.returncode != 0:
            print(
                f"error: claude plugin configure {target.id} exited {done.returncode}",
                file=sys.stderr,
            )
            print(redact(done.stderr or "", secrets_).strip(), file=sys.stderr)
            failed = True
            continue
        stored = True
        print(f"Stored in Claude Code's secure storage for {target.id}: {', '.join(subset)}")
        labels = group_labels(target.keys)
        for group, (_, missing) in partial.items():
            print(f"{labels[group]} stays skipped until {' and '.join(missing)} is saved too.")
    if stored:
        print("Restart Claude Code to apply it.")
        print(f"Delete {path} now, or keep it somewhere private; it holds the keys in plain text.")
    return 2 if failed else 0


def main(argv: Sequence[str], stdin_text: str | None, environ: Mapping[str, str]) -> int:
    """Run a subcommand. `stdin_text` is read only by the hooks, so pass None to skip it."""
    mode = argv[1] if len(argv) > 1 else ""
    if mode in ("start", "end"):
        return run_hook(mode, stdin_text or "", environ, ROOT)
    if mode in ("template", "store"):
        try:
            plugin = load_plugin(ROOT)
        except ValueError as exc:
            print(f"error: plugin.json: {exc}", file=sys.stderr)
            return 2
        if mode == "template":
            print(template(plugin.keys), end="")
            return 0
        ap = argparse.ArgumentParser(prog="plugin_keys.py store")
        ap.add_argument("file", help=".env file holding the keys")
        ap.add_argument(
            "--plugin", help=f"save into this plugin only, such as {plugin.name}@{MARKETPLACE}"
        )
        args = ap.parse_args(list(argv[2:]))
        return store(Path(args.file).expanduser(), args.plugin, ROOT)
    print(__doc__.split("\n\n")[1], file=sys.stderr)
    return 2


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("start", "end"):
        try:
            main(sys.argv, sys.stdin.read(), os.environ)
        except Exception:
            pass  # a hook never blocks a session
        sys.exit(0)
    sys.exit(main(sys.argv, None, os.environ))
