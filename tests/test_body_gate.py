"""Tests for phylax's body budget (body_gate.py) and its guard in git_guards.py (techne#229).

The counting is checked against graphe's length_budget.markdown_words, whose rule it
mirrors; the guard is fed PreToolUse JSON for each way gh writes a body.
"""

from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import random
import re
import shutil
import subprocess
import sys

import pytest
from conftest import HOOK_PYTHON, hook_env

ROOT = pathlib.Path(__file__).resolve().parent.parent
HOOKS = ROOT / "plugins" / "phylax" / "hooks"
GUARDS = HOOKS / "git_guards.py"
FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures" / "body_gate"
BODIES = "block_long_bodies"


def _load(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader, f"cannot load {path}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


body_gate = _load("phylax_body_gate", HOOKS / "body_gate.py")
sys.path.insert(0, str(ROOT / "plugins" / "graphe" / "_shared"))
length_budget = _load(
    "graphe_length_budget", ROOT / "plugins" / "graphe" / "_shared" / "length_budget.py"
)


def words_of(n: int, sentence: int = 12) -> str:
    """N words in sentences of SENTENCE words."""
    out, line = [], []
    for i in range(n):
        line.append(f"word{i}")
        if len(line) == sentence:
            out.append(" ".join(line) + ".")
            line = []
    if line:
        out.append(" ".join(line) + ".")
    return " ".join(out)


PROSE_CASES = [
    "Plain words, and a [link](https://example.com/very/long/path) with `code`.",
    "| What | Result |\n|---|---|\n| tests | 34 passed |\n\n- a bullet\n- **bold** item",
    "Text\n\n```bash\nmake test && echo done\n```\n\nafter <!-- hidden note --> it.",
    "## Heading\n\nA line with 3 numbers, 4.5% and v1.2.3.",
]


@pytest.mark.parametrize("text", PROSE_CASES)
def test_counts_words_as_graphe_counts_a_markdown_page(text):
    assert body_gate.visible_words(text) == length_budget.markdown_words(text)


def test_details_comments_and_code_are_not_visible():
    body = (
        "Short top.\n\n<details><summary>Details</summary>\n\n"
        + words_of(500)
        + "\n<details>\nnested "
        + words_of(50)
        + "\n</details>\n</details>\n\nAfter. <!-- a note "
        + words_of(40)
        + " -->"
    )
    assert body_gate.visible_words(body) == 4, "the summary line shows; the folded text does not"
    assert body_gate.visible_words("Top.\n<details>\n" + words_of(300)) == 1, (
        "unclosed hides the rest"
    )


def test_what_github_shows_is_what_counts():
    assert body_gate.visible_words("Top.\n<details open>\n" + words_of(200) + "\n</details>") == 201
    hidden = "Folds depth into `<details>` sections. " + words_of(300)
    assert body_gate.visible_words(hidden) == length_budget.markdown_words(hidden), (
        "a tag in code is text"
    )
    fenced = "- item\n\n  ```bash\n  " + words_of(200) + "\n  ```\n"
    assert body_gate.visible_words(fenced) == length_budget.markdown_words(fenced) == 1
    # An entity and a tag are not words.
    assert body_gate.visible_words("n<k and k>0 &nbsp; ok<br>") == 4
    assert body_gate.check("PR", "graphe reads a `<!-- budget: 900 words -->` line.")[0] == []
    assert body_gate.check("PR", "```\n% budget: 4 pages\n```")[0] == []


def test_pr_issue_and_comment_budgets_allow_about_a_tenth_more():
    for kind, budget in (("PR", 150), ("issue", 300), ("comment", 150)):
        assert body_gate.check(kind, words_of(int(budget * 1.1)))[0] == [], kind
        denies, _ = body_gate.check(kind, words_of(int(budget * 1.1) + 1))
        assert denies and f"budget is about {budget}" in denies[0], kind


def test_a_budget_marker_is_refused_even_under_budget():
    for body in ("Fine.\n<!-- budget: 150 words -->", "Fine.\n% budget: 2 pages"):
        denies, _ = body_gate.check("PR", body)
        assert any("budget:` marker" in d for d in denies)


def test_long_sentences_warn_without_refusing_and_tables_are_not_sentences():
    long = words_of(30, sentence=30)
    denies, warnings = body_gate.check("PR", long)
    assert denies == [] and warnings and "1 sentence(s)" in warnings[0]
    row = "| " + " ".join(f"w{i}" for i in range(40)) + " |"
    assert body_gate.long_sentences(row) == []


@pytest.mark.parametrize("name", sorted(p.name for p in FIXTURES.glob("*.md")))
def test_real_bodies_written_to_the_rule_pass(name):
    assert body_gate.check("PR", (FIXTURES / name).read_text())[0] == []


def run_guard(command: str, cwd: pathlib.Path, on=(BODIES,)) -> dict | None:
    payload = json.dumps({"cwd": str(cwd), "tool_input": {"command": command}})
    proc = subprocess.run(
        [HOOK_PYTHON, str(GUARDS)],
        input=payload,
        capture_output=True,
        text=True,
        env=hook_env(on),
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout) if proc.stdout.strip() else None


def refused(out: dict | None) -> str | None:
    if out and out["hookSpecificOutput"].get("permissionDecision") == "deny":
        return out["hookSpecificOutput"]["permissionDecisionReason"]
    return None


@pytest.fixture
def repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return tmp_path


LONG = words_of(200)
FOLDED = f"<details><summary>More</summary>\n\n{words_of(900)}\n</details>"
SHORT = words_of(100)


@pytest.mark.parametrize(
    "command",
    [
        f"gh pr create --title t --body '{LONG}'",
        f"gh pr create -t t -b '{LONG}'",
        f"gh pr edit 7 --body='{LONG}'",
        f"gh pr create --title t --body \"$(cat <<'EOF'\n{LONG}\nEOF\n)\"",
        f"gh pr create --title t --body-file - <<'EOF'\n{LONG}\nEOF",
        f"gh pr comment 7 --body '{LONG}'",
        f"gh issue comment 7 -b '{LONG}'",
        f"gh pr review 7 --comment --body '{LONG}'",
        f"gh issue create --title t --body '{words_of(400)}'",
        f"gh -R o/r issue edit 3 --body '{words_of(400)}'",
        f"gh api -X PATCH repos/o/r/pulls/9 -f body='{LONG}'",
        f"gh api repos/o/r/issues/9/comments -f body='{LONG}'",
        f"gh api --method PATCH /repos/o/r/issues/9 --raw-field body='{words_of(400)}'",
    ],
)
def test_each_way_gh_writes_an_overlong_body_is_refused(repo, command):
    assert "visible words" in (refused(run_guard(command, repo)) or "")


def test_each_gh_reads_its_own_heredoc_and_stdin_bodies_are_read(repo):
    two = (
        f"gh issue create --body \"$(cat <<'A'\n{words_of(250)}\nA\n)\" && "
        f"gh pr create --body \"$(cat <<'B'\n{words_of(20)}\nB\n)\""
    )
    assert refused(run_guard(two, repo)) is None, "a 250-word issue and a 20-word PR both pass"
    two_long_pr = (
        f"gh issue create --body \"$(cat <<'A'\n{words_of(20)}\nA\n)\" && "
        f"gh pr create --body \"$(cat <<'B'\n{LONG}\nB\n)\""
    )
    assert "PR body" in (refused(run_guard(two_long_pr, repo)) or "")
    assert refused(
        run_guard(f"gh api -X PATCH repos/o/r/pulls/1 -F body=@- <<'EOF'\n{LONG}\nEOF", repo)
    )
    payload = json.dumps({"body": LONG})
    assert refused(
        run_guard(f"gh api -X PATCH repos/o/r/pulls/1 --input - <<'EOF'\n{payload}\nEOF", repo)
    )
    (repo / "b.md").write_text(LONG)
    assert refused(run_guard('B="$(cat b.md)"; gh pr create -t t --body "$B"', repo))
    assert refused(run_guard(f"gh api repos/o/r/pulls/comments/9/replies -f body='{LONG}'", repo))


def test_body_files_are_read(repo):
    (repo / "long.md").write_text(LONG)
    (repo / "short.md").write_text(SHORT)
    (repo / "in.json").write_text(json.dumps({"body": LONG}))
    assert refused(run_guard("gh pr create -t t --body-file long.md", repo))
    assert refused(run_guard("gh pr create -t t -F long.md", repo))
    assert refused(run_guard("gh api -X PATCH repos/o/r/pulls/1 -F body=@long.md", repo))
    assert refused(run_guard("gh api -X PATCH repos/o/r/pulls/1 --input in.json", repo))
    assert run_guard("gh pr create -t t --body-file short.md", repo) is None


@pytest.mark.parametrize(
    "command",
    [
        f"gh pr create --title t --body '{SHORT}'",
        f"gh pr create --title t --body 'Top.\n\n{FOLDED}'",
        f"gh issue create --title t --body '{words_of(300)}'",
        "gh pr edit 7 --title 'a new title only'",
        f"gh pr view 7 --json body --jq '.body' # {LONG}",
        f"gh api repos/o/r/pulls/9 --jq .body # {LONG}",
        f"gh api graphql -f query='mutation {{ x }}' -f body='{LONG}'",
        "gh pr create --title t --body-file -",
    ],
)
def test_a_body_within_budget_or_no_body_passes(repo, command):
    assert refused(run_guard(command, repo)) is None


def test_off_by_default_and_off_per_repo(repo):
    command = f"gh pr create --title t --body '{LONG}'"
    assert run_guard(command, repo, on=()) is None
    subprocess.run(
        ["git", "-C", str(repo), "config", "phylax.blockLongBodies", "false"], check=True
    )
    assert run_guard(command, repo) is None


def test_a_heredoc_is_the_body_of_the_value_that_opened_it(repo):
    short_title = f"\"$(cat <<'T'\n{words_of(2)}\nT\n)\""
    long_body = f"\"$(cat <<'B'\n{LONG}\nB\n)\""
    assert refused(run_guard(f"gh pr create --title {short_title} --body {long_body}", repo))
    held = f"BODY=$(cat <<'EOF'\n{LONG}\nEOF\n)\ngh pr comment 1 --body \"$BODY\""
    assert refused(run_guard(held, repo)), "a heredoc held in a variable is still the body"
    quoted = f'BODY="$(cat <<\'EOF\'\n{LONG}\nEOF\n)"\ngh pr comment 1 --body "$BODY"'
    assert refused(run_guard(quoted, repo))
    assert refused(run_guard(f"gh pr comment 1 --body 'x << 2 {LONG}'", repo)), (
        "a quoted << is text, not a heredoc"
    )
    blamed = f"gh issue comment 1 --body 'x << 2' && gh pr comment 1 -F - <<'B'\n{LONG}\nB"
    assert refused(run_guard(blamed, repo))
    loop = f"while read l; do :; done <<'Q'\nq\nQ\ngh pr comment 1 -F - <<'B'\n{LONG}\nB"
    assert refused(run_guard(loop, repo)), "a heredoc fed to a loop is not the gh body"
    here_string = f"grep x <<< \"$y\" && gh pr comment 1 -F - <<'B'\n{LONG}\nB"
    assert refused(run_guard(here_string, repo)), "a here-string opens no heredoc"


def test_a_body_file_written_in_the_same_command_is_read_from_its_heredoc(repo):
    fresh = f"cat > new.md <<'EOF'\n{LONG}\nEOF\ngh pr create -t t --body-file new.md"
    assert refused(run_guard(fresh, repo)), "the file does not exist yet when the hook runs"
    (repo / "stale.md").write_text(words_of(400))
    rewrite = f"cat > stale.md <<'EOF'\n{SHORT}\nEOF\ngh pr create -t t --body-file stale.md"
    assert refused(run_guard(rewrite, repo)) is None, "the new short text counts, not the old file"
    unknown = "cp other.md made.md && gh pr create -t t --body-file made.md"
    assert "own call" in (refused(run_guard(unknown, repo)) or "")


def test_a_body_github_would_refuse_is_refused_without_a_slow_scan():
    import time

    start = time.monotonic()
    denies, _ = body_gate.check("PR", "```\n" + "x\n" * 40000)
    assert time.monotonic() - start < 1
    assert "GitHub refuses" in denies[0]


# The regexes the linear scanners replace, as graphe's prose_check holds them.
GRAPHE_FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,})[^\n]*\n.*?^[ \t]*\1[`~]*[ \t]*$", re.M | re.S)
HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)


def test_the_linear_scanners_match_the_regexes_they_replace():
    rng = random.Random(229)
    pieces = [
        "`",
        "```",
        "````",
        "~~~",
        "~",
        "a",
        " ",
        "\t",
        "\n",
        "<!--",
        "-->",
        "-",
        "<",
        ">",
        "](",
        ")",
        "<b>",
        "x",
    ]
    for _ in range(4000):
        text = "".join(rng.choice(pieces) for _ in range(rng.randrange(40)))
        assert body_gate.strip_fences(text) == GRAPHE_FENCE.sub(" ", text), repr(text)
        assert body_gate.strip_comments(text) == HTML_COMMENT.sub(" ", text), repr(text)
        for pattern, close in ((body_gate._TAG, ">"), (body_gate._LINK_URL, ")")):
            assert body_gate.sub_closed(pattern, " ", text, close) == pattern.sub(" ", text), repr(
                text
            )


@pytest.mark.parametrize("unit", ["<!--", "```a\n", "`", "<details", "<b", "]("])
def test_a_body_at_githubs_cap_is_checked_quickly(unit):
    import time

    body = (unit * (body_gate.GITHUB_MAX // len(unit) + 1))[: body_gate.GITHUB_MAX]
    start = time.monotonic()
    body_gate.check("PR", body)
    assert time.monotonic() - start < 2


def test_a_heredoc_held_in_a_variable_is_its_text_to_every_guard(repo):
    command = 'D=$(cat <<\'EOF\'\n.\nEOF\n)\ncd "$D" && git -C "$D" commit -m x'
    payload = json.dumps({"cwd": str(repo), "tool_input": {"command": command}})
    for on in ((BODIES,), ("block_attribution_trailers", "block_commits_md")):
        proc = subprocess.run(
            [HOOK_PYTHON, str(GUARDS)],
            input=payload,
            capture_output=True,
            text=True,
            env=hook_env(on),
            check=False,
        )
        assert (proc.returncode, proc.stdout.strip()) == (0, ""), proc.stderr


def test_each_assignment_holds_its_own_heredoc(repo):
    twice = (
        f"B=$(cat <<'EOF'\n{words_of(5)}\nEOF\n)\ngh issue comment 1 --body \"$B\"\n"
        f"B=$(cat <<'EOF'\n{LONG}\nEOF\n)\ngh pr comment 1 --body \"$B\""
    )
    assert refused(run_guard(twice, repo))
    reverse = (
        f"B=$(cat <<'EOF'\n{LONG}\nEOF\n)\nB=$(cat <<'EOF'\n{words_of(5)}\nEOF\n)\n"
        'gh pr comment 1 --body "$B"'
    )
    assert refused(run_guard(reverse, repo)) is None


def test_every_heredoc_and_text_in_a_value_counts(repo):
    five = f"$(cat <<'A'\n{words_of(5)}\nA\n)"
    assert refused(run_guard(f'gh pr comment 1 --body "{five} {LONG}"', repo))
    assert refused(run_guard(f"gh pr comment 1 --body \"{five}\n$(cat <<'C'\n{LONG}\nC\n)\"", repo))
    held = f"B=$(cat <<'EOF'\n{words_of(5)}\nEOF\n)\ngh pr comment 1 --body \"$B {LONG}\""
    assert refused(run_guard(held, repo))
    dash = f"gh pr comment 1 -F - <<-'EOF'\n{LONG}\nEOF"
    assert refused(run_guard(dash, repo)), "a <<- heredoc is read too"
    last = f"gh pr comment 1 -F - <<'A' <<'B'\nshort\nA\n{LONG}\nB"
    assert refused(run_guard(last, repo)), "bash feeds the last of two heredocs"
    two_on_a_line = f"cat <<'A' >/dev/null; gh pr comment 1 -F - <<'B'\nx\nA\n{LONG}\nB"
    assert refused(run_guard(two_on_a_line, repo))


def test_an_appended_or_combined_body_file_cannot_be_known_here(repo):
    (repo / "b.md").write_text(LONG)
    for write in (
        "cat >> b.md <<'EOF'\nmore\nEOF",
        "tee -a b.md <<'EOF'\nmore\nEOF",
        "cat b.md - > n.md <<'EOF'\nmore\nEOF",
    ):
        target = "n.md" if "n.md" in write else "b.md"
        out = run_guard(f"{write}\ngh pr create -t t --body-file {target}", repo)
        assert "own call" in (refused(out) or ""), write
    tee = f"tee c.md <<'EOF'\n{LONG}\nEOF\ngh pr create -t t --body-file c.md"
    assert refused(run_guard(tee, repo))
    (repo / "short.md").write_text(SHORT)
    copy = "cp short.md copy.md && gh pr create -t t --body-file short.md"
    assert refused(run_guard(copy, repo)) is None, "cp writes only its last name"


def test_a_body_file_named_through_a_variable_is_expanded(repo):
    (repo / "b.md").write_text(LONG)
    assert refused(run_guard('F=b.md; gh pr comment 1 --body-file "$F"', repo))
    assert refused(run_guard('gh pr comment 1 --body-file "$PWD/b.md"', repo))
    assert "Name the file" in (
        refused(run_guard('gh pr comment 1 --body-file "$(mktemp)"', repo)) or ""
    )
    made = f'T=$(mktemp); cat > "$T" <<\'EOF\'\n{SHORT}\nEOF\ngh pr comment 1 --body-file "$T"'
    assert refused(run_guard(made, repo)) is None, "a file written here from a heredoc is known"


def test_a_command_in_a_quoted_heredoc_body_is_text(repo):
    (repo / "README.md").write_text(LONG)
    said = 'The hook now reads $(cat README.md) before it sends, and `$(cat "$F")` too.'
    body = f"gh pr comment 1 --body \"$(cat <<'EOF'\n{said}\nEOF\n)\""
    assert refused(run_guard(body, repo)) is None
    held = f"B=$(cat <<'EOF'\n{said}\nEOF\n)\ngh pr comment 1 --body \"$B\""
    assert refused(run_guard(held, repo)) is None


def test_a_file_read_into_a_variable_is_the_body(repo):
    (repo / "b.md").write_text(LONG)
    for read in ("B=$(cat b.md)", "B=$(< b.md)", 'B="$(cat b.md)"'):
        assert refused(run_guard(f'{read}; gh pr comment 1 --body "$B"', repo)), read
    unknown = 'B=$(python3 make_body.py); gh pr comment 1 --body "$B"'
    assert "cannot run" in (refused(run_guard(unknown, repo)) or "")


def test_each_unknown_file_name_is_its_own(repo):
    two = (
        f"A=$(mktemp); B=$(mktemp); cat > \"$A\" <<'X'\n{SHORT}\nX\n"
        f'cat > "$B" <<\'Y\'\n{LONG}\nY\ngh pr comment 1 --body-file "$B"'
    )
    assert refused(run_guard(two, repo)), "B's long body, not A's short one"
    tee = "tee -ia c.md <<'EOF'\nmore\nEOF\ngh pr create -t t --body-file c.md"
    assert "own call" in (refused(run_guard(tee, repo)) or ""), "-ia appends"


def test_a_quoted_heredoc_folder_is_its_text_to_every_guard(repo):
    command = 'D="$(cat <<\'EOF\'\n.\nEOF\n)"\ncd "$D" && git commit -m x'
    payload = json.dumps({"cwd": str(repo), "tool_input": {"command": command}})
    proc = subprocess.run(
        [HOOK_PYTHON, str(GUARDS)],
        input=payload,
        capture_output=True,
        text=True,
        env=hook_env(("block_attribution_trailers",)),
        check=False,
    )
    assert (proc.returncode, proc.stdout.strip()) == (0, ""), proc.stderr


@pytest.mark.parametrize("unit", ["\n", " \n", "\n \n"])
def test_a_body_of_blank_lines_is_checked_quickly(unit):
    import time

    body = (unit * (body_gate.GITHUB_MAX // len(unit)))[: body_gate.GITHUB_MAX]
    start = time.monotonic()
    body_gate.check("PR", body)
    assert time.monotonic() - start < 2


def test_a_file_is_read_where_and_when_the_variable_is_set(repo):
    (repo / "b.md").write_text(LONG)
    (repo / "sub").mkdir()
    for read in ("B=$(cat b.md)", 'B="$(cat b.md)"', "B=$(< b.md)", "declare B=$(cat b.md)"):
        sent = f'{read}; cd sub && gh pr comment 1 --body "$B"'
        assert refused(run_guard(sent, repo)), read
    assert refused(run_guard('(B=$(< b.md); gh pr comment 1 --body "$B")', repo)), (
        "a subshell keeps it"
    )
    (repo / "short.md").write_text(SHORT)
    assert refused(run_guard('B=$(cat short.md); gh pr comment 1 --body "$B"', repo)) is None
    outside = '(B=$(cat b.md)); gh pr comment 1 --body "${B}ok"'
    assert "does not set" in (refused(run_guard(outside, repo)) or ""), "unset outside its subshell"
    later = (
        f"cat > n.md <<'A'\n{LONG}\nA\nB=$(cat n.md)\n"
        f"cat > n.md <<'C'\n{SHORT}\nC\ngh pr comment 1 --body \"$B\""
    )
    assert refused(run_guard(later, repo)), "B holds the text from when it was read"


def test_inline_and_variable_reads_follow_one_rule(repo):
    (repo / "b.md").write_text(LONG)
    for inline in ("$(cat 'b.md')", "$(cat -- b.md)", "$(<b.md)", "$(cat ./b.md)"):
        assert refused(run_guard(f'gh pr comment 1 --body "{inline}"', repo)), inline
    for unknown in (
        "$(cat b.md c.md)",
        "$(sed -n p b.md)",
        "$(cat b.md | head)",
        "$(python3 x.py)",
    ):
        out = refused(run_guard(f'gh pr comment 1 --body "Fixed in {unknown}"', repo))
        assert "cannot run" in (out or ""), unknown
        out = refused(run_guard(f'B={unknown}; gh pr comment 1 --body "Fixed in $B"', repo))
        assert "cannot run" in (out or ""), f"B={unknown}"
    tail = "gh pr comment 1 --body \"$(cat <<'A'; echo more\nshort\nA\n)\""
    assert "cannot run" in (refused(run_guard(tail, repo)) or ""), "a heredoc with more after it"


def test_a_gh_api_path_it_cannot_know_still_has_its_body_checked(repo):
    (repo / "b.md").write_text(LONG)
    for path in (
        "repos/o/r/issues/$N/comments",
        "repos/$R/issues/1/comments",
        "repos/o/r/pulls/${PR}",
    ):
        out = run_guard(
            f'N=$(gh pr view --json number -q .number); gh api {path} -f body="$(cat b.md)"', repo
        )
        assert refused(out), path
    notes = f"gh api repos/$R/releases -f body='{words_of(400)}'"
    assert refused(run_guard(notes, repo)) is None, "release notes are no issue or PR"


def test_a_variable_set_any_other_way_is_unknown(repo):
    (repo / "b.md").write_text(LONG)
    for setter in (
        "read -r -d '' B <<'EOF'\nlong\nEOF\n",
        "mapfile B < b.md; ",
        "declare -r B=x; ",
        "",
    ):
        for use in ('"$B"', '"${B:-x}"'):
            out = refused(run_guard(f"{setter}gh pr comment 1 --body {use}", repo))
            assert "does not set" in (out or ""), (setter, use)
    home = 'gh pr comment 1 --body "built in $HOME"'
    assert refused(run_guard(home, repo)) is None, "the hook's own env is known"


def test_stdin_from_a_file_or_a_here_string_is_read(repo):
    (repo / "b.md").write_text(LONG)
    assert refused(run_guard("gh pr comment 1 --body-file - < b.md", repo))
    here = 'gh api repos/o/r/issues/1/comments -F body=@- <<< "$(cat b.md)"'
    assert refused(run_guard(here, repo))
    assert refused(run_guard("gh pr comment 1 --body-file - <<< 'short'", repo)) is None


def test_a_file_another_command_may_change_is_unknown(repo):
    (repo / "b.md").write_text(SHORT)
    for change in (
        "sed -i 's/a/b/' b.md",
        "ln -sf other.md b.md",
        "python3 grow.py b.md",
        "dd if=x of=b.md",
    ):
        out = refused(run_guard(f"{change} && gh pr comment 1 --body-file b.md", repo))
        assert "own call" in (out or ""), change
    reader = "wc -w b.md && gh pr comment 1 --body-file b.md"
    assert refused(run_guard(reader, repo)) is None, "a reader changes nothing"
    made = refused(run_guard('echo hi > f.md; gh pr comment 1 --body "$(cat f.md)"', repo))
    assert made is not None, "a file written another way in this command is not read from disk"


def test_short_outputs_count_and_reads_are_trimmed_as_bash_trims_them(repo):
    sha = 'gh pr comment 1 --body "Fixed in $(git rev-parse --short HEAD)."'
    assert refused(run_guard(sha, repo)) is None
    assert refused(run_guard('gh pr comment 1 --body "$(cat $NOPE/b.md)"', repo))
    (repo / "b.md").write_text(LONG)
    for read in ("B=$(cat -- b.md)", 'B="$(cat -- b.md)"'):
        assert refused(run_guard(f'{read}; gh pr comment 1 --body "$B"', repo)), read
    two = (
        f'A="$(mktemp)"; B="$(mktemp)"; cat > "$A" <<\'X\'\n{SHORT}\nX\n'
        f'cat > "$B" <<\'Y\'\n{LONG}\nY\ngh pr comment 1 --body-file "$B"'
    )
    assert refused(run_guard(two, repo)), "two quoted mktemp names are two files"
    assert refused(run_guard(f"gh api repos/o/r/pulls/1/reviews -f body='{LONG}'", repo))
    (repo / "sub").mkdir()
    (repo / "dir.txt").write_text("sub\n")
    for command in (
        'D=$(cat dir.txt); cd "$D" && git commit -m x',
        'D=$(cat dir.txt); git -C "$D" commit -m x',
    ):
        payload = json.dumps({"cwd": str(repo), "tool_input": {"command": command}})
        proc = subprocess.run(
            [HOOK_PYTHON, str(GUARDS)],
            input=payload,
            capture_output=True,
            text=True,
            env=hook_env(("block_attribution_trailers",)),
            check=False,
        )
        assert (proc.returncode, proc.stdout.strip()) == (0, ""), (command, proc.stdout)


def test_an_append_adds_to_the_variable(repo):
    (repo / "b.md").write_text(LONG)
    grown = 'B="Notes:"; B+=" $(cat b.md)"; gh pr comment 1 --body "$B"'
    assert refused(run_guard(grown, repo))
    assert refused(run_guard('B="a"; B+=" b"; gh pr comment 1 --body "$B"', repo)) is None


def gate_off(command: str, cwd: pathlib.Path) -> tuple[int, str]:
    payload = json.dumps({"cwd": str(cwd), "tool_input": {"command": command}})
    proc = subprocess.run(
        [HOOK_PYTHON, str(GUARDS)],
        input=payload,
        capture_output=True,
        text=True,
        env=hook_env(("block_attribution_trailers", "block_commits_md")),
        check=False,
    )
    return proc.returncode, proc.stdout.strip()


def test_a_short_output_stays_unknown_as_a_folder(repo):
    for command in (
        'ROOT=$(git rev-parse --show-toplevel); cd "$ROOT" && git commit -m fix',
        'ROOT=$(git rev-parse --show-toplevel); git -C "$ROOT" commit -m fix',
        'D=$(pwd); cd "$D" && git add a.txt',
    ):
        assert gate_off(command, repo) == (0, ""), command
    (repo / "b.md").write_text(LONG)
    unknown = 'ROOT=$(git rev-parse --show-toplevel); gh pr comment 1 --body-file "$ROOT/b.md"'
    assert "Name the file" in (refused(run_guard(unknown, repo)) or "")
    dated = 'gh pr comment 1 --body "Built $(date)."'
    assert refused(run_guard(dated, repo)) is None


def test_an_unquoted_heredoc_is_expanded_as_bash_expands_it(repo):
    (repo / "b.md").write_text(LONG)
    for command in (
        "gh pr comment 1 --body-file - <<EOF\n$(cat b.md)\nEOF",
        "B=$(cat b.md)\ngh pr comment 1 --body-file - <<EOF\n$B\nEOF",
        'gh pr comment 1 --body "$(cat <<EOF\nNotes: $(cat b.md)\nEOF\n)"',
    ):
        assert refused(run_guard(command, repo)), command
    quoted = "gh pr comment 1 --body-file - <<'EOF'\n$(cat b.md)\nEOF"
    assert refused(run_guard(quoted, repo)) is None, "a quoted one stays literal"
    unknown = "gh pr comment 1 --body-file - <<EOF\n$(python3 make.py)\nEOF"
    assert "cannot run" in (refused(run_guard(unknown, repo)) or "")


def test_each_stdin_redirect_is_read_or_refused(repo):
    (repo / "b.md").write_text(LONG)
    (repo / "short.md").write_text(SHORT)
    (repo / "in.json").write_text(json.dumps({"body": LONG}))
    for command in (
        "gh pr comment -F - 251 < b.md",
        "gh pr comment 1 --body-file - < short.md < b.md",
        "gh api -X PATCH repos/o/r/pulls/1 --input - < in.json",
    ):
        assert refused(run_guard(command, repo)), command
    for odd in ("gh pr comment 1 --body-file - <&3", "gh pr comment 1 --body-file - < <(cat b.md)"):
        assert "cannot follow" in (refused(run_guard(odd, repo)) or ""), odd
    assert refused(run_guard("gh pr comment 1 --body-file - <<< b.md", repo)) is None, "a word"


def test_more_ways_a_file_changes_and_ways_it_is_only_read(repo):
    (repo / "b.md").write_text(LONG)
    (repo / "sub").mkdir()
    (repo / "sub" / "s.md").write_text(SHORT)
    (repo / "s.md").write_text(SHORT)
    for change, sent in (
        ("sort --output=s.md b.md", "s.md"),
        ("env -C sub sed -i 's/a/b/' s.md", "sub/s.md"),
    ):
        out = refused(run_guard(f"{change}; gh pr comment 1 --body-file {sent}", repo))
        assert "may change" in (out or ""), change
    for read in ("sed -n 1p s.md", "chmod 644 s.md", "awk 1 s.md", "sort s.md"):
        out = refused(run_guard(f"{read}; gh pr comment 1 --body-file s.md", repo))
        assert out is None, read


def test_an_append_keeps_what_the_variable_held(repo):
    (repo / "half.md").write_text(words_of(100))
    first = words_of(100)
    grown = f'B="{first}"; B+=" $(cat half.md)"; gh pr comment 1 --body "$B"'
    assert refused(run_guard(grown, repo)), "100 words held and 100 appended"


def test_a_fifo_body_file_never_hangs_the_hook(repo):
    os.mkfifo(repo / "pipe.md")
    out = run_guard("gh pr comment 1 --body-file pipe.md", repo)
    assert "no regular file" in (refused(out) or ""), "refused, never read"


def test_a_file_written_from_an_unquoted_heredoc_is_expanded(repo):
    (repo / "b.md").write_text(LONG)
    write = "cat > x.md <<EOF\n$(cat b.md)\nEOF\n"
    for send in (
        "gh pr comment 1 --body-file x.md",
        'gh pr comment 1 --body "$(cat x.md)"',
        "gh api repos/o/r/issues/1/comments -F body=@x.md",
    ):
        assert refused(run_guard(write + send, repo)), send
    tee = "tee x.md <<EOF >/dev/null\n$(cat b.md)\nEOF\ngh pr comment 1 --body-file x.md"
    assert refused(run_guard(tee, repo))
    log = "cat > x.md <<EOF\n$(git log --oneline -5)\nEOF\ngh pr comment 1 --body-file x.md"
    assert "unquoted heredoc" in (refused(run_guard(log, repo)) or "")
    literal = "cat > x.md <<EOF\nCosts \\$5 and \\$(cat b.md) stays text.\nEOF\n"
    assert refused(run_guard(literal + "gh pr comment 1 --body-file x.md", repo)) is None


def test_stdin_is_the_last_redirect(repo):
    (repo / "b.md").write_text(LONG)
    (repo / "s.md").write_text(SHORT)
    after = "gh pr comment 1 --body-file - <<'EOF' < b.md\nshort\nEOF"
    assert refused(run_guard(after, repo)), "the file after the heredoc"
    before = "gh pr comment 1 --body-file - < b.md <<'EOF'\nshort\nEOF"
    assert refused(run_guard(before, repo)) is None, "the heredoc after the file"
    titled = "gh pr create --title '<draft> x' --body-file - < s.md"
    assert refused(run_guard(titled, repo)) is None, "a quoted < in a title is a word"
    here = "gh pr comment 1 --body-file - <<< '<details>short</details>'"
    assert refused(run_guard(here, repo)) is None


def test_in_place_options_inside_a_cluster_count(repo):
    (repo / "b.md").write_text(LONG)
    (repo / "x.md").write_text(SHORT)
    for change in (
        "sed -Ei 's/a/b/' x.md",
        "sed -ni 'p' x.md",
        "sort -uo x.md b.md",
        "uniq b.md x.md",
    ):
        out = refused(run_guard(f"{change}; gh pr comment 1 --body-file x.md", repo))
        assert "may change" in (out or ""), change
    for read in ("sed -E 's/a/b/' x.md", "sort -u x.md"):
        assert refused(run_guard(f"{read}; gh pr comment 1 --body-file x.md", repo)) is None, read


def test_a_refusal_never_shows_the_internal_tag(repo):
    out = refused(
        run_guard('R=$(git rev-parse --show-toplevel); gh pr comment 1 --body-file "$R/b.md"', repo)
    )
    assert out and " #" not in out


def test_a_written_heredoc_holding_an_expansion_is_unknown_wherever_it_is_sent(repo):
    (repo / "b.md").write_text(LONG)
    (repo / "sub").mkdir()
    for command in (
        "cat > h.md <<EOF\n$(cat b.md)\nEOF\ncd sub && gh pr comment 1 --body-file ../h.md",
        'N="$(cat b.md)"; cat > h.md <<EOF\n$N\nEOF\nN=short; gh pr comment 1 --body-file h.md',
        'cat > h.md <<EOF\n$(cat b.md)\nEOF\nB=$(cat h.md); cd sub && gh pr comment 1 --body "$B"',
    ):
        assert refused(run_guard(command, repo)), command
    plain = "cat > h.md <<EOF\nNo expansion here.\nEOF\ngh pr comment 1 --body-file h.md"
    assert refused(run_guard(plain, repo)) is None


def test_a_name_read_from_a_file_is_never_taken_for_a_heredoc(repo):
    (repo / "b.md").write_text(LONG)
    (repo / "name.txt").write_text("b.md\n")
    for command in (
        'cat > n.txt <<\'EOF\'\nb.md\nEOF\nF=$(cat n.txt); gh pr comment 1 --body "$(cat "$F")"',
        'F=$(cat name.txt); gh pr comment 1 --body "$(cat "$F")"',
        'gh pr comment 1 --body "$(cat $(cat name.txt))"',
    ):
        assert refused(run_guard(command, repo)), command


def test_stdin_paths_and_odd_files_are_read_or_refused(repo):
    (repo / "b.md").write_text(LONG)
    for command in (
        f"gh pr comment 1 --body-file /dev/stdin <<'EOF'\n{LONG}\nEOF",
        "gh pr comment 1 --body-file /dev/stdin < b.md",
        "gh pr comment 1 --body-file /dev/fd/0 < b.md",
        "gh api repos/o/r/issues/1/comments -F body=@/dev/stdin < b.md",
        "gh pr comment 1 --body-file <(cat b.md)",
    ):
        assert refused(run_guard(command, repo)), command
    short = "gh pr comment 1 --body-file /dev/stdin <<'EOF'\nshort\nEOF"
    assert refused(run_guard(short, repo)) is None


def test_backslashes_in_an_unquoted_heredoc_read_as_bash_reads_them(repo):
    (repo / "b.md").write_text(LONG)
    doubled = "gh pr comment 1 --body-file - <<EOF\nsee \\\\$(cat b.md)\nEOF"
    assert refused(run_guard(doubled, repo)), "an escaped backslash leaves the $(...) live"
    joined = "gh pr comment 1 --body-file - <<EOF\none \\\ntwo\nEOF"
    assert refused(run_guard(joined, repo)) is None


def test_a_dash_heredoc_after_a_file_wins_and_awk_in_place_writes(repo):
    (repo / "b.md").write_text(LONG)
    dash = "gh pr comment 1 --body-file - < b.md <<-EOF\n\tshort\n\tEOF"
    assert refused(run_guard(dash, repo)) is None, "the last redirect is the heredoc"
    (repo / "x.md").write_text(SHORT)
    awk = "awk -i inplace '{print}' x.md; gh pr comment 1 --body-file x.md"
    assert "may change" in (refused(run_guard(awk, repo)) or "")


def test_a_trailing_backslash_joins_before_the_delimiter_is_seen(repo):
    first = f"gh pr comment 1 --body-file - <<EOF\nshort\\\nEOF\n{LONG}\nEOF"
    assert refused(run_guard(first, repo)), "bash reads past the first EOF"
    dash = f"gh pr comment 1 --body-file - <<-EOF\n\tshort\\\n\tEOF\n{LONG}\n\tEOF"
    assert refused(run_guard(dash, repo))
    written = f"cat > h.md <<EOF\nshort\\\nEOF\n{LONG}\nEOF\ngh pr comment 1 --body-file h.md"
    assert refused(run_guard(written, repo))
    quoted = f"gh pr comment 1 --body-file - <<'EOF'\nshort\\\nEOF\necho {LONG}"
    assert refused(run_guard(quoted, repo)) is None, "a quoted heredoc keeps its backslash"
    near = f"gh pr comment 1 --body-file - <<EOF\n{words_of(164)} wo\\\nrd\nEOF"
    assert refused(run_guard(near, repo)) is None, "165 words once the halves join"


def test_odd_stdin_and_body_files_are_named(repo):
    out = run_guard("gh pr comment 1 --body-file - < /dev/stdin", repo)
    assert refused(out) is None, "the shell's own stdin, passed through, never loops"
    assert refused(run_guard("gh pr edit 1 --body-file /dev/null", repo)) is None
    sub = refused(run_guard("gh pr comment 1 --body-file <(cat b.md)", repo))
    assert "process substitution" in (sub or "")
    empty = refused(run_guard("gh pr comment 1 --body-file ''", repo))
    assert "empty name" in (empty or "")
    (repo / "dir").mkdir()
    assert "folder" in (refused(run_guard("gh pr comment 1 --body-file dir", repo)) or "")
    fd0 = "gh pr comment 1 --body-file /dev/fd/0 <<'EOF'\nshort\nEOF"
    assert refused(run_guard(fd0, repo)) is None, "/dev/fd/0 is stdin, not a device to refuse"


def test_escapes_and_backticks_in_unquoted_heredocs_read_exactly(repo):
    (repo / "b.md").write_text(LONG)
    escaped = "gh pr comment 1 --body-file - <<EOF\nsee \\$(cat b.md) here\nEOF"
    assert refused(run_guard(escaped, repo)) is None, "an escaped $ is text"
    code = "cat > h.md <<EOF\nrun \\`make\\` first\nEOF\ngh pr comment 1 --body-file h.md"
    assert refused(run_guard(code, repo)) is None, "an escaped backtick is text"
    live = "cat > h.md <<EOF\nrun `make` first\nEOF\ngh pr comment 1 --body-file h.md"
    assert "unquoted heredoc" in (refused(run_guard(live, repo)) or ""), "a live backtick"


def test_the_join_reads_as_bash_reads_it(repo):
    even = f"gh pr comment 1 --body-file - <<EOF\nshort\\\\\nEOF\necho {LONG}"
    assert refused(run_guard(even, repo)) is None, "an even run of backslashes joins nothing"
    joined = f"gh pr comment 1 --body-file - <<EOF\nEO\\\nF\n{LONG}\nEOF"
    assert refused(run_guard(joined, repo)) is None, "the joined line is the delimiter"
    split = f"gh pr comment 1 --body-file - <<-EOF\nE\\\n\tOF\n{LONG}\nEOF"
    assert refused(run_guard(split, repo)), "E<tab>OF is no delimiter, so the body runs on"
    commit = (
        "git commit -F - <<-EOF\nfeat\nE\\\n\tOF\n"
        "Co-Authored-By: Claude <noreply@anthropic.com>\nEOF"
    )
    payload = json.dumps({"cwd": str(repo), "tool_input": {"command": commit}})
    proc = subprocess.run(
        [HOOK_PYTHON, str(GUARDS)],
        input=payload,
        capture_output=True,
        text=True,
        env=hook_env(("block_attribution_trailers",)),
        check=False,
    )
    assert "attribution" in proc.stdout, "gate off: the attribution line is in the message"


def test_dev_stdin_after_another_redirect_is_refused(repo):
    (repo / "b.md").write_text(LONG)
    for command in (
        f"gh pr comment 1 --body-file - <<'EOF' < /dev/stdin\n{LONG}\nEOF",
        "gh pr comment 1 --body-file - < b.md < /dev/stdin",
    ):
        assert "reopens" in (refused(run_guard(command, repo)) or ""), command


def test_the_delimiter_is_the_whole_line_after_dash_tabs(repo):
    dash = f"gh pr comment 1 --body-file - <<-EOF\n\tshort\n\tEOF\necho {LONG}"
    assert refused(run_guard(dash, repo)) is None, "<<- ends at the tab-indented EOF"
    plain = f"gh pr comment 1 --body-file - <<EOF\n\tEOF\n{LONG}\nEOF"
    assert refused(run_guard(plain, repo)), "<< does not strip tabs, so the body runs on"
    here = "gh pr comment 1 --body-file - <<< hi < /dev/stdin"
    assert "reopens" in (refused(run_guard(here, repo)) or "")


def test_other_flags_values_and_fill_are_handled(repo):
    long_with_title = f"gh pr create --body '{LONG}' --title '-Fix crash'"
    assert refused(run_guard(long_with_title, repo)), "a title starting with -F is no body file"
    bump = f"gh pr create --title '-bump deps' --body '{LONG}'"
    assert refused(run_guard(bump, repo)), "a title starting with -b is no body"
    for fill in ("--fill", "-f", "--fill-first", "--fill-verbose"):
        out = refused(run_guard(f"gh pr create {fill}", repo))
        assert "--fill" in (out or ""), fill
    assert refused(run_guard("gh pr create --fill --body 'short'", repo)) is None


def test_a_crlf_opener_keeps_its_carriage_return(repo):
    crlf = f"gh pr comment 1 --body-file - <<EOF\r\nshort\nEOF\n{LONG}\nEOF\r\n"
    assert refused(run_guard(crlf, repo)), "bash's delimiter is EOF\\r"


def test_a_written_file_refusal_never_shows_the_internal_tag(repo):
    out = refused(run_guard('T=$(mktemp); echo x > "$T"; gh pr comment 1 --body-file "$T"', repo))
    assert out and " #" not in out


@pytest.mark.parametrize(
    "command",
    [
        "gh pr review 4 -a -b '{L}'",
        "gh pr review 4 -r -b '{L}'",
        "gh pr review 4 -c -b '{L}'",
        "gh pr review 4 -a --body-file b.md",
        "gh pr review 4 -rb '{L}'",
        "gh pr review 4 -cb'{L}'",
        "gh pr comment 4 -e -b '{L}'",
        "gh pr create -d -b '{L}'",
        "gh pr create -dt title -b '{L}'",
        "gh pr create --title=-Fix -b '{L}'",
        "gh pr create -t '-Fix crash' --body '{L}'",
        "gh issue comment 4 -e -b '{L}'",
        "gh pr edit 3 -t x -b '{L}'",
        "gh pr review 4 -cF=b.md",
        "gh pr create -t t -dF=b.md",
        "gh issue comment 4 -eF=b.md",
        "gh pr review 4 -cb='{L}'",
    ],
)
def test_a_body_after_any_other_option_is_read(repo, command):
    (repo / "b.md").write_text(LONG)
    assert refused(run_guard(command.format(L=LONG), repo)), command


def test_fill_is_read_where_gh_reads_it(repo):
    for fill in ("-df", "-fd", "--fill-verbose"):
        assert "--fill" in (refused(run_guard(f"gh pr create {fill}", repo)) or ""), fill
    assert refused(run_guard("gh pr edit 3 --title --fill-in", repo)) is None, "a value, on edit"
    assert refused(run_guard("gh pr create -t --fill -b short", repo)) is None, "a title"


def test_a_marker_after_a_grouped_equals_is_still_seen(repo):
    assert "budget" in (refused(run_guard("gh pr review 4 -cb='% budget: 100'", repo)) or "")


@pytest.mark.parametrize(
    "command",
    [
        "gh pr create -t x -d=t -b '{L}'",
        "gh pr comment 3 -e=F -b '{L}'",
        "gh pr create -t x -d=T -F b.md",
        "gh pr -b '{L}' comment 3",
        "gh pr -F b.md comment 3",
        "gh pr --body-file b.md comment 3",
        "gh pr review 4 -c -F=b.md",
    ],
)
def test_options_read_as_gh_reads_them(repo, command):
    (repo / "b.md").write_text(LONG)
    assert refused(run_guard(command.format(L=LONG), repo)), command


def test_recover_takes_a_value(repo):
    out = refused(run_guard(f"gh pr create --recover -b '{LONG}'", repo))
    assert out is None, "-b is the recover file's name, so no body is given"


@pytest.fixture
def fake_github(tmp_path):
    """gh's environment pointed at the fake GitHub, and its request log."""
    import socket
    import time

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    log = tmp_path / "requests.jsonl"
    server = subprocess.Popen(
        [sys.executable, str(FIXTURES / "fake_github.py"), str(port), str(log)]
    )
    proxy = f"http://127.0.0.1:{port}"
    env = dict(
        os.environ,
        GH_CONFIG_DIR=str(tmp_path / "gh"),
        GH_TOKEN="x",
        GH_ENTERPRISE_TOKEN="x",
        GH_HOST="github.localhost",
        HTTP_PROXY=proxy,
        http_proxy=proxy,
        HTTPS_PROXY="",
        https_proxy="",
        NO_PROXY="",
        no_proxy="",
        GH_PROMPT_DISABLED="1",
        GH_NO_UPDATE_NOTIFIER="1",
    )
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    yield env, log
    server.terminate()
    server.wait(timeout=10)


@pytest.mark.skipif(shutil.which("gh") is None, reason="needs gh")
def test_the_body_read_is_the_body_gh_sends(tmp_path, fake_github):
    """Differential: random body and switch options, long and short, grouped, before and
    after the subcommand, for three subcommands. gh sends the body to a fake GitHub that
    logs it; the hook's walk must read that same body."""
    env, log = fake_github
    guards = _load("phylax_git_guards_diff", GUARDS)
    files = tmp_path / "files"
    files.mkdir()
    subs = {
        ("pr", "review"): ["-a", "-c", "-r", "--approve", "--comment", "--request-changes"],
        ("pr", "comment"): [],
        ("issue", "comment"): [],
    }
    rng = random.Random(229)
    sent = 0
    for t in range(200):
        words = rng.choice(list(subs))
        count = iter(range(100))

        def text(t: int = t, count=count) -> str:
            return f"T{t}_{next(count)}"

        def name(t: int = t, count=count) -> str:
            made = f"f{t}_{next(count)}"
            (files / made).write_text(f"FILE {made}")
            return made

        def piece(words: tuple[str, str] = words) -> list[str]:
            switches = subs[words]
            kind = rng.choice(
                ["b", "F", "long", "longF", "sw", "group", "eqb", "eqF", "lone", "val"]
            )
            if kind == "lone":
                return [rng.choice(["-b", "-F", "--body", "--body-file"])]
            if kind == "val":
                return [rng.choice([text(), name()])]
            if kind == "b":
                return ["-b", text()]
            if kind == "F":
                return ["-F", name()]
            if kind == "long":
                return ["--body", text()]
            if kind == "longF":
                return ["--body-file", name()]
            if kind == "eqb":
                return [f"--body={text()}"]
            if kind == "eqF":
                return [f"--body-file={name()}"]
            if kind == "sw":
                return [rng.choice(switches)] if switches else ["-b", text()]
            pool = "".join(s[1] for s in switches if len(s) == 2) + "bF"
            group = "".join(rng.choice(pool) for _ in range(rng.randrange(1, 3)))
            return [f"-{group}"] + ([rng.choice([text(), name()])] if rng.random() < 0.7 else [])

        before = [w for _ in range(rng.randrange(0, 3)) for w in piece()]
        after = [w for _ in range(rng.randrange(0, 3)) for w in piece()]
        args = [words[0], *before, words[1], *after, "1", "-R", "github.localhost/o/r"]
        log.write_text("")
        subprocess.run(
            ["gh", *args], capture_output=True, text=True, env=env, timeout=20, cwd=files
        )
        mutations = [
            json.loads(r["body"])
            for r in map(json.loads, log.read_text().splitlines())
            if "mutation" in r.get("body", "")
        ]
        if not mutations:
            continue
        gh_body = mutations[-1]["variables"]["input"]["body"]
        g = guards.Guards([], "")
        g.enabled = lambda *a, **k: True
        g.read_body = lambda flag, value, cwd, env: (
            value
            if flag in ("-b", "--body")
            else (files / value).read_text()
            if (files / value).is_file()
            else f"<file {value}>"
        )
        read: list[str | None] = []
        walk = g.gh_body
        g.gh_body = lambda *a, walk=walk, read=read, **k: read.append(walk(*a, **k)) or read[-1]
        real = guards.body_gate.check
        guards.body_gate.check = lambda kind, body: ([], [])
        try:
            g.check_gh(["gh", *args], files, {})
        finally:
            guards.body_gate.check = real
        assert ((read[-1] if read else None) or "") == gh_body, (args, gh_body, read)
        sent += 1
    assert sent > 20, f"gh sent only {sent} bodies"


@pytest.mark.parametrize(
    "command",
    [
        "gh pr -a -b review '{L}' 1",
        "gh pr --approve --body review '{L}' 1",
        "gh pr --edit-last -b comment '{L}' 1",
        "gh pr -c -F review b.md 1",
        "gh -f body='{L}' api repos/o/r/issues/1/comments",
        "gh -F body=@b.md api repos/o/r/issues/1/comments",
        "gh -p api api repos/o/r/issues/1/comments -f body='{L}'",
    ],
)
def test_options_before_the_subcommand_take_the_next_word(repo, command):
    (repo / "b.md").write_text(LONG)
    assert refused(run_guard(command.format(L=LONG), repo)), command


def test_a_lone_equals_is_the_file_named_equals(repo):
    (repo / "=").write_text(SHORT)
    assert refused(run_guard("gh pr review 4 -cF=", repo)) is None, "gh opens the file `=`"
