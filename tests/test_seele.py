"""SEELE's clerk: blind ballots, the count, the lanes to other CLIs, and the report."""

from __future__ import annotations

import json
import os
import pathlib
import re
import signal
import stat
import subprocess
import textwrap
import time

import pytest
import yaml
from conftest import HOOK_PYTHON, ROOT

PLUGIN = ROOT / "plugins" / "techne"
SKILL = PLUGIN / "skills" / "seele"
SCRIPT = SKILL / "scripts" / "seele.py"
CLAUDE3 = ["--seat", "claude:opus", "--seat", "claude:sonnet", "--seat", "claude:haiku"]


def run(
    state: pathlib.Path, *args: str, path: str | None = None, env: dict | None = None
) -> subprocess.CompletedProcess:
    env = dict(os.environ, XDG_STATE_HOME=str(state), **(env or {}))
    if path is not None:
        env["PATH"] = path
    return subprocess.run(
        [HOOK_PYTHON, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=120,
        check=False,
    )


def lib(expr: str):
    """Evaluate an expression against the module on the interpreter under test."""
    code = (
        "import json, random, sys\n"
        f"sys.path.insert(0, {str(SCRIPT.parent)!r})\n"
        "import seele\n"
        f"print(json.dumps({expr}))\n"
    )
    out = subprocess.run(
        [HOOK_PYTHON, "-c", code], capture_output=True, text=True, timeout=120, check=False
    )
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


class Panel:
    """One run on disk, driven the way the session drives it."""

    def __init__(self, state: pathlib.Path, *args: str, brief: str = "Name the tool.", path=None):
        self.state, self.path = state, path
        state.mkdir(parents=True, exist_ok=True)
        (state / "brief.md").write_text(brief, encoding="utf-8")
        args = args or tuple(CLAUDE3)
        out = self(
            "open", "--brief", str(state / "brief.md"), "--topic", "A name", "--seed", "7", *args
        )
        assert out.returncode == 0, out.stderr
        self.dir = pathlib.Path(out.stdout.split("run: ", 1)[1].splitlines()[0])
        self.opened = out.stdout

    def __call__(self, command: str, *args: str, env=None) -> subprocess.CompletedProcess:
        extra = ("--run", str(self.dir)) if command != "open" else ()
        return run(self.state, command, *extra, *args, path=self.path, env=env)

    @property
    def data(self) -> dict:
        return json.loads((self.dir / "run.json").read_text(encoding="utf-8"))

    def seat(self, n: int, rnd: int = 1) -> pathlib.Path:
        key = "dir" if rnd == 1 else "dir2"
        return pathlib.Path(next(s[key] for s in self.data["seats"] if s["n"] == n))

    def propose(self, n: int, *answers: str, verdict: str = "") -> None:
        text = f"VERDICT: {verdict}\nREASON: because\n" if verdict else ""
        for i, answer in enumerate(answers, 1):
            text += f"PROPOSAL {i}: {answer}\nWHY {i}: case for {answer}\n"
        (self.seat(n) / "proposal.md").write_text(text, encoding="utf-8")

    def vote(self, n: int, ranking: str, reject: str = "") -> None:
        """`ranking` and `reject` are candidate ids; the file uses the seat's own labels."""
        label = {cid: code for code, cid in self.data["ballots"][str(n)]["codes"].items()}
        text = "".join(f"ASSESS {label[c]}: seat {n} on {label[c]}\n" for c in ranking)
        text += "RANKING: " + " > ".join(label[c] for c in ranking) + "\n"
        text += "REJECT: " + (", ".join(label[c] for c in reject) or "none") + "\n"
        text += f"OBJECTION: {label[ranking[0]]} has a flaw\n"
        (self.seat(n, 2) / "vote.md").write_text(text, encoding="utf-8")

    def ids(self) -> dict[str, str]:
        return {c["text"]: c["id"] for c in self.data["candidates"]}

    def rule(self, text: str) -> None:
        (pathlib.Path(self.data["chair"]["dir"]) / "ruling.md").write_text(text, encoding="utf-8")


@pytest.fixture
def voted(tmp_path):
    """Three seats, three candidates; Council leads the vote 2 first places to 1."""
    panel = Panel(tmp_path)
    panel.propose(2, "Council", "Quorum")
    panel.propose(3, "Monolith")
    panel.propose(4, "council")
    assert panel("pool").returncode == 0
    c = panel.ids()
    panel.vote(2, c["Council"] + c["Monolith"] + c["Quorum"])
    panel.vote(3, c["Monolith"] + c["Council"] + c["Quorum"], reject=c["Quorum"])
    panel.vote(4, c["Council"] + c["Quorum"] + c["Monolith"])
    assert panel("tally").returncode == 0
    return panel


# ---------------------------------------------------------------- the ballots are blind


def test_every_order_is_a_permutation_and_no_candidate_keeps_a_position():
    bad = lib(
        "[(k, n) for k in range(2, 13) for n in range(2, 12) "
        "for rows in [seele.orders(k, n, random.Random(k * 100 + n))] "
        "if any(sorted(r) != list(range(k)) for r in rows) "
        "or any(max(sum(1 for r in rows if r[p] == c) for p in range(k)) > -(-n // k) "
        "for c in range(k))]"
    )
    assert bad == []


def test_with_an_even_count_every_candidate_follows_every_other_exactly_once():
    # Rotating one list would keep each candidate behind the same neighbour on every ballot.
    bad = lib(
        "[k for k in range(2, 13, 2) if len({(r[i], r[i + 1]) "
        "for r in seele.orders(k, k, random.Random(k)) for i in range(k - 1)}) != k * (k - 1)]"
    )
    assert bad == []


def test_a_ballot_hides_authors_and_uses_labels_the_brief_does_not(tmp_path):
    panel = Panel(tmp_path, brief="Name it. Hypothesis H2 and model K7 are in scope.")
    panel.propose(2, "Council", "Quorum B4")
    panel.propose(3, "Monolith")
    panel.propose(4, "Chamber")
    assert panel("pool").returncode == 0
    data, orders = panel.data, []
    for seat in data["seats"]:
        page = (pathlib.Path(seat["dir2"]) / "ballot.md").read_text(encoding="utf-8")
        # The seat's own proposal is in another folder: a ballot's folder holds the ballot.
        assert os.listdir(seat["dir2"]) == ["ballot.md"]
        codes = data["ballots"][str(seat["n"])]["codes"]
        assert not {"H2", "K7", "B4"} & set(codes)
        assert len({code[0] for code in codes}) == len(codes) == 4
        assert "case for" not in page  # a pitch is a fingerprint, and long pitches win votes
        assert not re.search(r"SEELE \d|opus|sonnet|haiku|claude", page, re.I)
        assert seat["dir"] not in page and str(panel.dir) not in page
        assert pathlib.Path(seat["dir"]).name not in page
        orders.append(tuple(data["ballots"][str(seat["n"])]["order"]))
    assert len(set(orders)) == 3
    assert len({order[0] for order in orders}) == 3
    labels = [tuple(data["ballots"][str(s["n"])]["codes"]) for s in data["seats"]]
    assert len(set(labels)) == 3  # one seat's label for a candidate means nothing to another


def test_a_label_the_brief_or_a_candidate_uses_never_labels_a_ballot(tmp_path):
    # The brief names every label but four, and one candidate names a fourth: three are left.
    every = lib("[a + b for a in seele.CODE_LETTERS for b in seele.CODE_DIGITS]")
    spare = ["B2", "K7", "Z9", "M4"]
    brief = "Name it. In scope: " + ", ".join(c.lower() for c in every if c not in spare)
    panel = Panel(tmp_path, brief=brief)
    panel.propose(2, "Council (M4)")
    panel.propose(3, "Monolith")
    panel.propose(4, "Chamber")
    assert panel("pool").returncode == 0
    for ballot in panel.data["ballots"].values():
        assert sorted(ballot["codes"]) == ["B2", "K7", "Z9"]
    panel.propose(4, "Chamber", "Quorum")
    out = panel("pool")
    assert out.returncode == 1 and "4 candidates are more than the 3 free labels" in out.stderr


def test_letters_and_ballot_names_do_not_follow_the_seats(tmp_path):
    """Candidate A is not always the first seat's, and J1 is not always the first seat."""
    first_letter, first_judge = set(), set()
    for seed in range(8):
        panel = Panel(tmp_path / str(seed), *CLAUDE3, "--seed", str(seed))
        for n, name in ((2, "Council"), (3, "Monolith"), (4, "Chamber")):
            panel.propose(n, name)
        assert panel("pool").returncode == 0
        c = panel.ids()
        for n in (2, 3, 4):
            panel.vote(n, c["Council"] + c["Monolith"] + c["Chamber"])
        assert panel("tally").returncode == 0
        first_letter.add(c["Council"])
        first_judge.add(panel.data["judges"]["2"])
    assert len(first_letter) > 1 and len(first_judge) > 1


def test_seat_folders_do_not_lead_to_each_other_or_to_the_run(tmp_path):
    panel = Panel(tmp_path)
    dirs = [pathlib.Path(s["dir"]) for s in panel.data["seats"]]
    for folder in [pathlib.Path(s["dir2"]) for s in panel.data["seats"]]:
        assert stat.S_IMODE(folder.stat().st_mode) == 0o700 and not os.listdir(folder)
    for folder in dirs:
        assert re.fullmatch(r"[0-9a-f]{16}", folder.name)
        assert panel.dir not in folder.parents and folder.parent != panel.dir.parent
        assert stat.S_IMODE(folder.stat().st_mode) == 0o700
        assert stat.S_IMODE(folder.parent.stat().st_mode) == 0o700  # the names stay private too
        page = (folder / "round1.md").read_text(encoding="utf-8")
        assert "Name the tool." in page and not re.search(r"SEELE \d|opus", page)
    pages = {(d / "round1.md").read_text(encoding="utf-8") for d in dirs}
    assert len(pages) == 1  # one shared brief, byte for byte


def test_the_docket_tells_the_chair_no_seat_model_or_author(voted):
    data = voted.data
    docket = (pathlib.Path(data["chair"]["dir"]) / "docket.md").read_text(encoding="utf-8")
    assert not re.search(r"SEELE \d|opus|sonnet|haiku|claude|anthropic|Proposed by", docket, re.I)
    # Points less the other seats' average would tell the chair who wrote what.
    assert "other seats" not in docket and "one model family" in docket
    for seat in data["seats"]:
        assert seat["dir"] not in docket and seat["dir2"] not in docket
        for code in data["ballots"][str(seat["n"])]["codes"]:
            assert code not in docket  # private labels are translated to candidate ids
    assert sorted(data["judges"].values()) == ["J1", "J2", "J3"]
    assert "### J1" in docket and "case for Monolith" in docket and "PICK: one letter" in docket


def test_the_docket_leaves_out_the_recount_that_would_point_at_an_author(tmp_path):
    panel = Panel(tmp_path)
    for n, name in ((2, "Alpha"), (3, "Beta"), (4, "Gamma")):
        panel.propose(n, name)
    assert panel("pool").returncode == 0
    c = panel.ids()
    a, b, g = c["Alpha"], c["Beta"], c["Gamma"]
    panel.vote(2, a + b + g)
    panel.vote(3, a + b + g)
    panel.vote(4, b + g + a)
    told = panel("tally").stdout  # the session sees the flag, and so does the report
    assert f"{b} leads on that count, {a} on the full count" in told
    docket = (pathlib.Path(panel.data["chair"]["dir"]) / "docket.md").read_text(encoding="utf-8")
    assert "own author" not in docket and "leads on that count" not in docket


# ---------------------------------------------------------------- reading what models write


def test_proposals_survive_markdown_quotes_preamble_and_a_restated_form():
    text = textwrap.dedent("""\
        Sure, here is my answer.

        PROPOSAL 1: <the answer itself, on one line>
        **PROPOSAL 1:** "Council of Voices"
        **WHY 1:** short,
        and plain
        - Proposal 2: `Quorum`
        > WHY 2: counts
        PROPOSAL 3: Third
        """)
    got = lib(f"seele.parse_proposal({text!r}, 2)")
    assert [p["text"] for p in got["proposals"]] == ["Council of Voices", "Quorum"]
    assert got["proposals"][0]["why"] == "short, and plain"
    assert got["extra"] == 1


def test_a_form_copied_back_is_not_an_answer():
    form = lib("seele.ROUND1['decide']")
    assert lib(f"seele.parse_proposal({form!r}, 2)")["proposals"] == []
    got = lib(f"seele.parse_proposal({form + chr(10) + 'PROPOSAL 1: Council'!r}, 2)")
    assert [p["text"] for p in got["proposals"]] == ["Council"]
    ballot = lib(
        "'ASSESS K7: ' + seele.ASSESS_HELP + '\\nRANKING: ' + seele.RANKING_HELP"
        " + '\\nREJECT: ' + seele.REJECT_HELP['decide'] + '\\nOBJECTION: ' + seele.OBJECTION_HELP"
    )
    vote = lib(f"seele.parse_vote({ballot!r}, {{'K7': 'A'}})")
    assert vote == {"ranking": [], "reject": [], "assess": {}, "objection": ""}
    ruling = lib("seele.parse_ruling(seele.RULING_VERDICT + seele.RULING_FORM, ['A', 'B'])")
    assert set(ruling.values()) == {""}
    # Copied loosely, and with a separator before the real ruling: still the form, not an answer.
    loose = "PROPOSAL 1: The answer itself, on one line.\nPROPOSAL 1: Council"
    assert [p["text"] for p in lib(f"seele.parse_proposal({loose!r}, 2)")["proposals"]] == [
        "Council"
    ]
    restated = lib(
        "seele.parse_ruling("
        "seele.RULING_FORM + '\\n---\\nPICK: B\\nDISSENT: J2 saw the cost', ['A', 'B'])"
    )
    assert (restated["PICK"], restated["DISSENT"]) == ("B", "J2 saw the cost")


def test_a_line_of_prose_that_opens_like_a_key_stays_in_its_proposal():
    text = (
        "PROPOSAL 1: Replace the claim in section 2\nReason (see section 2): too strong\nWHY 1: x"
    )
    (got,) = lib(f"seele.parse_proposal({text!r}, 5)")["proposals"]
    assert got["text"] == "Replace the claim in section 2 Reason (see section 2): too strong"


def test_a_pitch_longer_than_a_page_is_cut_and_marked():
    text = "PROPOSAL 1: Council\nWHY 1: " + "w" * 1001
    (got,) = lib(f"seele.parse_proposal({text!r}, 2)")["proposals"]
    assert got["why"] == "w" * 1000 + " [cut]"


def test_a_proposal_too_long_for_a_ballot_is_left_out_and_said_so(tmp_path):
    panel = Panel(tmp_path)
    panel.propose(2, "x" * 2001, "Council")
    panel.propose(3, "y" * 2000)
    panel.propose(4, "z" * 2001)
    out = panel("pool").stdout
    assert "SEELE 02 round 1: SOUND ONLY, 1 proposed, 1 over 2000 characters ignored" in out
    assert "SEELE 04 round 1: NO SIGNAL: each of its proposals is over 2000 characters" in out
    assert set(panel.ids()) == {"Council", "y" * 2000}
    (tmp_path / "mine.txt").write_text("Quorum\n" + "q" * 2001 + "\n", encoding="utf-8")
    refused = panel("pool", "--add", str(tmp_path / "mine.txt"))
    assert refused.returncode == 1 and "--add line 2 is over 2000 characters" in refused.stderr


def test_only_the_same_words_pool_as_one_candidate(tmp_path):
    panel = Panel(tmp_path)
    panel.propose(2, "Use C++", "Rewrite it")
    panel.propose(3, "Use C#", "use  c++.")
    panel.propose(4, "Re-write it")
    assert panel("pool").returncode == 0
    assert set(panel.ids()) == {"Use C++", "Use C#", "Rewrite it", "Re-write it"}
    authors = {c["text"]: c["authors"] for c in panel.data["candidates"]}
    assert authors["Use C++"] == [2, 3] and authors["Use C#"] == [3]


@pytest.mark.parametrize(
    ("body", "ranking", "reject"),
    [
        ("RANKING: K7 > Q2 > M4\nREJECT: none", ["A", "B", "C"], []),
        ("**RANKING:** [k7], [q2], [m4]\nREJECT: M4", ["A", "B", "C"], ["C"]),
        ("RANKING: <best> > <worst>\nRANKING: Q2 > K7\nREJECT: none (M4 is weak)", ["B", "A"], []),
        ("RANKING:\n1. M4\n2. K7\n3. Q2\n4. M4\nREJECT: K7 and Z9", ["C", "A", "B"], ["A"]),
        ("My ranking is K7 then Q2.", [], []),
        ("RANKING: K7 > Q2\nREJECT: No, Q2 should go", ["A", "B"], ["B"]),
        ("ASSESS K7 (the short one): fine\nRANKING: K7 > M4\nREJECT: n/a", ["A", "C"], []),
    ],
)
def test_votes_parse_in_the_shapes_models_write(body, ranking, reject):
    codes = {"K7": "A", "Q2": "B", "M4": "C"}
    got = lib(f"seele.parse_vote({body!r}, {codes!r})")
    assert (got["ranking"], got["reject"]) == (ranking, reject)


def test_a_seat_s_labels_are_translated_in_its_reasons():
    body = "ASSESS [K7]: clearer than Q2, unlike m4\nRANKING: K7 > Q2 > M4\nOBJECTION: K7 is long"
    got = lib(f"seele.parse_vote({body!r}, {{'K7': 'A', 'Q2': 'B', 'M4': 'C'}})")
    assert got["assess"] == {"A": "clearer than [B], unlike [C]"}
    assert got["objection"] == "[A] is long"
    for said, kept in (
        ("None.", ""),
        ("No objection.", ""),
        ("No real objection to raise", ""),
        ("None given.", ""),
        ("No.", ""),
        ("Nothing to add.", ""),
        ("No candidate names the cause", "No candidate names the cause"),
        ("None of the others names the cause", "None of the others names the cause"),
    ):
        got = lib(
            f"seele.parse_vote({'RANKING: K7' + chr(10) + 'OBJECTION: ' + said!r}, {{'K7': 'A'}})"
        )
        assert got["objection"] == kept
    noted = lib("seele.parse_vote('ASSESS K7 (Council): short', {'K7': 'A'})")
    assert noted["assess"] == {"A": "short"}


# ---------------------------------------------------------------- the count


def count(ids: str, authors: dict, votes: dict) -> dict:
    authors = {c: authors.get(c, []) for c in ids}
    ballots = {
        n: {"ranking": list(r), "reject": list(x), "assess": {}, "objection": ""}
        for n, (r, x) in votes.items()
    }
    expr = f"seele.count({list(ids)!r}, {authors!r}, {{int(k): v for k, v in {ballots!r}.items()}})"
    return lib(expr)


def test_borda_points_first_choices_and_full_agreement():
    got = count("ABC", {}, {2: ("ABC", ""), 3: ("ABC", ""), 4: ("ABC", "")})
    assert got["points"] == {"A": 6, "B": 3, "C": 0}
    assert got["first"] == {"A": 3, "B": 0, "C": 0}
    assert got["leaders"] == ["A"] and got["w"] == pytest.approx(1.0)


def test_w_is_zero_when_the_ballots_cancel_out():
    got = count("ABC", {}, {2: ("ABC", ""), 3: ("BCA", ""), 4: ("CAB", "")})
    assert got["w"] == pytest.approx(0.0)
    assert got["leaders"] == ["A", "B", "C"] and got["head_to_head"] is None


def test_unranked_candidates_share_the_points_left():
    got = count("ABCD", {}, {2: ("A", ""), 3: ("AB", "")})
    assert got["points"] == {"A": 6, "B": 3, "C": 1.5, "D": 1.5}
    assert 0 < got["w"] <= 1
    # Two seats, three candidates, one ballot that ties B with C: S = 6.5, and the tie takes
    # 2 x (2^3 - 2) off the denominator, so W = 78 / 84. Without the correction it is 78 / 96.
    tied = count("ABC", {}, {2: ("ABC", ""), 3: ("A", "")})
    assert tied["w"] == pytest.approx(78 / 84)


def test_points_winner_and_head_to_head_winner_can_differ_and_the_flag_says_so(tmp_path):
    votes = {n: ("ABC", "") for n in (2, 3, 4)}
    votes.update({5: ("BCA", ""), 6: ("BCA", "")})
    got = count("ABC", {}, votes)
    assert got["points"] == {"A": 6, "B": 7, "C": 2}
    assert got["leaders"] == ["B"] and got["head_to_head"] == "A"
    data = {"seats": [{"n": n, "family": "x" if n < 4 else "y"} for n in votes]}
    got["votes"] = {str(n): {} for n in votes}
    flags = lib(f"seele.flags({data!r}, json.loads({json.dumps(got)!r}))")
    assert flags == ["B leads on points, but A beats every other candidate head to head."]


def test_a_majority_reject_takes_the_leader_out_of_the_vote():
    votes = {2: ("ABC", "A"), 3: ("ABC", "A"), 4: ("ABC", "")}
    got = count("ABC", {}, votes)
    assert got["declined"] == ["A"] and got["leaders"] == ["B"]
    assert got["order"] == ["B", "C", "A"]
    half = count("ABCD", {}, {n: ("ABCD", "A" if n < 4 else "") for n in (2, 3, 4, 5)})
    assert half["declined"] == [] and half["leaders"] == ["A"]  # two of four is not a majority


def test_the_lead_is_recounted_without_each_author_s_own_ballot():
    # Seats 2 and 4 both wrote A and rank it first; the two seats that did not prefer B.
    votes = {2: ("ACB", ""), 3: ("BAC", ""), 4: ("ABC", ""), 5: ("BAC", "")}
    got = count("ABC", {"A": [2, 4]}, votes)
    assert got["leaders"] == ["A"]
    assert got["others"]["A"] == pytest.approx(1.0) and got["others"]["B"] == pytest.approx(1.25)
    assert got["others_leaders"] == ["B"]
    data = {"seats": [{"n": n, "family": str(n)} for n in votes]}
    got["votes"] = {str(n): {} for n in votes}
    (flag,) = lib(f"seele.flags({data!r}, json.loads({json.dumps(got)!r}))")
    assert "B leads on that count, A on the full count" in flag


def test_a_leader_every_voter_wrote_has_no_outside_count_and_no_flag():
    # Both ballots come from A's authors, so nobody outside them ranked A at all.
    votes = {2: ("ABC", ""), 3: ("ACB", "")}
    got = count("ABC", {"A": [2, 3], "B": [4], "C": [2]}, votes)
    assert got["leaders"] == ["A"] and got["others"]["A"] is None
    data = {"seats": [{"n": n, "family": str(n)} for n in votes]}
    got["votes"] = {str(n): {} for n in votes}
    assert lib(f"seele.flags({data!r}, json.loads({json.dumps(got)!r}))") == []


@pytest.mark.parametrize(
    ("x", "text"), [(6.0, "6"), (1.5, "1.5"), (1.125, "1.13"), (4 / 3, "1.33")]
)
def test_numbers_print_short_and_round_halves_up(x, text):
    assert lib(f"seele.num({x!r})") == text


def test_one_family_of_models_is_flagged_as_weaker_evidence(voted):
    (flag,) = voted.data["tally"]["flags"]
    assert "one model family (anthropic)" in flag


# ---------------------------------------------------------------- the report


RULING = "PICK: {pick}\nAMENDED: {amended}\nWHY: J1 and J2 agree.\nOBJECTION: it is obscure\n"


def test_a_chair_that_agrees_with_the_vote_says_so(voted):
    voted.rule(RULING.format(pick=voted.ids()["Council"], amended="none"))
    out = voted("report", "--chair-model", "fable")
    assert out.returncode == 0, out.stderr
    assert "The chair's pick is also the vote's winner." in out.stdout
    assert "overruled" not in out.stdout and "Amended" not in out.stdout
    assert (
        "SOUND ONLY" in out.stdout and "| SEELE 01 | fable (chair: no seat, no vote)" in out.stdout
    )
    assert "SEELE 03" in out.stdout and "ranked " + voted.ids()["Monolith"] + " first" in out.stdout
    assert not re.search(r"\bJ[123]\b", out.stdout)  # ballot labels become seat names
    assert "same model" not in out.stdout
    filed = (voted.dir / "report.md").read_text(encoding="utf-8")
    assert "![SEELE](seele-logo.png)" in filed and "# SEELE verdict: A name" in filed
    assert (voted.dir / "seele-logo.png").read_bytes()[:4] == b"\x89PNG"


def test_a_chair_that_overrules_the_vote_is_reported_beside_it(voted):
    c = voted.ids()
    voted.rule(RULING.format(pick=f"**{c['Monolith']}**", amended="The Monolith"))
    out = voted("report", "--chair-model", "opus").stdout
    assert "**The chair overruled the vote.**" in out
    assert f"The seats' vote put {c['Council']} first; the chair picked {c['Monolith']}." in out
    assert f"- **The vote** put {c['Council']} first" in out  # the vote is the first dissent
    assert "(the seats did not vote on this wording): **The Monolith**" in out
    assert "same model as SEELE 02" in out  # an opus chair is no check on the opus seat


@pytest.mark.parametrize(
    "pick",
    [
        *["the second one", "A good name is B", "I pick B", "B or C", "B and C tie", "A Council"],
        *["B, or C", "B / C", "B & C", "B; and C"],
    ],
)
def test_a_ruling_that_names_no_candidate_is_refused(voted, pick):
    voted.rule(f"PICK: {pick}\nWHY: it is best\n")
    out = voted("report")
    assert out.returncode == 1 and "names no candidate" in out.stderr
    assert not (voted.dir / "report.md").exists()


@pytest.mark.parametrize(
    "pick",
    [
        *["B", "b", "**B**", "[B]", "B.", "B (unamended)", "B: Council", "Candidate B", "B, as is"],
        *[
            "B) Council",
            "B's wording",
            "Candidate: B",
            "Letter B",
            "B Council",
            "B because it fits",
        ],
    ],
)
def test_a_pick_is_read_in_the_shapes_a_chair_writes(pick):
    assert lib(f"seele.parse_ruling({'PICK: ' + pick!r}, ['A', 'B', 'C'])")["PICK"] == "B"


def test_an_answer_that_reads_like_another_field_s_form_text_is_kept():
    got = lib("seele.parse_proposal('PROPOSAL 1: One sentence.', 2)")
    assert [p["text"] for p in got["proposals"]] == ["One sentence."]


@pytest.mark.parametrize("pick", ["I'd go with C", "I\u2019d pick D", "I'm torn; C", "I 'd say B"])
def test_the_word_i_is_not_candidate_i(pick):
    ids = list("ABCDEFGHIJK")
    assert lib(f"seele.parse_ruling({'PICK: ' + pick!r}, {ids!r})")["PICK"] == ""
    assert lib(f"seele.parse_ruling('PICK: I. Council', {ids!r})")["PICK"] == "I"


def test_a_key_line_padded_with_spaces_does_not_stall_the_clerk():
    start = time.monotonic()
    padded = (
        "PROPOSAL"
        + " " * 20000
        + "\nASSESS K7 (short)"
        + " \t" * 10000
        + "x\nPROPOSAL 1:   Council"
    )
    got = lib(f"seele.parse_proposal({padded!r}, 2)")
    assert [p["text"] for p in got["proposals"]] == ["Council"]
    assert time.monotonic() - start < 5


def test_a_chair_nobody_named_is_not_called_none(voted):
    voted.rule(RULING.format(pick=voted.ids()["Council"], amended="none"))
    assert "| SEELE 01 | model not named (chair: no seat, no vote)" in voted("report").stdout


def test_without_a_chair_the_report_says_the_vote_stands_alone(voted):
    out = voted("report").stdout
    assert "No chair ruled, so this is the vote's winner and nothing more." in out
    assert f"**{voted.ids()['Council']}. Council**" in out
    banner = out.split("```")[1].splitlines()
    assert banner[3].split("│")[1].strip() == "NO" and banner[4].split("│")[1].strip() == "SIGNAL"


def test_when_every_seat_proposes_the_same_thing_no_vote_is_held(tmp_path):
    panel = Panel(tmp_path)
    for n, text in ((2, "Council"), (3, '"council."'), (4, "COUNCIL")):
        panel.propose(n, text)
    out = panel("pool")
    assert "skip round 2" in out.stdout
    assert not (panel.seat(2) / "ballot.md").exists()
    report = panel("report")
    assert report.returncode == 0 and "No vote was needed" in report.stdout


def test_the_user_s_own_candidates_enter_the_pool_unnamed(tmp_path):
    panel = Panel(tmp_path)
    panel.propose(2, "Council")
    panel.propose(3, "Monolith")
    (tmp_path / "mine.txt").write_text("Chamber\n\nmonolith\n", encoding="utf-8")
    assert panel("pool", "--add", str(tmp_path / "mine.txt")).returncode == 0
    by_text = {c["text"]: c["authors"] for c in panel.data["candidates"]}
    assert by_text == {"Council": [2], "Monolith": [3, 0], "Chamber": [0]}
    c = panel.ids()
    for n in (2, 3, 4):  # seat 4 proposed nothing and still judges
        panel.vote(n, c["Chamber"] + c["Council"] + c["Monolith"])
    assert panel("tally").returncode == 0
    assert "| the user |" in panel("report").stdout


def test_review_mode_sorts_changes_by_how_the_seats_split(tmp_path):
    panel = Panel(tmp_path, *CLAUDE3, "--mode", "review")
    panel.propose(2, "Scope H2 to Qt", "Cut the pilot sentence", verdict="Accept")
    panel.propose(3, "Narrow H2 to the Qt case", "Add a threat", verdict="accept.")
    panel.propose(4, "Inline the prompt", verdict="Reject")
    assert panel("pool").returncode == 0
    c = panel.ids()
    out = panel("merge", c["Scope H2 to Qt"], c["Narrow H2 to the Qt case"])
    assert out.returncode == 0, out.stderr
    c = panel.ids()
    assert "Narrow H2 to the Qt case" not in c
    merged = next(x for x in panel.data["candidates"] if x["text"] == "Scope H2 to Qt")
    assert merged["authors"] == [2, 3]
    scope, cut, threat, inline = (
        c[t]
        for t in ("Scope H2 to Qt", "Cut the pilot sentence", "Add a threat", "Inline the prompt")
    )
    panel.vote(2, scope + threat + cut + inline, reject=inline)
    panel.vote(3, scope + cut + threat + inline, reject=inline + cut)
    panel.vote(4, scope + inline + threat + cut)
    assert panel("tally").returncode == 0
    panel.rule(f"VERDICT: accept\nPICK: {scope}\nWHY: every seat ranked it first\n")
    out = panel("report", "--chair-model", "fable").stdout
    assert (
        "**Recommendation: Accept, 2 of 3 (SEELE 02, SEELE 03); Reject, 1 of 3 (SEELE 04).**" in out
    )
    assert "The chair: accept." in out
    agreed, rest = out.split("## Your call (the seats split)")
    split, declined = rest.split("## Declined (a majority rejected these)")
    assert (
        f"| {scope} | Scope H2 to Qt | 2 of 3 |" in agreed
        and f"| {threat} | Add a threat" in agreed
    )
    assert f"- **{cut}.** Cut the pilot sentence. Raised by SEELE 02; rejected by 1 of 3." in split
    assert "Inline the prompt" in declined and "rejected by 2 of 3" in declined
    assert f"SEELE 02: seat 2 on [{inline}]. SEELE 03: seat 3 on [{inline}]." in declined
    assert "The clerk merged" in out


# ---------------------------------------------------------------- refusals


def test_pooling_or_merging_after_a_vote_is_refused(voted):
    before = voted.data["ballots"]
    for command in (("pool",), ("merge", "A", "B")):
        out = voted(*command)
        assert out.returncode == 1 and "votes already" in out.stderr
    assert voted.data["ballots"] == before


def test_a_merge_that_would_leave_one_candidate_is_refused(tmp_path):
    panel = Panel(tmp_path, "--mode", "review")
    panel.propose(2, "Cut the second example", verdict="minor revision")
    panel.propose(3, "Drop example two", verdict="minor revision")
    panel.propose(4, verdict="accept")
    panel("pool")
    out = panel("merge", *panel.ids().values())
    assert out.returncode == 1 and "nothing to vote on" in out.stderr
    assert len(panel.ids()) == 2


def test_one_answer_is_not_a_panel(tmp_path):
    panel = Panel(tmp_path)
    panel.propose(2, "Council", "Quorum")
    (panel.seat(3) / "proposal.md").write_text("I would rather not.", encoding="utf-8")
    out = panel("pool")
    assert out.returncode == 1 and "a panel needs two" in out.stderr
    assert "SEELE 03 round 1: NO SIGNAL: its answer has no usable PROPOSAL line" in out.stdout
    assert panel.data["candidates"] == []


def test_one_ballot_is_not_a_count(tmp_path):
    panel = Panel(tmp_path)
    panel.propose(2, "Council")
    panel.propose(3, "Monolith")
    assert panel("pool").returncode == 0
    panel.vote(2, "AB")
    out = panel("tally")
    assert out.returncode == 1 and "a count needs two" in out.stderr
    assert panel("report").returncode == 1


@pytest.mark.parametrize(
    "spec",
    [
        "claude:",
        "claude:--model",
        "agy:--dangerously",
        "fleet:codex",
        "copilot:gpt",
        "ollama:",
        "cmd:Bad Name=cat",
        "cmd:x=",
        "cmd:x='unclosed",
        "gemini",
    ],
)
def test_a_seat_spec_that_could_inject_an_option_or_names_nothing_is_refused(tmp_path, spec):
    (tmp_path / "b.md").write_text("q", encoding="utf-8")
    out = run(
        tmp_path,
        "open",
        "--brief",
        str(tmp_path / "b.md"),
        "--topic",
        "t",
        "--seat",
        spec,
        "--seat",
        "claude:opus",
    )
    assert out.returncode == 1 and "seat" in out.stderr
    assert not (tmp_path / "seele").exists()


def test_open_refuses_an_empty_brief_a_lone_seat_and_a_thirteenth_monolith(tmp_path):
    (tmp_path / "empty.md").write_text(" \n", encoding="utf-8")
    (tmp_path / "b.md").write_text("q", encoding="utf-8")
    assert (
        "is empty"
        in run(tmp_path, "open", "--brief", str(tmp_path / "empty.md"), "--topic", "t").stderr
    )
    one = run(
        tmp_path, "open", "--brief", str(tmp_path / "b.md"), "--topic", "t", "--seat", "claude:opus"
    )
    assert one.returncode == 1 and "2 to 11 seats" in one.stderr
    twelve = [x for _ in range(12) for x in ("--seat", "claude:opus")]
    assert (
        run(tmp_path, "open", "--brief", str(tmp_path / "b.md"), "--topic", "t", *twelve).returncode
        == 1
    )
    missing = run(tmp_path, "tally", "--run", str(tmp_path / "nowhere"))
    assert missing.returncode == 1 and "no run.json" in missing.stderr


# ---------------------------------------------------------------- lanes to other CLIs


def stub(bin_dir: pathlib.Path, name: str, body: str) -> None:
    bin_dir.mkdir(exist_ok=True)
    path = bin_dir / name
    path.write_text("#!/bin/sh\n" + textwrap.dedent(body), encoding="utf-8")
    path.chmod(0o755)


ANSWER = "PROPOSAL 1: From %s\\nWHY 1: stub\\n"


@pytest.fixture
def lanes(tmp_path):
    """Stub CLIs that record how they were called."""
    bin_dir, seen = tmp_path / "bin", tmp_path / "seen"
    seen.mkdir()
    stub(
        bin_dir,
        "agy",
        f"""\
        printf '%s\\n' "$@" > {seen}/agy.argv
        ls -A > {seen}/agy.cwd
        while [ $# -gt 0 ]; do [ "$1" = --settings ] && cp "$2" {seen}/agy.settings; shift; done
        printf '{ANSWER % "agy"}'
        """,
    )
    stub(
        bin_dir,
        "copilot",
        f"""\
        printf '%s\\n' "$@" > {seen}/copilot.argv
        ls -A > {seen}/copilot.cwd
        printf '{ANSWER % "copilot"}'
        """,
    )
    stub(
        bin_dir,
        "ollama",
        f"""\
        printf '%s\\n' "$@" > {seen}/ollama.argv
        cat > {seen}/ollama.stdin
        printf '{ANSWER % "ollama"}'
        """,
    )
    stub(
        bin_dir,
        "fleet",
        f"""\
        if [ "$2" = --help ]; then
          echo 'fleet delegate [--engine auto|agy|copilot] TASK-FILE'; exit 0
        fi
        printf '%s\\n' "$@" > {seen}/fleet.argv
        while [ $# -gt 1 ]; do [ "$1" = --dir ] && dir=$2; shift; done
        git -C "$dir" rev-parse HEAD > {seen}/fleet.head
        git -C "$dir" ls-files > {seen}/fleet.files
        cp "$1" {seen}/fleet.task
        printf '> Unverified lead from agy (gemini-x).\\n\\n{ANSWER % "fleet"}' > {seen}/answer.md
        echo "engine=agy model=gemini-x status=ok path={seen}/answer.md id=1"
        """,
    )
    return bin_dir, seen


def test_each_cli_seat_runs_locked_in_an_empty_folder_and_answers(tmp_path, lanes):
    bin_dir, seen = lanes
    path = f"{bin_dir}{os.pathsep}{os.environ['PATH']}"
    seats = [
        "agy:gemini-pro",
        "copilot",
        "ollama:qwen3",
        "fleet:agy",
        "cmd:echo=sh -c 'cat >/dev/null; echo PROPOSAL 1: From cmd'",
    ]
    panel = Panel(tmp_path / "s", *[x for s in seats for x in ("--seat", s)], path=path)
    out = panel("ask", "--round", "1")
    assert out.stdout.count("SOUND ONLY") == 5, out.stdout + out.stderr
    assert panel("pool").returncode == 0
    assert set(panel.ids()) == {f"From {x}" for x in ("agy", "copilot", "ollama", "fleet", "cmd")}

    page = (panel.seat(2) / "round1.md").read_text(encoding="utf-8")
    agy = (seen / "agy.argv").read_text().split("\n")
    assert agy[0] == "-p" and "--sandbox" in agy and agy[agy.index("--model") + 1] == "gemini-pro"
    lock = json.loads((seen / "agy.settings").read_text())
    assert {"write_file(*)", "command(*)", "read_url(*)"} <= set(lock["permissions"]["deny"])
    assert lock["allowNonWorkspaceAccess"] is False and len(lock["trustedWorkspaces"]) == 1
    copilot = (seen / "copilot.argv").read_text()
    for flag in (
        "--deny-tool=write",
        "--deny-tool=shell",
        "--no-ask-user",
        "--disable-builtin-mcps",
    ):
        assert flag in copilot
    assert (seen / "agy.cwd").read_text() == "" and (seen / "copilot.cwd").read_text() == ""
    assert (seen / "ollama.argv").read_text().split() == ["run", "qwen3"]
    assert (seen / "ollama.stdin").read_text() == page
    fleet = (seen / "fleet.argv").read_text().split("\n")
    assert fleet[:5] == ["delegate", "--engine", "agy", "--kind", "draft"]
    assert re.fullmatch(r"[0-9a-f]{40,}\n", (seen / "fleet.head").read_text())
    assert (seen / "fleet.files").read_text() == ""  # the snapshot holds nothing
    assert (seen / "fleet.task").read_text() == page
    assert "Unverified lead" not in (panel.seat(5) / "proposal.md").read_text()
    assert json.loads((panel.dir / "lane-5.json").read_text()) == {"model": "gemini-x"}
    assert sorted(os.listdir(panel.seat(5))) == ["proposal.md", "round1.md"]


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:  # killed but not yet reaped still answers signal 0
        return pathlib.Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return True


def test_a_lane_that_times_out_leaves_no_process_behind(tmp_path, lanes):
    bin_dir, seen = lanes
    # The CLI dies on TERM; the child it started ignores TERM and would hold on for a minute.
    stub(
        bin_dir,
        "stubborn",
        f"""\
        (trap '' TERM; exec sh -c 'echo $$ > {seen}/child.pid; exec sleep 60') &
        wait
        """,
    )
    path = f"{bin_dir}{os.pathsep}{os.environ['PATH']}"
    panel = Panel(
        tmp_path / "s", "--seat", "claude:opus", "--seat", "cmd:stubborn=stubborn", path=path
    )
    out = panel("ask", "--round", "1", "--timeout", "1").stdout
    pid = int((seen / "child.pid").read_text())
    try:
        assert "NO SIGNAL: no answer after 1 s" in out
        deadline = time.monotonic() + 5
        while alive(pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not alive(pid)
    finally:
        if alive(pid):
            os.kill(pid, signal.SIGKILL)


def test_the_fleet_workspace_is_made_without_the_user_s_git_hooks(tmp_path, lanes):
    bin_dir, _ = lanes
    hooks = tmp_path / "hooks"
    stub(hooks, "pre-commit", "echo 'hook ran' >&2; exit 1")
    config = tmp_path / "gitconfig"
    config.write_text(f"[core]\n\thooksPath = {hooks}\n", encoding="utf-8")
    path = f"{bin_dir}{os.pathsep}{os.environ['PATH']}"
    panel = Panel(tmp_path / "s", "--seat", "claude:opus", "--seat", "fleet:agy", path=path)
    out = panel("ask", "--round", "1", env={"GIT_CONFIG_GLOBAL": str(config)})
    assert "SEELE 03 fleet:agy round 1: SOUND ONLY" in out.stdout, out.stdout + out.stderr


def test_a_lane_does_not_inherit_the_session_s_git_variables(tmp_path, lanes):
    bin_dir, _ = lanes
    stub(bin_dir, "gitenv", 'cat > /dev/null; echo "PROPOSAL 1: dir=${GIT_DIR:-unset}"')
    path = f"{bin_dir}{os.pathsep}{os.environ['PATH']}"
    panel = Panel(tmp_path / "s", "--seat", "claude:opus", "--seat", "cmd:gitenv=gitenv", path=path)
    out = panel("ask", "--round", "1", env={"GIT_DIR": str(tmp_path / "elsewhere")})
    assert "SOUND ONLY" in out.stdout, out.stdout + out.stderr
    assert "dir=unset" in (panel.seat(3) / "proposal.md").read_text()


def test_asking_again_and_failing_withdraws_the_earlier_answer(tmp_path, lanes):
    bin_dir, _ = lanes
    path = f"{bin_dir}{os.pathsep}{os.environ['PATH']}"
    panel = Panel(tmp_path / "s", "--seat", "claude:opus", "--seat", "copilot", path=path)
    assert "SOUND ONLY" in panel("ask", "--round", "1").stdout
    stub(bin_dir, "copilot", "echo 'quota exceeded' >&2; exit 3")
    assert "NO SIGNAL: exit 3" in panel("ask", "--round", "1", "--again").stdout
    assert sorted(os.listdir(panel.seat(3))) == ["proposal.md.failed", "round1.md"]
    stub(bin_dir, "copilot", f"printf '{ANSWER % 'copilot'}'")
    assert "SOUND ONLY" in panel("ask", "--round", "1", "--again").stdout
    assert sorted(os.listdir(panel.seat(3))) == ["proposal.md", "round1.md"]


def test_a_failed_lane_is_named_and_sits_out_round_two(tmp_path, lanes):
    bin_dir, _ = lanes
    stub(bin_dir, "copilot", "echo 'quota exceeded' >&2; exit 3")
    stub(bin_dir, "fleet", "echo 'engine=agy model=- status=quota path=/dev/null id=1'")
    path = f"{bin_dir}{os.pathsep}{os.environ['PATH']}"
    seats = [
        "claude:opus",
        "claude:sonnet",
        "copilot",
        "cmd:slow=sleep 30",
        "cmd:mute=true",
        "cmd:gone=/nonexistent/cli",
        "fleet:agy",
    ]
    panel = Panel(tmp_path / "s", *[x for s in seats for x in ("--seat", s)], path=path)
    out = panel("ask", "--round", "1", "--timeout", "1").stdout
    assert "SEELE 04 copilot round 1: NO SIGNAL: exit 3: quota exceeded" in out
    assert "SEELE 05 cmd:slow=sleep 30 round 1: NO SIGNAL: no answer after 1 s" in out
    assert (
        "SEELE 06 cmd:mute=true round 1: NO SIGNAL: the lane exited cleanly and said nothing" in out
    )
    assert "SEELE 07" in out and "could not start /nonexistent/cli" in out
    assert "SEELE 08 fleet:agy round 1: NO SIGNAL: fleet delegate: engine=agy" in out
    panel.propose(2, "Council")
    panel.propose(3, "Monolith")
    pooled = panel("pool").stdout
    assert "SEELE 04 round 1: NO SIGNAL: exit 3: quota exceeded" in pooled
    assert "run by `ask`" not in pooled.split("round 2:")[1]
    assert set(panel.data["ballots"]) == {"2", "3"}
    assert "no CLI seat to ask in round 2" in panel("ask", "--round", "2").stdout


def test_a_page_too_large_for_a_lane_is_refused_before_the_cli_runs(tmp_path, lanes):
    bin_dir, seen = lanes
    path = f"{bin_dir}{os.pathsep}{os.environ['PATH']}"
    panel = Panel(
        tmp_path / "s", "--seat", "fleet:agy", "--seat", "agy", brief="x" * 125000, path=path
    )
    out = panel("ask", "--round", "1").stdout
    assert "SEELE 02 fleet:agy round 1: NO SIGNAL: the page is" in out and "65536" in out
    assert "shorten the brief or a candidate" in out
    assert "SEELE 03 agy round 1: NO SIGNAL: the page is" in out and "120000" in out
    assert list(seen.iterdir()) == []


def test_the_lineup_takes_what_the_machine_has_and_never_needs_more_than_claude(tmp_path, lanes):
    bin_dir, _ = lanes
    bare = tmp_path / "bare"
    bare.mkdir()
    alone = run(tmp_path, "seats", path=str(bare)).stdout
    assert "lineup: claude:opus claude:sonnet claude:haiku" in alone and "leaves" not in alone
    full = run(tmp_path, "seats", path=f"{bin_dir}{os.pathsep}{bare}").stdout
    assert "lineup: claude:opus claude:sonnet fleet:agy fleet:copilot" in full
    assert "the brief goes to fleet:agy, fleet:copilot" in full and "ollama: found" in full
    stub(bin_dir, "fleet", "echo 'JetBrains Fleet launcher'")  # another tool with the same name
    other = run(tmp_path, "seats", path=f"{bin_dir}{os.pathsep}{bare}").stdout
    assert "lineup: claude:opus claude:sonnet agy copilot" in other
    kept = run(tmp_path, "seats", "--claude-only", path=f"{bin_dir}{os.pathsep}{bare}").stdout
    assert "lineup: claude:opus claude:sonnet claude:haiku" in kept


# ---------------------------------------------------------------- the skill and its agent


def test_the_seat_agent_can_only_read_and_write_and_pins_no_model():
    text = (PLUGIN / "agents" / "seele-seat.md").read_text(encoding="utf-8")
    meta = yaml.safe_load(text.split("---", 2)[1])
    assert meta["name"] == "seele-seat" and "model" not in meta
    assert {t.strip() for t in meta["tools"].split(",")} == {"Read", "Write"}
    assert "techne:seele-seat" in (SKILL / "SKILL.md").read_text(encoding="utf-8")


def test_every_command_and_flag_the_skill_names_exists_in_the_parser():
    options = lib(
        "{name: [o for a in p._actions for o in a.option_strings] "
        "for name, p in next(a for a in seele.build_parser()._actions "
        "if hasattr(a, 'choices') and a.choices).choices.items()}"
    )
    docs = [
        SKILL / "SKILL.md",
        *sorted((SKILL / "references").glob("*.md")),
        ROOT / "docs" / "skills" / "seele.md",
    ]
    calls = [
        m
        for doc in docs
        for m in re.findall(r"seele\.py\"? (\w+)([^\n`]*)", doc.read_text(encoding="utf-8"))
    ]
    assert {name for name, _ in calls} >= set(options)  # the skill uses every command
    for name, rest in calls:
        assert name in options, name
        for flag in re.findall(r"(?<![\w-])--[a-z][a-z-]*", rest):
            assert flag in options[name], (name, flag)


def test_the_skill_ships_the_logo_and_no_em_dash():
    assert (SKILL / "assets" / "seele-logo.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    for path in [
        SKILL / "SKILL.md",
        PLUGIN / "agents" / "seele-seat.md",
        *(SKILL / "references").glob("*.md"),
    ]:
        assert "—" not in path.read_text(encoding="utf-8"), path
