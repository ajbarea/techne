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
        ("noteX", "noteX", True),  # a trailing X is part of the name
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


# --- mutation round 2: every message whole, and the cells mutants survived -------------------


def one(root: Path, home: Path, *extra: str) -> str:
    got = check(root, home, *extra)
    assert len(got) == 1, got
    return got[0]


def test_flaky_messages_read_whole(tmp_path):
    r = make(tmp_path, {"tests/test_x.py": "@" + MARK + "\n"}, git=True)
    assert one(r, tmp_path, "--only", "flaky", "--no-dates") == (
        "tests/test_x.py:1 retries or marks a test flaky with no quarantine end → fix the test or "
        "delete it; to buy time, add `quarantine: until YYYY-MM-DD #<issue>` beside it"
    )
    (r / "tests/test_x.py").write_text("# quarantine: until 2026-11-01 #1\n@" + MARK + "\n")
    assert one(r, tmp_path, "--only", "flaky") == (
        "tests/test_x.py:2 quarantine ended 2026-11-01 → fix the test or delete it (git keeps it); "
        "a retry teaches the agent to rerun until green"
    )
    (r / "tests/test_x.py").write_text("# quarantine: until 2027-01-01 #1\n@" + MARK + "\n")
    assert one(r, tmp_path, "--only", "flaky") == (
        "tests/test_x.py:2 quarantine runs to 2027-01-01, past the 30-day limit → fix it sooner, "
        "or delete it"
    )


def test_a_quarantine_below_the_marker_does_not_count(tmp_path):
    r = make(
        tmp_path, {"tests/test_x.py": "@" + MARK + "\n# quarantine: until 2026-12-01\n"}, git=True
    )
    assert "no quarantine end" in one(r, tmp_path, "--only", "flaky")


def test_every_flaky_file_and_marker_is_reported(tmp_path):
    files = {
        "tests/test_a.py": "x = 1\n",  # no marker: skipped, never stops the scan
        "tests/test_b.py": "@" + MARK + "\n@" + MARK + "\n",
        "tests/test_c.py": "@" + MARK + "\n",
    }
    r = make(tmp_path, files, git=True)
    got = check(r, tmp_path, "--only", "flaky")
    assert [g.split(" ")[0] for g in got] == [
        "tests/test_b.py:1",
        "tests/test_b.py:2",
        "tests/test_c.py:1",
    ]


def test_outside_git_the_walk_finds_tests_at_every_depth(tmp_path):
    files = {
        "test_top.py": "@" + MARK + "\n",
        "a/b/test_deep.py": "@" + MARK + "\n",
        "c/test_c.py": "@" + MARK + "\n",
    }
    got = check(make(tmp_path, files), tmp_path, "--only", "flaky")
    assert sorted(g.split(" ")[0] for g in got) == [
        "a/b/test_deep.py:1",
        "c/test_c.py:1",
        "test_top.py:1",
    ]


def test_git_from_a_hook_cannot_turn_the_test_list_into_a_walk(tmp_path):
    root = make(tmp_path, {"README.md": "x"}, git=True)
    (root / "tests").mkdir()
    (root / "tests" / "test_untracked.py").write_text("@" + MARK + "\n")  # a walk would see it
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env |= {"HOME": str(tmp_path), "GIT_DIR": str(tmp_path / "nope")}
    out = subprocess.run(
        [sys.executable, str(CLEANUP_SCRIPT), "check", "--only", "flaky", str(root)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert out.stdout.endswith(": cleanup ✓\n"), out.stdout


def test_rules_messages_read_whole(tmp_path):
    ctx = "## cleanup\n- rules: CLAUDE.md\n- rules: lessons/*.md\n"
    files = {
        ".claude/skill-context.md": ctx,
        "CLAUDE.md": "# Rules\n",
        "lessons/l.md": lesson("x", Rule="r"),
    }
    r = make(tmp_path, files)
    assert check(r, tmp_path, "--no-dates") == [
        "CLAUDE.md has no reviewed date → add `<!-- reviewed: YYYY-MM-DD -->` once its rules have "
        "been reviewed (cut each one a check now enforces)",
        "lessons/l.md:1 'x' has no Since, Reviewed or Incidents date → add `- **Reviewed:** "
        "YYYY-MM-DD` if it still earns its place, or retire it",
    ]
    (r / "CLAUDE.md").write_text("<!-- reviewed: 2026-01-01 -->\n# Rules\n")
    assert check(r, tmp_path)[0] == (
        "CLAUDE.md last reviewed 2026-01-01, over 90 days ago → prune it: cut each rule a check "
        "enforces or the code shows, then set reviewed: 2026-11-20"
    )


@pytest.mark.parametrize(("day", "stale"), [("2026-08-22", False), ("2026-08-21", True)])
def test_a_rules_file_date_boundary(tmp_path, day, stale):
    r = make(
        tmp_path,
        {
            ".claude/skill-context.md": "## cleanup\n- rules: CLAUDE.md\n",
            "CLAUDE.md": f"<!-- reviewed: {day} -->\n",
        },
    )
    assert (check(r, tmp_path) != ["cleanup ✓"]) is stale


@pytest.mark.parametrize(("line", "counts"), [(29, True), (30, False)])
def test_the_reviewed_marker_is_read_in_the_first_30_lines(tmp_path, line, counts):
    text = "x\n" * line + "<!-- reviewed: 2026-11-01 -->\n"
    r = make(
        tmp_path,
        {".claude/skill-context.md": "## cleanup\n- rules: CLAUDE.md\n", "CLAUDE.md": text},
    )
    assert (check(r, tmp_path) == ["cleanup ✓"]) is counts


def test_every_rules_file_and_entry_is_checked(tmp_path):
    ctx = "## cleanup\n- rules: a.md\n- rules: b.md\n- rules: c.md\n"
    files = {
        ".claude/skill-context.md": ctx,
        "b.md": (
            "## Part\n### one: x\n- **Since:** 2026-11-01\n## Other\n### two: y\n- **Rule:** r\n"
        ),
        "c.md": lesson("three", Rule="r"),
    }
    r = make(tmp_path, files)
    os.mkfifo(r / "a.md")
    got = check(r, tmp_path)
    assert got[0] == "a.md is not a regular file → make it a regular file"
    assert ["two" in g for g in got[1:]] == [True, False] and "'three'" in got[2]


def test_a_bad_date_after_a_good_one_keeps_the_good(tmp_path):
    text = "### x: n\n- **Incidents:** a (2026-11-01): y; b (2026-02-30): z\n"
    r = make(tmp_path, {".claude/skill-context.md": "## cleanup\n- rules: r.md\n", "r.md": text})
    assert check(r, tmp_path) == ["cleanup ✓"]


def test_the_newest_of_several_dates_counts(tmp_path):
    text = "### x: n\n- **Since:** 2026-11-01\n- **Reviewed:** 2020-01-01\n"
    r = make(tmp_path, {".claude/skill-context.md": "## cleanup\n- rules: r.md\n", "r.md": text})
    assert check(r, tmp_path) == ["cleanup ✓"]


def test_prune_refusal_messages_read_whole(tmp_path):
    root = make(tmp_path, {"x": "y"}, git=True)
    (root / "ROADMAP.md").write_text(ROADMAP)
    assert refused(root, tmp_path) == (
        "repo: refused: ROADMAP.md is not tracked by git, so a deletion could not be recovered "
        "→ commit it first\n"
    )
    subprocess.run(["git", "-C", str(root), "add", "ROADMAP.md"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "r"],
        check=True,
    )
    (root / "ROADMAP.md").write_text(ROADMAP + "x\n")
    assert refused(root, tmp_path) == (
        "repo: refused: ROADMAP.md has uncommitted changes → commit or drop them first, so the "
        "prune is its own diff\n"
    )
    (root / "ROADMAP.md").unlink()
    (root / "ROADMAP.md").symlink_to("x")
    assert refused(root, tmp_path) == "repo: refused: ROADMAP.md is not a regular file\n"


def test_another_dirty_file_does_not_block_the_prune(tmp_path):
    root = make(tmp_path, {"ROADMAP.md": ROADMAP, "other.md": "a"}, git=True)
    (root / "other.md").write_text("changed")
    assert run("prune", "--apply", str(root), home=tmp_path).returncode == 0


def test_registered_message_reads_whole(tmp_path):
    root = make(tmp_path, {"ROADMAP.md": ROADMAP}, git=True)
    roster(tmp_path / "home", tmp_path, "registered_report = true\n")
    assert refused(root, tmp_path / "home") == (
        "repo: refused: techne.toml marks it registered_report: its text is never edited → change "
        "nothing\n"
    )


@pytest.mark.parametrize(
    "url",
    [
        "git@github.com:me/repo.git",
        "https://github.com/me/repo",
        "https://github.com/me/repo/",
        "ssh://git@github.com:22/me/repo.git",
        "repo",
    ],
)
def test_a_registered_clone_is_found_by_any_origin_form(tmp_path, url):
    src = make(tmp_path, {"ROADMAP.md": ROADMAP}, git=True)
    clone = tmp_path / "elsewhere" / "other"
    subprocess.run(["git", "clone", "-q", str(src), str(clone)], check=True)
    subprocess.run(["git", "-C", str(clone), "remote", "set-url", "origin", url], check=True)
    ws = tmp_path / "ws"
    ws.mkdir()
    roster(tmp_path / "home", ws, "registered_report = true\n")
    assert "registered_report" in refused(clone, tmp_path / "home")


def test_a_roster_without_workspace_root_still_matches_by_name(tmp_path):
    root = make(tmp_path, {"ROADMAP.md": ROADMAP}, git=True)
    (tmp_path / "home" / ".claude").mkdir(parents=True)
    (tmp_path / "home" / ".claude" / "techne.toml").write_text(
        'github_user = "me"\n\n[[sisters]]\nname = "repo"\nregistered_report = true\n'
    )
    assert "registered_report" in refused(root, tmp_path / "home")


def test_main_worktree_and_sys_path(tmp_path, monkeypatch):
    mod = load_module()
    root = make(tmp_path, {"x": "y"}, git=True)
    wt = tmp_path / "wt"
    subprocess.run(["git", "-C", str(root), "worktree", "add", "-q", str(wt)], check=True)
    assert mod.main_worktree(wt) == root.resolve()
    assert mod.main_worktree(root) == root.resolve()
    plain = tmp_path / "plain"
    plain.mkdir()
    assert mod.main_worktree(plain) == plain.resolve()
    before = list(sys.path)
    monkeypatch.setenv("HOME", str(tmp_path))
    mod.roster_refusal(root)
    assert sys.path == before


def test_prune_outside_git_with_a_roster_refuses_cleanly(tmp_path):
    root = make(tmp_path, {"ROADMAP.md": ROADMAP})
    roster(tmp_path / "home", tmp_path, "")
    assert "not tracked by git" in refused(root, tmp_path / "home")


def test_prune_removes_its_temp_file_when_the_replace_fails(tmp_path, monkeypatch):
    mod = load_module()
    root = make(tmp_path, {"ROADMAP.md": ROADMAP}, git=True)
    monkeypatch.setenv("HOME", str(tmp_path))

    def fail(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(mod.os, "replace", fail)
    with pytest.raises(OSError):
        mod.prune(root.resolve(), True)
    assert sorted(p.name for p in root.iterdir() if p.name != ".git") == ["ROADMAP.md"]
    assert (root / "ROADMAP.md").read_text() == ROADMAP


@pytest.mark.parametrize(
    ("text", "expect"),
    [
        ("---\n---\n## Done\n- x\n", "---\n---\n"),  # empty frontmatter keeps its close
        ("# R\n\n---\n\n## Done\n- x\n", "# R\n"),  # a dangling rule at the end goes
        (
            "# R\n\n---\n\n## Done\n- x\n\n## Next\n",
            "# R\n\n---\n\n## Next\n",
        ),  # a rule before a heading stays
        ("# R\r\n\r\n---\r\n\r\n## Done\r\n- x\r\n", "# R\r\n"),  # CRLF rules too
        ("## Done\n- x\n## Next\n- a", "## Next\n- a\n"),  # a last line without newline gets one
        ("## Done\n- x\n## Next\n## Shipped\n- y\n## Last\n", "## Next\n## Last\n"),  # two cuts
        ("---\ntitle: R\n...\n## Done\n- x\n", "---\ntitle: R\n...\n"),  # YAML's ... end
    ],
)
def test_without_edge_cells(text, expect):
    mod = load_module()
    assert mod.without(text, mod.done_sections(text)) == expect


@pytest.mark.parametrize(
    ("text", "names"),
    [
        ("## Completed\n- a\n## Shipped\n- b\n", ["Completed", "Shipped"]),  # back to back
        (
            "## Shipped\n### Completed\n## Next\n## Done\n- d\n",
            ["Shipped", "Done"],
        ),  # after a nested one
    ],
)
def test_done_sections_cells(text, names):
    assert [t for _, _, t in load_module().done_sections(text)] == names


def test_span_hazard_looks_one_line_past_the_span_and_no_further():
    mod = load_module()
    lines = "## Completed\n- x\n## Next\nNext para\n---\n".splitlines()
    assert mod.span_hazard(lines, 1, 2) is None
    lines = "## Completed\nPara\n---\n## Next\n".splitlines()
    assert (
        mod.span_hazard(lines, 1, 3)
        == "line 3 underlines the line above it, which a reader may take for a heading"
    )
    lines = "## Completed\n> " + "q" * 60 + "\n".splitlines()[0]
    assert mod.span_hazard(lines.splitlines(), 1, 2) == (
        "line 2 ('> " + "q" * 38 + "') is a shape the scanner does not model"
    )


def test_matching_files_walks_only_the_fixed_folder(tmp_path, monkeypatch):
    mod = load_module()
    root = make(tmp_path, {"docs/a.md": "x", "docs/sub/b.md": "x", "other/c.md": "x"})
    starts = []
    real = mod.walk_files
    monkeypatch.setattr(mod, "walk_files", lambda p: (starts.append(p), real(p))[1])
    assert mod.matching_files(root, ["docs/*.md"]) == ["docs/a.md"]
    assert mod.matching_files(root, ["docs/sub/b.md"]) == ["docs/sub/b.md"]
    assert mod.matching_files(root, ["missing/x/*.md"]) == []
    assert mod.matching_files(root, ["*/c.md"]) == ["other/c.md"]
    assert starts == [root / "docs", root / "docs/sub", root, root]


def test_load_config_details(tmp_path):
    mod = load_module()
    ctx = (
        "## cleanup\n- transient: <placeholder>\n- prune: `off`\n- colour: x\n- keep: k/**\n"
        "- impl_lines: 7\n"
    )
    r = make(tmp_path, {".claude/skill-context.md": ctx})
    cfg = mod.load_config(r)
    assert cfg.transient == [] and cfg.keep == ["k/**"] and cfg.prune_off == "`off`"
    assert cfg.budgets["impl_lines"] == 7
    assert cfg.errors == ["## cleanup: unknown key 'colour' → see cleanup.py's usage"]
    (tmp_path / "b").mkdir()
    bad = make(tmp_path / "b", {".claude/skill-context.md": "## cleanup\n- prune: maybe\n"})
    assert mod.load_config(bad).errors == [
        "## cleanup: prune 'maybe' is neither off nor on → write one"
    ]


def test_an_unreadable_skill_context_is_named(tmp_path):
    r = make(tmp_path, {})
    (r / ".claude").mkdir()
    os.mkfifo(r / ".claude" / "skill-context.md")
    assert check(r, tmp_path)[0] == (
        ".claude/skill-context.md is not a regular file → make it a regular file"
    )


def test_read_text_limits(tmp_path):
    mod = load_module()
    f = tmp_path / "f"
    f.write_bytes(b"abcd")
    assert mod.read_text(f, 4) == "abcd"
    with pytest.raises(mod.Unreadable, match=r"^is over 3 bytes$"):
        mod.read_text(f, 3)
    assert mod.read_text(f, 3, head=True) == "abc"
    assert mod.read_text(f, 4, head=True) == "abcd"
    f.write_bytes(b"a\xffb")
    assert mod.byte_count(mod.read_text(f)) == 3
    f.chmod(0)
    if not os.access(f, os.R_OK):
        with pytest.raises(mod.Unreadable, match=r"^Permission denied$"):
            mod.read_text(f)


def test_frontmatter_details(tmp_path):
    mod = load_module()
    f = tmp_path / "a.md"
    f.write_text("")
    assert mod.frontmatter(f) is None  # an empty file has none
    f.write_text("---\nowner: heph\n---\n" + "x" * 20000)
    assert mod.frontmatter(f) == {"owner": "heph"}  # a long body does not hide it
    f.write_text('---\nowner: "Xander"\nexpires: 2026-01-01\n---\n')
    assert (
        mod.freshness(mod.frontmatter(f), mod.dt.date(2026, 11, 20), 90)
        == "expired 2026-01-01 (owner Xander)"
    )


def test_is_expired_cells():
    mod = load_module()
    d = mod.dt.date(2026, 11, 20)
    assert mod.is_expired({"owner": "h", "expires": "2026-11-19"}, d)
    assert not mod.is_expired({"owner": "h", "expires": "2026-11-20"}, d)
    assert not mod.is_expired({"expires": "2026-11-19"}, d)  # no owner: not one to delete
    assert not mod.is_expired({"owner": "h", "reviewed": "2020-01-01"}, d)
    assert not mod.is_expired({"owner": "h", "expires": "2026-11-19"}, None)


def test_transient_status_lists_what_expired(tmp_path):
    mod = load_module()
    files = {
        "review/a.md": fm(owner="h", expires="2026-01-01"),
        "review/b.md": fm(owner="h", reviewed="2020-01-01"),
    }
    root = make(tmp_path, files)
    cfg = mod.Config()
    cfg.transient = ["review/**"]
    got = mod.transient_status(root, cfg, mod.dt.date(2026, 11, 20))
    assert got.expired == {"review/a.md"} and set(got.stale) == {"review/a.md", "review/b.md"}


def test_freshness_messages():
    mod = load_module()
    d = mod.dt.date(2026, 11, 20)
    assert mod.freshness({}, d, 90) == "no owner"
    assert mod.freshness({"owner": "h"}, d, 90) == "no expires or reviewed date"
    assert mod.freshness({"owner": "h", "reviewed": "2026-01-01"}, d, 90) == (
        "last reviewed 2026-01-01, over 90 days ago (owner h)"
    )


def test_roadmap_budget_message_reads_whole(tmp_path):
    r = make(tmp_path, {"ROADMAP.md": lines(301)})
    assert one(r, tmp_path) == (
        "ROADMAP.md has 301 lines, over its 300-line budget → cut shipped scope and history; keep "
        "milestones, next-up order, design rules and backlog"
    )


def test_root_level_unowned_files_are_named_bare(tmp_path):
    r = make(tmp_path, {"a.png": "x"})
    assert one(r, tmp_path, "--only", "transient", "--transient", "**") == (
        "a.png has no owner + expires frontmatter → add it, or harvest the file into the repo "
        "that owns it and delete it"
    )


def test_help_shows_the_no_dates_line_and_the_description(tmp_path, capsys, monkeypatch):
    import re

    monkeypatch.setenv("COLUMNS", "500")  # one line each, so no hyphen is wrapped
    mod = load_module()
    with pytest.raises(SystemExit):
        mod.main(["check", "--help"])
    out = capsys.readouterr().out
    assert out.startswith("usage: cleanup.py check")
    assert re.search(
        r"(?<!\S)only what no calendar date decides: for a pull-request gate that must not turn "
        r"red on a date; expiry, review age and quarantine ends run on a schedule(?!\S)",
        " ".join(out.split()),
    )
    with pytest.raises(SystemExit):
        mod.main(["--help"])
    out = capsys.readouterr().out
    first, second = mod.__doc__.split("\n\n")[:2]
    assert re.search(
        r"(?<!\S)" + re.escape(" ".join(first.split())) + r"(?!\S)", " ".join(out.split())
    )
    assert second.split("\n")[1].strip() not in out  # the description is the first paragraph only


def test_only_limits_the_parts(tmp_path):
    r = make(tmp_path, {"IMPL.md": lines(51), "ROADMAP.md": lines(301)})
    assert len(check(r, tmp_path, "--only", "impl")) == 1


def test_glob_double_star_inside_a_name():
    mod = load_module()
    assert mod.glob_regex("a**z").match("a/b/z") and mod.glob_regex("a**bz").match("ax/bz")
    assert not mod.glob_regex("a**bz").match("axz")


# --- mutation round 3: cells each guard needs to go red -----------------------------------


def test_a_prose_line_in_the_cleanup_section_does_not_end_it(tmp_path):
    ctx = "## cleanup\nBudgets for this repo.\n- impl_lines: 10\n"
    r = make(tmp_path, {".claude/skill-context.md": ctx, "IMPL.md": lines(11)})
    assert one(r, tmp_path, "--only", "impl").startswith("IMPL.md has 11 lines")


def test_frontmatter_closed_past_its_read_window_is_no_frontmatter(tmp_path):
    body = "---\nowner: heph\nexpires: 2027-01-01\n" + "note: x\n" * 1200 + "---\n"
    r = make(tmp_path, {".claude/skill-context.md": CTX, "review/a.md": body})
    assert "no owner + expires frontmatter" in one(r, tmp_path, "--only", "transient")


def test_a_compact_date_is_not_a_date(tmp_path):
    r = make(
        tmp_path,
        {".claude/skill-context.md": CTX, "review/a.md": fm(owner="h", expires="20270101")},
    )
    assert "expires '20270101' is not a YYYY-MM-DD date" in one(r, tmp_path, "--only", "transient")


def test_normal_title_collapses_inner_whitespace():
    assert load_module().normal_title("Shipped  This \t Week") == "shipped this week"


def test_a_glob_with_no_slash_still_matches_at_the_root(tmp_path):
    r = make(tmp_path, {"notes.md": "x", "notes/a.md": "y"})
    assert load_module().matching_files(r, ["notes*"]) == ["notes.md", "notes/a.md"]


def test_rule_entries_after_a_preface_are_read(tmp_path):
    text = "# Lessons\n\nIntro.\n" + lesson("a", Rule="r")
    r = make(tmp_path, {".claude/skill-context.md": "## cleanup\n- rules: r.md\n", "r.md": text})
    assert "'a' has no Since" in one(r, tmp_path)


def test_an_entry_after_a_retired_one_is_still_checked(tmp_path):
    text = lesson("a", Retired="2026-01-01") + lesson("b", Rule="r")
    r = make(tmp_path, {".claude/skill-context.md": "## cleanup\n- rules: r.md\n", "r.md": text})
    assert "'b' has no Since" in one(r, tmp_path)


def test_an_unreadable_test_file_does_not_stop_the_flaky_scan(tmp_path):
    r = make(tmp_path, {"tests/test_b.py": f"@{MARK}\n"})
    (r / "tests" / "test_a.py").symlink_to(r / "gone.py")
    assert "test_b.py:1" in one(r, tmp_path, "--only", "flaky")


def test_a_tracked_test_file_deleted_from_the_tree_is_skipped(tmp_path):
    r = make(tmp_path, {"tests/test_a.py": "def test_a(): ...\n"}, git=True)
    (r / "tests" / "test_a.py").unlink()
    assert check(r, tmp_path, "--only", "flaky") == ["cleanup ✓"]


def test_no_dates_reads_past_a_dated_quarantine(tmp_path):
    text = f"# quarantine: until 2026-12-01 #1\n@{MARK}\n\n\n\n@{MARK}\n"
    r = make(tmp_path, {"tests/test_x.py": text})
    assert "test_x.py:6 retries" in one(r, tmp_path, "--only", "flaky", "--no-dates")


def test_a_quarantine_split_over_two_lines_does_not_count(tmp_path):
    text = f"# quarantine: until\n2026-12-01  # {MARK}\n"
    r = make(tmp_path, {"tests/test_x.py": text})
    assert "no quarantine end" in one(r, tmp_path, "--only", "flaky")


def test_an_origin_name_ending_in_x_is_matched_whole(tmp_path):
    src = make(tmp_path, {"ROADMAP.md": ROADMAP}, git=True)
    clone = tmp_path / "elsewhere" / "other"
    subprocess.run(["git", "clone", "-q", str(src), str(clone)], check=True)
    url = "https://github.com/me/repoX/"
    subprocess.run(["git", "-C", str(clone), "remote", "set-url", "origin", url], check=True)
    (tmp_path / "ws").mkdir()
    (tmp_path / "home" / ".claude").mkdir(parents=True)
    (tmp_path / "home" / ".claude" / "techne.toml").write_text(
        f'github_user = "me"\nworkspace_root = "{tmp_path / "ws"}"\n\n'
        '[[sisters]]\nname = "repoX"\nregistered_report = true\n'
    )
    assert "registered_report" in refused(clone, tmp_path / "home")


def test_a_sister_path_that_links_to_another_clone_is_matched(tmp_path):
    src = make(tmp_path, {"ROADMAP.md": ROADMAP}, git=True)
    clone = tmp_path / "elsewhere" / "other"
    subprocess.run(["git", "clone", "-q", str(src), str(clone)], check=True)
    url = "https://github.com/me/zzz"
    subprocess.run(["git", "-C", str(clone), "remote", "set-url", "origin", url], check=True)
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "repo").symlink_to(clone)
    roster(tmp_path / "home", ws, "registered_report = true\n")
    assert "registered_report" in refused(clone, tmp_path / "home")


def test_prune_checks_only_the_line_after_the_span(tmp_path):
    text = "# R\n## Completed\n- x\n## Next\n> a quote two lines past the span\n"
    make(tmp_path, {"ROADMAP.md": text}, git=True)
    out = run("prune", "repo", home=tmp_path, cwd=tmp_path)
    assert out.returncode == 0 and "would delete ROADMAP.md:2-3" in out.stdout


def test_prune_refuses_a_setext_done_log_at_the_top(tmp_path):
    root = make(tmp_path, {"ROADMAP.md": "Completed\n=========\n- x\n"}, git=True)
    assert "line 2 underlines the line above it" in refused(root, tmp_path)


@pytest.mark.parametrize(
    ("text", "expect"),
    [
        ("# R\n---\n## Completed\n- x\n", "# R\n"),  # a rule on the second line
        ("---\n***\n## Done\n- x\n", "---\n"),  # a leading --- that never closes
        (
            "---\ntitle: R\n...\n# R\n\n---\n\n## Done\n- x\n",
            "---\ntitle: R\n...\n# R\n",
        ),  # frontmatter closed by ..., then a dangling rule
        ("# R\nintro\n\n## Done\n- x\n## Next\n", "# R\nintro\n\n## Next\n"),  # the gap is a blank
    ],
)
def test_without_edge_cells_round_3(text, expect):
    mod = load_module()
    assert mod.without(text, mod.done_sections(text)) == expect


def test_prune_refuses_when_the_roadmap_vanishes_mid_run(tmp_path, monkeypatch, capsys):
    mod = load_module()
    root = make(tmp_path, {"ROADMAP.md": ROADMAP}, git=True)
    monkeypatch.setenv("HOME", str(tmp_path))

    def vanish(r, cfg):
        (r / "ROADMAP.md").unlink()

    monkeypatch.setattr(mod, "prune_refusal", vanish)
    assert mod.prune(root, True) == 1
    assert capsys.readouterr().out == "repo: refused: ROADMAP.md is gone\n"


# --- review round 2 -----------------------------------------------------------------------


def clone_as(tmp_path: Path, folder: str, url: str) -> Path:
    src = make(tmp_path, {"ROADMAP.md": ROADMAP}, git=True)
    clone = tmp_path / "elsewhere" / folder
    subprocess.run(["git", "clone", "-q", str(src), str(clone)], check=True)
    subprocess.run(["git", "-C", str(clone), "remote", "set-url", "origin", url], check=True)
    (tmp_path / "ws").mkdir(exist_ok=True)
    return clone


@pytest.mark.parametrize(
    ("folder", "url", "sister"),
    [
        ("Repo", "https://github.com/me/Repo.git", "repo"),  # GitHub names ignore case
        ("other", "https://gitlab.example/me/repo.GIT", "repo"),  # .GIT, no GitHub slug
        ("other", "git@github.com:ME/REPO.git", "repo"),  # by slug, any case
        ("repo", "https://example.org/x", "Repo"),  # the roster's case differs
        ("other", "https://gitlab.example/me/repo/", "repo"),  # a trailing slash, no slug
        ("other", "https://gitlab.example/me/repoX", "repoX"),  # a name ending in X
    ],
)
def test_a_registered_clone_is_found_in_any_case(tmp_path, folder, url, sister):
    clone = clone_as(tmp_path, folder, url)
    (tmp_path / "home" / ".claude").mkdir(parents=True)
    (tmp_path / "home" / ".claude" / "techne.toml").write_text(
        f'github_user = "me"\nworkspace_root = "{tmp_path / "ws"}"\n\n'
        f'[[sisters]]\nname = "{sister}"\nregistered_report = true\n'
    )
    assert "registered_report" in refused(clone, tmp_path / "home")


@pytest.mark.parametrize(
    ("text", "line"),
    [
        ("# R\n## Done\n- x\n```\ncode\n## Backlog\n- b\n", 4),
        ("# R\n## Done\n```\ncode\n## Backlog\n- b\n", 3),  # on the first line under it
    ],
)
def test_prune_refuses_a_fence_that_never_closes(tmp_path, text, line):
    root = make(tmp_path, {"ROADMAP.md": text}, git=True)
    assert f"line {line} opens a code fence that never closes" in refused(root, tmp_path)


def test_prune_still_cuts_a_done_log_with_a_closed_fence(tmp_path):
    text = "# R\n## Done\n```\nx\n```\n## Backlog\n- b\n"
    root = make(tmp_path, {"ROADMAP.md": text}, git=True)
    assert run("prune", "--apply", "repo", home=tmp_path, cwd=tmp_path).returncode == 0
    assert (root / "ROADMAP.md").read_text() == "# R\n## Backlog\n- b\n"


@pytest.mark.parametrize(
    ("text", "expect"),
    [
        (  # back to back: one cut, so the rule and the blank before it stay
            "Intro text.\n\n---\n\n## Done\n- x\n## Shipped\n- y\n\nBacklog\n-------\n- b\n",
            "Intro text.\n\n---\n\nBacklog\n-------\n- b\n",
        ),
        ("Next up\n---\n## Done\n- x\n", "Next up\n---\n"),  # an underline is no dangling rule
        (  # a setext title must not join the list above it
            "- a\n## Completed\n- x\n\nLater\n-----\n",
            "- a\n\nLater\n-----\n",
        ),
        ("- a\r\n## Completed\r\n- x\r\n\r\nLater\r\n-----\r\n", "- a\r\n\r\nLater\r\n-----\r\n"),
        ("- a\n## Completed\n- x\n## Next\n", "- a\n## Next\n"),  # an ATX heading needs no gap
    ],
)
def test_without_keeps_what_a_reader_sees(text, expect):
    mod = load_module()
    assert mod.without(text, mod.done_sections(text)) == expect


def test_a_rules_glob_reaches_into_a_skipped_folder(tmp_path):
    r = make(
        tmp_path,
        {
            ".claude/skill-context.md": "## cleanup\n- rules: site/*/a.md\n",
            "site/x/a.md": lesson("a", Rule="r"),
        },
    )
    assert "'a' has no Since" in one(r, tmp_path)
