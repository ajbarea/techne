"""Lint a Google Vids script.

Every segment fits one clip and states what Vids would otherwise invent.

Usage: python3 check_script.py script.md [script.md ...]
The rules it enforces are in ../references/vids-rules.md.
"""

import math
import pathlib
import re
import sys
from dataclasses import dataclass, field

#: A Gemini Omni clip in Vids runs at most 15 seconds (Omni 1.2 Flash, 2026-11-05; 10 before).
MAX_SECONDS = 15
#: US conversational rate, about 150 words a minute; a spoken line is timed at it.
WORDS_PER_MINUTE = 150
#: Room a spoken line leaves in its clip for directed pauses and the cut.
HEADROOM_SECONDS = 1
#: Each segment's required fields, matched against its bullet labels.
FIELDS = {
    "Environment & Lighting": re.compile(r"environment", re.I),
    "Avatar (Wardrobe & Physicality)": re.compile(r"wardrobe|physicality", re.I),
    "Visual Overlay": re.compile(r"overlay", re.I),
    "Spoken Script": re.compile(r"\bspoken", re.I),
    "Vocal Direction": re.compile(r"vocal", re.I),
}
#: Fields whose 'At m:ss' times must fall inside their segment.
TIMED = re.compile(r"wardrobe|physicality|overlay", re.I)
SEGMENT = re.compile(r"^#{2,4}\s+(?:Segment|Scene)\b", re.I)
NUMBER = re.compile(r"^#{2,4}\s+\w+\s+S?(\d+)\b", re.I)
SPAN = re.compile(r"\((\d+):(\d{2})\s*[–—-]\s*(\d+):(\d{2})\)")  # noqa: RUF001
AT = re.compile(r"\bAt (\d+):(\d{2})\b(?!\s*[AP]M)", re.I)
END = re.compile(r"^(#{1,6}\s|---\s*$)")
BULLET = re.compile(r"^[*-]\s+(.*)$")
LABEL = re.compile(
    r"^\*\*(.+?):\*\*\s*(.*)$|^\*\*(.+?)\*\*:\s*(.*)$|^([A-Za-z][^:`'\"*\d]{1,59}):\s*(.*)$"
)
DOUBLE = re.compile(r"[\"“”„‟«»″]")
QUOTED = re.compile(r"[\"“„]([^\"“”„]*)[\"”]")
WORD = re.compile(r"\w[\w'’-]*")  # noqa: RUF001
BACKREF = re.compile(r"\b(same as|as above|as before|see segment|segment s?\d+)\b", re.I)


@dataclass
class Segment:
    line: int
    heading: str
    fields: list[tuple[str, int, str]] = field(default_factory=list)
    loose: list[tuple[int, str]] = field(default_factory=list)


def segments(text: str) -> list[Segment]:
    """Each segment heading with its fields: (label, line, text), continuation lines folded in."""
    out: list[Segment] = []
    seg: Segment | None = None
    for n, raw in enumerate(text.splitlines(), 1):
        if SEGMENT.match(raw):
            seg = Segment(n, raw)
            out.append(seg)
            continue
        if seg is None:
            continue
        if END.match(raw):
            seg = None
            continue
        bullet = BULLET.match(raw)
        label = LABEL.match(bullet.group(1)) if bullet else None
        if label:
            groups = label.groups()
            name, body = next((groups[i], groups[i + 1]) for i in (0, 2, 4) if groups[i])
            seg.fields.append((name.strip(), n, body))
        elif seg.fields and raw.strip():
            name, line, body = seg.fields[-1]
            seg.fields[-1] = (name, line, f"{body}\n{raw}")
        elif raw.strip():
            seg.loose.append((n, raw))
    return out


def clock(m: str, s: str) -> int:
    return int(m) * 60 + int(s)


def spoken_seconds(spoken: str) -> float:
    """A word takes one slot; a number takes one per two digits ('2025' is 'twenty twenty-five')."""
    slots = sum(math.ceil(len(w) / 2) if w.isdigit() else 1 for w in WORD.findall(spoken))
    return slots * 60 / WORDS_PER_MINUTE


def check(text: str) -> list[tuple[int, str]]:
    """Every problem as (line, message); an empty list means the script passes."""
    problems: list[tuple[int, str]] = []
    for n, raw in enumerate(text.splitlines(), 1):
        if not SEGMENT.match(raw) and (
            NUMBER.match(raw) or (SPAN.search(raw) and re.match(r"^(#|\*\*)", raw))
        ):
            problems.append(
                (n, "looks like a segment heading but is not '### Segment N (m:ss – m:ss): Title'")  # noqa: RUF001
            )
    segs = segments(text)
    if not segs:
        return problems or [(1, "no '### Segment N (m:ss – m:ss)' headings found")]  # noqa: RUF001
    previous_end: int | None = None
    for seg in segs:
        span = SPAN.search(seg.heading)
        start = end = None
        if span is None:
            problems.append((seg.line, "heading has no (m:ss – m:ss) span"))  # noqa: RUF001
        else:
            start, end = clock(*span.groups()[:2]), clock(*span.groups()[2:])
            if not 0 < end - start <= MAX_SECONDS:
                runs = f"runs {end - start} s" if end > start else "runs backwards or for 0 s"
                problems.append((seg.line, f"segment {runs}; a clip is 1 to {MAX_SECONDS} s"))
            number = NUMBER.match(seg.heading)
            first = number is not None and number.group(1) == "1"
            if not first and previous_end is not None and start != previous_end:
                problems.append(
                    (
                        seg.line,
                        f"segment starts at {start} s but the one before ends at {previous_end} s",
                    )
                )
        previous_end = end
        if DOUBLE.search(seg.heading):
            problems.append(
                (seg.line, "double quotes in the heading get voiced; use single quotes")
            )
        for name, rule in FIELDS.items():
            if not any(rule.search(label) and body.strip() for label, _, body in seg.fields):
                problems.append((seg.line, f"missing {name}"))
        for n, raw in seg.loose:
            if DOUBLE.search(raw):
                problems.append(
                    (n, "double quotes outside the spoken line get voiced; use single quotes")
                )
        for label, n, body in seg.fields:
            if BACKREF.search(body):
                problems.append(
                    (
                        n,
                        f"{label} points elsewhere; each clip is generated alone, "
                        "so say it in full",
                    )
                )
            if TIMED.search(label) and start is not None and end is not None:
                for at in AT.finditer(body):
                    if not start <= clock(*at.groups()) <= end:
                        problems.append((n, f"{label}: '{at.group(0)}' falls outside this segment"))
            if not FIELDS["Spoken Script"].search(label):
                if DOUBLE.search(body):
                    problems.append(
                        (n, f"double quotes in {label} get voiced; use single quotes or backticks")
                    )
                continue
            spans = QUOTED.findall(body)
            if len(DOUBLE.findall(body)) != 2 or len(spans) != 1:
                problems.append(
                    (n, "the spoken line needs exactly one double-quoted span; each one is voiced")
                )
            spoken = " ".join(spans)
            if "[" in spoken or "]" in spoken:
                problems.append(
                    (
                        n,
                        "a [direction] inside the spoken quotes is voiced; "
                        "move it to Vocal Direction",
                    )
                )
            need = spoken_seconds(spoken)
            length = end - start if span and start is not None and end is not None else MAX_SECONDS
            room = min(length, MAX_SECONDS) - HEADROOM_SECONDS
            if length > 0 and need > room:
                problems.append(
                    (
                        n,
                        f"spoken line needs {need:.1f} s at {WORDS_PER_MINUTE} wpm; "
                        f"it has {room} s",
                    )
                )
    return sorted(problems)


def main(argv: list[str]) -> int:
    paths = [pathlib.Path(a) for a in argv]
    if not paths:
        print("usage: check_script.py script.md [script.md ...]", file=sys.stderr)
        return 2
    failed = 0
    for path in paths:
        if not path.is_file():
            print(f"{path}: no such file", file=sys.stderr)
            failed += 1
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as err:
            print(f"{path}: not UTF-8 text ({err.reason} at byte {err.start})", file=sys.stderr)
            failed += 1
            continue
        problems = check(text)
        for line, message in problems:
            print(f"{path}:{line}: {message}", file=sys.stderr)
        failed += bool(problems)
        if not problems:
            print(f"{path}: ok")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
