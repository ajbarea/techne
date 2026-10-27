"""Unit tests for docsync's scripts/repo_meta.py, which gathers a repo's GitHub About section
and its README opening for the metadata check.

The opening has to survive the HTML a README hero uses (centered images, badges, an HTML
title), or the check compares the description against nothing.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from conftest import HOOK_PYTHON, REPO_META_SCRIPT

SLUG = "ajbarea/myrepo"
REPO = ["gh", "api", "--hostname", "github.com", f"repos/{SLUG}"]
PAGES = ["gh", "api", "--hostname", "github.com", f"repos/{SLUG}/pages", "--jq", ".html_url"]

HERO = """\
<p align="center">
  <img src="assets/hero.png" alt="the bar over the taskbar" width="520">
</p>

<h1 align="center">myrepo</h1>

<p align="center">Your usage limit always on screen.</p>

<p align="center">
  <a href="x"><img src="https://img.shields.io/badge/ci" alt="CI"></a>
</p>

<!-- budget: 160 words
     spans lines -->
myrepo is a thin bar that shows your
[usage](#usage) &amp; limits.

## Install

Not part of the opening.
"""


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "myrepo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "remote", "add", "origin", f"git@github.com:{SLUG}.git")
    return root


@pytest.fixture
def gh(fp, tmp_path, monkeypatch):
    """gh calls are stubbed per test; one no test stubbed fails the test."""
    fp.allow_unregistered(True)
    bin_dir, log = tmp_path / "fake-bin", tmp_path / "unstubbed-gh.log"
    bin_dir.mkdir()
    fake = bin_dir / "gh"
    fake.write_text(f'#!/bin/sh\necho "$*" >> "{log}"\nexit 97\n', encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{__import__('os').environ['PATH']}")
    yield fp
    assert not log.exists(), f"unstubbed gh call: {log.read_text(encoding='utf-8')}"


def about(gh, pages: str | None = None, **fields) -> None:
    body = {"description": "A bar.", "homepage": "", "topics": ["rust"], **fields}
    gh.register(REPO, stdout=json.dumps(body))
    if pages is None:
        gh.register(PAGES, returncode=1, stderr="gh: Not Found (HTTP 404)")
    else:
        gh.register(PAGES, stdout=pages + "\n")


def report(meta, capsys, path: Path) -> dict:
    code = meta.main([str(path)])
    out, err = capsys.readouterr()
    assert code == 0, err
    return json.loads(out)


def failure(meta, capsys, path: Path) -> str:
    code = meta.main([str(path)])
    assert code == 2
    return capsys.readouterr().err


# ------------------------------------------------------------------ opening ----


def test_opening_skips_hero_html_badges_and_comments(meta):
    found = meta.opening(HERO)
    assert found == [
        {"line": 7, "text": "Your usage limit always on screen."},
        {"line": 15, "text": "myrepo is a thin bar that shows your usage & limits."},
    ]


def test_opening_skips_a_markdown_title_and_badge_line(meta):
    text = (
        "# myrepo\n\n[![CI](https://x/ci.svg)](https://x) [![PyPI](https://x/p.svg)](https://p)\n\n"
        "A tool that does one thing.\n\n```bash\nmake setup\n```\n\nSecond paragraph.\n"
    )
    assert [p["text"] for p in meta.opening(text)] == [
        "A tool that does one thing.",
        "Second paragraph.",
    ]


def test_opening_stops_at_the_first_section_heading_in_either_form(meta):
    assert meta.opening("Lead.\n\n<h2>Install</h2>\n\nAfter.\n") == [{"line": 1, "text": "Lead."}]
    assert meta.opening("Lead.\n\n### Deep\n\nAfter.\n") == [{"line": 1, "text": "Lead."}]


def test_opening_drops_blockquote_markers(meta):
    assert meta.opening("> Ariadne gave Theseus\n> the thread.\n") == [
        {"line": 1, "text": "Ariadne gave Theseus the thread."}
    ]
    tag = '<img src="a.png"\n  width="520"\n>\nText after.\n'
    assert meta.opening(tag) == [{"line": 1, "text": "Text after."}]


def test_opening_keeps_at_most_three_paragraphs(meta):
    text = "\n\n".join(f"Paragraph {n}." for n in range(5))
    assert len(meta.opening(text)) == 3


def test_a_heading_inside_a_code_fence_does_not_end_the_opening(meta):
    text = "Lead.\n\n```md\n## not a heading\n```\n\nStill opening.\n\n## Real\n"
    assert [p["text"] for p in meta.opening(text)] == ["Lead.", "Still opening."]


def test_readme_follows_githubs_precedence(meta, tmp_path):
    for where in ("docs", "", ".github"):
        (tmp_path / where).mkdir(exist_ok=True)
        (tmp_path / where / "README.md").write_text("x", encoding="utf-8")
    assert meta.readme(tmp_path) == tmp_path / ".github" / "README.md"
    (tmp_path / ".github" / "README.md").unlink()
    assert meta.readme(tmp_path) == tmp_path / "README.md"


def test_readme_matches_any_case_and_extension(meta, tmp_path):
    (tmp_path / "Readme.rst").write_text("x", encoding="utf-8")
    assert meta.readme(tmp_path) == tmp_path / "Readme.rst"


# ------------------------------------------------------------------- report ----


def test_report_carries_the_about_section_and_the_opening(meta, repo, gh, capsys):
    (repo / "README.md").write_text(HERO, encoding="utf-8")
    about(gh, description="A bar.", homepage="https://example.org", topics=["rust", "tauri"])
    out = report(meta, capsys, repo / "README.md")
    assert out["repo"] == SLUG
    assert out["description"] == "A bar."
    assert out["homepage"] == "https://example.org"
    assert out["topics"] == ["rust", "tauri"]
    assert out["pages_url"] is None
    assert out["readme"] == "README.md"
    assert out["opening"][0]["text"] == "Your usage limit always on screen."
    assert out["problems"] == []


def test_empty_fields_are_problems(meta, repo, gh, capsys):
    (repo / "README.md").write_text("## Only sections\n", encoding="utf-8")
    about(gh, description=None, topics=[])
    out = report(meta, capsys, repo)
    assert out["problems"] == [
        "description: empty",
        "topics: none set",
        "readme: README.md has no opening paragraph before its first section heading",
    ]


def test_an_unset_homepage_names_the_pages_site(meta, repo, gh, capsys):
    (repo / "README.md").write_text("Lead.\n", encoding="utf-8")
    about(gh, pages="https://ajbarea.github.io/myrepo/", homepage=None)
    out = report(meta, capsys, repo)
    assert out["pages_url"] == "https://ajbarea.github.io/myrepo/"
    assert out["problems"] == [
        "homepage: empty while GitHub Pages serves https://ajbarea.github.io/myrepo/"
    ]


def test_a_homepage_off_the_pages_site_on_github_io_is_a_problem(meta, repo, gh, capsys):
    (repo / "README.md").write_text("Lead.\n", encoding="utf-8")
    about(gh, pages="https://ajbarea.github.io/myrepo/", homepage="https://ajbarea.github.io/old/")
    out = report(meta, capsys, repo)
    assert out["problems"] == [
        "homepage: https://ajbarea.github.io/old/ is not under the GitHub Pages site "
        "https://ajbarea.github.io/myrepo/"
    ]


def test_a_homepage_elsewhere_or_under_the_pages_site_is_fine(meta, repo, gh, capsys):
    (repo / "README.md").write_text("Lead.\n", encoding="utf-8")
    about(
        gh,
        pages="https://ajbarea.github.io/myrepo/",
        homepage="https://ajbarea.github.io/myrepo/docs/",
    )
    out = report(meta, capsys, repo)
    assert out["problems"] == []


def test_no_readme_is_a_problem(meta, repo, gh, capsys):
    about(gh)
    out = report(meta, capsys, repo)
    assert out["readme"] is None
    assert out["problems"] == ["readme: none in .github/, the repo root or docs/"]


def test_no_github_origin_stops_with_a_reason(meta, tmp_path, capsys):
    root = tmp_path / "plain"
    root.mkdir()
    git(root, "init", "-q")
    err = failure(meta, capsys, root)
    assert "no GitHub origin (no origin remote)" in err


def test_a_folder_outside_git_stops_with_its_own_reason(meta, tmp_path, capsys):
    assert "is not in a git repository" in failure(meta, capsys, tmp_path)


def test_a_failed_github_read_stops_with_a_reason(meta, repo, gh, capsys):
    gh.register(REPO, returncode=1, stderr="gh: Not Found (HTTP 404)")
    err = failure(meta, capsys, repo)
    assert f"could not read {SLUG} on GitHub: gh: Not Found (HTTP 404)" in err


# ------------------------------------------------------ README shapes ----


def texts(meta, text: str) -> list[str]:
    return [p["text"] for p in meta.opening(text)]


def test_a_tagline_heading_in_a_centred_header_is_kept(meta):
    text = (
        '<div align="center">\n\n# keryx\n\n### Gives Claude Code a voice.\n\n</div>\n\n'
        "keryx speaks a short gist of each reply.\n\n## Install\n"
    )
    assert texts(meta, text) == [
        "Gives Claude Code a voice.",
        "keryx speaks a short gist of each reply.",
    ]


def test_an_h2_inside_the_header_container_is_a_tagline(meta):
    text = '<p align="center">\n\n## A centred h2 tagline\n\n</p>\n\nLead.\n\n## Install\n'
    assert texts(meta, text) == ["A centred h2 tagline", "Lead."]


def test_a_subtitle_right_under_the_title_is_kept_but_an_h2_ends_the_opening(meta):
    assert texts(meta, "# T\n### A tool.\nLead.\n") == ["A tool.", "Lead."]
    assert texts(meta, "# T\n\n## Install\n\nRun it.\n") == []


def test_fences_close_only_on_their_own_character_and_length(meta):
    four = "````md\n```\n## not a heading\n````\n\nLead.\n"
    tilde = "~~~\n```\n## not a heading\n~~~\n\nLead.\n"
    assert texts(meta, four) == ["Lead."]
    assert texts(meta, tilde) == ["Lead."]


def test_front_matter_and_setext_headings(meta):
    assert texts(meta, "---\ntitle: x\n---\n\nLead.\n") == ["Lead."]
    assert texts(meta, "My Tool\n=======\n\nLead.\n\nUsage\n-----\n\nAfter.\n") == ["Lead."]


def test_reference_badges_and_definitions_are_not_prose(meta):
    text = "[![CI][ci]][run] [![PyPI][pypi]][pkg]\n\n[ci]: https://x/ci.svg\n\nLead.\n"
    assert texts(meta, text) == ["Lead."]


def test_angle_brackets_in_text_survive_and_autolinks_keep_their_address(meta):
    assert texts(meta, "When a < b and c > d, it stops.\n") == ["When a < b and c > d, it stops."]
    assert texts(meta, "Docs at <https://x.org/docs> for everyone.\n") == [
        "Docs at https://x.org/docs for everyone."
    ]


def test_tables_code_details_labels_and_link_rows_are_not_the_opening(meta):
    text = (
        "| a | b |\n| - | - |\n\n    indented code\n\n<details>\n<summary>More</summary>\n\n"
        "Hidden text.\n\n</details>\n\n**Docs:**\n\n[Docs](d) · [Explorer](e) · [Paper](p)\n\n"
        "🚀 ✨\n\n> [!NOTE]\n> The real lead.\n"
    )
    assert texts(meta, text) == ["The real lead."]


def test_bold_and_emphasis_markers_are_dropped(meta):
    assert texts(meta, "**Sensemaking** for _nonatomic_ entities.\n") == [
        "Sensemaking for _nonatomic_ entities."
    ]


def test_a_utf16_or_bom_readme_reads_as_text(meta, repo, gh, capsys):
    (repo / "README.md").write_bytes("# T\n\nLead.\n".encode("utf-16"))
    about(gh)
    assert report(meta, capsys, repo)["opening"] == [{"line": 3, "text": "Lead."}]
    (repo / "README.md").write_bytes("\ufeff# T\n\nLead.\n".encode())
    about(gh)
    assert report(meta, capsys, repo)["opening"] == [{"line": 3, "text": "Lead."}]


def test_a_readme_link_that_leaves_the_repo_is_not_read(meta, repo, tmp_path):
    (tmp_path / "outside.txt").write_text("secret", encoding="utf-8")
    (repo / "README.md").symlink_to(tmp_path / "outside.txt")
    assert meta.readme(repo) is None


def test_a_sibling_path_is_not_under_the_pages_site(meta):
    site = "https://ajbarea.github.io/myrepo/"
    assert meta.under("https://ajbarea.github.io/myrepo", site)
    assert meta.under("https://ajbarea.github.io/myrepo/docs/", site)
    assert not meta.under("https://ajbarea.github.io/myrepo-old/", site)
    assert not meta.under("https://ajbarea.github.io/myrepo2", site)


def test_the_script_runs_on_the_oldest_supported_python(tmp_path):
    """`make test-hooks-oldest` points HOOK_PYTHON at python3 3.9."""
    out = subprocess.run(
        [HOOK_PYTHON, str(REPO_META_SCRIPT), str(tmp_path)], capture_output=True, text=True
    )
    assert out.returncode == 2 and "is not in a git repository" in out.stderr, out.stderr
    probe = (
        f"import sys; sys.path.insert(0, {str(REPO_META_SCRIPT.parent)!r}); import repo_meta; "
        "print(repo_meta.opening('# T\\n\\n### Tagline.\\n\\nLead.\\n'))"
    )
    run = subprocess.run([HOOK_PYTHON, "-c", probe], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    assert "'Tagline.'" in run.stdout and "'Lead.'" in run.stdout
