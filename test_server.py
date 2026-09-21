"""In-process end-to-end test for the skill-proof MCP server.

Runs the REAL protocol stack (JSON-RPC messages over in-memory streams),
not a shortcut around it: the SDK's connected-session helper runs the
server and a ClientSession against each other exactly the way a stdio host
would. Every tool gets called and its output asserted.
"""

import anyio
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp.shared.memory import create_connected_server_and_client_session

from server import server as mcp_server

DATA_DIR = Path(__file__).resolve().parent / "data"


def check(label: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}" + (f" — {detail}" if detail else ""))
    if not condition:
        raise AssertionError(label)


async def main() -> None:
    # Clean slate so the notes test is deterministic.
    if DATA_DIR.exists():
        shutil.rmtree(DATA_DIR)

    async with create_connected_server_and_client_session(mcp_server) as session:
        await session.initialize()

        tools = await session.list_tools()
        names = sorted(t.name for t in tools.tools)
        print(f"Server initialized. Tools exposed: {names}")
        check("all 3 tools listed",
              names == ["fetch_url", "notes_store", "readability_analyze"])

        # ---- 1. readability_analyze ----
        sample = (
            "The cat sat on the mat. It was a warm and sunny day outside. "
            "The dog barked loudly at the passing cars on the busy street."
        )
        res = await session.call_tool("readability_analyze", {"text": sample})
        payload = json.loads(res.content[0].text)
        print("readability_analyze ->", json.dumps(payload))
        check("word_count correct", payload["word_count"] == 26,
              f"got {payload['word_count']}")
        check("sentence_count correct", payload["sentence_count"] == 3)
        check("flesch fields present",
              "flesch_reading_ease" in payload and "flesch_kincaid_grade" in payload)
        check("grade level sane", 0 <= payload["flesch_kincaid_grade"] <= 6,
              f"grade {payload['flesch_kincaid_grade']}")

        empty = await session.call_tool("readability_analyze", {"text": "   "})
        check("empty text returns error, not crash",
              "error" in json.loads(empty.content[0].text))

        # ---- 2. fetch_url ----
        res = await session.call_tool("fetch_url", {"url": "https://example.com"})
        payload = json.loads(res.content[0].text)
        print("fetch_url ->", json.dumps(payload)[:300], "...")
        check("example.com fetched", "error" not in payload,
              payload.get("error", ""))
        check("title extracted", payload.get("title") == "Example Domain",
              f"title={payload.get('title')!r}")
        check("excerpt contains body text",
              "documentation examples" in payload["excerpt"].lower())

        bad = await session.call_tool("fetch_url", {"url": "ftp://x.example/y"})
        check("non-http URL rejected",
              "error" in json.loads(bad.content[0].text))

        # ---- 3. notes_store (save -> get -> list -> delete, persisted) ----
        r = await session.call_tool(
            "notes_store",
            {"action": "save", "key": "mcp-proof", "value": "MCP works end to end."},
        )
        check("note saved", json.loads(r.content[0].text).get("ok") is True)

        r = await session.call_tool("notes_store", {"action": "get", "key": "mcp-proof"})
        payload = json.loads(r.content[0].text)
        check("note retrieved", payload.get("value") == "MCP works end to end.")

        r = await session.call_tool("notes_store", {"action": "list"})
        payload = json.loads(r.content[0].text)
        check("note listed", payload["keys"] == ["mcp-proof"],
              f"keys={payload['keys']}")

        # Persistence: the JSON file exists on disk, independent of the session.
        check("notes file persisted on disk",
              (DATA_DIR / "notes.json").exists())

        r = await session.call_tool(
            "notes_store", {"action": "delete", "key": "mcp-proof"})
        check("note deleted", json.loads(r.content[0].text).get("ok") is True)

        r = await session.call_tool("notes_store", {"action": "list"})
        check("store empty after delete",
              json.loads(r.content[0].text)["count"] == 0)

        r = await session.call_tool(
            "notes_store", {"action": "get", "key": "missing"})
        check("missing key returns error, not crash",
              "error" in json.loads(r.content[0].text))

    print("\nAll tool tests passed.")


if __name__ == "__main__":
    anyio.run(main)
