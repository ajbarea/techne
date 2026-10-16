"""Command line for every mechanical heuresis step. Skills and agents call this."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

import heuresis


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="heuresis")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("version", help="print the heuresis version")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "version":
        print(heuresis.__version__)
        return 0
    raise AssertionError(f"unhandled command {args.command}")
