"""A local log of each phylax denial and the same session's next guarded call (techne#399).

On a deny, a hook calls record_denial: one `deny` row goes to denied-calls.jsonl and a
pending record is left for the session. The next call a phylax PreToolUse hook sees from that
session (a Bash/run_command, Agent/Task or email-draft call; other tools run no phylax hook)
adds a `next_call` row under the same id. Commands are redacted and cut to COMMAND_MAX
characters. The log stays on this machine (mode 0600) and is never sent anywhere.

Hooks import this module only on a deny or when pending_any() says a record waits, so a
call with nothing pending pays one access() check. It runs on the system python3, so it
stays compatible with 3.9 (macOS's).
"""

from __future__ import annotations

import json
import os
import re
import time

import jsonl_log
from git_options import STALE_PENDING_SEC, safe_id

COMMAND_MAX = 1000

# (pattern, replacement) pairs, applied in order. They stay strings: re's own cache compiles
# each once per process, on the first redact, so importing this module compiles nothing.
# A Bearer or Basic credential: 16+ token or base64 characters mixing upper and lower case
# with a digit, `+`, `/` or `=`, so "Bearer token-based auth" and "Basic
# authentication/authorization" stay. Every lookahead is bounded and the tail is not, so a
# long token is replaced whole and no pattern retries quadratically.
_T = r"[A-Za-z0-9._~+/-]"
CREDENTIAL = (
    rf"(?-i:(?={_T}{{0,255}}[A-Z])(?={_T}{{0,255}}[a-z])(?={_T}{{0,255}}[0-9+/=])"
    rf"{_T}{{16,255}}{_T}*=*)"
)

TOKEN_PATTERNS = (
    (
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)",
        "[REDACTED]",
    ),
    (r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})", "[REDACTED]"),
    (r"\bglpat-[A-Za-z0-9_-]{20,}", "[REDACTED]"),
    (r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}", "[REDACTED]"),
    (r"\b(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{16,}", "[REDACTED]"),
    (r"\bhf_[A-Za-z0-9]{30,}", "[REDACTED]"),
    (r"\bpypi-AgE[A-Za-z0-9_-]{20,}", "[REDACTED]"),
    (r"\bnpm_[A-Za-z0-9]{36}\b", "[REDACTED]"),
    (r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b", "[REDACTED]"),
    (r"\bxox[abposr]-[A-Za-z0-9-]{10,}", "[REDACTED]"),
    (r"\bAIza[0-9A-Za-z_-]{35}\b", "[REDACTED]"),
    (r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]*", "[REDACTED]"),
    # After a scheme word (token, Bearer) any 8+ character value, whole; a bare value is left,
    # so "Authorization: check scopes" stays.
    (r"(?i)(authorization\s*:\s*[a-z]+\s+)(?!\$)[^\s'\",}]{8,255}[^\s'\",}]*", r"\1[REDACTED]"),
    (r"(?i)\b(Bearer|Basic)\s+" + CREDENTIAL, r"\1 [REDACTED]"),
    (r"(?i)(://)[^\s/@:]{1,256}:[^\s/@]{1,256}@", r"\1[REDACTED]@"),
    (r"(?i)(://)[^\s/@:]{16,256}@", r"\1[REDACTED]@"),  # a token as the whole userinfo
    (
        r"(\bcurl\b[^|;&\n]{0,200}?\s(?:-u|--user|-U|--proxy-user)(?:=|\s+))(['\"]?)"
        r"(?!\[REDACTED)[^\s:'\"=]+:[^\s'\"]*\2",
        r"\1[REDACTED]",
    ),
    (r"(\b(?:mysql|mariadb|mysqldump)\b[^|;&\n]{0,200}?\s-p)[^\s-]\S*", r"\1[REDACTED]"),
    (r"(\bdocker\s+login\b[^|;&\n]{0,200}?\s-p[\s=]+)\S+", r"\1[REDACTED]"),
    (
        r"(\bgh\s+secret\s+set\b[^|;&\n]{0,200}?\s(?:-b|--body)[\s=]+)"
        r"(?:'[^']*(?:'|\Z)|\"[^\"]*(?:\"|\Z)|\S+)",
        r"\1[REDACTED]",
    ),
    (r"(?i)(\bsshpass\s+-p\s*)\S+", r"\1[REDACTED]"),
    (
        r"(\b(?:uv\s+publish|twine\s+upload)\b[^|;&\n]{0,200}?\s-[pt](?:=|\s+))(?!\[REDACTED)\S+",
        r"\1[REDACTED]",
    ),
    (r"(\bnpm\s+config\s+set\s+\S{0,200}_auth(?:Token)?\s+)\S+", r"\1[REDACTED]"),
    (
        # A credential header after -H: PRIVATE-TOKEN, X-API-Key, X-Auth-Token.
        # Authorization has a rule of its own, which knows its scheme word.
        r"(?i)((?:-H|--header)(?:=|\s+)['\"]?(?!(?:proxy-)?authorization\b)[A-Za-z0-9-]{0,64}"
        r"(?:token|api-?key|auth|secret|passw(?:or)?d)[A-Za-z0-9-]{0,64}\s*:\s*)(?!\$)[^\s'\"]+",
        r"\1[REDACTED]",
    ),
    (
        # KEY=value; a quote the cut left open runs to the end. A `$` value is a reference, a
        # literal (None, null, true) no secret, and a quote then a space closes a search
        # pattern (`grep "api_key="`), not a value.
        # A name with secret, token, password or api_key anywhere in it (AWS_SECRET_ACCESS_KEY,
        # GITHUB_TOKEN_VALUE), or ending in pat, pwd, pass, key or auth (GH_PAT, DB_PASS), so
        # PATH and GIT_AUTHOR_NAME stay.
        r"(?i)\b([A-Za-z0-9_-]{0,64}(?:(?:api[_-]?key|passw(?:or)?d|secret|token)[A-Za-z0-9_-]{0,64}"
        r"|(?:pat|pwd|pass|key|auth|credentials?)(?![A-Za-z0-9_-])))\s*="
        r"(?!\s|(?:none|null|nil|true|false|undefined)\b)"
        r"(?:'(?![\s)]|\Z)[^']*(?:'|\Z)|\"(?![\s)]|\Z)[^\"]*(?:\"|\Z)|[^\s'\",}$)][^\s'\",})]*)",
        r"\1=[REDACTED]",
    ),
    (
        # "key": "value" in JSON or a dict's repr: the key is quoted, so prose like
        # "auth: fix" stays.
        r"(?i)(['\"][A-Za-z0-9_-]{0,64}(?:api[_-]?key|passw(?:or)?d|secret|token|auth)['\"])"
        r"\s*:\s*(?:'(?![\s)]|\Z)[^']*(?:'|\Z)|\"(?![\s)]|\Z)[^\"]*(?:\"|\Z)|[^\s'\",})]+)",
        r"\1: [REDACTED]",
    ),
    (
        # A value that is a reference (docker's `--secret id=...`) or a redirect stays. Prose
        # naming the flag ("add --token flag") loses the next word: the safe direction.
        r"(?i)(--[a-z0-9_-]{0,64}(?:api[_-]?key|passw(?:or)?d|secret|token|bearer))\s+(?!id=|src=)"
        r"(?:'[^']*(?:'|\Z)|\"[^\"]*(?:\"|\Z)|[^-\s<>|$]\S*)",
        r"\1 [REDACTED]",
    ),
)


# For each TOKEN_PATTERNS entry, in order, lower-case substrings it cannot match without: a
# pattern runs only when one of them is in the text, so a refusal whose text names no secret
# compiles and scans nothing (compiling every pattern cost ~4 ms per hook process). A test
# holds them conservative: wherever a pattern matches, one of its triggers is present.
_KEY_WORDS = ("key", "pass", "secret", "token", "pat", "pwd", "auth", "credential")
_QUOTED_KEYS = ("key", "password", "passwd", "secret", "token", "auth")
# An entry's alternatives are substrings, or tuples of substrings that must all be present
# (KEY= needs an `=`, so phylax's own "pass model:" runs nothing).
TRIGGERS: tuple[tuple[str | tuple[str, ...], ...], ...] = (
    ("-----begin",),
    ("ghp_", "gho_", "ghu_", "ghs_", "ghr_", "github_pat_"),
    ("glpat-",),
    ("sk-",),
    ("_live_", "_test_"),
    ("hf_",),
    ("pypi-age",),
    ("npm_",),
    ("akia", "asia"),
    ("xox",),
    ("aiza",),
    ("eyj",),
    ("authorization",),
    ("bearer", "basic"),
    ("://",),
    ("://",),
    ("curl",),
    ("mysql", "mariadb"),
    ("docker",),
    ("secret",),
    ("sshpass",),
    ("publish", "twine"),
    ("_auth",),
    ("-h", "--header"),
    tuple((k, "=") for k in _KEY_WORDS),
    tuple(k + q for k in _QUOTED_KEYS for q in "'\""),
    tuple(("--", k) for k in ("key", "pass", "secret", "token", "bearer")),
)


def triggered(low: str, triggers: tuple[str | tuple[str, ...], ...]) -> bool:
    """Whether lower-case text LOW holds one of an entry's TRIGGERS."""
    return any(t in low if isinstance(t, str) else all(x in low for x in t) for t in triggers)


# Patterns anchored on a command name (curl, uv publish) find one flag per pass, so they run
# again, up to 8 passes (more credential flags than a real command carries); their values
# never match [REDACTED] again.
REPEATED = frozenset(p for p, _ in TOKEN_PATTERNS if p.startswith(r"(\bcurl\b") or "publish" in p)


def redact(text: str) -> str:
    """TEXT with known token shapes, private keys, URL and command-line credentials and
    KEY=value secrets replaced. Best effort: a secret in no known shape stays."""
    low = text.lower()  # replacements only remove text, so later triggers stay conservative
    for (pattern, repl), triggers in zip(TOKEN_PATTERNS, TRIGGERS):  # noqa: B905  # 3.9; a test pins the lengths
        if not triggered(low, triggers):
            continue
        text, n = re.subn(pattern, repl, text)
        passes = 1
        while n and pattern in REPEATED and passes < 8:  # bounded: still linear
            text, n = re.subn(pattern, repl, text)
            passes += 1
    return text


def clip(text: str) -> str:
    """TEXT cut to COMMAND_MAX characters, then redacted. It is cut first, to a window of
    COMMAND_MAX + 1024 characters, so a secret that starts before the cut is still seen whole:
    redacting all of a long input first costs time a hook does not have. A word the window cuts
    is dropped, since a token cut short no longer matches its pattern, and a long secret
    redacted earlier can pull it into what is kept."""
    size = len(text)
    window = text[: COMMAND_MAX + 1024]
    if size > len(window):
        kept = re.match(r"(?s).*\s", window)  # up to the window's last whitespace
        window = kept.group(0) if kept else ""
    text = redact(window)[:COMMAND_MAX]
    return text if size <= COMMAND_MAX else text + f"…[{size} chars]"


def state_dir() -> str:
    from git_options import state_home

    return state_home() + "/phylax"


def log_path() -> str:
    return os.path.join(state_dir(), "denied-calls.jsonl")


def pending_dir() -> str:
    return state_dir() + "/pending-denials"


def pending_any() -> bool:
    """Whether any session has a pending denial: the folder exists only while one does."""
    return os.access(pending_dir(), os.F_OK)


def session_id_of(data: dict) -> str:
    return str(
        data.get("session_id") or data.get("sessionId") or data.get("conversationId") or "default"
    )


def actor_of(data: dict) -> str:
    """The session, and within it the subagent: a subagent's calls carry the parent's
    session_id and their own agent_id, so a sibling's call never pairs with its deny."""
    agent = data.get("agent_id")
    return session_id_of(data) + (f".{agent}" if isinstance(agent, str) and agent else "")


def harness_of(data: dict) -> str:
    if isinstance(data.get("toolCall"), dict) or data.get("conversationId"):
        return "agy"
    return "claude-code"


def command_of(data: dict) -> str:
    tool_input = data.get("tool_input") or {}
    tool_args = (data.get("toolCall") or {}).get("args") or {}
    return str(
        tool_input.get("command")
        or tool_args.get("CommandLine")
        or tool_args.get("command")
        or tool_input
    )


def same_action(denied_cmd: str, next_cmd: str, guard: str) -> bool:
    """A word-overlap heuristic: whether the next call runs the same kind of action as the
    denied one (both commit, both push, both write a PR or issue, both kill, a subagent after
    a subagent refusal, a draft after a greeting refusal). It does not judge whether the
    guard's concern was avoided or worked around."""
    words = re.compile(r"[a-z0-9_-]+")
    d_words = set(words.findall(denied_cmd.lower()))
    n_words = set(words.findall(next_cmd.lower()))
    for kind in ({"commit"}, {"push"}, {"pkill", "kill"}):
        if d_words & kind and n_words & kind:
            return True
    if d_words & {"pr", "issue"} and n_words & {"pr", "issue", "api"}:
        return True
    if guard == "require_subagent_model":
        return bool(n_words & {"agent", "task", "subagent_type", "prompt"})
    if guard == "email_greeting":
        return bool(n_words & {"draft", "message", "email", "body"})
    return False


def _pending_file(actor: str) -> str:
    return os.path.join(pending_dir(), safe_id(actor) + ".json")


def _drop_pending(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass
    try:
        os.rmdir(os.path.dirname(path))  # only when no other session's record waits
    except OSError:
        pass


def next_bash_call(payload: str) -> None:
    """git_guards' check for a Bash or run_command call that git_options.pending_record let
    through: link it to this actor's record, and sweep a stale folder. Never raises."""
    try:
        _sweep(pending_dir(), time.time())
        data = json.loads(payload)
        if isinstance(data, dict):
            import hook_output

            check_next_call(data, "run_command" if hook_output.from_agy(data) else "Bash")
    except Exception:
        pass


def shapes_denied(data: dict, denies: list[str]) -> None:
    """Log a command-shape refusal under the shape option that made it. Never raises."""
    try:
        import command_shapes

        record_denial(data, command_shapes.guard_of(denies[0]), "\n".join(denies))
    except Exception:
        pass


def _sweep(folder: str, now: float) -> None:
    """Drop records older than STALE_PENDING_SEC: a session that ended right after a deny
    would otherwise keep the folder, and every call's slow path, alive."""
    try:
        for name in os.listdir(folder):
            path = os.path.join(folder, name)
            try:
                if now - os.stat(path).st_mtime > STALE_PENDING_SEC:
                    os.unlink(path)
            except OSError:
                pass
        os.rmdir(folder)  # only when nothing is left
    except OSError:
        pass


def _row(data: dict, now: float, **fields) -> dict:
    """The fields every row carries, then FIELDS."""
    return {
        "epoch": now,
        **fields,
        "session_id": session_id_of(data),
        "agent_id": data.get("agent_id"),
        "tool_use_id": data.get("tool_use_id"),
        "harness": harness_of(data),
    }


def _create(path: str) -> int:
    """Open PATH new (0600), making its folder (0700) when it is missing."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    try:
        return os.open(path, flags, 0o600)
    except FileNotFoundError:  # no record waits, or another session just removed the folder
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        return os.open(path, flags, 0o600)


def record_denial(data: dict, guard: str, reason: str, command: str | None = None) -> str | None:
    """Log a denied call and leave a pending record for the session's next guarded call.
    Never raises: a log that cannot be written never changes the verdict."""
    try:
        now = time.time()
        call_id = f"{int(now)}-{os.urandom(4).hex()}"
        shown = clip(command if command is not None else command_of(data))
        row = _row(data, now, id=call_id, event="deny", guard=guard, command=shown)
        jsonl_log.append(log_path(), {**row, "reason": clip(reason)})
        path = _pending_file(actor_of(data))
        record = {"id": call_id, "ts": now, "guard": guard, "command": shown}
        fd = _create(path)
        try:
            os.write(fd, json.dumps(record).encode())
        finally:
            os.close(fd)
        _sweep(os.path.dirname(path), now)
        return call_id
    except Exception:
        return None


def check_next_call(data: dict, tool_name: str, command: str | None = None) -> None:
    """When this session has a pending denial, log this call under its id and clear it."""
    try:
        path = _pending_file(actor_of(data))
        try:
            with open(path, "rb") as fh:
                pending = json.loads(fh.read())
        except FileNotFoundError:
            return
        except (OSError, ValueError):
            _drop_pending(path)
            return
        _drop_pending(path)
        now = time.time()
        # Our own record always holds these keys; any other file is dropped unlogged.
        call_id, ts, guard, denied = (pending[k] for k in ("id", "ts", "guard", "command"))
        if not isinstance(ts, (int, float)) or now - ts > STALE_PENDING_SEC:
            return
        shown = clip(command if command is not None else command_of(data))
        row = _row(data, now, id=call_id, event="next_call", tool_name=tool_name, command=shown)
        row["same_action"] = same_action(str(denied), shown, str(guard))
        row["seconds_after"] = round(now - ts, 3)
        jsonl_log.append(log_path(), row)
    except Exception:
        pass
