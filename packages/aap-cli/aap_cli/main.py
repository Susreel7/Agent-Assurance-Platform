"""Entry point for the ``aap`` command.

Uses argparse rather than Typer: the dependency set is intentionally tiny and Typer would
add another install for little gain on four subcommands with straightforward flags.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from aap_cli import __version__
from aap_cli.commands import diff as diff_cmd
from aap_cli.commands import extract as extract_cmd
from aap_cli.commands import pack as pack_cmd
from aap_cli.commands import preview as preview_cmd
from aap_cli.commands import validate as validate_cmd
from aap_cli.config import config_from_env


def _optional_before(value: str) -> Path | None:
    if value in {"-", "/dev/null", "null"}:
        return None
    return Path(value)


def _global_flags(*, suppress: bool) -> argparse.ArgumentParser:
    """The flags that apply to every subcommand.

    Registered twice: once on the root parser and once on each subparser, so that both
    ``aap --json preview a b`` and ``aap preview a b --json`` work. Appending a flag is
    what people actually type, and argparse rejects it by default.

    The subparser copies default to SUPPRESS. Without it the subparser is parsed second
    and writes its own default over a value the root parser already captured, so the
    earlier position would silently stop working.
    """
    parser = argparse.ArgumentParser(add_help=False)
    nothing = argparse.SUPPRESS
    parser.add_argument(
        "--base-url",
        dest="base_url",
        default=nothing if suppress else None,
        help="Platform API base URL (default: AAP_BASE_URL or http://localhost:8000)",
    )
    parser.add_argument(
        "--org-id",
        dest="org_id",
        default=nothing if suppress else None,
        help="Organisation id sent as X-Org-Id (default: AAP_ORG_ID)",
    )
    parser.add_argument(
        "--token",
        dest="token",
        default=nothing if suppress else None,
        help="Bearer token (default: AAP_TOKEN)",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        default=nothing if suppress else False,
        help="Machine-readable output",
    )
    return parser


def build_parser() -> argparse.ArgumentParser:
    inherited = _global_flags(suppress=True)
    parser = argparse.ArgumentParser(
        prog="aap",
        description="Agent Assurance Platform CLI",
        parents=[_global_flags(suppress=False)],
    )
    parser.add_argument("--version", action="version", version=f"aap {__version__}")

    sub = parser.add_subparsers(dest="command", required=True)

    p_validate = sub.add_parser(
        "validate", help="Validate a descriptor against AAP 0.1", parents=[inherited]
    )
    p_validate.add_argument("descriptor", type=Path, help="Path to descriptor.yaml or .json")

    p_diff = sub.add_parser(
        "diff", help="Semantic diff between two descriptors", parents=[inherited]
    )
    p_diff.add_argument("before", type=Path, help="Previous descriptor")
    p_diff.add_argument("after", type=Path, help="New descriptor")

    p_preview = sub.add_parser("preview", help="CI release gate verdict", parents=[inherited])
    p_preview.add_argument(
        "before",
        type=_optional_before,
        help="Previous descriptor, or - / null for a first version",
    )
    p_preview.add_argument("after", type=Path, help="New descriptor")
    p_preview.add_argument(
        "--offline",
        action="store_true",
        help="Local differ and provisional materiality (no API call)",
    )

    p_extract = sub.add_parser(
        "extract",
        help="Harvest composition from a repo into the descriptor",
        parents=[inherited],
    )
    p_extract.add_argument(
        "repo",
        type=Path,
        help="Repository root to scan",
    )
    p_extract.add_argument(
        "descriptor",
        type=Path,
        help="Path to .aap.yaml descriptor to patch",
    )
    p_extract.add_argument(
        "--write",
        action="store_true",
        help="Write extracted fields back to the descriptor file",
    )

    p_pack = sub.add_parser("pack", help="Download an accreditation pack", parents=[inherited])
    p_pack.add_argument("accreditation_id", help="Accreditation UUID")
    p_pack.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory to write the pack file (default: current working directory)",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = config_from_env(
        base_url=args.base_url,
        org_id=args.org_id,
        token=args.token,
        json_output=args.json_output,
    )

    if args.command == "validate":
        return validate_cmd.run(args.descriptor, config)
    if args.command == "diff":
        return diff_cmd.run(args.before, args.after, config)
    if args.command == "preview":
        before_path = args.before
        return preview_cmd.run(
            before_path,
            args.after,
            config,
            offline=args.offline,
        )
    if args.command == "extract":
        return extract_cmd.run(
            args.repo,
            args.descriptor,
            config,
            write=args.write,
        )
    if args.command == "pack":
        return pack_cmd.run(args.accreditation_id, config, output_dir=args.output_dir)
    raise RuntimeError(f"unhandled command {args.command!r}")


if __name__ == "__main__":
    sys.exit(main())
