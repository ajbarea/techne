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
    assert "no GitHub origin" in err


def test_a_failed_github_read_stops_with_a_reason(meta, repo, gh, capsys):
    gh.register(REPO, returncode=1, stderr="gh: Not Found (HTTP 404)")
    err = failure(meta, capsys, repo)
    assert f"could not read {SLUG} on GitHub" in err
