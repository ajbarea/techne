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
    bound = {"url": "https://r.example", "source": "openalex", "evidence_url": ""}
    (run / "verify.json").write_text(
        json.dumps({"r1": {"ok": True, "reason": "", "quote": QUOTE, **bound}})
    )
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
    judge = {
        "closest": {"ref": "r1", "quote": "a quoted passage long enough"},
        "others": [],
        "verdict": {"state": "trash", "reason": "r"},
    }
    (run / "judge.json").write_text(json.dumps(judge))
    args = ["verify", "--ideas", str(ideas), "--id", idea_id, "--repos-root", str(tmp_path)]
    assert cli.main(args) == 3
    assert json.loads((run / "verify.json").read_text())["r1"]["ok"] is False


QUOTE = "a quoted passage long enough"
R_BOUND = {"url": "https://r.example", "source": "openalex", "evidence_url": ""}


def _triaged(ideas: Path, capsys, verdict=None, verify_entry=None, quote=QUOTE) -> tuple[str, Path]:
    """An idea with a one-record pool, a judge file and a verify file, ready for apply."""
    idea_id = _capture(ideas, capsys)
    run = ideas / "runs" / idea_id
    run.mkdir(parents=True)
    record = {"title": "R", "url": "https://r.example", "source": "openalex", "kind": "paper"}
    coverage = [{"source": "openalex", "status": "ok", "queries": 1, "hits": 1}]
    scout = {"group": "papers", "queries": ["q"], "records": [record], "coverage": coverage}
    (run / "scout-papers.json").write_text(json.dumps(scout))
    assert cli.main(["pool", "--ideas", str(ideas), "--id", idea_id]) == 0
    differs = dict.fromkeys(("domain", "purpose", "mechanism", "evaluation"), "x")
    judge = {
        "closest": {"ref": "r1", "quote": quote, "differs": differs},
        "others": [],
        "fit": "f",
        "verdict": verdict or {"state": "do", "type": "tool", "reason": "new"},
    }
    (run / "judge.json").write_text(json.dumps(judge))
    entry = verify_entry or {"ok": True, "reason": "", "quote": QUOTE, **R_BOUND}
    (run / "verify.json").write_text(json.dumps({"r1": entry}))
    return idea_id, run


def _apply(ideas: Path, idea_id: str) -> int:
    return cli.main(["apply", "--ideas", str(ideas), "--id", idea_id, "--today", "2026-10-15"])


@pytest.mark.parametrize(
    "verdict",
    [
        {"state": "maybe", "reason": "r"},
        {"state": "shipped", "type": "tool", "reason": "r"},
        {"state": "do", "type": "app", "reason": "r"},
        {"state": "do", "type": "tool", "reason": "r", "revisit_on": "keyword:x"},
    ],
)
def test_apply_rejects_a_bad_verdict_and_saves_nothing(tmp_path: Path, capsys, verdict):
    ideas = init_ideas(tmp_path)
    idea_id, _ = _triaged(ideas, capsys, verdict=verdict)
    path = ideas / "ideas" / f"{idea_id}.md"
    before = path.read_text()
    capsys.readouterr()
    assert _apply(ideas, idea_id) == 1
    assert capsys.readouterr().err.startswith("heuresis: judge.json: verdict.")
    assert path.read_text() == before


def test_override_do_without_a_type_leaves_the_idea_unchanged(tmp_path: Path, capsys):
    ideas = init_ideas(tmp_path)
    idea_id = _capture(ideas, capsys)
    path = ideas / "ideas" / f"{idea_id}.md"
    before = path.read_text()
    assert cli.main(["override", "--ideas", str(ideas), idea_id, "do", "go"]) == 1
    assert "needs a type" in capsys.readouterr().err
    assert path.read_text() == before


def test_a_stale_verify_file_does_not_count_as_verified(tmp_path: Path, capsys):
    ideas = init_ideas(tmp_path)
    stale = {"ok": True, "reason": "", "quote": "an older quote that was checked", **R_BOUND}
    idea_id, _ = _triaged(ideas, capsys, verify_entry=stale)
    assert _apply(ideas, idea_id) == 0
    text = (ideas / "ideas" / f"{idea_id}.md").read_text()
    assert "· triage · later" in text and "not verified against the current quote" in text


def test_a_loose_ok_value_does_not_count_as_verified(tmp_path: Path, capsys):
    ideas = init_ideas(tmp_path)
    idea_id, _ = _triaged(ideas, capsys, verify_entry={"ok": "false", "quote": QUOTE, **R_BOUND})
    assert _apply(ideas, idea_id) == 0
    assert "· triage · later" in (ideas / "ideas" / f"{idea_id}.md").read_text()


def test_a_cited_ref_missing_from_the_pool_is_dropped(tmp_path: Path, capsys):
    ideas = init_ideas(tmp_path)
    idea_id, run = _triaged(ideas, capsys)
    judge = json.loads((run / "judge.json").read_text())
    judge["others"] = [{"ref": "r9", "quote": "q", "differs": "x"}]
    (run / "judge.json").write_text(json.dumps(judge))
    assert _apply(ideas, idea_id) == 0
    assert "r9 (not in pool)" in (ideas / "ideas" / f"{idea_id}.md").read_text()


@pytest.mark.parametrize(
    ("name", "edit"),
    [
        ("judge.json", lambda d: d.pop("verdict")),
        ("judge.json", lambda d: d.update(others=["r1"])),
        ("verify.json", lambda d: d["r1"].pop("ok")),
        ("pool.json", lambda d: d.pop("records")),
    ],
)
def test_malformed_run_files_are_a_message_and_write_nothing(tmp_path: Path, capsys, name, edit):
    ideas = init_ideas(tmp_path)
    idea_id, run = _triaged(ideas, capsys)
    data = json.loads((run / name).read_text())
    edit(data)
    (run / name).write_text(json.dumps(data))
    path = ideas / "ideas" / f"{idea_id}.md"
    before = path.read_text()
    capsys.readouterr()
    assert _apply(ideas, idea_id) == 1
    err = capsys.readouterr().err
    assert err.startswith("heuresis: ") and "Traceback" not in err
    assert path.read_text() == before


def test_verify_with_no_closest_writes_no_none_key(tmp_path: Path, capsys):
    ideas = init_ideas(tmp_path)
    idea_id, run = _triaged(ideas, capsys)
    judge = json.loads((run / "judge.json").read_text())
    judge["closest"] = None
    (run / "judge.json").write_text(json.dumps(judge))
    args = ["verify", "--ideas", str(ideas), "--id", idea_id, "--repos-root", str(tmp_path)]
    assert cli.main(args) == 0
    assert json.loads((run / "verify.json").read_text()) == {}


def test_verify_records_the_quote_it_checked(tmp_path: Path, capsys):
    ideas = init_ideas(tmp_path)
    idea_id, run = _triaged(ideas, capsys)
    judge = json.loads((run / "judge.json").read_text())
    judge["others"] = [{"ref": "r9", "quote": "missing quote here", "differs": "x"}]
    (run / "judge.json").write_text(json.dumps(judge))
    args = ["verify", "--ideas", str(ideas), "--id", idea_id, "--repos-root", str(tmp_path)]
    cli.main(args)
    result = json.loads((run / "verify.json").read_text())
    assert result["r9"] == {"ok": False, "reason": "not in pool", "quote": "missing quote here"}


def test_apply_off_main_says_the_verdict_is_saved_locally(tmp_path: Path, capsys):
    ideas = init_ideas(tmp_path)
    idea_id, _ = _triaged(ideas, capsys)
    subprocess.run(["git", "-C", str(ideas), "checkout", "-q", "-b", "side"], check=True)
    capsys.readouterr()
    assert _apply(ideas, idea_id) == 1
    assert "saved locally" in capsys.readouterr().err


def _stdin(monkeypatch, text: str) -> None:
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO(text))


def test_add_record_reads_json_from_stdin_with_an_apostrophe(tmp_path: Path, capsys, monkeypatch):
    ideas = init_ideas(tmp_path)
    idea_id = _capture(ideas, capsys)
    record = {
        "title": "T",
        "url": "https://t.example",
        "source": "web",
        "kind": "web",
        "text": "it's a tool that doesn't quit",
    }
    _stdin(monkeypatch, json.dumps(record))
    args = ["add-record", "--ideas", str(ideas), "--id", idea_id, "--group", "context"]
    assert cli.main([*args, "--json", "-"]) == 0
    scout = json.loads((ideas / "runs" / idea_id / "scout-context.json").read_text())
    assert scout["records"][0]["text"] == "it's a tool that doesn't quit"


def test_restate_reads_json_from_stdin_with_an_apostrophe(tmp_path: Path, capsys, monkeypatch):
    ideas = init_ideas(tmp_path)
    idea_id = _capture(ideas, capsys)
    _stdin(monkeypatch, json.dumps({"restated": "AJ's tool", "queries": ["a b c"]}))
    assert cli.main(["restate", "--ideas", str(ideas), "--id", idea_id, "--json", "-"]) == 0
    run = ideas / "runs" / idea_id
    assert json.loads((run / "restate.json").read_text())["restated"] == "AJ's tool"


def test_restate_starts_a_new_run(tmp_path: Path, capsys, monkeypatch):
    ideas = init_ideas(tmp_path)
    idea_id = _capture(ideas, capsys)
    run = ideas / "runs" / idea_id
    run.mkdir(parents=True)
    names = ["scout-papers.json", "scout-context.json", "pool.json", "judge.json", "verify.json"]
    for name in names:
        (run / name).write_text("{}")
    _stdin(monkeypatch, json.dumps({"restated": "x", "queries": []}))
    assert cli.main(["restate", "--ideas", str(ideas), "--id", idea_id, "--json", "-"]) == 0
    assert sorted(p.name for p in run.iterdir()) == ["restate.json"]


def test_search_twice_keeps_both_record_sets_and_combines_coverage(
    tmp_path: Path, capsys, monkeypatch
):
    from heuresis.model import Coverage, Record

    ideas = init_ideas(tmp_path)
    idea_id = _capture(ideas, capsys)
    batches = iter(
        [
            ([Record("A", "https://a.example", "s", "paper")], [Coverage("s", "empty", 2, 0)]),
            ([Record("B", "https://b.example", "s", "paper")], [Coverage("s", "ok", 1, 1, "n")]),
        ]
    )
    monkeypatch.setattr(cli.sources, "run_queries", lambda *a: next(batches))
    args = ["search", "--ideas", str(ideas), "--id", idea_id, "--group", "papers"]
    assert cli.main([*args, "--query", "one"]) == 0
    capsys.readouterr()
    assert cli.main([*args, "--query", "two"]) == 0
    assert capsys.readouterr().out.strip() == "s: ok, 3 queries, 1 hits (n)"
    scout = json.loads((ideas / "runs" / idea_id / "scout-papers.json").read_text())
    assert [r["title"] for r in scout["records"]] == ["A", "B"]
    assert scout["queries"] == ["one", "two"]


def test_similar_excludes_the_named_ideas(tmp_path: Path, capsys):
    ideas = init_ideas(tmp_path)
    first = _capture(ideas, capsys)
    capsys.readouterr()
    assert cli.main(["similar", "--ideas", str(ideas), "records"]) == 0
    assert first in capsys.readouterr().out
    args = ["similar", "--ideas", str(ideas), "--exclude", first, "records"]
    assert cli.main(args) == 0
    assert first not in capsys.readouterr().out


def test_add_record_rejects_a_record_citing_the_idea_under_triage(tmp_path: Path, capsys):
    ideas = init_ideas(tmp_path)
    idea_id = _capture(ideas, capsys)
    record = {"title": "T", "url": f"idea:{idea_id}", "source": "ideas", "kind": "idea"}
    args = ["add-record", "--ideas", str(ideas), "--id", idea_id, "--group", "context"]
    capsys.readouterr()
    assert cli.main([*args, "--json", json.dumps(record)]) == 2
    assert "cannot cite the idea being triaged" in capsys.readouterr().err
    assert not (ideas / "runs" / idea_id / "scout-context.json").exists()


def test_retriage_commits_the_deletion_of_the_previous_runs_scout_file(
    tmp_path: Path, capsys, monkeypatch
):
    ideas = init_ideas(tmp_path)
    idea_id, run = _triaged(ideas, capsys)
    _scout(run, "products", [])
    assert cli.main(["pool", "--ideas", str(ideas), "--id", idea_id]) == 0
    (run / "judge.json").write_text(json.dumps({"closest": None, "verdict": {"state": "later"}}))
    (run / "verify.json").write_text("{}")
    assert _apply(ideas, idea_id) == 0

    def tracked() -> str:
        cmd = ["git", "-C", str(ideas), "ls-tree", "-r", "--name-only", "HEAD", f"runs/{idea_id}"]
        return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout

    assert "scout-products.json" in tracked()
    _stdin(monkeypatch, json.dumps({"restated": "again", "queries": []}))
    assert cli.main(["restate", "--ideas", str(ideas), "--id", idea_id, "--json", "-"]) == 0
    pooled = {"records": [], "coverage": [], "queries": {}}
    (run / "pool.json").write_text(json.dumps(pooled))
    (run / "judge.json").write_text(json.dumps({"closest": None, "verdict": {"state": "later"}}))
    (run / "verify.json").write_text("{}")
    assert _apply(ideas, idea_id) == 0
    assert "scout-products.json" not in tracked()
    status = subprocess.run(
        ["git", "-C", str(ideas), "status", "--porcelain", "--untracked-files=no"],
        capture_output=True,
        text=True,
    )
    assert status.stdout == ""


def _scout(run: Path, group: str, records: list[dict]) -> None:
    coverage = [{"source": "openalex", "status": "ok", "queries": 1, "hits": len(records)}]
    scout = {"group": group, "queries": ["q"], "records": records, "coverage": coverage}
    (run / f"scout-{group}.json").write_text(json.dumps(scout))


def test_a_verify_file_from_an_earlier_pool_does_not_approve_a_renumbered_ref(
    tmp_path: Path, capsys, monkeypatch
):
    ideas = init_ideas(tmp_path)
    idea_id = _capture(ideas, capsys)
    run = ideas / "runs" / idea_id
    run.mkdir(parents=True)
    first, second = "the first paper triages ideas by hand", "the second paper ranks ideas by votes"
    _scout(
        run,
        "papers",
        [
            {"title": "P1", "url": "https://p1.example", "source": "web", "kind": "paper"},
            {"title": "P2", "url": "https://p2.example", "source": "web", "kind": "paper"},
        ],
    )
    assert cli.main(["pool", "--ideas", str(ideas), "--id", idea_id]) == 0
    differs = dict.fromkeys(("domain", "purpose", "mechanism", "evaluation"), "x")
    judge = {
        "closest": {"ref": "r2", "quote": second, "differs": differs},
        "others": [],
        "fit": "f",
        "verdict": {"state": "do", "type": "tool", "reason": "new"},
    }
    (run / "judge.json").write_text(json.dumps(judge))
    pages = {"https://p1.example": first, "https://p2.example": second}
    monkeypatch.setattr(cli.verify.http, "get", lambda url, headers=None: pages[url].encode())
    args = ["verify", "--ideas", str(ideas), "--id", idea_id, "--repos-root", str(tmp_path)]
    assert cli.main(args) == 0
    checked = json.loads((run / "verify.json").read_text())
    assert checked["r2"]["url"] == "https://p2.example" and checked["r2"]["source"] == "web"
    assert checked["r2"]["evidence_url"] == ""
    stale = {n: (run / n).read_text() for n in ("judge.json", "verify.json")}
    record = {"title": "C", "url": "repo:x/ROADMAP.md", "source": "context", "kind": "context"}
    add = ["add-record", "--ideas", str(ideas), "--id", idea_id, "--group", "context"]
    assert cli.main([*add, "--json", json.dumps(record)]) == 0
    assert cli.main(["pool", "--ideas", str(ideas), "--id", idea_id]) == 0
    assert not (run / "judge.json").exists() and not (run / "verify.json").exists()
    for name, text in stale.items():
        (run / name).write_text(text)
    capsys.readouterr()
    assert _apply(ideas, idea_id) == 0
    assert "later" in capsys.readouterr().out
    assert "**Closest:** none verified." in (ideas / "ideas" / f"{idea_id}.md").read_text()


def test_apply_refuses_a_pool_json_edited_after_pool_ran(tmp_path: Path, capsys):
    ideas = init_ideas(tmp_path)
    idea_id, run = _triaged(ideas, capsys)
    pooled = json.loads((run / "pool.json").read_text())
    pooled["records"][0]["text"] = QUOTE
    (run / "pool.json").write_text(json.dumps(pooled))
    path = ideas / "ideas" / f"{idea_id}.md"
    before = path.read_text()
    capsys.readouterr()
    assert _apply(ideas, idea_id) == 1
    assert "pool.json changed since pool ran; run pool again" in capsys.readouterr().err
    assert path.read_text() == before


def _status(ideas: Path, *paths: str) -> str:
    cmd = ["git", "-C", str(ideas), "status", "--porcelain", "--", *paths]
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout


def test_restate_writes_only_the_run_file_and_apply_copies_the_restatement(
    tmp_path: Path, capsys, monkeypatch
):
    ideas = init_ideas(tmp_path)
    idea_id, run = _triaged(ideas, capsys)
    before = (ideas / "ideas" / f"{idea_id}.md").read_text()
    _stdin(monkeypatch, json.dumps({"restated": "A neutral restatement.", "queries": []}))
    assert cli.main(["restate", "--ideas", str(ideas), "--id", idea_id, "--json", "-"]) == 0
    assert _status(ideas, f"ideas/{idea_id}.md") == ""
    assert (ideas / "ideas" / f"{idea_id}.md").read_text() == before
    _scout(run, "papers", [])
    assert cli.main(["pool", "--ideas", str(ideas), "--id", idea_id]) == 0
    (run / "judge.json").write_text(json.dumps({"closest": None, "verdict": {"state": "later"}}))
    (run / "verify.json").write_text("{}")
    assert _apply(ideas, idea_id) == 0
    assert (
        "## Restated\n\nA neutral restatement." in (ideas / "ideas" / f"{idea_id}.md").read_text()
    )


def test_publish_command_pushes_an_idea_a_failed_capture_left_behind(tmp_path: Path, capsys):
    ideas = init_ideas(tmp_path)
    for step in (["add", "-A"], ["commit", "-qm", "init: ideas repository"]):  # setup's runbook
        subprocess.run(["git", "-C", str(ideas), *step], check=True)
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    subprocess.run(["git", "-C", str(ideas), "remote", "add", "origin", str(remote)], check=True)
    _capture(ideas, capsys)
    subprocess.run(["git", "-C", str(ideas), "checkout", "-q", "-b", "side"], check=True)
    capsys.readouterr()
    assert cli.main(["capture", "--ideas", str(ideas), "Left behind"]) == 1
    assert "heuresis publish" in capsys.readouterr().err
    subprocess.run(["git", "-C", str(ideas), "checkout", "-q", "main"], check=True)
    assert cli.main(["publish", "--ideas", str(ideas)]) == 0
    tree = subprocess.run(
        ["git", "-C", str(remote), "ls-tree", "-r", "--name-only", "main"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert any(line.endswith("left-behind.md") for line in tree.splitlines())
    assert _status(ideas) == ""


def _two_clones(tmp_path: Path) -> tuple[Path, Path]:
    """Two clones of one ideas repository sharing a local bare remote."""
    a = init_ideas(tmp_path)
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    for step in (
        ["add", "-A"],
        ["commit", "-qm", "init: ideas repository"],
        ["remote", "add", "origin", str(remote)],
        ["push", "-q", "-u", "origin", "main"],
    ):
        subprocess.run(["git", "-C", str(a), *step], check=True)
    b = tmp_path / "phone"
    subprocess.run(["git", "clone", "-q", str(remote), str(b)], check=True, capture_output=True)
    for key, value in (("user.email", "t@example.com"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(b), "config", key, value], check=True)
    subprocess.run(["git", "-C", str(b), "config", "commit.gpgsign", "false"], check=True)
    return a, b


def _capture_in(ideas: Path, capsys, text: str) -> tuple[int, str, str]:
    capsys.readouterr()
    code = cli.main(["capture", "--ideas", str(ideas), text])
    out = capsys.readouterr()
    return code, out.out.strip(), out.err


def test_same_title_captured_on_two_clones_gets_two_ids(tmp_path: Path, capsys):
    a, b = _two_clones(tmp_path)
    code_a, id_a, _ = _capture_in(a, capsys, "Same title on both\nfrom the terminal")
    code_b, id_b, err = _capture_in(b, capsys, "Same title on both\nfrom the phone")
    assert (code_a, code_b) == (0, 0), err
    assert id_b == f"{id_a}-2"
    tree = subprocess.run(
        ["git", "-C", str(tmp_path / "remote.git"), "ls-tree", "-r", "--name-only", "main"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert f"ideas/{id_a}.md" in tree and f"ideas/{id_b}.md" in tree


def test_an_id_collision_the_fetch_missed_names_the_idea(tmp_path: Path, capsys, monkeypatch):
    a, b = _two_clones(tmp_path)
    _, id_a, _ = _capture_in(a, capsys, "Same title on both\nfrom the terminal")
    monkeypatch.setattr(cli.sync, "remote_ideas", lambda root: [], raising=False)  # offline
    code, id_b, err = _capture_in(b, capsys, "Same title on both\nfrom the phone")
    assert code == 1 and id_b == ""
    assert f"idea {id_a}" in err and "local copy is kept" in err
    assert (b / "ideas" / f"{id_a}.md").is_file()
    assert not (b / ".git" / "rebase-merge").exists()
