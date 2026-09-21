# Skill-Proof MCP Server

A working Model Context Protocol server with three small tools. This is a
**skills proof**, not a production deployment: it exists to show I can design,
implement, and test a real MCP server end to end.

## Why MCP

Before MCP, every AI host needed bespoke glue code to reach outside tools.
MCP replaces that with one contract: a host and a server exchange JSON-RPC
messages over a transport (stdio or HTTP+SSE), and the server advertises its
capabilities (tools, resources, prompts) in a machine-readable schema.

The mechanics, in short:

```
  +----------------+   JSON-RPC over stdio/HTTP   +----------------+
  |  Host          |  --------------------------> |  Server        |
  | (Claude Code,  |   initialize -> capabilities |  (this project)|
  |  an agent,     |   tools/list                |  - advertises   |
  |  a custom app) |   tools/call {name, args}   |  - executes     |
  +----------------+  <-------------------------- |  - returns      |
                          result payloads         +----------------+
```

Why I used it here: the value of MCP is *separation*. The host handles model
reasoning and UI; the server owns tool execution, auth, and state. A server
written once plugs into any compliant host without host-side changes. That
decoupling is the whole point, and this project demonstrates it: the server
below works with any MCP host via stdio, no custom integration code needed.

## Why these three tools

Each tool isolates one common pattern in AI tooling, and each is honest
about its limits:

1. **`readability_analyze`** — Pure function, no I/O. Shows schema-first tool
   design: typed JSON input, structured JSON output. Flesch Reading Ease and
   Flesch-Kincaid grade use a heuristic syllable counter, which is good
   enough for scoring prose but not for linguistics research.

2. **`fetch_url`** — Network I/O with clear boundaries. Only `http(s)`,
   15s timeout, 1MB cap, HTML only. It strips scripts/styles and returns
   title plus plain-text excerpt. It does *not* execute JavaScript; a page
   that needs a browser would come back thin, and that tradeoff is stated
   in the tool description the model sees.

3. **`notes_store`** — Persistent state with a single action-dispatched tool
   (`save`/`get`/`list`/`delete`, JSON file on disk). MCP servers are
   stateless by default, so state has to be an explicit design choice. Here
   a flat file is the right call: the data is tiny, single-user, and needs
   to survive restarts without a database.

## Files

| File | What it is |
|---|---|
| `server.py` | The MCP server: tool implementations plus protocol wiring |
| `test_server.py` | End-to-end test: real protocol round-trips, in-process |
| `pyproject.toml` | Dependencies (`mcp>=1.9,<2`), Python >= 3.10 |
| `data/notes.json` | Created at runtime by `notes_store` (gitignored in real use) |

## How a host connects

Stdio transport. Any MCP host (Claude Code, Claude Desktop, a custom agent)
spawns the server as a subprocess and talks JSON-RPC over its stdin/stdout:

```json
{
  "mcpServers": {
    "skill-proof": {
      "command": "/path/to/.venv/bin/python",
      "args": ["/path/to/skill-proof/mcp-server/server.py"]
    }
  }
}
```

No API keys, no network config, no services to run. The server announces its
three tools on `initialize`; the host never needs code changes to use them.

## Run it

```bash
cd skill-proof/mcp-server
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/python test_server.py   # runs the full protocol test suite
```

## Testing approach

`test_server.py` does not shortcut the protocol. It wires
`server.run()` to a `ClientSession` through in-memory streams and performs
real `initialize`, `tools/list`, and `tools/call` round-trips: the same
messages a stdio host would send. Each tool is called with valid input,
edge cases (empty text, non-HTTP URL, missing note key) are asserted to
return structured errors rather than crash, and persistence is verified by
checking the JSON file on disk between calls.

## Known limits (deliberate)

- Syllable counting is heuristic, not dictionary-based.
- `fetch_url` cannot read JavaScript-rendered pages.
- Notes are a flat JSON file: fine for one user, wrong for concurrent writers.
- No authentication layer: appropriate for local stdio, not for a networked deployment.
