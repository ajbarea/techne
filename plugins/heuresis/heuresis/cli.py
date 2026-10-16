"""Command line for every mechanical heuresis step. Skills and agents call this."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections.abc import Sequence
from pathlib import Path

import heuresis
from heuresis import board, context, pool, render, rules, similar, sources, store, sync, verify
from heuresis.model import STATES, TYPES, Coverage, Idea, Record, Verdict

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
    p.add_argument("text", nargs="+")

    p = ideas(sub.add_parser("context", help="list AJ's research sources that exist"))
    p.add_argument("--repos-root", type=Path, required=True)

    p = ideas(sub.add_parser("similar", help="earlier ideas sharing words with TEXT"))
    p.add_argument("--k", type=int, default=5)
    p.add_argument("text", nargs="+")

    p = ideas(sub.add_parser("restate", help="save the neutral restatement and queries"), True)
    p.add_argument("--json", required=True)

    p = ideas(sub.add_parser("search", help="run queries against one source group"), True)
    p.add_argument("--group", choices=sorted(sources.REGISTRY), required=True)
    p.add_argument("--limit", type=int, default=8)
    p.add_argument("--query", action="append", required=True)

    p = ideas(sub.add_parser("add-record", help="append one record to a scout file"), True)
    p.add_argument("--group", choices=[*sorted(sources.REGISTRY), "context"], required=True)
    p.add_argument("--json", required=True)

    ideas(sub.add_parser("pool", help="merge scout files for the judge"), True)

    p = ideas(sub.add_parser("verify", help="check every quote the judge used"), True)
    p.add_argument("--repos-root", type=Path, required=True)

    p = ideas(sub.add_parser("apply", help="enforce the rules and record the verdict"), True)
    p.add_argument("--today", type=dt.date.fromisoformat, default=None)

    p = ideas(sub.add_parser("override", help="record AJ's own decision"))
    p.add_argument("idea_id")
    p.add_argument("state", choices=STATES)
    p.add_argument("--type", choices=TYPES)
    p.add_argument("--project")
    p.add_argument("--duplicate-of")
    p.add_argument("reason", nargs="+")

    ideas(sub.add_parser("board", help="regenerate BOARD.md and LOG.md"))
    return parser


def _capture(args) -> int:
    text = " ".join(args.text).strip()
    if not text:
        print("heuresis: the idea text is empty", file=sys.stderr)
        return 2
    taken = [p.stem for p in (args.ideas / "ideas").glob("*.md")]
    title = store.title_from(text)
    idea = Idea(
        id=store.new_id(dt.date.today(), title, taken),
        title=title,
        captured=_now(),
        captured_via=args.via,
        sections={"Idea": text},
    )
    path = store.save(args.ideas, idea, new=True)
    try:
        sync.publish(args.ideas, [path], f"capture: {idea.id}", dt.date.today())
    except sync.SyncError as exc:
        raise sync.SyncError(f"idea saved locally as {path}, but publishing failed: {exc}") from exc
    print(idea.id)
    return 0


def _search(args) -> int:
    group = sources.REGISTRY[args.group]
    records, coverage = sources.run_queries(group, args.query, args.limit)
    out = _run_dir(args.ideas, args.id) / f"scout-{args.group}.json"
    payload = {
        "group": args.group,
        "queries": args.query,
        "records": [r.to_dict() for r in records],
        "coverage": [c.to_dict() for c in coverage],
    }
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    for c in coverage:
        print(c.line())
    return 0


def _add_record(args) -> int:
    record = Record.from_dict(json.loads(args.json))
    problem = verify.record_problem(record)
    if problem:
        print(f"heuresis: record rejected: {problem}", file=sys.stderr)
        return 2
    out = _run_dir(args.ideas, args.id) / f"scout-{args.group}.json"
    empty = {"group": args.group, "queries": [], "records": [], "coverage": []}
    data = json.loads(out.read_text()) if out.exists() else empty
    data["records"].append(record.to_dict())
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    return 0


def _verify(args) -> int:
    run = _run_dir(args.ideas, args.id)
    judge = json.loads((run / "judge.json").read_text())
    records = {r["ref"]: r for r in json.loads((run / "pool.json").read_text())["records"]}
    cited = [judge.get("closest") or {}, *judge.get("others", [])]
    results = {}
    for item in cited:
        ref = item.get("ref")
        if ref not in records:
            results[str(ref)] = {"ok": False, "reason": "not in pool"}
            continue
        record = Record.from_dict(records[ref])
        ok, why = verify.check(record, item.get("quote", ""), args.ideas, args.repos_root)
        results[ref] = {"ok": ok, "reason": why}
    (run / "verify.json").write_text(json.dumps(results, indent=2))
    closest_ref = (judge.get("closest") or {}).get("ref")
    for ref, result in results.items():
        print(f"{ref}: {'ok' if result['ok'] else result['reason']}")
    if closest_ref and not results.get(closest_ref, {}).get("ok"):
        return EXIT_CLOSEST_DROPPED
    return 0


def _apply(args) -> int:
    today = args.today or dt.date.today()
    run = _run_dir(args.ideas, args.id)
    idea = _load_idea(args.ideas, args.id)
    judge = json.loads((run / "judge.json").read_text())
    pooled = json.loads((run / "pool.json").read_text())
    checked = json.loads((run / "verify.json").read_text())
    records = {r["ref"]: r for r in pooled["records"]}
    dropped = {ref for ref, r in checked.items() if not r["ok"]}
    proposed = judge["verdict"]
    closest = judge.get("closest")
    closest_ref = (closest or {}).get("ref")
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
        dropped=[
            f"{records[r]['url']} ({checked[r]['reason']})" for r in sorted(dropped) if r in records
        ],
    )
    known = {p.stem for p in (args.ideas / "ideas").glob("*.md")} - {idea.id}
    verdict = rules.enforce(
        verdict,
        closest=closest if closest_ref in records else None,
        closest_verified=bool(checked.get(closest_ref, {}).get("ok")),
        known_ids=known,
        today=today,
    )
    idea.sections["Closest work"] = render.closest_section(judge, records, dropped)
    idea.sections["Fit with your work"] = judge.get("fit", "")
    product = render.product_section(judge)
    if product:
        idea.sections["Product evidence"] = product
    idea.revisit_on = list(proposed.get("revisit_on") or idea.revisit_on)
    store.add_verdict(idea, verdict)
    path = store.save(args.ideas, idea)
    paths = [path, *sorted(run.glob("*.json"))]
    sync.publish(args.ideas, paths, f"triage: {idea.id} -> {verdict.state}", today)
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
    sync.publish(
        args.ideas, [store.save(args.ideas, idea)], f"override: {idea.id} -> {args.state}", today
    )
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
            print(json.dumps(similar.similar(" ".join(args.text), ideas, args.k)))
            return 0
        case "restate":
            idea = _load_idea(args.ideas, args.id)
            data = json.loads(args.json)
            if not isinstance(data, dict) or not isinstance(data.get("restated"), str):
                print('heuresis: --json needs {"restated": str, "queries": [str]}', file=sys.stderr)
                return 2
            run = _run_dir(args.ideas, args.id)
            (run / "restate.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))
            idea.sections["Restated"] = data["restated"]
            store.save(args.ideas, idea)
            return 0
        case "search":
            return _search(args)
        case "add-record":
            return _add_record(args)
        case "pool":
            run = _run_dir(args.ideas, args.id)
            pooled = pool.build(sorted(run.glob("scout-*.json")))
            (run / "pool.json").write_text(json.dumps(pooled, indent=2, ensure_ascii=False))
            print(json.dumps(pooled, ensure_ascii=False))
            return 0
        case "verify":
            return _verify(args)
        case "apply":
            return _apply(args)
        case "override":
            return _override(args)
        case "board":
            board.write(args.ideas, dt.date.today())
            return 0
    raise AssertionError(f"unhandled command {args.command}")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _dispatch(args)
    except (store.StoreError, sync.SyncError, ValueError, OSError) as exc:
        print(f"heuresis: {exc}", file=sys.stderr)
        return 1
