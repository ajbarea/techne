"""Projects seeded from techne.toml, the marketplace and paper dirs; context sources resolved."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from heuresis import context


def repos(tmp_path: Path) -> Path:
    root = tmp_path / "repos"
    for name in ("techne", "papers", "talks", "ariadne"):
        (root / name).mkdir(parents=True)
    (root / "techne" / ".claude-plugin").mkdir()
    (root / "techne" / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps({"plugins": [{"name": "techne"}, {"name": "graphe"}]})
    )
    (root / "papers" / "org-house-style").mkdir()
    (root / "papers" / "org-house-style" / "main.tex").write_text("")
    (root / "papers" / "references.bib").write_text("@article{x,}")
    (root / "talks" / "federated-agents").mkdir()
    (root / "talks" / "federated-agents" / "index.html").write_text("<html>")
    (root / "ariadne" / "ROADMAP.md").write_text("# r")
    return root


TOML = (
    '[[sisters]]\nname = "ariadne"\nstatus = "active"\n'
    '[[sisters]]\nname = "techne"\nstatus = "active"\n'
    '[[sisters]]\nname = "kourai"\nstatus = "backburner"\n'
)


def test_seed_projects_names_each_kind_without_collisions(tmp_path: Path):
    root = repos(tmp_path)
    toml = tmp_path / "techne.toml"
    toml.write_text(TOML)
    names = {p.name: p for p in context.seed_projects(toml, root)}
    assert names["ariadne"].kind == "repo"
    assert names["kourai"].status == "backburner"
    assert names["plugin:graphe"].repo == "techne"
    assert "plugin:techne" in names and names["techne"].kind == "repo"
    assert names["paper:org-house-style"].repo == "papers"


def test_seed_projects_without_techne_toml_still_finds_plugins_and_papers(tmp_path: Path):
    names = {p.name for p in context.seed_projects(None, repos(tmp_path))}
    assert {"plugin:graphe", "paper:org-house-style"} <= names


def test_projects_round_trip(tmp_path: Path):
    projects = context.seed_projects(None, repos(tmp_path))
    path = tmp_path / "projects.toml"
    context.write_projects(path, projects)
    assert context.load_projects(path) == projects


def test_resolve_sources_expands_globs_and_star_repos(tmp_path: Path):
    root = repos(tmp_path)
    ctx = tmp_path / "context.toml"
    context.write_context(ctx)
    projects = [context.Project("ariadne", "repo", "ariadne")]
    sources = context.resolve_sources(ctx, projects, root)
    found = {(s["kind"], Path(s["path"]).relative_to(root).as_posix()) for s in sources}
    assert ("bib", "papers/references.bib") in found
    assert ("deck", "talks/federated-agents/index.html") in found
    assert ("roadmap", "ariadne/ROADMAP.md") in found
    assert all(Path(s["path"]).is_absolute() for s in sources)


def test_init_repo_creates_the_layout_and_a_git_repo(tmp_path: Path):
    root = repos(tmp_path)
    ideas = tmp_path / "ideas-repo"
    context.init_repo(ideas, None, root)
    expected = ("ideas", "runs", "projects.toml", "context.toml", "README.md", "BOARD.md", "LOG.md")
    for name in expected:
        assert (ideas / name).exists(), name
    assert (ideas / ".git").is_dir()
    snapshot = {n: (ideas / n).read_text() for n in ("projects.toml", "context.toml", "README.md")}
    context.init_repo(ideas, None, root)  # a second run changes nothing and does not fail
    assert {n: (ideas / n).read_text() for n in snapshot} == snapshot


def test_init_repo_inside_another_repo_gets_its_own_repo(tmp_path: Path):
    outer = tmp_path / "outer"
    outer.mkdir()
    subprocess.run(["git", "init", "-q", str(outer)], check=True)
    ideas = outer / "ideas-repo"
    context.init_repo(ideas, None, repos(tmp_path))
    assert (ideas / ".git").is_dir()


def test_non_ascii_project_name_round_trips(tmp_path: Path):
    path = tmp_path / "projects.toml"
    projects = [context.Project("idea:\U0001f680", "new", None)]
    context.write_projects(path, projects)
    assert context.load_projects(path) == projects


@pytest.mark.parametrize("bad", ["/etc/passwd", "../secret.md", "a/../../b"])
def test_resolve_sources_rejects_absolute_and_parent_paths(tmp_path: Path, bad: str):
    ctx = tmp_path / "context.toml"
    ctx.write_text(f'[[source]]\nkind = "notes"\nrepo = "papers"\npath = "{bad}"\n')
    with pytest.raises(ValueError, match="notes"):
        context.resolve_sources(ctx, [], tmp_path)
