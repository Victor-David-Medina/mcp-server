"""Skill-proof MCP server.

Three small, self-contained tools exposed over the Model Context Protocol.
No external services, no API keys. stdlib only, plus the `mcp` package.
"""

import json
import re
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

from mcp.server import Server
from mcp.types import Tool

DATA_DIR = Path(__file__).resolve().parent / "data"
NOTES_FILE = DATA_DIR / "notes.json"

server = Server("skill-proof-mcp")

# ---------------------------------------------------------------- readability

_WORD_RE = re.compile(r"[A-Za-z0-9']+")
_SENTENCE_RE = re.compile(r"[^.!?]+[.!?]+")
_VOWEL_GROUP_RE = re.compile(r"[aeiouy]+")


def _syllables(word: str) -> int:
    """Heuristic syllable count. Good enough for readability scoring."""
    word = word.lower().strip("'")
    if not word:
        return 0
    groups = len(_VOWEL_GROUP_RE.findall(word))
    if word.endswith("e") and groups > 1:
        groups -= 1
    return max(groups, 1)


def readability_analyze(text: str) -> dict:
    words = _WORD_RE.findall(text)
    sentences = _SENTENCE_RE.findall(text) or [text]
    word_count = len(words)
    sentence_count = len(sentences)
    syllable_count = sum(_syllables(w) for w in words)

    if word_count == 0:
        return {"error": "no words found in text"}

    wps = word_count / sentence_count
    spw = syllable_count / word_count
    flesch_ease = 206.835 - 1.015 * wps - 84.6 * spw
    fk_grade = 0.39 * wps + 11.8 * spw - 15.59

    return {
        "word_count": word_count,
        "sentence_count": sentence_count,
        "syllable_count": syllable_count,
        "avg_words_per_sentence": round(wps, 1),
        "flesch_reading_ease": round(flesch_ease, 1),
        "flesch_kincaid_grade": round(fk_grade, 1),
    }

# ------------------------------------------------------------------ url fetch


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip = 0
        self.title = ""
        self._in_title = False
        self.chunks: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self._skip += 1
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self._skip = max(0, self._skip - 1)
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._skip:
            return
        text = data.strip()
        if not text:
            return
        if self._in_title:
            self.title += text
        else:
            self.chunks.append(text)

    def text(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self.chunks)).strip()


def fetch_url(url: str, max_chars: int = 4000) -> dict:
    if not url.startswith(("http://", "https://")):
        return {"error": "only http:// and https:// URLs are supported"}
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "skill-proof-mcp/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read(1_000_000).decode("utf-8", errors="replace")
            content_type = resp.headers.get("Content-Type", "")
    except Exception as exc:  # network errors are user-facing, not crashes
        return {"error": f"fetch failed: {exc}"}

    if "html" not in content_type.lower():
        return {
            "url": url,
            "content_type": content_type,
            "note": "non-HTML content, no text extraction attempted",
        }

    parser = _TextExtractor()
    parser.feed(raw)
    text = parser.text()
    return {
        "url": url,
        "title": parser.title or None,
        "char_count": len(text),
        "excerpt": text[:max_chars],
    }

# --------------------------------------------------------------------- notes


def _load_notes() -> dict:
    if NOTES_FILE.exists():
        return json.loads(NOTES_FILE.read_text())
    return {}


def _save_notes(notes: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    NOTES_FILE.write_text(json.dumps(notes, indent=2))


def notes_store(action: str, key: str = "", value: str = "") -> dict:
    """One tool, four actions. Persistent across server restarts (JSON file)."""
    notes = _load_notes()

    if action == "save":
        if not key:
            return {"error": "key is required to save a note"}
        notes[key] = value
        _save_notes(notes)
        return {"ok": True, "key": key}

    if action == "get":
        if key not in notes:
            return {"error": f"no note stored under key {key!r}"}
        return {"key": key, "value": notes[key]}

    if action == "list":
        return {"count": len(notes), "keys": sorted(notes)}

    if action == "delete":
        if key not in notes:
            return {"error": f"no note stored under key {key!r}"}
        del notes[key]
        _save_notes(notes)
        return {"ok": True, "deleted": key}

    return {"error": f"unknown action {action!r}; use save, get, list, or delete"}

# ------------------------------------------------------------ server wiring


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="readability_analyze",
            description="Analyze English text: word/sentence counts, average "
                        "words per sentence, Flesch Reading Ease, Flesch-Kincaid grade.",
            inputSchema={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        ),
        Tool(
            name="fetch_url",
            description="Fetch an http(s) URL and return its title, character "
                        "count, and a plain-text excerpt. No JavaScript execution.",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "max_chars": {"type": "integer", "default": 4000},
                },
                "required": ["url"],
            },
        ),
        Tool(
            name="notes_store",
            description="Persistent key/value notes. Actions: save, get, list, "
                        "delete. Stored as JSON next to the server.",
            inputSchema={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["save", "get", "list", "delete"]},
                    "key": {"type": "string"},
                    "value": {"type": "string"},
                },
                "required": ["action"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == "readability_analyze":
        result = readability_analyze(arguments["text"])
    elif name == "fetch_url":
        result = fetch_url(arguments["url"], arguments.get("max_chars", 4000))
    elif name == "notes_store":
        result = notes_store(
            arguments["action"],
            arguments.get("key", ""),
            arguments.get("value", ""),
        )
    else:
        result = {"error": f"unknown tool {name!r}"}
    return [{"type": "text", "text": json.dumps(result, indent=2)}]


def main() -> None:
    import anyio
    from mcp.server.stdio import stdio_server

    async def _run():
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream, write_stream, server.create_initialization_options()
            )

    anyio.run(_run)


if __name__ == "__main__":
    main()
