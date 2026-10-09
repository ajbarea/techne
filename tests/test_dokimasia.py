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
from pathlib import Path

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


def test_an_ieeetran_style_control_is_not_an_entry(dk, project):
    """`@IEEEtranBSTCTL` and `\\bstctlcite` switch IEEEtran's style; neither is a reference."""
    text = '@IEEEtranBSTCTL{BSTcontrol,\n  CTLuse_forced_etal = "yes"\n}\n' + CLEAN
    assert [key for _, key, _ in dk.entries(text)] == ["good2024entry"]
    assert project(text, tex=r"\bstctlcite{BSTcontrol}\cite{good2024entry}") == 0


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
    assert dk.cite_keys(r"\bstctlcite{BSTcontrol}") == set()


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
            "q/main.tex": "\\documentclass{article}\\cite{a}\n",
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


# =========================================================================================
# Review round: every test below was run against the previous engine and failed there.
# =========================================================================================

DOC = "\\documentclass{article}\n"


def _err(capsys):
    return capsys.readouterr().err


# --- R1. \nocite{*} covers the bibliographies a document uses ----------------------------


def test_nocite_star_counts_every_entry_as_cited(dk, tmp_path):
    """A skeleton that renders the whole bibliography leaves nothing to be an orphan."""
    _tree(
        tmp_path,
        {
            "references.bib": CLEAN,
            "p/main.tex": DOC + "\\nocite{*}\n\\bibliography{../references}\n",
        },
    )
    assert dk.lint(dk.load_config(tmp_path)) == 0


def test_nocite_star_is_named_in_one_summary_line(dk, tmp_path, capsys):
    _tree(
        tmp_path,
        {
            "references.bib": CLEAN,
            "p/main.tex": DOC + "\\nocite{*}\n\\bibliography{../references}\n",
            "q/main.tex": DOC + "\\nocite{*}\n\\bibliography{../references}\n",
        },
    )
    dk.lint(dk.load_config(tmp_path))
    lines = [ln for ln in capsys.readouterr().out.splitlines() if "nocite" in ln]
    assert len(lines) == 1
    assert "p/main.tex" in lines[0]
    assert "q/main.tex" in lines[0]
    assert "references.bib" in lines[0]


def test_a_commented_nocite_star_covers_nothing(dk, tmp_path):
    _tree(
        tmp_path,
        {
            "references.bib": CLEAN,
            "p/main.tex": DOC + "% \\nocite{*}\n\\bibliography{../references}\n",
        },
    )
    assert dk.lint(dk.load_config(tmp_path)) == 1


def test_nocite_star_covers_only_the_bibliographies_its_document_uses(dk, tmp_path, capsys):
    _tree(
        tmp_path,
        {
            "a.bib": CLEAN,
            "b.bib": CLEAN.replace("good2024entry", "other2024entry"),
            "p/main.tex": DOC + "\\nocite{*}\n\\bibliography{../a}\n",
            "q/main.tex": DOC + "\\cite{good2024entry}\n\\bibliography{../a}\n",
        },
    )
    assert dk.lint(dk.load_config(tmp_path)) == 1
    assert "orphan entry: other2024entry" in _err(capsys)


# --- R2. cite commands are case-insensitive in the cite part -----------------------------


@pytest.mark.parametrize(
    "command", ["Cite", "Citet", "Citep", "Citeauthor", "Parencite", "Textcite", "Autocite"]
)
def test_capitalised_cite_commands_count(dk, command):
    assert dk.cite_keys(f"\\{command}{{a,b}}") == {"a", "b"}


# --- R3. more include forms, and unreached files are reported ----------------------------


def test_input_without_braces_is_followed(dk, tmp_path):
    _tree(tmp_path, {"m.tex": DOC + "\\input sec\n", "sec.tex": "\\cite{k}\n"})
    assert dk.document_cites(tmp_path / "m.tex") == {"k"}


@pytest.mark.parametrize("command", ["import", "inputfrom", "includefrom"])
def test_import_forms_resolve_from_the_document_directory(dk, tmp_path, command):
    _tree(
        tmp_path,
        {
            "m.tex": DOC + f"\\input{{a/inc}}\\{command}{{d/}}{{x}}\n",
            "a/inc.tex": "\\cite{inc}\n",
            "d/x.tex": "\\cite{right}\n",
            "a/d/x.tex": "\\cite{wrong}\n",
        },
    )
    assert dk.document_cites(tmp_path / "m.tex") == {"inc", "right"}


@pytest.mark.parametrize("command", ["subimport", "subinputfrom", "subincludefrom"])
def test_sub_forms_resolve_from_the_including_file(dk, tmp_path, command):
    _tree(
        tmp_path,
        {
            "m.tex": DOC + "\\input{a/inc}\n",
            "a/inc.tex": f"\\{command}{{d}}{{x}}\n",
            "d/x.tex": "\\cite{wrong}\n",
            "a/d/x.tex": "\\cite{right}\n",
        },
    )
    assert dk.document_cites(tmp_path / "m.tex") == {"right"}


def test_rendered_names_tex_files_no_document_reached(dk, tmp_path, capsys):
    _tree(
        tmp_path,
        {
            "p/main.tex": DOC + "\\cite{a}\\input{used}\n",
            "p/main.bbl": "\\bibitem{a}x",
            "p/used.tex": "x\n",
            "p/stray.tex": "\\cite{a}\n",
            "p/deep/also.tex": "y\n",
        },
    )
    assert dk.rendered(dk.load_config(tmp_path)) == 0
    out = capsys.readouterr().out
    assert "2 .tex files" in out
    assert "p/stray.tex" in out
    assert "p/deep/also.tex" in out
    assert "used.tex" not in out


def test_rendered_is_quiet_when_every_file_was_reached(dk, tmp_path, capsys):
    _tree(
        tmp_path,
        {
            "p/main.tex": DOC + "\\cite{a}\\input{used}\n",
            "p/main.bbl": "\\bibitem{a}x",
            "p/used.tex": "x\n",
        },
    )
    dk.rendered(dk.load_config(tmp_path))
    assert "reached by no document" not in capsys.readouterr().out


# --- R4. cache path safety ---------------------------------------------------------------


def _no_network(dk, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("the network was reached")

    monkeypatch.setattr(dk, "_get", boom)


@pytest.mark.parametrize("path", ["../escape.json", "/tmp/dokimasia-escape.json", "a/../../x.json"])
def test_a_cache_outside_the_root_is_a_config_error(dk, tmp_path, path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "dokimasia.toml").write_text(f'cache = "{path}"\n')
    with pytest.raises(dk.ConfigError, match="cache"):
        dk.load_config(root)


def test_a_cache_symlinked_out_of_the_root_is_a_config_error(dk, tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    (tmp_path / "elsewhere.json").write_text("{}")
    (root / "link.json").symlink_to(tmp_path / "elsewhere.json")
    (root / "dokimasia.toml").write_text('cache = "link.json"\n')
    with pytest.raises(dk.ConfigError, match="cache"):
        dk.load_config(root)


@pytest.mark.parametrize("content", ["[1, 2]", "not json", '"text"', ""])
def test_a_cache_that_is_not_an_object_is_never_overwritten(dk, tmp_path, monkeypatch, content):
    (tmp_path / "references.bib").write_text(CLEAN)
    cache = tmp_path / ".dokimasia-cache.json"
    cache.write_text(content)
    _no_network(dk, monkeypatch)
    assert dk.main(["--root", str(tmp_path), "verify"]) == 2
    assert cache.read_text() == content


def test_the_error_for_a_bad_cache_names_the_file(dk, tmp_path, monkeypatch, capsys):
    (tmp_path / "references.bib").write_text(CLEAN)
    (tmp_path / ".dokimasia-cache.json").write_text("[]")
    _no_network(dk, monkeypatch)
    dk.main(["--root", str(tmp_path), "verify"])
    assert ".dokimasia-cache.json" in _err(capsys)


# --- R5. skill scripts run without a project ---------------------------------------------


def test_every_skill_script_runs_through_uv_without_the_project():
    """Plain `uv run` creates .venv and uv.lock in a user project that has a pyproject.toml."""
    from conftest import ROOT

    docs = [*ROOT.glob("plugins/*/skills/*/SKILL.md"), *ROOT.glob("docs/skills/*.md")]
    bad = [
        f"{path.relative_to(ROOT)}:{n}"
        for path in docs
        for n, line in enumerate(path.read_text().splitlines(), 1)
        if "uv run" in line and ".py" in line and "--no-project" not in line
    ]
    assert bad == []


# --- R6. documents are checked against their own bibliographies --------------------------


def _paper(tmp_path, name, bib, body):
    _tree(tmp_path, {f"{name}/main.tex": DOC + body + f"\\bibliography{{{bib}}}\n"})


def _entry(key):
    return CLEAN.replace("good2024entry", key)


def test_the_same_key_in_two_unrelated_papers_bibliographies_is_fine(dk, tmp_path):
    _tree(tmp_path, {"p/refs.bib": CLEAN, "q/refs.bib": CLEAN})
    _paper(tmp_path, "p", "refs", "\\cite{good2024entry}")
    _paper(tmp_path, "q", "refs", "\\cite{good2024entry}")
    assert dk.lint(dk.load_config(tmp_path)) == 0


def test_the_same_key_in_two_bibliographies_one_document_uses_is_a_duplicate(dk, tmp_path, capsys):
    _tree(tmp_path, {"a.bib": CLEAN, "b.bib": CLEAN})
    _paper(tmp_path, "p", "../a,../b", "\\cite{good2024entry}")
    assert dk.lint(dk.load_config(tmp_path)) == 1
    assert "duplicate key: good2024entry" in _err(capsys)


def test_a_duplicate_inside_one_file_is_still_a_duplicate(dk, tmp_path):
    _tree(tmp_path, {"a.bib": CLEAN + CLEAN})
    _paper(tmp_path, "p", "../a", "\\cite{good2024entry}")
    assert dk.lint(dk.load_config(tmp_path)) == 1


def test_a_key_another_papers_bibliography_defines_is_dangling(dk, tmp_path, capsys):
    _tree(tmp_path, {"a.bib": CLEAN, "b.bib": _entry("other2024entry")})
    _paper(tmp_path, "p", "../a", "\\cite{good2024entry,other2024entry}")
    _paper(tmp_path, "q", "../b", "\\cite{other2024entry}")
    assert dk.lint(dk.load_config(tmp_path)) == 1
    err = _err(capsys)
    assert "dangling citation: \\cite{other2024entry}" in err
    assert "p/main.tex" in err


def test_an_entry_no_document_using_its_bibliography_cites_is_an_orphan(dk, tmp_path, capsys):
    _tree(tmp_path, {"a.bib": CLEAN, "b.bib": _entry("other2024entry")})
    _paper(tmp_path, "p", "../a", "\\cite{good2024entry}")
    _paper(tmp_path, "q", "../b", "\\relax")
    assert dk.lint(dk.load_config(tmp_path)) == 1
    assert "orphan entry: other2024entry" in _err(capsys)


def test_a_document_naming_no_bibliography_uses_all_of_them(dk, tmp_path):
    _tree(tmp_path, {"a.bib": CLEAN, "b.bib": _entry("other2024entry")})
    _tree(tmp_path, {"p/main.tex": DOC + "\\cite{good2024entry,other2024entry}\n"})
    assert dk.lint(dk.load_config(tmp_path)) == 0


def test_addbibresource_names_a_bibliography_and_appends_the_extension(dk, tmp_path):
    _tree(tmp_path, {"a.bib": CLEAN, "b.bib": _entry("other2024entry")})
    _tree(
        tmp_path,
        {
            "p/main.tex": DOC + "\\addbibresource[label=x]{../a.bib}\\input{sec}\n"
            "\\cite{good2024entry}\n",
            "p/sec.tex": "\\addbibresource{../b}\\cite{other2024entry}\n",
        },
    )
    assert dk.lint(dk.load_config(tmp_path)) == 0


def test_a_bibliography_a_document_names_but_is_missing_is_a_finding(dk, tmp_path, capsys):
    _tree(tmp_path, {"a.bib": CLEAN})
    _paper(tmp_path, "p", "nope", "\\cite{good2024entry}")
    assert dk.lint(dk.load_config(tmp_path)) >= 1
    assert "missing bibliography: p/main.tex -> p/nope.bib" in _err(capsys)


def test_a_loose_citation_counts_against_every_bibliography(dk, tmp_path):
    _tree(tmp_path, {"a.bib": CLEAN, "b.bib": _entry("other2024entry")})
    _paper(tmp_path, "p", "../a", "\\cite{good2024entry}")
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "frag.tex").write_text("\\cite{other2024entry}\n")
    assert dk.lint(dk.load_config(tmp_path)) == 0


# --- R7. a missing intake file -----------------------------------------------------------


def test_a_missing_intake_file_is_a_config_error_naming_it(dk, tmp_path, capsys):
    (tmp_path / "references.bib").write_text(CLEAN)
    (tmp_path / "dokimasia.toml").write_text('[intake]\nfile = "related-work/intake.md"\n')
    assert dk.main(["--root", str(tmp_path), "lint"]) == 2
    assert "related-work/intake.md" in _err(capsys)


# --- R8. --require-built counts only documents that need a bibliography ------------------


def test_a_document_that_needs_no_bibliography_may_have_no_bbl(dk, tmp_path):
    _tree(tmp_path, {"m.tex": DOC + "no citations here\n"})
    assert dk.rendered(dk.load_config(tmp_path), require_built=True) == 0


@pytest.mark.parametrize(
    "body", ["\\cite{a}", "\\bibliography{refs}", "\\addbibresource{r.bib}", "\\printbibliography"]
)
def test_a_document_that_uses_a_bibliography_must_be_built(dk, tmp_path, body):
    _tree(tmp_path, {"m.tex": DOC + body + "\n"})
    assert dk.rendered(dk.load_config(tmp_path), require_built=True) == 1


def test_a_subfiles_child_is_not_a_document(dk, tmp_path):
    _tree(
        tmp_path,
        {
            "m.tex": DOC + "\\subfile{ch}\n",
            "ch.tex": "\\documentclass[m.tex]{subfiles}\n\\cite{a}\n",
        },
    )
    cfg = dk.load_config(tmp_path)
    assert [p.name for p in dk.documents(cfg)] == ["m.tex"]


def test_the_bbl_is_found_in_the_configured_outdir(dk, tmp_path):
    _tree(tmp_path, {"p/m.tex": DOC + "\\cite{a}\n", "p/build/m.bbl": "\\bibitem{a}x"})
    (tmp_path / "dokimasia.toml").write_text('outdir = "build"\n')
    assert dk.rendered(dk.load_config(tmp_path), require_built=True) == 0


def test_the_bbl_beside_the_tex_still_wins_without_outdir(dk, tmp_path):
    _tree(tmp_path, {"p/m.tex": DOC + "\\cite{a}\n", "p/build/m.bbl": "\\bibitem{a}x"})
    assert dk.rendered(dk.load_config(tmp_path), require_built=True) == 1


def test_outdir_must_be_a_string(dk, tmp_path):
    (tmp_path / "dokimasia.toml").write_text("outdir = 3\n")
    with pytest.raises(dk.ConfigError, match="outdir must"):
        dk.load_config(tmp_path)


# --- R9. macro definitions and malformed keys --------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        r"\newcommand{\mycite}[1]{\cite{#1}}",
        r"\renewcommand*{\mycite}[2][x]{\citep[#2]{inmacro}}",
        r"\providecommand\mycite[1]{\cite{inmacro}}",
        r"\DeclareRobustCommand{\mycite}{\cite{inmacro}}",
        r"\def\mycite#1{\citep{inmacro}}",
    ],
)
def test_citations_inside_macro_definitions_are_not_citations(dk, text):
    assert dk.cite_keys(text + r"\cite{real}") == {"real"}


@pytest.mark.parametrize("text", [r"\cite{\key}", r"\cite{a b}", r"\cite{#1}", r"\cite{a{b}}"])
def test_keys_with_macro_or_space_characters_are_ignored(dk, text):
    assert dk.cite_keys(text) == set()


# --- R10. entries delimited by parentheses -----------------------------------------------


def test_parenthesised_entries_are_parsed(dk):
    text = "@article(p2020,\n  title = {A (nested) Title},\n  eprint = {2401.00001}\n)\n" + CLEAN
    found = list(dk.entries(text))
    assert [key for _, key, _ in found] == ["p2020", "good2024entry"]
    assert dk.field(found[0][2], "title") == "A (nested) Title"


def test_a_parenthesised_entry_lints_clean(project):
    text = "@article(p2020,\n  title = {T},\n  eprint = {2401.00001}\n)\n"
    assert project(text, tex=r"\cite{p2020}") == 0


# --- R11. accents ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tex",
    [
        r"Gonz{\'a}lez",
        r"Gonz\'alez",
        r"Gonz\'{a}lez",
        "González",
        "Gonza\u0301lez",
    ],
)
def test_accented_forms_normalise_to_the_base_letters(dk, tex):
    assert dk.normalise(tex) == "gonzalez"


@pytest.mark.parametrize(
    ("tex", "plain"),
    [
        (r"M{\"u}ller", "muller"),
        (r"Fran\c{c}ois", "francois"),
        (r"Se{\~n}or", "senor"),
        (r"\v{S}koda", "skoda"),
        (r"Str{\o}m", "strom"),
        (r"Stra\ss e", "strasse"),
        (r"Mar{\'\i}a", "maria"),
        (r"Mar{\'{\i}}a", "maria"),
        (r"{\L}ukasz", "lukasz"),
        ("Łukasz Ørsted", "lukasz orsted"),
        (r"{\AA}ngstr{\"o}m", "angstrom"),
    ],
)
def test_tex_accent_macros_become_their_base_letters(dk, tex, plain):
    assert dk.normalise(tex) == plain


def test_an_accented_author_matches_the_source_spelling(dk):
    assert dk._matches_author(r"Gonz{\'a}lez, Mar{\'\i}a", ["María González"])
    assert dk._matches_author("María González", ["Maria Gonzalez"])
    assert not dk._matches_author(r"Gonz{\'a}lez, Maria", ["Maria Gomez"])


# --- R12. adjacent argument groups, verbatim text ----------------------------------------


def test_groups_after_cites_may_be_separated_by_whitespace(dk):
    assert dk.cite_keys(r"\cites{a}{b} {\em x}") == {"a", "b"}
    assert dk.cite_keys(r"\cites{a} {b}") == {"a", "b"}


@pytest.mark.parametrize(
    "text",
    [
        r"\verb|\cite{x}|",
        r"\verb+\cite{x}+",
        r"\verb*!\cite{x}!",
        "\\begin{verbatim}\\cite{x}\\end{verbatim}",
        "\\begin{verbatim*}\n\\cite{x}\n\\end{verbatim*}",
        "\\begin{lstlisting}[language=TeX]\n\\cite{x}\n\\end{lstlisting}",
        "\\begin{minted}{latex}\n\\cite{x}\n\\end{minted}",
    ],
)
def test_verbatim_text_is_not_a_citation(dk, text):
    assert dk.cite_keys(text + r"\cite{y}") == {"y"}


def test_a_percent_inside_verbatim_does_not_comment_out_the_rest(dk):
    text = "\\begin{verbatim}\n50% done\n\\end{verbatim}\n\\cite{y}\n"
    assert dk.cite_keys(text) == {"y"}


def test_a_commented_verbatim_start_is_still_a_comment(dk):
    assert dk.cite_keys("% \\begin{verbatim}\n\\cite{y}\n") == {"y"}


# --- R13. the docs say what the code does ------------------------------------------------


def test_the_skill_states_the_real_backoff_and_prefix_contract():
    from conftest import DOKIMASIA_SCRIPT

    skill = (DOKIMASIA_SCRIPT.parents[1] / "SKILL.md").read_text()
    assert "every summary and finding line" in skill
    assert "5, 20 and 60" not in skill
    assert "5 then 20" in skill


# --- R14. exclude: names anywhere, paths from the root -----------------------------------


def test_exclude_with_a_slash_is_a_path_prefix_from_the_root(dk, tmp_path):
    _tree(
        tmp_path,
        {
            "a/b/x.tex": "x",
            "a/c/y.tex": "y",
            "z/b/w.tex": "w",
            "a/bb/v.tex": "v",
        },
    )
    (tmp_path / "dokimasia.toml").write_text('exclude = ["a/b"]\n')
    cfg = dk.load_config(tmp_path)
    found = sorted(p.relative_to(tmp_path).as_posix() for p in dk._walk(cfg, ".tex"))
    assert found == ["a/bb/v.tex", "a/c/y.tex", "z/b/w.tex"]


def test_a_bare_exclude_name_matches_a_directory_anywhere(dk, tmp_path):
    _tree(tmp_path, {"b/x.tex": "x", "a/b/y.tex": "y", "a/c/z.tex": "z"})
    (tmp_path / "dokimasia.toml").write_text('exclude = ["b"]\n')
    cfg = dk.load_config(tmp_path)
    found = sorted(p.relative_to(tmp_path).as_posix() for p in dk._walk(cfg, ".tex"))
    assert found == ["a/c/z.tex"]


# --- R15. root discovery ------------------------------------------------------------------


def test_root_discovery_stops_at_the_git_toplevel(dk, tmp_path):
    import subprocess

    (tmp_path / "dokimasia.toml").write_text("")
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    deep = repo / "a"
    deep.mkdir()
    assert dk.load_config(cwd=deep).root == repo.resolve()


def test_an_unparseable_pyproject_without_our_table_is_skipped(dk, tmp_path):
    (tmp_path / "dokimasia.toml").write_text("")
    inner = tmp_path / "inner"
    inner.mkdir()
    (inner / "pyproject.toml").write_text("[project\nbroken")
    assert dk.load_config(cwd=inner).root == tmp_path.resolve()


def test_an_unparseable_pyproject_with_our_table_is_an_error(dk, tmp_path, capsys):
    (tmp_path / "pyproject.toml").write_text("[tool.dokimasia]\nexclude = [\n")
    assert dk.main(["--root", str(tmp_path), "lint"]) == 2
    assert "pyproject.toml" in _err(capsys)


# =========================================================================================
# Second review round.
# =========================================================================================

# --- S1. escaped braces are not structural ------------------------------------------------


@pytest.mark.parametrize(
    "definition",
    [
        r"\newcommand{\lb}{\{}",
        r"\newcommand{\lb}{\left\{ x \right.}",
        r"\newcommand{\rb}{\}}",
        r"\newcommand{\bs}{\\}",
    ],
)
def test_an_escaped_brace_in_a_macro_body_does_not_swallow_later_citations(dk, definition):
    assert dk.cite_keys(definition + r"\cite{a,b} \cite{zz}") == {"a", "b", "zz"}


def test_an_escaped_brace_does_not_hide_a_dangling_citation(dk, tmp_path, capsys):
    _tree(
        tmp_path,
        {
            "a.bib": CLEAN,
            "p/main.tex": DOC + "\\newcommand{\\lb}{\\{}\n\\cite{good2024entry} \\cite{zz}\n"
            "\\bibliography{../a}\n",
        },
    )
    assert dk.lint(dk.load_config(tmp_path)) == 1
    assert "zz" in _err(capsys)


def test_an_escaped_brace_in_a_field_value_does_not_unbalance_the_entry(dk):
    body = "k,\n  title = {An open \\{ brace},\n  year = {2020}\n"
    assert dk.field(body, "title") == "An open \\{ brace"
    assert dk.field(body, "year") == "2020"


# --- S2. a document that needs no bibliography has an empty bibliography scope -----------


def test_a_cover_letter_does_not_join_two_papers_bibliographies(dk, tmp_path):
    _tree(
        tmp_path,
        {
            "a/refs.bib": CLEAN,
            "b/refs.bib": CLEAN,
            "a/main.tex": DOC + "\\cite{good2024entry}\\bibliography{refs}\n",
            "b/main.tex": DOC + "\\cite{good2024entry}\\bibliography{refs}\n",
            "letter/letter.tex": DOC + "Dear editor, thank you.\n",
        },
    )
    assert dk.lint(dk.load_config(tmp_path)) == 0


@pytest.mark.parametrize("body", ["\\cite{good2024entry}", "\\nocite{*}", "\\printbibliography"])
def test_a_document_that_needs_a_bibliography_and_names_none_uses_all(dk, tmp_path, capsys, body):
    _tree(
        tmp_path,
        {
            "a/refs.bib": CLEAN,
            "b/refs.bib": CLEAN,
            "c/main.tex": DOC + body + "\n",
        },
    )
    dk.lint(dk.load_config(tmp_path))
    assert "duplicate key: good2024entry" in _err(capsys)


# --- S3. whitespace between key groups ---------------------------------------------------


def test_a_newline_between_cites_groups_is_allowed(dk):
    assert dk.cite_keys("\\textcites{a}\n  {b}") == {"a", "b"}
    assert dk.cite_keys("\\parencites[x]{a} [y]{b}") == {"a", "b"}


def test_a_text_group_after_cites_is_dropped_by_the_key_filter(dk):
    assert dk.cite_keys(r"\cites{a} {\em x}") == {"a"}


# --- S4. \nocite{*} detection follows the same rules as citations ------------------------


def test_nocite_star_inside_a_macro_definition_covers_nothing(dk, tmp_path):
    _tree(
        tmp_path,
        {
            "references.bib": CLEAN,
            "p/main.tex": DOC + "\\newcommand{\\all}{\\nocite{*}}\n\\bibliography{../references}\n",
        },
    )
    assert dk.lint(dk.load_config(tmp_path)) == 1


def test_a_loose_file_with_nocite_star_does_not_disable_orphans(dk, tmp_path):
    _tree(
        tmp_path,
        {
            "a.bib": CLEAN,
            "b.bib": _entry("other2024entry"),
            "p/main.tex": DOC + "\\cite{good2024entry}\\bibliography{../a}\n",
            "q/main.tex": DOC + "\\cite{other2024entry}\\bibliography{../b}\n",
            "loose/notes.tex": "\\nocite{*}\n",
        },
    )
    (tmp_path / "references.bib").write_text(_entry("orphan2024entry"))
    (tmp_path / "dokimasia.toml").write_text('bib = ["a.bib", "b.bib", "references.bib"]\n')
    assert dk.lint(dk.load_config(tmp_path)) == 1


def test_nocite_star_in_an_included_file_covers_its_documents_bibliography(dk, tmp_path):
    _tree(
        tmp_path,
        {
            "references.bib": CLEAN,
            "p/main.tex": DOC + "\\input{sec}\\bibliography{../references}\n",
            "p/sec.tex": "\\nocite{*}\n",
        },
    )
    assert dk.lint(dk.load_config(tmp_path)) == 0


# --- S5. the cache directory is created, and a failed write is reported ------------------


def test_the_cache_parent_directory_is_created(dk, tmp_path, monkeypatch):
    (tmp_path / "references.bib").write_text(CLEAN)
    (tmp_path / "dokimasia.toml").write_text('cache = "build/cache/dok.json"\n')
    monkeypatch.setattr(dk, "_get", lambda *a, **k: (None, "HTTP 500"))
    monkeypatch.setattr(dk.time, "sleep", lambda *_: None)
    dk.verify(dk.load_config(tmp_path), delay=0)
    assert (tmp_path / "build" / "cache" / "dok.json").exists()


def test_a_cache_that_cannot_be_written_is_reported(dk, tmp_path, monkeypatch, capsys):
    (tmp_path / "references.bib").write_text(CLEAN)
    (tmp_path / "blocker").write_text("a file where a directory is needed")
    (tmp_path / "dokimasia.toml").write_text('cache = "blocker/dok.json"\n')
    monkeypatch.setattr(dk, "_get", lambda *a, **k: (None, "HTTP 500"))
    monkeypatch.setattr(dk.time, "sleep", lambda *_: None)
    dk.verify(dk.load_config(tmp_path), delay=0)
    err = _err(capsys)
    assert "dokimasia: cache not written:" in err
    assert "blocker" in err


# --- S6. outdir wins over a stale .bbl beside the .tex -----------------------------------


def test_outdir_is_preferred_over_a_stale_bbl_beside_the_tex(dk, tmp_path):
    _tree(
        tmp_path,
        {
            "p/m.tex": DOC + "\\cite{a}\n",
            "p/m.bbl": "\\bibitem{stale}x",
            "p/build/m.bbl": "\\bibitem{a}x",
        },
    )
    (tmp_path / "dokimasia.toml").write_text('outdir = "build"\n')
    assert dk.rendered(dk.load_config(tmp_path)) == 0


# --- S7. exclude normalisation and unmatched entries -------------------------------------


def test_exclude_entries_are_normalised(dk, tmp_path):
    _tree(tmp_path, {"a/b/x.tex": "x", "a/c/y.tex": "y"})
    (tmp_path / "dokimasia.toml").write_text('exclude = ["./a/b/"]\n')
    cfg = dk.load_config(tmp_path)
    found = [p.relative_to(tmp_path).as_posix() for p in dk._walk(cfg, ".tex")]
    assert found == ["a/c/y.tex"]


def test_an_exclude_that_matches_nothing_is_named(dk, tmp_path, capsys):
    (tmp_path / "references.bib").write_text(CLEAN)
    (tmp_path / "p.tex").write_text(DOC + "\\cite{good2024entry}\n")
    (tmp_path / "dokimasia.toml").write_text('exclude = ["nope", "also/nope"]\n')
    assert dk.lint(dk.load_config(tmp_path)) == 0
    out = capsys.readouterr().out
    assert out.count("dokimasia: exclude matched nothing: nope") == 1
    assert "dokimasia: exclude matched nothing: also/nope" in out


def test_an_exclude_that_matches_is_not_reported(dk, tmp_path, capsys):
    (tmp_path / "references.bib").write_text(CLEAN)
    (tmp_path / "p.tex").write_text(DOC + "\\cite{good2024entry}\n")
    (tmp_path / "vendor" / "deep").mkdir(parents=True)
    (tmp_path / "dokimasia.toml").write_text('exclude = ["deep", "vendor/deep"]\n')
    dk.lint(dk.load_config(tmp_path))
    assert "matched nothing" not in capsys.readouterr().out


# --- S8. canonical decomposition, ligatures ----------------------------------------------


def test_a_tex_ell_matches_the_unicode_script_l(dk):
    assert dk.normalise(r"$\ell_2$ regularisation") == dk.normalise("\u21132 regularisation")


def test_compatibility_forms_are_not_folded_into_letters(dk):
    assert dk.normalise("\u2113") == ""
    assert dk.normalise("x²") == "x"


@pytest.mark.parametrize(
    ("text", "plain"),
    [
        ("ﬁne ﬂow", "fine flow"),
        ("o\ufb00er", "offer"),
        ("o\ufb03ce", "office"),
        ("ba\ufb04e", "baffle"),
    ],
)
def test_latin_ligatures_are_expanded(dk, text, plain):
    assert dk.normalise(text) == plain


# --- S9. titles with no Latin letters ----------------------------------------------------


def test_a_matching_cjk_title_is_not_drift(dk):
    assert dk.titles_match("联邦学习综述", "联邦学习综述")
    assert dk.titles_match("联邦学习 综述", "联邦学习  综述")


def test_a_different_cjk_title_is_drift(dk):
    assert not dk.titles_match("联邦学习综述", "联邦学习研究")


def test_a_greek_title_is_compared_by_its_text(dk):
    assert dk.titles_match("Δοκιμασία", "δοκιμασία")
    assert not dk.titles_match("Δοκιμασία", "Φύλαξ")


def test_an_empty_source_title_never_matches_by_prefix(dk):
    assert not dk.titles_match("Any claimed title", "")


def test_a_cjk_title_that_differs_reports_drift_in_verify(dk, tmp_path, monkeypatch, capsys):
    bib = CLEAN.replace("A Perfectly Ordinary Title", "联邦学习综述")
    (tmp_path / "references.bib").write_text(bib)
    feed = (
        "<feed><entry><title>联邦学习研究</title><published>2024-01-01</published>"
        "<author><name>Jane Doe</name></author></entry></feed>"
    )
    monkeypatch.setattr(dk, "_get", lambda *a, **k: (feed, ""))
    monkeypatch.setattr(dk.time, "sleep", lambda *_: None)
    assert dk.main(["--root", str(tmp_path), "verify"]) == 1
    assert "title drift" in capsys.readouterr().err


# --- low: orphan names its file, \subimport* ---------------------------------------------


def test_an_orphan_names_the_bibliography_file_it_lives_in(dk, tmp_path, capsys):
    _tree(tmp_path, {"refs/a.bib": CLEAN})
    _paper(tmp_path, "p", "../refs/a", "\\relax")
    dk.lint(dk.load_config(tmp_path))
    err = _err(capsys)
    assert "orphan entry: good2024entry" in err
    assert "refs/a.bib" in err


def test_a_starred_import_is_followed(dk, tmp_path):
    _tree(
        tmp_path,
        {
            "m.tex": DOC + "\\input{a/inc}\n",
            "a/inc.tex": "\\subimport*{d}{x}\n",
            "a/d/x.tex": "\\cite{right}\n",
        },
    )
    assert dk.document_cites(tmp_path / "m.tex") == {"right"}


# --- hand-written thebibliography (#113) -------------------------------------------------

#: An IEEE-style hand-written list: one arXiv preprint, one journal article with a DOI, and
#: one with neither, which is how most printed styles look.
HAND = r"""\documentclass{article}
\begin{document}
Text \cite{doe2024,roe2019} and \cite{poe2015}.
\begin{thebibliography}{3}
\bibitem{doe2024}
J.~Doe, ``A perfectly ordinary title,'' arXiv:2401.00001, 2024.

\bibitem{roe2019}
R.~Roe and S.~Sun, ``Checking the {LLM}s that check,'' \emph{Empirical Softw. Eng.},
vol.~24, pp.~1--9, 2019, doi: 10.1007/s10664-018-9653-2.

\bibitem{poe2015}
E.~Poe, ``A raven,'' \emph{PeerJ}, vol.~3, 2015.
\end{thebibliography}
\end{document}
"""

ARXIV_FEED = (
    "<feed><entry><title>A Perfectly Ordinary Title</title><published>2024-01-02</published>"
    "<author><name>Jane Doe</name></author></entry></feed>"
)
CROSSREF = json.dumps(
    {
        "message": {
            "title": ["Checking the LLMs that check"],
            "author": [{"given": "Rita", "family": "Roe"}],
            "issued": {"date-parts": [[2018, 11]]},
            "published-print": {"date-parts": [[2019, 2]]},
        }
    }
)


def _hand(tmp_path, tex=HAND, name="paper.tex"):
    (tmp_path / name).write_text(tex)
    return tmp_path / name


def _answer(dk, monkeypatch, feed=ARXIV_FEED, crossref=CROSSREF):
    """Serve arXiv and Crossref from fixtures; the lookup never touches the network."""

    def get(url, *a, **k):
        return (feed, "") if "arxiv" in url else (crossref, "")

    monkeypatch.setattr(dk, "_get", get)
    monkeypatch.setattr(dk.time, "sleep", lambda *_: None)


def test_a_project_with_only_a_hand_written_list_is_not_a_config_error(dk, tmp_path, capsys):
    _hand(tmp_path)
    assert dk.main(["--root", str(tmp_path), "lint"]) == 0
    out = capsys.readouterr().out
    assert "3 entries (3 hand-written)" in out


def test_no_bib_and_no_hand_written_list_is_still_a_config_error(dk, tmp_path, capsys):
    (tmp_path / "paper.tex").write_text(DOC + "\\cite{x}\n")
    assert dk.main(["--root", str(tmp_path), "lint"]) == 2
    assert "no document has a hand-written thebibliography" in capsys.readouterr().err


def test_bibitems_reads_keys_and_the_text_up_to_the_next_item(dk, tmp_path):
    items = dk.bibitems(dk.strip_comments(HAND), tmp_path / "paper.tex")
    assert [i.key for i in items] == ["doe2024", "roe2019", "poe2015"]
    assert items[1].text.startswith("R.~Roe and S.~Sun,")
    assert items[1].text.endswith("10.1007/s10664-018-9653-2.")
    assert "\\bibitem" not in items[0].text


def test_a_natbib_label_with_braces_and_brackets_is_skipped(dk, tmp_path):
    tex = (
        "\\begin{thebibliography}{1}"
        "\\bibitem[{Doe et~al.(2024)}]{doe2024} J. Doe."
        "\\end{thebibliography}"
    )
    assert [i.key for i in dk.bibitems(tex, tmp_path)] == ["doe2024"]


def test_a_commented_bibitem_is_not_an_entry(dk, tmp_path, capsys):
    _hand(tmp_path, HAND.replace("\\bibitem{poe2015}", "% \\bibitem{poe2015}"))
    dk.lint(dk.load_config(tmp_path))
    assert "dangling citation: \\cite{poe2015}" in _err(capsys)


def test_a_duplicate_bibitem_is_caught(dk, tmp_path, capsys):
    _hand(tmp_path, HAND.replace("\\bibitem{poe2015}", "\\bibitem{doe2024}"))
    dk.lint(dk.load_config(tmp_path))
    assert "duplicate \\bibitem: doe2024 appears 2 times (in paper.tex)" in _err(capsys)


def test_a_citation_with_no_bibitem_is_dangling(dk, tmp_path, capsys):
    _hand(tmp_path, HAND.replace("\\cite{poe2015}", "\\cite{poe2015,ghost2020}"))
    assert dk.lint(dk.load_config(tmp_path)) == 1
    assert "dangling citation: \\cite{ghost2020} has no entry (cited by paper.tex)" in _err(capsys)


def test_a_printed_item_nothing_cites_is_an_orphan(dk, tmp_path, capsys):
    """A hand-written list prints every item, cited or not."""
    _hand(tmp_path, HAND.replace(" and \\cite{poe2015}", ""))
    assert dk.lint(dk.load_config(tmp_path)) == 1
    assert "orphan \\bibitem: poe2015 is printed in paper.tex" in _err(capsys)


def test_nocite_star_does_not_cover_a_hand_written_orphan(dk, tmp_path, capsys):
    _hand(tmp_path, HAND.replace(" and \\cite{poe2015}", "\\nocite{*}"))
    assert dk.lint(dk.load_config(tmp_path)) == 1


def test_hand_written_orphans_follow_the_orphans_switch(dk, tmp_path):
    _hand(tmp_path, HAND.replace(" and \\cite{poe2015}", ""))
    (tmp_path / "dokimasia.toml").write_text("orphans = false\n")
    assert dk.lint(dk.load_config(tmp_path)) == 0


def test_a_hand_written_document_does_not_draw_on_a_bib(dk, tmp_path, capsys):
    """Its citations must be in its own list. A .bib elsewhere in the project, used by
    another paper, neither satisfies them nor gains orphans from them."""
    _tree(tmp_path, {"q/refs.bib": _entry("ghost2020")})
    _paper(tmp_path, "q", "refs", "\\cite{ghost2020}")
    _hand(tmp_path, HAND.replace("\\cite{poe2015}", "\\cite{poe2015,ghost2020}"))
    assert dk.lint(dk.load_config(tmp_path)) == 1
    assert "\\cite{ghost2020} has no entry (cited by paper.tex)" in _err(capsys)


def test_an_entry_with_no_printed_identifier_is_counted_not_a_finding(dk, tmp_path, capsys):
    _hand(tmp_path)
    assert dk.lint(dk.load_config(tmp_path)) == 0
    assert "info: 1 of 3 hand-written entries print no arXiv id or DOI" in capsys.readouterr().out


def test_an_exemption_may_name_a_hand_written_entry(dk, tmp_path):
    _hand(tmp_path)
    (tmp_path / "dokimasia.toml").write_text('[exempt.title]\npoe2015 = "the source is wrong"\n')
    assert dk.lint(dk.load_config(tmp_path)) == 0


@pytest.mark.parametrize(
    ("text", "eprint", "doi"),
    [
        ("arXiv:2607.22693, 2026.", "2607.22693", None),
        ("arXiv preprint arXiv:2607.22693v2", "2607.22693", None),
        ("\\url{https://arxiv.org/abs/2607.22693}", "2607.22693", None),
        ("arXiv:hep-th/9901001", "hep-th/9901001", None),
        ("doi: 10.7717/peerj.1364.", None, "10.7717/peerj.1364"),
        ("\\url{https://doi.org/10.1109/C-M.1978.218136}", None, "10.1109/C-M.1978.218136"),
        ("doi: 10.1000/a\\_b.", None, "10.1000/a_b"),
        ("(https://doi.org/10.1000/xyz)", None, "10.1000/xyz"),
        # arXiv's DataCite DOI resolves through the arXiv id, not through Crossref.
        ("doi: 10.48550/arXiv.2607.22693", "2607.22693", None),
        ("vol. 13, 2023.", None, None),
    ],
)
def test_inline_ids_finds_printed_identifiers(dk, text, eprint, doi):
    assert dk.inline_ids(text) == (eprint, doi)


def test_rendered_checks_a_hand_written_document_instead_of_calling_it_unbuilt(
    dk, tmp_path, capsys
):
    _hand(tmp_path)
    assert dk.main(["--root", str(tmp_path), "--require-built", "rendered"]) == 0
    out = capsys.readouterr().out
    assert "3/3 cited keys rendered (hand-written thebibliography)" in out
    assert "not built" not in out.replace("0 not built", "")


def test_rendered_catches_a_citation_with_no_bibitem(dk, tmp_path, capsys):
    _hand(tmp_path, HAND.replace("\\cite{poe2015}", "\\cite{poe2015,ghost2020}"))
    assert dk.rendered(dk.load_config(tmp_path)) == 1
    assert "\\cite{ghost2020} did not render" in _err(capsys)


def test_rendered_reads_a_bbl_pasted_in_through_input(dk, tmp_path, capsys):
    """arXiv submissions often paste the .bbl into the source; it is then the list."""
    body = HAND.split("\\begin{thebibliography}")[1].split("\\end{thebibliography}")[0]
    _tree(
        tmp_path,
        {
            "main.tex": DOC + "\\cite{doe2024}\n\\input{main.bbl}\n",
            "main.bbl": "\\begin{thebibliography}" + body + "\\end{thebibliography}\n",
        },
    )
    assert dk.rendered(dk.load_config(tmp_path)) == 0
    # It is build output beside the .tex, so the ordinary .bbl check runs, as before.
    out = capsys.readouterr().out
    assert "1/1 cited keys rendered\n" in out


def test_verify_resolves_printed_identifiers_and_names_the_rest(dk, tmp_path, monkeypatch, capsys):
    _hand(tmp_path)
    _answer(dk, monkeypatch)
    assert dk.verify(dk.load_config(tmp_path), delay=0) == 0
    out = capsys.readouterr().out
    assert "verified 2, exempt 0, unresolved 0, unverifiable 1, uncompared 0, drift 0" in out
    assert "poe2015 (paper.tex)" in out


def test_a_printed_title_that_differs_from_the_source_is_drift(dk, tmp_path, monkeypatch, capsys):
    _hand(tmp_path, HAND.replace("A perfectly ordinary title", "A perfectly ordinary tale"))
    _answer(dk, monkeypatch)
    assert dk.verify(dk.load_config(tmp_path), delay=0) == 1
    assert "title drift: doe2024 (paper.tex)" in _err(capsys)


def test_a_title_is_matched_as_whole_words_not_as_a_substring(dk, tmp_path):
    record = {"title": "Ordinary title", "authors": ["Jane Doe"], "source": "arxiv"}
    text = "J. Doe, ``Extraordinary titles,'' arXiv:2401.00001."
    cfg = dk.Config(root=tmp_path)
    assert [f[0] for f in dk._printed_findings(cfg, "k", text, record)] == ["title"]


def test_the_first_author_must_be_printed_before_the_title(dk, tmp_path, monkeypatch, capsys):
    _hand(tmp_path, HAND.replace("J.~Doe,", "J.~Smith,"))
    _answer(dk, monkeypatch)
    assert dk.verify(dk.load_config(tmp_path), delay=0) == 1
    assert "first author drift: doe2024 (paper.tex)" in _err(capsys)


def test_a_preprint_year_that_differs_is_drift(dk, tmp_path, monkeypatch, capsys):
    _hand(tmp_path, HAND.replace("arXiv:2401.00001, 2024", "arXiv:2401.00001, 2023"))
    _answer(dk, monkeypatch)
    assert dk.verify(dk.load_config(tmp_path), delay=0) == 1
    assert "year drift: doe2024 (paper.tex)" in _err(capsys)


def test_a_venue_paper_is_not_compared_with_its_arxiv_year(dk, tmp_path, monkeypatch):
    """A NeurIPS 2023 paper posted to arXiv in 2024 is correctly dated 2023."""
    venue = HAND.replace(
        "arXiv:2401.00001, 2024.", "in \\emph{Proc. NeurIPS}, 2023. arXiv:2401.00001."
    )
    _hand(tmp_path, venue)
    _answer(dk, monkeypatch)
    assert dk.verify(dk.load_config(tmp_path), delay=0) == 0


def test_a_print_year_or_an_issued_year_both_satisfy_crossref(dk, tmp_path, monkeypatch):
    for year in ("2018", "2019"):
        _hand(tmp_path, HAND.replace("pp.~1--9, 2019", f"pp.~1--9, {year}"))
        _answer(dk, monkeypatch)
        assert dk.verify(dk.load_config(tmp_path), delay=0) == 0


def test_a_crossref_year_printed_nowhere_is_drift(dk, tmp_path, monkeypatch, capsys):
    _hand(tmp_path, HAND.replace("pp.~1--9, 2019", "pp.~1--9, 2021"))
    _answer(dk, monkeypatch)
    assert dk.verify(dk.load_config(tmp_path), delay=0) == 1
    assert "year drift: roe2019 (paper.tex)" in _err(capsys)


def test_a_record_exemption_skips_author_and_year_for_a_printed_entry(
    dk, tmp_path, monkeypatch, capsys
):
    _hand(tmp_path, HAND.replace("J.~Doe,", "J.~Smith,"))
    (tmp_path / "dokimasia.toml").write_text('[exempt.record]\ndoe2024 = "renamed author"\n')
    _answer(dk, monkeypatch)
    assert dk.verify(dk.load_config(tmp_path), delay=0) == 0
    assert "exempt: doe2024 (paper.tex) -- renamed author" in capsys.readouterr().out


def test_a_list_two_documents_share_is_verified_once(dk, tmp_path, monkeypatch, capsys):
    body = HAND.split("\\begin{document}")[1].split("\\end{document}")[0]
    _tree(
        tmp_path,
        {
            "refs.tex": body,
            "a.tex": DOC + "\\input{refs}\n",
            "b.tex": DOC + "\\input{refs}\n",
        },
    )
    _answer(dk, monkeypatch)
    dk.verify(dk.load_config(tmp_path), delay=0)
    assert "verified 2, exempt 0, unresolved 0, unverifiable 1" in capsys.readouterr().out


def test_a_bib_and_a_hand_written_list_are_verified_together(dk, tmp_path, monkeypatch, capsys):
    (tmp_path / "references.bib").write_text(CLEAN)
    _hand(tmp_path)
    _answer(dk, monkeypatch)
    dk.verify(dk.load_config(tmp_path), delay=0)
    # good2024entry and doe2024 share one arXiv id; the second is a cache hit.
    assert (
        "verified 3, exempt 0, unresolved 0, unverifiable 1, uncompared 0, drift 0 (1 from cache)"
        in (capsys.readouterr().out)
    )


# --- #113 review round: every test below failed against the first cut of #114 -----------


def test_an_empty_block_in_a_bib_project_changes_nothing(dk, tmp_path):
    (tmp_path / "references.bib").write_text(CLEAN)
    (tmp_path / "paper.tex").write_text(
        DOC + "\\cite{good2024entry}\\bibliography{references}\n"
        "\\begin{thebibliography}{9}\\end{thebibliography}\n"
    )
    assert dk.lint(dk.load_config(tmp_path)) == 0


def test_a_list_inside_a_newenvironment_template_is_not_a_list(dk, tmp_path, capsys):
    (tmp_path / "references.bib").write_text(CLEAN)
    (tmp_path / "paper.tex").write_text(
        "\\newenvironment{refs}{\\begin{thebibliography}{99}}{\\end{thebibliography}}\n"
        + DOC
        + "\\cite{good2024entry}\n"
    )
    assert dk.lint(dk.load_config(tmp_path)) == 0
    assert "1 entries, 0 staged unread, 0 finding(s)" in capsys.readouterr().out


def test_items_kept_in_an_input_file_belong_to_the_block_that_inputs_them(dk, tmp_path):
    items = HAND.split("\\begin{thebibliography}{3}")[1].split("\\end{thebibliography}")[0]
    _tree(
        tmp_path,
        {
            "paper.tex": DOC + "\\cite{doe2024,roe2019,poe2015}\n"
            "\\begin{thebibliography}{3}\\input{items}\\end{thebibliography}\n",
            "items.tex": items,
        },
    )
    cfg = dk.load_config(tmp_path)
    assert dk.lint(cfg) == 0
    assert dk.rendered(cfg) == 0


def test_loose_bibitems_outside_a_hand_written_document_are_not_entries(dk, tmp_path):
    (tmp_path / "references.bib").write_text(CLEAN)
    (tmp_path / "paper.tex").write_text(
        DOC + "\\cite{good2024entry}\\bibliography{references}\n\\bibitem{stray} Stray.\n"
    )
    assert dk.lint(dk.load_config(tmp_path)) == 0


def test_a_pasted_bbl_does_not_orphan_the_bib_it_came_from(dk, tmp_path):
    """arXiv-prep layout: refs.bib plus `\\input{main.bbl}`; main lints this clean."""
    _tree(
        tmp_path,
        {
            "refs.bib": CLEAN,
            "main.tex": DOC + "\\cite{good2024entry}\n\\input{main.bbl}\n",
            "main.bbl": "\\begin{thebibliography}{1}\\bibitem{good2024entry} J. Doe."
            "\\end{thebibliography}\n",
        },
    )
    assert dk.lint(dk.load_config(tmp_path)) == 0


def test_a_pasted_bbl_under_another_stem_renders(dk, tmp_path, capsys):
    _tree(
        tmp_path,
        {
            "refs.bib": CLEAN,
            "main.tex": DOC + "\\cite{good2024entry}\n\\input{final.bbl}\n",
            "final.bbl": "\\begin{thebibliography}{1}\\bibitem{good2024entry} J. Doe."
            "\\end{thebibliography}\n",
        },
    )
    assert dk.rendered(dk.load_config(tmp_path)) == 0
    assert "1/1 cited keys rendered (pasted .bbl)" in capsys.readouterr().out


def test_a_list_parked_in_iffalse_is_not_a_list(dk, tmp_path, capsys):
    _tree(
        tmp_path,
        {
            "refs.bib": CLEAN,
            "main.tex": DOC + "\\cite{good2024entry}\\bibliography{refs}\n\\iffalse\n"
            "\\begin{thebibliography}{1}\\bibitem{old} Old.\\end{thebibliography}\n\\fi\n",
            "main.bbl": "\\bibitem{good2024entry} J. Doe.\n",
        },
    )
    cfg = dk.load_config(tmp_path)
    assert dk.lint(cfg) == 0
    assert dk.rendered(cfg) == 0
    assert "1/1 cited keys rendered\n" in capsys.readouterr().out


def test_a_bibtex_document_does_not_read_a_thebibliography_beside_it(dk, tmp_path, capsys):
    """As on main: a document that names a .bib is checked against its .bbl alone."""
    _tree(
        tmp_path,
        {
            "refs.bib": CLEAN,
            "main.tex": DOC + "\\cite{good2024entry,data2020}\\bibliography{refs}\n"
            "\\begin{thebibliography}{1}\\bibitem{data2020} A dataset.\\end{thebibliography}\n",
            "main.bbl": "\\bibitem{good2024entry} J. Doe.\n",
        },
    )
    cfg = dk.load_config(tmp_path)
    assert dk.rendered(cfg) == 1
    assert "1/2 cited keys rendered\n" in capsys.readouterr().out


def test_a_bib_only_project_keeps_its_unverifiable_wording(dk, tmp_path, monkeypatch, capsys):
    (tmp_path / "references.bib").write_text(CLEAN.replace("eprint", "url"))
    _answer(dk, monkeypatch)
    dk.verify(dk.load_config(tmp_path), delay=0)
    assert "unverifiable -- no eprint or doi, so verify can never check these:" in (
        capsys.readouterr().out
    )


def test_a_longer_quoted_title_around_the_source_title_is_drift(dk):
    """A real DOI under an invented, longer title: the typical fabricated reference."""
    record = {"title": "Deep learning", "authors": ["Yann LeCun"], "source": "crossref"}
    printed = "Y. LeCun, ``Applications of deep learning in medicine,'' \\emph{Nature}, 2015."
    found = dk._printed_findings(dk.Config(root=Path(".")), "k", printed, record)
    assert [f[0] for f in found] == ["title"]


@pytest.mark.parametrize(
    "printed",
    [
        "Y. LeCun. Applications of deep learning in medicine. \\emph{Nature}, 2015.",
        "Y. LeCun. Deep learning: a review. \\emph{Nature}, 2015.",
        "Y. LeCun. 2015. \\emph{Deep Learning}. Nature.",
    ],
)
def test_an_unquoted_title_is_never_compared(dk, printed):
    """Neither verified nor drift: the printed text does not say which part is the title."""
    record = {"title": "Deep learning", "authors": ["Yann LeCun"], "source": "crossref"}
    assert dk._printed_findings(dk.Config(root=Path(".")), "k", printed, record) is None


def test_the_quoted_source_title_is_not_drift(dk):
    record = {"title": "Deep learning", "authors": ["Yann LeCun"], "source": "crossref"}
    printed = "Y. LeCun, ``Deep learning,'' \\emph{Nature}, 2015."
    assert dk._printed_findings(dk.Config(root=Path(".")), "k", printed, record) == []


def test_a_tex_umlaut_does_not_open_a_quoted_title(dk):
    record = {"title": "Deep learning", "authors": ["Kurt M\u00fcller"], "source": "crossref"}
    printed = 'K. M\\"uller and A. B\\"ohm. Deep learning. Nature, 2015.'
    assert dk._printed_findings(dk.Config(root=Path(".")), "k", printed, record) is None


def test_another_source_author_printed_first_is_drift(dk):
    record = {
        "title": "Deep learning",
        "authors": ["Yann LeCun", "Yoshua Bengio", "Geoffrey Hinton"],
        "source": "crossref",
    }
    printed = "G. Hinton, Y. Bengio, and Y. LeCun, ``Deep learning,'' Nature, 2015."
    found = dk._printed_findings(dk.Config(root=Path(".")), "k", printed, record)
    assert [f[0] for f in found] == ["first author"]


def test_a_generational_suffix_on_the_source_is_not_drift(dk):
    record = {"title": "Deep learning", "authors": ["Jane Doe Jr."], "source": "crossref"}
    printed = "J. Doe, ``Deep learning,'' Nature, 2015."
    assert dk._printed_findings(dk.Config(root=Path(".")), "k", printed, record) == []


def test_preprint_wording_alone_does_not_compare_a_venue_paper_with_arxiv(dk):
    record = {"title": "Title here", "authors": ["John Smith"], "year": 2020, "source": "arxiv"}
    printed = "J. Smith, ``Title here,'' in NeurIPS, 2021. arXiv preprint arXiv:2001.01234."
    assert dk._printed_findings(dk.Config(root=Path(".")), "k", printed, record) == []


def test_a_year_after_a_classified_arxiv_id_is_compared(dk):
    record = {"title": "Title here", "authors": ["John Smith"], "year": 2024, "source": "arxiv"}
    printed = "J. Smith, ``Title here,'' arXiv:2401.00001 [cs.LG], 2023."
    found = dk._printed_findings(dk.Config(root=Path(".")), "k", printed, record)
    assert [f[0] for f in found] == ["year"]


@pytest.mark.parametrize(
    ("text", "eprint", "doi"),
    [
        ("doi:10.1145/3442188.3445922\\url{x}", None, "10.1145/3442188.3445922"),
        ("Y. Smith. Foo. CoRR, abs/2001.01234, 2020.", "2001.01234", None),
        ("\\showeprint[arxiv]{2001.01234}", "2001.01234", None),
        (
            "doi: 10.1002/(SICI)1097-4571(199806)49:8<693::AID-ASI4>3.0.CO;2-0.",
            None,
            "10.1002/(SICI)1097-4571(199806)49:8<693::AID-ASI4>3.0.CO;2-0",
        ),
        ("``Title,'' doi:10.1000/xyz''", None, "10.1000/xyz"),
    ],
)
def test_inline_ids_stop_at_tex_and_keep_sici_dois(dk, text, eprint, doi):
    assert dk.inline_ids(text) == (eprint, doi)


def test_each_copy_of_a_duplicated_key_is_resolved(dk, tmp_path, monkeypatch, capsys):
    """lint reports the duplicate; verify must still look up the second copy's DOI."""
    _hand(
        tmp_path,
        HAND.replace("E.~Poe,", "E.~Poe, doi: 10.9999/fake,").replace(
            "\\bibitem{poe2015}", "\\bibitem{roe2019}"
        ),
    )
    seen = []

    def get(url, *a, **k):
        seen.append(url)
        return (ARXIV_FEED, "") if "arxiv" in url else (CROSSREF, "")

    monkeypatch.setattr(dk, "_get", get)
    monkeypatch.setattr(dk.time, "sleep", lambda *_: None)
    dk.verify(dk.load_config(tmp_path), delay=0)
    assert any("10.9999" in u for u in seen)


def test_a_broken_symlink_does_not_crash_verify(dk, tmp_path, monkeypatch):
    (tmp_path / "references.bib").write_text(CLEAN)
    (tmp_path / "gone.tex").symlink_to(tmp_path / "missing.tex")
    _answer(dk, monkeypatch)
    assert dk.verify(dk.load_config(tmp_path), delay=0) == 0


# --- #113 later review rounds ------------------------------------------------------------

VASWANI = {
    "title": "Attention is all you need",
    "authors": ["Ashish Vaswani", "Noam Shazeer"],
    "year": 2017,
    "source": "arxiv",
}


def _compare(dk, printed, record=None):
    found = dk._printed_findings(dk.Config(root=Path(".")), "k", printed, record or VASWANI)
    return None if found is None else [f[0] for f in found]


@pytest.mark.parametrize(
    "printed",
    [
        "A.~Vaswani and N.~Shazeer, ``Attention is all you need,'' arXiv:1706.03762, 2017.",
        "A.~Vaswani \\emph{et~al.}, ``Attention is all you need,'' 2017.",
        'Vaswani, Ashish, and Noam Shazeer. 2017. "Attention Is All You Need." arXiv.',
        'Vaswani, Ashish, et al. "Attention Is All You Need." \\emph{arXiv}, 2017.',
        "A. Vaswani, ``Attention is all you need: a subtitle Crossref drops,'' 2017.",
    ],
)
def test_correct_quoted_entries_are_clean(dk, printed):
    assert _compare(dk, printed) == []


@pytest.mark.parametrize(
    "printed",
    [
        "Vaswani, A., Shazeer, N.: Attention is all you need. arXiv:1706.03762 (2017)",
        "Ashish Vaswani and Noam Shazeer. 2017. Attention is all you need. arXiv:1706.03762.",
        "Vaswani, A. and Shazeer, N. (2017) Attention is all you need. arXiv:1706.03762.",
        "Vaswani A and Shazeer N 2017 Attention is all you need arXiv:1706.03762",
        "A.~Vaswani, N.~Shazeer, Phys. Rev. \\textbf{47}, 777 (2017).",
        # Fabrications in unquoted styles are reported uncompared, never verified.
        "Doe, J.: Fabricated chapter. In: Attention is all you need, pp. 1--9 (2017)",
        "J. Doe. Fabricated method. \\newblock In {\\em Attention is all you need}, 2017.",
    ],
)
def test_unquoted_styles_are_uncompared(dk, printed):
    assert _compare(dk, printed) is None


@pytest.mark.parametrize(
    "printed",
    [
        # A comma inside an invented title used to expose the real one.
        "A.~Vaswani, ``Rethinking, attention is all you need, and more,'' 2017.",
        "A.~Vaswani, ``Rethinking transformers: Attention is all you need,'' 2017.",
        # A chapter borrowing its volume's DOI: the quoted title is the chapter's.
        "J.~Doe, ``Fabricated chapter,'' in \\emph{Attention is all you need}, 2017.",
        "J.~Doe, ``Fabricated chapter,'' in J. Smith (Ed.), ``Attention is all you need,'' 2017.",
    ],
)
def test_a_fabricated_quoted_title_is_drift(dk, printed):
    assert "title" in _compare(dk, printed)


@pytest.mark.parametrize(
    "printed",
    [
        "J.~Doe, A.~Vaswani, and N.~Shazeer, ``Attention is all you need,'' 2017.",
        "Yann Smith and Ashish Vaswani, ``Attention is all you need,'' 2017.",
        "J. de Doe, ``Attention is all you need,'' 2017.",
    ],
)
def test_a_wrong_first_author_is_drift(dk, printed):
    assert _compare(dk, printed) == ["first author"]


@pytest.mark.parametrize(
    ("printed", "first"),
    [
        ("Li Wang and Wei Li, ``Deep learning,'' Nature, 2020.", "Li Wang"),
        ("Yann LeCun, ``Deep learning,'' Nature, 2020.", "Y. LeCun"),
        ("{World Health Organization}, ``Deep learning,'' 2020.", "World Health Organization"),
    ],
)
def test_first_authors_the_bib_rule_accepts_are_accepted(dk, printed, first):
    record = {"title": "Deep learning", "authors": [first, "Wei Li"], "source": "crossref"}
    assert _compare(dk, printed, record) == []


@pytest.mark.parametrize(
    "printed",
    [
        "Doe, J. (2020). The ``attention'' trap in reading. \\emph{Mind}, 1.",
        'Doe, J. (2020). The "attention" trap in reading. Mind, 1.',
    ],
)
def test_a_quoted_word_inside_an_unquoted_title_is_not_the_title(dk, printed):
    record = {
        "title": "The attention trap in reading",
        "authors": ["Jane Doe"],
        "source": "crossref",
    }
    assert _compare(dk, printed, record) is None


def test_nested_quotes_inside_a_title_are_one_title(dk):
    record = {"title": "On robust estimation", "authors": ["Jane Doe"], "source": "crossref"}
    assert _compare(dk, "J.~Doe, ``On ``robust'' estimation,'' 2020.", record) == []


def test_a_page_range_is_not_a_claimed_year(dk):
    record = {
        "title": "Deep learning",
        "authors": ["Yann LeCun"],
        "year": 2015,
        "source": "crossref",
    }
    assert _compare(dk, "Y. LeCun, ``Deep learning,'' Nature, pp. 2016--2020, 2015.", record) == []


def test_verify_names_uncompared_entries_and_exits_clean(dk, tmp_path, monkeypatch, capsys):
    tex = HAND.replace(
        "R.~Roe and S.~Sun, ``Checking the {LLM}s that check,'' \\emph{Empirical Softw. Eng.},",
        "R.~Roe and S.~Sun, \\emph{Empirical Softw. Eng.},",
    )
    _hand(tmp_path, tex)
    _answer(dk, monkeypatch)
    assert dk.verify(dk.load_config(tmp_path), delay=0) == 0
    out = capsys.readouterr().out
    assert "verified 1, exempt 0, unresolved 0, unverifiable 1, uncompared 1, drift 0" in out
    assert "uncompared -- the identifier resolved" in out
    assert "roe2019 (paper.tex)" in out


def test_a_stale_bbl_beside_a_hand_written_document_is_ignored(dk, tmp_path, capsys):
    _hand(tmp_path, HAND.replace("\\cite{poe2015}", "\\cite{poe2015,gone2020}"))
    (tmp_path / "paper.bbl").write_text("\\bibitem{gone2020} Old build.\n")
    assert dk.rendered(dk.load_config(tmp_path)) == 1
    assert "\\cite{gone2020} did not render" in _err(capsys)


@pytest.mark.parametrize(
    "text", ["{\\em CoRR}, abs/1810.04805, 2018.", "\\emph{CoRR}, vol. abs/1810.04805, 2018."]
)
def test_dblp_corr_ids_in_braces_are_read(dk, text):
    assert dk.inline_ids(text) == ("1810.04805", None)


def test_let_iffalse_does_not_hide_the_list(dk, tmp_path):
    """A conditional defined in the preamble and closed after the list must not swallow it."""
    tex = HAND.replace("\\end{document}", "\\ifdraft draft\\fi\n\\end{document}")
    _hand(tmp_path, "\\let\\ifdraft\\iffalse\n" + tex)
    assert dk.lint(dk.load_config(tmp_path)) == 0


def test_a_list_inside_an_xparse_environment_definition_is_not_a_list(dk, tmp_path):
    (tmp_path / "references.bib").write_text(CLEAN)
    (tmp_path / "paper.tex").write_text(
        "\\NewDocumentEnvironment{refs}{}{\\begin{thebibliography}{9}}{\\end{thebibliography}}\n"
        + DOC
        + "\\cite{good2024entry}\n"
    )
    assert dk.lint(dk.load_config(tmp_path)) == 0


def test_a_project_with_only_a_pasted_bbl_is_still_a_config_error(dk, tmp_path):
    """The .bbl is build output; with no .bib in the project there is nothing to check."""
    _tree(
        tmp_path,
        {
            "main.tex": DOC + "\\cite{good2024entry}\n\\input{main.bbl}\n",
            "main.bbl": "\\begin{thebibliography}{1}\\bibitem{good2024entry} J. Doe."
            "\\end{thebibliography}\n",
        },
    )
    assert dk.main(["--root", str(tmp_path), "lint"]) == 2


def test_a_key_only_in_a_pasted_bbl_is_still_dangling(dk, tmp_path, capsys):
    _tree(
        tmp_path,
        {
            "refs.bib": CLEAN,
            "main.tex": DOC + "\\cite{good2024entry,x}\n\\input{main.bbl}\n",
            "main.bbl": "\\begin{thebibliography}{2}\\bibitem{good2024entry} J. Doe."
            "\\bibitem{x} Fabricated.\\end{thebibliography}\n",
        },
    )
    assert dk.lint(dk.load_config(tmp_path)) == 1
    assert "dangling citation: \\cite{x}" in _err(capsys)


# --- #113 fourth review round -------------------------------------------------------------

HANDBOOK = {"title": "Handbook of machine learning systems", "authors": [], "source": "crossref"}


@pytest.mark.parametrize(
    "printed",
    [
        # Only the first quoted span can be the title; a later one is the borrowed book.
        "J.~Doe, ``Fabricated chapter on agents'' in ``Handbook of machine learning systems,''",
        'J. Doe, "Fabricated chapter"; in: "Handbook of machine learning systems."',
        "J.~Doe, Fabricated method, in ``Handbook of machine learning systems,'' 2020.",
    ],
)
def test_a_quoted_book_after_the_item_is_never_its_title(dk, printed):
    assert _compare(dk, printed, HANDBOOK) is None


def test_an_enquote_chapter_before_a_quoted_book_is_drift(dk):
    printed = "J.~Doe, \\enquote{Fabricated chapter}, in ``Handbook of machine learning systems,''"
    assert _compare(dk, printed, HANDBOOK) == ["title"]


@pytest.mark.parametrize(
    "printed",
    [
        "J. Doe \\& A. Vaswani, ``Attention is all you need,'' 2017.",
        "J. Doe & A. Vaswani, ``Attention is all you need,'' 2017.",
        "J. Doe with A. Vaswani, ``Attention is all you need,'' 2017.",
        "J. Doe et A. Vaswani, ``Attention is all you need,'' 2017.",
        "J. DOE AND A. VASWANI, ``Attention is all you need,'' 2017.",
    ],
)
def test_every_author_separator_ends_the_first_author(dk, printed):
    assert _compare(dk, printed) == ["first author"]


@pytest.mark.parametrize(
    ("printed", "first"),
    [
        ("Y. Le Cun, ``Adam: a method for stochastic optimization,'' 2014.", "Yann LeCun"),
        ("Y. LeCun, ``Adam: a method for stochastic optimization,'' 2014.", "Yann Le Cun"),
    ],
)
def test_split_surnames_are_the_same_author(dk, printed, first):
    record = {
        "title": "Adam: a method for stochastic optimization",
        "authors": [first],
        "source": "arxiv",
    }
    assert _compare(dk, printed, record) == []


def test_a_year_after_a_later_arxiv_version_is_not_the_posting_year(dk):
    record = {"title": "Adam", "authors": ["Diederik Kingma"], "year": 2014, "source": "arxiv"}
    assert _compare(dk, "D. Kingma, ``Adam,'' arXiv:1412.6980v9, 2017.", record) == []


@pytest.mark.parametrize(
    "printed",
    [
        "A. Vaswani, \u201cAttention is all you need,\u201d 2017.",
        "A. Vaswani, \\enquote{Attention is all you need}, 2017.",
    ],
)
def test_typographic_and_csquotes_titles_are_compared(dk, printed):
    assert _compare(dk, printed) == []


def test_a_bbl_pasted_into_the_tex_does_not_orphan_its_bib(dk, tmp_path):
    _tree(
        tmp_path,
        {
            "refs.bib": CLEAN,
            "main.tex": DOC + "\\cite{good2024entry}\n\\begin{thebibliography}{1}"
            "\\bibitem{good2024entry} J. Doe.\\end{thebibliography}\n",
        },
    )
    assert dk.lint(dk.load_config(tmp_path)) == 0


def test_an_etoolbox_test_inside_iffalse_needs_no_fi(dk, tmp_path):
    tex = HAND.replace(
        "\\begin{thebibliography}",
        "\\iffalse old \\iftoggle{draft}{a}{b} \\fi\n\\begin{thebibliography}",
    )
    _hand(tmp_path, tex)
    assert dk.lint(dk.load_config(tmp_path)) == 0


def test_the_else_branch_of_iffalse_is_typeset(dk, tmp_path):
    tex = HAND.replace(
        "\\begin{thebibliography}", "\\iffalse old list\\else\n\\begin{thebibliography}"
    )
    _hand(tmp_path, tex.replace("\\end{thebibliography}", "\\end{thebibliography}\n\\fi"))
    assert dk.lint(dk.load_config(tmp_path)) == 0


def test_a_csname_let_iffalse_does_not_swallow_the_file(dk, tmp_path):
    tex = HAND.replace("\\end{document}", "\\ifdraft x\\fi\n\\end{document}")
    _hand(tmp_path, "\\expandafter\\let\\csname ifdraft\\endcsname\\iffalse\n" + tex)
    assert dk.lint(dk.load_config(tmp_path)) == 0


def test_an_xparse_environment_with_a_braced_argument_spec_is_stripped(dk, tmp_path):
    (tmp_path / "references.bib").write_text(CLEAN)
    (tmp_path / "paper.tex").write_text(
        "\\NewDocumentEnvironment{refs}{ O{} m }"
        "{\\begin{thebibliography}{9}}{\\end{thebibliography}}\n" + DOC + "\\cite{good2024entry}\n"
    )
    assert dk.lint(dk.load_config(tmp_path)) == 0


# --- #113 fifth review round --------------------------------------------------------------


@pytest.mark.parametrize(
    ("printed", "first"),
    [
        # A short capitalised surname is not Vancouver initials to strip.
        ("Kaiming LIU, ``Deep residual learning,'' 2016.", "Kaiming He"),
        # A given name and surname are not one joined name.
        ("Jian Li, ``Deep residual learning,'' 2016.", "Jianli Wang"),
    ],
)
def test_a_wrong_first_author_sharing_a_given_name_is_drift(dk, printed, first):
    record = {"title": "Deep residual learning", "authors": [first], "source": "crossref"}
    assert _compare(dk, printed, record) == ["first author"]


def test_vancouver_initials_after_a_surname_report_drift_not_a_pass(dk):
    """`Kingma DP` cannot be told from `Kaiming LIU`, so it reads as the wrong author: false
    drift, never a false pass. Vancouver styles rarely quote titles, so this is uncommon."""
    record = {"title": "Adam", "authors": ["Diederik P. Kingma"], "source": "arxiv"}
    assert _compare(dk, "Kingma DP, Ba J. ``Adam.'' 2014.", record) == ["first author"]


@pytest.mark.parametrize(
    "lead",
    ["In~", "In\\ ", "In {", "In: \\emph{", "In Proc. ", "In: Smith, J. (ed.) "],
)
def test_in_anywhere_before_the_quote_leaves_the_entry_uncompared(dk, lead):
    printed = f"K. He, Fabricated chapter. {lead}``Handbook of machine learning systems,'' 2020."
    assert _compare(dk, printed, HANDBOOK) is None


@pytest.mark.parametrize(
    "parked",
    [
        "\\iffalse\n{\\bf Old list}\n\\fi",
        "\\iffalse \\ifmmode{a}\\else{b}\\fi \\fi",
    ],
)
def test_text_after_a_conditional_is_never_dropped(dk, tmp_path, parked):
    tex = HAND.replace("\\begin{thebibliography}", parked + "\n\\begin{thebibliography}")
    _hand(tmp_path, tex)
    assert dk.lint(dk.load_config(tmp_path)) == 0


# --- #113 sixth review round --------------------------------------------------------------


def test_conditionals_are_not_evaluated_so_nothing_is_hidden(dk, tmp_path, capsys):
    """A list parked in \\iffalse is read: over-reading adds an orphan, never hides an entry.
    Every attempt to evaluate conditionals deleted live text somewhere."""
    parked = "\\iffalse\\begin{thebibliography}{1}\\bibitem{old} Old.\\end{thebibliography}\\fi\n"
    _hand(tmp_path, HAND.replace("\\begin{thebibliography}", parked + "\\begin{thebibliography}"))
    assert dk.lint(dk.load_config(tmp_path)) == 1
    assert "orphan \\bibitem: old" in _err(capsys)


@pytest.mark.parametrize(
    "preamble",
    [
        "\\iftrue\\iftoggle {long}{}{}\\fi\n",
        "\\providecommand\\ifshowurl\\iftrue\n",
        "\\iftrue \\newif\\ifanonymous \\anonymousfalse \\fi\n",
        "\\loop\\ifnum0>1 \\repeat\n",
    ],
)
def test_an_unclosable_conditional_does_not_drop_the_list(dk, tmp_path, preamble):
    _hand(tmp_path, preamble + HAND)
    items = dk.read_document(tmp_path / "paper.tex").bibitems
    assert [i.key for i in items] == ["doe2024", "roe2019", "poe2015"]


@pytest.mark.parametrize(
    "printed",
    [
        "LIU Kaiming, X. Zhang, ``Deep residual learning,'' 2016.",
        "Kaiming, Z., ``Deep residual learning,'' 2016.",
    ],
)
def test_a_given_name_printed_as_the_surname_is_drift(dk, printed):
    record = {"title": "Deep residual learning", "authors": ["Kaiming He"], "source": "crossref"}
    assert _compare(dk, printed, record) == ["first author"]


@pytest.mark.parametrize(
    ("printed", "first"),
    [
        ("J. Garc{\\'\\i}a, ``Deep learning,'' Nature, 2020.", "Juan Garc\u00eda M\u00e1rquez"),
        ("X. Wang, ``Deep learning,'' Nature, 2020.", "Wang Xiaoming"),
    ],
)
def test_a_double_surname_or_swapped_source_name_reads_as_drift(dk, printed, first):
    """Only the source's last name word is its family name. A Spanish double surname or a
    record with given and family swapped reads as drift: never a pass on a given name."""
    record = {"title": "Deep learning", "authors": [first], "source": "crossref"}
    assert _compare(dk, printed, record) == ["first author"]
