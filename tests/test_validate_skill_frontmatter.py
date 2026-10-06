"""validate_skill_frontmatter.py: required keys, and descriptions claude.ai can store intact."""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "validate_skill_frontmatter.py"
_spec = importlib.util.spec_from_file_location("validate_skill_frontmatter", SCRIPT)
assert _spec and _spec.loader
validator = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(validator)


def _skill(tmp_path: pathlib.Path, frontmatter: str, body: str = "body\n") -> pathlib.Path:
    path = tmp_path / "SKILL.md"
    path.write_text(f"---\n{frontmatter}\n---\n{body}", encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "description",
    [
        'description: Use when asked to "catch me up on <repo>".',
        "description: >-\n  Folded text with a <tag> inside.",
        "description: |\n  First line.\n  Second line names logs/dev-<ts>.log.",
    ],
)
def test_angle_brackets_in_the_description_fail(tmp_path, description):
    reason = validator.check_skill(_skill(tmp_path, f"name: x\n{description}"))
    assert reason is not None and "< or >" in reason


@pytest.mark.parametrize(
    "description",
    [
        "description: Plain text, arrows like setup → lint are fine.",
        "description: >-\n  A folded scalar whose indicator is YAML syntax.",
    ],
)
def test_a_clean_description_passes(tmp_path, description):
    assert validator.check_skill(_skill(tmp_path, f"name: x\n{description}")) is None


def test_angle_brackets_in_the_body_or_another_key_pass(tmp_path):
    frontmatter = "name: x\ndescription: Clean.\nargument-hint: <path>"
    path = _skill(tmp_path, frontmatter, "Run it on <path>.\n")
    assert validator.check_skill(path) is None


def test_missing_description_is_reported(tmp_path):
    assert "missing description:" in validator.check_skill(_skill(tmp_path, "name: x"))


def test_every_shipped_skill_passes():
    paths = sorted(validator.REPO_ROOT.glob(validator.SKILLS_GLOB))
    assert paths
    assert [r for r in map(validator.check_skill, paths) if r] == []
