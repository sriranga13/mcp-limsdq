"""Pure-Python data-quality engine for lab/LIMS CSV exports.

Stdlib only. The MCP server in server.py is a thin wrapper around these
functions, which makes the logic easy to test and reuse without an MCP client.
"""

from __future__ import annotations

import csv
import datetime as _dt
import math
import re
from collections import Counter
from typing import Any

# Tokens labs use when a measurement is below/above the reportable range.
CENSORED_TOKENS = {"ND", "BQL", "BDL", "LOQ", "TNTC", "TFTC", "NA", "N/A"}
_CENSORED_RE = re.compile(r"^[<>]=?\s*\d+(\.\d+)?([eE][+-]?\d+)?$")

_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%d-%b-%Y", "%Y/%m/%d")


def is_censored(value: Any) -> bool:
    """True if the value is a censored lab token like 'ND', 'BQL' or '<0.01'."""
    if value is None:
        return False
    text = str(value).strip()
    return text.upper() in CENSORED_TOKENS or bool(_CENSORED_RE.match(text))


def is_blank(value: Any) -> bool:
    return value is None or str(value).strip() == ""


def coerce_number(value: Any) -> float | int | None:
    """Parse a numeric value; return None for blanks/censored/non-numeric."""
    if is_blank(value) or is_censored(value):
        return None
    text = str(value).strip().replace(",", "")
    try:
        return int(text)
    except ValueError:
        pass
    try:
        num = float(text)
    except ValueError:
        return None
    return num


def coerce_date(value: Any) -> _dt.date | None:
    if is_blank(value):
        return None
    text = str(value).strip()
    for fmt in _DATE_FORMATS:
        try:
            return _dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def read_csv(path: str) -> list[dict[str, str]]:
    """Read a CSV export into a list of row dicts (all values kept as text)."""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


# ---------------------------------------------------------------------------
# Schema inference
# ---------------------------------------------------------------------------

def infer_schema(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Infer a validation schema from example rows.

    Returns {"columns": [...], "allow_extra_columns": True}. Each column entry
    carries name, dtype (int/float/date/string), required (no blanks seen),
    null_fraction, and for numerics min/max plus allow_censored when censored
    tokens were observed. String columns with few distinct values get an
    "allowed" list suggestion.
    """
    columns: list[dict[str, Any]] = []
    if not rows:
        return {"columns": columns, "allow_extra_columns": True}
    names = list(rows[0].keys())
    n = len(rows)
    for name in names:
        values = [r.get(name) for r in rows]
        nonblank = [v for v in values if not is_blank(v)]
        censored = [v for v in nonblank if is_censored(v)]
        measurable = [v for v in nonblank if not is_censored(v)]

        numbers = [coerce_number(v) for v in measurable]
        dates = [coerce_date(v) for v in measurable]
        if measurable and all(x is not None for x in numbers):
            dtype = "int" if all(isinstance(x, int) for x in numbers) else "float"
        elif measurable and all(x is not None for x in dates):
            dtype = "date"
        else:
            dtype = "string"

        col: dict[str, Any] = {
            "name": name,
            "dtype": dtype,
            "required": len(nonblank) == n,
            "null_fraction": round((n - len(nonblank)) / n, 4),
        }
        if dtype in ("int", "float") and numbers:
            nums = [x for x in numbers if x is not None]
            col["min"] = min(nums)
            col["max"] = max(nums)
        if censored:
            col["allow_censored"] = True
            col["censored_fraction"] = round(len(censored) / n, 4)
        if dtype == "string":
            distinct = sorted({str(v).strip() for v in measurable})
            col["unique_count"] = len(distinct)
            if 1 < len(distinct) <= 20:
                col["allowed"] = distinct
        columns.append(col)
    return {"columns": columns, "allow_extra_columns": True}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _check_value(value: Any, spec: dict[str, Any]) -> str | None:
    """Return an issue code for a single cell, or None if the cell is fine."""
    name = spec["name"]
    dtype = spec.get("dtype", "string")
    required = spec.get("required", False)

    if is_blank(value):
        return "MISSING_REQUIRED" if required else None
    if is_censored(value):
        return None if spec.get("allow_censored") else "CENSORED_NOT_ALLOWED"

    if dtype in ("int", "float"):
        num = coerce_number(value)
        if num is None:
            return "TYPE_MISMATCH"
        if dtype == "int" and not isinstance(num, int):
            return "TYPE_MISMATCH"
        lo, hi = spec.get("min"), spec.get("max")
        if (lo is not None and num < lo) or (hi is not None and num > hi):
            return "OUT_OF_RANGE"
    elif dtype == "date":
        if coerce_date(value) is None:
            return "TYPE_MISMATCH"
    allowed = spec.get("allowed")
    if allowed is not None and str(value).strip() not in [str(a) for a in allowed]:
        return "NOT_ALLOWED"
    return None


def validate(rows: list[dict[str, Any]], schema: dict[str, Any]) -> dict[str, Any]:
    """Validate rows against a schema; return a JSON-serializable report."""
    specs = {c["name"]: c for c in schema.get("columns", [])}
    allow_extra = schema.get("allow_extra_columns", True)
    issues: list[dict[str, Any]] = []
    for i, row in enumerate(rows, start=1):
        if not allow_extra:
            for key in row:
                if key not in specs:
                    issues.append({
                        "row": i, "column": key, "code": "UNKNOWN_COLUMN",
                        "message": f"Column '{key}' is not in the schema",
                        "value": row[key],
                    })
        for name, spec in specs.items():
            code = _check_value(row.get(name), spec)
            if code:
                messages = {
                    "MISSING_REQUIRED": f"Required column '{name}' is blank",
                    "TYPE_MISMATCH": (
                        f"Value {row.get(name)!r} is not a valid {spec.get('dtype')}"
                    ),
                    "OUT_OF_RANGE": f"Value {row.get(name)!r} is outside the allowed range",
                    "NOT_ALLOWED": f"Value {row.get(name)!r} is not in the allowed list",
                    "CENSORED_NOT_ALLOWED": (
                        f"Censored value {row.get(name)!r} is not allowed in '{name}'"
                    ),
                }
                issues.append({
                    "row": i,
                    "column": name,
                    "code": code,
                    "message": messages[code],
                    "value": row.get(name),
                })
    return {
        "valid": not issues,
        "rows_checked": len(rows),
        "columns_checked": len(specs),
        "issue_count": len(issues),
        "issues": issues,
    }


# ---------------------------------------------------------------------------
# Migration / ETL parity comparison
# ---------------------------------------------------------------------------

def _cells_equal(a: Any, b: Any, tolerance: float) -> bool:
    if is_blank(a) and is_blank(b):
        return True
    na, nb = coerce_number(a), coerce_number(b)
    if na is not None and nb is not None:
        return math.isclose(float(na), float(nb), abs_tol=tolerance)
    return str(a).strip() == str(b).strip()


def compare(
    before: list[dict[str, Any]],
    after: list[dict[str, Any]],
    key: str,
    tolerance: float = 0.0,
) -> dict[str, Any]:
    """Row-level diff of two exports aligned on a key column.

    Raises ValueError on duplicate keys (ambiguous alignment).
    """
    def index(rows: list[dict[str, Any]], label: str) -> dict[str, dict[str, Any]]:
        idx: dict[str, dict[str, Any]] = {}
        for i, row in enumerate(rows, start=1):
            k = row.get(key)
            if is_blank(k):
                raise ValueError(f"{label}: row {i} has a blank key column '{key}'")
            ks = str(k).strip()
            if ks in idx:
                raise ValueError(f"{label}: duplicate key {ks!r} in column '{key}'")
            idx[ks] = row
        return idx

    b_idx = index(before, "before")
    a_idx = index(after, "after")
    b_cols = set().union(*(r.keys() for r in before)) if before else set()
    a_cols = set().union(*(r.keys() for r in after)) if after else set()

    changed: list[dict[str, Any]] = []
    for k in sorted(set(b_idx) & set(a_idx)):
        rb, ra = b_idx[k], a_idx[k]
        for col in sorted(set(rb) | set(ra)):
            if col == key:
                continue
            if not _cells_equal(rb.get(col), ra.get(col), tolerance):
                changed.append({
                    "key": k, "column": col,
                    "before": rb.get(col), "after": ra.get(col),
                })
    return {
        "key": key,
        "rows_before": len(before),
        "rows_after": len(after),
        "rows_only_in_before": sorted(set(b_idx) - set(a_idx)),
        "rows_only_in_after": sorted(set(a_idx) - set(b_idx)),
        "columns_only_in_before": sorted(b_cols - a_cols),
        "columns_only_in_after": sorted(a_cols - b_cols),
        "changed_cells": changed,
        "changed_cell_count": len(changed),
        "identical": not changed
        and not (set(b_idx) ^ set(a_idx))
        and b_cols == a_cols,
    }


# ---------------------------------------------------------------------------
# Profiling
# ---------------------------------------------------------------------------

def profile(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-column summary stats for a quick look at a lab export."""
    result: dict[str, Any] = {"row_count": len(rows), "columns": []}
    if not rows:
        return result
    for name in rows[0].keys():
        values = [r.get(name) for r in rows]
        nonblank = [v for v in values if not is_blank(v)]
        censored_n = sum(1 for v in nonblank if is_censored(v))
        measurable = [v for v in nonblank if not is_censored(v)]
        numbers = [coerce_number(v) for v in measurable]
        col: dict[str, Any] = {
            "name": name,
            "nonblank_count": len(nonblank),
            "blank_count": len(rows) - len(nonblank),
            "unique_count": len({str(v).strip() for v in nonblank}),
            "censored_count": censored_n,
        }
        nums = [x for x in numbers if x is not None]
        if measurable and len(nums) == len(measurable):
            col["dtype_guess"] = "numeric"
            col["min"] = min(nums)
            col["max"] = max(nums)
            col["mean"] = round(sum(nums) / len(nums), 4)
        else:
            col["dtype_guess"] = "text"
            col["most_common"] = [
                {"value": v, "count": c}
                for v, c in Counter(str(v).strip() for v in measurable).most_common(5)
            ]
        result["columns"].append(col)
    return result
