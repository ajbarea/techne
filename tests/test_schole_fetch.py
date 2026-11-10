import json
import os
import re
import stat
from pathlib import Path

import pytest
from schole import config, d2l, fetch

FIXTURE = Path(__file__).parent / "fixtures" / "schole_toc.json"
TOC = json.loads(FIXTURE.read_text())
SEEN = {
    "11": "2026-09-01T12:00:00.000Z",
    "21": "2026-09-08T12:00:00.000Z",
    "22": "2026-09-08T12:00:00.000Z",
    "31": "2026-09-09T12:00:00.000Z",
}


def modules(toc=TOC):
    return toc["Modules"]


def test_first_run_lists_every_visible_file_topic_as_new():
    mods, now = fetch.diff(modules(), {})
    assert {m.path: m.new for m in mods} == {
        "Week 1": ["Lecture One Slides"],
        "Week 2": ["Lecture Two Slides", "Homework Two"],
        "Week 2 / Extras": ["Practice Notebook"],
    }
    assert set(now) == {"11", "21", "22", "31"}  # no Link topic, no hidden topic


def test_only_a_later_date_counts_as_changed():
    mods, _ = fetch.diff(modules(), SEEN)
    assert [(m.path, m.new, m.changed) for m in mods] == [("Week 2", [], ["Homework Two"])]


def test_an_older_or_equal_server_date_is_not_a_change():
    seen = dict(SEEN, **{"22": "2026-09-21T00:00:00.000Z"})
    assert fetch.diff(modules(), seen)[0] == []


def test_a_missing_date_is_new_once_then_seen_after_a_record():
    toc = json.loads(FIXTURE.read_text())
    toc["Modules"][0]["Topics"][0]["LastModifiedDate"] = None
    mods, now = fetch.diff(toc["Modules"], {})
    assert now["11"] == "" and mods[0].new == ["Lecture One Slides"]
    assert "Week 1" not in [m.path for m in fetch.diff(toc["Modules"], now)[0]]


@pytest.mark.parametrize("bad", [True, "7", None, 1.5])
def test_topics_without_an_integer_id_are_skipped(bad):
    toc = json.loads(FIXTURE.read_text())
    toc["Modules"][0]["Topics"][0]["TopicId"] = bad
    assert "Lecture One Slides" not in [t for m in fetch.diff(toc["Modules"], {})[0] for t in m.new]


def test_a_hidden_module_hides_its_topics():
    toc = json.loads(FIXTURE.read_text())
    toc["Modules"][1]["IsHidden"] = True
    assert [m.path for m in fetch.diff(toc["Modules"], {})[0]] == ["Week 1"]


def test_malformed_nodes_do_not_crash():
    assert fetch.diff([None, 3, {"Topics": [None, "x"], "Modules": [None]}], {}) == ([], {})


def test_a_tree_nested_past_the_cap_is_a_site_error():
    node: dict = {"Title": "x", "Topics": [], "Modules": []}
    top = node
    for _ in range(fetch.MAX_DEPTH + 5):
        child: dict = {"Title": "x", "Topics": [], "Modules": []}
        node["Modules"].append(child)
        node = child
    with pytest.raises(d2l.SiteError):
        list(fetch.file_topics([top]))


def make_repos(root, *names, agents=()):
    for d in names:
        (root / d / ".git").mkdir(parents=True)
        if d in agents:
            (root / d / "AGENTS.md").write_text("x")


@pytest.mark.parametrize(
    ("name", "code", "want"),
    [
        ("ABCD.111.01 - Topics", "ABCD11101.2261", "abcd111-ml"),
        ("Topics in AI", "ABCD11101.2261", "abcd111-ml"),
        ("ABCD.222/333.01 - Cross", "ABCD33301.2261", "none (ambiguous: abcd222-a, abcd333-b)"),
        ("Sample", "WXYZ44401.2261", "none (no repo)"),
        ("ABCD.444.01", "", "none (no repo)"),
        ("", "", "none (no course number)"),
        ("../x", "../x", "none (no course number)"),
    ],
)
def test_course_names_its_class_repo(tmp_path, name, code, want):
    make_repos(tmp_path, "abcd111-ml", "abcd222-a", "abcd333-b", "other", agents=("abcd111-ml",))
    (tmp_path / "abcd111-file").write_text("not a repo")
    (tmp_path / "abcd444-nogit").mkdir()
    repo, why = fetch.course_repo(tmp_path, name, code)
    assert (repo.name if repo else f"none ({why})") == want


def test_two_repos_without_one_agents_file_are_ambiguous_as_in_mycourses_sync(tmp_path):
    make_repos(tmp_path, "abcd111-a", "abcd111-b", agents=("abcd111-a", "abcd111-b"))
    repo, why = fetch.course_repo(tmp_path, "ABCD.111.01", "")
    assert repo is None and why == "ambiguous: abcd111-a, abcd111-b"
    make_repos(tmp_path, "abcd222-a", "abcd222-b")
    assert fetch.course_repo(tmp_path, "ABCD.222.01", "")[1] == "ambiguous: abcd222-a, abcd222-b"


def test_a_cross_listed_course_with_one_agents_repo_resolves(tmp_path):
    make_repos(tmp_path, "abcd222-a", "abcd333-b", agents=("abcd333-b",))
    assert fetch.course_repo(tmp_path, "ABCD.222/333.01", "")[0] == tmp_path / "abcd333-b"


def test_title_match_is_advisory_and_ignores_short_titles(tmp_path):
    (tmp_path / "02-lectures").mkdir()
    (tmp_path / "02-lectures" / "Lecture_One_Slides_v2.pdf").write_text("x")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "Homework_Two.pdf").write_text("x")
    index = fetch.repo_index([tmp_path])
    assert fetch.in_repo("Lecture One Slides", index)
    assert not fetch.in_repo("Homework Two", index)  # VCS folders are not read
    assert not fetch.in_repo("A1", index)
    assert not fetch.in_repo("Lecture One Slides\nHomework", index)


def course_site(toc_status=200, toc=None):
    pages = {
        "/d2l/api/lp/1.30/enrollments/myenrollments/?orgUnitTypeId=3&pageSize=200": json.dumps(
            {
                "Items": [
                    {"OrgUnit": {"Id": 7, "Code": "ABCD11101.2261", "Name": "Sample Course"}}
                ],
                "PagingInfo": {"HasMoreItems": False},
            }
        ),
        "/d2l/api/le/1.30/7/content/toc": (toc_status, json.dumps(toc or TOC)),
    }
    seen: list[str] = []

    def get(path):
        seen.append(path)
        page = pages.get(path)
        return page if isinstance(page, tuple) else (200, page) if page else (404, "")

    return get, seen


def test_list_only_reads_the_enrollments_and_the_toc(tmp_path):
    get, seen = course_site()
    make_repos(tmp_path, "abcd111-ml", agents=("abcd111-ml",))
    lines, state = fetch.list_lines(get, "", {"7": SEEN}, tmp_path)
    assert seen == [
        "/d2l/api/lp/1.30/enrollments/myenrollments/?orgUnitTypeId=3&pageSize=200",
        "/d2l/api/le/1.30/7/content/toc",
    ]
    assert lines[0] == "COURSE Sample Course :: repo abcd111-ml :: 1 modules with changes"
    assert lines[1] == (
        "MODULE Sample Course :: Week 2 :: 0 new, 1 changed :: new in repo by title 0/0"
    )
    assert set(state["7"]) == {"11", "21", "22", "31"}


def test_a_failing_toc_is_named_and_keeps_its_old_state():
    get, _ = course_site(toc_status=500)
    lines, state = fetch.list_lines(get, "", {"7": SEEN}, None)
    assert lines == ["APIFAIL Sample Course :: toc:500"]
    assert state == {"7": SEEN}


def test_a_toc_that_is_not_a_tree_fails_the_course():
    get, _ = course_site(toc={"Modules": "no"})
    assert fetch.list_lines(get, "", {}, None)[0] == ["APIFAIL Sample Course :: toc:200"]


def test_listing_does_not_change_the_state_it_was_given():
    get, _ = course_site()
    seen = {"7": dict(SEEN)}
    fetch.list_lines(get, "", seen, None)
    assert seen == {"7": SEEN}


def test_an_ended_session_surfaces_as_no_session():
    def get(path):
        return 302, ""

    with pytest.raises(d2l.NoSession):
        fetch.list_lines(get, "", {}, None)


def test_state_round_trips_privately(tmp_path):
    path = tmp_path / "state" / "fetch-state.json"
    fetch.save_state(path, {"7": SEEN})
    assert fetch.load_state(path) == {"7": SEEN}
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700  # a folder schole made


def test_a_missing_state_is_empty(tmp_path):
    assert fetch.load_state(tmp_path / "none.json") == {}


@pytest.mark.parametrize(
    "text",
    [
        "",
        "[]",
        "{}",
        '{"version": 2, "courses": {}}',
        '{"version": 1, "courses": []}',
        '{"version": 1, "courses": {"7": {"1": 5}}}',
        '{"version": 1, "courses": {"7": 3}}',
        "\xff",
    ],
)
def test_a_bad_state_file_is_refused_not_overwritten(tmp_path, text):
    path = tmp_path / "s.json"
    path.write_bytes(text.encode("latin-1"))
    with pytest.raises(fetch.StateError):
        fetch.load_state(path)
    assert path.read_bytes() == text.encode("latin-1")


def test_state_home_honours_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("SCHOLE_STATE_HOME", str(tmp_path))
    assert fetch.state_path() == tmp_path / "fetch-state.json"
    monkeypatch.setenv("SCHOLE_STATE_HOME", "relative")
    with pytest.raises(config.ConfigError):
        fetch.state_path()
    monkeypatch.delenv("SCHOLE_STATE_HOME")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert fetch.state_path() == tmp_path / "schole" / "fetch-state.json"


def test_fixture_holds_no_real_course_data():
    text = FIXTURE.read_text()
    assert "rit.edu" not in text and "mycourses" not in text.lower()
    assert os.path.getsize(FIXTURE) < 20_000


def test_recording_keeps_topics_that_are_hidden_for_a_while():
    get, _ = course_site()
    _, state = fetch.list_lines(get, "", {"7": {"999": "2026-01-01T00:00:00.000Z"}}, None)
    assert "999" in state["7"] and "11" in state["7"]


def test_a_course_nested_too_deep_fails_alone():
    node: dict = {"Title": "x", "Topics": [], "Modules": []}
    top = node
    for _ in range(fetch.MAX_DEPTH + 5):
        child: dict = {"Title": "x", "Topics": [], "Modules": []}
        node["Modules"].append(child)
        node = child
    get, _ = course_site(toc={"Modules": [top]})
    lines, _ = fetch.list_lines(get, "", {}, None)
    assert lines[0].startswith("APIFAIL Sample Course ::")


class FakeBrowser:
    def __init__(self, lines=None, error=None):
        self.lines, self.error = lines or ["COURSE x :: repo none :: 0 modules with changes"], error

    def __call__(self, base, site, headless):
        import contextlib

        @contextlib.contextmanager
        def ctx():
            yield object()

        return ctx()


@pytest.fixture
def entry(monkeypatch, tmp_path):
    from schole import cli

    monkeypatch.setenv("SCHOLE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SCHOLE_STATE_HOME", str(tmp_path / "state"))
    config.save(tmp_path / "home", config.Config("https://lms.example.edu", "", None))
    monkeypatch.setattr(cli, "browser", FakeBrowser())
    monkeypatch.setattr(cli, "getter", lambda ctx, site: None)
    return cli


def run_fetch(entry, monkeypatch, behaviour, *argv):
    monkeypatch.setattr(
        fetch,
        "list_lines",
        behaviour
        if callable(behaviour)
        else lambda *a: (["COURSE c :: repo none :: 0"], {"7": {}}),
    )
    return entry.main(["fetch", *argv])


def test_entry_lists_and_records(entry, monkeypatch, tmp_path, capsys):
    assert run_fetch(entry, monkeypatch, None, "--list", "--record") == 0
    assert (tmp_path / "state" / "fetch-state.json").is_file()
    assert "recorded" in capsys.readouterr().out


def test_entry_without_record_writes_nothing(entry, monkeypatch, tmp_path):
    assert run_fetch(entry, monkeypatch, None, "--list") == 0
    assert not (tmp_path / "state").exists()


def test_entry_requires_list(entry, monkeypatch):
    with pytest.raises(SystemExit) as e:
        run_fetch(entry, monkeypatch, None)
    assert e.value.code == 2


def raises(exc):
    def f(*a):
        raise exc

    return f


def test_entry_exit_codes(entry, monkeypatch, capsys):
    assert run_fetch(entry, monkeypatch, raises(d2l.NoSession("x")), "--list") == 3
    assert "needs login" in capsys.readouterr().err
    assert run_fetch(entry, monkeypatch, raises(d2l.SiteError("x")), "--list") == 4


def test_entry_refuses_a_missing_classes_folder(entry, monkeypatch, tmp_path, capsys):
    assert run_fetch(entry, monkeypatch, None, "--list", "--classes", str(tmp_path / "nope")) == 1
    assert "not a folder" in capsys.readouterr().err


def test_entry_refuses_a_bad_state_file_without_touching_it(entry, monkeypatch, tmp_path):
    bad = tmp_path / "s.json"
    bad.write_text("{}")
    assert run_fetch(entry, monkeypatch, None, "--list", "--state", str(bad), "--record") == 1
    assert bad.read_text() == "{}"


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write a read-only folder")
def test_a_failed_save_is_an_exit_code_not_a_traceback(entry, monkeypatch, tmp_path, capsys):
    ro = tmp_path / "ro"
    ro.mkdir(mode=0o500)
    try:
        code = run_fetch(
            entry, monkeypatch, None, "--list", "--state", str(ro / "s.json"), "--record"
        )
    finally:
        ro.chmod(0o700)
    assert code == 1 and "could not save" in capsys.readouterr().err


def test_relative_arguments_resolve_against_the_callers_folder(entry, monkeypatch, tmp_path):
    caller = tmp_path / "caller"
    (caller / "classes").mkdir(parents=True)
    monkeypatch.setenv("SCHOLE_CWD", str(caller))
    assert entry.user_path("classes") == caller / "classes"
    assert entry.user_path("/abs") == Path("/abs")
    assert run_fetch(entry, monkeypatch, None, "--list", "--classes", "classes") == 0


def test_saving_leaves_a_named_folders_mode_alone(tmp_path):
    folder = tmp_path / "notes"
    folder.mkdir(mode=0o755)
    folder.chmod(0o755)
    fetch.save_state(folder / "s.json", {})
    assert stat.S_IMODE(folder.stat().st_mode) == 0o755


def test_a_later_real_date_after_a_missing_one_is_a_change():
    mods, now = fetch.diff(modules(), {"22": ""})
    assert "Homework Two" in [t for m in mods for t in m.changed]
    assert now["22"] == TOC["Modules"][1]["Topics"][1]["LastModifiedDate"]


def test_an_unreadable_new_date_keeps_the_recorded_one():
    toc = json.loads(FIXTURE.read_text())
    toc["Modules"][1]["Topics"][1]["LastModifiedDate"] = None
    _, now = fetch.diff(toc["Modules"], {"22": SEEN["22"]})
    assert now["22"] == SEEN["22"]


@pytest.mark.parametrize("flag", ["--classes", "--state"])
@pytest.mark.parametrize("value", ["", "  ", "~no-such-user-xyz/a"])
def test_empty_or_unexpandable_paths_are_refused(entry, monkeypatch, tmp_path, capsys, flag, value):
    assert run_fetch(entry, monkeypatch, None, "--list", flag, value) == 1
    assert capsys.readouterr().err.startswith("schole:")


def test_output_lines_are_single_clean_lines():
    toc = {
        "Modules": [
            {
                "Title": "Top\nMODULE fake :: x\x1b[2J",
                "Topics": [],
                "Modules": [
                    {
                        "Title": "Sub\r\nAPIFAIL x",
                        "Topics": [{"TopicId": 1, "TypeIdentifier": "File", "Title": "T"}],
                    }
                ],
            }
        ]
    }
    get, _ = course_site(toc=toc)
    enroll = "/d2l/api/lp/1.30/enrollments/myenrollments/?orgUnitTypeId=3&pageSize=200"
    hostile = json.dumps(
        {
            "Items": [
                {
                    "OrgUnit": {
                        "Id": 7,
                        "Code": "X",
                        "Name": "Sample\nMODULE fake :: x :: 99 new\x1b[2J",
                    }
                }
            ],
            "PagingInfo": {"HasMoreItems": False},
        }
    )

    def site(path):
        if path == enroll:
            return 200, hostile
        return get(path)

    lines, _ = fetch.list_lines(site, "", {}, None)
    assert len(lines) == 2
    assert all(re.fullmatch(r"[^\x00-\x1f\x7f-\x9f]*", line) for line in lines)
    assert lines[0].startswith("COURSE Sample MODULE fake")


def test_short_titles_never_match(tmp_path):
    (tmp_path / "abc.pdf").write_text("x")
    assert not fetch.in_repo("abc", fetch.repo_index([tmp_path]))
    assert fetch.in_repo("abcd", "xabcdx")


def test_a_longer_course_number_does_not_match_a_shorter_one(tmp_path):
    make_repos(tmp_path, "abcd111-a", agents=("abcd111-a",))
    assert fetch.course_repo(tmp_path, "ABCD.1112.01", "")[1] == "no course number"


def test_the_reason_appears_on_the_course_line(tmp_path):
    get, _ = course_site()
    make_repos(tmp_path, "abcd111-a", "abcd111-b")
    lines, _ = fetch.list_lines(get, "", {}, tmp_path)
    assert "repo none (no AGENTS.md" not in lines[0]
    assert "repo none (ambiguous: abcd111-a, abcd111-b)" in lines[0]


def test_one_repo_without_agents_says_so(tmp_path):
    make_repos(tmp_path, "abcd111-a")
    assert fetch.course_repo(tmp_path, "ABCD.111.01", "")[1] == "no AGENTS.md in: abcd111-a"


def test_a_relative_xdg_state_home_is_ignored(monkeypatch, tmp_path):
    monkeypatch.delenv("SCHOLE_STATE_HOME", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", "relative")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert fetch.state_path() == tmp_path / ".local" / "state" / "schole" / "fetch-state.json"


def test_a_deeply_nested_state_file_is_refused_not_a_traceback(tmp_path):
    path = tmp_path / "s.json"
    path.write_text("[" * 100_000)
    with pytest.raises(fetch.StateError):
        fetch.load_state(path)


def test_state_home_with_an_unknown_user_is_a_config_error(monkeypatch):
    monkeypatch.setenv("SCHOLE_STATE_HOME", "~no-such-user-xyz/s")
    with pytest.raises(config.ConfigError):
        fetch.state_path()
