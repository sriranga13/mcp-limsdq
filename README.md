# mcp-limsdq

An MCP (Model Context Protocol) server that gives AI assistants lab/LIMS data-quality superpowers: validate CSV exports against a schema, infer schemas from example files, profile a dataset, and diff before/after exports for migration or ETL parity checks.

Built for the lab-informatics workflow where a bad CSV silently poisons everything downstream. Instead of eyeballing exports, ask your assistant to check the file first.

## Tools

| Tool | What it does |
|---|---|
| `infer_schema` | Infer column dtypes, required flags, numeric ranges, censored-value detection, and allowed-value lists from an example CSV |
| `validate` | Validate a CSV against a JSON schema; returns per-cell issues with codes |
| `compare` | Row-level diff of two exports aligned on a key column (migration/ETL parity) |
| `profile` | Per-column summary: counts, uniques, censored values, min/max/mean or top values |

Issue codes: `MISSING_REQUIRED`, `TYPE_MISMATCH`, `OUT_OF_RANGE`, `NOT_ALLOWED`, `CENSORED_NOT_ALLOWED`, `UNKNOWN_COLUMN`.

Censored lab tokens (`ND`, `BQL`, `BDL`, `<0.01`, `TNTC`, ...) are first-class: schemas can allow them per column instead of failing validation.

## Install

```bash
pip install mcp-limsdq
```

Requires Python 3.10+.

## Use with Claude Desktop

Add to your MCP config (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "lims-dq": {
      "command": "mcp-limsdq",
      "args": ["serve"]
    }
  }
}
```

Then ask: *"Validate this week's assay export against our schema and flag anything odd."*

## Schema format

```json
{
  "allow_extra_columns": false,
  "columns": [
    {"name": "sample_id", "dtype": "string", "required": true},
    {"name": "result", "dtype": "float", "required": true,
     "min": 0, "max": 50, "allow_censored": true},
    {"name": "status", "dtype": "string", "allowed": ["PASS", "FAIL"]},
    {"name": "run_date", "dtype": "date", "required": true}
  ]
}
```

Tip: point `infer_schema` at a known-good export to generate a starting schema, then tighten ranges and allowed lists by hand.

## Local CLI (no MCP client needed)

```bash
# validate and print issues (exit 0 = valid, 1 = invalid)
mcp-limsdq check exports/assay_2026-09-21.csv schemas/assay.json

# quiet mode for CI
mcp-limsdq check exports/assay.csv schemas/assay.json --quiet --report report.json
```

## Development

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest
```

The quality engine (`src/mcp_limsdq/checks.py`) is stdlib-only and fully decoupled from the MCP layer, so it can be reused as a plain library.

## Examples

See `examples/`: `samples.csv` (clean export with censored values), `samples_bad.csv` (six distinct issue types), `schema.json`, and a `migration_before.csv` / `migration_after.csv` pair for `compare`.

## License

MIT
