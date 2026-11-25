"""Tests for the periegesis guided product tour skill."""

from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
SKILL_MD = REPO_ROOT / "plugins" / "techne" / "skills" / "periegesis" / "SKILL.md"
DOCS_MD = REPO_ROOT / "docs" / "skills" / "periegesis.md"
TEMPLATE_MD = (
    REPO_ROOT / "plugins" / "techne" / "skills" / "periegesis" / "templates" / "friction-log.md"
)


def test_periegesis_log_path_sits_outside_docs_folders() -> None:
    """Friction logs and screenshots must never be directed to docs/ which deploys publicly."""
    skill_text = SKILL_MD.read_text(encoding="utf-8")
    docs_text = DOCS_MD.read_text(encoding="utf-8")
    template_text = TEMPLATE_MD.read_text(encoding="utf-8")

    assert "docs/friction" not in skill_text
    assert "docs/friction" not in docs_text
    assert "docs/friction" not in template_text

    assert ".periegesis/" in skill_text
    assert ".periegesis/" in docs_text
    assert "~/.local/state/periegesis/" in skill_text


def test_periegesis_description_excludes_tooling_friction_log() -> None:
    """Skill description and docs must distinguish app UX tour from tooling friction.md."""
    skill_text = SKILL_MD.read_text(encoding="utf-8")
    docs_text = DOCS_MD.read_text(encoding="utf-8")

    assert "Not for the agents' tooling friction log" in skill_text
    assert "friction.md" in skill_text
    assert "Not for the agents' tooling friction log" in docs_text


def test_periegesis_checks_repo_kind_before_filing_issues() -> None:
    """periegesis must run repo_kind.py before filing issues and ask on team repos."""
    skill_text = SKILL_MD.read_text(encoding="utf-8")

    assert "repo_kind.py" in skill_text
    assert "solo repo" in skill_text
    assert "team repo" in skill_text
    assert "unassigned" in skill_text


def test_periegesis_reuses_visual_qa_tool() -> None:
    """periegesis must reuse techne's visual_qa.py for machine checks."""
    skill_text = SKILL_MD.read_text(encoding="utf-8")

    assert "visual_qa.py" in skill_text
    assert "axe-core" in skill_text
    assert "390x844" in skill_text


def test_periegesis_requires_playwright_mcp_without_unrunnable_fallback() -> None:
    """periegesis must rely on Playwright MCP rather than an unrunnable one-shot python process."""
    skill_text = SKILL_MD.read_text(encoding="utf-8")

    assert "Playwright MCP" in skill_text
    assert "uv run --no-project --with playwright==1.63.0 python" not in skill_text
