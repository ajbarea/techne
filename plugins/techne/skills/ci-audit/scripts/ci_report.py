#!/usr/bin/env python3
"""The deterministic half of ci-audit's report mode.

    ci_report.py fetch REPO RUN DIR   record a run with read-only gh api calls
    ci_report.py facts DIR            print the run's facts as JSON
    ci_report.py schema               print the JSON Schema a report follows
    ci_report.py check REPORT         exit non-zero when REPORT breaks the schema
    ci_report.py render REPORT        print REPORT as Markdown

A recorded run is DIR/run.json, DIR/jobs.json (each job's steps with their times
and conclusions), DIR/annotations.json and DIR/logs/<job id>.log. Logs come from
the REST job-log endpoint, which serves any job; `gh run view --log` returns
nothing for some runs on older gh. Log lines are assigned to steps by the
markers the runner prints as each step starts.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

ERROR = re.compile(
    r"##\[error\]|\berror(\[[A-Z]\d+\])?:|\bFAILED\b|panicked at"
    r"|Traceback \(most recent|AssertionError|\bfailures?:",
    re.I,
)
WARNING = re.compile(r"##\[warning\]|DeprecationWarning|deprecat|\bwarning(\[\w+\])?:", re.I)
LOCATION = re.compile(
    r"([\w./\\-]+\.(?:py|rs|js|ts|tsx|sh|ya?ml|toml|json|go|java|c|cpp|h|md))[:(](\d+)"
)
STAMP = re.compile(r"^\ufeff?(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.\d+)?Z ?")
VOLATILE = re.compile(r"\d{4}-\d\d-\d\dT[\d:.]+Z|/home/runner/work/[^/]+/[^/]+/|\b\d+(\.\d+)?s\b")
TAIL = 30
MAX_LINE = 400


def gh(path: str) -> str:
    """One read-only GitHub API call."""
    return subprocess.run(["gh", "api", path], capture_output=True, text=True, check=True).stdout


def fetch(repo: str, run: str, out: Path) -> None:
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo) or not run.isdigit():
        raise SystemExit(f"error: a repo is OWNER/NAME and a run id is a number: {repo} {run}")
    (out / "logs").mkdir(parents=True, exist_ok=True)
    r = json.loads(gh(f"repos/{repo}/actions/runs/{run}"))
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
    jobs = json.loads(gh(f"repos/{repo}/actions/runs/{run}/jobs?per_page=100"))["jobs"]
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
        except subprocess.CalledProcessError:
            (out / "logs" / f"{j['id']}.log").write_text("")
        try:
            got = json.loads(gh(f"repos/{repo}/check-runs/{j['id']}/annotations"))
        except subprocess.CalledProcessError:
            got = []
        notes[str(j["id"])] = [
            {k: a.get(k) for k in ("path", "start_line", "annotation_level", "title", "message")}
            for a in got
        ]
    (out / "jobs.json").write_text(json.dumps(kept, indent=1) + "\n")
    (out / "annotations.json").write_text(json.dumps(notes, indent=1) + "\n")


def by_step(job: dict, log: str) -> dict[int, list[str]]:
    """The job's log lines per step number, timestamps removed. The runner marks
    each step it runs: "##[group]Run ..." opens the next step that runs a command
    or an action, "Post job cleanup." the next post step, and "Cleaning up orphan
    processes" the job's last step. Skipped steps print nothing."""
    steps = job.get("steps") or []
    out: dict[int, list[str]] = {s["number"]: [] for s in steps}
    if not steps:
        return out
    ran = [s for s in steps if s.get("conclusion") != "skipped"]
    main = [
        s
        for s in ran
        if s["name"] not in ("Set up job", "Complete job") and not s["name"].startswith("Post ")
    ]
    post = [s for s in ran if s["name"].startswith("Post ")]
    last = [s for s in ran if s["name"] == "Complete job"]
    current = ran[0] if ran else steps[0]
    for raw in log.splitlines():
        m = STAMP.match(raw)
        text = raw[m.end() :] if m else raw
        if text.startswith("##[group]Run ") and main:
            current = main.pop(0)
        elif text.startswith("Post job cleanup.") and post:
            current = post.pop(0)
        elif text.startswith("Cleaning up orphan processes") and last:
            current = last[0]
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
    failing, mismatches, warnings, out_jobs = [], [], {}, []
    for job in jobs:
        log_path = d / "logs" / f"{job['id']}.log"
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
            if step["conclusion"] == "failure":
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
                if WARNING.search(x) and not ERROR.search(x):
                    key = norm(x)
                    w = warnings.setdefault(key, where | {"line": x.strip(), "count": 0})
                    w["count"] += 1
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
        "verdict": {"enum": ["failure", "green-with-findings", "clean", "in-progress"]},
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
    elif len(argv) == 3 and argv[1] == "check":
        problems = check(json.loads(Path(argv[2]).read_text()))
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
