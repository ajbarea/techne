import json
import os
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


def test_a_missing_date_is_new_once_and_never_changed():
    toc = json.loads(FIXTURE.read_text())
    toc["Modules"][0]["Topics"][0]["LastModifiedDate"] = None
    mods, now = fetch.diff(toc["Modules"], {})
    assert "11" not in now and mods[0].new == ["Lecture One Slides"]
    assert fetch.diff(toc["Modules"], {"11": SEEN["11"]})[0][0].path != "Week 1"


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


@pytest.mark.parametrize(
    ("name", "code", "want"),
    [
        ("CSCI.739.01 - Topics", "CSCI73901.2261", ["csci739-ml"]),
        ("Topics in AI", "CSCI73901.2261", ["csci739-ml"]),
        ("ISTE.476782.01 - Cross", "ISTE47601.2261", ["iste476-a", "iste782-b"]),
        ("ISTE.476/782.01 - Cross", "ISTE78201.2261", ["iste476-a", "iste782-b"]),
        ("Sample", "PSYC71901.2261", []),
        ("", "", []),
        ("../x", "../x", []),
    ],
)
def test_course_names_its_class_repos(tmp_path, name, code, want):
    for d in ("csci739-ml", "iste476-a", "iste782-b", "other"):
        (tmp_path / d).mkdir()
    (tmp_path / "csci739-file").write_text("not a dir")
    assert [p.name for p in fetch.course_dirs(tmp_path, name, code)] == want


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
                    {"OrgUnit": {"Id": 7, "Code": "CSCI73901.2261", "Name": "Sample Course"}}
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
    (tmp_path / "csci739-ml").mkdir()
    lines, state = fetch.list_lines(get, "", {"7": SEEN}, tmp_path)
    assert seen == [
        "/d2l/api/lp/1.30/enrollments/myenrollments/?orgUnitTypeId=3&pageSize=200",
        "/d2l/api/le/1.30/7/content/toc",
    ]
    assert lines[0] == "COURSE Sample Course :: repo csci739-ml :: 1 modules with changes"
    assert lines[1] == (
        "MODULE Sample Course :: Week 2 :: 0 new, 1 changed :: in repo by title 0/1"
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
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


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
