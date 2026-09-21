"""Tests for the pure-Python data-quality engine."""

import pytest

from mcp_limsdq import checks


ROWS = [
    {"sample_id": "S-1", "analyte": "Glucose", "result": "5.4", "status": "PASS"},
    {"sample_id": "S-2", "analyte": "Glucose", "result": "<0.5", "status": "PASS"},
    {"sample_id": "S-3", "analyte": "Lactate", "result": "ND", "status": "FAIL"},
    {"sample_id": "S-4", "analyte": "Lactate", "result": "12.75", "status": "PASS"},
]


def test_is_censored_tokens():
    assert checks.is_censored("ND")
    assert checks.is_censored("bql")
    assert checks.is_censored("<0.01")
    assert checks.is_censored(">1000")
    assert checks.is_censored("TNTC")
    assert not checks.is_censored("5.4")
    assert not checks.is_censored("")
    assert not checks.is_censored(None)


def test_coerce_number():
    assert checks.coerce_number("42") == 42
    assert checks.coerce_number("5.4") == 5.4
    assert checks.coerce_number("1,000.5") == 1000.5
    assert checks.coerce_number("ND") is None
    assert checks.coerce_number("") is None
    assert checks.coerce_number("abc") is None


def test_infer_schema_dtypes_and_censored():
    schema = checks.infer_schema(ROWS)
    by_name = {c["name"]: c for c in schema["columns"]}
    assert by_name["result"]["dtype"] == "float"
    assert by_name["result"]["allow_censored"] is True
    assert by_name["result"]["min"] == 5.4
    assert by_name["result"]["max"] == 12.75
    assert by_name["sample_id"]["dtype"] == "string"
    assert by_name["sample_id"]["required"] is True
    assert by_name["status"]["allowed"] == ["FAIL", "PASS"]


def test_infer_schema_empty():
    assert checks.infer_schema([]) == {"columns": [], "allow_extra_columns": True}


def test_validate_clean_rows():
    schema = checks.infer_schema(ROWS)
    report = checks.validate(ROWS, schema)
    assert report["valid"] is True
    assert report["issue_count"] == 0
    assert report["rows_checked"] == 4


def test_validate_issue_codes():
    schema = {
        "columns": [
            {"name": "sample_id", "dtype": "string", "required": True},
            {"name": "result", "dtype": "float", "required": True,
             "min": 0, "max": 50, "allow_censored": False},
            {"name": "status", "dtype": "string", "allowed": ["PASS", "FAIL"]},
        ],
        "allow_extra_columns": False,
    }
    rows = [
        {"sample_id": "", "result": "5.4", "status": "PASS", "extra": "x"},   # blank required + unknown col
        {"sample_id": "S-2", "result": "-3", "status": "PASS"},              # out of range
        {"sample_id": "S-3", "result": "high", "status": "PASS"},            # type mismatch
        {"sample_id": "S-4", "result": "ND", "status": "MAYBE"},             # censored + not allowed
    ]
    report = checks.validate(rows, schema)
    codes = {(i["row"], i["column"], i["code"]) for i in report["issues"]}
    assert (1, "sample_id", "MISSING_REQUIRED") in codes
    assert (1, "extra", "UNKNOWN_COLUMN") in codes
    assert (2, "result", "OUT_OF_RANGE") in codes
    assert (3, "result", "TYPE_MISMATCH") in codes
    assert (4, "result", "CENSORED_NOT_ALLOWED") in codes
    assert (4, "status", "NOT_ALLOWED") in codes
    assert report["valid"] is False


def test_validate_allows_censored_when_permitted():
    schema = {"columns": [
        {"name": "result", "dtype": "float", "allow_censored": True, "min": 0, "max": 50}
    ]}
    report = checks.validate([{"result": "BQL"}, {"result": "<0.01"}], schema)
    assert report["valid"] is True


def test_compare_identical():
    before = [{"id": "A", "v": "1.0"}, {"id": "B", "v": "2"}]
    after = [{"id": "A", "v": "1.0"}, {"id": "B", "v": "2"}]
    result = checks.compare(before, after, key="id")
    assert result["identical"] is True
    assert result["changed_cell_count"] == 0


def test_compare_reports_diffs():
    before = [{"id": "A", "v": "5.40"}, {"id": "B", "v": "2"}, {"id": "C", "v": "9"}]
    after = [{"id": "A", "v": "5.4"}, {"id": "B", "v": "2.5"}, {"id": "D", "v": "9"}]
    result = checks.compare(before, after, key="id", tolerance=0.01)
    # 5.40 vs 5.4 within tolerance -> not a change
    assert result["rows_only_in_before"] == ["C"]
    assert result["rows_only_in_after"] == ["D"]
    assert result["changed_cell_count"] == 1
    change = result["changed_cells"][0]
    assert change["key"] == "B" and change["column"] == "v"
    assert change["before"] == "2" and change["after"] == "2.5"
    assert result["identical"] is False


def test_compare_blank_normalization():
    before = [{"id": "A", "v": ""}]
    after = [{"id": "A", "v": "   "}]
    assert checks.compare(before, after, key="id")["identical"] is True


def test_compare_duplicate_keys_rejected():
    before = [{"id": "A", "v": "1"}, {"id": "A", "v": "2"}]
    with pytest.raises(ValueError, match="duplicate key"):
        checks.compare(before, [{"id": "A", "v": "1"}], key="id")


def test_compare_blank_key_rejected():
    with pytest.raises(ValueError, match="blank key"):
        checks.compare([{"id": "", "v": "1"}], [{"id": "A", "v": "1"}], key="id")


def test_compare_column_side_diffs():
    before = [{"id": "A", "v": "1", "old": "x"}]
    after = [{"id": "A", "v": "1", "new": "y"}]
    result = checks.compare(before, after, key="id")
    assert result["columns_only_in_before"] == ["old"]
    assert result["columns_only_in_after"] == ["new"]


def test_profile_numeric_and_text():
    prof = checks.profile(ROWS)
    assert prof["row_count"] == 4
    by_name = {c["name"]: c for c in prof["columns"]}
    result = by_name["result"]
    assert result["dtype_guess"] == "numeric"
    assert result["censored_count"] == 2
    assert result["min"] == 5.4 and result["max"] == 12.75
    status = by_name["status"]
    assert status["dtype_guess"] == "text"
    assert status["most_common"][0] == {"value": "PASS", "count": 3}


def test_profile_empty():
    assert checks.profile([]) == {"row_count": 0, "columns": []}


def test_read_csv_roundtrip(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
    rows = checks.read_csv(str(p))
    assert rows == [{"a": "1", "b": "2"}, {"a": "3", "b": "4"}]
