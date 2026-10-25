"""Tests for phylax budget mode: budget.py (the hooks) and budget_snapshot.py (the status line
step)."""

from __future__ import annotations

import json
import math
import os
import pathlib
import subprocess
import time

import pytest
from conftest import HOOK_PYTHON, _load, hook_env, hook_handlers

ROOT = pathlib.Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "plugins" / "phylax"
BUDGET = PLUGIN / "hooks" / "budget.py"
SNAPSHOT = PLUGIN / "hooks" / "budget_snapshot.py"
MANIFEST = PLUGIN / ".claude-plugin" / "plugin.json"
HOUR, DAY = 3600, 86400
NOW = 1_800_000_000.0


@pytest.fixture(scope="module")
def bg():
    return _load("phylax_budget", BUDGET)


def thresholds(bg, **over):
    values = {k: str(v) for k, v in over.items()}
    env = {f"CLAUDE_PLUGIN_OPTION_{k.upper()}": v for k, v in values.items()}
    return bg.settings(env)


def window(used, elapsed_fraction, length=7 * DAY, now=NOW):
    """A rate_limits window `used` percent spent with `elapsed_fraction` of it gone."""
    return {"used_percentage": used, "resets_at": now + length * (1 - elapsed_fraction)}


# --- the pace math -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("used", "elapsed", "level"),
    [
        (5, 1, "normal"),
        (10.99, 1, "normal"),  # pace 9.99: just under lean
        (11, 1, "lean"),  # pace 10: lean starts at the margin
        (30, 14.3, "lean"),  # 30% used on day 1 of 7
        (38.99, 14, "lean"),  # pace 24.99
        (39, 14, "frugal"),  # pace 25: frugal starts at the margin
        (66, 28.6, "frugal"),  # the 10-21 run after day 2
        (79.99, 95, "normal"),  # behind pace and under the lean level
        (80, 95, "lean"),  # the lean level alone
        (94.99, 99, "lean"),
        (95, 99, "frugal"),  # the frugal level alone
        (100, 100, "frugal"),
        (0, 0, "normal"),
    ],
)
def test_classify(bg, used, elapsed, level):
    assert bg.classify(used, elapsed, thresholds(bg)) == level


def test_classify_reads_the_options(bg):
    s = thresholds(bg, budget_lean_pace=2, budget_frugal_pace=50, budget_lean_used=99)
    assert bg.classify(13, 10, s) == "lean"  # pace 3 >= 2
    assert bg.classify(40, 10, s) == "lean"  # pace 30 < 50
    assert bg.classify(60, 10, s) == "frugal"


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (window(40, 0.5), (40, 50.0)),
        (window(40, 0.0), (40, 0.0)),  # the window just started
        ({"used_percentage": 40, "resets_at": NOW + 8 * DAY}, (40, 0.0)),  # beyond its length
        (window(40, 0.999), (40, 99.9)),
        ({"used_percentage": "40", "resets_at": NOW + DAY}, None),  # a string is not a number
        ({"used_percentage": True, "resets_at": NOW + DAY}, None),
        ({"used_percentage": math.nan, "resets_at": NOW + DAY}, None),
        ({"used_percentage": 40}, None),
        ({"resets_at": NOW + DAY}, None),
        ({"used_percentage": 40, "resets_at": NOW}, None),  # reset now: Claude Code drops it
        ({"used_percentage": 40, "resets_at": NOW - 1}, None),
        ("40", None),
    ],
)
def test_window_state(bg, data, expected):
    got = bg.window_state("seven_day", data, NOW)
    if expected is None:
        assert got is None
    else:
        assert got is not None
        assert got[0] == expected[0] and got[1] == pytest.approx(expected[1], abs=0.01)


def test_the_five_hour_window_uses_its_own_length(bg):
    used, elapsed = bg.window_state("five_hour", window(20, 0.5, length=5 * HOUR), NOW)
    assert (used, round(elapsed)) == (20, 50)


def test_an_unknown_window_is_ignored(bg):
    assert bg.window_state("spend_limit", window(99, 0.1), NOW) is None


def state(tmp_path, limits, age=0.0, name="phylax-budget.json"):
    path = tmp_path / name
    path.write_text(json.dumps({"rate_limits": limits, "written_at": NOW - age}))
    os.utime(path, (NOW - age, NOW - age))
    return path


def level_of(bg, path, now=NOW, **over):
    env = {f"CLAUDE_PLUGIN_OPTION_{k.upper()}": str(v) for k, v in over.items()}
    env["CLAUDE_PLUGIN_OPTION_BUDGET_STATE_FILE"] = str(path)
    return bg.level(env, now)


def test_the_higher_window_decides(bg, tmp_path):
    path = state(
        tmp_path,
        {"five_hour": window(90, 0.4, 5 * HOUR), "seven_day": window(10, 0.5)},
    )
    found = level_of(bg, path)
    assert found.level == "frugal"
    assert [w.name for w in found.windows] == ["five_hour", "seven_day"]


def test_a_seat_with_only_the_five_hour_window_still_reads(bg, tmp_path):
    path = state(tmp_path, {"five_hour": window(40, 0.2, 5 * HOUR)})
    assert level_of(bg, path).level == "lean"


@pytest.mark.parametrize(
    "content",
    ["", "not json", "[1, 2]", '{"rate_limits": "x"}', '{"rate_limits": {}}', '{"other": 1}'],
)
def test_an_unreadable_snapshot_reads_normal(bg, tmp_path, content):
    path = tmp_path / "s.json"
    path.write_text(content)
    os.utime(path, (NOW, NOW))
    assert level_of(bg, path).level == "normal"


def test_a_missing_snapshot_reads_normal(bg, tmp_path):
    found = level_of(bg, tmp_path / "absent.json")
    assert found.level == "normal" and found.note.startswith("no snapshot")


def test_a_stale_snapshot_reads_normal(bg, tmp_path):
    limits = {"seven_day": window(90, 0.5)}
    assert level_of(bg, state(tmp_path, limits, age=bg.MAX_AGE - 60)).level == "frugal"
    found = level_of(bg, state(tmp_path, limits, age=bg.MAX_AGE + 60))
    assert found.level == "normal" and "old" in found.note


def test_a_snapshot_from_the_future_is_not_stale(bg, tmp_path):
    # A clock that moved back must not hide the reading.
    path = state(tmp_path, {"seven_day": window(90, 0.5)}, age=-600)
    assert level_of(bg, path).level == "frugal"


def test_the_raw_statusline_payload_works_as_a_snapshot(bg, tmp_path):
    payload = {"model": {"id": "x"}, "rate_limits": {"seven_day": window(60, 0.2)}}
    path = tmp_path / "raw.json"
    path.write_text(json.dumps(payload))
    os.utime(path, (NOW, NOW))
    assert level_of(bg, path).level == "frugal"


def test_the_level_follows_the_clock_until_the_reset(bg, tmp_path):
    limits = {"seven_day": {"used_percentage": 70, "resets_at": NOW + 3 * DAY}}
    path = state(tmp_path, limits)
    assert level_of(bg, path).level == "lean"  # 57% of the window gone: pace 13
    assert level_of(bg, path, now=NOW + DAY).level == "normal"  # 71% gone: pace -1
    assert level_of(bg, path, now=NOW + 3 * DAY).level == "normal"  # reset passed


# --- options -----------------------------------------------------------------------


@pytest.mark.parametrize("value", ["abc", "nan", "inf", "-5", "101", " "])
def test_a_bad_threshold_falls_back_and_is_named(bg, value):
    s = thresholds(bg, budget_lean_pace=value)
    assert s.lean_pace == bg.DEFAULTS["budget_lean_pace"]
    assert ("budget_lean_pace" in s.bad) == (value.strip() != "")


def test_an_unset_threshold_is_the_default(bg):
    s = bg.settings({"CLAUDE_PLUGIN_OPTION_BUDGET_LEAN_PACE": "${user_config.budget_lean_pace}"})
    assert s.lean_pace == bg.DEFAULTS["budget_lean_pace"] and not s.bad


def test_the_state_file_defaults_per_config_dir(bg, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert bg.settings({}).path == str(tmp_path / ".claude" / "phylax-budget.json")
    env = {"CLAUDE_CONFIG_DIR": str(tmp_path / "personal")}
    assert bg.settings(env).path == str(tmp_path / "personal" / "phylax-budget.json")
    env["CLAUDE_PLUGIN_OPTION_BUDGET_STATE_FILE"] = "~/x.json"
    assert bg.settings(env).path == str(tmp_path / "x.json")


def test_manifest_options_match_the_defaults(bg):
    config = json.loads(MANIFEST.read_text())["userConfig"]
    assert config["budget_mode"]["type"] == "boolean"
    assert config["budget_mode"]["default"] is False
    for key, default in bg.DEFAULTS.items():
        assert config[key]["type"] == "number" and config[key]["default"] == default, key
        assert config[key]["min"] == 0 and config[key]["max"] == 100, key
    assert config["budget_state_file"]["type"] == "string"
    assert config["budget_state_file"]["default"] == ""


# --- the hooks, run as Claude Code runs them ------------------------------------------


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    (h / ".claude").mkdir(parents=True)
    return h


def run(home, sub, stdin, data=None, limits=None, role="background", **extra):
    """budget.py SUB under budget_mode in a session of ROLE, with LIMITS saved as the
    account's snapshot."""
    if limits is not None:
        path = home / ".claude" / "phylax-budget.json"
        path.write_text(json.dumps({"rate_limits": limits, "written_at": time.time()}))
    env = hook_env(
        ["budget_mode"],
        drop=("CLAUDE_CONFIG_DIR", "CLAUDE_PLUGIN_DATA", "CLAUDE_PLUGIN_OPTION_", "PHYLAX_BUDGET"),
        HOME=str(home),
        **({"PHYLAX_BUDGET_ROLE": role} if role else {}),
        **({"CLAUDE_PLUGIN_DATA": str(data)} if data else {}),
        **extra,
    )
    return subprocess.run(
        [HOOK_PYTHON, str(BUDGET), sub],
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=30,
    )


def now_window(used, elapsed_fraction, length=7 * DAY):
    return window(used, elapsed_fraction, length, now=time.time())


LEAN = {"seven_day": now_window(40, 0.2)}
FRUGAL = {"seven_day": now_window(70, 0.2)}
NORMAL = {"seven_day": now_window(5, 0.5)}


def out(proc) -> dict | None:
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)["hookSpecificOutput"] if proc.stdout.strip() else None


def session(sid="s1", event="SessionStart"):
    return json.dumps({"session_id": sid, "hook_event_name": event, "cwd": "/x"})


@pytest.mark.parametrize(("limits", "says"), [(LEAN, "lean"), (FRUGAL, "frugal")])
def test_session_start_names_the_level_and_the_routing(home, tmp_path, limits, says):
    found = out(run(home, "session", session(), data=tmp_path / "data", limits=limits))
    assert found and found["hookEventName"] == "SessionStart"
    text = found["additionalContext"]
    assert f"budget mode: {says}" in text and "Sonnet implements" in text
    assert ("capped at 2" in text) == (says == "frugal")
    assert ("final review" in text) == (says == "frugal")


def test_session_start_is_silent_when_normal(home, tmp_path):
    assert out(run(home, "session", session(), data=tmp_path / "d", limits=NORMAL)) is None
    assert out(run(home, "session", session(), data=tmp_path / "d")) is None  # no snapshot


def test_session_start_keeps_the_snapshot_copy_current(home, tmp_path):
    data = tmp_path / "data"
    run(home, "session", session(), data=data)
    copy = data / "budget_snapshot.py"
    assert copy.read_bytes() == SNAPSHOT.read_bytes()
    copy.write_text("old")
    run(home, "session", session(), data=data)
    assert copy.read_bytes() == SNAPSHOT.read_bytes()


def test_a_prompt_speaks_only_when_the_level_changes(home, tmp_path):
    data = tmp_path / "data"
    assert out(run(home, "session", session(), data=data, limits=LEAN))
    prompt = session(event="UserPromptSubmit")
    assert out(run(home, "prompt", prompt, data=data, limits=LEAN)) is None
    found = out(run(home, "prompt", prompt, data=data, limits=FRUGAL))
    assert found and found["hookEventName"] == "UserPromptSubmit"
    assert "budget mode: frugal" in found["additionalContext"]
    assert out(run(home, "prompt", prompt, data=data, limits=FRUGAL)) is None
    back = out(run(home, "prompt", prompt, data=data, limits=NORMAL))
    assert back and "back to normal" in back["additionalContext"]
    assert out(run(home, "prompt", prompt, data=data, limits=NORMAL)) is None


def test_without_a_place_to_remember_a_prompt_stays_quiet(home):
    # SessionStart already named the level; repeating it on every prompt would cost tokens.
    assert out(run(home, "prompt", session(event="UserPromptSubmit"), limits=LEAN)) is None


def test_old_remembered_levels_are_pruned(home, tmp_path):
    data = tmp_path / "data"
    seen = data / "budget-seen"
    seen.mkdir(parents=True)
    (seen / "old").write_text("lean")
    (seen / "recent").write_text("lean")
    ancient = time.time() - 8 * DAY
    os.utime(seen / "old", (ancient, ancient))
    run(home, "session", session("now"), data=data, limits=NORMAL)
    assert sorted(p.name for p in seen.iterdir()) == ["now", "recent"]


def test_crossed_thresholds_are_reported(bg):
    s = thresholds(bg, budget_lean_pace=30, budget_lean_used=99)
    assert len(s.conflicts) == 2
    assert not thresholds(bg).conflicts


def test_a_prompt_in_a_session_never_seen_starts_from_normal(home, tmp_path):
    prompt = session("new", event="UserPromptSubmit")
    data = tmp_path / "data"
    assert out(run(home, "prompt", prompt, data=data, limits=NORMAL)) is None
    assert out(run(home, "prompt", session("new2", "UserPromptSubmit"), data=data, limits=LEAN))


def test_sessions_are_tracked_apart(home, tmp_path):
    data = tmp_path / "data"
    run(home, "session", session("a"), data=data, limits=LEAN)
    found = out(run(home, "prompt", session("b", "UserPromptSubmit"), data=data, limits=LEAN))
    assert found  # b never saw lean


@pytest.mark.parametrize("sid", ["", "../x", "a/b", None, 5])
def test_an_odd_session_id_is_not_a_path(home, tmp_path, sid):
    data = tmp_path / "data"
    payload = json.dumps({"session_id": sid, "hook_event_name": "UserPromptSubmit"})
    proc = run(home, "prompt", payload, data=data, limits=LEAN)
    assert (proc.returncode, proc.stdout) == (0, "")  # no record, so no repeat on each prompt
    assert not (tmp_path / "x").exists() and not (data / "x").exists()


def agent(**tool_input):
    tool_input.setdefault("prompt", "p")
    tool_input.setdefault("description", "implement the parser")
    tool_input.setdefault("subagent_type", "general-purpose")
    return json.dumps({"tool_name": "Agent", "tool_input": tool_input, "session_id": "s"})


@pytest.mark.parametrize(
    "model",
    ["opus", "Opus", "claude-opus-5-5", "opus[1m]", " opus ", "fable", "claude-fable-5-1", "best"],
)
def test_frugal_runs_an_opus_call_on_sonnet(home, model):
    found = out(run(home, "agent", agent(model=model), limits=FRUGAL))
    assert found and found["hookEventName"] == "PreToolUse"
    assert found["updatedInput"] == {
        **json.loads(agent(model=model))["tool_input"],
        "model": "sonnet",
    }
    assert "permissionDecision" not in found  # the permission flow is left alone
    assert "final review" in found["additionalContext"]


@pytest.mark.parametrize(
    "description", ["final review of #204", "Final Review round 3", "opus final  review"]
)
def test_a_final_review_keeps_opus(home, description):
    assert (
        out(run(home, "agent", agent(model="opus", description=description), limits=FRUGAL)) is None
    )


@pytest.mark.parametrize(
    "model", ["sonnet", "haiku", "claude-sonnet-5-5", "", None, 5, "bestest", "claude-opusx"]
)
def test_other_models_are_untouched(home, model):
    fields = {} if model is None else {"model": model}
    assert out(run(home, "agent", agent(**fields), limits=FRUGAL)) is None


@pytest.mark.parametrize("limits", [LEAN, NORMAL, None])
def test_below_frugal_an_opus_call_is_untouched(home, limits):
    assert out(run(home, "agent", agent(model="opus"), limits=limits)) is None


@pytest.mark.parametrize("tool", ["Task", "Bash"])
def test_only_agent_calls_are_rewritten(home, tool):
    payload = json.loads(agent(model="opus"))
    payload["tool_name"] = tool
    found = out(run(home, "agent", json.dumps(payload), limits=FRUGAL))
    assert (found is not None) == (tool == "Task")


@pytest.mark.parametrize(
    "stdin", ["", "not json", "[1]", '{"tool_name": "Agent", "tool_input": 5}']
)
def test_an_unreadable_payload_goes_ahead(home, stdin):
    proc = run(home, "agent", stdin, limits=FRUGAL)
    assert (proc.returncode, proc.stdout) == (0, "")


def test_an_unknown_mode_fails_loudly(home):
    proc = run(home, "nope", "{}")
    assert proc.returncode == 2 and "nope" in proc.stderr


def test_the_agent_hook_reads_no_snapshot_for_a_call_it_cannot_change(bg, monkeypatch):
    def boom(*_args):
        raise AssertionError("read the snapshot")

    monkeypatch.setattr(bg, "level", boom)
    assert bg.rewrite({"tool_name": "Agent", "tool_input": {"model": "sonnet"}}, {}) is None
    tool_input = {"model": "opus", "description": "final review"}
    assert bg.rewrite({"tool_name": "Agent", "tool_input": tool_input}, {}) is None


# --- hooks.json --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("event", "matcher", "mode"),
    [
        ("SessionStart", None, "session"),
        ("UserPromptSubmit", None, "prompt"),
        ("PreToolUse", "Agent|Task", "agent"),
    ],
)
def test_hooks_json_runs_each_mode_under_the_option(event, matcher, mode):
    commands = [h["command"] for h in hook_handlers("phylax", event, matcher)]
    ours = [c for c in commands if "budget.py" in c]
    assert len(ours) == 1, commands
    assert '"$CLAUDE_PLUGIN_OPTION_BUDGET_MODE" in true)' in ours[0]
    assert ours[0].rstrip().endswith(f'budget.py" {mode} ;; esac')


# --- the statusLine step -------------------------------------------------------------


def snap(stdin: bytes, home, *args, **extra):
    env = {**os.environ, "HOME": str(home), **extra}
    env.pop("CLAUDE_CONFIG_DIR", None) if "CLAUDE_CONFIG_DIR" not in extra else None
    return subprocess.run(
        [HOOK_PYTHON, str(SNAPSHOT), *args],
        input=stdin,
        capture_output=True,
        env=env,
        check=False,
        timeout=30,
    )


PAYLOAD = {
    "model": {"id": "m"},
    "rate_limits": {"seven_day": {"used_percentage": 41.2, "resets_at": 1}},
}


def test_the_snapshot_passes_stdin_through_and_saves_the_limits(home):
    raw = json.dumps(PAYLOAD).encode() + b"\n"
    proc = snap(raw, home)
    assert proc.returncode == 0 and proc.stdout == raw
    saved = json.loads((home / ".claude" / "phylax-budget.json").read_text())
    assert saved["rate_limits"] == PAYLOAD["rate_limits"]
    assert abs(saved["written_at"] - time.time()) < 60


def test_the_snapshot_follows_the_config_dir_and_an_argument(home, tmp_path):
    raw = json.dumps(PAYLOAD).encode()
    snap(raw, home, CLAUDE_CONFIG_DIR=str(tmp_path / "personal"))
    assert (tmp_path / "personal" / "phylax-budget.json").exists()
    snap(raw, home, str(tmp_path / "elsewhere" / "b.json"))
    assert (tmp_path / "elsewhere" / "b.json").exists()


@pytest.mark.parametrize(
    "raw", [b"", b"not json", b"[1]", json.dumps({"model": {}}).encode(), b'{"rate_limits": {}}']
)
def test_the_snapshot_keeps_the_last_file_without_new_limits(home, raw):
    target = home / ".claude" / "phylax-budget.json"
    target.write_text("previous")
    proc = snap(raw, home)
    assert proc.returncode == 0 and proc.stdout == raw
    assert target.read_text() == "previous"


def test_the_snapshot_never_breaks_the_status_line(home, tmp_path):
    blocked = tmp_path / "file"
    blocked.write_text("x")  # a file where the folder should be
    raw = json.dumps(PAYLOAD).encode()
    proc = snap(raw, home, str(blocked / "b.json"))
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, raw, b"")
    assert not list(tmp_path.glob("**/.phylax-*"))  # no temp file left behind


def test_the_snapshot_and_the_reader_agree(bg, home, monkeypatch):
    payload = {"rate_limits": {"seven_day": now_window(70, 0.2)}}
    snap(json.dumps(payload).encode(), home)
    monkeypatch.setenv("HOME", str(home))
    assert bg.level({}, time.time()).level == "frugal"


def test_an_unchanged_recent_reading_is_not_rewritten(home):
    raw = json.dumps(PAYLOAD).encode()
    snap(raw, home)
    target = home / ".claude" / "phylax-budget.json"
    first = target.stat().st_mtime_ns
    snap(raw, home)
    assert target.stat().st_mtime_ns == first
    changed = {**PAYLOAD, "rate_limits": {"seven_day": {"used_percentage": 50, "resets_at": 1}}}
    snap(json.dumps(changed).encode(), home)
    assert json.loads(target.read_text())["rate_limits"]["seven_day"]["used_percentage"] == 50


def test_an_unchanged_old_reading_is_rewritten(home):
    raw = json.dumps(PAYLOAD).encode()
    snap(raw, home)
    target = home / ".claude" / "phylax-budget.json"
    old = time.time() - 600
    os.utime(target, (old, old))
    snap(raw, home)
    assert target.stat().st_mtime > old + 60


def test_the_recommended_chain_keeps_the_status_line_when_the_copy_is_missing(tmp_path):
    raw = json.dumps(PAYLOAD)
    line = f"{{ python3 {tmp_path / 'absent.py'} 2>/dev/null || cat; }} | cat"
    proc = subprocess.run(
        ["sh", "-c", line], input=raw, capture_output=True, text=True, check=False
    )
    assert proc.stdout == raw


# --- who pays: the session's role and the overrides ---------------------------------------


@pytest.mark.parametrize(
    ("role", "asked", "applies"),
    [
        ("background", "", True),
        ("Background", "", True),
        ("", "", False),  # an interactive session keeps normal routing
        ("interactive", "", False),
        ("", "on", True),  # unless it opts in
        ("background", "normal", False),  # PHYLAX_BUDGET=normal exempts any session
        ("", "normal", False),
    ],
)
def test_who_budget_mode_routes(bg, tmp_path, role, asked, applies):
    env = {"PHYLAX_BUDGET_ROLE": role, "PHYLAX_BUDGET": asked, "CLAUDE_CONFIG_DIR": str(tmp_path)}
    assert bg.role(env, NOW).applies is applies


def pause_file(tmp_path, until):
    (tmp_path / "phylax-budget-override.json").write_text(json.dumps({"until": until}))


def test_a_pause_returns_opted_in_sessions_to_normal_until_it_ends(bg, tmp_path):
    env = {"PHYLAX_BUDGET": "on", "CLAUDE_CONFIG_DIR": str(tmp_path)}
    pause_file(tmp_path, NOW + 60)
    who = bg.role(env, NOW)
    assert not who.applies and who.reason.startswith("paused until")
    assert bg.role(env, NOW + 61).applies  # expired


def test_a_pause_leaves_background_agents_paying(bg, tmp_path):
    pause_file(tmp_path, NOW + 3600)
    env = {"PHYLAX_BUDGET_ROLE": "background", "CLAUDE_CONFIG_DIR": str(tmp_path)}
    assert bg.role(env, NOW).applies


@pytest.mark.parametrize(
    "content", ["not json", '{"until": "soon"}', "[]", '{"until": 1e999}', '{"until": 1e300}']
)
def test_an_unreadable_pause_is_no_pause(bg, tmp_path, content):
    (tmp_path / "phylax-budget-override.json").write_text(content)
    env = {"PHYLAX_BUDGET": "on", "CLAUDE_CONFIG_DIR": str(tmp_path)}
    assert bg.role(env, NOW).applies


@pytest.mark.parametrize("sub", ["session", "agent"])
def test_an_interactive_session_is_left_alone_whatever_the_level(home, tmp_path, sub):
    stdin = session() if sub == "session" else agent(model="opus")
    assert out(run(home, sub, stdin, data=tmp_path / "d", limits=FRUGAL, role="")) is None


def pause_cli(home, *args, **extra):
    env = hook_env(drop=("CLAUDE_CONFIG_DIR", "PHYLAX_BUDGET"), HOME=str(home), **extra)
    return subprocess.run(
        [HOOK_PYTHON, str(BUDGET), *args], capture_output=True, text=True, env=env, timeout=30
    )


def test_budget_off_pauses_for_four_hours_and_on_ends_it(home):
    proc = pause_cli(home, "off", PHYLAX_BUDGET="on")
    assert (
        proc.returncode == 0 and "paused until" in proc.stdout and "normal routing" in proc.stdout
    )
    until = json.loads((home / ".claude" / "phylax-budget-override.json").read_text())["until"]
    assert abs(until - time.time() - 4 * HOUR) < 60
    proc = pause_cli(home, "on", PHYLAX_BUDGET="on")
    assert "not paused" in proc.stdout and "routed by budget mode" in proc.stdout
    assert not (home / ".claude" / "phylax-budget-override.json").exists()
    assert pause_cli(home, "on").returncode == 0  # already on


def test_budget_off_takes_hours(home):
    pause_cli(home, "off", "1.5")
    until = json.loads((home / ".claude" / "phylax-budget-override.json").read_text())["until"]
    assert abs(until - time.time() - 1.5 * HOUR) < 60


@pytest.mark.parametrize("hours", ["0", "-1", "abc", "169", "nan"])
def test_budget_off_refuses_bad_hours(home, hours):
    proc = pause_cli(home, "off", hours)
    assert proc.returncode == 2 and "more than 0 and at most 168" in proc.stdout
    assert not (home / ".claude" / "phylax-budget-override.json").exists()


def test_status_names_the_role(home):
    proc = pause_cli(home, "status", PHYLAX_BUDGET_ROLE="background")
    assert "this session is background, routed by budget mode" in proc.stdout


@pytest.mark.parametrize("source", ["resume", "compact"])
def test_a_resumed_session_hears_the_level_fell(home, tmp_path, source):
    data = tmp_path / "data"
    assert out(run(home, "session", session(), data=data, limits=LEAN))
    resumed = json.dumps({"session_id": "s1", "hook_event_name": "SessionStart", "source": source})
    back = out(run(home, "session", resumed, data=data, limits=NORMAL))
    assert back and "back to normal" in back["additionalContext"]
    fresh = json.dumps({"session_id": "s2", "hook_event_name": "SessionStart", "source": "startup"})
    assert out(run(home, "session", fresh, data=data, limits=NORMAL)) is None


# --- a hostile snapshot ------------------------------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        '{"rate_limits": {"seven_day": {"used_percentage": ' + "9" * 400 + ', "resets_at": 2e9}}}',
    ],
)
def test_a_hostile_snapshot_reads_normal(bg, tmp_path, content):
    path = tmp_path / "s.json"
    path.write_text(content)
    os.utime(path, (NOW, NOW))
    assert level_of(bg, path).level == "normal"


def test_a_fifo_snapshot_does_not_block(bg, tmp_path):
    path = tmp_path / "s.json"
    os.mkfifo(path)
    os.utime(path, (NOW, NOW))
    found = level_of(bg, path)
    assert found.level == "normal" and "unreadable" in found.note


def test_pruning_never_deletes_through_a_symlink(home, tmp_path):
    data = tmp_path / "data"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "precious").write_text("x")
    ancient = time.time() - 30 * DAY
    os.utime(elsewhere / "precious", (ancient, ancient))
    data.mkdir()
    (data / "budget-seen").symlink_to(elsewhere, target_is_directory=True)
    run(home, "session", session(), data=data, limits=NORMAL)
    assert (elsewhere / "precious").exists()


def test_pruning_touches_only_session_files(home, tmp_path):
    seen = tmp_path / "data" / "budget-seen"
    seen.mkdir(parents=True)
    (seen / "notes.txt").write_text("x")
    (seen / "sub").mkdir()
    ancient = time.time() - 30 * DAY
    for name in ("notes.txt", "sub"):
        os.utime(seen / name, (ancient, ancient))
    run(home, "session", session(), data=tmp_path / "data", limits=NORMAL)
    assert (seen / "notes.txt").exists() and (seen / "sub").exists()


def test_a_deeply_nested_snapshot_reads_normal_on_the_hook_python(home):
    # python3 3.9's json raises RecursionError here; later ones may parse it.
    path = home / ".claude" / "phylax-budget.json"
    path.write_text("[" * 32000 + "]" * 32000)
    proc = run(home, "agent", agent(model="opus"))
    assert (proc.returncode, proc.stdout) == (0, ""), proc.stderr


def test_pruning_skips_a_file_that_is_not_a_session(home, tmp_path):
    seen = tmp_path / "data" / "budget-seen"
    seen.mkdir(parents=True)
    (seen / "notes.txt").write_text("x")
    ancient = time.time() - 30 * DAY
    os.utime(seen / "notes.txt", (ancient, ancient))
    run(home, "session", session(), data=tmp_path / "data", limits=NORMAL)
    assert (seen / "notes.txt").exists()


def test_a_pause_too_far_off_to_be_ours_does_not_break_status(home):
    (home / ".claude" / "phylax-budget-override.json").write_text('{"until": 1e300}')
    proc = pause_cli(home, "status", PHYLAX_BUDGET="on")
    assert proc.returncode == 0 and "not paused" in proc.stdout, proc.stderr


@pytest.mark.parametrize("sub", ["on", "off"])
def test_a_folder_at_the_pause_path_is_reported_not_raised(home, sub):
    (home / ".claude" / "phylax-budget-override.json").mkdir()
    proc = pause_cli(home, sub)
    assert proc.returncode == 1 and "Traceback" not in proc.stderr
    assert "could not" in proc.stdout


def test_no_seen_path_reads_normal_not_a_file_named_none(bg, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "None").write_text("frugal")
    assert bg.read_seen(None) == "normal"


def test_pruning_looks_at_seen_max_entries_at_most(bg, tmp_path, monkeypatch):
    seen = tmp_path / "budget-seen"
    seen.mkdir()
    for n in range(5):
        (seen / f"s{n}").write_text("lean")
        os.utime(seen / f"s{n}", (NOW - 30 * DAY, NOW - 30 * DAY))
    monkeypatch.setattr(bg, "SEEN_MAX", 2)
    bg.prune_seen({"CLAUDE_PLUGIN_DATA": str(tmp_path)}, NOW)
    assert len(list(seen.iterdir())) == 3


def test_frugal_names_every_model_it_moves(bg):
    assert "names Opus or Fable runs on Sonnet" in bg.FRUGAL_EXTRA


def reading_of(home):
    return json.loads((home / ".claude" / "phylax-budget.json").read_text())["rate_limits"]


def test_an_older_reading_never_lowers_a_newer_one(home):
    # An idle session re-renders its status line with the usage of its last response.
    first = {"seven_day": {"used_percentage": 70, "resets_at": 2e9}}
    snap(json.dumps({"rate_limits": first}).encode(), home)
    lower = {"seven_day": {"used_percentage": 40, "resets_at": 2e9}}
    snap(json.dumps({"rate_limits": lower}).encode(), home)
    assert reading_of(home)["seven_day"]["used_percentage"] == 70
    earlier = {"seven_day": {"used_percentage": 90, "resets_at": 2e9 - 7 * DAY}}
    snap(json.dumps({"rate_limits": earlier}).encode(), home)
    assert reading_of(home) == first  # a window already past
    later = {"seven_day": {"used_percentage": 3, "resets_at": 2e9 + 7 * DAY}}
    snap(json.dumps({"rate_limits": later}).encode(), home)
    assert reading_of(home)["seven_day"] == later["seven_day"]  # the next window


def test_a_window_missing_from_a_reading_is_kept(home):
    both = {
        "five_hour": {"used_percentage": 20, "resets_at": 2e9},
        "seven_day": {"used_percentage": 30, "resets_at": 2e9},
    }
    snap(json.dumps({"rate_limits": both}).encode(), home)
    one = {"seven_day": {"used_percentage": 31, "resets_at": 2e9}}
    snap(json.dumps({"rate_limits": one}).encode(), home)
    assert reading_of(home) == {**both, **one}


def test_a_fifo_at_the_snapshot_path_does_not_block_the_status_line(home):
    target = home / ".claude" / "phylax-budget.json"
    os.mkfifo(target)
    raw = json.dumps(PAYLOAD).encode()
    proc = snap(raw, home)
    assert (proc.returncode, proc.stdout) == (0, raw)
