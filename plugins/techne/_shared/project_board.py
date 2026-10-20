"""A GitHub Projects board that tracks work across repos: Idea, Issue, In PR, Merged, Live.

The board is named by a `[board]` table in ~/.claude/techne.toml (`owner`, `number`); without
one every caller does nothing. All GitHub access goes through `gh project`, each call bounded
by a shared Budget. The board's node IDs are cached under ~/.cache/techne. Runs on python3
3.9 (stock macOS), because the PostToolUse hook imports it.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

STATUSES = ("Idea", "Issue", "In PR", "Merged", "Live")
STATUS_FIELD = "Status"
GH_TIMEOUT = 10.0
SCOPE_FIX = (
    "gh token lacks the 'project' scope; the user runs: gh auth refresh -h github.com -s project"
)

ITEM_URL = re.compile(r"https://github\.com/([A-Za-z0-9-]+)/([A-Za-z0-9._-]+)/(issues|pull)/(\d+)")
_SEGMENT_SPLIT = re.compile(r"&&|\|\||[;|\n]")
# gh in command position: after an optional ( or {, `env`, and VAR=value assignments.
_GH = r"^\s*[({]?\s*(?:env\s+)?(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*gh\s+"
_CREATE = re.compile(_GH + r"(?:issue|pr)\s+create(?:\s|$)")
_API = re.compile(_GH + r"api(?:\s|$)")
_API_PATH = re.compile(r"""(?:^|[\s'"/])repos/[^/\s'"]+/[^/\s'"]+/(?:issues|pulls)/?(?:$|[\s'"])""")
_METHOD = re.compile(r"""(?:-X\s*|--method[=\s]+)['"]?([A-Za-z]+)""")
_FIELDS = re.compile(r"(?:^|\s)(?:-[fF]|--field|--raw-field|--input)(?:[=\s]|$)")


class BoardError(Exception):
    """A gh call or the board's setup failed; the message is one short reason."""


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


def techne_toml() -> Path:
    return Path.home() / ".claude" / "techne.toml"


def load_board(path: Path | None = None) -> Board | None:
    """The configured board, or None when techne.toml or its [board] table is absent.

    Raises BoardError when [board] is there but malformed."""
    path = path or techne_toml()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    table = _board_table(text)
    if table is None:
        return None
    owner, number = table.get("owner"), table.get("number")
    if not isinstance(owner, str) or not owner or isinstance(number, bool):
        raise BoardError(f'[board] in {path} needs owner = "<login>" and number = <int>')
    if not isinstance(number, int) or number < 1:
        raise BoardError(f'[board] in {path} needs owner = "<login>" and number = <int>')
    return Board(owner, number)


def _board_table(text: str) -> dict | None:
    try:
        import tomllib  # 3.11+
    except ImportError:
        return _board_table_fallback(text)
    try:
        table = tomllib.loads(text).get("board")
    except tomllib.TOMLDecodeError as exc:
        raise BoardError(f"techne.toml is not valid TOML ({exc})") from exc
    return table if isinstance(table, dict) else None


_HEADER = re.compile(r"^\s*\[\[?\s*([^\]]+?)\s*\]\]?\s*(?:#.*)?$")
_KEY = re.compile(r"""^\s*([A-Za-z0-9_-]+)\s*=\s*("[^"]*"|'[^']*'|[+-]?\d+)\s*(?:#.*)?$""")


def _board_table_fallback(text: str) -> dict | None:
    """The [board] table on a python3 without tomllib: string and integer keys only."""
    table: dict | None = None
    for line in text.splitlines():
        header = _HEADER.match(line)
        if header:
            if table is not None:
                break
            if header.group(1) == "board" and not line.strip().startswith("[["):
                table = {}
            continue
        if table is None:
            continue
        kv = _KEY.match(line)
        if kv:
            value = kv.group(2)
            table[kv.group(1)] = value[1:-1] if value[0] in "\"'" else int(value)
    return table


def creates_item(command: str) -> bool:
    """True when the shell command opens an issue or a PR: `gh issue create`, `gh pr create`,
    or a `gh api` POST to repos/<owner>/<repo>/issues or /pulls."""
    for segment in _SEGMENT_SPLIT.split(command):
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
    """[(url, "Issue" | "In PR")] for each issue or PR URL in OUTPUT whose repo belongs to OWNER.

    A JSON response (gh api) yields only its html_url, so the issues a PR body links are not
    taken for new ones."""
    text = output.strip()
    candidates: list[str] = []
    if text[:1] in ("[", "{"):
        try:
            data = json.loads(text)
        except ValueError:
            data = None
        if data is not None:
            records = data if isinstance(data, list) else [data]
            for record in records:
                if isinstance(record, dict) and isinstance(record.get("html_url"), str):
                    candidates.append(record["html_url"])
            text = ""
    if text:
        candidates = [m.group(0) for m in ITEM_URL.finditer(text)]
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
