"""
PFM Export - Turn parser and training data exporters.

Converts .pfm conversation files into fine-tuning JSONL formats:
  - OpenAI  (messages array with system/user/assistant roles)
  - Alpaca  (instruction/input/output per turn pair)
  - ShareGPT (conversations array with human/gpt roles)

Usage:
    from pfm.export import export_documents

    docs = [PFMReader.read(p) for p in pfm_paths]
    lines, total_turns = export_documents(docs, format="openai")
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

from pfm.document import PFMDocument
from pfm.reader import PFMReader


# ---------------------------------------------------------------------------
# Turn parser
# ---------------------------------------------------------------------------

def parse_turns(text: str) -> list[tuple[str, str]]:
    """Parse a chain string into (role, content) turn pairs.

    Chrome extension writes chains as:
        User: ...\n\nAssistant: ...

    We split on double-newline boundaries and detect User:/Assistant: prefixes.
    """
    turns: list[tuple[str, str]] = []
    if not text or not text.strip():
        return turns

    blocks = text.split("\n\n")
    current_role: str | None = None
    current_lines: list[str] = []

    for block in blocks:
        stripped = block.strip()
        if not stripped:
            continue

        # Detect role prefix
        if stripped.startswith("User:"):
            # Flush previous
            if current_role is not None:
                turns.append((current_role, "\n\n".join(current_lines).strip()))
            current_role = "user"
            current_lines = [stripped[len("User:"):].strip()]
        elif stripped.startswith("Assistant:"):
            if current_role is not None:
                turns.append((current_role, "\n\n".join(current_lines).strip()))
            current_role = "assistant"
            current_lines = [stripped[len("Assistant:"):].strip()]
        elif stripped.startswith("Agent:"):
            if current_role is not None:
                turns.append((current_role, "\n\n".join(current_lines).strip()))
            current_role = "assistant"
            current_lines = [stripped[len("Agent:"):].strip()]
        else:
            # Continuation of current block
            if current_role is not None:
                current_lines.append(stripped)
            else:
                # No role prefix yet — treat as assistant content
                current_role = "assistant"
                current_lines = [stripped]

    # Flush last turn
    if current_role is not None:
        turns.append((current_role, "\n\n".join(current_lines).strip()))

    return turns


def _extract_metadata(doc: PFMDocument) -> dict[str, str]:
    """Extract optional metadata fields from a PFM document."""
    meta: dict[str, str] = {}
    if doc.model:
        meta["model"] = doc.model
    if doc.agent:
        meta["platform"] = doc.agent
    # Check custom_meta for extra fields
    for key in ("source_url", "title", "platform"):
        val = doc.custom_meta.get(key, "")
        if val:
            meta[key] = val
    return meta


# ---------------------------------------------------------------------------
# Format exporters — each returns (json_line, turn_count)
# ---------------------------------------------------------------------------

def _export_openai(doc: PFMDocument, turns: list[tuple[str, str]], meta: dict[str, str]) -> tuple[str, int]:
    """Export one document as OpenAI fine-tuning format."""
    platform = meta.get("platform", "unknown")
    model = meta.get("model", "unknown")
    system_msg = f"Conversation from {platform} using {model}"

    messages: list[dict[str, str]] = [{"role": "system", "content": system_msg}]
    for role, content in turns:
        messages.append({"role": role, "content": content})

    return json.dumps({"messages": messages}, ensure_ascii=False), len(turns)


def _export_alpaca(doc: PFMDocument, turns: list[tuple[str, str]], meta: dict[str, str]) -> tuple[list[str], int]:
    """Export one document as Alpaca format (one line per user/assistant pair)."""
    lines: list[str] = []
    i = 0
    while i < len(turns):
        role, content = turns[i]
        if role == "user" and i + 1 < len(turns) and turns[i + 1][0] == "assistant":
            entry = {
                "instruction": content,
                "input": "",
                "output": turns[i + 1][1],
            }
            if meta:
                entry["metadata"] = meta
            lines.append(json.dumps(entry, ensure_ascii=False))
            i += 2
        else:
            i += 1
    return lines, len(lines)


def _export_sharegpt(doc: PFMDocument, turns: list[tuple[str, str]], meta: dict[str, str]) -> tuple[str, int]:
    """Export one document as ShareGPT format."""
    conversations: list[dict[str, str]] = []
    for role, content in turns:
        gpt_role = "human" if role == "user" else "gpt"
        conversations.append({"from": gpt_role, "value": content})

    return json.dumps({"conversations": conversations}, ensure_ascii=False), len(turns)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def export_document(doc: PFMDocument, fmt: str = "openai") -> tuple[list[str], int]:
    """Export a single PFM document to JSONL lines.

    Returns (lines, turn_count).
    """
    # Prefer chain section; fall back to content
    chain = doc.chain
    if chain:
        turns = parse_turns(chain)
    else:
        content = doc.content or ""
        if content:
            turns = [("assistant", content)]
        else:
            return [], 0

    if not turns:
        return [], 0

    meta = _extract_metadata(doc)

    if fmt == "openai":
        line, count = _export_openai(doc, turns, meta)
        return [line], count
    elif fmt == "alpaca":
        lines, count = _export_alpaca(doc, turns, meta)
        return lines, count
    elif fmt == "sharegpt":
        line, count = _export_sharegpt(doc, turns, meta)
        return [line], count
    else:
        raise ValueError(f"Unknown export format: {fmt!r}. Use: openai, alpaca, sharegpt")


def export_documents(docs: Sequence[PFMDocument], fmt: str = "openai") -> tuple[list[str], int]:
    """Export multiple PFM documents. Returns (all_lines, total_turns)."""
    all_lines: list[str] = []
    total_turns = 0
    for doc in docs:
        lines, count = export_document(doc, fmt)
        all_lines.extend(lines)
        total_turns += count
    return all_lines, total_turns


def load_pfm_paths(path: str) -> list[Path]:
    """Resolve a path to a list of .pfm file paths.

    If path is a file, returns [path].
    If path is a directory, returns all .pfm files in it (non-recursive).
    """
    p = Path(path)
    if p.is_file():
        return [p]
    elif p.is_dir():
        files = sorted(p.glob("*.pfm"))
        return files
    else:
        raise FileNotFoundError(f"Path not found: {path}")
