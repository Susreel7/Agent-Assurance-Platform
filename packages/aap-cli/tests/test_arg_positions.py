"""Global flags must work before or after the subcommand.

`aap preview a b --json` is what people type. argparse only accepts options declared on
the root parser *before* the subcommand, so the natural form failed with "unrecognized
arguments" and the pipeline got no machine-readable verdict.
"""

from __future__ import annotations

import pytest

from aap_cli.main import build_parser


@pytest.mark.parametrize(
    "argv",
    [
        ["--json", "preview", "before.yaml", "after.yaml"],
        ["preview", "before.yaml", "after.yaml", "--json"],
    ],
    ids=["leading", "trailing"],
)
def test_json_is_accepted_in_either_position(argv: list[str]) -> None:
    args = build_parser().parse_args(argv)
    assert args.json_output is True


def test_json_defaults_to_off() -> None:
    args = build_parser().parse_args(["preview", "before.yaml", "after.yaml"])
    assert args.json_output is False


@pytest.mark.parametrize(
    "argv",
    [
        ["--org-id", "org-9", "diff", "before.yaml", "after.yaml"],
        ["diff", "before.yaml", "after.yaml", "--org-id", "org-9"],
    ],
    ids=["leading", "trailing"],
)
def test_valued_flags_are_accepted_in_either_position(argv: list[str]) -> None:
    args = build_parser().parse_args(argv)
    assert args.org_id == "org-9"


def test_a_leading_flag_is_not_erased_by_the_subparser() -> None:
    """The regression that made this file necessary.

    Both parsers own `--json`. The subparser runs second, so unless its default is
    SUPPRESS it writes False over the True the root parser already recorded.
    """
    args = build_parser().parse_args(
        ["--json", "--org-id", "org-9", "--token", "t", "preview", "a.yaml", "b.yaml"]
    )
    assert args.json_output is True
    assert args.org_id == "org-9"
    assert args.token == "t"


def test_a_trailing_flag_wins_over_a_leading_one() -> None:
    """Last position wins, which is what a shell user expects from a repeated flag."""
    args = build_parser().parse_args(
        ["--org-id", "first", "diff", "a.yaml", "b.yaml", "--org-id", "second"]
    )
    assert args.org_id == "second"


@pytest.mark.parametrize("command", ["validate", "diff", "preview", "pack"])
def test_every_subcommand_accepts_the_global_flags(command: str) -> None:
    operands = {
        "validate": ["d.yaml"],
        "diff": ["a.yaml", "b.yaml"],
        "preview": ["a.yaml", "b.yaml"],
        "pack": ["11111111-2222-3333-4444-555555555555"],
    }[command]
    args = build_parser().parse_args([command, *operands, "--json"])
    assert args.json_output is True


def test_preview_treats_a_dash_as_a_first_version() -> None:
    """A brand new agent has nothing to diff against, and CI should not special-case it."""
    args = build_parser().parse_args(["preview", "-", "after.yaml"])
    assert args.before is None
