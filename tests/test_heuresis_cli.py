"""heuresis CLI entry point."""

from __future__ import annotations

import heuresis
from heuresis import cli


def test_version_command_prints_the_package_version(capsys):
    assert cli.main(["version"]) == 0
    assert capsys.readouterr().out.strip() == heuresis.__version__


def test_unknown_command_exits_with_usage_error(capsys):
    try:
        cli.main(["no-such-command"])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("argparse should reject an unknown command")
