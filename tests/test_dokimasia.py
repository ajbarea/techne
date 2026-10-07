"""Controls for the bibliography checker.

Every check is tripped on purpose against a bibliography built to break it, and each has a
negative case asserting the clean version still passes.

Two controls cover mistakes already on the record. A naive title regex stops at the first `}`
and truncates `{LLM}s`, which read as a title mismatch during the 2026-08-25 audit. And 50 of
77 entries once carried an arXiv id inside `journal = {arXiv preprint arXiv:2312.17493}`,
where no tool could reach it.
"""

from __future__ import annotations

import email.message
import json
import urllib.error

import pytest

CLEAN = """\
@article{good2024entry,
  title         = {A Perfectly Ordinary Title},
  author        = {Doe, Jane},
  year          = {2024},
  archivePrefix = {arXiv},
  eprint        = {2401.00001}
}
"""

STAGED_INTAKE = """\
# intake

## In `references.bib` but not yet positioned

- `good2024entry` -- recorded, nobody has read it
"""

INTAKE_CONFIG = '[intake]\nfile = "related-work/intake.md"\n'


@pytest.fixture
def project(dk, tmp_path):
    """A scratch project. `write` fills it and hands back the lint's finding count."""

    def write(bib_text=CLEAN, *, tex=None, intake_text=None, config=None):
        (tmp_path / "references.bib").write_text(bib_text)
        if tex is not None:
            (tmp_path / "paper.tex").write_text(tex)
        if intake_text is not None:
            (tmp_path / "related-work").mkdir(exist_ok=True)
            (tmp_path / "related-work" / "intake.md").write_text(intake_text)
            config = (config or "") + INTAKE_CONFIG
        if config is not None:
            (tmp_path / "dokimasia.toml").write_text(config)
        return dk.lint(dk.load_config(tmp_path))

    return write


# --- lint: the original checks ---------------------------------------------------------


def test_clean_bibliography_has_no_findings(project):
    assert project(tex=r"\cite{good2024entry}") == 0


def test_entry_without_any_identifier_is_caught(project):
    text = CLEAN.replace("  archivePrefix = {arXiv},\n  eprint        = {2401.00001}\n", "")
    assert project(text, tex=r"\cite{good2024entry}") == 1


def test_arxiv_id_left_in_prose_is_caught(project, capsys):
    """The exact shape the 2026-08-25 backfill removed: id present, field absent.

    The message has to name the real problem. "No resolvable identifier" sends someone
    off to look one up when it is already sitting in the entry, one field over.
    """
    text = CLEAN.replace(
        "  archivePrefix = {arXiv},\n  eprint        = {2401.00001}\n",
        "  journal       = {arXiv preprint arXiv:2401.00001}\n",
    )
    assert project(text, tex=r"\cite{good2024entry}") == 1
    assert "only in prose" in capsys.readouterr().err


def test_prose_journal_is_fine_once_the_eprint_field_exists(project):
    """Both together are normal. Flagging that would fail every backfilled entry."""
    text = CLEAN.replace(
        "  archivePrefix = {arXiv},",
        "  journal       = {arXiv preprint arXiv:2401.00001},\n  archivePrefix = {arXiv},",
    )
    assert project(text, tex=r"\cite{good2024entry}") == 0


def test_malformed_eprint_is_caught(project):
    text = CLEAN.replace("2401.00001", "arXiv:2401.00001")
    assert project(text, tex=r"\cite{good2024entry}") == 1


def test_versioned_eprint_is_accepted(project):
    """`2505.24313v2` is a deliberate version pin, not a malformed id."""
    assert project(CLEAN.replace("2401.00001", "2401.00001v2"), tex=r"\cite{good2024entry}") == 0


def test_malformed_doi_is_caught(project):
    text = CLEAN.replace("  eprint        = {2401.00001}\n", "  doi           = {not-a-doi}\n")
    assert project(text, tex=r"\cite{good2024entry}") == 1


def test_duplicate_key_is_caught(project):
    assert project(CLEAN + CLEAN, tex=r"\cite{good2024entry}") == 1


def test_dangling_citation_is_caught(project):
    assert project(tex=r"\cite{good2024entry,nosuchkey2020}") == 1


def test_orphan_entry_is_caught(project):
    assert project(tex=r"\relax") == 1


def test_intake_mention_accounts_for_an_uncited_entry(project):
    """Naming a key in the intake log is enough; positioning is a human judgement."""
    assert project(tex=r"\relax", intake_text="see `good2024entry` in the queue") == 0


def test_excluded_directories_are_not_scanned(project, tmp_path):
    """Someone else's bibliography in the tree is a finding nobody here can act on."""
    lab = tmp_path / "rit-manuscripts"
    lab.mkdir()
    (lab / "theirs.tex").write_text(r"\cite{some_lab_key_we_do_not_have}")
    assert project(tex=r"\cite{good2024entry}", config='exclude = ["rit-manuscripts"]') == 0


def test_without_the_exclusion_that_directory_is_scanned(project, tmp_path):
    lab = tmp_path / "rit-manuscripts"
    lab.mkdir()
    (lab / "theirs.tex").write_text(r"\cite{some_lab_key_we_do_not_have}")
    assert project(tex=r"\cite{good2024entry}") == 1


def test_brace_protection_survives_title_extraction(project, dk):
    """`{LLM}s` must read as one title, not truncate at the first closing brace."""
    text = CLEAN.replace("A Perfectly Ordinary Title", "Fine-tuning of {LLM}s from User-Edits")
    assert project(text, tex=r"\cite{good2024entry}") == 0
    entries = list(dk.entries(text))
    assert dk.field(entries[0][2], "title") == "Fine-tuning of {LLM}s from User-Edits"


def test_normalise_equates_brace_protected_and_plain_titles(dk):
    assert dk.normalise("Fine-tuning of {LLM}s") == dk.normalise("Fine-tuning of LLMs")


def test_normalise_unescapes_html_entities(dk):
    """arXiv's Atom feed returns `&amp;` where the entry writes `\\&`.

    Left alone the entity survives normalisation as the word "amp", and every title
    containing an ampersand reports as drift.
    """
    assert dk.normalise(r"ecology \& evolution") == dk.normalise("ecology &amp; evolution")


def test_a_configured_project_lints_clean_through_the_command_line(dk, tmp_path, capsys):
    (tmp_path / "references.bib").write_text(CLEAN)
    (tmp_path / "paper.tex").write_text(r"\cite{good2024entry}")
    (tmp_path / "dokimasia.toml").write_text('bib = ["references.bib"]\n')
    assert dk.main(["--root", str(tmp_path), "lint"]) == 0
    out = capsys.readouterr()
    assert out.out.startswith("dokimasia: 1 entries")
    assert out.err == ""


# --- exemptions -------------------------------------------------------------------------


def test_an_exemption_without_a_reason_is_a_config_error(dk, tmp_path):
    """A reason-less exemption is indistinguishable from a silenced mistake."""
    (tmp_path / "dokimasia.toml").write_text('[exempt.title]\ngood2024entry = "  "\n')
    with pytest.raises(dk.ConfigError, match="reason"):
        dk.load_config(tmp_path)


def test_a_record_exemption_without_a_reason_is_a_config_error(dk, tmp_path):
    (tmp_path / "dokimasia.toml").write_text('[exempt.record]\ngood2024entry = ""\n')
    with pytest.raises(dk.ConfigError, match="reason"):
        dk.load_config(tmp_path)


def test_an_exemption_naming_a_missing_entry_is_a_finding(project, capsys):
    """An exemption left behind after its entry was removed should fail."""
    config = '[exempt.title]\ngone2020entry = "the source record misspells the title"\n'
    assert project(tex=r"\cite{good2024entry}", config=config) == 1
    assert "exemption for missing entry" in capsys.readouterr().err


def test_a_record_exemption_naming_a_missing_entry_is_a_finding(project, capsys):
    config = '[exempt.record]\ngone2020entry = "the source reports a date we do not use"\n'
    assert project(tex=r"\cite{good2024entry}", config=config) == 1
    assert "exemption for missing entry" in capsys.readouterr().err


def test_an_exemption_naming_an_existing_entry_is_clean(project):
    config = '[exempt.title]\ngood2024entry = "the source record misspells the title"\n'
    assert project(tex=r"\cite{good2024entry}", config=config) == 0


# --- intake -----------------------------------------------------------------------------


def test_staged_entry_is_accounted_for_but_not_a_finding(project):
    """Staging an unread paper is legitimate bookkeeping, not an error."""
    assert project(tex=r"\relax", intake_text=STAGED_INTAKE) == 0


def test_citing_a_staged_unread_entry_is_caught(project, capsys):
    assert project(tex=r"\cite{good2024entry}", intake_text=STAGED_INTAKE) == 1
    assert "cited but unread" in capsys.readouterr().err


def test_positioned_entry_may_be_cited_freely(project):
    """Once a key sits under a normal topic heading it is fair game."""
    positioned = "# intake\n\n## Robust aggregation\n\n- `good2024entry` -- read and positioned.\n"
    assert project(tex=r"\cite{good2024entry}", intake_text=positioned) == 0


def test_staged_section_ends_at_the_next_heading(project):
    """A key after the staging section must not inherit its unread status."""
    mixed = (
        "# intake\n\n## not yet positioned\n\n- `someone_else2020`\n\n"
        "## Robust aggregation\n\n- `good2024entry` -- positioned.\n"
    )
    assert project(tex=r"\cite{good2024entry}", intake_text=mixed) == 0


def test_staged_headings_are_configurable(dk, tmp_path):
    intake = "# log\n\n## Unread pile\n\n- `good2024entry`\n"
    (tmp_path / "related-work").mkdir()
    (tmp_path / "related-work" / "intake.md").write_text(intake)
    (tmp_path / "dokimasia.toml").write_text(
        '[intake]\nfile = "related-work/intake.md"\nstaged_headings = ["Unread Pile"]\n'
    )
    cfg = dk.load_config(tmp_path)
    assert dk.staged_keys(cfg) == {"good2024entry"}
    assert dk.accounted_keys(cfg) == {"good2024entry"}


def test_a_key_read_out_of_staging_is_no_longer_staged(dk, tmp_path):
    """Moving a key under a normal heading ends its staged status."""
    (tmp_path / "log.md").write_text(STAGED_INTAKE)
    (tmp_path / "dokimasia.toml").write_text('[intake]\nfile = "log.md"\n')
    assert dk.staged_keys(dk.load_config(tmp_path)) == {"good2024entry"}
    (tmp_path / "log.md").write_text("## Robust aggregation\n\n- `good2024entry`\n")
    assert dk.staged_keys(dk.load_config(tmp_path)) == set()


def test_orphan_reporting_can_be_switched_off(project):
    assert project(tex=r"\relax", config="orphans = false\n") == 0


# --- author and title comparison ---------------------------------------------------------


def test_surname_handles_both_bibtex_orders(dk):
    assert dk.surname("Yin, Dong and Chen, Yudong") == "yin"
    assert dk.surname("Dong Yin and Yudong Chen") == "yin"
    corporate = dk.surname("{Association for Computing Machinery}")
    assert corporate == "association for computing machinery"
    assert dk.surname(None) == ""


def test_multi_part_surname_matches_the_api_ordering(dk):
    assert dk._matches_author("De Vaan, Mathijs", ["Mathijs De Vaan"])
    assert dk._matches_author("El Mhamdi, El Mahdi", ["El Mahdi El Mhamdi"])


def test_wrong_first_author_is_caught(dk):
    assert not dk._matches_author("Imam, Neena", ["Kun Yang", "Neena Imam"])


def test_missing_author_data_is_not_a_mismatch(dk):
    """Nothing to compare must never read as drift."""
    assert dk._matches_author(None, ["Kun Yang"])
    assert dk._matches_author("Yang, Kun", [])


# --- rendered ---------------------------------------------------------------------------


@pytest.fixture
def paper(dk, tmp_path):
    """A document directory `p/` with a `main.tex`; returns (cfg, write)."""
    (tmp_path / "p").mkdir()

    def write(tex, bbl=None):
        (tmp_path / "p" / "main.tex").write_text("\\documentclass{article}\n" + tex)
        if bbl is not None:
            (tmp_path / "p" / "main.bbl").write_text(bbl)
        return dk.load_config(tmp_path)

    return write


def test_rendered_passes_when_every_cited_key_is_in_the_bbl(dk, paper, capsys):
    cfg = paper(r"\cite{a2020,b2021}", r"\bibitem{a2020}...\bibitem{b2021}...")
    assert dk.rendered(cfg) == 0
    assert "2/2 cited keys rendered" in capsys.readouterr().out


def test_rendered_catches_a_citation_that_did_not_render(dk, paper):
    """The failure that motivated it: cites resolved to nothing in the bbl."""
    cfg = paper(r"\cite{a2020,missing2021}", r"\bibitem{a2020}...")
    assert dk.rendered(cfg) == 1


def test_rendered_ignores_nocite_expansion(dk, paper, capsys):
    """A skeleton using \\nocite{*} has nothing to assert, and must not score full marks."""
    cfg = paper(r"\nocite{*}", r"\bibitem{a2020}...\bibitem{b2021}...")
    assert dk.rendered(cfg) == 0
    assert "0/0 cited keys rendered" in capsys.readouterr().out


# --- year handling and the cache -----------------------------------------------------------

_ONLINE_FIRST = {
    "title": ["Ethics in the mining of software repositories"],
    "author": [{"given": "Nicolas E.", "family": "Gold"}],
    "issued": {"date-parts": [[2021, 11, 2]]},
    "published-print": {"date-parts": [[2022, 1]]},
}


def test_a_journal_that_posted_online_first_carries_both_its_years(dk):
    """Springer issued this 2021-11-02 and printed it in 27(1), 2022; both are correct to cite.

    Reporting the issue year as drift on every scheduled run is how a check teaches its reader
    to ignore it, which is what had happened to this one.
    """
    record = dk.crossref_fields(_ONLINE_FIRST)
    assert record["year"] == 2021
    assert record["print_year"] == 2022


def test_a_record_with_only_an_issued_date_has_no_print_year(dk):
    message = {k: v for k, v in _ONLINE_FIRST.items() if k != "published-print"}
    assert dk.crossref_fields(message)["print_year"] is None


def test_a_cached_record_from_an_older_shape_is_a_miss(dk):
    """Adding a field must not leave the cache answering for it with silence.

    `print_year` was added to catch a journal that posts online first, and every cached record
    predated it, so the drift the change removed survived in exactly the entries the cache covered.
    """
    now = 1_000_000.0
    fresh = {"record": {"title": "x"}, "at": now, "schema": dk.RECORD_SCHEMA}
    assert dk._cache_hit(fresh, now)
    assert not dk._cache_hit({"record": {"title": "x"}, "at": now}, now)
    assert not dk._cache_hit(
        {"record": {"title": "x"}, "at": now, "schema": dk.RECORD_SCHEMA - 1}, now
    )


def test_a_stale_or_malformed_cache_entry_is_a_miss(dk):
    now = 1_000_000.0
    stale = {"record": {"title": "x"}, "at": now - dk.CACHE_TTL - 1, "schema": dk.RECORD_SCHEMA}
    assert not dk._cache_hit(stale, now)
    assert not dk._cache_hit({"record": "not a dict", "at": now, "schema": dk.RECORD_SCHEMA}, now)
    assert not dk._cache_hit(None, now)


def test_what_verify_stores_reads_back_as_a_hit(dk):
    """The write and the read are one contract: an entry written now must be reusable now.

    Without the schema stamp on the way in, every read is a miss, the cache silently stops
    working, and the run hammers arXiv and Crossref until they stop answering.
    """
    now = 1_000_000.0
    assert dk._cache_hit(dk._cache_entry({"title": "x"}, now), now)


# --- lookups -----------------------------------------------------------------------------


class _Response:
    def __init__(self, body):
        self._body = body

    def read(self):
        return self._body.encode()


def _refuse(code, reason):
    def refuse(request, timeout=0):
        raise urllib.error.HTTPError(request.full_url, code, reason, email.message.Message(), None)

    return refuse


def test_a_lookup_that_fails_says_why(dk, monkeypatch):
    """A throttled host and a missing record were the same event, so a blocked run read as a
    bibliography with 67 bad identifiers."""
    monkeypatch.setattr(dk.time, "sleep", lambda *_: None)
    monkeypatch.setattr(dk.urllib.request, "urlopen", _refuse(406, "Not Acceptable"))
    body, reason = dk._get("https://example.invalid/x")
    assert body is None
    assert reason == "HTTP 406"


def test_a_lookup_that_succeeds_reports_no_reason(dk, monkeypatch):
    monkeypatch.setattr(dk.urllib.request, "urlopen", lambda *a, **k: _Response("<feed/>"))
    assert dk._get("https://example.invalid/x") == ("<feed/>", "")


def test_a_throttled_host_is_waited_out_rather_than_retried_at_once(dk, monkeypatch):
    """Three retries two seconds apart all land inside the same block."""
    slept: list[float] = []
    monkeypatch.setattr(dk.time, "sleep", slept.append)
    monkeypatch.setattr(dk.urllib.request, "urlopen", _refuse(429, "Too Many Requests"))
    dk._get("https://example.invalid/x")
    assert slept == [dk.BACKOFF[0], dk.BACKOFF[1]]
    assert min(slept) >= 5, "a throttle needs longer than a blip"


def test_a_missing_page_is_not_waited_out(dk, monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(dk.time, "sleep", slept.append)
    monkeypatch.setattr(dk.urllib.request, "urlopen", _refuse(404, "Not Found"))
    assert dk._get("https://example.invalid/x") == (None, "HTTP 404")
    assert slept == [2, 4], "a 404 is not a throttle and must not cost a minute"


def test_a_failed_arxiv_lookup_is_not_mistaken_for_a_record(dk, monkeypatch):
    monkeypatch.setattr(dk, "_get", lambda *a, **k: (None, "HTTP 406"))
    record = dk._arxiv_record("1812.06127")
    assert record["failed"] == "HTTP 406"
    assert record.get("title") is None


def test_a_failed_lookup_is_never_cached(dk):
    """Caching one would freeze a throttled minute into a fortnight."""
    assert not dk._cacheable({"failed": "HTTP 406"})
    assert not dk._cacheable(None)
    assert dk._cacheable({"title": "x"})


def test_a_timeout_is_not_waited_out_like_a_throttle(dk, monkeypatch):
    """A slow host is a blip; only the statuses that mean 'you, later' earn the long wait."""
    slept: list[float] = []

    def timeout(request, timeout=0):
        raise TimeoutError("timed out")

    monkeypatch.setattr(dk.time, "sleep", slept.append)
    monkeypatch.setattr(dk.urllib.request, "urlopen", timeout)
    assert dk._get("https://example.invalid/x") == (None, "TimeoutError")
    assert slept == [2, 4]


# --- 1. field values in any BibTeX form --------------------------------------------------


def test_field_reads_quoted_and_bare_values(dk):
    body = (
        'k,\n  doi = "10.1/x",\n  title = "A {Braced} \\"Quote\\"",\n  year = 2023,\n  month = jan'
    )
    assert dk.field(body, "doi") == "10.1/x"
    assert dk.field(body, "title") == 'A {Braced} \\"Quote\\"'
    assert dk.field(body, "year") == "2023"
    assert dk.field(body, "month") == "jan"


def test_field_reads_a_one_line_entry_and_a_concatenation(dk):
    body = 'k, author = "Doe" # " and Roe", year = {2020}'
    assert dk.field(body, "author") == "Doe and Roe"
    assert dk.field(body, "year") == "2020"


def test_a_quoted_doi_counts_as_an_identifier(project):
    text = '@article{q2020,\n  title = "T",\n  doi = "10.1/x"\n}\n'
    assert project(text, tex=r"\cite{q2020}") == 0


def test_a_bare_year_does_not_hide_a_quoted_identifier(project):
    text = '@misc{q2020,\n  year = 2023,\n  url = "https://example.org"\n}\n'
    assert project(text, tex=r"\cite{q2020}") == 0


# --- 2. non-entries ----------------------------------------------------------------------


def test_string_preamble_and_comment_are_not_entries(dk, project):
    text = (
        '@STRING{jan = "January"}\n@Preamble{"\\newcommand{\\x}{y}"}\n'
        "@comment{@article{inside, title = {x}}}\n" + CLEAN
    )
    assert [key for _, key, _ in dk.entries(text)] == ["good2024entry"]
    assert project(text, tex=r"\cite{good2024entry}") == 0


# --- 3. old-style arXiv ids --------------------------------------------------------------


@pytest.mark.parametrize("ident", ["hep-th/9901001", "math.GT/0309136", "hep-th/9901001v2"])
def test_old_style_arxiv_ids_are_well_formed(project, ident):
    assert project(CLEAN.replace("2401.00001", ident), tex=r"\cite{good2024entry}") == 0


def test_a_malformed_old_style_id_is_still_caught(project):
    assert project(CLEAN.replace("2401.00001", "hep-th/99"), tex=r"\cite{good2024entry}") == 1


def test_an_old_style_id_in_prose_is_found(project, capsys):
    text = CLEAN.replace(
        "  archivePrefix = {arXiv},\n  eprint        = {2401.00001}\n",
        "  journal       = {arXiv preprint arXiv:hep-th/9901001}\n",
    )
    assert project(text, tex=r"\cite{good2024entry}") == 1
    assert "only in prose" in capsys.readouterr().err


# --- 4. citation commands ----------------------------------------------------------------


@pytest.mark.parametrize(
    "tex",
    [
        r"\citep{a,b}",
        r"\citet*{a, b}",
        r"\citeauthor{a}\citeyear{b}",
        r"\parencite{a,b}",
        r"\textcite[see][p.~3]{a,b}",
        r"\autocite*[12]{a,b}",
        r"\footcite{a}\nocite{b}",
        r"\citep[see][p.~3]{a,b}",
        "\\cite{a,\n b}",
        r"\parencites[3]{a}[4]{b}",
    ],
)
def test_cite_commands_yield_their_keys(dk, tex):
    assert dk.cite_keys(tex) == {"a", "b"}


def test_nocite_star_names_no_key(dk):
    assert dk.cite_keys(r"\nocite{*}") == set()


def test_commands_that_are_not_key_lists_are_ignored(dk):
    assert dk.cite_keys(r"\setcitestyle{round}\renewcommand{\mycite}[1]{\cite{#1}}") == set()


def test_a_commented_citation_is_not_a_citation(dk):
    text = "% \\cite{x}\n\\cite{y} % \\cite{z}\nwe gain 50\\% \\cite{w}\n"
    assert dk.cite_keys(text) == {"y", "w"}


def test_an_escaped_backslash_before_percent_still_starts_a_comment(dk):
    assert dk.cite_keys("line\\\\% \\cite{x}\n\\cite{y}") == {"y"}


def test_lint_uses_every_citation_command(project):
    text = CLEAN + CLEAN.replace("good2024entry", "other2024entry")
    assert project(text, tex=r"\citep[see]{good2024entry}\textcite{other2024entry}") == 0


# --- 5. documents are derived ------------------------------------------------------------


def _tree(tmp_path, files):
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


def test_documents_are_the_files_with_a_documentclass(dk, tmp_path):
    _tree(
        tmp_path,
        {
            "a/main.tex": "\\documentclass{article}\n",
            "a/sec.tex": "no class here\n",
            "b/c.tex": "% \\documentclass{article}\n",
            "d/e.tex": "\\documentclass[12pt]{report}\n",
            ".hidden/f.tex": "\\documentclass{article}\n",
            "node_modules/g.tex": "\\documentclass{article}\n",
            "skip/h.tex": "\\documentclass{article}\n",
        },
    )
    (tmp_path / "dokimasia.toml").write_text('exclude = ["skip"]\n')
    cfg = dk.load_config(tmp_path)
    assert [p.relative_to(tmp_path).as_posix() for p in dk.documents(cfg)] == [
        "a/main.tex",
        "d/e.tex",
    ]


def test_a_document_cites_through_input_include_and_subfile(dk, tmp_path):
    _tree(
        tmp_path,
        {
            "m.tex": "\\documentclass{article}\n\\cite{r}\\input{s/one}\\include{two.tex}"
            "\\subfile{s/three}\\input{missing}\n% \\input{commented}\n",
            "s/one.tex": "\\cite{one}\n\\input{s/one}\n",
            "two.tex": "\\cite{two}\n",
            "s/three.tex": "\\cite{three}\n",
            "commented.tex": "\\cite{nope}\n",
            "unrelated.tex": "\\cite{other}\n",
        },
    )
    assert dk.document_cites(tmp_path / "m.tex") == {"r", "one", "two", "three"}


def test_included_files_cycle_safely(dk, tmp_path):
    _tree(
        tmp_path,
        {
            "m.tex": "\\documentclass{article}\\input{a}\n",
            "a.tex": "\\cite{a}\\input{b}\n",
            "b.tex": "\\cite{b}\\input{a}\\input{m}\n",
        },
    )
    assert dk.document_cites(tmp_path / "m.tex") == {"a", "b"}


def test_rendered_without_arguments_checks_every_document(dk, tmp_path, capsys):
    _tree(
        tmp_path,
        {
            "p/main.tex": "\\documentclass{article}\\cite{a}\n",
            "p/main.bbl": "\\bibitem{a}x",
            "q/main.tex": "\\documentclass{article}\\cite{a}\n",
            "q/main.bbl": "\\bibitem{a}x",
        },
    )
    assert dk.rendered(dk.load_config(tmp_path)) == 0
    out = capsys.readouterr().out
    assert "p/main.tex: 1/1" in out
    assert "q/main.tex: 1/1" in out


def test_rendered_with_arguments_checks_only_those(dk, tmp_path, capsys):
    _tree(
        tmp_path,
        {
            "p/main.tex": "\\documentclass{article}\\cite{a}\n",
            "p/main.bbl": "\\bibitem{a}x",
            "q/main.tex": "\\documentclass{article}\\cite{a,b}\n",
            "q/main.bbl": "\\bibitem{a}x",
        },
    )
    assert dk.main(["--root", str(tmp_path), "rendered", "p/main.tex"]) == 0
    assert "q/main.tex" not in capsys.readouterr().out


def test_the_bibliography_is_the_same_stem_beside_the_document(dk, tmp_path, capsys):
    _tree(
        tmp_path,
        {
            "thesis.tex": "\\documentclass{book}\\cite{a}\n",
            "main.bbl": "\\bibitem{a}x",
        },
    )
    assert dk.rendered(dk.load_config(tmp_path)) == 0
    assert "thesis.tex: not built" in capsys.readouterr().out


# --- 6. rendered keys are parsed ---------------------------------------------------------


def test_a_prefix_key_does_not_pass_because_a_longer_key_rendered(dk, paper, capsys):
    """`li2020` is not rendered just because `li2020b` was."""
    cfg = paper(r"\cite{li2020}", r"\bibitem{li2020b}...")
    assert dk.rendered(cfg) == 1
    assert "li2020}" in capsys.readouterr().err


def test_bbl_keys_reads_bibtex_labels_and_biber_entries(dk):
    bbl = (
        "\\bibitem[{Doe(2020)}]{doe2020}\ntext\n"
        "\\bibitem[Roe et~al.(2021)Roe, Poe\n and Moe]{roe2021}\n"
        "\\bibitem{plain}\n"
        "\\entry{biber2022}{article}{}\n\\entry{ biber2023 }{book}{}\n"
    )
    assert dk.bbl_keys(bbl) == {"doe2020", "roe2021", "plain", "biber2022", "biber2023"}


def test_a_key_in_running_text_of_the_bbl_does_not_render(dk):
    assert dk.bbl_keys("mentions li2020 in prose \\bibitem{other}") == {"other"}


# --- 7. skipped documents are reported ---------------------------------------------------


def test_an_unbuilt_document_is_named_and_not_a_failure_by_default(dk, paper, capsys):
    cfg = paper(r"\cite{a}")
    assert dk.rendered(cfg) == 0
    out = capsys.readouterr().out
    assert "p/main.tex: not built" in out
    assert "dokimasia: rendered: 0 documents checked, 1 not built (p/main.tex)" in out


def test_an_unbuilt_document_fails_under_require_built(dk, paper):
    assert dk.rendered(paper(r"\cite{a}"), require_built=True) == 1


def test_the_summary_counts_built_and_unbuilt_documents(dk, tmp_path, capsys):
    _tree(
        tmp_path,
        {
            "p/main.tex": "\\documentclass{article}\\cite{a}\n",
            "p/main.bbl": "\\bibitem{a}x",
            "q/main.tex": "\\documentclass{article}\n",
        },
    )
    dk.rendered(dk.load_config(tmp_path))
    assert "rendered: 1 documents checked, 1 not built (q/main.tex)" in capsys.readouterr().out


def test_the_command_line_exit_code_follows_require_built(dk, tmp_path):
    _tree(tmp_path, {"main.tex": "\\documentclass{article}\\cite{a}\n"})
    assert dk.main(["--root", str(tmp_path), "rendered"]) == 0
    assert dk.main(["--root", str(tmp_path), "--require-built", "rendered"]) == 1


def test_an_unknown_document_argument_is_a_usage_error(dk, tmp_path):
    assert dk.main(["--root", str(tmp_path), "rendered", "nope.tex"]) == 2


# --- 8. an unparseable response is a failed lookup ---------------------------------------


def test_an_arxiv_200_without_a_feed_is_a_failed_lookup(dk, monkeypatch):
    monkeypatch.setattr(dk, "_get", lambda *a, **k: ("<html>Service Unavailable</html>", ""))
    assert dk._arxiv_record("1812.06127") == {"failed": "unparseable response"}


def test_an_empty_arxiv_feed_means_no_such_record(dk, monkeypatch):
    feed = '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>x</title></feed>'
    monkeypatch.setattr(dk, "_get", lambda *a, **k: (feed, ""))
    assert dk._arxiv_record("1812.06127") is None


@pytest.mark.parametrize("body", ["not json", "{}", '{"message": "x"}', "[]"])
def test_an_unparseable_crossref_200_is_a_failed_lookup(dk, monkeypatch, body):
    monkeypatch.setattr(dk, "_get", lambda *a, **k: (body, ""))
    assert dk._crossref_record("10.1/x") == {"failed": "unparseable response"}


def test_a_valid_crossref_record_still_parses(dk, monkeypatch):
    body = json.dumps({"message": _ONLINE_FIRST})
    monkeypatch.setattr(dk, "_get", lambda *a, **k: (body, ""))
    assert dk._crossref_record("10.1/x")["year"] == 2021


def test_an_unparseable_response_is_unresolved_and_never_cached(dk, tmp_path, monkeypatch, capsys):
    (tmp_path / "references.bib").write_text(CLEAN)
    monkeypatch.setattr(dk, "_get", lambda *a, **k: ("<html>proxy</html>", ""))
    monkeypatch.setattr(dk.time, "sleep", lambda *_: None)
    assert dk.verify(dk.load_config(tmp_path), delay=0) == 0
    assert "unparseable response x1" in capsys.readouterr().out
    assert not (tmp_path / ".dokimasia-cache.json").read_text().strip("{}\n ")


# --- 9. polite pool ----------------------------------------------------------------------


def test_mailto_is_added_to_crossref_requests_and_the_user_agent(dk, monkeypatch):
    monkeypatch.setenv("DOKIMASIA_MAILTO", "me@example.org")
    seen: list[str] = []
    monkeypatch.setattr(dk, "_get", lambda url, *a, **k: (seen.append(url), ("", "x"))[1])
    dk._crossref_record("10.1/x")
    assert seen == ["https://api.crossref.org/works/10.1/x?mailto=me%40example.org"]
    assert dk.user_agent() == (
        "dokimasia/1.0 (+https://github.com/ajbarea/techne; mailto:me@example.org)"
    )


def test_the_request_carries_the_user_agent(dk, monkeypatch):
    monkeypatch.setenv("DOKIMASIA_MAILTO", "me@example.org")
    headers: list[dict] = []

    def capture(request, timeout=0):
        headers.append(dict(request.header_items()))
        return _Response("ok")

    monkeypatch.setattr(dk.urllib.request, "urlopen", capture)
    dk._get("https://example.invalid/x")
    assert "mailto:me@example.org" in headers[0]["User-agent"]


def test_without_mailto_nothing_is_added_and_no_address_is_hard_coded(dk, monkeypatch):
    monkeypatch.delenv("DOKIMASIA_MAILTO", raising=False)
    assert "mailto" not in dk._crossref_url("10.1/x")
    assert dk.user_agent() == "dokimasia/1.0 (+https://github.com/ajbarea/techne)"
    assert "@" not in dk.user_agent()


# --- 10. spans all configured bibliographies ---------------------------------------------


def test_duplicate_keys_across_files_are_findings(dk, tmp_path, capsys):
    (tmp_path / "a.bib").write_text(CLEAN)
    (tmp_path / "b.bib").write_text(CLEAN)
    (tmp_path / "p.tex").write_text(r"\cite{good2024entry}")
    assert dk.lint(dk.load_config(tmp_path)) == 1
    err = capsys.readouterr().err
    assert "duplicate key: good2024entry appears 2 times (a.bib, b.bib)" in err


def test_a_citation_resolves_against_any_bibliography(dk, tmp_path):
    (tmp_path / "a.bib").write_text(CLEAN)
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.bib").write_text(CLEAN.replace("good2024entry", "other2024entry"))
    (tmp_path / "p.tex").write_text(r"\cite{good2024entry,other2024entry}")
    assert dk.lint(dk.load_config(tmp_path)) == 0


def test_an_uncited_entry_in_the_second_bibliography_is_an_orphan(dk, tmp_path):
    (tmp_path / "a.bib").write_text(CLEAN)
    (tmp_path / "b.bib").write_text(CLEAN.replace("good2024entry", "other2024entry"))
    (tmp_path / "p.tex").write_text(r"\cite{good2024entry}")
    assert dk.lint(dk.load_config(tmp_path)) == 1


def test_configured_bibliographies_replace_discovery(dk, tmp_path):
    (tmp_path / "a.bib").write_text(CLEAN)
    (tmp_path / "ignored.bib").write_text("@article{broken,\n}\n")
    (tmp_path / "p.tex").write_text(r"\cite{good2024entry}")
    (tmp_path / "dokimasia.toml").write_text('bib = ["a.bib"]\n')
    assert dk.lint(dk.load_config(tmp_path)) == 0


# --- configuration -----------------------------------------------------------------------


def test_an_unknown_key_is_a_config_error_naming_it(dk, tmp_path, capsys):
    (tmp_path / "dokimasia.toml").write_text("orphan = true\n")
    assert dk.main(["--root", str(tmp_path), "lint"]) == 2
    assert "orphan" in capsys.readouterr().err


@pytest.mark.parametrize(
    "toml", ["[intake]\nfle = 'x'\n", "[exempt.titel]\na = 'b'\n", "[exempt]\nrecords = {}\n"]
)
def test_unknown_keys_in_subtables_are_config_errors(dk, tmp_path, toml):
    (tmp_path / "dokimasia.toml").write_text(toml)
    with pytest.raises(dk.ConfigError, match="unknown key"):
        dk.load_config(tmp_path)


@pytest.mark.parametrize("toml", ["bib = 'a.bib'\n", "orphans = 'yes'\n", "cache = 3\n", "bib = ["])
def test_badly_typed_or_invalid_config_is_an_error(dk, tmp_path, toml):
    (tmp_path / "dokimasia.toml").write_text(toml)
    with pytest.raises(dk.ConfigError):
        dk.load_config(tmp_path)


def test_a_missing_configured_bib_is_a_config_error(dk, tmp_path):
    (tmp_path / "dokimasia.toml").write_text('bib = ["nope.bib"]\n')
    assert dk.main(["--root", str(tmp_path), "lint"]) == 2


def test_a_project_with_no_bib_is_a_config_error(dk, tmp_path):
    assert dk.main(["--root", str(tmp_path), "lint"]) == 2


def test_an_unknown_mode_is_a_usage_error(dk, tmp_path):
    with pytest.raises(SystemExit) as exit_:
        dk.main(["--root", str(tmp_path), "frobnicate"])
    assert exit_.value.code == 2


def test_the_root_is_found_by_walking_up_to_a_config(dk, tmp_path):
    (tmp_path / "dokimasia.toml").write_text("")
    deep = tmp_path / "a" / "b"
    deep.mkdir(parents=True)
    assert dk.load_config(cwd=deep).root == tmp_path.resolve()


def test_a_pyproject_table_marks_the_root(dk, tmp_path):
    (tmp_path / "pyproject.toml").write_text('[tool.dokimasia]\nexclude = ["x"]\n')
    deep = tmp_path / "a"
    deep.mkdir()
    cfg = dk.load_config(cwd=deep)
    assert cfg.root == tmp_path.resolve()
    assert cfg.exclude == {"x"}


def test_a_pyproject_without_the_table_is_not_a_root(dk, tmp_path):
    inner = tmp_path / "inner"
    inner.mkdir()
    (inner / "pyproject.toml").write_text('[project]\nname = "x"\n')
    (tmp_path / "dokimasia.toml").write_text("")
    assert dk.load_config(cwd=inner).root == tmp_path.resolve()


def test_dokimasia_toml_wins_over_pyproject(dk, tmp_path):
    (tmp_path / "dokimasia.toml").write_text('cache = "own.json"\n')
    (tmp_path / "pyproject.toml").write_text('[tool.dokimasia]\ncache = "py.json"\n')
    assert str(dk.load_config(tmp_path).cache) == "own.json"


def test_the_root_falls_back_to_the_git_toplevel(dk, tmp_path):
    import subprocess

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    deep = tmp_path / "a"
    deep.mkdir()
    assert dk.load_config(cwd=deep).root == tmp_path.resolve()


def test_the_root_falls_back_to_the_cwd_without_git(dk, tmp_path, monkeypatch):
    monkeypatch.setattr(dk, "_git_toplevel", lambda cwd: None)
    assert dk.load_config(cwd=tmp_path).root == tmp_path.resolve()


def test_an_absent_git_binary_is_tolerated(dk, tmp_path, monkeypatch):
    def no_git(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(dk.subprocess, "run", no_git)
    assert dk._git_toplevel(tmp_path) is None


def test_the_root_option_beats_discovery(dk, tmp_path):
    (tmp_path / "dokimasia.toml").write_text("")
    other = tmp_path / "other"
    other.mkdir()
    assert dk.load_config(other).root == other.resolve()


def test_hidden_and_vendored_directories_are_never_scanned(dk, tmp_path):
    _tree(
        tmp_path,
        {
            "references.bib": CLEAN,
            ".venv/x.bib": "@article{broken,\n}\n",
            "node_modules/y.bib": "@article{broken2,\n}\n",
            "paper.tex": "\\cite{good2024entry}",
            ".git/z.tex": "\\cite{ghost}",
        },
    )
    assert dk.lint(dk.load_config(tmp_path)) == 0


def test_the_cache_path_is_configurable_and_relative_to_the_root(dk, tmp_path, monkeypatch):
    (tmp_path / "references.bib").write_text(CLEAN)
    (tmp_path / "dokimasia.toml").write_text('cache = "sub-cache.json"\n')
    monkeypatch.setattr(dk, "_get", lambda *a, **k: (None, "HTTP 500"))
    monkeypatch.setattr(dk.time, "sleep", lambda *_: None)
    dk.verify(dk.load_config(tmp_path), delay=0)
    assert (tmp_path / "sub-cache.json").exists()
    assert not (tmp_path / ".dokimasia-cache.json").exists()


def test_verify_exits_one_only_on_drift(dk, tmp_path, monkeypatch, capsys):
    (tmp_path / "references.bib").write_text(CLEAN)
    feed = (
        "<feed><entry><title>A Different Title</title><published>2024-01-01</published>"
        "<author><name>Jane Doe</name></author></entry></feed>"
    )
    monkeypatch.setattr(dk, "_get", lambda *a, **k: (feed, ""))
    monkeypatch.setattr(dk.time, "sleep", lambda *_: None)
    assert dk.main(["--root", str(tmp_path), "verify"]) == 1
    assert "title drift: good2024entry" in capsys.readouterr().err


def test_a_title_exemption_skips_the_title_and_prints_its_reason(dk, tmp_path, monkeypatch, capsys):
    (tmp_path / "references.bib").write_text(CLEAN)
    (tmp_path / "dokimasia.toml").write_text(
        '[exempt.title]\ngood2024entry = "the source misspells a word"\n'
    )
    feed = (
        "<feed><entry><title>A Diferent Title</title><published>2024-01-01</published>"
        "<author><name>Jane Doe</name></author></entry></feed>"
    )
    monkeypatch.setattr(dk, "_get", lambda *a, **k: (feed, ""))
    monkeypatch.setattr(dk.time, "sleep", lambda *_: None)
    assert dk.main(["--root", str(tmp_path), "verify"]) == 0
    assert "exempt: good2024entry -- the source misspells a word" in capsys.readouterr().out
