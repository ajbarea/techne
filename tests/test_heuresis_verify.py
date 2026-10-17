"""Quote verification: normalization, local evidence, network failures."""

from __future__ import annotations

from pathlib import Path

from heuresis import sources, verify
from heuresis.model import Record
from heuresis.sources import http

PAGE = """<html><head><script>var x = "decoy quote that is long enough";</script></head>
<body><p>We present &ldquo;IdeaScout&rdquo;&mdash;a tool that
triages   ideas against prior&nbsp;art.</p></body></html>"""


def web(url="https://p.example/x"):
    return Record(title="t", url=url, source="web", kind="web")


def test_normalize_folds_quotes_dashes_space_and_case():
    text = "“IdeaScout” — Triages\n  IDEAS"
    assert verify.normalize(text) == '"ideascout" - triages ideas'


def test_quote_across_entities_and_line_breaks_matches(monkeypatch):
    monkeypatch.setattr(verify.http, "get", lambda url, headers=None: PAGE.encode())
    quote = "“IdeaScout”—a tool that triages ideas against prior art"
    ok, why = verify.check(web(), quote, Path("."), Path("."))
    assert ok, why


def test_script_text_does_not_count(monkeypatch):
    monkeypatch.setattr(verify.http, "get", lambda url, headers=None: PAGE.encode())
    ok, why = verify.check(web(), "decoy quote that is long enough", Path("."), Path("."))
    assert (ok, why) == (False, "quote not found")


def test_short_quote_is_rejected_before_fetching(monkeypatch):
    monkeypatch.setattr(
        verify.http, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("fetched"))
    )
    assert verify.check(web(), "prior art", Path("."), Path(".")) == (False, "quote too short")


def test_network_failure_is_a_reason_not_a_crash(monkeypatch):
    def boom(url, headers=None):
        raise http.SourceError("http 404 from p.example")

    monkeypatch.setattr(verify.http, "get", boom)
    assert verify.check(web(), "a tool that triages ideas against", Path("."), Path(".")) == (
        False,
        "http 404 from p.example",
    )


def test_js_only_page_drops_the_record(monkeypatch):
    monkeypatch.setattr(
        verify.http,
        "get",
        lambda url, headers=None: b"<html><body><div id=root></div></body></html>",
    )
    assert verify.check(web(), "a tool that triages ideas against", Path("."), Path(".")) == (
        False,
        "quote not found",
    )


def test_idea_and_context_records_read_local_files(tmp_path: Path):
    ideas, repos = tmp_path / "ideas-repo", tmp_path / "repos"
    (ideas / "ideas").mkdir(parents=True)
    (ideas / "ideas" / "2026-10-01-x.md").write_text(
        "---\nid: x\n---\nAn earlier idea about triaging ideas."
    )
    (repos / "papers").mkdir(parents=True)
    (repos / "papers" / "references.bib").write_text(
        "@article{k, title={Federated agents and source attribution}}"
    )
    idea = Record(title="x", url="idea:2026-10-01-x", source="ideas", kind="idea")
    ctx = Record(title="bib", url="repo:papers/references.bib", source="context", kind="context")
    assert verify.check(idea, "An earlier idea about triaging ideas", ideas, repos) == (True, "")
    assert verify.check(ctx, "Federated agents and source attribution", ideas, repos) == (True, "")


def test_missing_local_file_is_a_reason_not_a_crash(tmp_path: Path):
    idea = Record(title="x", url="idea:2026-10-01-gone", source="ideas", kind="idea")
    ok, why = verify.check(idea, "An earlier idea about triaging ideas", tmp_path, tmp_path)
    assert not ok
    assert why.startswith("unreadable")


def test_json_evidence_joins_string_leaves(monkeypatch):
    monkeypatch.setattr(
        verify.http,
        "get",
        lambda url, headers=None: (
            b'{"full_name": "a/b", "description": "Triage your ideas against prior art quickly"}'
        ),
    )
    rec = Record(
        title="a/b",
        url="https://github.com/a/b",
        source="github",
        kind="repo",
        evidence_url="https://api.github.com/repos/a/b",
    )
    assert verify.check(rec, "Triage your ideas against prior art", Path("."), Path(".")) == (
        True,
        "",
    )


def test_json_string_leaves_are_de_tagged(monkeypatch):
    body = b'{"text": "<p>Triage your ideas&#x2F;notes against prior art</p><p>second para</p>"}'
    monkeypatch.setattr(verify.http, "get", lambda url, headers=None: body)
    rec = Record(
        title="hn",
        url="https://news.ycombinator.com/item?id=1",
        source="hacker_news",
        kind="product",
        evidence_url="https://hn.algolia.com/api/v1/items/1",
    )
    quote = "Triage your ideas/notes against prior art"
    assert verify.check(rec, quote, Path("."), Path(".")) == (True, "")


def test_a_sources_own_evidence_error_is_contained(monkeypatch):
    class Broken:
        name, group = "broken", "papers"

        def evidence(self, record):
            raise RuntimeError("api changed")

    monkeypatch.setattr(sources, "by_name", lambda name: Broken())
    rec = Record(title="t", url="https://p.example/x", source="broken", kind="paper")
    ok, why = verify.check(rec, "a tool that triages ideas against", Path("."), Path("."))
    assert (ok, why) == (False, "RuntimeError: api changed")


def _page(monkeypatch, body: bytes):
    monkeypatch.setattr(verify.http, "get", lambda url, headers=None: body)


def test_inline_tags_do_not_split_words_or_punctuation(monkeypatch):
    _page(monkeypatch, b"<p>We present <a>IdeaScout</a>, a tool that Fed<em>er</em>ated</p>")
    assert verify.check(
        web(), "We present IdeaScout, a tool that Federated", Path("."), Path(".")
    ) == (True, "")


def test_block_tags_separate_words(monkeypatch):
    _page(monkeypatch, b"<p>first paragraph ends</p><p>second one starts here</p>")
    assert verify.check(web(), "first paragraph ends second one starts", Path("."), Path(".")) == (
        True,
        "",
    )


def test_atom_and_epo_xml_keep_words_whole(monkeypatch):
    atom = (
        b'<?xml version="1.0"?><feed><entry><title>A tool</title>'
        b"<summary>Triages <i>ideas</i>, fast and cheap</summary></entry></feed>"
    )
    _page(monkeypatch, atom)
    assert verify.check(web(), "A tool Triages ideas, fast and cheap", Path("."), Path(".")) == (
        True,
        "",
    )
    epo = (
        b'<?xml version="1.0"?><abstract><p>An apparatus for triage.</p>'
        b"<p>It ranks ideas.</p></abstract>"
    )
    _page(monkeypatch, epo)
    assert verify.check(
        web(), "An apparatus for triage. It ranks ideas.", Path("."), Path(".")
    ) == (True, "")


def test_paths_outside_the_roots_are_refused(tmp_path: Path):
    ideas, repos = tmp_path / "i", tmp_path / "r"
    (ideas / "ideas").mkdir(parents=True)
    repos.mkdir()
    (tmp_path / "secret.md").write_text("a line that is long enough to quote")
    quote = "a line that is long enough to quote"
    for url, why in [
        ("repo:../secret.md", "path outside repos root"),
        (f"repo:{tmp_path}/secret.md", "path outside repos root"),
        ("idea:../../secret", "invalid idea id"),
    ]:
        rec = Record(title="x", url=url, source="context", kind="context")
        assert verify.check(rec, quote, ideas, repos) == (False, why)


def test_file_scheme_is_refused(tmp_path: Path):
    target = tmp_path / "s.txt"
    target.write_text("a line that is long enough to quote")
    rec = Record(title="x", url=f"file://{target}", source="web", kind="web")
    assert verify.check(rec, "a line that is long enough to quote", tmp_path, tmp_path) == (
        False,
        "unsupported scheme: file",
    )


def test_none_quote_does_not_raise():
    assert verify.check(web(), None, Path("."), Path(".")) == (False, "quote too short")  # ty: ignore[invalid-argument-type]


def test_normalize_drops_soft_hyphens_and_zero_width_and_folds_hyphens():
    text = "tri\N{SOFT HYPHEN}ages a\N{ZERO WIDTH SPACE}b \N{HYPHEN} c\N{NON-BREAKING HYPHEN}d"
    assert verify.normalize(text) == "triages ab - c-d"


def test_leading_bom_does_not_hide_json(monkeypatch):
    _page(monkeypatch, b'\xef\xbb\xbf{"description": "Triage your ideas against prior art"}')
    assert verify.check(web(), "Triage your ideas against prior art", Path("."), Path(".")) == (
        True,
        "",
    )


def test_unlisted_tags_still_separate_words(monkeypatch):
    for body, quote in [
        (b"<head><title>Title</title></head><body>Body text here", "Title Body text here"),
        (
            b"<nav>Nav items listed</nav><main>Main content here</main>",
            "Nav items listed Main content",
        ),
        (b"<p>first word<img src=x>second word follows</p>", "first word second word follows"),
    ]:
        _page(monkeypatch, body)
        assert verify.check(web(), quote, Path("."), Path(".")) == (True, ""), body


def test_record_problem_rejects_a_repo_path_to_an_idea_file():
    for url in ("repo:ideas-repo/ideas/2026-10-15-x.md", "repo:a/b/ideas/2026-10-15-x.md"):
        rec = Record(title="x", url=url, source="context", kind="context")
        assert verify.record_problem(rec) == "cite an idea as idea:2026-10-15-x"
    fine = Record(title="x", url="repo:papers/ideas/notes.md", source="context", kind="context")
    assert verify.record_problem(fine) is None


def test_a_repo_path_inside_the_ideas_repository_is_refused(tmp_path: Path):
    repos = tmp_path / "repos"
    ideas = repos / "ideas-repo"
    (ideas / "runs" / "2026-10-15-x").mkdir(parents=True)
    quote = "a line that is long enough to quote"
    (ideas / "runs" / "2026-10-15-x" / "scout-context.json").write_text(quote)
    (ideas / "BOARD.md").write_text(quote)
    (repos / "link").symlink_to(ideas)
    for url in (
        "repo:ideas-repo/runs/2026-10-15-x/scout-context.json",
        "repo:ideas-repo/BOARD.md",
        "repo:link/BOARD.md",
    ):
        rec = Record(title="x", url=url, source="context", kind="context")
        assert verify.check(rec, quote, ideas, repos) == (
            False,
            "path inside the ideas repository; cite an idea as idea:<id>",
        )
