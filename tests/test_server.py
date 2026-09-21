"""Tests for the MCP tool functions and CLI.

The @mcp.tool() decorator leaves plain sync functions callable directly,
so the tools are exercised without spinning up an MCP client.
"""

import json

import pytest

from mcp_limsdq import cli
from mcp_limsdq.server import compare, infer_schema, profile, validate

EXAMPLES = "/home/hatch/workspace/mcp-limsdq/examples"


def test_tool_infer_schema():
    schema = infer_schema(f"{EXAMPLES}/samples.csv")
    names = [c["name"] for c in schema["columns"]]
    assert names == ["sample_id", "analyte", "result", "result_unit", "status", "run_date"]


def test_tool_validate_clean_and_bad(tmp_path):
    schema_path = tmp_path / "schema.json"
    schema_path.write_text(open(f"{EXAMPLES}/schema.json").read(), encoding="utf-8")
    good = validate(f"{EXAMPLES}/samples.csv", str(schema_path))
    assert good["valid"] is True
    bad = validate(f"{EXAMPLES}/samples_bad.csv", str(schema_path))
    assert bad["valid"] is False
    assert bad["issue_count"] >= 5
    codes = {i["code"] for i in bad["issues"]}
    assert {"MISSING_REQUIRED", "OUT_OF_RANGE", "TYPE_MISMATCH", "NOT_ALLOWED"} <= codes


def test_tool_validate_max_issues_truncates(tmp_path):
    schema_path = tmp_path / "schema.json"
    schema_path.write_text(open(f"{EXAMPLES}/schema.json").read(), encoding="utf-8")
    report = validate(f"{EXAMPLES}/samples_bad.csv", str(schema_path), max_issues=2)
    assert len(report["issues"]) == 2
    assert report["truncated"] is True


def test_tool_compare():
    result = compare(
        f"{EXAMPLES}/migration_before.csv",
        f"{EXAMPLES}/migration_after.csv",
        "sample_id", tolerance=0.05,
    )
    assert result["rows_only_in_before"] == ["S-103"]
    assert result["rows_only_in_after"] == ["S-104"]
    assert result["changed_cell_count"] == 0  # 12.75 -> 12.79 within tolerance


def test_tool_compare_strict():
    result = compare(
        f"{EXAMPLES}/migration_before.csv",
        f"{EXAMPLES}/migration_after.csv",
        "sample_id", tolerance=0.0,
    )
    assert result["changed_cell_count"] == 1
    assert result["changed_cells"][0]["key"] == "S-102"


def test_tool_profile():
    prof = profile(f"{EXAMPLES}/samples.csv")
    assert prof["row_count"] == 6
    by_name = {c["name"]: c for c in prof["columns"]}
    assert by_name["result"]["censored_count"] == 3


def test_cli_check_valid_quiet(capsys):
    rc = cli.main(["check", f"{EXAMPLES}/samples.csv", f"{EXAMPLES}/schema.json", "--quiet"])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "VALID"


def test_cli_check_invalid_exit_code_and_report(tmp_path, capsys):
    report = tmp_path / "report.json"
    rc = cli.main(["check", f"{EXAMPLES}/samples_bad.csv", f"{EXAMPLES}/schema.json",
                   "--report", str(report), "--max-issues", "3"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "INVALID" in out
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["valid"] is False
    assert data["issue_count"] >= 5


def test_cli_version(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert "0.1.0" in capsys.readouterr().out
