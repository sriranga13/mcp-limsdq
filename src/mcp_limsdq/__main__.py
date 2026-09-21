from .cli import main

if __name__ == "__main__":
    import sys

    # `python -m mcp_limsdq` with no subcommand starts the MCP server.
    if len(sys.argv) == 1:
        sys.argv.append("serve")
    raise SystemExit(main())
