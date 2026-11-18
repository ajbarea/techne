"""Golden tests for the pure helpers of command_shapes.py: each case pins what the helper returns
for an input whose right answer is bash's (or procps's) own rule, checked by hand when the table
was written. They exist so that a change to a helper that no end-to-end case happens to reach
(a boundary, a separator, a flag spelling) fails here, not in a mutation run.
"""

# ruff: noqa: E501  (the tables hold whole commands)

from __future__ import annotations

import pytest
from conftest import load_phylax_hooks


@pytest.fixture
def cs(monkeypatch):
    (mod,) = load_phylax_hooks(monkeypatch, "command_shapes")
    return mod


def lex(cs, text, closer=False):
    lexer = cs.Lexer(text)
    toks = lexer.tokens(closer=closer)
    kinds = [("op" if isinstance(t, cs.Op) else ("q" if t.quoted else "w"), str(t)) for t in toks]
    subs = [(s.code, s.tokens is not None, len(s.subs)) for s in lexer.subs]
    return kinds, subs, lexer.unclosed, lexer.i


def groups(cs, text):
    return cs.commands(cs.Lexer(text).tokens())


LEXER = [
    ("a b", [("w", "a"), ("w", "b")], [], False, 3),
    ("a#b c", [("w", "a#b"), ("w", "c")], [], False, 5),
    ("a #c\nb", [("w", "a"), ("op", "\n"), ("w", "b")], [], False, 6),
    ("a # it's\nb", [("w", "a"), ("op", "\n"), ("w", "b")], [], False, 10),
    ("x #", [("w", "x")], [], False, 3),
    ("echo hi # c", [("w", "echo"), ("w", "hi")], [], False, 11),
    ("a\\ b", [("w", "a b")], [], False, 4),
    ("a\\", [("w", "a")], [], False, 3),
    ("'a b' c", [("q", "a b"), ("w", "c")], [], False, 7),
    ("'unterminated", [("q", "unterminated")], [], True, 14),
    ('"a b" c', [("q", "a b"), ("w", "c")], [], False, 7),
    ('"a\\"b"', [("q", 'a"b')], [], False, 6),
    ('"a\\\\b"', [("q", "a\\b")], [], False, 6),
    ('"a\\$b"', [("q", "a$b")], [], False, 6),
    ('"a\\`b"', [("q", "a`b")], [], False, 6),
    ('"a\\nb"', [("q", "a\\nb")], [], False, 6),
    ('"$(echo x)"', [("q", "$(echo x)")], [("echo x", True, 0)], False, 11),
    ('"`echo x`"', [("q", "`echo x`")], [("echo x", False, 0)], False, 10),
    ('"${x:-a}"', [("q", "${x:-a}")], [], False, 9),
    ('"unterminated', [("q", "unterminated")], [], True, 13),
    ("a$(b c)d", [("w", "a$(b c)d")], [("b c", True, 0)], False, 8),
    ("a`b c`d", [("w", "a`b c`d")], [("b c", False, 0)], False, 7),
    ("a${x}b", [("w", "a${x}b")], [], False, 6),
    ("a<(b)c", [("w", "a<(b)c")], [("b", True, 0)], False, 6),
    ("a>(b)c", [("w", "a>(b)c")], [("b", True, 0)], False, 6),
    ("a<b", [("w", "a"), ("op", "<"), ("w", "b")], [], False, 3),
    ("2>&1", [("op", "2>&")], [], False, 4),
    ("2>x", [("op", "2>")], [], False, 3),
    ("a 2>x", [("w", "a"), ("op", "2>")], [], False, 5),
    ("'2'>x", [("q", "2"), ("op", ">"), ("w", "x")], [], False, 5),
    ("x>y", [("w", "x"), ("op", ">"), ("w", "y")], [], False, 3),
    ("(a)", [("op", "("), ("w", "a"), ("op", ")")], [], False, 3),
    ("a;b", [("w", "a"), ("op", ";"), ("w", "b")], [], False, 3),
    (
        "a&&b||c|d",
        [("w", "a"), ("op", "&&"), ("w", "b"), ("op", "||"), ("w", "c"), ("op", "|"), ("w", "d")],
        [],
        False,
        9,
    ),
    ("a &", [("w", "a"), ("op", "&")], [], False, 3),
    ("a\nb", [("w", "a"), ("op", "\n"), ("w", "b")], [], False, 3),
    ("$((1+2))", [("w", "$((1+2))")], [], False, 8),
    ("$( (a) )", [("w", "$( (a) )")], [(" (a) ", True, 0)], False, 8),
    ("$(a $(b))", [("w", "$(a $(b))")], [("a $(b)", True, 1)], False, 9),
    ("$(a", [("w", "$(a")], [("", True, 0)], True, 3),
    ("`a", [("w", "`a")], [("a", False, 0)], True, 3),
    ("${x:-'}'}", [("w", "${x:-'}'}")], [], False, 9),
    ('${x:-"}"}', [("w", '${x:-"}"}')], [], False, 9),
    ("${x:-$(a)}", [("w", "${x:-$(a)}")], [("a", True, 0)], False, 10),
    ("${x:-{a}}", [("w", "${x:-{a}}")], [], False, 9),
    ("${x", [("w", "${x")], [], True, 3),
    ("${x:-\\}}", [("w", "${x:-\\}}")], [], False, 8),
    ("${x:-'a", [("w", "${x:-'a")], [], True, 7),
    ("a|&b", [("w", "a"), ("op", "|&"), ("w", "b")], [], False, 4),
    ("a<<<b", [("w", "a"), ("op", "<<<"), ("w", "b")], [], False, 5),
    ("a>>b", [("w", "a"), ("op", ">>"), ("w", "b")], [], False, 4),
    ("a>|b", [("w", "a"), ("op", ">|"), ("w", "b")], [], False, 4),
    ("a&>b", [("w", "a"), ("op", "&>"), ("w", "b")], [], False, 4),
    ("a<&3", [("w", "a"), ("op", "<&"), ("w", "3")], [], False, 4),
    ("a;;b", [("w", "a"), ("op", ";;"), ("w", "b")], [], False, 4),
    ("a;&b", [("w", "a"), ("op", ";&"), ("w", "b")], [], False, 4),
    ("((a))", [("op", "("), ("op", "("), ("w", "a"), ("op", ")"), ("op", ")")], [], False, 5),
    ("a\tb\rc", [("w", "a"), ("w", "b"), ("w", "c")], [], False, 5),
    ("echo \"a\" 'b' c", [("w", "echo"), ("q", "a"), ("q", "b"), ("w", "c")], [], False, 14),
    (
        "(( x = 1 ))",
        [("op", "("), ("op", "("), ("w", "x"), ("w", "="), ("w", "1"), ("op", ")"), ("op", ")")],
        [],
        False,
        11,
    ),
]

CLOSER = [
    ("a b) c", [("w", "a"), ("w", "b")], [], False, 4),
    ("a (b) c) d", [("w", "a"), ("op", "("), ("w", "b"), ("op", ")"), ("w", "c")], [], False, 8),
    ("a b", [("w", "a"), ("w", "b")], [], True, 3),
    (") x", [], [], False, 1),
    ("a $(b) c) d", [("w", "a"), ("w", "$(b)"), ("w", "c")], [("b", True, 0)], False, 9),
]


@pytest.mark.parametrize("row", LEXER, ids=[r[0] for r in LEXER])
def test_the_lexer_reads_bash_words_quotes_and_substitutions(cs, row):
    text, kinds, subs, unclosed, pos = row
    assert lex(cs, text) == (kinds, subs, unclosed, pos)


@pytest.mark.parametrize("row", CLOSER, ids=[r[0] for r in CLOSER])
def test_a_lexer_inside_dollar_paren_stops_at_its_closing_paren(cs, row):
    text, kinds, subs, unclosed, pos = row
    assert lex(cs, text, closer=True) == (kinds, subs, unclosed, pos)


ON_CLOCK = [
    ("while [ $SECONDS -lt 9 ]; do sleep 1; done", [True]),
    ("until [ $SECONDS -gt 9 ]; do sleep 1; done", [True]),
    ("while (( SECONDS < 9 )); do sleep 1; done", [True]),
    ("while echo SECONDS; do sleep 1; done", [False]),
    ("while echo $SECONDS; do sleep 1; done", [False]),
    ("while true; do sleep 1; done", [False]),
    ("while true", [False]),
    ("while true; do [ $SECONDS -gt 9 ] && break; sleep 1; done", [True]),
    ("while true; do [ $SECONDS -gt 9 ] && exit 1; sleep 1; done", [True]),
    ("while true; do [ $SECONDS -gt 9 ] || break; sleep 1; done", [True]),
    ("while true; do [ $SECONDS -gt 9 ] && return; sleep 1; done", [False]),
    ("while true; do [ $SECONDS -gt 9 ] && echo late; sleep 1; done", [False]),
    ("while true; do [ $SECONDS -gt 9 ] && echo late; break; done", [False]),
    ("while true; do [ $SECONDS -gt 9 ]; break; done", [False]),
    ("while true; do [ $SECONDS -gt 9 ]\nbreak; done", [False]),
    ("while true; do [ $SECONDS -gt 9 ] &&\nbreak; done", [True]),
    ("while true; do [ $SECONDS -gt 9 ] && { echo late; exit 1; }; sleep 1; done", [True]),
    ("while true; do [ $SECONDS -gt 9 ] && { echo late; }; exit 1; done", [False]),
    ("while true; do [ $SECONDS -gt 9 ] && { { echo; } }; break; done", [False]),
    ("while true; do [ $SECONDS -gt 9 ] && { { echo; exit 1; } }; done", [True]),
    ("while true; do { [ $SECONDS -gt 9 ] && { echo; } }; curl x && break; done", [False]),
    ("while true; do { [ $SECONDS -gt 9 ] && { echo late; exit 1; } }; sleep 1; done", [True]),
    ("while true; do if [ $SECONDS -gt 9 ]; then break; fi; sleep 1; done", [True]),
    ("while true; do if [ $SECONDS -gt 9 ]; then echo late; exit 1; fi; sleep 1; done", [True]),
    ("while true; do if [ $SECONDS -gt 9 ]; then echo late; else break; fi; done", [False]),
    ("while true; do if [ $SECONDS -gt 9 ]; then echo a; elif x; then break; fi; done", [False]),
    ("while true; do if foo && [ $SECONDS -gt 1 ]; then break; fi; sleep 1; done", [False]),
    ("while true; do if (( SECONDS > 9 )); then break; fi; done", [True]),
    ("while true; do [ $SECONDS -gt 9 ] && echo late; if x; then break; fi; done", [False]),
    ("while true; do [ $SECONDS -gt 9 ] && [ -f done ] && break; done", [False]),
    ("while true; do [ $SECONDS -gt 9 ] && echo a && break; done", [True]),
    ("while true; do [ $SECONDS -gt 9 ] && echo a || break; done", [True]),
    ("while true; do [ $SECONDS -gt 9 ] && echo $SECONDS; done", [False]),
    ("while true; do for i in 1; do [ $SECONDS -gt 9 ] && break; done; sleep 1; done", [False]),
    ("while true; do for i in 1; do [ $SECONDS -gt 9 ] && break 2; done; sleep 1; done", [True]),
    ("while true; do for i in 1; do [ $SECONDS -gt 9 ] && break 3; done; done", [True]),
    ("while true; do for i in 1; do [ $SECONDS -gt 9 ] && exit 1; done; done", [True]),
    (
        "while true; do for i in 1; do for j in 1; do [ $SECONDS -gt 9 ] && break 2; done; done; done",
        [False],
    ),
    (
        "while true; do for i in 1; do for j in 1; do [ $SECONDS -gt 9 ] && break 3; done; done; done",
        [True],
    ),
    ("while true; do [ $SECONDS -gt 9 ] && break 1; done", [True]),
    (
        "while true; do [ $SECONDS -gt 9 ] && break; done; while true; do sleep 1; done",
        [True, False],
    ),
    ("while true; do ( [ $SECONDS -gt 9 ] && exit ); sleep 1; done", [False]),
    ("while true; do (( SECONDS > 9 )) && exit 1; sleep 1; done", [True]),
    ("while true; do [ $SECONDS -gt 9 ] && while x; do y; done; break; done", [False, False]),
    (
        "while true; do [ $SECONDS -gt 9 ] && echo late; until x; do y; done; break; done",
        [False, False],
    ),
    ("while true; do [ $SECONDS -gt 9 ] && echo late; case x in a) break;; esac; done", [False]),
    ("while true; do [ $SECONDS -gt 9 ] && echo late; for f in a; do break; done; done", [False]),
    ("while true; do test $SECONDS -gt 9 && break; done", [True]),
    ("while true; do [[ $SECONDS -gt 9 ]] && break; done", [True]),
    ("while true; do echo $SECONDS && break; done", [False]),
    ("while true; do echo SECONDS && break; done", [False]),
    ("while true; do [ $SECONDS -gt 9 ] && break", [True]),
    ("while true; do sleep 1", [False]),
    ("while a; do break; done; while [ $SECONDS -lt 9 ]; do x; done", [False, True]),
]


@pytest.mark.parametrize("row", ON_CLOCK, ids=[r[0] for r in ON_CLOCK])
def test_on_clock_per_loop(cs, row):
    text, want = row
    g = groups(cs, text)
    loop_at = [i for i, c in enumerate(g) if cs.loops(c)]
    assert [cs.on_clock(g, i) for i in loop_at] == want


# --- the groups of a command, and what each helper reads from them -------------------------

COMMANDS = [
    ("a;b", [(["a"], "", 0), (["b"], ";", 0)]),
    ("a && b", [(["a"], "", 0), (["b"], "&&", 0)]),
    ("a &&\nb", [(["a"], "", 0), (["b"], "&&", 0)]),
    ("a ||\n b", [(["a"], "", 0), (["b"], "||", 0)]),
    ("a |\n b", [(["a"], "", 0), (["b"], "|", 0)]),
    ("a |&\n b", [(["a"], "", 0), (["b"], "|&", 0)]),
    ("a;\nb", [(["a"], "", 0), (["b"], "\n", 0)]),
    ("a\n\nb", [(["a"], "", 0), (["b"], "\n", 0)]),
    ("(a; b); c", [(["a"], "(", 1), (["b"], ";", 1), (["c"], ";", 0)]),
    ("((a)); b", [(["a"], "(", 2), (["b"], ";", 0)]),
    ("a) b", [(["a"], "", 0), (["b"], ")", 0)]),  # a `)` with no `(` closes nothing
    (
        "case x in a) b;; esac",
        [(["case", "x", "in", "a"], "", 0), (["b"], ")", 0), (["esac"], ";;", 0)],
    ),
    ("a & b", [(["a"], "", 0), (["b"], "&", 0)]),
    ("if x; then y; fi", [(["if", "x"], "", 0), (["then", "y"], ";", 0), (["fi"], ";", 0)]),
]


@pytest.mark.parametrize(("text", "want"), COMMANDS, ids=[c[0] for c in COMMANDS])
def test_commands_split_at_separators_and_keep_the_one_before(cs, text, want):
    assert [([str(w) for w in g], g.sep, g.parens) for g in groups(cs, text)] == want


COMMAND_START = [
    ("echo a", 0), ("! echo a", 1), ("{ echo a", 1), ("if echo a", 1), ("then echo a", 1),
    ("do echo a", 1), ("coproc echo a", 1), ("time echo a", 1), ("time -p echo a", 2),
    ("time -p -- echo a", 3), ("time", 1), ("function f { echo a", 3), ("function", 2),
    ("else if then x", 3), ("'if' x", 0), ("if", 1), ("( x", 0),
]  # fmt: skip


@pytest.mark.parametrize(("text", "want"), COMMAND_START, ids=[c[0] for c in COMMAND_START])
def test_command_start_skips_keywords_headers_and_time_options(cs, text, want):
    assert cs.command_start(groups(cs, text)[0]) == want


def test_command_start_of_no_words_is_zero(cs):
    assert cs.command_start([]) == 0


LOOPS = [
    ("while x", "wait"), ("until x", "wait"), ("! while x", "wait"), ("do while x", "wait"),
    ("'while' x", ""), ("while read l", "read"), ("while IFS= read -r l", "read"),
    ("while FOO=1 read l", "read"), ("until read l", "wait"), ("while =x read", "wait"),
    ("while", "wait"), ("echo while", ""), ("while A=1 B=2 read x", "read"),
    ("while read", "read"), ("{ until x", "wait"),
]  # fmt: skip


@pytest.mark.parametrize(("text", "want"), LOOPS, ids=[c[0] for c in LOOPS])
def test_loops_names_the_kind_of_loop_a_command_opens(cs, text, want):
    assert cs.loops(groups(cs, text)[0]) == want


LOOP_EXTENT = [
    ("while x; do y; done", (1, 2), False),
    ("while x; do while z; do y; done; done", (1, 4), False),
    ("while x", (None, None), False),
    ("while x; do y", (1, None), False),
    ("a; while x; do y; done; b", (2, 3), False),
    ("while read l; do y; done < f", (1, 2), True),
    ("while read l; do y; done <<< x", (1, 2), True),
    ("while read l; do y; done << EOF", (1, 2), True),
    ("while read l; do y; done < /dev/tty", (1, 2), False),
    ("while read l; do y; done < /dev/null", (1, 2), True),
    ("while read l; do y; done < <(x)", (1, 2), False),
    ("while read l; do y; done 0< f", (1, 2), True),
    ("while read l; do y; done", (1, 2), False),
    ("while read l; do y; done < /dev/stdin", (1, 2), False),
    ("while read l; do y; done > out", (1, 2), False),
]


@pytest.mark.parametrize(("text", "extent", "ends"), LOOP_EXTENT, ids=[c[0] for c in LOOP_EXTENT])
def test_loop_extent_and_whether_a_read_loop_ends(cs, text, extent, ends):
    g = groups(cs, text)
    k = next(i for i, c in enumerate(g) if cs.loops(c))
    assert cs.loop_extent(g, k) == extent
    assert cs.reads_to_end(g, k) is ends


CLOCK_TEST = [
    ("[ $SECONDS -gt 9 ]", True, True), ("[[ $SECONDS -gt 9 ]]", True, True),
    ("test $SECONDS -gt 9", True, True), ("(( SECONDS > 9 ))", True, False),
    ("echo $SECONDS", False, False), ("[ -f x ]", False, True),
    ("while [ $SECONDS -lt 9 ]", True, False), ("until test $SECONDS -gt 1", True, False),
    ("echo SECONDS", False, False), ("if [ ${SECONDS} -gt 1 ]", True, True),
    ("echo [ $SECONDS", False, False), ("time [ $SECONDS -gt 1 ]", True, True),
    ("! [ $SECONDS -gt 1 ]", True, True), ("SECONDS", False, False),
    ("[ x$SECONDS ]", True, True),
]  # fmt: skip


@pytest.mark.parametrize(("text", "clock", "test"), CLOCK_TEST, ids=[c[0] for c in CLOCK_TEST])
def test_a_clock_test_is_a_bracket_or_arithmetic_command_that_names_seconds(cs, text, clock, test):
    g = groups(cs, text)[0]
    assert (cs._reads_clock(g), cs._is_test(g)) == (clock, test)


ARITHMETIC_FORS = [
    ("for ((;;)); do x; done", [True]), ("for ((i=0;i<3;i++)); do x; done", [False]),
    ("for ((;1;)); do x; done", [False]), ("for ((i=0;;i++)); do x; done", [True]),
    ("for i in 1; do x; done", []), ("for ((;;)); for ((;;)); do x; done", [True, True]),
    ("for ((i=0;i<3;i++)); for ((;;)); do x; done", [False, True]),
    ("for (( ; ; )); do x", [True]), ("'for' ((;;))", [True]), ("for", []),
    ("for ((a;b;c;d));", [False]),
]  # fmt: skip


@pytest.mark.parametrize(("text", "want"), ARITHMETIC_FORS, ids=[c[0] for c in ARITHMETIC_FORS])
def test_arithmetic_fors_without_a_condition_never_end(cs, text, want):
    assert cs.arithmetic_fors(cs.Lexer(text).tokens()) == want


SPLIT_REDIRECTS = [
    ("a b", (["a", "b"], [])), ("a >f b", (["a", "b"], [(">", "f")])),
    ("a 2>&1", (["a"], [("2>&", "")])), ("a < f", (["a"], [("<", "f")])),
    ("a >", (["a"], [(">", "")])), ("a 2> f > g", (["a"], [("2>", "f"), (">", "g")])),
    ("a <<< x b", (["a", "b"], [("<<<", "x")])), (">f", ([], [(">", "f")])),
]  # fmt: skip


@pytest.mark.parametrize(("text", "want"), SPLIT_REDIRECTS, ids=[c[0] for c in SPLIT_REDIRECTS])
def test_split_redirects_pairs_each_redirection_with_its_target(cs, text, want):
    words, redirects = cs.split_redirects(groups(cs, text)[0])
    assert ([str(w) for w in words], [(str(o), str(t)) for o, t in redirects]) == want


@pytest.mark.parametrize(
    ("took", "want"),
    [([], False), (["-f"], True), (["--fork"], True), (["-wf"], True), (["-w"], False),
     (["--foo"], False), (["f"], False), (["-"], False), (["--f"], False), (["-cf"], True)],
)  # fmt: skip
def test_setsid_forks_with_f_or_fork(cs, took, want):
    assert cs._forks(took) is want


@pytest.mark.parametrize(
    ("took", "want"),
    [([], True), (["5"], True), (["0"], False), (["0s"], False), (["0.0"], False),
     (["inf"], False), (["infinity"], False), (["nan"], False), (["1d"], True), (["2m"], True),
     (["x"], True), (["$T"], True), (["-k", "5", "60"], True), (["-s"], True), (["1e3"], True),
     (["--foreground"], True), (["1.5h"], True), (["-0"], False)],
)  # fmt: skip
def test_a_timeout_sets_a_limit_unless_its_duration_is_zero_inf_or_nan(cs, took, want):
    assert cs._limits(took) is want


@pytest.mark.parametrize(
    ("flag", "want"),
    [("--wait", "--wait"), ("--wai", "--wait"), ("--w", "--wait"), ("--timeout", "--timeout"),
     ("--ti", "--timeout"), ("--no", "--no"), ("--n", "--n"), ("--", "--"), ("--zzz", "--zzz"),
     ("--nb", "--nb"), ("--nonblock", "--nonblock"), ("--c", "--c"), ("--com", "--command"),
     ("--shared", "--shared"), ("--s", "--shared")],
)  # fmt: skip
def test_a_long_option_is_any_unique_prefix(cs, flag, want):
    assert cs._long(flag, cs.FLOCK_LONG) == want


@pytest.mark.parametrize(
    ("tok", "want"),
    [("-9", True), ("-15", True), ("-HUP", True), ("-hup", True), ("-SIGHUP", True),
     ("-sigterm", True), ("-KILL", True), ("-RTMIN+1", True), ("-RTMAX-3", True),
     ("-RTMIN", True), ("-fpe", True), ("-f", False), ("-x", False), ("-0", True),
     ("-X", False), ("-SIGFOO", False), ("-USR1", True), ("-usr2", True), ("-9f", False),
     ("-", False), ("-IO", True), ("-POLL", True), ("-CLD", True), ("-IOT", True),
     ("-STKFLT", True)],
)  # fmt: skip
def test_a_dash_word_is_a_signal_when_it_names_one(cs, tok, want):
    assert cs._signal(tok) is want


FULL_MATCH = [
    ("pgrep", ["-f", "x"], True), ("pgrep", ["--full", "x"], True), ("pgrep", ["--fu", "x"], True),
    ("pgrep", ["--f", "x"], True), ("pgrep", ["-af", "x"], True), ("pgrep", ["x", "-f"], True),
    ("pgrep", ["-x", "x"], False), ("pgrep", ["-u", "f", "x"], False),
    ("pgrep", ["-uf", "x"], False), ("pgrep", ["--", "-f"], False), ("pgrep", ["-"], False),
    ("pgrep", ["--full=x"], True), ("pgrep", ["--signal", "-f", "x"], False),
    ("pgrep", ["--signal=KILL", "-f", "x"], True), ("pgrep", ["-F", "p", "-f"], True),
    ("pgrep", ["-G", "1", "-f"], True), ("pgrep", ["-g", "1", "x"], False),
    ("pgrep", ["-d", ",", "-f"], True), ("pgrep", ["-d,", "f"], False),
    ("pkill", ["-9", "-f", "x"], True), ("pkill", ["-fpe", "x"], False),
    ("pkill", ["-FPE", "x"], False), ("pkill", ["-x", "-fpe", "x"], True),
    ("pkill", ["-HUP", "-f", "x"], True), ("pkill", ["-s", "f", "x"], False),
    ("pkill", ["-t", "tty", "-f"], True), ("pkill", ["-fxsz", "x"], True),
    ("pgrep", ["-fxsz", "x"], True), ("pkill", ["-xfsz", "x"], False),
    ("pkill", ["--pgroup", "1", "-f"], True), ("pkill", ["--delimiter", ",", "--full"], True),
    ("pkill", ["--older", "5", "-f"], True), ("pkill", ["-O", "5", "-f"], True),
    ("pkill", ["-q", "5", "-f"], True), ("pkill", ["-r", "R", "-f"], True),
    ("pkill", ["-P", "1", "-f"], True), ("pkill", ["-U", "1", "-f"], True),
    ("pkill", ["--queue", "1", "-f"], True), ("pkill", ["--cgroup", "c", "-f"], True),
    ("pkill", ["--ns", "1", "-f"], True), ("pkill", ["--nslist", "n", "-f"], True),
    ("pkill", ["--runstates", "R", "-f"], True), ("pkill", ["--session", "1", "-f"], True),
    ("pkill", ["--terminal", "t", "-f"], True), ("pkill", ["--euid", "1", "-f"], True),
    ("pkill", ["--uid", "1", "-f"], True), ("pkill", ["--parent", "1", "-f"], True),
    ("pkill", ["--group", "1", "-f"], True), ("pkill", ["--pidfile", "p", "-f"], True),
    ("pkill", ["-fo", "x"], True), ("pkill", ["-ef", "x"], True), ("pkill", ["-xf", "x"], True),
]  # fmt: skip


@pytest.mark.parametrize(
    ("name", "args", "want"), FULL_MATCH, ids=[f"{n} {' '.join(a)}" for n, a, _ in FULL_MATCH]
)
def test_full_match_reads_procps_options(cs, name, args, want):
    assert cs.full_match(name, args) is want


SHELL_CODE = [
    (["-c", "x"], ("x", False)), (["-c"], (None, False)), (["-lc", "x"], ("x", False)),
    (["-ec", "x"], ("x", False)), (["-euo", "pipefail", "-c", "x"], ("x", False)),
    (["-o", "pipefail", "-c", "x"], ("x", False)), (["+o", "pipefail", "-c", "x"], ("x", False)),
    (["-O", "extglob", "-c", "x"], ("x", False)), (["--rcfile", "f", "-c", "x"], ("x", False)),
    (["--init-file", "f", "-c", "x"], ("x", False)), (["--norc", "-c", "x"], ("x", False)),
    (["script.sh"], (None, False)), (["-s"], (None, True)), (["-s", "arg"], (None, True)),
    (["-"], (None, True)), (["/dev/stdin"], (None, True)), ([], (None, True)),
    (["--"], (None, True)), (["--", "-c"], (None, False)), (["-c", "x", "y"], ("x", False)),
    (["-x"], (None, True)), (["x"], (None, False)), (["-eo", "pipefail", "x"], (None, False)),
    (["-i"], (None, True)), (["-ci", "x"], ("x", False)), (["-sc", "x"], ("x", False)),
    (["-cs", "x"], ("x", False)), (["--login", "-c", "x"], ("x", False)),
    (["--posix", "x"], (None, False)), (["-", "x"], (None, True)),
    (["-oo", "a", "b", "-c", "x"], ("x", False)), (["-xo"], (None, True)),
    (["-c", "--", "x"], ("x", False)), (["--", "x"], (None, False)), (["-sx"], (None, True)),
    (["-s", "--", "a"], (None, True)), (["+x", "-c", "x"], ("x", False)),
    (["-O", "-c", "x"], (None, False)),
]  # fmt: skip


@pytest.mark.parametrize(
    ("args", "want"), SHELL_CODE, ids=[" ".join(a) or "none" for a, _ in SHELL_CODE]
)
def test_shell_code_reads_a_shells_command_string_and_stdin_use(cs, args, want):
    assert cs.shell_code(args) == want


# --- wrappers, and the pieces of the lexer that read a substitution -----------------------

PEEL = [
    (["echo", "a"], (["echo", "a"], False, None, False)),
    (["timeout", "5", "echo", "a"], (["echo", "a"], True, None, False)),
    (["timeout", "0", "echo", "a"], (["echo", "a"], False, None, False)),
    (["timeout", "-k", "2", "5", "echo"], (["echo"], True, None, False)),
    (["/usr/bin/timeout", "5", "x"], (["x"], True, None, False)),
    (["./timeout", "5", "x"], (["./timeout", "5", "x"], False, None, False)),
    (["gtimeout", "5", "x"], (["x"], True, None, False)),
    (["sudo", "timeout", "5", "x"], (["x"], True, None, False)),
    (["timeout", "5", "sudo", "x"], (["x"], True, None, False)),
    (["setsid", "-f", "x"], (["x"], False, None, True)),
    (["setsid", "x"], (["x"], False, None, False)),
    (["timeout", "5", "setsid", "-f", "x"], (["x"], False, None, True)),
    (["setsid", "-f", "timeout", "5", "x"], (["x"], True, None, True)),
    (["setsid", "-fw", "x"], (["x"], False, None, True)),
    (["setsid", "--fork", "x"], (["x"], False, None, True)),
    (["setsid", "-w", "x"], (["x"], False, None, False)),
    (["timeout", "0", "setsid", "-f", "timeout", "5", "x"], (["x"], True, None, True)),
    (["nice", "timeout", "5", "x"], (["x"], True, None, False)),
    (["coproc", "x", "y"], (["x", "y"], False, None, False)),
    (["busybox", "sh"], (["sh"], False, None, False)),
    (["nohup", "busybox", "x"], (["x"], False, None, False)),
    (["env", "A=1", "x"], (["x"], False, None, False)),
    (["flock", "lk", "-c", "code"], ([], False, "code", False)),
    (["flock", "lk", "x", "y"], (["x", "y"], False, None, False)),
    (["flock", "-w", "5", "lk", "x"], (["x"], False, None, False)),
    (["flock", "-x", "lk", "-c", "c"], ([], False, "c", False)),
    (["flock", "lk"], ([], False, None, False)),
    (["flock"], ([], False, None, False)),
    (["flock", "lk", "flock", "lk2", "-c", "deep"], ([], False, "deep", False)),
    (["timeout", "5", "flock", "lk", "-c", "c"], ([], True, "c", False)),
    (["script", "-qc", "code", "/dev/null"], ([], False, "code", False)),
    (["script", "-q", "log"], (["script", "-q", "log"], False, None, False)),
    (["script", "--command=c"], ([], False, "c", False)),
    (["script", "--command", "c", "f"], ([], False, "c", False)),
    (["script"], (["script"], False, None, False)),
]


@pytest.mark.parametrize(("argv", "want"), PEEL, ids=[" ".join(a) for a, _ in PEEL])
def test_peel_strips_wrappers_and_reports_the_bound_the_code_and_a_fork(cs, argv, want):
    assert cs.peel(list(argv)) == want


EXPANSIONS = [
    ("a $(b) c", ["b"], False, 8),
    ("$(a $(b))", ["a $(b)"], False, 9),
    ("`a`", ["a"], False, 3),
    ("${x:-$(a)}", ["a"], False, 10),
    ("\\$(a)", [], False, 5),  # an escaped dollar runs nothing
    ("\\\\$(a)", ["a"], False, 6),  # an escaped backslash does not escape the dollar
    ("x \\` y", [], False, 6),
    ("$(", [""], True, 2),
    ("a ${", [], True, 4),
    ("${x}", [], False, 4),
    ("plain", [], False, 5),
    ("", [], False, 0),
    ("a\\", [], False, 2),
    ("\\`$(b)", ["b"], False, 6),
    ("$((1+2))", [], False, 8),
    ("$(a) `b` ${c:-$(d)}", ["a", "b", "d"], False, 19),
    ("$( (a) )", [" (a) "], False, 8),
]


@pytest.mark.parametrize(("text", "codes", "unclosed", "pos"), EXPANSIONS)
def test_an_unquoted_heredoc_body_runs_its_substitutions(cs, text, codes, unclosed, pos):
    lexer = cs.Lexer(text)
    lexer.expansions()
    assert ([s.code for s in lexer.subs], lexer.unclosed, lexer.i) == (codes, unclosed, pos)


BRACES = [
    ("${x}", "${x}", [], False, 4),
    ("${x:-a}", "${x:-a}", [], False, 7),
    ("${x:-{a}}", "${x:-{a}}", [], False, 9),
    ("${x:-'}'}", "${x:-'}'}", [], False, 9),
    ('${x:-"}"}', '${x:-"}"}', [], False, 9),
    ("${x:-\\}}", "${x:-\\}}", [], False, 8),
    ("${x:-$(a)}", "${x:-$(a)}", ["a"], False, 10),
    ("${x:-`a`}", "${x:-`a`}", ["a"], False, 9),
    ("${x", "${x", [], True, 3),
    ("${x:-'a", "${x:-'a", [], True, 7),
    ('${x:-"a', '${x:-"a', [], True, 7),
    ("${}", "${}", [], False, 3),
    ("${x}}", "${x}", [], False, 4),
    ("a${x}b", "${x}", [], False, 5),
]


@pytest.mark.parametrize(("text", "word", "codes", "unclosed", "pos"), BRACES)
def test_a_dollar_brace_ends_at_its_own_brace_past_quotes_and_substitutions(
    cs, text, word, codes, unclosed, pos
):
    lexer = cs.Lexer(text)
    lexer.i = text.find("${")
    assert lexer.braces() == word
    assert ([s.code for s in lexer.subs], lexer.unclosed, lexer.i) == (codes, unclosed, pos)


SUBSTITUTIONS = [
    ("$(a)", "$(a)", [("a", True, 0)], False, 4),
    ("$(a) b", "$(a)", [("a", True, 0)], False, 4),
    ("$((1+2))", "$((1+2))", [], False, 8),
    ("$((a))", "$((a))", [], False, 6),
    ("$(( (a) ))", "$(( (a) ))", [], False, 10),
    ("$( (a) )", "$( (a) )", [(" (a) ", True, 0)], False, 8),
    ("$((a) )", "$((a) )", [("(a) ", True, 0)], False, 7),
    ("$(a $(b))", "$(a $(b))", [("a $(b)", True, 1)], False, 9),
    ("`a`", "`a`", [("a", False, 0)], False, 3),
    ("`a\\`b`", "`a\\`b`", [("a`b", False, 0)], False, 6),
    ("`a\\\\b`", "`a\\\\b`", [("a\\b", False, 0)], False, 6),
    ("`a\\$b`", "`a\\$b`", [("a$b", False, 0)], False, 6),
    ("`a", "`a", [("a", False, 0)], True, 3),
    ("$(a", "$(a", [("", True, 0)], True, 3),
    ("<(a)", "<(a)", [("a", True, 0)], False, 4),
    (">(a)", ">(a)", [("a", True, 0)], False, 4),
    ("$((", "$((", [("", True, 0)], True, 3),
    ("$(())", "$(())", [], False, 5),
    ("$(a)$(b)", "$(a)", [("a", True, 0)], False, 4),
    ("$(echo '))')", "$(echo '))')", [("echo '))'", True, 0)], False, 12),
]


@pytest.mark.parametrize(("text", "word", "subs", "unclosed", "pos"), SUBSTITUTIONS)
def test_a_substitution_is_read_to_its_closing_paren_or_backtick(
    cs, text, word, subs, unclosed, pos
):
    lexer = cs.Lexer(text)
    assert lexer.substitution() == word
    assert (
        [(s.code, s.tokens is not None, len(s.subs)) for s in lexer.subs],
        lexer.unclosed,
        lexer.i,
    ) == (
        subs,
        unclosed,
        pos,
    )


DQUOTES = [
    ('"a"', "a", [], False, 3),
    ('"a b" c', "a b", [], False, 5),
    ('"a\\"b"', 'a"b', [], False, 6),
    ('"a$(b)c"', "a$(b)c", ["b"], False, 8),
    ('"a`b`c"', "a`b`c", ["b"], False, 7),
    ('"a${x}c"', "a${x}c", [], False, 8),
    ('"a', "a", [], True, 2),
    ('"a\\\\"', "a\\", [], False, 5),
    ('"a\\$"', "a$", [], False, 5),
    ('"a\\`"', "a`", [], False, 5),
    ('"a\\x"', "a\\x", [], False, 5),
]


@pytest.mark.parametrize(("text", "word", "codes", "unclosed", "pos"), DQUOTES)
def test_a_double_quoted_string_keeps_a_backslash_unless_it_escapes_a_special(
    cs, text, word, codes, unclosed, pos
):
    lexer = cs.Lexer(text)
    lexer.i = 1
    assert lexer.dquote() == word
    assert ([s.code for s in lexer.subs], lexer.unclosed, lexer.i) == (codes, unclosed, pos)


def test_substitutions_nest_at_most_fifty_deep(cs):
    cs.Lexer("$(" * 50 + "x" + ")" * 50).tokens()
    with pytest.raises(ValueError, match="more than 50 deep"):
        cs.Lexer("$(" * 51 + "x" + ")" * 51).tokens()
