import json
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from schole import d2l

NY = ZoneInfo("America/New_York")
NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
SINCE = NOW - timedelta(days=1)


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def enrollments(*units, more=None):
    items = [{"OrgUnit": {"Id": ou, "Code": code, "Name": name}} for ou, code, name in units]
    paging = {"Bookmark": more, "HasMoreItems": bool(more)}
    return json.dumps({"Items": items, "PagingInfo": paging})


class Site:
    """A fake course site keyed by path; records every request."""

    def __init__(self, pages):
        self.pages = pages
        self.seen = []

    def __call__(self, path):
        self.seen.append(path)
        page = self.pages.get(path)
        if page is None:
            return 404, "not found"
        return page if isinstance(page, tuple) else (200, page)


def course_pages(ou, news=(), modules=(), folders=(), listing=None):
    pages = {
        f"/d2l/api/le/1.30/{ou}/news/": json.dumps(list(news)),
        f"/d2l/api/le/1.30/{ou}/content/toc": json.dumps({"Modules": list(modules)}),
        f"/d2l/api/le/1.30/{ou}/dropbox/folders/": json.dumps(list(folders)),
    }
    if listing is not None:
        pages[f"/d2l/lms/dropbox/user/folders_list.d2l?ou={ou}"] = listing
    return pages


@pytest.mark.parametrize(
    "path",
    [
        d2l.ENROLLMENTS,
        d2l.ENROLLMENTS + "&bookmark=abc_12",
        "/d2l/api/le/1.30/123/news/",
        "/d2l/api/le/1.30/123/content/toc",
        "/d2l/api/le/1.30/123/dropbox/folders/",
        "/d2l/lms/dropbox/user/folders_list.d2l?ou=123",
    ],
)
def test_allowlist_admits_the_sweep_paths(path):
    assert d2l.allowed(path)


@pytest.mark.parametrize(
    "path",
    [
        "/d2l/le/lessons/123/topics/456",
        "/d2l/le/content/123/viewContent/456/View",
        "/d2l/api/le/1.30/123/content/topics/456/file",
        "/d2l/api/le/1.30/123/dropbox/folders/9/submissions/",
        "/d2l/api/le/1.30/123/news/../content/toc",
        "https://evil.example/d2l/api/le/1.30/123/news/",
        "/d2l/lms/dropbox/user/folders_list.d2l?ou=123&x=1",
    ],
)
def test_allowlist_refuses_anything_else(path):
    assert not d2l.allowed(path)
    with pytest.raises(PermissionError):
        d2l.guarded(lambda p: (200, ""))(path)


def test_courses_filters_by_term_and_follows_bookmarks():
    site = Site(
        {
            d2l.ENROLLMENTS: enrollments(
                (1, "CSCI.739.01.2261", "QML"), (2, "OLD.2258", "Old"), more="b1"
            ),
            d2l.ENROLLMENTS + "&bookmark=b1": enrollments((3, "CISC.820.01.2261", "Opt")),
        }
    )
    found = d2l.courses(site, "2261")
    assert [c.ou for c in found] == [1, 3]


@pytest.mark.parametrize(
    "reply", [(200, "<html>Login - RIT myCourses</html>"), (302, ""), (401, "{}")]
)
def test_courses_raise_nosession_on_a_login_page(reply):
    with pytest.raises(d2l.NoSession):
        d2l.courses(Site({d2l.ENROLLMENTS: reply}), "")


def test_sweep_reports_what_changed_and_what_is_due():
    ou = 7
    news = [
        {
            "Title": "Room change",
            "StartDate": iso(NOW - timedelta(hours=2)),
            "Body": {"Html": "<p>Class moves to <b>GOL 1440</b>.</p>"},
        },
        {"Title": "Welcome", "StartDate": iso(NOW - timedelta(days=9)), "Body": {"Html": ""}},
    ]
    modules = [
        {
            "Topics": [
                {
                    "Title": "Lecture 5",
                    "LastModifiedDate": iso(NOW - timedelta(hours=3)),
                    "Unread": True,
                }
            ],
            "Modules": [
                {
                    "Topics": [
                        {
                            "Title": "Notes C7",
                            "LastModifiedDate": iso(NOW - timedelta(hours=1)),
                            "Unread": False,
                        },
                        {
                            "Title": "Old notes",
                            "LastModifiedDate": iso(NOW - timedelta(days=5)),
                            "Unread": True,
                        },
                    ]
                }
            ],
        },
    ]
    folders = [
        {"Name": "HW3", "DueDate": iso(NOW + timedelta(days=3))},
        {"Name": "HW9", "DueDate": iso(NOW + timedelta(days=30))},
        {"Name": "Report #3", "DueDate": iso(NOW - timedelta(hours=5))},
        {"Name": "Report #4", "DueDate": iso(NOW - timedelta(hours=4))},
        {"Name": "Report #1", "DueDate": iso(NOW - timedelta(days=10))},
        {"Name": "Optional", "DueDate": None},
    ]
    listing = (
        "<table><tr><td>Report #30Due on Dec 1</td><td>Not Submitted</td></tr>"
        "<tr><td>Report #3Due on Oct 16</td><td>1 Submission, 1 File</td></tr>"
        "<tr><td>Report #4Due on Oct 16</td><td>Not Submitted</td></tr></table>"
    )
    site = Site(
        {
            d2l.ENROLLMENTS: enrollments((ou, "CSCI.739.01.2261", "Quantum ML")),
            **course_pages(ou, news, modules, folders, listing),
        }
    )
    lines = d2l.sweep(site, "2261", SINCE, NOW, NY)
    assert lines[0] == "OK Quantum ML :: news 2 topics 3 dropbox 6"
    assert any(
        line.startswith("ANNOUNCE Quantum ML :: Room change")
        and line.endswith(":: Class moves to GOL 1440.")
        for line in lines
    )
    assert not any(
        "Welcome" in x or "Old notes" in x or "HW9" in x or "Report #1 " in x for x in lines
    )
    assert "CONTENT Quantum ML :: Lecture 5 :: Fri Oct 16 05:00 EDT :: UNREAD" in lines
    assert "CONTENT Quantum ML :: Notes C7 :: Fri Oct 16 07:00 EDT :: seen" in lines
    assert "DUE Quantum ML :: HW3 :: Mon Oct 19 08:00 EDT" in lines
    assert "PASTDUE Quantum ML :: Report #3 :: Fri Oct 16 03:00 EDT :: 1 submitted" in lines
    assert "PASTDUE Quantum ML :: Report #4 :: Fri Oct 16 04:00 EDT :: NOT SUBMITTED" in lines
    assert all(d2l.allowed(p) for p in site.seen)


def test_sweep_marks_a_dead_endpoint_and_unreadable_listing():
    ou = 8
    pages = course_pages(ou, folders=[{"Name": "Lab", "DueDate": iso(NOW - timedelta(hours=1))}])
    del pages[f"/d2l/api/le/1.30/{ou}/news/"]
    site = Site({d2l.ENROLLMENTS: enrollments((ou, "X.2261", "Lab course")), **pages})
    lines = d2l.sweep(site, "2261", SINCE, NOW, NY)
    assert lines[0] == "APIFAIL Lab course :: news:404"
    assert lines[1].endswith(":: LISTFAIL 404")


def test_submission_state_cases():
    rows = ["HW 1Due on Oct 1 Not Submitted", "HW 10Due on Oct 9 2 Submissions, 2 Files"]
    assert d2l.submission_state(rows, "HW 1", 200) == "NOT SUBMITTED"
    assert d2l.submission_state(rows, "HW 10", 200) == "2 submitted"
    assert d2l.submission_state(rows, "HW 2", 200) == "NOROW"
    assert d2l.submission_state(rows, "", 200) == "NOROW"
    assert d2l.submission_state(None, "HW 1", 500) == "LISTFAIL 500"


def test_clean_strips_controls_and_caps():
    assert d2l.clean("a\x1b[31m\nb  c") == "a [31m b c"
    assert len(d2l.clean("x" * 500)) == d2l.TEXT_CAP


def test_signed_out_reply_is_403_json_and_reads_as_nosession():
    with pytest.raises(d2l.NoSession):
        d2l.courses(Site({d2l.ENROLLMENTS: (403, '{"Errors":[]}')}), "")


@pytest.mark.parametrize("status", [500, 503, 429])
def test_server_failures_are_site_errors_not_logins(status):
    with pytest.raises(d2l.SiteError):
        d2l.courses(Site({d2l.ENROLLMENTS: (status, "{}")}), "")


def test_repeated_bookmark_and_endless_paging_are_site_errors(monkeypatch):
    loop = Site(
        {
            d2l.ENROLLMENTS: enrollments((1, "A.2261", "A"), more="b"),
            d2l.ENROLLMENTS + "&bookmark=b": enrollments((2, "B.2261", "B"), more="b"),
        }
    )
    with pytest.raises(d2l.SiteError, match="repeated"):
        d2l.courses(loop, "")
    monkeypatch.setattr(d2l, "MAX_PAGES", 2)
    pages = {d2l.ENROLLMENTS: enrollments(more="p1")}
    pages[d2l.ENROLLMENTS + "&bookmark=p1"] = enrollments(more="p2")
    with pytest.raises(d2l.SiteError, match="2 pages"):
        d2l.courses(Site(pages), "")


def test_bookmark_is_url_encoded_and_still_allowed():
    site = Site(
        {
            d2l.ENROLLMENTS: enrollments(more="a+b/c="),
            d2l.ENROLLMENTS + "&bookmark=a%2Bb%2Fc%3D": enrollments((5, "X.2261", "X")),
        }
    )
    assert [c.ou for c in d2l.courses(d2l.guarded(site), "")] == [5]


def test_due_boundaries_and_naive_times():
    ou = 9
    folders = [
        {"Name": "At now", "DueDate": iso(NOW)},
        {"Name": "At since", "DueDate": iso(SINCE)},
        {"Name": "Naive", "DueDate": (NOW + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")},
    ]
    site = Site(
        {
            d2l.ENROLLMENTS: enrollments((ou, "B.2261", "Bounds")),
            **course_pages(ou, folders=folders, listing="<table></table>"),
        }
    )
    lines = d2l.sweep(site, "2261", SINCE, NOW, NY)
    assert any(x.startswith("PASTDUE Bounds :: At now") for x in lines)
    assert not any("At since" in x for x in lines)
    assert any(x.startswith("DUE Bounds :: Naive") for x in lines)


def test_submission_state_prefers_the_exact_name():
    rows = ["Lab 1 RedoDue on Oct 2 Not Submitted", "Lab 1Due on Oct 1 1 Submission, 1 File"]
    assert d2l.submission_state(rows, "Lab 1", 200) == "1 submitted"
    assert d2l.submission_state(["Lab  2Due on Oct 3 1 Submission"], "Lab  2", 200) == "NOROW"
    assert d2l.submission_state(["Lab 2 Due on Oct 3 1 Submission"], "Lab  2", 200) == "1 submitted"
