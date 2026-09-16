"""Unit tests for techne:latex's log, bibliography, and coverage gates.

Every defect found in this script so far has been a misclassification in a pure
function: a regex that matched nothing, or a finding reported when it should
have been suppressed. These run without TeX.
"""

from __future__ import annotations

import pathlib

import pytest

ERROR, BLOCK, WARN, REVIEW, INFO = "ERROR", "BLOCK", "WARN", "REVIEW", "INFO"


# --------------------------------------------------------------------- log --


def test_file_line_error_is_an_error(lx, write_log, gates):
    log = write_log("./doc.tex:12: Undefined control sequence.\n")
    found = lx.parse_log(log, 5.0)
    assert (ERROR, "tex-error") in gates(found)
    assert found[0].where == "./doc.tex:12"


def test_bang_line_is_an_error(lx, write_log, gates):
    log = write_log("! LaTeX Error: File `nope.sty' not found.\n")
    assert (ERROR, "tex-error") in gates(lx.parse_log(log, 5.0))


def test_latex_warning_is_not_read_as_a_file_line_error(lx, write_log, gates):
    """`LaTeX Warning: ... on input line 4.` matches the file:line shape."""
    log = write_log("LaTeX Warning: Something happened on input line 4.\n")
    assert (ERROR, "tex-error") not in gates(lx.parse_log(log, 5.0))


def test_undefined_reference_blocks(lx, write_log, gates):
    log = write_log("LaTeX Warning: Reference `fig:one' on page 2 undefined on input line 9.\n")
    found = lx.parse_log(log, 5.0)
    assert (BLOCK, "undefined-ref") in gates(found)
    assert "fig:one" in found[0].message


def test_classic_undefined_citation_blocks(lx, write_log, gates):
    log = write_log("LaTeX Warning: Citation `knuth84' on page 1 undefined on input line 3.\n")
    assert (BLOCK, "undefined-cite") in gates(lx.parse_log(log, 5.0))


def test_biblatex_missing_entry_blocks_rather_than_warns(lx, write_log, gates):
    """biblatex reports an unresolvable key as a package warning, not as
    'Citation undefined'. Classifying it as generic package chatter is how a
    [?] reaches the PDF through a clean-looking run."""
    log = write_log(
        "Package biblatex Warning: The following entry could not be found on input line 7.\n"
    )
    found = gates(lx.parse_log(log, 5.0))
    assert (BLOCK, "undefined-cite") in found
    assert (WARN, "package") not in found


def test_duplicate_label_blocks(lx, write_log, gates):
    log = write_log("LaTeX Warning: Label `sec:a' multiply defined.\n")
    assert (BLOCK, "duplicate-label") in gates(lx.parse_log(log, 5.0))


def test_missing_glyphs_are_counted_per_font(lx, write_log):
    body = "".join(
        "Missing character: There is no ` (U+0060) in font TeX Gyre Heros!\n" for _ in range(3)
    )
    found = [f for f in lx.parse_log(write_log(body), 5.0) if f.gate == "missing-glyph"]
    assert len(found) == 1
    assert found[0].severity == BLOCK
    assert "3 character(s)" in found[0].message


def test_overfull_respects_the_threshold(lx, write_log):
    body = (
        "Overfull \\hbox (12.5pt too wide) in paragraph at lines 10--12\n"
        "Overfull \\hbox (1.2pt too wide) in paragraph at lines 20--22\n"
    )
    found = [f for f in lx.parse_log(write_log(body), 5.0) if f.gate == "overfull"]
    assert len(found) == 1
    assert "12.5pt" in found[0].message


def test_underfull_is_not_reported(lx, write_log):
    body = "Underfull \\vbox (badness 10000) has occurred while \\output is active\n"
    assert [f for f in lx.parse_log(write_log(body), 5.0) if f.gate == "overfull"] == []


def test_only_the_largest_five_overfull_boxes_are_listed(lx, write_log, gates):
    body = "".join(
        f"Overfull \\hbox ({n}.0pt too wide) in paragraph at lines {n}--{n + 1}\n"
        for n in range(10, 20)
    )
    found = lx.parse_log(write_log(body), 5.0)
    assert len([f for f in found if f.severity == WARN and f.gate == "overfull"]) == 5
    assert (INFO, "overfull") in gates(found)


def test_surviving_rerun_request_blocks(lx, write_log, gates):
    log = write_log("LaTeX Warning: Label(s) may have changed. Rerun to get cross-references.\n")
    assert (BLOCK, "unsettled") in gates(lx.parse_log(log, 5.0))


def test_repeated_package_warnings_collapse(lx, write_log):
    body = "".join("Package caption Warning: hypcap ignored on input line 3.\n" for _ in range(4))
    assert len([f for f in lx.parse_log(write_log(body), 5.0) if f.gate == "package"]) == 1


def test_a_missing_log_is_an_error(lx, tmp_path, gates):
    assert (ERROR, "build") in gates(lx.parse_log(tmp_path / "absent.log", 5.0))


# ------------------------------------------------------------ bibliography --


def test_biber_severity_survives_its_module_prefix(lx, tmp_path, gates):
    """Regression. biber prefixes every line with its own trace, so anchoring
    the severity to the start of the line matched nothing at all and a missing
    citation reported as a clean build."""
    (tmp_path / "doc.blg").write_text(
        "[0] Biber.pm:415> INFO - This is Biber 2.19\n"
        "[0] Biber.pm:830> WARN - I didn't find a database entry for 'ghost' (section 0)\n",
        encoding="utf-8",
    )
    found = lx.parse_blg(tmp_path / "doc.tex")
    assert gates(found) == {(BLOCK, "bibliography")}
    assert "ghost" in found[0].message


def test_biber_error_outranks_a_warning(lx, tmp_path, gates):
    (tmp_path / "doc.blg").write_text(
        "[0] Utils.pm:410> ERROR - Cannot find 'refs.bib'\n", encoding="utf-8"
    )
    assert gates(lx.parse_blg(tmp_path / "doc.tex")) == {(ERROR, "bibliography")}


def test_clean_blg_reports_nothing(lx, tmp_path):
    (tmp_path / "doc.blg").write_text(
        "[0] Biber.pm:415> INFO - Found 3 entries\n", encoding="utf-8"
    )
    assert lx.parse_blg(tmp_path / "doc.tex") == []


# ---------------------------------------------------------------- cascade --


def test_fatal_build_hides_the_undefined_cascade(lx, gates):
    """Regression. A run that died wrote no .aux, so every ref and cite reads
    undefined. Reporting all of it buried the one error to fix."""
    found = [
        lx.Finding(ERROR, "tex-error", "Undefined control sequence."),
        lx.Finding(BLOCK, "undefined-ref", "\\ref{a} renders as ??"),
        lx.Finding(BLOCK, "undefined-cite", "\\cite{b} renders as [?]"),
        lx.Finding(WARN, "overfull", "hbox 9pt over"),
        lx.Finding(INFO, "pdf", "0 pages"),
    ]
    collapsed = lx.collapse_cascade(found)
    assert gates(collapsed) == {(ERROR, "tex-error"), (INFO, "pdf"), (INFO, "cascade")}
    assert "3 downstream" in next(f for f in collapsed if f.gate == "cascade").message


def test_a_clean_run_keeps_every_finding(lx, gates):
    found = [
        lx.Finding(BLOCK, "draft-marker", "1x `FILL'"),
        lx.Finding(WARN, "package", "chatter"),
    ]
    assert gates(lx.collapse_cascade(found)) == {(BLOCK, "draft-marker"), (WARN, "package")}


def test_findings_are_ordered_by_severity(lx):
    found = [
        lx.Finding(INFO, "pdf", "4 pages"),
        lx.Finding(BLOCK, "draft-marker", "1x `FILL'"),
        lx.Finding(WARN, "package", "chatter"),
    ]
    assert [f.severity for f in lx.collapse_cascade(found)] == [BLOCK, WARN, INFO]


# ---------------------------------------------------------------- verdict --


@pytest.mark.parametrize(
    ("severities", "code"),
    [
        ([], 0),
        ([INFO, WARN], 0),
        ([REVIEW], 0),
        ([BLOCK], 2),
        ([BLOCK, ERROR], 1),
        ([ERROR], 1),
    ],
)
def test_exit_code_follows_the_worst_finding(lx, severities, code):
    found = [lx.Finding(s, "gate", "message") for s in severities]
    assert lx.verdict(found, pathlib.Path("d.pdf"), pathlib.Path("d.log"))[0] == code


def test_a_clean_verdict_still_surfaces_coverage_doubt(lx):
    found = [lx.Finding(REVIEW, "coverage", "not located: Problem 3")]
    code, line = lx.verdict(found, pathlib.Path("d.pdf"), pathlib.Path("d.log"))
    assert code == 0
    assert "confirm by eye" in line


# --------------------------------------------------------------- coverage --


def test_coverage_reports_an_unanswered_problem(lx, tmp_path):
    prompt = tmp_path / "hw.md"
    prompt.write_text("Problem 1. Do a thing.\nProblem 2. Another.\nProblem 3. A third.\n")
    found = lx.prompt_coverage(prompt, "Problem 1 answered. Problem 2 answered.")
    assert found[0].severity == REVIEW
    assert "Problem 3" in found[0].message


def test_coverage_is_quiet_when_everything_is_answered(lx, tmp_path):
    prompt = tmp_path / "hw.md"
    prompt.write_text("Problem 1. Do a thing.\nBonus A. Extra.\n")
    found = lx.prompt_coverage(prompt, "Problem 1 answered. Bonus A answered.")
    assert found[0].severity == INFO


def test_coverage_says_so_when_the_prompt_has_no_problems(lx, tmp_path):
    prompt = tmp_path / "essay.md"
    prompt.write_text("Write about a breakfast you cooked.\n")
    found = lx.prompt_coverage(prompt, "Some essay text.")
    assert found[0].severity == INFO
    assert "nothing to compare" in found[0].message


# ------------------------------------------------------------ path finding --


def test_the_documents_own_sidecar_is_not_its_prompt(lx, tmp_path):
    (tmp_path / "solutions.tex").write_text("\\documentclass{article}")
    (tmp_path / "solutions.extracted.md").write_text("my own text")
    (tmp_path / "assignment.extracted.md").write_text("Problem 1.")
    prompt, ambiguous = lx.find_prompt(tmp_path / "solutions.tex")
    assert prompt.name == "assignment.extracted.md"
    assert ambiguous == ""


def test_two_candidate_prompts_asks_rather_than_guessing(lx, tmp_path):
    (tmp_path / "doc.tex").write_text("\\documentclass{article}")
    for name in ("a.extracted.md", "b.extracted.md"):
        (tmp_path / name).write_text("Problem 1.")
    prompt, ambiguous = lx.find_prompt(tmp_path / "doc.tex")
    assert prompt is None
    assert "--prompt" in ambiguous


def test_root_document_is_found_by_its_documentclass(lx, tmp_path):
    (tmp_path / "main.tex").write_text("\\documentclass{article}\n")
    (tmp_path / "section-one.tex").write_text("\\section{One}\n")
    assert lx.find_main_tex(tmp_path).name == "main.tex"


def test_two_root_documents_refuse_to_pick_one(lx, tmp_path):
    for name in ("a.tex", "b.tex"):
        (tmp_path / name).write_text("\\documentclass{article}\n")
    with pytest.raises(SystemExit, match="2 root documents"):
        lx.find_main_tex(tmp_path)


def test_no_root_document_is_an_explicit_failure(lx, tmp_path):
    (tmp_path / "fragment.tex").write_text("\\section{One}\n")
    with pytest.raises(SystemExit, match="documentclass"):
        lx.find_main_tex(tmp_path)


def test_an_explicit_file_is_taken_as_given(lx, tmp_path):
    tex = tmp_path / "anything.tex"
    tex.write_text("\\section{no documentclass here}\n")
    assert lx.find_main_tex(tex) == tex
