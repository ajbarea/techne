"""A fake GitHub for tests/test_body_gate.py, reached by gh as an HTTP proxy for
github.localhost: it answers the few queries `gh pr|issue comment|review` makes and
logs each request body, so a test sees the body gh really sends.

    python3 fake_github.py PORT LOG
"""

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOG = sys.argv[2]
PR = {
    "id": "PR_1",
    "number": 1,
    "url": "http://github.localhost/o/r/pull/1",
    "title": "t",
    "state": "OPEN",
    "body": "",
    "headRefName": "h",
    "baseRefName": "main",
    "isDraft": False,
    "author": {"login": "me"},
    "headRepositoryOwner": {"login": "o"},
    "headRepository": {"name": "r"},
    "isCrossRepository": False,
}
ISSUE = {
    "id": "I_1",
    "number": 1,
    "url": "http://github.localhost/o/r/issues/1",
    "title": "t",
    "state": "OPEN",
    "body": "",
    "author": {"login": "me"},
    "__typename": "Issue",
}


class H(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass

    def reply(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("X-Oauth-Scopes", "repo, read:org")
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        with open(LOG, "a") as f:
            f.write(json.dumps({"method": "GET", "path": self.path}) + "\n")
        self.reply({"login": "me"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n).decode("utf-8", "replace")
        with open(LOG, "a") as f:
            f.write(json.dumps({"method": "POST", "path": self.path, "body": raw}) + "\n")
        try:
            q = json.loads(raw)
        except ValueError:
            q = {}
        query = q.get("query", "") if isinstance(q, dict) else ""
        if "mutation" in query:
            self.reply(
                {
                    "data": {
                        "addComment": {"commentEdge": {"node": {"url": "http://x/c"}}},
                        "addPullRequestReview": {"clientMutationId": ""},
                    }
                }
            )
        elif "pullRequest(" in query or "PullRequestByNumber" in query:
            self.reply({"data": {"repository": {"pullRequest": PR, "hasIssuesEnabled": True}}})
        elif "issueOrPullRequest" in query or "issue(" in query:
            self.reply(
                {
                    "data": {
                        "repository": {
                            "hasIssuesEnabled": True,
                            "issue": ISSUE,
                            "issueOrPullRequest": ISSUE,
                        }
                    }
                }
            )
        else:
            self.reply({"data": {}})

    do_PATCH = do_POST


ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
