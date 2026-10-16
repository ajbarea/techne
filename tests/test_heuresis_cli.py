"""heuresis CLI entry point."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import heuresis
import pytest
from heuresis import cli


def test_version_command_prints_the_package_version(capsys):
    assert cli.main(["version"]) == 0
    assert capsys.readouterr().out.strip() == heuresis.__version__


def test_unknown_command_exits_with_usage_error(capsys):
    try:
        cli.main(["no-such-command"])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("argparse should reject an unknown command")


def init_ideas(tmp_path: Path) -> Path:
    repos = tmp_path / "repos"
    (repos / "papers").mkdir(parents=True)
    ideas = tmp_path / "ideas-repo"
    assert cli.main(["init", str(ideas), "--repos-root", str(repos)]) == 0
    for key, value in (
        ("user.email", "t@example.com"),
        ("user.name", "t"),
        ("commit.gpgsign", "false"),
    ):
        subprocess.run(["git", "-C", str(ideas), "config", key, value], check=True)
    return ideas


def test_capture_rejects_empty_text(tmp_path: Path, capsys):
    ideas = init_ideas(tmp_path)
    assert cli.main(["capture", "--ideas", str(ideas), "   "]) == 2


def test_capture_then_apply_runs_the_rules(tmp_path: Path, capsys):
    ideas = init_ideas(tmp_path)
    capsys.readouterr()
    assert cli.main(["capture", "--ideas", str(ideas), "A tool that triages ideas"]) == 0
    idea_id = capsys.readouterr().out.strip()
    run = ideas / "runs" / idea_id
    restated = json.dumps({"restated": "A triage tool.", "queries": ["idea triage"]})
    assert cli.main(["restate", "--ideas", str(ideas), "--id", idea_id, "--json", restated]) == 0
    scout = {
        "group": "papers",
        "queries": ["idea triage"],
        "records": [
            {
                "title": "Rival",
                "url": "https://r.example",
                "source": "openalex",
                "kind": "paper",
                "text": "a quoted passage long enough",
            }
        ],
        "coverage": [{"source": "openalex", "status": "ok", "queries": 1, "hits": 1}],
    }
    (run / "scout-papers.json").write_text(json.dumps(scout))
    assert cli.main(["pool", "--ideas", str(ideas), "--id", idea_id]) == 0
    judge = {
        "closest": {
            "ref": "r1",
            "quote": "a quoted passage long enough",
            "differs": {"domain": "d", "purpose": "p", "mechanism": "m", "evaluation": ""},
        },
        "others": [],
        "fit": "Fits plugin:graphe.",
        "verdict": {
            "state": "do",
            "type": "tool",
            "project": "plugin:graphe",
            "reason": "new",
            "next_step": "build it",
        },
    }
    (run / "judge.json").write_text(json.dumps(judge))
    (run / "verify.json").write_text(json.dumps({"r1": {"ok": True, "reason": ""}}))
    capsys.readouterr()
    args = ["apply", "--ideas", str(ideas), "--id", idea_id, "--today", "2026-10-15"]
    assert cli.main(args) == 0
    out = capsys.readouterr().out
    assert "later" in out and "evaluation" in out
    text = (ideas / "ideas" / f"{idea_id}.md").read_text()
    assert "## Restated\n\nA triage tool." in text
    assert "**Closest:** [Rival](https://r.example)" in text
    assert "2026-10-15 · triage · later" in text
    assert idea_id in (ideas / "BOARD.md").read_text()


def test_override_records_an_override_verdict(tmp_path: Path, capsys):
    ideas = init_ideas(tmp_path)
    cli.main(["capture", "--ideas", str(ideas), "Something"])
    idea_id = capsys.readouterr().out.strip().splitlines()[-1]
    args = ["override", "--ideas", str(ideas), idea_id, "trash", "already", "exists"]
    assert cli.main(args) == 0
    assert "· override · trash" in (ideas / "ideas" / f"{idea_id}.md").read_text()


def test_capture_never_overwrites_an_existing_idea(tmp_path: Path, capsys):
    ideas = init_ideas(tmp_path)
    capsys.readouterr()
    cli.main(["capture", "--ideas", str(ideas), "Same idea"])
    first = capsys.readouterr().out.strip()
    cli.main(["capture", "--ideas", str(ideas), "Same idea"])
    second = capsys.readouterr().out.strip()
    assert first != second
    assert (ideas / "ideas" / f"{first}.md").is_file()
    assert (ideas / "ideas" / f"{second}.md").is_file()


def test_capture_off_main_keeps_the_idea_and_says_so(tmp_path: Path, capsys):
    ideas = init_ideas(tmp_path)
    subprocess.run(["git", "-C", str(ideas), "checkout", "-q", "-b", "side"], check=True)
    capsys.readouterr()
    assert cli.main(["capture", "--ideas", str(ideas), "Kept locally"]) == 1
    err = capsys.readouterr().err
    assert err.startswith("heuresis: ") and "saved locally" in err
    assert "Traceback" not in err
    assert len(list((ideas / "ideas").glob("*.md"))) == 1


def test_unreadable_idea_is_a_message_not_a_traceback(tmp_path: Path, capsys):
    ideas = init_ideas(tmp_path)
    (ideas / "ideas" / "2026-10-15-bad.md").write_text("no front matter")
    capsys.readouterr()
    args = ["restate", "--ideas", str(ideas), "--id", "2026-10-15-bad", "--json", "{}"]
    assert cli.main(args) == 1
    assert capsys.readouterr().err.startswith("heuresis: ")


def test_context_rejects_a_path_that_escapes_the_repo(tmp_path: Path, capsys):
    ideas = init_ideas(tmp_path)
    (ideas / "context.toml").write_text('[[source]]\nkind = "x"\nrepo = "papers"\npath = "../x"\n')
    capsys.readouterr()
    assert cli.main(["context", "--ideas", str(ideas), "--repos-root", str(tmp_path)]) == 1
    assert capsys.readouterr().err.startswith("heuresis: ")


def _capture(ideas: Path, capsys) -> str:
    capsys.readouterr()
    cli.main(["capture", "--ideas", str(ideas), "An idea for records"])
    return capsys.readouterr().out.strip()


def test_add_record_appends_to_a_new_scout_file(tmp_path: Path, capsys):
    ideas = init_ideas(tmp_path)
    idea_id = _capture(ideas, capsys)
    record = {"title": "T", "url": "https://t.example", "source": "web", "kind": "web"}
    args = ["add-record", "--ideas", str(ideas), "--id", idea_id, "--group", "context"]
    assert cli.main([*args, "--json", json.dumps(record)]) == 0
    scout = json.loads((ideas / "runs" / idea_id / "scout-context.json").read_text())
    assert scout["records"][0]["url"] == "https://t.example"
    assert scout["queries"] == [] and scout["coverage"] == []


@pytest.mark.parametrize(
    "url",
    [
        "repo:/etc/passwd",
        "repo:../secret",
        "idea:../../etc/passwd",
        "file:///etc/passwd",
        "ftp://x.example/a",
    ],
)
def test_add_record_rejects_unacceptable_urls(tmp_path: Path, capsys, url):
    ideas = init_ideas(tmp_path)
    idea_id = _capture(ideas, capsys)
    record = {"title": "T", "url": url, "source": "web", "kind": "web"}
    args = ["add-record", "--ideas", str(ideas), "--id", idea_id, "--group", "context"]
    capsys.readouterr()
    assert cli.main([*args, "--json", json.dumps(record)]) == 2
    assert capsys.readouterr().err.startswith("heuresis: ")
    assert not (ideas / "runs" / idea_id / "scout-context.json").exists()


def test_verify_exits_3_when_the_closest_rival_fails(tmp_path: Path, capsys):
    ideas = init_ideas(tmp_path)
    idea_id = _capture(ideas, capsys)
    run = ideas / "runs" / idea_id
    run.mkdir(parents=True)
    (run / "pool.json").write_text(
        json.dumps(
            {
                "records": [
                    {
                        "ref": "r1",
                        "title": "T",
                        "url": "repo:missing.md",
                        "source": "x",
                        "kind": "repo",
                    }
                ],
                "coverage": [],
                "queries": {},
            }
        )
    )
    judge = {"closest": {"ref": "r1", "quote": "a quoted passage long enough"}, "others": []}
    (run / "judge.json").write_text(json.dumps(judge))
    args = ["verify", "--ideas", str(ideas), "--id", idea_id, "--repos-root", str(tmp_path)]
    assert cli.main(args) == 3
    assert json.loads((run / "verify.json").read_text())["r1"]["ok"] is False
