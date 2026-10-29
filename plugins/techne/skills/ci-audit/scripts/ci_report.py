#!/usr/bin/env python3
"""The deterministic half of ci-audit's report mode.

    ci_report.py fetch REPO RUN DIR   record a run with read-only gh api calls
    ci_report.py facts DIR            print the run's facts as JSON
    ci_report.py schema               print the JSON Schema a report follows
    ci_report.py check REPORT [FACTS] exit non-zero when REPORT breaks the schema
                                      or contradicts FACTS
    ci_report.py render REPORT        print REPORT as Markdown

A recorded run is DIR/run.json, DIR/jobs.json (each job's steps with their times
and conclusions), DIR/annotations.json and DIR/logs/<job id>.log. Logs come from
the REST job-log endpoint, which serves any job; `gh run view --log` returns
nothing for some runs on older gh. Log lines are assigned to steps by the
files of the run's log archive, one per step, where it has them (DIR/steps/<job
id>/<step number>.txt); otherwise by the markers the runner prints as each step
starts and by the steps' times.
"""

import json
import re
import subprocess
import sys
import zipfile
import zlib
from datetime import datetime
from pathlib import Path

ERROR = re.compile(
    r"##\[error\]|\b[Ee]rror(\[[A-Z]\d+\])?:|\bFAILED\b|panicked at|Traceback \(most recent"
    r"|AssertionError|\bERROR\b"
)
WARNING = re.compile(
    r"##\[warning\]|\w*DeprecationWarning|\b[Ww]arning(\[\w+\])?:|\bis deprecated\b|\bDEPRECATED\b"
)
# A test runner's line for a test that passed, whatever the test is called.
PASSED = re.compile(r"\b(PASSED|ok|SKIPPED)\s*(\[\s*\d+%\])?$")
LOCATION = re.compile(
    r"([\w./\\-]+\.(?:py|rs|js|ts|tsx|sh|ya?ml|toml|json|go|java|c|cpp|h|md))[:(](\d+)"
)
STAMP = re.compile(r"^\ufeff?(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.\d+)?Z ?")
VOLATILE = re.compile(r"\d{4}-\d\d-\d\dT[\d:.]+Z|/home/runner/work/[^/]+/[^/]+/|\b\d+(\.\d+)?s\b")
TAIL = 30
MAX_LINE = 400


class GhError(Exception):
    pass


def gh(path: str) -> str:
    """One read-only GitHub API call; GhError carries gh's own words."""
    got = subprocess.run(["gh", "api", path], capture_output=True, text=True, errors="replace")
    if got.returncode:
        raise GhError(f"gh api {path}: {got.stderr.strip()[:300] or f'exit {got.returncode}'}")
    return got.stdout


def gh_bytes(path: str) -> bytes:
    got = subprocess.run(["gh", "api", path], capture_output=True)
    if got.returncode:
        raise GhError(f"gh api {path}: {got.stderr.decode(errors='replace').strip()[:300]}")
    return got.stdout


def split_archive(data: bytes, jobs: list[dict]) -> dict[int, dict[int, str]]:
    """The run's log archive as {job id: {step number: text}}. The archive holds
    "<job name>/<n>_<step name>.txt" per step; a job whose name is shared or
    absent is left out, and falls back to its whole log."""
    import io

    by_name: dict[str, list[dict]] = {}
    for j in jobs:
        by_name.setdefault(j["name"], []).append(j)
    out: dict[int, dict[int, str]] = {}
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist():
            folder, _, leaf = info.filename.rpartition("/")
            m = re.match(r"(\d+)_", leaf)
            owners = by_name.get(folder, [])
            if not m or len(owners) != 1 or info.file_size > 50 << 20:
                continue
            text = z.read(info).decode("utf-8", errors="replace")
            out.setdefault(owners[0]["id"], {})[int(m.group(1))] = text
    return out


def fetch(repo: str, run: str, out: Path) -> None:
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo) or not run.isdigit():
        raise SystemExit(f"error: a repo is OWNER/NAME and a run id is a number: {repo} {run}")
    (out / "logs").mkdir(parents=True, exist_ok=True)
    try:
        r = json.loads(gh(f"repos/{repo}/actions/runs/{run}"))
    except GhError as e:
        raise SystemExit(f"error: {e}") from None
    errors = []
    keys = (
        "id",
        "name",
        "head_branch",
        "head_sha",
        "status",
        "conclusion",
        "html_url",
        "event",
        "run_attempt",
    )
    (out / "run.json").write_text(
        json.dumps({"repository": repo} | {k: r.get(k) for k in keys}, indent=1) + "\n"
    )
    jobs = json.loads(gh(f"repos/{repo}/actions/runs/{run}/jobs?per_page=100&filter=latest"))[
        "jobs"
    ]
    step_keys = ("number", "name", "conclusion", "started_at", "completed_at")
    kept, notes = [], {}
    for j in jobs:
        kept.append(
            {k: j.get(k) for k in ("id", "name", "conclusion", "started_at", "completed_at")}
            | {"steps": [{k: s.get(k) for k in step_keys} for s in j.get("steps") or []]}
        )
        try:
            (out / "logs" / f"{j['id']}.log").write_text(
                gh(f"repos/{repo}/actions/jobs/{j['id']}/logs")
            )
        except GhError as e:
            (out / "logs" / f"{j['id']}.log").write_text("")
            errors.append({"job": j.get("name"), "what": "log", "error": str(e)})
        try:
            got = json.loads(gh(f"repos/{repo}/check-runs/{j['id']}/annotations?per_page=100"))
        except GhError as e:
            got = []
            errors.append({"job": j.get("name"), "what": "annotations", "error": str(e)})
        notes[str(j["id"])] = [
            {k: a.get(k) for k in ("path", "start_line", "annotation_level", "title", "message")}
            for a in got
        ]
    try:
        steps = split_archive(gh_bytes(f"repos/{repo}/actions/runs/{run}/logs"), kept)
    except (
        GhError,
        OSError,
        ValueError,
        RuntimeError,
        NotImplementedError,
        zipfile.BadZipFile,
        zlib.error,
    ) as e:
        steps = {}
        errors.append({"job": None, "what": "log archive", "error": str(e)[:300]})
    for job_id, texts in steps.items():
        folder = out / "steps" / str(job_id)
        folder.mkdir(parents=True, exist_ok=True)
        for n, text in texts.items():
            (folder / f"{n}.txt").write_text(text)
    (out / "jobs.json").write_text(json.dumps(kept, indent=1) + "\n")
    (out / "annotations.json").write_text(json.dumps(notes, indent=1) + "\n")
    (out / "errors.json").write_text(json.dumps(errors, indent=1) + "\n")


QUIET = ("Set up job", "Initialize containers", "Stop containers", "Complete job")


def second(stamp: str | None) -> int | None:
    """An ISO time as whole seconds since the epoch (the API's step times are whole seconds)."""
    if not stamp:
        return None
    return int(datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp())


def by_step(job: dict, log: str) -> dict[int, list[str]]:
    """The job's log lines per step number, timestamps removed.

    A step that runs a command or an action opens with "##[group]Run ...". Such a
    header opens the next of those steps once the current step's time is up; one
    that falls inside a running step is that step's own group (a script's
    `::group::Run tests`). The steps that print no header (setting up and
    stopping containers, post steps) take the lines that fall in their time
    span; "Post job cleanup.", "Stop and remove container" and "Cleaning up
    orphan processes" open the next post step, the container stop and the last
    step. Skipped steps print nothing."""
    steps = job.get("steps") or []
    out: dict[int, list[str]] = {s["number"]: [] for s in steps}
    ran = [s for s in steps if s.get("conclusion") != "skipped"]
    if not ran:
        out[0] = [(STAMP.sub("", x))[:MAX_LINE] for x in log.splitlines()]
        return out
    span = {s["number"]: (second(s.get("started_at")), second(s.get("completed_at"))) for s in ran}

    names = {s["name"] for s in steps}

    def post(s: dict) -> bool:
        """The runner's post step for a step of this job ("Post Run actions/checkout")."""
        return s["name"].startswith("Post ") and s["name"][5:] in names

    def quiet(s: dict) -> bool:
        return s["name"] in QUIET or post(s)

    def inside(s: dict, t: int) -> bool:
        lo, hi = span[s["number"]]
        return lo is not None and hi is not None and lo <= t <= hi

    current = ran[0]
    for raw in log.splitlines():
        m = STAMP.match(raw)
        text = raw[m.end() :] if m else raw
        t = second(m.group(1) + "Z") if m else None
        later = [s for s in ran if s["number"] > current["number"]]
        ends = span[current["number"]][1]
        if text.startswith("##[group]Run "):
            nxt = [s for s in later if not quiet(s)]
            if nxt and (t is None or ends is None or t >= ends):
                current = nxt[0]
        elif text.startswith("Post job cleanup."):
            nxt = [s for s in later if post(s)]
            current = nxt[0] if nxt else current
        elif text.startswith(("Print service container logs", "Stop and remove container")):
            nxt = [s for s in later if s["name"] == "Stop containers"]
            current = nxt[0] if nxt else current
        elif text.startswith("Cleaning up orphan processes"):
            nxt = [s for s in later if s["name"] == "Complete job"]
            current = nxt[0] if nxt else current
        elif t is not None and not inside(current, t):
            nxt = [s for s in later if quiet(s) and inside(s, t)]
            current = nxt[0] if nxt else current
        out[current["number"]].append(text[:MAX_LINE])
    return out


def norm(line: str) -> str:
    return VOLATILE.sub("", line).strip()


def facts(d: Path) -> dict:
    run = json.loads((d / "run.json").read_text())
    jobs = json.loads((d / "jobs.json").read_text())
    notes = (
        json.loads((d / "annotations.json").read_text())
        if (d / "annotations.json").exists()
        else {}
    )
    errors_path = d / "errors.json"
    fetch_errors = json.loads(errors_path.read_text()) if errors_path.exists() else []
    failing, mismatches, warnings, out_jobs = [], [], {}, []
    for job in jobs:
        log_path = d / "logs" / f"{job['id']}.log"
        if log_path.is_symlink():
            raise SystemExit(f"error: {log_path} is a symlink; a recorded log is a plain file")
        step_dir = d / "steps" / str(job["id"])
        if step_dir.is_dir() and not step_dir.is_symlink():
            lines = {
                int(f.stem): [
                    STAMP.sub("", x)[:MAX_LINE] for x in f.read_text(errors="replace").splitlines()
                ]
                for f in step_dir.glob("*.txt")
                if f.stem.isascii() and f.stem.isdigit() and f.is_file() and not f.is_symlink()
            }
        else:
            lines = by_step(job, log_path.read_text(errors="replace") if log_path.exists() else "")
        out_jobs.append(
            {
                "name": job["name"],
                "conclusion": job["conclusion"],
                "log_lines": sum(map(len, lines.values())),
            }
        )
        for step in job.get("steps") or []:
            text = lines.get(step["number"], [])
            errors = [x for x in text if ERROR.search(x)]
            where = {"job": job["name"], "step": step["name"], "conclusion": step["conclusion"]}
            stopped = (
                step["conclusion"] in ("cancelled", "timed_out") and job["conclusion"] == "failure"
            )
            if step["conclusion"] == "failure" or stopped:
                failing.append(
                    where
                    | {
                        "error_lines": errors[-15:],
                        "locations": sorted(
                            {f"{p}:{n}" for x in errors for p, n in LOCATION.findall(x)}
                        ),
                        "tail": text[-TAIL:],
                    }
                )
            elif step["conclusion"] == "success" and any("##[error]" in x for x in text):
                mismatches.append(
                    where | {"error_lines": [x for x in text if "##[error]" in x][:10]}
                )
            for x in text:
                if WARNING.search(x) and not PASSED.search(x):
                    key = norm(x)
                    w = warnings.setdefault(key, where | {"line": x.strip(), "count": 0})
                    w["count"] += 1
        if job["conclusion"] == "failure" and not any(f["job"] == job["name"] for f in failing):
            # Failed before or between steps (a startup failure has none).
            whole = [x for v in lines.values() for x in v]
            failing.append(
                {
                    "job": job["name"],
                    "step": "(job)",
                    "conclusion": "failure",
                    "error_lines": [x for x in whole if ERROR.search(x)][-15:],
                    "locations": [],
                    "tail": whole[-TAIL:],
                }
            )
        for a in notes.get(str(job["id"]), []):
            if a.get("annotation_level") in ("warning", "notice"):
                key = norm(a.get("message") or "")
                w = warnings.setdefault(
                    key,
                    {
                        "job": job["name"],
                        "step": "(annotation)",
                        "conclusion": job["conclusion"],
                        "line": f"{a['annotation_level']}: {(a.get('message') or '')[:MAX_LINE]}",
                        "count": 0,
                    },
                )
                w["count"] += 1
    error_notes = {
        j["name"]: [
            a for a in notes.get(str(j["id"]), []) if a.get("annotation_level") == "failure"
        ]
        for j in jobs
    }
    return {
        "run": {
            "repository": run.get("repository"),
            "id": run.get("id"),
            "workflow": run.get("name"),
            "branch": run.get("head_branch"),
            "head_sha": run.get("head_sha"),
            "conclusion": run.get("conclusion"),
            "url": run.get("html_url"),
        },
        "jobs": out_jobs,
        "failing_steps": failing,
        "success_with_error": mismatches,
        "warnings": sorted(warnings.values(), key=lambda w: -w["count"])[:40],
        "error_annotations": {k: v for k, v in error_notes.items() if v},
        "fetch_errors": fetch_errors,
        "logging": {
            "failing_steps_with_a_file_annotation": sum(
                1
                for f in failing
                if any(
                    a.get("path") not in (None, "", ".github") and a.get("start_line")
                    for a in error_notes.get(f["job"], [])
                )
            ),
            "failing_steps_whose_errors_name_a_file": sum(1 for f in failing if f["locations"]),
            "failing_steps": len(failing),
        },
    }


def maybe(kind: str | list[str]) -> dict:
    """A value of KIND (one type name or several) or null, as anyOf: strict
    validators refuse a list of types."""
    kinds = kind if isinstance(kind, list) else [kind]
    return {"anyOf": [{"type": k} for k in kinds] + [{"type": "null"}]}


BUCKETS = ["FIX", "BUMP", "PROPOSE", "DEFER", "EXPECTED"]
KINDS = ["failure", "error-in-green-step", "warning", "deprecation", "logging", "external-check"]
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["run", "verdict", "failing_step", "findings", "logging", "summary"],
    "properties": {
        "run": {
            "type": "object",
            "required": ["repository", "id", "conclusion"],
            "properties": {
                k: maybe(["string", "integer"])
                for k in ("repository", "id", "workflow", "branch", "head_sha", "conclusion", "url")
            },
        },
        "verdict": {
            "enum": ["failure", "green-with-findings", "clean", "in-progress", "cancelled"]
        },
        "failing_step": {
            "anyOf": [
                {"type": "null"},
                {
                    "type": "object",
                    "required": ["job", "step", "root_cause", "location", "evidence"],
                    "properties": {
                        "job": {"type": "string"},
                        "step": {"type": "string"},
                        "root_cause": {"type": "string"},
                        "location": maybe("string"),
                        "evidence": {"type": "string"},
                    },
                },
            ]
        },
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["bucket", "kind", "summary", "location", "evidence"],
                "properties": {
                    "bucket": {"enum": BUCKETS},
                    "kind": {"enum": KINDS},
                    "summary": {"type": "string"},
                    "location": maybe("string"),
                    "evidence": {"type": "string"},
                    "why": {"type": "string"},
                },
            },
        },
        "logging": {
            "type": "object",
            "required": ["names_the_cause", "notes"],
            "properties": {"names_the_cause": maybe("boolean"), "notes": {"type": "string"}},
        },
        "summary": {"type": "string"},
    },
}


def check(report: dict) -> list[str]:
    """What in REPORT breaks the schema (a small validator for this schema's shapes)."""
    problems = []

    def fits(value, kind):
        return {
            "object": isinstance(value, dict),
            "array": isinstance(value, list),
            "string": isinstance(value, str),
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "boolean": isinstance(value, bool),
            "null": value is None,
        }[kind]

    def walk(value, schema, at):
        if "anyOf" in schema:
            options = [o for o in schema["anyOf"] if fits(value, o["type"])]
            if not options:
                problems.append(f"{at}: matches none of {[o['type'] for o in schema['anyOf']]}")
                return
            schema = {k: v for k, v in schema.items() if k != "anyOf"} | options[0]
        kinds = schema.get("type")
        if "enum" in schema and value not in schema["enum"]:
            problems.append(f"{at}: {value!r} is not one of {schema['enum']}")
            return
        if kinds:
            names = kinds if isinstance(kinds, list) else [kinds]
            ok = {
                "object": isinstance(value, dict),
                "array": isinstance(value, list),
                "string": isinstance(value, str),
                "integer": isinstance(value, int) and not isinstance(value, bool),
                "boolean": isinstance(value, bool),
                "null": value is None,
            }
            if not any(ok[n] for n in names):
                problems.append(f"{at}: expected {kinds}, got {type(value).__name__}")
                return
        if isinstance(value, dict):
            for k in schema.get("required", []):
                if k not in value:
                    problems.append(f"{at}: missing {k}")
            props = schema.get("properties", {})
            if schema.get("additionalProperties") is False:
                problems.extend(f"{at}: unexpected {k}" for k in value if k not in props)
            for k, v in value.items():
                if k in props:
                    walk(v, props[k], f"{at}.{k}")
        if isinstance(value, list) and "items" in schema:
            for i, v in enumerate(value):
                walk(v, schema["items"], f"{at}[{i}]")

    walk(report, SCHEMA, "report")
    return problems


def expected(f: dict) -> set[str]:
    """The verdicts FACTS allow, by one precedence: a run still going is in
    progress, a cancelled run is cancelled, then a run that failed or has a
    failing step is a failure; a green run is clean only without a swallowed error."""
    conclusion = f["run"].get("conclusion")
    if conclusion is None:
        return {"in-progress"}
    if conclusion == "cancelled":
        return {"cancelled"}
    if conclusion in ("failure", "timed_out", "startup_failure") or f["failing_steps"]:
        return {"failure"}
    if f["success_with_error"]:
        return {"green-with-findings"}
    return {"clean", "green-with-findings"}


def agree(report: dict, f: dict) -> list[str]:
    """Where REPORT contradicts FACTS: a log line may have steered the judgement."""
    problems = []
    for k in ("repository", "id"):
        if report["run"].get(k) != f["run"].get(k):
            problems.append(
                f"run.{k} is {report['run'].get(k)!r}, the facts say {f['run'].get(k)!r}"
            )
    allowed = expected(f)
    if report["verdict"] not in allowed:
        problems.append(f"verdict {report['verdict']!r}; the facts allow {sorted(allowed)}")
    return problems


def render(r: dict) -> str:
    run = r["run"]
    sha = (run.get("head_sha") or "")[:7]
    workflow = run.get("workflow") or "workflow"
    out = [
        f"## CI report: {run.get('repository')} run {run.get('id')} ({workflow})",
        "",
        f"Branch {run.get('branch')} @ {sha}, conclusion **{run.get('conclusion')}**, "
        f"verdict **{r['verdict']}**. {run.get('url') or ''}".rstrip(),
        "",
    ]
    f = r.get("failing_step")
    if f:
        out += [
            "### Failing step",
            "",
            f"{f['job']} / {f['step']}: {f['root_cause']}"
            + (f" ({f['location']})" if f.get("location") else ""),
            "",
            f"> {f['evidence']}",
            "",
        ]
    out += ["### Findings", ""]
    for i, x in enumerate(r["findings"], 1):
        loc = f" {x['location']}" if x.get("location") else ""
        why = f" Why: {x['why']}" if x.get("why") else ""
        out.append(f"{i}. [{x['bucket']}] ({x['kind']}) {x['summary']}{loc}.{why}")
    if not r["findings"]:
        out.append("None.")
    lg = r["logging"]
    said = {True: "yes", False: "no", None: "n/a"}[lg.get("names_the_cause")]
    out += [
        "",
        "### Logging",
        "",
        f"Does the log name the cause? {said}. {lg['notes']}",
        "",
        "### Summary",
        "",
        r["summary"],
        "",
    ]
    return "\n".join(out)


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[1] == "schema":
        print(json.dumps(SCHEMA))
    elif len(argv) == 5 and argv[1] == "fetch":
        fetch(argv[2], argv[3], Path(argv[4]))
    elif len(argv) == 3 and argv[1] == "facts":
        print(json.dumps(facts(Path(argv[2])), indent=1))
    elif len(argv) in (3, 4) and argv[1] == "check":
        report = json.loads(Path(argv[2]).read_text())
        problems = check(report)
        if not problems and len(argv) == 4:
            problems = agree(report, json.loads(Path(argv[3]).read_text()))
        for p in problems:
            print(f"error: {p}", file=sys.stderr)
        return 1 if problems else 0
    elif len(argv) == 3 and argv[1] == "render":
        print(render(json.loads(Path(argv[2]).read_text())), end="")
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
