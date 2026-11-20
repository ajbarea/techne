"""Tests for the cleanup check (_shared/cleanup.py, sisters check 18).

Every guard here exists to go red: a done-log in a ROADMAP, a working doc past its budget, a
transient file nobody owns or that has expired. Each test runs the script the way sisters and CI
do, in a subprocess with its own HOME, and asserts on the line it prints.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import CLEANUP_SCRIPT

TODAY = "2026-11-20"


def run(*args: str, home: Path, cwd: Path | None = None) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["HOME"] = str(home)
    return subprocess.run(
        [sys.executable, str(CLEANUP_SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
        timeout=30,
        check=False,
    )


def make(tmp_path: Path, files: dict[str, str], git: bool = False) -> Path:
    root = tmp_path / "repo"
    root.mkdir(exist_ok=True)
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    if git:
        g = ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run([*g, "add", "-A"], check=True)
        subprocess.run([*g, "commit", "-qm", "init"], check=True)
    return root


def check(root: Path, tmp_path: Path, *extra: str) -> list[str]:
    out = run("check", "--today", TODAY, *extra, str(root), home=tmp_path / "home")
    assert out.returncode == 0, out.stderr
    return [line.split(": ", 1)[1] for line in out.stdout.splitlines()]


def lines(n: int) -> str:
    return "".join(f"line {i}\n" for i in range(n))


# --- ROADMAP done-log ---------------------------------------------------------------------

DONE_HEADINGS = [
    "## Completed",
    "## Shipped",
    "## Done",
    "## ✅ Done this week",
    "## Done since 11-15",
    "### Recently shipped",
    "## 3. Changelog",
    "# History",
    "## **Completed**",
    "## Release notes",
    "## Landed",
    "## Archive",
]
NOT_DONE = [
    "## Done when",
    "### Done means",
    "## Milestones",
    "## Shipping plan",
    "## Next up",
    "## Phase 0 (nearly complete)",
    "## Design rules",
]


@pytest.mark.parametrize("heading", DONE_HEADINGS)
def test_a_done_log_heading_is_a_finding(tmp_path, heading):
    root = make(tmp_path, {"ROADMAP.md": f"# Roadmap\n\n## Next\n- a\n\n{heading}\n- 10-01 x\n"})
    got = check(root, tmp_path)
    assert len(got) == 1 and got[0].startswith("ROADMAP.md:6 ") and "lines 6-7" in got[0]


@pytest.mark.parametrize("heading", NOT_DONE)
def test_a_forward_heading_passes(tmp_path, heading):
    root = make(tmp_path, {"ROADMAP.md": f"# Roadmap\n\n{heading}\n- a\n"})
    assert check(root, tmp_path) == ["cleanup ✓"]


def test_a_heading_inside_a_code_fence_is_not_a_heading(tmp_path):
    text = "# R\n\n```md\n## Completed\n```\n\n~~~~\n## Shipped\n~~~~\n"
    root = make(tmp_path, {"ROADMAP.md": text})
    assert check(root, tmp_path) == ["cleanup ✓"]


def test_the_section_stops_at_the_next_heading_of_its_level(tmp_path):
    text = "# R\n## Completed\n- a\n### 2026-10\n- b\n## Backlog\n- c\n"
    root = make(tmp_path, {"ROADMAP.md": text})
    out = run("done-log", str(root), home=tmp_path)
    assert "ROADMAP.md:2-5 'Completed'" in out.stdout
    assert "- b" in out.stdout and "- c" not in out.stdout


def test_a_done_log_nested_in_another_is_reported_once(tmp_path):
    text = "# R\n## Shipped\n### Completed\n- a\n## Next\n"
    root = make(tmp_path, {"ROADMAP.md": text})
    got = check(root, tmp_path)
    assert got == [g for g in got if "Shipped" in g] and len(got) == 1


@pytest.mark.parametrize(("n", "flagged"), [(0, False), (300, False), (301, True)])
def test_roadmap_line_budget_boundary(tmp_path, n, flagged):
    root = make(tmp_path, {"ROADMAP.md": lines(n)})
    got = check(root, tmp_path)
    assert (got != ["cleanup ✓"]) is flagged
    if flagged:
        assert "301 lines, over its 300-line budget" in got[0]


def test_a_last_line_without_newline_counts(tmp_path):
    root = make(tmp_path, {"IMPL.md": lines(50) + "tail"})
    assert "51 lines" in check(root, tmp_path)[0]


# --- IMPL and agent files -----------------------------------------------------------------


@pytest.mark.parametrize(("n", "flagged"), [(50, False), (51, True)])
def test_impl_budget_boundary(tmp_path, n, flagged):
    root = make(tmp_path, {"IMPL.md": lines(n)})
    assert (check(root, tmp_path) != ["cleanup ✓"]) is flagged


@pytest.mark.parametrize(
    "rel",
    [
        "AGENTS.md",
        "CLAUDE.md",
        ".claude/CLAUDE.md",
        "CLAUDE.local.md",
        ".github/copilot-instructions.md",
        ".claude/skill-context.md",
    ],
)
@pytest.mark.parametrize(("n", "flagged"), [(200, False), (201, True)])
def test_agent_file_budget_boundary(tmp_path, rel, n, flagged):
    root = make(tmp_path, {rel: lines(n)})
    got = check(root, tmp_path)
    assert (got != ["cleanup ✓"]) is flagged
    if flagged:
        assert got[0].startswith(f"{rel} has 201 lines, over the 200-line budget")


@pytest.mark.parametrize(("size", "flagged"), [(25000, False), (25001, True)])
def test_agent_file_byte_budget_boundary(tmp_path, size, flagged):
    root = make(tmp_path, {"AGENTS.md": "x" * (size - 1) + "\n"})
    got = check(root, tmp_path)
    assert (got != ["cleanup ✓"]) is flagged
    if flagged:
        assert got[0].startswith("AGENTS.md has 25001 bytes, over the 25000-byte budget")


def test_agent_file_globs_add_files_such_as_a_memory_index(tmp_path):
    ctx = "## cleanup\n- agent_file: projects/*/memory/MEMORY.md\n- agent_lines: 3\n"
    files = {
        ".claude/skill-context.md": ctx,
        "projects/a/memory/MEMORY.md": lines(4),
        "projects/a/memory/other.md": lines(9),
        "projects/b/memory/MEMORY.md": lines(3),
    }
    got = check(make(tmp_path, files), tmp_path)
    assert got == [
        "projects/a/memory/MEMORY.md has 4 lines, over the 3-line budget for agent "
        "instructions → move what a hook or check can enforce into one, and cut what the code "
        "shows"
    ]


def test_budgets_come_from_the_cleanup_section(tmp_path):
    ctx = (
        "## repo\nx\n\n## cleanup\n- impl_lines: 10\n- roadmap_lines: 5\n"
        "- agent_lines: 400\n\n## audit\n- impl_lines: 99\n"
    )
    root = make(
        tmp_path, {".claude/skill-context.md": ctx, "IMPL.md": lines(11), "ROADMAP.md": lines(6)}
    )
    got = check(root, tmp_path)
    assert any("IMPL.md has 11 lines, over its 10-line" in g for g in got)
    assert any("ROADMAP.md has 6 lines, over its 5-line" in g for g in got)


@pytest.mark.parametrize(
    ("line", "expect"),
    [
        ("- impl_lines: lots", "impl_lines 'lots' is not a whole number"),
        ("- impl_lines: 0", "impl_lines '0' is not a whole number"),
        ("- transient:", "transient has no glob"),
        ("- colour: red", "unknown key 'colour'"),
    ],
)
def test_a_config_line_that_cannot_be_read_is_a_finding(tmp_path, line, expect):
    root = make(tmp_path, {".claude/skill-context.md": f"## cleanup\n{line}\n"})
    assert any(expect in g for g in check(root, tmp_path))


def test_the_template_s_placeholders_are_skipped(tmp_path):
    ctx = "## cleanup\n- transient: <glob, e.g. review/**>\n- keep: <glob>\n"
    root = make(tmp_path, {".claude/skill-context.md": ctx, "review/a.md": "x"})
    assert check(root, tmp_path) == ["cleanup ✓"]


def test_a_fifo_is_reported_not_read(tmp_path):
    root = make(tmp_path, {})
    os.mkfifo(root / "IMPL.md")
    assert check(root, tmp_path) == ["IMPL.md is not a regular file → make it a regular file"]


def test_a_broken_link_is_reported(tmp_path):
    root = make(tmp_path, {})
    (root / "AGENTS.md").symlink_to(root / "gone.md")
    assert check(root, tmp_path) == [
        "AGENTS.md is a link to a missing file → make it a regular file"
    ]


def test_a_missing_folder_is_a_finding(tmp_path):
    assert check(tmp_path / "nope", tmp_path) == [f"not a folder: {tmp_path / 'nope'}"]


# --- transient files ----------------------------------------------------------------------

CTX = "## cleanup\n- transient: review/**\n- keep: review/README.md\n"


def fm(**fields: str) -> str:
    return "---\n" + "".join(f"{k}: {v}\n" for k, v in fields.items()) + "---\n# body\n"


@pytest.mark.parametrize(
    ("fields", "expect"),
    [
        ({"owner": "heph", "expires": "2026-11-20"}, None),  # expires today: still current
        ({"owner": "heph", "expires": "2026-11-19"}, "expired 2026-11-19 (owner heph)"),
        ({"owner": "heph", "reviewed": "2026-08-22"}, None),  # 90 days
        ({"owner": "heph", "reviewed": "2026-08-21"}, "over 90 days ago"),
        ({"expires": "2027-01-01"}, "no owner"),
        ({"owner": "heph"}, "no expires or reviewed date"),
        ({"owner": "heph", "expires": "soon"}, "expires 'soon' is not a YYYY-MM-DD date"),
        ({"owner": "heph", "expires": "2026-02-30"}, "is not a YYYY-MM-DD date"),
        ({"owner": "heph", "expires": "2027-01-01", "reviewed": "2020-01-01"}, "over 90 days ago"),
    ],
)
def test_a_markdown_file_carries_its_own_frontmatter(tmp_path, fields, expect):
    root = make(tmp_path, {".claude/skill-context.md": CTX, "review/a.md": fm(**fields)})
    got = check(root, tmp_path)
    if expect is None:
        assert got == ["cleanup ✓"]
    else:
        assert len(got) == 1 and got[0].startswith("review/a.md: ") and expect in got[0]


def test_a_file_without_frontmatter_is_named(tmp_path):
    root = make(tmp_path, {".claude/skill-context.md": CTX, "review/a.md": "# draft\n"})
    assert check(root, tmp_path)[0].startswith("review/a.md has no owner + expires frontmatter")


def test_a_folder_of_images_is_reported_once(tmp_path):
    files = {".claude/skill-context.md": CTX, **{f"review/art/{i}.png": "x" for i in range(3)}}
    root = make(tmp_path, files)
    assert check(root, tmp_path) == [
        "review/art/ holds 3 file(s) with no owner + expires (0.png, 1.png, 2.png) → add a "
        "README.md there with that frontmatter, or harvest the files into the repo that owns "
        "them and delete them"
    ]


@pytest.mark.parametrize(
    ("names", "lines_out"),
    [
        (["a.md", "b.md", "c.md"], 3),  # a few notes are each named
        (["a.md", "b.md", "c.md", "d.md"], 1),  # past GROUP_AT: one line for the folder
        (["a.md", "README.md"], 1),  # a bare README speaks for its folder
    ],
)
def test_notes_are_named_until_a_folder_holds_many(tmp_path, names, lines_out):
    files = {".claude/skill-context.md": CTX, **{f"review/notes/{n}": "x" for n in names}}
    got = check(make(tmp_path, files), tmp_path)
    assert len(got) == lines_out
    if lines_out == 1:
        assert got[0].startswith(f"review/notes/ holds {len(names)} file(s)")


def test_a_readme_above_covers_the_folder_and_the_nearest_wins(tmp_path):
    files = {
        ".claude/skill-context.md": CTX,
        "review/art/README.md": fm(owner="heph", expires="2026-12-01"),
        "review/art/a.png": "x",
        "review/art/old/README.md": fm(owner="heph", expires="2026-01-01"),
        "review/art/old/b.png": "x",
    }
    got = check(make(tmp_path, files), tmp_path)
    assert got == [
        "review/art/old/README.md: expired 2026-01-01 (owner heph) → harvest into the repo that "
        "owns it and delete, or re-review and move the date"
    ]


def test_keep_and_unmatched_paths_are_left_alone(tmp_path):
    files = {".claude/skill-context.md": CTX, "review/README.md": "# index\n", "notes/a.md": "x"}
    assert check(make(tmp_path, files), tmp_path) == ["cleanup ✓"]


def test_no_transient_globs_means_no_transient_check(tmp_path):
    assert check(make(tmp_path, {"review/a.md": "x"}), tmp_path) == ["cleanup ✓"]


def test_command_line_globs_add_to_the_repo_s(tmp_path):
    files = {"README.md": "x", "queue.md": "x", "done/W46.md": "x", ".git/config": "x"}
    got = check(
        make(tmp_path, files),
        tmp_path,
        "--only",
        "transient",
        "--transient",
        "**",
        "--keep",
        "README.md",
        "--keep",
        "queue.md",
    )
    assert got == [
        "done/W46.md has no owner + expires frontmatter → add it, or harvest the file into the "
        "repo that owns it and delete it"
    ]


@pytest.mark.parametrize(
    ("glob", "path", "hit"),
    [
        ("review/**", "review/a/b.png", True),
        ("review", "review/a.md", True),
        ("review/", "review/a.md", True),
        ("review/*", "review/a/b.md", True),  # a folder match covers what is under it
        ("review/*.md", "review/a.png", False),
        ("**/*.png", "x/y/z.png", True),
        ("**/*.png", "z.png", True),
        ("rev?ew/**", "review/a", True),
        ("review/**", "reviewer/a", False),
        ("a.b", "aXb", False),
    ],
)
def test_glob_cells(glob, path, hit):
    import importlib.util

    spec = importlib.util.spec_from_file_location("cleanup_mod", CLEANUP_SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert bool(mod.glob_regex(glob).match(path)) is hit


# --- exit codes ---------------------------------------------------------------------------


def test_ci_exits_1_on_a_finding_and_0_when_clean(tmp_path):
    bad = make(tmp_path, {"IMPL.md": lines(51)})
    assert run("check", "--ci", str(bad), home=tmp_path).returncode == 1
    assert run("check", str(bad), home=tmp_path).returncode == 0
    (bad / "IMPL.md").write_text(lines(5))
    assert run("check", "--ci", str(bad), home=tmp_path).returncode == 0


# --- prune --------------------------------------------------------------------------------

ROADMAP = "# R\n\n## Next\n- a\n\n## Completed\n- 10-01 x\n- 10-02 y\n\n## Backlog\n- b\n"


def test_prune_is_a_dry_run_until_apply(tmp_path):
    root = make(tmp_path, {"ROADMAP.md": ROADMAP}, git=True)
    out = run("prune", str(root), home=tmp_path)
    assert out.returncode == 0 and "would delete ROADMAP.md:6-9 'Completed'" in out.stdout
    assert (root / "ROADMAP.md").read_text() == ROADMAP
    out = run("prune", "--apply", str(root), home=tmp_path)
    assert out.returncode == 0, out.stdout
    assert (root / "ROADMAP.md").read_text() == "# R\n\n## Next\n- a\n\n## Backlog\n- b\n"


@pytest.mark.parametrize(
    ("text", "expect"),
    [
        ("# R\n\n## Next\n- a\n\n---\n\n## Shipped\n- x\n", "# R\n\n## Next\n- a\n"),
        (
            "# R\n\n---\n\n## Done\n- x\n\n---\n\n## Backlog\n- b\n",
            "# R\n\n---\n\n## Backlog\n- b\n",
        ),
        ("## Completed\n- x\n", ""),
    ],
)
def test_prune_leaves_no_dangling_rule(tmp_path, text, expect):
    root = make(tmp_path, {"ROADMAP.md": text}, git=True)
    assert run("prune", "--apply", "repo", home=tmp_path, cwd=tmp_path).returncode == 0
    assert (root / "ROADMAP.md").read_text() == expect


def test_prune_names_the_repo_when_given_a_dot(tmp_path):
    root = make(tmp_path, {"ROADMAP.md": ROADMAP}, git=True)
    out = run("prune", ".", home=tmp_path, cwd=root)
    assert out.stdout.startswith("repo: would delete")


def test_prune_with_nothing_to_do(tmp_path):
    root = make(tmp_path, {"ROADMAP.md": "# R\n## Next\n"}, git=True)
    out = run("prune", "--apply", str(root), home=tmp_path)
    assert out.returncode == 0 and "keeps no done-log" in out.stdout


def refused(root: Path, home: Path) -> str:
    before = (root / "ROADMAP.md").read_text() if (root / "ROADMAP.md").exists() else None
    out = run("prune", "--apply", str(root), home=home)
    assert out.returncode == 1, out.stdout
    after = (root / "ROADMAP.md").read_text() if (root / "ROADMAP.md").exists() else None
    assert before == after
    return out.stdout


def test_prune_refuses_an_untracked_roadmap(tmp_path):
    root = make(tmp_path, {"x": "y"}, git=True)
    (root / "ROADMAP.md").write_text(ROADMAP)
    assert "not tracked by git" in refused(root, tmp_path)


def test_prune_refuses_uncommitted_changes(tmp_path):
    root = make(tmp_path, {"ROADMAP.md": ROADMAP}, git=True)
    (root / "ROADMAP.md").write_text(ROADMAP + "- new\n")
    assert "uncommitted changes" in refused(root, tmp_path)


def test_prune_refuses_outside_git(tmp_path):
    root = make(tmp_path, {"ROADMAP.md": ROADMAP})
    assert "not tracked by git" in refused(root, tmp_path)


def test_prune_refuses_a_symlinked_roadmap(tmp_path):
    root = make(tmp_path, {"real.md": ROADMAP}, git=True)
    (root / "ROADMAP.md").symlink_to("real.md")
    assert "not a regular file" in refused(root, tmp_path)


def test_prune_refuses_when_the_repo_says_off(tmp_path):
    ctx = "## cleanup\n- prune: off (registered report)\n"
    root = make(tmp_path, {"ROADMAP.md": ROADMAP, ".claude/skill-context.md": ctx}, git=True)
    assert "prune: off (registered report)" in refused(root, tmp_path)


def roster(home: Path, ws: Path, extra: str) -> None:
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "techne.toml").write_text(
        f'github_user = "me"\nworkspace_root = "{ws}"\n\n'
        f'[[sisters]]\nname = "repo"\nstatus = "active"\n{extra}'
    )


def test_prune_refuses_a_registered_report_sister(tmp_path):
    root = make(tmp_path, {"ROADMAP.md": ROADMAP}, git=True)
    roster(tmp_path / "home", tmp_path, "registered_report = true\n")
    assert "registered_report" in refused(root, tmp_path / "home")


def test_prune_refuses_when_the_roster_cannot_be_read(tmp_path):
    root = make(tmp_path, {"ROADMAP.md": ROADMAP}, git=True)
    (tmp_path / "home" / ".claude").mkdir(parents=True)
    (tmp_path / "home" / ".claude" / "techne.toml").write_text("not = [toml")
    assert "the sister roster cannot be read" in refused(root, tmp_path / "home")


def test_prune_runs_for_an_unmarked_sister(tmp_path):
    root = make(tmp_path, {"ROADMAP.md": ROADMAP}, git=True)
    roster(tmp_path / "home", tmp_path, "")
    assert run("prune", "--apply", str(root), home=tmp_path / "home").returncode == 0
    assert "Completed" not in (root / "ROADMAP.md").read_text()


def test_transient_status_maps_each_governing_file_to_what_it_covers(tmp_path):
    """klepsydra's `fleet tidy expired` deletes exactly what an expired file governs."""
    import datetime as dt
    import importlib.util

    spec = importlib.util.spec_from_file_location("cleanup_mod2", CLEANUP_SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    files = {
        "review/art/README.md": fm(owner="heph", expires="2026-01-01"),
        "review/art/a.png": "x",
        "review/art/keep/README.md": fm(owner="heph", expires="2027-01-01"),
        "review/art/keep/b.png": "x",
        "review/note.md": fm(owner="heph", expires="2026-01-01"),
    }
    root = make(tmp_path, files)
    cfg = mod.Config()
    cfg.transient = ["review/**"]
    got = mod.transient_status(root, cfg, dt.date(2026, 11, 20))
    assert sorted(got.stale) == ["review/art/README.md", "review/note.md"]
    assert got.governs["review/art/README.md"] == ["review/art/README.md", "review/art/a.png"]
    assert got.governs["review/art/keep/README.md"] == [
        "review/art/keep/README.md",
        "review/art/keep/b.png",
    ]
    assert got.bare == {}


# --- rules: pruned as well as added -------------------------------------------------------

RULES_CTX = "## cleanup\n- rules: lessons/*.md\n"


def lesson(slug: str, **fields: str) -> str:
    return f"### {slug}: Name\n\n" + "".join(f"- **{k}:** {v}\n" for k, v in fields.items()) + "\n"


@pytest.mark.parametrize(
    ("fields", "expect"),
    [
        ({"Rule": "r", "Since": "2026-08-22"}, None),  # 90 days: still current
        ({"Rule": "r", "Since": "2026-08-21"}, "last dated 2026-08-21, over 90 days ago"),
        ({"Rule": "r", "Since": "2026-01-01", "Reviewed": "2026-11-01"}, None),
        ({"Incidents": "x (2026-01-02): a; y (2026-10-30): b"}, None),  # newest incident counts
        ({"Incidents": "none recorded."}, "has no Since, Reviewed or Incidents date"),
        ({"Rule": "r", "Since": "2020-01-01", "Retired": "make guards"}, None),
        ({"Rule": "r", "Why": "since 2026-11-01 it bites"}, "has no Since"),  # only dated fields
    ],
)
def test_a_rule_entry_needs_a_recent_date(tmp_path, fields, expect):
    root = make(
        tmp_path, {".claude/skill-context.md": RULES_CTX, "lessons/a.md": lesson("x", **fields)}
    )
    got = check(root, tmp_path)
    if expect is None:
        assert got == ["cleanup ✓"]
    else:
        assert len(got) == 1 and got[0].startswith("lessons/a.md:1 'x' ") and expect in got[0]


def test_numbered_entries_and_fenced_headings(tmp_path):
    text = (
        "```\n### fake: in a fence\n```\n### 3. real-one: Name\n- **Incidents:** none recorded.\n"
    )
    root = make(tmp_path, {".claude/skill-context.md": RULES_CTX, "lessons/a.md": text})
    got = check(root, tmp_path)
    assert len(got) == 1 and "lessons/a.md:4 'real-one'" in got[0]


@pytest.mark.parametrize(
    ("head", "expect"),
    [
        ("<!-- reviewed: 2026-11-01 -->\n", None),
        ("---\nreviewed: 2026-11-01\n---\n", None),
        ("<!-- reviewed: 2026-01-01 -->\n", "last reviewed 2026-01-01, over 90 days ago"),
        ("", "has no reviewed date"),
    ],
)
def test_a_rules_file_without_entries_needs_a_file_date(tmp_path, head, expect):
    ctx = "## cleanup\n- rules: CLAUDE.md\n"
    root = make(tmp_path, {".claude/skill-context.md": ctx, "CLAUDE.md": head + "# Rules\n- one\n"})
    got = check(root, tmp_path)
    assert (got == ["cleanup ✓"]) if expect is None else (expect in got[0])


# --- flaky tests: quarantined with an end date, then fixed or deleted ----------------------

MARK = "pytest.mark." + "flaky"  # built, so this file does not trip the check it tests


@pytest.mark.parametrize(
    ("text", "expect"),
    [
        (f"@{MARK}(" + "rer" + "uns=2)\ndef test_a(): ...\n", "no quarantine end"),
        (f"# quarantine: until 2026-12-01 #75\n@{MARK}\ndef test_a(): ...\n", None),
        (f"@{MARK}  # quarantine until 2026-11-20 #75\n", None),  # ends today
        (f"# quarantine: until 2026-11-19 #75\n@{MARK}\n", "quarantine ended 2026-11-19"),
        (f"# quarantine: until 2027-03-01\n@{MARK}\n", "past the 30-day limit"),
        (f"# quarantine: until 2026-12-01\n\n\n@{MARK}\n", "no quarantine end"),  # 3 lines up
        ("def test_a():\n    assert 'flaky' in names\n", None),  # the word alone is no marker
    ],
)
def test_a_flaky_marker_needs_a_live_quarantine(tmp_path, text, expect):
    root = make(tmp_path, {"tests/test_x.py": text}, git=True)
    got = check(root, tmp_path, "--only", "flaky")
    if expect is None:
        assert got == ["cleanup ✓"]
    else:
        assert len(got) == 1 and got[0].startswith("tests/test_x.py:") and expect in got[0]


@pytest.mark.parametrize(
    ("rel", "text"),
    [
        ("pyproject.toml", '[tool.pytest.ini_options]\naddopts = "--' + 'reruns 2"\n'),
        ("playwright.config.ts", "export default { retr" + "ies: 2 }\n"),
        ("src/a.test.ts", "jest.retry" + "Times(3)\n"),
        (".github/workflows/ci.yml", "    - uses: nick-fields/" + "retry@abc\n"),
        ("requirements-dev.txt", "pytest-rerun" + "failures==14\n"),
        ("tests/test_y.py", "@pytest.mark.skip(reason='fla" + "ky on CI')\n"),
    ],
)
def test_every_kind_of_retry_is_found(tmp_path, rel, text):
    root = make(tmp_path, {rel: text}, git=True)
    got = check(root, tmp_path, "--only", "flaky")
    assert len(got) == 1 and got[0].startswith(f"{rel}:{text.count(chr(10))} ")


def test_retries_outside_tests_and_in_untracked_files_are_left_alone(tmp_path):
    root = make(tmp_path, {"src/app.py": f"@{MARK}\n"}, git=True)
    (root / "tests").mkdir()
    (root / "tests" / "test_new.py").write_text(f"@{MARK}\n")  # untracked: not git's yet
    assert check(root, tmp_path, "--only", "flaky") == ["cleanup ✓"]


def test_outside_git_the_walk_skips_environments(tmp_path):
    root = make(tmp_path, {"tests/test_a.py": f"@{MARK}\n", ".venv/lib/test_b.py": f"@{MARK}\n"})
    got = check(root, tmp_path, "--only", "flaky")
    assert len(got) == 1 and got[0].startswith("tests/test_a.py:1")


# --- review round 1 regressions -----------------------------------------------------------


def load_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("cleanup_r1", CLEANUP_SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_prune_refuses_a_registered_sister_from_its_worktree(tmp_path):
    root = make(tmp_path, {"ROADMAP.md": ROADMAP}, git=True)
    wt = root / ".claude" / "worktrees" / "w"
    subprocess.run(["git", "-C", str(root), "worktree", "add", "-q", str(wt)], check=True)
    roster(tmp_path / "home", tmp_path, "registered_report = true\n")
    assert "registered_report" in refused(wt, tmp_path / "home")


def test_prune_refuses_a_registered_sister_cloned_elsewhere(tmp_path):
    src = make(tmp_path, {"ROADMAP.md": ROADMAP}, git=True)
    clone = tmp_path / "elsewhere" / "other-name"
    subprocess.run(["git", "clone", "-q", str(src), str(clone)], check=True)
    subprocess.run(
        ["git", "-C", str(clone), "remote", "set-url", "origin", "git@github.com:me/repo.git"],
        check=True,
    )
    ws = tmp_path / "ws"
    ws.mkdir()
    roster(tmp_path / "home", ws, "registered_report = true\n")
    assert "registered_report" in refused(clone, tmp_path / "home")


def test_prune_refuses_a_workspace_repo_that_is_no_sister(tmp_path):
    root = make(tmp_path, {"ROADMAP.md": ROADMAP}, git=True)
    (tmp_path / "home" / ".claude").mkdir(parents=True)
    (tmp_path / "home" / ".claude" / "techne.toml").write_text(
        f'github_user = "me"\nworkspace_root = "{tmp_path}"\n\n[[sisters]]\nname = "other"\n'
    )
    assert "in no [[sisters]] entry" in refused(root, tmp_path / "home")


def test_prune_refuses_a_roster_entry_without_a_name(tmp_path):
    root = make(tmp_path, {"ROADMAP.md": ROADMAP}, git=True)
    (tmp_path / "home" / ".claude").mkdir(parents=True)
    (tmp_path / "home" / ".claude" / "techne.toml").write_text(
        f'github_user = "me"\nworkspace_root = "{tmp_path}"\n\n[[sisters]]\nstatus = "active"\n'
    )
    assert "cannot be read" in refused(root, tmp_path / "home")


@pytest.mark.parametrize(
    "line",
    ["- prune: OFF", "- Prune: off", "prune: off", "- **prune:** off", "* prune: off (registered)"],
)
def test_prune_off_in_any_spelling_refuses(tmp_path, line):
    ctx = f"## cleanup\n{line}\n"
    root = make(tmp_path, {"ROADMAP.md": ROADMAP, ".claude/skill-context.md": ctx}, git=True)
    assert "prune:" in refused(root, tmp_path)


@pytest.mark.parametrize("line", ["- prune: false", "- prune: no", "- prune:"])
def test_a_prune_value_that_is_neither_off_nor_on_refuses(tmp_path, line):
    root = make(
        tmp_path,
        {"ROADMAP.md": ROADMAP, ".claude/skill-context.md": f"## cleanup\n{line}\n"},
        git=True,
    )
    assert "has an error" in refused(root, tmp_path)


def test_prune_on_is_allowed(tmp_path):
    root = make(
        tmp_path,
        {"ROADMAP.md": ROADMAP, ".claude/skill-context.md": "## cleanup\n- prune: on\n"},
        git=True,
    )
    assert run("prune", "--apply", str(root), home=tmp_path).returncode == 0


def test_prune_refuses_when_skill_context_cannot_be_read(tmp_path):
    root = make(tmp_path, {"ROADMAP.md": ROADMAP}, git=True)
    (root / ".claude").mkdir()
    (root / ".claude" / "skill-context.md").symlink_to(root / "gone.md")
    assert "has an error" in refused(root, tmp_path)


@pytest.mark.parametrize(
    ("after", "why"),
    [
        ("Backlog\n-------\n- b\n", "underlines the line above"),
        (" ## Backlog\n- b\n", "does not model"),
        ("> ## quoted\n", "does not model"),
        ("<details>\n## x\n</details>\n", "does not model"),
    ],
)
def test_prune_refuses_a_span_a_reader_may_cut_elsewhere(tmp_path, after, why):
    text = "# R\n\n## Completed\n- x\n" + after + "## Next\n- n\n"
    root = make(tmp_path, {"ROADMAP.md": text}, git=True)
    assert why in refused(root, tmp_path)


def test_an_info_string_fence_line_does_not_close_a_fence(tmp_path):
    text = "# R\n## Completed\n```\n```js\n## not a heading\n```\n## Backlog\n- keep\n"
    root = make(tmp_path, {"ROADMAP.md": text}, git=True)
    assert run("prune", "--apply", str(root), home=tmp_path).returncode == 0
    assert (root / "ROADMAP.md").read_text() == "# R\n## Backlog\n- keep\n"


@pytest.mark.parametrize(
    ("text", "expect"),
    [
        (  # a kept code fence keeps its double blank line
            "# R\n\n```py\nx = 1\n\n\ny = 2\n```\n\n## Done\n- x\n\n## Next\n",
            "# R\n\n```py\nx = 1\n\n\ny = 2\n```\n\n## Next\n",
        ),
        (  # frontmatter keeps its closing fence when the done-log is last
            "---\ntitle: Roadmap\n---\n## Completed\n- x\n",
            "---\ntitle: Roadmap\n---\n",
        ),
        ("# R\n- a\n## Done\n- x\n## Next\n", "# R\n- a\n## Next\n"),  # no blank stays none
    ],
)
def test_prune_changes_nothing_away_from_the_cut(tmp_path, text, expect):
    root = make(tmp_path, {"ROADMAP.md": text}, git=True)
    assert run("prune", "--apply", str(root), home=tmp_path).returncode == 0
    assert (root / "ROADMAP.md").read_text() == expect


def test_a_heading_after_a_nested_done_log_is_kept(tmp_path):
    text = "# R\n## Shipped\n- a\n### Completed\n- b\n## Next\n- n\n"
    root = make(tmp_path, {"ROADMAP.md": text}, git=True)
    out = run("done-log", str(root), home=tmp_path).stdout
    assert "ROADMAP.md:2-5 'Shipped'" in out and "Completed" not in out.split("=====")[1]


def test_prune_refuses_when_the_file_changes_mid_prune(tmp_path, monkeypatch, capsys):
    mod = load_module()
    root = make(tmp_path, {"ROADMAP.md": ROADMAP}, git=True)
    monkeypatch.setenv("HOME", str(tmp_path))
    real = mod.read_text
    calls = {"n": 0}

    def moving(path, *a, **k):
        text = real(path, *a, **k)
        if path.name == "ROADMAP.md":
            calls["n"] += 1
            if calls["n"] > 1:
                return (text or "") + "- added meanwhile\n"
        return text

    monkeypatch.setattr(mod, "read_text", moving)
    assert mod.prune(root, True) == 1
    assert "changed during the prune" in capsys.readouterr().out
    assert (root / "ROADMAP.md").read_text() == ROADMAP


def test_prune_refuses_when_git_status_fails(tmp_path, monkeypatch, capsys):
    mod = load_module()
    root = make(tmp_path, {"ROADMAP.md": ROADMAP}, git=True)
    monkeypatch.setenv("HOME", str(tmp_path))
    real = mod.git_out

    def failing(r, *args):
        out = real(r, *args)
        if args[:1] == ("status",):
            out.returncode, out.stdout = 128, ""
        return out

    monkeypatch.setattr(mod, "git_out", failing)
    assert mod.prune(root, True) == 1
    assert "uncommitted changes" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("until", "expect"),
    [("2026-12-20", None), ("2026-12-21", "past the 30-day limit")],  # 30 days, 31 days
)
def test_quarantine_limit_boundary(tmp_path, until, expect):
    root = make(
        tmp_path, {"tests/test_x.py": f"# quarantine: until {until} #1\n@{MARK}\n"}, git=True
    )
    got = check(root, tmp_path, "--only", "flaky")
    assert (got == ["cleanup ✓"]) if expect is None else (expect in got[0])


@pytest.mark.parametrize("reason", ["flake8 noise", "flakes8"])
def test_flake8_in_a_skip_reason_is_no_flaky_marker(tmp_path, reason):
    root = make(tmp_path, {"tests/test_x.py": f"@pytest.mark.skip(reason='{reason}')\n"}, git=True)
    assert check(root, tmp_path, "--only", "flaky") == ["cleanup ✓"]


def test_a_readme_without_owner_fields_does_not_govern(tmp_path):
    files = {
        ".claude/skill-context.md": CTX,
        "review/README.md": "---\nowner: heph\nexpires: 2026-12-01\n---\n",
        "review/drafts/README.md": "---\ntitle: drafts\n---\n",
        "review/drafts/a.png": "x",
    }
    root = make(tmp_path, files)
    assert check(root, tmp_path) == ["cleanup ✓"]


@pytest.mark.parametrize(
    ("files", "flagged"),
    [
        ({"review/a.md": fm(owner="heph", expires="2020-01-01")}, False),  # expired: a date decides
        ({"review/a.md": fm(owner="heph")}, True),  # no date at all: no date decides
        ({"review/a.md": fm(owner="heph", expires="soon")}, True),  # malformed date
        ({"lessons/a.md": lesson("x", Since="2020-01-01")}, False),  # old rule: a date decides
        ({"lessons/a.md": lesson("x", Rule="r")}, True),  # undated rule
        ({"tests/test_x.py": f"# quarantine: until 2020-01-01\n@{MARK}\n"}, False),
        ({"tests/test_x.py": f"@{MARK}\n"}, True),  # no quarantine at all
    ],
)
def test_no_dates_keeps_only_what_no_date_decides(tmp_path, files, flagged):
    ctx = "## cleanup\n- transient: review/**\n- rules: lessons/*.md\n"
    root = make(tmp_path, {".claude/skill-context.md": ctx, **files}, git=True)
    got = check(root, tmp_path, "--no-dates")
    assert (got != ["cleanup ✓"]) is flagged, got


def test_lesson_glob_with_a_wildcard_before_the_first_slash(tmp_path):
    ctx = "## cleanup\n- rules: lesson*/x.md\n"
    root = make(
        tmp_path, {".claude/skill-context.md": ctx, "lessons-a/x.md": lesson("y", Rule="r")}
    )
    assert any("lessons-a/x.md:1 'y'" in g for g in check(root, tmp_path))


# --- mutation round: exact output, environment, wiring --------------------------------------

GOLDEN_FILES = {
    ".claude/skill-context.md": (
        "## cleanup\n- transient: review/**\n- rules: lessons/*.md\n- impl_lines: 2\n"
        "- agent_bytes: 200\n"
    ),
    "ROADMAP.md": "# R\n## Next\n## Completed\n- x\n",
    "IMPL.md": "a\nb\nc\n",
    "AGENTS.md": "x" * 250 + "\n",
    "review/a.md": fm(owner="heph", expires="2026-11-01"),
    "review/b.md": "# no frontmatter\n",
    "review/art/1.png": "x",
    "review/art/2.png": "x",
    "review/art/3.png": "x",
    "review/art/4.png": "x",
    "lessons/l.md": lesson("old", Since="2026-01-01") + lesson("bare", Rule="r"),
    "tests/test_q.py": "@" + MARK + "\n",
}
GOLDEN = """\
repo: ROADMAP.md:3 'Completed' keeps a log of finished work (lines 3-4) → harvest its lessons and open follow-ups, then delete it (/techne:sisters clean); git and GitHub hold the record
repo: IMPL.md has 3 lines, over its 2-line budget → rewrite it as the current slice: done, next, verify
repo: AGENTS.md has 251 bytes, over the 200-byte budget for agent instructions → move what a hook or check can enforce into one, and cut what the code shows
repo: review/b.md has no owner + expires frontmatter → add it, or harvest the file into the repo that owns it and delete it
repo: review/art/ holds 4 file(s) with no owner + expires (1.png, 2.png, 3.png, ...) → add a README.md there with that frontmatter, or harvest the files into the repo that owns them and delete them
repo: review/a.md: expired 2026-11-01 (owner heph) → harvest into the repo that owns it and delete, or re-review and move the date
repo: lessons/l.md:1 'old' last dated 2026-01-01, over 90 days ago → still earning its place? add `- **Reviewed:** 2026-11-20`, or delete it (git keeps it)
repo: lessons/l.md:5 'bare' has no Since, Reviewed or Incidents date → add `- **Reviewed:** 2026-11-20` if it still earns its place, or retire it
repo: tests/test_q.py:1 retries or marks a test flaky with no quarantine end → fix the test or delete it; to buy time, add `quarantine: until 2026-12-20 #<issue>` beside it
"""  # noqa: E501


def test_every_finding_reads_exactly_as_documented(tmp_path):
    root = make(tmp_path, GOLDEN_FILES, git=True)
    out = run("check", "--today", TODAY, str(root), home=tmp_path)
    assert out.returncode == 0
    assert out.stdout == GOLDEN


def test_git_variables_from_a_hook_never_redirect_git(tmp_path):
    """From a worktree a git hook exports GIT_DIR and GIT_INDEX_FILE; the check must still read
    the repo it was pointed at."""
    root = make(tmp_path, {"ROADMAP.md": ROADMAP, "tests/test_q.py": "@" + MARK + "\n"}, git=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env |= {"HOME": str(tmp_path), "GIT_DIR": str(tmp_path / "nope"), "GIT_INDEX_FILE": "/nope"}
    flaky = subprocess.run(
        [sys.executable, str(CLEANUP_SCRIPT), "check", "--only", "flaky", str(root)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert "tests/test_q.py:1" in flaky.stdout
    prune = subprocess.run(
        [sys.executable, str(CLEANUP_SCRIPT), "prune", "--apply", str(root)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert prune.returncode == 0, prune.stdout
    assert "Completed" not in (root / "ROADMAP.md").read_text()


def test_prune_writes_a_hidden_temp_file_beside_the_roadmap(tmp_path, monkeypatch):
    mod = load_module()
    root = make(tmp_path, {"ROADMAP.md": ROADMAP}, git=True)
    monkeypatch.setenv("HOME", str(tmp_path))
    seen = []
    real = os.replace

    def spy(src, dst):
        seen.append((Path(src), Path(dst)))
        assert Path(src).read_bytes().endswith(b"## Backlog\n- b\n")
        real(src, dst)

    monkeypatch.setattr(mod.os, "replace", spy)
    assert mod.prune(root.resolve(), True) == 0
    ((src, dst),) = seen
    assert src.parent == root.resolve() and dst == root.resolve() / "ROADMAP.md"
    assert src.name.startswith(".ROADMAP.") and src.name.endswith(".tmp")
    assert not src.exists()


def test_prune_keeps_crlf_and_writes_utf8(tmp_path):
    text = "# R ✅\r\n\r\n## Completed\r\n- x\r\n\r\n## Next\r\n- é\r\n"
    root = tmp_path / "repo"
    root.mkdir()
    (root / "ROADMAP.md").write_bytes(text.encode())
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    g = [
        "git",
        "-C",
        str(root),
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@t",
        "-c",
        "core.autocrlf=false",
    ]
    subprocess.run([*g, "add", "-A"], check=True)
    subprocess.run([*g, "commit", "-qm", "i"], check=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "LC_", "LANG"))}
    env |= {"HOME": str(tmp_path), "LC_ALL": "C", "PYTHONUTF8": "0"}
    out = subprocess.run(
        [sys.executable, str(CLEANUP_SCRIPT), "prune", "--apply", str(root)],
        capture_output=True,
        env=env,
        check=False,
    )
    assert out.returncode == 0, out
    assert (root / "ROADMAP.md").read_bytes() == "# R ✅\r\n\r\n## Next\r\n- é\r\n".encode()


@pytest.mark.parametrize(
    ("args", "code"),
    [(["check"], 2), (["check", "--only", "nonsense", "."], 2), ([], 2), (["prune"], 2)],
)
def test_bad_command_lines_exit_2(tmp_path, args, code):
    assert run(*args, home=tmp_path).returncode == code


def test_help_names_the_program_and_hides_today(tmp_path):
    out = run("check", "--help", home=tmp_path).stdout
    assert out.startswith("usage: cleanup.py check") and "--today" not in out
    top = run("--help", home=tmp_path).stdout
    assert "finished work lives in git and GitHub" in top


def test_main_reads_its_own_arguments_not_sys_argv(tmp_path, monkeypatch, capsys):
    mod = load_module()
    root = make(tmp_path, {"IMPL.md": lines(51)})
    monkeypatch.setattr(sys, "argv", ["pytest", "--whatever"])
    assert mod.main(["check", "--ci", str(root)]) == 1
    assert "IMPL.md has 51 lines" in capsys.readouterr().out


def test_ci_fails_when_any_root_has_a_finding(tmp_path):
    bad = make(tmp_path, {"IMPL.md": lines(51)})
    good = tmp_path / "good"
    good.mkdir()
    assert run("check", "--ci", str(bad), str(good), home=tmp_path).returncode == 1


def test_repeated_options_all_apply(tmp_path):
    root = make(tmp_path, {"a/x.md": "x", "b/y.md": "y", "IMPL.md": lines(51)})
    got = check(
        root,
        tmp_path,
        "--only",
        "transient",
        "--only",
        "impl",
        "--transient",
        "a/**",
        "--transient",
        "b/**",
    )
    assert len(got) == 3 and any("a/x.md" in g for g in got) and any("b/y.md" in g for g in got)


def test_today_is_read_from_the_command_line(tmp_path):
    root = make(
        tmp_path,
        {".claude/skill-context.md": CTX, "review/a.md": fm(owner="h", expires="2026-02-01")},
    )
    assert check(root, tmp_path) != ["cleanup ✓"]  # --today 2026-11-20: expired
    got = run("check", "--today", "2026-01-15", str(root), home=tmp_path).stdout
    assert got.endswith(": cleanup ✓\n")


def test_a_path_that_is_not_utf8_prints(tmp_path):
    root = make(tmp_path, {".claude/skill-context.md": CTX})
    (root / "review").mkdir()
    (root / os.fsdecode(b"review/caf\xe9.md")).write_text("x")
    out = run("check", "--today", TODAY, str(root), home=tmp_path)
    assert out.returncode == 0 and "caf\\udce9.md has no owner" in out.stdout


@pytest.mark.parametrize(
    "head",
    [
        "﻿---\nowner: heph\nexpires: 2026-12-01\n---\n",  # a byte-order mark
        "---\nowner: heph\nexpires: 2026-12-01\n...\n",  # YAML's other end marker
        "---\nOwner: heph\nExpires: 2026-12-01\n---\n",  # keys in any case
        "---\nowner: 'heph'\nexpires: \"2026-12-01\"\n---\n",  # quoted values
    ],
)
def test_frontmatter_shapes_that_count(tmp_path, head):
    root = make(tmp_path, {".claude/skill-context.md": CTX, "review/a.md": head + "# body\n"})
    assert check(root, tmp_path) == ["cleanup ✓"]


@pytest.mark.parametrize(
    "value",
    ["2026-12-01junk", "2026-12-01T10:00", "26-12-01", ""],
)
def test_a_date_with_anything_else_is_no_date(tmp_path, value):
    root = make(
        tmp_path, {".claude/skill-context.md": CTX, "review/a.md": fm(owner="h", expires=value)}
    )
    assert check(root, tmp_path) != ["cleanup ✓"]


@pytest.mark.parametrize(
    ("glob", "path", "hit"),
    [
        ("./review/**", "review/a", True),
        ("././review", "review/a", True),
        ("a/**/b.md", "a/b.md", True),
        ("a/**/b.md", "a/x/y/b.md", True),
        ("a/**", "a/x/y", True),
        ("**", "x/y/z", True),
        ("*.md", "x/a.md", False),
        ("a/*/c", "a/b/c", True),
    ],
)
def test_more_glob_cells(glob, path, hit):
    assert bool(load_module().glob_regex(glob).match(path)) is hit


@pytest.mark.parametrize(
    "glob", ["docs/agent.md", "**/agent.md", "docs/*.md", "*/agent.md", "missing/*.md"]
)
def test_agent_file_globs_find_files_wherever_the_base_is(tmp_path, glob):
    ctx = f"## cleanup\n- agent_file: {glob}\n"
    root = make(tmp_path, {".claude/skill-context.md": ctx, "docs/agent.md": lines(201)})
    got = check(root, tmp_path, "--only", "agents")
    assert got == (
        ["cleanup ✓"]
        if glob.startswith("missing")
        else [
            "docs/agent.md has 201 lines, over the 200-line budget for agent instructions → move "
            "what a hook or check can enforce into one, and cut what the code shows"
        ]
    )


def test_config_lines_after_a_bad_one_still_count(tmp_path):
    ctx = (
        "## cleanup\n- impl_lines: lots\n- colour: red\n- transient:\n- transient: <placeholder>\n"
        "- impl_lines: 2\n"
    )
    root = make(tmp_path, {".claude/skill-context.md": ctx, "IMPL.md": lines(3)})
    got = check(root, tmp_path)
    assert any("IMPL.md has 3 lines, over its 2-line budget" in g for g in got)
    assert sum("## cleanup:" in g for g in got) == 3


def test_every_unreadable_agent_file_and_overrun_is_reported(tmp_path):
    root = make(tmp_path, {"CLAUDE.md": lines(201)})
    os.mkfifo(root / "AGENTS.md")
    got = check(root, tmp_path)
    assert got[0] == "AGENTS.md is not a regular file → make it a regular file"
    assert got[1].startswith("CLAUDE.md has 201 lines")


def test_every_root_level_and_folder_finding_is_listed(tmp_path):
    files = {"x.md": "x", "y.md": "y", "f1/a.png": "x", "f2/b.png": "x"}
    got = check(make(tmp_path, files), tmp_path, "--only", "transient", "--transient", "**")
    assert len(got) == 4


def test_done_log_output_and_codes(tmp_path):
    root = make(tmp_path, {"ROADMAP.md": "# R\n## Done\n- a\n- b\n## Next\n"})
    out = run("done-log", str(root), home=tmp_path)
    assert out.returncode == 0
    assert out.stdout == "===== ROADMAP.md:2-4 'Done' =====\n## Done\n- a\n- b\n"
    empty = tmp_path / "empty"
    empty.mkdir()
    out = run("done-log", str(empty), home=tmp_path)
    assert (out.returncode, out.stdout) == (0, "empty: ROADMAP.md keeps no done-log ✓\n")
    os.mkfifo(empty / "ROADMAP.md")
    out = run("done-log", str(empty), home=tmp_path)
    assert (out.returncode, out.stdout) == (1, "empty: ROADMAP.md is not a regular file\n")


def test_prune_output_dry_and_applied(tmp_path):
    root = make(tmp_path, {"ROADMAP.md": ROADMAP}, git=True)
    dry = run("prune", str(root), home=tmp_path)
    assert dry.stdout == (
        "repo: would delete ROADMAP.md:6-9 'Completed'\n"
        "repo: dry run; harvest first (cleanup.py done-log), then --apply\n"
    )
    done = run("prune", "--apply", str(root), home=tmp_path)
    assert done.stdout == (
        "repo: deleting ROADMAP.md:6-9 'Completed'\n"
        "repo: done; `git diff ROADMAP.md` shows it, and git history keeps the text\n"
    )
