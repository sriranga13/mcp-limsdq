"""MCP server exposing lab/LIMS data-quality checks as tools for AI assistants."""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from . import checks

mcp = FastMCP("mcp-limsdq")


def _load_json(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


@mcp.tool()
def infer_schema(csv_path: str) -> dict:
    """Infer a validation schema from a lab CSV export.

    Returns column dtypes, required flags, numeric ranges, censored-value
    detection, and allowed-value suggestions. Save the result as schema.json
    and refine it, then use it with validate.
    """
    return checks.infer_schema(checks.read_csv(csv_path))


@mcp.tool()
def validate(csv_path: str, schema_path: str, max_issues: int = 50) -> dict:
    """Validate a lab CSV export against a JSON schema.

    Returns valid/invalid plus a list of issues (row, column, code, message).
    Issue codes: MISSING_REQUIRED, TYPE_MISMATCH, OUT_OF_RANGE, NOT_ALLOWED,
    CENSORED_NOT_ALLOWED, UNKNOWN_COLUMN.
    """
    report = checks.validate(checks.read_csv(csv_path), _load_json(schema_path))
    if len(report["issues"]) > max_issues:
        report["issues"] = report["issues"][:max_issues]
        report["truncated"] = True
    return report


@mcp.tool()
def compare(before_csv: str, after_csv: str, key: str, tolerance: float = 0.0) -> dict:
    """Diff two lab CSV exports (e.g. before/after a LIMS migration or ETL run).

    Aligns rows on the key column and reports rows present on only one side,
    columns present on only one side, and every changed cell with before/after
    values. tolerance absorbs float rounding between systems.
    """
    return checks.compare(
        checks.read_csv(before_csv), checks.read_csv(after_csv),
        key, tolerance=tolerance,
    )


@mcp.tool()
def profile(csv_path: str) -> dict:
    """Summarize a lab CSV export: per-column counts, uniques, censored values,
    numeric min/max/mean or most common text values."""
    return checks.profile(checks.read_csv(csv_path))


def serve() -> None:
    mcp.run(transport="stdio")
