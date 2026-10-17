"""Command line for every mechanical heuresis step. Skills and agents call this."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import heuresis
from heuresis import board, context, pool, render, rules, similar, sources, store, sync, verify
from heuresis.model import FACETS, STATES, TYPES, Coverage, Idea, Record, Verdict

EXIT_CLOSEST_DROPPED = 3


def _now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def _check_id(idea_id: str) -> str:
    if not store.IDEA_ID.fullmatch(idea_id):
        raise store.StoreError(f"{idea_id!r} is not an idea id")
    return idea_id


def _run_dir(root: Path, idea_id: str) -> Path:
    path = root / "runs" / _check_id(idea_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _load_idea(root: Path, idea_id: str) -> Idea:
    path = store.idea_path(root, _check_id(idea_id))
    if not path.is_file():
        raise store.StoreError(f"no idea {idea_id} in {root / 'ideas'}")
    return store.load(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="heuresis")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("version", help="print the heuresis version")

    p = sub.add_parser("init", help="create an ideas repository")
    p.add_argument("path", type=Path)
    p.add_argument("--techne-toml", type=Path, default=Path.home() / ".claude" / "techne.toml")
    p.add_argument("--repos-root", type=Path, required=True)

    def ideas(p: argparse.ArgumentParser, with_id: bool = False) -> argparse.ArgumentParser:
        p.add_argument("--ideas", type=Path, required=True)
        if with_id:
            p.add_argument("--id", required=True)
        return p

    p = ideas(sub.add_parser("capture", help="save an idea to the inbox"))
    p.add_argument("--via", choices=["terminal", "phone", "form", "import"], default="terminal")
    # Shell arguments lose $5 and backticks inside double quotes; stdin from a quoted heredoc
    # keeps the text verbatim.
    p.add_argument("--text", help="the idea text, or - to read it from stdin")
    p.add_argument("words", nargs="*", metavar="text")

    p = ideas(sub.add_parser("context", help="list the user's research sources that exist"))
    p.add_argument("--repos-root", type=Path, required=True)

    p = ideas(sub.add_parser("similar", help="earlier ideas sharing words with TEXT"))
    p.add_argument("--k", type=int, default=5)
    p.add_argument("--exclude", action="append", default=[], help="idea id to leave out")
    p.add_argument("text", nargs="+")

    p = ideas(sub.add_parser("restate", help="save the neutral restatement and queries"), True)
    p.add_argument("--json", required=True, help="JSON text, or - to read it from stdin")

    p = ideas(sub.add_parser("search", help="run queries against one source group"), True)
    p.add_argument("--group", choices=sorted(sources.REGISTRY), required=True)
    p.add_argument("--limit", type=int, default=8)
    p.add_argument("--query", action="append", required=True)

    p = ideas(sub.add_parser("add-record", help="append one record to a scout file"), True)
    p.add_argument("--group", choices=[*sorted(sources.REGISTRY), "context"], required=True)
    p.add_argument("--json", required=True, help="JSON text, or - to read it from stdin")

    ideas(sub.add_parser("pool", help="merge scout files for the judge"), True)

    p = ideas(sub.add_parser("verify", help="check every quote the judge used"), True)
    p.add_argument("--repos-root", type=Path, required=True)

    p = ideas(sub.add_parser("apply", help="enforce the rules and record the verdict"), True)
    p.add_argument("--today", type=dt.date.fromisoformat, default=None)

    p = ideas(sub.add_parser("override", help="record the user's own decision"))
    p.add_argument("idea_id")
    p.add_argument("state", choices=STATES)
    p.add_argument("--type", choices=TYPES)
    p.add_argument("--project")
    p.add_argument("--duplicate-of")
    p.add_argument("reason", nargs="+")

    ideas(sub.add_parser("board", help="regenerate BOARD.md and LOG.md"))
    ideas(sub.add_parser("publish", help="commit and push pending idea changes"))
    return parser


def _capture(args) -> int:
    if args.text is not None and args.words:
        print("heuresis: give the idea text as arguments or with --text, not both", file=sys.stderr)
        return 2
    if args.text is None:
        text = " ".join(args.words).strip()
    else:
        text = (sys.stdin.read() if args.text == "-" else args.text).strip()
    if not text:
        print("heuresis: the idea text is empty", file=sys.stderr)
        return 2
    local = [p.stem for p in (args.ideas / "ideas").glob("*.md")]
    taken = [*local, *sync.remote_ideas(args.ideas)]
    title = store.title_from(text)
    idea = Idea(
        id=store.new_id(dt.date.today(), title, taken),
        title=title,
        captured=_now(),
        captured_via=args.via,
        sections={"Idea": text},
    )
    path = store.save(args.ideas, idea, new=True)
    _publish(args.ideas, path, [path], f"capture: {idea.id}", dt.date.today())
    print(idea.id)
    return 0


def _json_arg(text: str) -> Any:
    return json.loads(sys.stdin.read() if text == "-" else text)


def _merge_coverage(old: Coverage, new: Coverage) -> Coverage:
    statuses = {old.status, new.status}
    status = next((s for s in ("ok", "failed") if s in statuses), new.status)
    notes = [n for n in (old.note, new.note) if n]
    note = "; ".join(dict.fromkeys(notes))
    return Coverage(old.source, status, old.queries + new.queries, old.hits + new.hits, note)


def _search(args) -> int:
    group = sources.REGISTRY[args.group]
    records, coverage = sources.run_queries(group, args.query, args.limit)
    out = _run_dir(args.ideas, args.id) / f"scout-{args.group}.json"
    data = _load_json(out, dict) if out.exists() else {}
    merged: dict[str, Coverage] = {
        c["source"]: Coverage.from_dict(c) for c in data.get("coverage", [])
    }
    for c in coverage:
        merged[c.source] = _merge_coverage(merged[c.source], c) if c.source in merged else c
    payload = {
        "group": args.group,
        "queries": [*data.get("queries", []), *args.query],
        "records": [*data.get("records", []), *({**r.to_dict(), "query": q} for q, r in records)],
        "coverage": [c.to_dict() for c in merged.values()],
    }
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    for c in merged.values():
        print(c.line())
    return 0


def _add_record(args) -> int:
    try:
        record = Record.from_dict(_json_arg(args.json))
    except ValueError as exc:
        print(f"heuresis: {exc}", file=sys.stderr)
        return 2
    problem = verify.record_problem(record)
    if problem:
        print(f"heuresis: record rejected: {problem}", file=sys.stderr)
        return 2
    if record.url == f"idea:{_check_id(args.id)}":
        print("heuresis: a record cannot cite the idea being triaged", file=sys.stderr)
        return 2
    out = _run_dir(args.ideas, args.id) / f"scout-{args.group}.json"
    empty = {"group": args.group, "queries": [], "records": [], "coverage": []}
    data = json.loads(out.read_text()) if out.exists() else empty
    data["records"].append(record.to_dict())
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    return 0


RUN_FILES = ("pool.json", "judge.json", "verify.json")
# Written from the pool, so a new pool leaves them describing refs that may now name other records.
POOL_DEPENDENTS = ("judge.json", "verify.json")
TRIAGE_STATES = ("trash", "later", "do", "merged")
NOT_VERIFIED = "not verified against the current quote and record"
# A verify entry holds for the record it checked: re-pooling renumbers refs.
BOUND = ("url", "source", "evidence_url")


def _load_json(path: Path, kind: type):
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, kind):
        raise ValueError(f"{path.name}: expected a JSON {kind.__name__}")
    return data


def _need(ok: bool, name: str, what: str) -> None:
    if not ok:
        raise ValueError(f"{name}: {what}")


def _strings(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def _check_product(name: str, evidence: object) -> None:
    if evidence is None:
        return
    if not isinstance(evidence, dict):
        raise ValueError(f"{name}: product_evidence must be an object")
    for key in ("rivals", "demand"):
        ok = key not in evidence or _strings(evidence[key])
        _need(ok, name, f"product_evidence.{key} must be a list of strings")
    for key in ("riskiest_assumption", "cheapest_test"):
        ok = evidence.get(key) is None or isinstance(evidence[key], str)
        _need(ok, name, f"product_evidence.{key} must be a string")


def _load_judge(run: Path) -> dict:
    judge = _load_json(run / "judge.json", dict)
    name = "judge.json"
    closest = judge.get("closest")
    _need(closest is None or isinstance(closest, dict), name, "closest must be an object or null")
    if closest is not None:
        _need(isinstance(closest.get("ref"), str), name, "closest.ref must be a string like r3")
        differs = closest.get("differs")
        ok = isinstance(differs, dict) and all(isinstance(differs.get(f), str) for f in FACETS)
        _need(ok, name, f"closest.differs must be an object with string {', '.join(FACETS)}")
    others = judge.get("others") or []
    ok = isinstance(others, list) and all(isinstance(o, dict) for o in others)
    _need(ok, name, "others must be a list of objects")
    _need(all("ref" in o for o in others), name, "every item in others needs a ref")
    _need(all(isinstance(o["ref"], str) for o in others), name, "ref in others must be a string")
    ok = all(isinstance(o.get("differs", ""), str) for o in others)
    _need(ok, name, "others[].differs must be a string")
    _need(isinstance(judge.get("fit", ""), str), name, "fit must be a string")
    _check_product(name, judge.get("product_evidence"))
    verdict = judge.get("verdict")
    _need(isinstance(verdict, dict), name, "verdict missing")
    state = verdict.get("state")
    _need(state in TRIAGE_STATES, name, f"verdict.state {state!r} is not one of {TRIAGE_STATES}")
    kind = verdict.get("type")
    _need(kind is None or kind in TYPES, name, f"verdict.type {kind!r} is not one of {TYPES}")
    revisit_on = verdict.get("revisit_on")
    ok = revisit_on is None or (
        isinstance(revisit_on, list) and all(isinstance(v, str) for v in revisit_on)
    )
    _need(ok, name, "verdict.revisit_on must be a list of strings")
    duplicate = verdict.get("duplicate_of")
    ok = duplicate is None or isinstance(duplicate, str)
    _need(ok, name, "verdict.duplicate_of must be a string or null")
    return judge


def _load_pool(run: Path) -> dict:
    pooled = _load_json(run / "pool.json", dict)
    name = "pool.json"
    records, coverage = pooled.get("records"), pooled.get("coverage")
    _need(isinstance(records, list), name, "records must be a list")
    _need(isinstance(coverage, list), name, "coverage must be a list")
    need = ("ref", "title", "url", "source", "kind")
    for r in records:
        _need(isinstance(r, dict) and all(k in r for k in need), name, f"a record lacks {need}")
    for c in coverage:
        _need(isinstance(c, dict) and "source" in c and "status" in c, name, "bad coverage entry")
    return pooled


def _load_verify(run: Path) -> dict:
    checked = _load_json(run / "verify.json", dict)
    for ref, entry in checked.items():
        _need(isinstance(entry, dict) and "ok" in entry, "verify.json", f"{ref} lacks ok")
    return checked


def _cited(judge: dict) -> dict[str, str]:
    """ref -> the quote the judge gave for it; the closest rival's quote wins a repeated ref."""
    cited: dict[str, str] = {}
    for item in [judge.get("closest") or {}, *(judge.get("others") or [])]:
        if item.get("ref") is not None:
            cited.setdefault(str(item["ref"]), str(item.get("quote", "")))
    return cited


def _bound(record: dict) -> dict[str, str]:
    return {key: str(record.get(key) or "") for key in BOUND}


def _same_check(entry: dict, quote: str, record: dict) -> bool:
    """The verify entry was made for this quote against this record."""
    return entry.get("quote") == quote and all(entry.get(k) == v for k, v in _bound(record).items())


def _verified(checked: dict, ref: str, quote: str, record: dict) -> bool:
    entry = checked.get(ref) or {}
    return entry.get("ok") is True and _same_check(entry, quote, record)


def verified_refs(judge: dict, records: dict[str, dict], checked: dict) -> set[str]:
    """The cited refs that apply keeps: in the pool, and checked for this quote and this record."""
    return {
        ref
        for ref, quote in _cited(judge).items()
        if ref in records and _verified(checked, ref, quote, records[ref])
    }


def _scouts(run: Path) -> list[Path]:
    return sorted(run.glob("scout-*.json"))


def _pool(args) -> int:
    run = _run_dir(args.ideas, args.id)
    pooled = pool.build(_scouts(run))
    (run / "pool.json").write_text(json.dumps(pooled, indent=2, ensure_ascii=False))
    for name in POOL_DEPENDENTS:
        (run / name).unlink(missing_ok=True)
    print(json.dumps(pooled, ensure_ascii=False))
    return 0


def _verify(args) -> int:
    run = _run_dir(args.ideas, args.id)
    judge = _load_judge(run)
    records = {r["ref"]: r for r in _load_pool(run)["records"]}
    results = {}
    for ref, quote in _cited(judge).items():
        if ref not in records:
            results[ref] = {"ok": False, "reason": "not in pool", "quote": quote}
            continue
        ok, why = verify.check(Record.from_dict(records[ref]), quote, args.ideas, args.repos_root)
        results[ref] = {"ok": ok, "reason": why, "quote": quote, **_bound(records[ref])}
    (run / "verify.json").write_text(json.dumps(results, indent=2, ensure_ascii=False))
    for ref, result in results.items():
        print(f"{ref}: {'ok' if result['ok'] else result['reason']}")
    closest_ref = (judge.get("closest") or {}).get("ref")
    if closest_ref is not None and not results[str(closest_ref)]["ok"]:
        return EXIT_CLOSEST_DROPPED
    return 0


def _checked_idea(idea: Idea) -> None:
    problems = store.validate(idea)
    if problems:
        raise store.StoreError(f"{idea.id}: " + "; ".join(problems))


def _publish(root: Path, idea_path: Path, paths: list[Path], message: str, today: dt.date) -> None:
    try:
        sync.publish(root, paths, message, today)
    except sync.SyncError as exc:
        hint = "" if sync.PUBLISH_HINT in str(exc) else f"; once that is fixed, {sync.PUBLISH_HINT}"
        raise sync.SyncError(
            f"saved locally as {idea_path}, but publishing failed: {exc}{hint}"
        ) from exc


def _apply(args) -> int:
    today = args.today or dt.date.today()
    run = _run_dir(args.ideas, args.id)
    idea = _load_idea(args.ideas, args.id)
    judge = _load_judge(run)
    pooled = _load_pool(run)
    if pool.build(_scouts(run)) != pooled:
        raise ValueError("pool.json changed since pool ran; run pool again")
    checked = _load_verify(run)
    records = {r["ref"]: r for r in pooled["records"]}
    cited = _cited(judge)
    dropped = set(cited) - verified_refs(judge, records, checked)
    proposed = judge["verdict"]
    closest = judge.get("closest")
    closest_ref = str((closest or {}).get("ref"))

    def why(ref: str) -> str:
        if ref not in records:
            return "not in pool"
        entry = checked.get(ref) or {}
        stale = entry.get("ok") is not False or not _same_check(entry, cited[ref], records[ref])
        return NOT_VERIFIED if stale else str(entry.get("reason") or NOT_VERIFIED)

    verdict = Verdict(
        date=today.isoformat(),
        origin="triage",
        state=proposed["state"],
        reason=proposed.get("reason", ""),
        type=proposed.get("type"),
        project=proposed.get("project"),
        next_step=proposed.get("next_step", ""),
        duplicate_of=proposed.get("duplicate_of"),
        coverage=[Coverage.from_dict(c) for c in pooled["coverage"]],
        dropped=[f"{records[r]['url'] if r in records else r} ({why(r)})" for r in sorted(dropped)],
    )
    known = {p.stem for p in (args.ideas / "ideas").glob("*.md")} - {idea.id}
    verdict = rules.enforce(
        verdict,
        closest=closest if closest_ref in records else None,
        closest_verified=closest_ref not in dropped and closest_ref in cited,
        known_ids=known,
        today=today,
    )
    restate = run / "restate.json"
    if restate.is_file():
        restated = _load_json(restate, dict).get("restated")
        _need(isinstance(restated, str), "restate.json", "restated must be a string")
        idea.sections["Restated"] = store.inert(restated)
    idea.sections["Closest work"] = store.inert(render.closest_section(judge, records, dropped))
    idea.sections["Fit with your work"] = store.inert(judge.get("fit", ""))
    product = render.product_section(judge)
    if product:
        idea.sections["Product evidence"] = store.inert(product)
    else:
        idea.sections.pop("Product evidence", None)
    idea.revisit_on = list(proposed.get("revisit_on") or idea.revisit_on)
    store.add_verdict(idea, verdict)
    _checked_idea(idea)
    path = store.save(args.ideas, idea)
    paths = [path, run]
    _publish(args.ideas, path, paths, f"triage: {idea.id} -> {verdict.state}", today)
    kind, project = verdict.type or "no type", verdict.project or "no project"
    print(f"{idea.id}: {verdict.state} ({kind}, {project})")
    print(verdict.reason)
    return 0


def _override(args) -> int:
    today = dt.date.today()
    idea = _load_idea(args.ideas, args.idea_id)
    verdict = Verdict(
        date=today.isoformat(),
        origin="override",
        state=args.state,
        reason=" ".join(args.reason),
        type=args.type,
        project=args.project,
        duplicate_of=args.duplicate_of,
    )
    known = {p.stem for p in (args.ideas / "ideas").glob("*.md")} - {idea.id}
    if args.state == "merged" and args.duplicate_of not in known:
        print("heuresis: --duplicate-of must name an existing idea", file=sys.stderr)
        return 2
    if args.state == "later":
        verdict.revisit = (today + rules.REVISIT_AFTER_INSUFFICIENT).isoformat()
    store.add_verdict(idea, verdict)
    _checked_idea(idea)
    path = store.save(args.ideas, idea)
    _publish(args.ideas, path, [path], f"override: {idea.id} -> {args.state}", today)
    return 0


def _dispatch(args: argparse.Namespace) -> int:
    match args.command:
        case "version":
            print(heuresis.__version__)
            return 0
        case "init":
            context.init_repo(args.path, args.techne_toml, args.repos_root)
            print(args.path)
            return 0
        case "capture":
            return _capture(args)
        case "context":
            projects = context.load_projects(args.ideas / "projects.toml")
            context_toml = args.ideas / "context.toml"
            found = context.resolve_sources(context_toml, projects, args.repos_root)
            print(json.dumps(found, indent=2))
            return 0
        case "similar":
            ideas = [i for _, i, _ in store.load_all(args.ideas) if i is not None]
            ideas = [i for i in ideas if i.id not in args.exclude]
            print(json.dumps(similar.similar(" ".join(args.text), ideas, args.k)))
            return 0
        case "restate":
            _load_idea(args.ideas, args.id)
            data = _json_arg(args.json)
            if not isinstance(data, dict) or not isinstance(data.get("restated"), str):
                print('heuresis: --json needs {"restated": str, "queries": [str]}', file=sys.stderr)
                return 2
            run = _run_dir(args.ideas, args.id)
            for stale in (*run.glob("scout-*.json"), *(run / n for n in RUN_FILES)):
                stale.unlink(missing_ok=True)
            # The idea file changes only at apply, which commits it; an uncommitted edit here
            # would block every later publish once the remote moves.
            (run / "restate.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))
            return 0
        case "search":
            return _search(args)
        case "add-record":
            return _add_record(args)
        case "pool":
            return _pool(args)
        case "verify":
            return _verify(args)
        case "apply":
            return _apply(args)
        case "override":
            return _override(args)
        case "board":
            board.write(args.ideas, dt.date.today())
            return 0
        case "publish":
            print(sync.publish(args.ideas, [], "publish: pending idea changes", dt.date.today()))
            return 0
    raise AssertionError(f"unhandled command {args.command}")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _dispatch(args)
    except (store.StoreError, sync.SyncError, ValueError, FileNotFoundError) as exc:
        print(f"heuresis: {exc}", file=sys.stderr)
        return 1
