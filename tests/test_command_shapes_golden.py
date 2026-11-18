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
    ("2>&1", [("op", "2>&"), ("w", "1")], [], False, 4),
    ("2>x", [("op", "2>"), ("w", "x")], [], False, 3),
    ("a 2>x", [("w", "a"), ("op", "2>"), ("w", "x")], [], False, 5),
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
    ("a 2>&1", (["a"], [("2>&", "1")])), ("a < f", (["a"], [("<", "f")])),
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
    (["-o", "pipefail", "-c", "x"], ("x", False)),
    (["-euo", "pipefail", "-c", "x"], ("x", False)),
    (["-eO", "extglob", "-c", "x"], ("x", False)),
    (["-eu", "-c", "x"], ("x", False)), (["+o", "pipefail", "-c", "x"], ("x", False)),
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


# --- Scan: the walk through nesting, one level at a time -------------------------------------

LOOP = "while true; do sleep 1; done"
# Each way bash runs a string as code, with one unbounded loop in that code.
NESTED_LOOP = {
    "backtick": f"echo `{LOOP}`",
    "dollar-paren": f"echo $({LOOP})",
    "process-substitution": f"cat <({LOOP})",
    "bash -c": f"bash -c '{LOOP}'",
    "eval words": r"eval while true\; do sleep 1\; done",
    "eval string": f"eval '{LOOP}'",
    "watch": f"watch -n 5 '{LOOP}'",
    "su -c": f"su -c '{LOOP}' root",
    "flock -c": f"flock /tmp/x -c '{LOOP}'",
    "here-string": f"bash <<< '{LOOP}'",
    "heredoc to a shell": f"bash <<EOF\n{LOOP}\nEOF",
    "cat heredoc in -c": f'bash -c "$(cat <<EOF\n{LOOP}\nEOF\n)"',
    "unquoted heredoc expansion": f"cat <<EOF\n$({LOOP})\nEOF",
}


def scan_of(cs, text, bounded=False, depth=0):
    scan = cs.Scan()
    scan.text(text, bounded, depth)
    return scan


@pytest.mark.parametrize("flags", ["-Xc", "-X -c"])
def test_a_zsh_option_that_takes_no_word_does_not_hide_the_code(cs, flags):
    text = f"zsh {flags} '{LOOP}'"
    assert scan_of(cs, text).loops == [(False, False)]


@pytest.mark.parametrize("form", NESTED_LOOP)
def test_every_way_of_running_code_passes_the_bound_down_and_nothing_else(cs, form):
    text = NESTED_LOOP[form]
    assert scan_of(cs, text, bounded=False).loops == [(False, False)]
    assert scan_of(cs, text, bounded=True).loops == [(True, False)]


@pytest.mark.parametrize("form", NESTED_LOOP)
def test_every_way_of_running_code_costs_one_level_of_depth(cs, form):
    text = NESTED_LOOP[form]
    scan_of(cs, text, depth=cs.MAX_DEPTH - 1)  # the code inside is read at MAX_DEPTH
    with pytest.raises(ValueError, match="more than 16 deep"):
        scan_of(cs, text, depth=cs.MAX_DEPTH)


def test_text_nested_exactly_at_the_limit_is_read(cs):
    inner = "pkill -f x"
    for _ in range(cs.MAX_DEPTH):
        inner = f"echo $({inner})"
    scan = cs.Scan()
    scan.text(inner)  # the default depth, 0
    assert scan.full == ["pkill"]
    with pytest.raises(ValueError, match="more than 16 deep"):
        cs.Scan().text(f"echo $({inner})")
    # A top-level text at depth 0 is read; the same text started one level in is refused.
    scan_of(cs, "pkill -f x", depth=cs.MAX_DEPTH)
    with pytest.raises(ValueError, match="more than 16 deep"):
        scan_of(cs, "pkill -f x", depth=cs.MAX_DEPTH + 1)


def test_a_walk_at_the_limit_is_read_and_one_past_it_is_refused(cs):
    lexer = cs.Lexer("pkill -f x")
    scan = cs.Scan()
    scan.walk(lexer.tokens(), [], False, [], cs.MAX_DEPTH)
    assert scan.full == ["pkill"]
    with pytest.raises(ValueError, match="more than 16 deep"):
        scan.walk(lexer.tokens(), [], False, [], cs.MAX_DEPTH + 1)


def test_a_forged_heredoc_marker_with_no_body_is_text_not_an_index_error(cs):
    marker = "\x00H0\x00"
    cs.Scan().code(f"$(cat <<{marker})", False, [], 0)
    scan = cs.Scan()
    scan.command(["bash", cs.Op("<<"), marker], False, [], 0)
    assert scan.loops == [] and scan.full == []


def test_a_dash_heredoc_fed_to_a_shell_is_read(cs):
    assert scan_of(cs, "bash <<-EOF\n\tpkill -f x\nEOF").full == ["pkill"]
    assert scan_of(cs, "bash <<EOF\npkill -f x\nEOF").full == ["pkill"]


def test_eval_joins_its_words_with_one_space(cs):
    assert scan_of(cs, "eval pkill -f x").full == ["pkill"]
    assert scan_of(cs, "eval pkill -f x").loops == []


WATCH = [
    ("watch -n 5 'pkill -f x'", ["pkill"]),
    ("watch --interval 5 'pkill -f x'", ["pkill"]),
    ("watch -d 'pkill -f x'", ["pkill"]),  # -d takes no value: the next word is the command
    ("watch -- 'pkill -f x'", ["pkill"]),
    ("watch -n 5 -- 'pkill -f x'", ["pkill"]),
    ("watch -- -1 pkill -f x", []),  # past `--` a word with a dash is the command's name
    ("watch -x", []),  # options and no command
]


@pytest.mark.parametrize(("text", "want"), WATCH)
def test_watch_runs_its_words_after_its_options(cs, text, want):
    assert scan_of(cs, text).full == want


def test_a_scan_restores_what_the_text_around_it_detached(cs):
    scan = scan_of(cs, "sleep 9 & echo hi")
    assert scan.detached is False
    assert scan_of(cs, "echo hi").detached is False


def test_an_arithmetic_for_inside_a_loop_body_counts_as_a_loop(cs):
    scan = scan_of(cs, "while x; do for ((;;)); do sleep 1; done; done")
    assert scan.loops == [(False, False), (False, False)]


def test_a_clock_test_bounds_an_arithmetic_for_even_after_other_one_word_commands(cs):
    scan = scan_of(cs, "echo; for ((;;)); do [ $SECONDS -gt 9 ] && break; done")
    assert scan.loops == [(True, False)]


def test_a_for_with_one_paren_is_no_loop(cs):
    assert scan_of(cs, "for (a); do :; done").loops == []


def test_the_code_of_a_cat_heredoc_is_read_one_level_in(cs):
    text = 'bash -c "$(cat <<EOF\necho $(pkill -f x)\nEOF\n)"'
    scan_of(cs, text, depth=cs.MAX_DEPTH - 2)
    with pytest.raises(ValueError, match="more than 16 deep"):
        scan_of(cs, text, depth=cs.MAX_DEPTH - 1)


# --- option readers ----------------------------------------------------------------------------


def test_command_option_reads_a_string_missing_at_the_end_as_empty(cs):
    assert cs._command_option(["--command"], "w") == ("", [])
    assert cs._command_option(["-c"], "w") == ("", [])
    assert cs._command_option(["/tmp/l", "-c"], "wE", stop=True) == ("", ["/tmp/l"])


def test_command_option_reads_a_lone_dash_as_an_operand(cs):
    assert cs._command_option(["-", "x"], "w") == (None, ["-", "x"])
    assert cs._command_option(["-", "-c", "x"], "wE", stop=True) == ("x", ["-"])


def test_command_option_takes_an_attached_value_without_skipping_a_word(cs):
    assert cs._command_option(["-w5", "-c", "x"], "wE") == ("x", [])
    assert cs._command_option(["-w", "5", "-c", "x"], "wE") == ("x", [])


@pytest.mark.parametrize("opt", list("EIOBTmo"))
def test_a_script_option_with_a_value_takes_the_next_word_even_a_dash_c(cs, opt):
    assert scan_of(cs, f"script -{opt} -c 'pkill -f x' out").full == []
    assert scan_of(cs, "script -c 'pkill -f x' out").full == ["pkill"]


@pytest.mark.parametrize("opt", ["-w", "-E"])
def test_a_flock_option_with_a_value_takes_the_next_word(cs, opt):
    assert scan_of(cs, f"flock {opt} 3 /tmp/l -c 'pkill -f x'").full == ["pkill"]


@pytest.mark.parametrize("opt", list("gGsTw"))
def test_a_su_option_with_a_value_takes_the_next_word_even_a_dash_c(cs, opt):
    assert scan_of(cs, f"su -{opt} -c 'pkill -f x' root").full == []
    assert scan_of(cs, "su -c 'pkill -f x' root").full == ["pkill"]


SHELL_CODE_MORE = [
    (["-c", "--", "-x"], ("-x", False)),
    (["-O", "extglob", "-c", "pkill -f x"], ("pkill -f x", False)),
    (["-o", "pipefail", "-c", "x"], ("x", False)),
    (["-euo", "pipefail", "-c", "x"], ("x", False)),
    (["-eO", "extglob", "-c", "x"], ("x", False)),
    (["-eu", "-c", "x"], ("x", False)),
    (["--", "/dev/stdin"], (None, True)),
    (["--", "-"], (None, True)),
    (["--", "script.sh"], (None, False)),
    (["-Xc", "x"], ("x", False)),  # zsh -X (LIST_TYPES) takes no word
    (["-X", "-c", "x"], ("x", False)),
]


@pytest.mark.parametrize(
    ("args", "want"), SHELL_CODE_MORE, ids=[str(r[0]) for r in SHELL_CODE_MORE]
)
def test_shell_code_after_a_double_dash_and_with_valued_options(cs, args, want):
    assert cs.shell_code(args) == want


@pytest.mark.parametrize(
    ("name", "args", "want"),
    [
        ("pgrep", ["-s", "-f", "x"], False),  # -f is the value of -s
        ("pgrep", ["-sf", "-f", "x"], True),  # -sf is -s with the value f; the next -f is real
        ("pgrep", ["x", "-s", "-f"], False),
        ("pgrep", ["--=x"], False),
        ("pgrep", ["xf"], False),  # an operand, not options
        ("pgrep", ["-"], False),
    ],
)
def test_full_match_values_and_operands(cs, name, args, want):
    assert cs.full_match(name, args) is want


def test_a_timeout_duration_this_check_cannot_read_counts_as_a_limit(cs):
    assert cs._limits(["0X"]) is True
    assert cs._limits(["0"]) is False
    assert cs._limits(["0s"]) is False
    assert cs._limits([]) is True


# --- helpers on plain lists and nested shapes -------------------------------------------------


def test_command_start_and_loops_read_plain_string_words(cs):
    assert cs.command_start(["if", "x"]) == 1
    assert cs.command_start(["!", "x"]) == 1
    assert cs.loops(["while", "true"]) == "wait"
    assert cs.loops(["while", "read", "x"]) == "read"


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("if ! x", 2),
        ("then { x", 2),
        ("! function f echo", 3),
        ("{ function f x", 3),
        ("! time x", 2),
        ("{ time -p x", 3),
    ],
)
def test_command_start_skips_every_keyword_and_a_function_header_after_one(cs, text, want):
    assert cs.command_start(groups(cs, text)[0]) == want


def test_reads_clock_on_a_plain_list_has_no_parens(cs):
    assert cs._reads_clock(["SECONDS"]) is False
    assert cs._reads_clock(["[", "$SECONDS", "]"]) is True


def test_a_time_before_a_loop_keyword_is_skipped_to_its_condition(cs):
    g = groups(cs, "time -p while [ $SECONDS -lt 9 ]")[0]
    assert cs._reads_clock(g) is True


def test_reads_to_end_with_a_redirection_and_no_target(cs):
    g = groups(cs, "while read x; do :; done <")
    i = next(n for n, c in enumerate(g) if cs.loops(c))
    assert cs.reads_to_end(g, i) is True


def test_arithmetic_fors_at_the_end_of_the_tokens(cs):
    assert cs.arithmetic_fors(cs.Lexer("for ((").tokens()) == [False]
    assert cs.arithmetic_fors(cs.Lexer("for ( '(' ; ; )").tokens()) == []
    assert cs.arithmetic_fors(cs.Lexer("for '(' ( ; ; ))").tokens()) == []
    assert cs.arithmetic_fors(cs.Lexer("for (( ; ; i<3 ))").tokens()) == [True]
    assert cs.arithmetic_fors(cs.Lexer("for (( ; <3 ; ))").tokens()) == [False]


# --- on_clock: a subshell, an `if` on its own line, a loop that has ended, the nesting count ---

ON_CLOCK_MORE = [
    ("( while true; do [ $SECONDS -gt 9 ] && break; sleep 1; done )", [True]),
    ("while true; do\nif\n[ $SECONDS -gt 9 ]; then break; fi; done", [True]),
    ("while true; do\nif a; then b\nelif\n[ $SECONDS -gt 9 ]; then break; fi; done", [True]),
    ("while true; do if a; then b; elif [ $SECONDS -gt 9 ]; then break; fi; done", [True]),
    ("while true; do for i in 1; do x; done; [ $SECONDS -gt 9 ] && break; done", [True]),
    ("while true; do if [ $SECONDS -gt 9 ]; then ( echo hi ); break; fi; done", [True]),
    ("echo a; while true; do for i in 1; do [ $SECONDS -gt 9 ] && break; done; done", [False]),
    ("[ $SECONDS -gt 9 ] && exit 1; while true; do sleep 1; done", [False]),
    ("while true; do sleep 1; done; [ $SECONDS -gt 9 ] && exit 1", [False]),
]


@pytest.mark.parametrize("row", ON_CLOCK_MORE, ids=[r[0] for r in ON_CLOCK_MORE])
def test_on_clock_more_shapes(cs, row):
    text, want = row
    g = groups(cs, text)
    loop_at = [i for i, c in enumerate(g) if cs.loops(c)]
    assert [cs.on_clock(g, i) for i in loop_at] == want


def test_on_clock_reads_plain_lists_as_outside_every_subshell(cs):
    commands = [["while", "true"], ["do", "[", "$SECONDS", "-gt", "9", "]"], ["break"], ["done"]]
    # No `sep`: a plain list is no `&&` consequent, so the break is no bound of the test's own.
    assert cs.on_clock(commands, 0) is False
    commands[2] = cs.Group(["break"])
    commands[2].sep = "&&"
    assert cs.on_clock(commands, 0) is True


# --- the lexer ----------------------------------------------------------------------------------

MORE_LEXER = [
    ("a\nb #c\nd", [("w", "a"), ("op", "\n"), ("w", "b"), ("op", "\n"), ("w", "d")]),
    ("# c\nd\ne", [("op", "\n"), ("w", "d"), ("op", "\n"), ("w", "e")]),
    ("echo 2>x", [("w", "echo"), ("op", "2>"), ("w", "x")]),
    ("echo 2>&1", [("w", "echo"), ("op", "2>&"), ("w", "1")]),
    ("echo 10>x", [("w", "echo"), ("op", "10>"), ("w", "x")]),
    ("cat 3<f", [("w", "cat"), ("op", "3<"), ("w", "f")]),
    ("cat 3<<<f", [("w", "cat"), ("op", "3<<<"), ("w", "f")]),
    ("echo a2>x", [("w", "echo"), ("w", "a2"), ("op", ">"), ("w", "x")]),
    ("echo '2'>x", [("w", "echo"), ("q", "2"), ("op", ">"), ("w", "x")]),
    ("ab\\ c", [("w", "ab c")]),
    ("echo X(a)", [("w", "echo"), ("w", "X"), ("op", "("), ("w", "a"), ("op", ")")]),
    ('echo "${x:-"a b"}" c', [("w", "echo"), ("q", '${x:-"a b"}'), ("w", "c")]),
]


@pytest.mark.parametrize("row", MORE_LEXER, ids=[r[0] for r in MORE_LEXER])
def test_the_lexer_more_shapes(cs, row):
    text, want = row
    kinds, _, unclosed, _ = lex(cs, text)
    assert kinds == want
    assert unclosed is False


def test_arithmetic_after_other_words_runs_only_the_substitutions_inside(cs):
    lexer = cs.Lexer("echo $(( $(a) + 1 ))")
    lexer.tokens()
    assert [(s.code, len(s.subs)) for s in lexer.subs] == [("a", 0)]


def test_braces_with_an_empty_quoted_string_and_text_after(cs):
    lexer = cs.Lexer("${x:-''}b")
    assert lexer.braces() == "${x:-''}"
    assert (lexer.i, lexer.unclosed) == (8, False)
    lexer = cs.Lexer('${x:-"a"}b')
    assert lexer.braces() == '${x:-"a"}'
    assert (lexer.i, lexer.unclosed) == (9, False)
    lexer = cs.Lexer("${x}b")
    assert lexer.braces() == "${x}" and lexer.i == 4


def test_on_clock_reads_a_plain_list_if_branch(cs):
    """Without a `parens` or `sep` attribute a command counts as outside every subshell."""
    commands = [
        ["while", "true"],
        ["do"],
        ["if"],
        ["[", "$SECONDS", "-gt", "9", "]"],
        ["then"],
        ["break"],
        ["fi"],
        ["done"],
    ]
    assert cs.on_clock(commands, 0) is True


def test_an_arithmetic_for_is_counted_at_its_own_header_not_at_a_one_word_command(cs):
    scan = scan_of(
        cs,
        "echo; for ((;i<3;)); do :; done; for ((;;)); do [ $SECONDS -gt 9 ] && break; done",
    )
    assert scan.loops == [(True, False)]


def test_braces_read_a_substitution_inside_a_double_quote_from_its_first_character(cs):
    lexer = cs.Lexer('${x:-"$(a)"}b')
    assert lexer.braces() == '${x:-"$(a)"}'
    assert ([s.code for s in lexer.subs], lexer.unclosed, lexer.i) == (["a"], False, 12)
