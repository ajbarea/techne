"""A GitHub Projects board that tracks work across repos: Idea, Issue, In PR, Merged, Live.

The board is named by a `[board]` table in ~/.claude/techne.toml (`owner`, `number`); without
one every caller does nothing. All GitHub access goes through `gh project`, each call bounded
by a shared Budget. The board's node IDs are cached under ~/.cache/techne. Imports on python3
3.9 (stock macOS), where the PostToolUse hook loads it; reading the config needs tomllib (3.11),
so below that the board is never configured.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:  # loaded by file path: techne_config sits beside this file
    sys.path.append(_HERE)
import techne_config as tc  # noqa: E402

STATUSES = ("Idea", "Issue", "In PR", "Merged", "Live")
STATUS_FIELD = "Status"
GH_TIMEOUT = 10.0
SCOPE_FIX = (
    "gh token lacks the 'project' scope; the user runs: gh auth refresh -h github.com -s project"
)

ITEM_URL = re.compile(r"https://github\.com/([A-Za-z0-9-]+)/([A-Za-z0-9._-]+)/(issues|pull)/(\d+)")
# gh in command position: after ( or {, the env, command, exec, nohup or time wrappers, and
# VAR=value assignments.
_GH = r"^\s*(?:[({]\s*)*(?:(?:env|command|exec|nohup|time)\s+|[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*gh\s+"
_CREATE = re.compile(_GH + r"(?:issue|pr)\s+(?:create|new)(?=[\s)}]|$)")
_API = re.compile(_GH + r"api(?:\s|$)")
_HEREDOC = re.compile(r"(?<!<)<<(-?)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")
_SEPARATORS = ("&&", "||", ";", "|", "&", "\n")
_API_PATH = re.compile(r"""(?:^|[\s'"/])repos/[^/\s'"]+/[^/\s'"]+/(?:issues|pulls)/?(?:$|[\s'"])""")
_METHOD = re.compile(r"""(?:-X\s*|--method[=\s]+)['"]?([A-Za-z]+)""")
_FIELDS = re.compile(r"(?:^|\s)(?:-[fF]|--field|--raw-field|--input)(?:[=\s]|$)")


class BoardError(Exception):
    """A gh call or the board's setup failed; the message is one short reason."""


class TomlError(BoardError):
    """techne.toml is not valid TOML, so no [board] can be read from it."""


@dataclass(frozen=True)
class Board:
    owner: str
    number: int


@dataclass(frozen=True)
class BoardIds:
    project_id: str
    field_id: str
    options: dict  # Status option name -> option ID


class Budget:
    """One deadline shared by every gh call of a run."""

    def __init__(self, seconds: float) -> None:
        self.deadline = time.monotonic() + seconds

    def timeout(self, cap: float = GH_TIMEOUT) -> float:
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise BoardError("ran out of time")
        return min(cap, left)


techne_toml = tc.techne_toml


def load_board(path: Path | None = None) -> Board | None:
    """The configured board, or None when techne.toml or its [board] table is absent, or when
    this python3 cannot read it (one TOML reader, so a config means the same everywhere).

    Raises BoardError when [board] is there but malformed, TomlError when the file is not TOML."""
    path = path or techne_toml()
    try:
        cfg = tc.load(path)
    except (tc.NeedsTomllib, tc.ConfigUnreadable):
        return None
    except tc.ConfigInvalid as exc:
        raise TomlError(str(exc)) from exc
    table = (cfg or {}).get("board")
    if not isinstance(table, dict):
        return None
    owner, number = table.get("owner"), table.get("number")
    if not isinstance(owner, str) or not owner or isinstance(number, bool):
        raise BoardError(f'[board] in {path} needs owner = "<login>" and number = <int>')
    if not isinstance(number, int) or number < 1:
        raise BoardError(f'[board] in {path} needs owner = "<login>" and number = <int>')
    return Board(owner, number)


def _without_heredocs(command: str) -> str:
    """COMMAND with each heredoc body dropped, so the text it feeds a command is not read as
    commands."""
    kept: list[str] = []
    end: tuple[str, bool] | None = None
    for line in command.split("\n"):
        if end is not None:
            word, dash = end
            if (line.lstrip("\t") if dash else line) == word:
                end = None
            continue
        kept.append(line)
        heredoc = _HEREDOC.search(line)
        if heredoc:
            end = (heredoc.group(3), heredoc.group(1) == "-")
    return "\n".join(kept)


def _segments(command: str) -> list[str]:
    """The simple commands of COMMAND, split on &&, ||, ;, |, & and newlines outside quotes."""
    text = _without_heredocs(command)
    parts: list[str] = []
    start = i = 0
    quote = ""
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\" and quote == '"':
                i += 2
                continue
            if ch == quote:
                quote = ""
        elif ch in "'\"":
            quote = ch
        elif ch == "\\":
            i += 2
            continue
        else:
            sep = next((s for s in _SEPARATORS if text.startswith(s, i)), None)
            if sep:
                parts.append(text[start:i])
                i += len(sep)
                start = i
                continue
        i += 1
    parts.append(text[start:])
    return parts


def creates_item(command: str) -> bool:
    """True when the shell command opens an issue or a PR: `gh issue create` or `gh pr create`
    (or their alias `new`), or a `gh api` POST to repos/<owner>/<repo>/issues or /pulls."""
    for segment in _segments(command):
        if _CREATE.search(segment):
            return True
        if _API.search(segment) and _API_PATH.search(segment):
            method = _METHOD.search(segment)
            if method:
                if method.group(1).upper() == "POST":
                    return True
            elif _FIELDS.search(segment):  # gh api posts when given fields and no method
                return True
    return False


def created_urls(output: str, owner: str) -> list[tuple[str, str]]:
    """[(url, "Issue" | "In PR")] for each issue or PR that OUTPUT reports created in a repo of
    OWNER.

    gh prints a created item's URL on a line of its own, and a `gh api` POST answers with one
    JSON object; only those count, so a URL quoted in a body or a listing is never taken."""
    text = output.strip()
    candidates: list[str] = []
    if text[:1] in ("[", "{"):
        try:
            data = json.loads(text)
        except ValueError:
            data = None
        if data is not None:
            if isinstance(data, dict) and isinstance(data.get("html_url"), str):
                candidates.append(data["html_url"])
            text = ""
    if text:
        candidates = [line.strip() for line in text.splitlines()]
    found: list[tuple[str, str]] = []
    for url in candidates:
        m = ITEM_URL.fullmatch(url)
        if not m or m.group(1).lower() != owner.lower():
            continue
        entry = (url, "Issue" if m.group(3) == "issues" else "In PR")
        if entry not in found:
            found.append(entry)
    return found


def gh(args: list[str], budget: Budget, stdin: str | None = None, cap: float = GH_TIMEOUT) -> str:
    """gh's stdout, or BoardError with one short reason."""
    try:
        proc = subprocess.run(
            ["gh", *args],
            input=stdin,
            stdin=None if stdin is not None else subprocess.DEVNULL,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=budget.timeout(cap),
            env={**os.environ, "GH_PROMPT_DISABLED": "1", "NO_COLOR": "1"},
        )
    except FileNotFoundError as exc:
        raise BoardError("gh is not on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise BoardError(f"`gh {' '.join(args[:2])}` timed out") from exc
    except OSError as exc:
        raise BoardError(f"gh could not run ({exc})") from exc
    if proc.returncode != 0:
        raise BoardError(reason(proc.stderr or proc.stdout))
    return proc.stdout


def reason(stderr: str) -> str:
    low = stderr.lower()
    if "scope" in low and "project" in low:
        return SCOPE_FIX
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    return lines[0][:200] if lines else "gh failed"


def gh_json(args: list[str], budget: Budget, cap: float = GH_TIMEOUT):
    """A `gh project` command's --format json output, parsed."""
    out = gh([*args, "--format", "json"], budget, cap=cap)
    try:
        return json.loads(out)
    except ValueError as exc:
        raise BoardError(f"`gh {' '.join(args[:2])}` printed no JSON") from exc


def cache_file(board: Board) -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "techne" / f"board-{board.owner.lower()}-{board.number}.json"


def forget_ids(board: Board) -> None:
    try:
        cache_file(board).unlink()
    except OSError:
        pass


def board_ids(board: Board, budget: Budget, refresh: bool = False) -> BoardIds:
    """The project, Status field and option IDs, from the cache or from gh (then cached)."""
    path = cache_file(board)
    if not refresh:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return BoardIds(data["project_id"], data["field_id"], dict(data["options"]))
        except (OSError, ValueError, KeyError, TypeError):
            pass
    num = str(board.number)
    project = gh_json(["project", "view", num, "--owner", board.owner], budget)
    fields = gh_json(["project", "field-list", num, "--owner", board.owner], budget)
    status = status_field(fields)
    if status is None:
        raise BoardError(f"board {board.owner}#{board.number} has no {STATUS_FIELD} field")
    ids = BoardIds(
        str(project["id"]),
        str(status["id"]),
        {str(o["name"]): str(o["id"]) for o in status.get("options") or []},
    )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")  # sessions may write at once
        tmp.write_text(
            json.dumps(
                {"project_id": ids.project_id, "field_id": ids.field_id, "options": ids.options}
            ),
            encoding="utf-8",
        )
        os.replace(tmp, path)
    except OSError:
        pass  # an uncached board still works, one lookup slower
    return ids


def status_field(fields: dict) -> dict | None:
    for f in fields.get("fields") or []:
        if isinstance(f, dict) and f.get("name") == STATUS_FIELD:
            return f
    return None


def set_status(board: Board, item_id: str, status: str, budget: Budget) -> None:
    """Set the item's Status; on a stale cache, look the IDs up again once."""
    for refresh in (False, True):
        ids = board_ids(board, budget, refresh=refresh)
        option = ids.options.get(status)
        if option is None:
            if refresh:
                raise BoardError(
                    f"board has no {STATUS_FIELD} option '{status}'; run /techne:board init"
                )
            continue
        try:
            gh(
                [
                    "project", "item-edit",
                    "--id", item_id,
                    "--project-id", ids.project_id,
                    "--field-id", ids.field_id,
                    "--single-select-option-id", option,
                ],
                budget,
            )  # fmt: skip
            return
        except BoardError as exc:
            if refresh or str(exc) == SCOPE_FIX:
                raise


def add_item(board: Board, url: str, budget: Budget) -> str:
    """The board item ID for the issue or PR at URL, adding it when absent (gh is idempotent)."""
    item = gh_json(
        ["project", "item-add", str(board.number), "--owner", board.owner, "--url", url], budget
    )
    item_id = item.get("id") if isinstance(item, dict) else None
    if not isinstance(item_id, str):
        raise BoardError("`gh project item-add` returned no item id")
    return item_id


def file_item(board: Board, url: str, status: str, budget: Budget) -> str:
    item_id = add_item(board, url, budget)
    set_status(board, item_id, status, budget)
    return item_id


MEMBERSHIP = """
query($url: URI!) {
  resource(url: $url) {
    ... on Issue { projectItems(first: 50, includeArchived: true) { nodes { project { id } } } }
    ... on PullRequest {
      projectItems(first: 50, includeArchived: true) { nodes { project { id } } }
    }
  }
}
"""


def on_board(board: Board, url: str, budget: Budget) -> bool:
    """Whether the issue or PR at URL is already an item of BOARD (archived ones included)."""
    out = gh(["api", "graphql", "-f", f"query={MEMBERSHIP}", "-f", f"url={url}"], budget)
    try:
        resource = (json.loads(out).get("data") or {}).get("resource") or {}
    except (ValueError, AttributeError) as exc:
        raise BoardError("`gh api graphql` printed no JSON") from exc
    project_id = board_ids(board, budget).project_id
    nodes = (resource.get("projectItems") or {}).get("nodes") or []
    return any(((n or {}).get("project") or {}).get("id") == project_id for n in nodes)


def file_new_item(board: Board, url: str, status: str, budget: Budget) -> bool:
    """Add the issue or PR at URL with STATUS, unless it is on the board already: an existing
    item keeps its Status. True when it was added."""
    if on_board(board, url, budget):
        return False
    file_item(board, url, status, budget)
    return True
