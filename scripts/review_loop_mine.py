"""Mine review-subagent transcripts for the elenchus review loop's findings, without a model.

Reads every subagent transcript (`<config>/projects/*/*/subagents/*.jsonl`) whose first prompt
asks for a review, keeps those started on or after --since, and pulls from each final report
its Blocking and Should-fix findings and the class each is tagged with. Each finding is then
checked against the bug-class catalog as it stood in git when the round started.

Prints, and writes with --out-md/--out-json:
- the share of tagged findings whose class was already catalogued when the round ran;
- `new:` classes seen more than once and still missing from the catalog;
- rounds per PR, by repo.

Repos are named only when --public lists them; every other repo folds into one
"private repos" row, so the committed table names no private repo.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import statistics
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field

ROOT = pathlib.Path(__file__).resolve().parent.parent
CATALOG = "plugins/techne/skills/elenchus/references/bug-classes.md"
SLUG_RE = re.compile(r"^### (?:\d+\. )?([a-z0-9]+(?:-[a-z0-9]+)*): ", re.M)

# The first prompt of a review subagent, in the shapes the fleet has used.
REVIEW_RE = re.compile(
    r"\b(?:review(?:er|ing)?|verify pass|verify round|dispatched reader|elenchus)\b", re.I
)
# Implementers of review fixes and other non-review agents that mention a review.
NOT_REVIEW_RE = re.compile(
    r"^\s*IDEAS=|heuresis|\bscout\b|\byou (?:implement|are the implementer|fix)\b|\bfix round\b",
    re.I,
)
PR_URL_RE = re.compile(r"github\.com/([\w.-]+)/([\w.-]+)/pull/(\d+)")
SLUG_PR_RE = re.compile(r"\b(?:([\w.-]+)/)?([A-Za-z][\w.-]*)(?:#|\s+(?:PR|pull)\s+#)(\d+)\b")
WORKTREE_RE = re.compile(r"/ajsoftworks/([\w.-]+)/")
ROUND_RE = re.compile(r"\bround (\d+)\b|\b(\d+)(?:st|nd|rd|th) round\b|\br(\d+)\b", re.I)
VERIFY_RE = re.compile(r"\bverify (?:pass|round)\b|\bverif(?:y|ies) (?:the|those) fixes\b", re.I)

SEVERITY_RE = re.compile(r"\b(blocking|should[- ]fix)\b", re.I)
OTHER_SEVERITY_RE = re.compile(r"\b(minor|nits?|informational|verified clean)\b", re.I)
# "Blocking: none", "No blocking findings", "nothing blocking" open no finding.
NEGATED_RE = re.compile(
    r"\b(?:no|none|nothing|zero|0)\b[^.\n]{0,40}\b(?:blocking|should[- ]fix)\b"
    r"|\b(?:blocking|should[- ]fix)\b[*:\s]*(?:none|nothing|no\s+(?:findings?|items?|issues?)\b"
    r"|0\b|clean)",
    re.I,
)
LABEL_RE = re.compile(r"^\*\*\s*(?:\d+|[A-Z]\d?)[.)]\s")
# A verify round's status line for an earlier finding, not a new one.
RESOLVED_RE = re.compile(
    r"✅|\b(?:fixed|resolved|closed|addressed)\b\s*[.:*)]|[:(]\s*(?:fixed|resolved)\b", re.I
)
# The severity field of elenchus's own output format, under a finding already opened.
FIELD_RE = re.compile(r"^\s*[-*]\s+\*\*(?:severity|class|anchor|verdict)\*\*", re.I)
NEW_RE = re.compile(r"`?new:\s*([^`\]\n.;,|)]{2,60})`?", re.I)


@dataclass
class Finding:
    severity: str
    cls: str  # a catalog slug, "new: <name>", or "" when untagged
    catalogued: bool | None  # None when untagged, new, or the round predates the catalog


@dataclass
class Round:
    path: str
    started: str
    repo: str
    owner: str
    pr: str
    round: int | None
    findings: list[Finding] = field(default_factory=list)
    stated: dict[str, int] = field(default_factory=dict)
    catalog_existed: bool = True


def text_of(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            x.get("text", "") for x in content if isinstance(x, dict) and x.get("type") == "text"
        )
    return ""


def read_transcript(path: pathlib.Path) -> tuple[str, str, str] | None:
    """(first prompt, its timestamp, last assistant text), or None when either is missing."""
    first = started = last = ""
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg = rec.get("message") or {}
                if rec.get("type") == "user" and not first:
                    first = text_of(msg.get("content"))
                    started = rec.get("timestamp", "")
                elif rec.get("type") == "assistant":
                    t = text_of(msg.get("content"))
                    if t.strip():
                        last = t
    except OSError as exc:
        print(f"warning: cannot read {path}: {exc}", file=sys.stderr)
        return None
    return (first, started, last) if first and last else None


def identify(prompt: str, known: set[str]) -> tuple[str, str, str]:
    """(owner, repo, pr) from a review prompt; pr is "" when only the repo is known.

    An `owner/name#N` slug always counts; a bare `name#N` only when `name` is a known repo
    (a folder in the workspace), so "review of PR #90" is not read as a repo called "of".
    Repo names are lowercased, as GitHub compares them.
    """
    head = prompt[:1500]
    if m := PR_URL_RE.search(head):
        return m.group(1), m.group(2).lower(), m.group(3)
    slugs = [
        (m.group(1) or "", m.group(2).lower(), m.group(3))
        for m in SLUG_PR_RE.finditer(head)
        if m.group(1) or m.group(2).lower() in known
    ]
    wt = WORKTREE_RE.search(head)
    here = wt.group(1).lower() if wt else ""
    owned = [s for s in slugs if s[0]]
    if owned:
        return owned[0]
    # The repo the reviewer stands in wins over a PR the prompt only cites.
    if here:
        mine = [s for s in slugs if s[1] == here]
        if mine:
            return mine[0]
        pr = re.search(r"(?<![\w/-])PR #(\d+)", head)
        if pr or not slugs:
            return "", here, pr.group(1) if pr else ""
    return slugs[0] if slugs else ("", "", "")


def round_of(prompt: str) -> int | None:
    m = ROUND_RE.search(prompt[:1500])
    if m:
        return int(next(g for g in m.groups() if g))
    return None


def is_heading(line: str) -> bool:
    """A Markdown heading, or a short wholly bold label ("**Should-fix**", "**New findings**").

    A bold line with a numbered label, code, punctuation or more than five words ("**1.
    Blocking: heads over-count**", "**[Should-fix] boundary-input `a.py:2`: ...**") opens
    a finding.
    """
    s = line.strip()
    if re.match(r"^#{1,6}\s", s):
        return not re.match(r"^#{3,6}\s+\d+[.)]?\s", s)
    bold = re.fullmatch(r"\*\*([^*]+)\*\*:?", s)
    if not bold or LABEL_RE.match(s):
        return False
    label = bold.group(1).strip().rstrip(":")
    return bool(re.fullmatch(r"[\w -]+", label)) and len(label.split()) <= 5


def names_own_severity(line: str, sev: re.Match[str]) -> bool:
    """The severity sits in the line's lead: its opening bold span or first 25 characters.

    "**Round 2 is not clean.** One should-fix is open" is a summary, not a finding.
    """
    if '"severity"' in line:
        return True
    bold = re.match(r"^\s*(?:[-*]\s+|\d+[.)]\s+)?\*\*(.*?)\*\*", line)
    if bold:
        return sev.start() <= bold.end() + 3
    body = len(line) - len(line.lstrip("-*#0123456789.) "))
    return sev.start() - body < 25


def parse_findings(report: str, slugs: list[str]) -> list[tuple[str, str]]:
    """(severity, class) for each Blocking or Should-fix finding in a report.

    A finding opens on a line that names its own severity (an item, a bold lead or a JSON
    "severity" key), or on an item under a Blocking or Should-fix heading. Under a heading,
    numbered, bold-led and sub-heading items are the findings when the section has any, so
    the plain bullets that detail them are not counted; otherwise its top-level bullets are.
    """
    by_len = sorted(slugs, key=len, reverse=True)
    # A slug also matches written with spaces ("claim-code drift", "boundary input").
    alts = [re.escape(s).replace(r"\-", r"[-\s]") for s in by_len]
    slug_re = re.compile(r"(?<![\w-])(" + "|".join(alts) + r")(?![\w-])", re.I) if alts else None
    lines = report.splitlines()
    starts: list[tuple[int, str]] = []
    stops: set[int] = set()
    section, strong, plain = "", [], []

    def close() -> None:
        starts.extend((i, section) for i in (strong or plain))

    for i, line in enumerate(lines):
        sev = SEVERITY_RE.search(line)
        negated = bool(NEGATED_RE.search(line))
        other = OTHER_SEVERITY_RE.search(line)
        if FIELD_RE.match(line):
            continue
        if is_heading(line):
            stops.add(i)
            close()
            section, strong, plain = "", [], []
            if sev and not negated and not OTHER_SEVERITY_RE.search(line):
                section = sev.group(1).lower()
            continue
        lead = re.match(r"^\s*(?:\d+[.)]\s|\*\*|#{3,6}\s)", line)
        top_bullet = re.match(r"^[-*]\s", line)
        early = bool(sev) and names_own_severity(line, sev)
        if (lead or top_bullet) and other and names_own_severity(line, other):
            stops.add(i)  # a Minor or Nit item ends the finding above it
            continue
        if sev and early and not negated and (lead or top_bullet or '"severity"' in line):
            if RESOLVED_RE.search(line):
                stops.add(i)
            elif section:
                strong.append(i)
            else:
                starts.append((i, sev.group(1).lower()))
        elif section and lead:
            strong.append(i)
        elif section and top_bullet:
            plain.append(i)
    close()
    starts.sort()
    out = []
    bounds = sorted(stops | {i for i, _ in starts})
    for i, sev in starts:
        end = next((b for b in bounds if b > i), min(len(lines), i + 25))
        block = "\n".join(lines[max(0, i - 2) if '"severity"' in lines[i] else i : end])
        cls = ""
        nm = NEW_RE.search(block)
        sm = slug_re.search(block) if slug_re else None
        if sm and (not nm or sm.start() < nm.start()):
            cls = canonical(sm.group(1))
        elif nm and normalize_new(nm.group(1)):
            cls = "new: " + normalize_new(nm.group(1))
        out.append(("blocking" if sev.startswith("block") else "should-fix", cls))
    return out


def canonical(found: str) -> str:
    return re.sub(r"[-\s]+", "-", found.lower())


NUMBERS = {"no": 0, "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
STATED_RE = re.compile(
    r"\b(no|zero|one|two|three|four|five|six|\d)\s+(?:open\s+|new\s+|remaining\s+)?"
    r"(blocking|should[- ]fix)",
    re.I,
)


def stated_counts(report: str) -> dict[str, int]:
    """The counts a report's opening states ("two Should-fix"), to check the parser against."""
    out: dict[str, int] = {}
    for m in STATED_RE.finditer(report[:600]):
        sev = "blocking" if m.group(2).lower().startswith("b") else "should-fix"
        word = m.group(1).lower()
        out.setdefault(sev, NUMBERS[word] if word in NUMBERS else int(word))
    return out


def normalize_new(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")


def catalog_history(root: pathlib.Path) -> list[tuple[str, list[str]]]:
    """[(commit time ISO, slugs)] oldest first, from the catalog's git history on main."""
    log = subprocess.run(
        ["git", "-C", str(root), "log", "--format=%H %cI", "origin/main", "--", CATALOG],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split("\n")
    hist = []
    for entry in filter(None, log):
        sha, when = entry.split(" ", 1)
        body = subprocess.run(
            ["git", "-C", str(root), "show", f"{sha}:{CATALOG}"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        hist.append((utc(when), SLUG_RE.findall(body)))
    return sorted(hist)


def utc(iso: str) -> str:
    from datetime import UTC, datetime

    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(UTC).isoformat()


def catalog_at(hist: list[tuple[str, list[str]]], when: str) -> set[str]:
    current: list[str] = []
    for t, slugs in hist:
        if t <= when:
            current = slugs
    return set(current)


def mine(
    paths: list[pathlib.Path], since: str, hist: list[tuple[str, list[str]]], known: set[str]
) -> list[Round]:
    all_slugs = sorted({s for _, slugs in hist for s in slugs})
    rounds = []
    for path in sorted(paths):
        got = read_transcript(path)
        if not got:
            continue
        prompt, started, report = got
        if not started or utc(started) < since:
            continue
        if not REVIEW_RE.search(prompt[:600]) or NOT_REVIEW_RE.search(prompt[:600]):
            continue
        owner, repo, pr = identify(prompt, known)
        if not repo:
            continue
        rnd = Round(str(path), utc(started), repo, owner, pr, round_of(prompt))
        rnd.stated = stated_counts(report)
        then = catalog_at(hist, rnd.started)
        rnd.catalog_existed = bool(then)
        for sev, cls in parse_findings(report, all_slugs):
            slug = bool(cls) and not cls.startswith("new:")
            catalogued = (cls in then) if slug and then else None
            rnd.findings.append(Finding(sev, cls, catalogued))
        if VERIFY_RE.search(prompt[:600]) and rnd.round is None:
            rnd.round = -1  # numbered after the PR's other rounds
        rounds.append(rnd)
    number_rounds(rounds)
    return rounds


def number_rounds(rounds: list[Round]) -> None:
    """Fill missing round numbers by start order within each PR."""
    by_pr: dict[str, list[Round]] = defaultdict(list)
    for r in rounds:
        by_pr[key(r)].append(r)
    for rs in by_pr.values():
        rs.sort(key=lambda r: r.started)
        for n, r in enumerate(rs, 1):
            if r.round is None or r.round < 0:
                r.round = n


def key(r: Round) -> str:
    return f"{r.repo}#{r.pr}" if r.pr else f"{r.repo}@{pathlib.Path(r.path).parent.parent.name}"


def summarize(rounds: list[Round], public: set[str], current: set[str]) -> dict:
    findings = [f for r in rounds for f in r.findings]
    public = {p.lower() for p in public}
    after = [f for r in rounds if r.catalog_existed for f in r.findings]
    tagged = [f for f in after if f.cls]
    known = [f for f in tagged if f.catalogued]
    new = [f for f in tagged if f.cls.startswith("new:")]
    before = len(findings) - len(after)
    new_seen: dict[str, set[str]] = defaultdict(set)
    for r in rounds:
        for f in r.findings:
            if f.cls.startswith("new:"):
                new_seen[f.cls].add(key(r))
    repeated_new = {
        c: sorted(label_key(k, public) for k in ks)
        for c, ks in sorted(new_seen.items())
        if len(ks) > 1 and c[5:] not in current
    }
    by_repo: dict[str, dict[str, int]] = defaultdict(dict)
    for r in rounds:
        if not r.pr:
            continue
        repo = r.repo if r.repo.lower() in public else "private repos"
        k = key(r)
        by_repo[repo][k] = max(by_repo[repo].get(k, 0), r.round or 0)
    repo_rows = {
        repo: {
            "prs": len(prs),
            "median_rounds": statistics.median(prs.values()),
            "max_rounds": max(prs.values()),
        }
        for repo, prs in sorted(by_repo.items())
    }
    checked = [r for r in rounds if r.stated]
    agree = sum(
        all(sum(f.severity == s for f in r.findings) == n for s, n in r.stated.items())
        for r in checked
    )
    wasted = sum(
        1
        for r in rounds
        if r.catalog_existed and r.findings and all(f.catalogued for f in r.findings)
    )
    return {
        "rounds": len(rounds),
        "parser_check": {"rounds_stating_counts": len(checked), "parsed_counts_agree": agree},
        "prs": sum(v["prs"] for v in repo_rows.values()),
        "findings": len(findings),
        "before_catalog": before,
        "tagged": len(tagged),
        "untagged": len(after) - len(tagged),
        "already_catalogued": len(known),
        "not_yet_catalogued": sum(f.catalogued is False for f in tagged),
        "new_tagged": len(new),
        "already_catalogued_share": round(len(known) / len(tagged), 3) if tagged else None,
        "already_catalogued_share_of_all": round(len(known) / len(after), 3) if after else None,
        "rounds_all_catalogued": wasted,
        "class_counts": dict(Counter(f.cls for f in tagged).most_common()),
        "repeated_new_never_added": repeated_new,
        "rounds_per_pr_by_repo": repo_rows,
    }


def label_key(k: str, public: set[str]) -> str:
    """A PR key safe to publish: a public repo's PR, else no name at all."""
    m = re.match(r"([^#@]+)([#@]?)", k)
    repo, sep = (m.group(1), m.group(2)) if m else (k, "")
    if repo.lower() not in public:
        return "a private repo"
    return k if sep == "#" else f"{repo} (no PR number)"


def to_markdown(s: dict, since: str, command: str = "") -> str:
    share = s["already_catalogued_share"]
    check = s["parser_check"]
    lines = [
        f"# Review-loop findings since {since[:10]}",
        "",
        "Generated by `scripts/review_loop_mine.py`; do not edit by hand.",
        *([f"Command: `{command}`", ""] if command else [""]),
        "A reviewer tags each finding with a catalog slug or `new: <name>`, so the share below",
        "is how often reviewers placed a finding in a class the catalog already held: by the",
        "brief's definition, a finding the author's catalog walk before review could have caught.",
        "Most tagged findings come from reviewers told to tag from this same catalog, so the share",
        "of all findings, tagged or not, is given beside it.",
        "Findings from rounds that ran before the catalog existed on main are counted apart.",
        "",
        "| Measure | Value |",
        "| --- | --- |",
        f"| Review rounds | {s['rounds']} |",
        f"| PRs with a known number | {s['prs']} |",
        f"| Blocking + Should-fix findings | {s['findings']} |",
        f"| From rounds before the catalog existed | {s['before_catalog']} |",
        f"| After it: tagged with a class | {s['tagged']} |",
        f"| After it: untagged | {s['untagged']} |",
        f"| Tagged with a class already in the catalog | {s['already_catalogued']} |",
        f"| Tagged with a slug the catalog added later | {s['not_yet_catalogued']} |",
        f"| Tagged `new:` | {s['new_tagged']} |",
        "| Share of tagged findings in a class already catalogued | "
        + (f"{share:.1%}" if share is not None else "n/a")
        + " |",
        "| Same, as a share of every finding after the catalog existed | "
        + (
            f"{s['already_catalogued_share_of_all']:.1%}"
            if s["already_catalogued_share_of_all"] is not None
            else "n/a"
        )
        + " |",
        f"| Rounds whose every finding was already catalogued | {s['rounds_all_catalogued']} |",
        "",
        f"Parser check: of {check['rounds_stating_counts']} reports whose opening states how"
        " many Blocking or Should-fix findings they hold, the parsed count matches in"
        f" {check['parsed_counts_agree']}.",
        "",
        "## Findings by class",
        "",
        "| Class | Findings |",
        "| --- | --- |",
        *(f"| `{c}` | {n} |" for c, n in s["class_counts"].items()),
        "",
        "## `new:` classes seen in more than one PR and never added",
        "",
    ]
    rep = s["repeated_new_never_added"]
    lines += [f"- `{c}`: {', '.join(ks)}" for c, ks in rep.items()] or ["None."]
    lines += [
        "",
        "## Rounds per PR, by repo",
        "",
        "| Repo | PRs | Median rounds | Max rounds |",
        "| --- | --- | --- | --- |",
        *(
            f"| {repo} | {v['prs']} | {v['median_rounds']:g} | {v['max_rounds']} |"
            for repo, v in s["rounds_per_pr_by_repo"].items()
        ),
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--since", default="2026-10-22", help="first day to include (UTC)")
    ap.add_argument("--until", help="first day to leave out (UTC); default: none")
    ap.add_argument(
        "--config-dir",
        action="append",
        type=pathlib.Path,
        help="Claude config folder to read (repeatable; default ~/.claude and ~/.claude-personal)",
    )
    ap.add_argument(
        "--workspace",
        type=pathlib.Path,
        default=pathlib.Path.home() / "ajsoftworks",
        help="folder whose subfolders are the repo names a review prompt may cite",
    )
    ap.add_argument("--public", default="", help="comma-separated repos that may be named")
    ap.add_argument("--out-md", type=pathlib.Path)
    ap.add_argument("--out-json", type=pathlib.Path)
    args = ap.parse_args(argv)
    dirs = args.config_dir or [
        pathlib.Path.home() / ".claude",
        pathlib.Path.home() / ".claude-personal",
    ]
    paths = [p for d in dirs for p in d.glob("projects/*/*/subagents/*.jsonl")]
    since = utc(args.since + "T00:00:00+00:00")
    until = utc(args.until + "T00:00:00+00:00") if args.until else None
    hist = catalog_history(ROOT)
    known = {p.name.lower() for p in args.workspace.iterdir() if p.is_dir()}
    rounds = [r for r in mine(paths, since, hist, known) if not until or r.started < until]
    current = set(hist[-1][1]) if hist else set()
    public = {p.strip() for p in args.public.split(",") if p.strip()}
    summary = summarize(rounds, public, current)
    command = " ".join(["uv run python scripts/review_loop_mine.py", *(argv or sys.argv[1:])])
    md = to_markdown(summary, since, command)
    if args.out_md:
        args.out_md.write_text(md, encoding="utf-8")
    if args.out_json:
        args.out_json.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
