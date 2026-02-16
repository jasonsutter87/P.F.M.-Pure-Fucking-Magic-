"""
PFM Streaming Writer - Write sections on the fly, index at the end.

Solves the "4-hour agent task crashes at hour 3" problem.

Design:
    #!PFM/1.0:STREAM              <- Magic line with stream flag
    #@meta                         <- Meta written immediately on open
    id: ...
    agent: ...
    #@content                      <- Sections written as they arrive
    First chunk of content...
    #@tools                        <- More sections appended over time
    search("query")
    #@chain
    ...
    #@index:trailing               <- Index written on close (or crash recovery)
    content 85 28
    tools 121 16
    chain 145 20
    #!END:173                      <- EOF with index offset for fast seeking

The trailing index means:
  - Sections are written to disk the moment they're ready
  - If the process crashes, you still have everything up to that point
  - On close, the index is appended at the end
  - Readers check for trailing index if no inline index found
  - Crash recovery can rebuild index by scanning section markers

Usage:
    with PFMStreamWriter("output.pfm", agent="my-agent") as w:
        w.write_section("content", "first result...")
        w.write_section("tools", "search('query')")
        # ... hours later ...
        w.write_section("chain", "full conversation")
    # Index written automatically on close

    # Append mode (resume after crash):
    with PFMStreamWriter("output.pfm", append=True) as w:
        w.write_section("content", "more results")
"""

from __future__ import annotations

import hashlib
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pfm.spec import MAGIC, EOF_MARKER, SECTION_PREFIX, FORMAT_VERSION, escape_content


class PFMStreamWriter:
    """
    Streaming .pfm writer. Sections are flushed to disk immediately.
    Index is written on close.
    """

    def __init__(
        self,
        path: str | Path,
        agent: str = "",
        model: str = "",
        append: bool = False,
        **custom_meta: str,
    ) -> None:
        self.path = Path(path)
        self._sections: list[tuple[str, int, int]] = []  # (name, offset, length)
        self._checksum = hashlib.sha256()
        self._closed = False

        if append and self.path.exists():
            self._handle, self._sections = _recover(self.path)
            # Recompute running checksum from existing sections
            self._checksum = hashlib.sha256()
            raw = self.path.read_bytes()
            for name, offset, length in self._sections:
                if 0 <= offset and offset + length <= len(raw):
                    self._checksum.update(raw[offset:offset + length])
            # Position at end, before any trailing index/EOF
            self._handle.seek(0, 2)
        else:
            self._handle = open(self.path, "wb")
            self._write_header(agent, model, custom_meta)

    def _write_header(self, agent: str, model: str, custom_meta: dict[str, str]) -> None:
        """Write magic line and meta section."""
        doc_id = str(uuid.uuid4())
        created = datetime.now(timezone.utc).isoformat()

        self._write(f"{MAGIC}/{FORMAT_VERSION}:STREAM\n")
        self._write(f"{SECTION_PREFIX}meta\n")
        self._write(f"id: {doc_id}\n")
        if agent:
            self._write(f"agent: {agent}\n")
        if model:
            self._write(f"model: {model}\n")
        self._write(f"created: {created}\n")
        for key, val in custom_meta.items():
            self._write(f"{key}: {val}\n")
        self._handle.flush()

    def write_section(self, name: str, content: str) -> None:
        """Write a section to disk immediately. Flushes after write."""
        if self._closed:
            raise RuntimeError("Cannot write to a closed PFMStreamWriter")

        header = f"{SECTION_PREFIX}{name}\n"
        self._handle.write(header.encode("utf-8"))

        # Escape content lines that look like PFM markers
        escaped = escape_content(content)
        content_bytes = escaped.encode("utf-8")
        offset = self._handle.tell()
        self._handle.write(content_bytes)

        # Ensure trailing newline
        if not content_bytes.endswith(b"\n"):
            self._handle.write(b"\n")
            length = len(content_bytes) + 1
        else:
            length = len(content_bytes)

        self._sections.append((name, offset, length))
        # Checksum covers the original unescaped content
        self._checksum.update(content.encode("utf-8"))

        # Flush to disk immediately — this is the whole point
        self._handle.flush()
        os.fsync(self._handle.fileno())

    def close(self) -> None:
        """Write the trailing index and EOF marker. Finalizes the file."""
        if self._closed:
            return

        # Write trailing index
        index_offset = self._handle.tell()
        self._write(f"{SECTION_PREFIX}index:trailing\n")
        for name, offset, length in self._sections:
            self._write(f"{name} {offset} {length}\n")

        # Write checksum as part of index block
        self._write(f"checksum {self._checksum.hexdigest()}\n")

        # EOF with index offset for fast reverse-seeking
        self._write(f"{EOF_MARKER}:{index_offset}\n")

        self._handle.flush()
        os.fsync(self._handle.fileno())
        self._handle.close()
        self._closed = True

    def _write(self, text: str) -> None:
        self._handle.write(text.encode("utf-8"))

    def __enter__(self) -> PFMStreamWriter:
        return self

    def __exit__(self, *args) -> None:
        self.close()

    @property
    def sections_written(self) -> int:
        return len(self._sections)

    @property
    def bytes_written(self) -> int:
        return self._handle.tell() if not self._closed else self.path.stat().st_size


def _recover(path: Path) -> tuple:
    """
    Recover a streamed .pfm file (e.g., after crash).
    Scans for section markers and rebuilds the section list.
    Returns (file_handle, sections) with handle positioned for appending.

    PFM-004 fix: Creates backup before truncation, uses rfind for marker search.
    """
    # Create backup before any modifications
    backup_path = path.with_suffix(path.suffix + ".bak")
    shutil.copy2(path, backup_path)

    raw = path.read_bytes()
    text = raw.decode("utf-8")
    lines = text.split("\n")

    sections: list[tuple[str, int, int]] = []
    byte_pos = 0

    i = 0
    current_section_name: str | None = None
    current_content_start: int = 0

    while i < len(lines):
        line = lines[i]
        line_bytes = len(line.encode("utf-8")) + 1  # +1 for newline

        # Only match unescaped section markers
        if line.startswith(SECTION_PREFIX) and not line.startswith("\\#"):
            # Flush previous section
            if current_section_name is not None:
                length = byte_pos - current_content_start
                sections.append((current_section_name, current_content_start, length))

            section_tag = line[len(SECTION_PREFIX):]

            # Skip meta, index, and trailing index
            if section_tag in ("meta", "index", "index:trailing"):
                current_section_name = None
            else:
                current_section_name = section_tag
                current_content_start = byte_pos + line_bytes

        elif (line.startswith(EOF_MARKER) or line.startswith(MAGIC)) and not line.startswith("\\#"):
            # Flush previous section
            if current_section_name is not None:
                length = byte_pos - current_content_start
                sections.append((current_section_name, current_content_start, length))
                current_section_name = None

        byte_pos += line_bytes
        i += 1

    # Flush last section if file was truncated (crash)
    if current_section_name is not None:
        length = byte_pos - current_content_start
        sections.append((current_section_name, current_content_start, length))

    # Strip any trailing index/EOF for appending
    # PFM-004 fix: Use rfind to find the LAST occurrence, not the first
    truncate_at = len(raw)
    trailing_marker = f"{SECTION_PREFIX}index:trailing"
    # Search from end of file for trailing index marker
    rpos = text.rfind(trailing_marker)
    if rpos >= 0:
        truncate_at = len(text[:rpos].encode("utf-8"))
    else:
        # No trailing index — look for EOF marker from end
        eof_pos = text.rfind(EOF_MARKER)
        if eof_pos >= 0:
            truncate_at = len(text[:eof_pos].encode("utf-8"))

    handle = open(path, "r+b")
    handle.seek(truncate_at)
    handle.truncate()

    return handle, sections
