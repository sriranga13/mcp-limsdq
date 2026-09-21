"""CLI: `mcp-limsdq serve` starts the MCP server; `mcp-limsdq check` validates locally."""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__, checks


def _cmd_serve(_args: argparse.Namespace) -> int:
    from .server import serve

    serve()
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    rows = checks.read_csv(args.csv)
    with open(args.schema, encoding="utf-8") as fh:
        schema = json.load(fh)
    report = checks.validate(rows, schema)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, default=str)
    if args.quiet:
        print("VALID" if report["valid"] else f"INVALID ({report['issue_count']} issues)")
    else:
        for issue in report["issues"][: args.max_issues]:
            print(f"row {issue['row']} [{issue['column']}] {issue['code']}: {issue['message']}")
        if report["issue_count"] > args.max_issues:
            print(f"... and {report['issue_count'] - args.max_issues} more issues")
        print(f"{report['rows_checked']} rows checked: "
              f"{'VALID' if report['valid'] else 'INVALID'}")
    return 0 if report["valid"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mcp-limsdq",
        description="Lab/LIMS data-quality checks, exposed as MCP tools.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve", help="Run the MCP server over stdio.")
    p_serve.set_defaults(func=_cmd_serve)

    p_check = sub.add_parser("check", help="Validate a CSV against a schema (no MCP client needed).")
    p_check.add_argument("csv", help="Lab CSV export to validate")
    p_check.add_argument("schema", help="JSON schema file")
    p_check.add_argument("--report", help="Write the full JSON report to this path")
    p_check.add_argument("--max-issues", type=int, default=50)
    p_check.add_argument("--quiet", action="store_true")
    p_check.set_defaults(func=_cmd_check)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
