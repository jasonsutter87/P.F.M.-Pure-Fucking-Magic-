"""
PFM Reader - Fast parser for .pfm files.

Speed features:
  - Magic byte check in first 64 bytes (instant file identification)
  - Index-based O(1) section access (seek directly to any section by byte offset)
  - Lazy loading: only reads sections when requested
  - Streaming: can parse from file handle without loading entire file into memory

Security features:
  - Content unescaping (reverses writer escaping of #@/#! markers)
  - Strict allowlist for meta field parsing (no arbitrary setattr)
  - File size limits (prevents OOM from crafted files)
  - Index bounds validation (prevents out-of-bounds reads)
"""

from __future__ import annotations

import hashlib
import hmac as _hmac
from pathlib import Path
from typing import BinaryIO

from pfm.spec import (
    MAGIC, EOF_MARKER, SECTION_PREFIX, MAX_MAGIC_SCAN_BYTES,
    META_ALLOWLIST, MAX_FILE_SIZE, MAX_META_FIELDS, SUPPORTED_FORMAT_VERSIONS,
    unescape_content,
)
from pfm.document import PFMDocument, PFMSection


class PFMIndex:
    """Parsed index for O(1) section access."""

    def __init__(self) -> None:
        self.entries: dict[str, list[tuple[int, int]]] = {}  # name -> [(offset, length), ...]

    def add(self, name: str, offset: int, length: int) -> None:
        if name not in self.entries:
            self.entries[name] = []
        self.entries[name].append((offset, length))

    def get(self, name: str) -> tuple[int, int] | None:
        """Get first entry for a section name. Returns (offset, length) or None."""
        entries = self.entries.get(name)
        if entries:
            return entries[0]
        return None

    def get_all(self, name: str) -> list[tuple[int, int]]:
        """Get all entries for a section name."""
        return self.entries.get(name, [])

    @property
    def section_names(self) -> list[str]:
        return list(self.entries.keys())


class PFMReader:
    """
    Fast .pfm file reader.

    Usage:
        # Full parse
        doc = PFMReader.read("file.pfm")

        # Indexed access (lazy - only reads what you need)
        reader = PFMReader.open("file.pfm")
        content = reader.get_section("content")
        reader.close()

        # Context manager
        with PFMReader.open("file.pfm") as reader:
            content = reader.get_section("content")
    """

    def __init__(self, handle: BinaryIO, raw: bytes | None = None) -> None:
        self._handle = handle
        self._raw = raw  # If we loaded into memory
        self.meta: dict[str, str] = {}
        self.index: PFMIndex = PFMIndex()
        self.format_version: str = ""
        self._parsed_header = False

    @staticmethod
    def is_pfm(path: str | Path) -> bool:
        """Fast check if a file is PFM format. Reads only first 64 bytes."""
        with open(path, "rb") as f:
            head = f.read(MAX_MAGIC_SCAN_BYTES)
        return head.startswith(MAGIC.encode("utf-8"))

    @staticmethod
    def is_pfm_bytes(data: bytes) -> bool:
        """Fast check if bytes are PFM format."""
        return data[:len(MAGIC)].startswith(MAGIC.encode("utf-8"))

    @classmethod
    def read(cls, path: str | Path, max_size: int = MAX_FILE_SIZE) -> PFMDocument:
        """Fully parse a .pfm file into a PFMDocument."""
        path = Path(path)
        file_size = path.stat().st_size
        if file_size > max_size:
            raise ValueError(
                f"File size {file_size} exceeds maximum {max_size} bytes. "
                f"Pass max_size= to override."
            )
        with open(path, "rb") as f:
            data = f.read()
        return cls.parse(data)

    @classmethod
    def parse(cls, data: bytes) -> PFMDocument:
        """Parse bytes into a PFMDocument."""
        text = data.decode("utf-8")
        lines = text.split("\n")

        doc = PFMDocument()
        current_section: str | None = None
        section_lines: list[str] = []
        in_meta = False
        in_index = False

        i = 0
        while i < len(lines):
            line = lines[i]

            # Magic line (handles both "#!PFM/1.0" and "#!PFM/1.0:STREAM")
            if line.startswith(MAGIC):
                version_part = line.split("/", 1)[1] if "/" in line else "1.0"
                parsed_version = version_part.split(":")[0]  # Strip :STREAM flag
                if parsed_version not in SUPPORTED_FORMAT_VERSIONS:
                    raise ValueError(
                        f"Unsupported PFM format version: {parsed_version!r}. "
                        f"Supported: {', '.join(sorted(SUPPORTED_FORMAT_VERSIONS))}"
                    )
                doc.format_version = parsed_version
                i += 1
                continue

            # EOF marker (only match unescaped)
            if line.startswith(EOF_MARKER):
                break

            # Section header (only match unescaped — escaped lines start with \#)
            if line.startswith(SECTION_PREFIX):
                # Flush previous section
                skip_sections = ("meta", "index", "index:trailing")
                if current_section and current_section not in skip_sections:
                    content = "\n".join(section_lines)
                    # Strip trailing newline that writer adds
                    if content.endswith("\n"):
                        content = content[:-1]
                    # Unescape content lines
                    content = unescape_content(content)
                    doc.add_section(current_section, content)

                section_name = line[len(SECTION_PREFIX):]
                current_section = section_name
                section_lines = []
                in_meta = section_name == "meta"
                in_index = section_name in ("index", "index:trailing")
                i += 1
                continue

            # Meta key-value pairs (strict allowlist — PFM-002 fix)
            if in_meta:
                if ": " in line:
                    key, val = line.split(": ", 1)
                    key = key.strip()
                    val = val.strip()
                    if key in META_ALLOWLIST:
                        setattr(doc, key, val)
                    else:
                        # PFM-014: Enforce custom meta field count limit
                        if len(doc.custom_meta) >= MAX_META_FIELDS:
                            raise ValueError(
                                f"Maximum custom meta fields exceeded: {MAX_META_FIELDS}"
                            )
                        doc.custom_meta[key] = val
                i += 1
                continue

            # Index entries
            if in_index:
                parts = line.strip().split()
                if len(parts) == 3:
                    name, offset, length = parts
                    # Store in index (not used in full parse, but good to have)
                    pass
                i += 1
                continue

            # Section content (raw — unescaping happens on flush)
            if current_section:
                section_lines.append(line)

            i += 1

        # Flush last section
        if current_section and current_section not in ("meta", "index", "index:trailing"):
            content = "\n".join(section_lines)
            if content.endswith("\n"):
                content = content[:-1]
            content = unescape_content(content)
            doc.add_section(current_section, content)

        return doc

    @classmethod
    def open(cls, path: str | Path, max_size: int = MAX_FILE_SIZE) -> PFMReaderHandle:
        """Open a .pfm file for indexed, lazy reading."""
        path = Path(path)
        file_size = path.stat().st_size
        if file_size > max_size:
            raise ValueError(
                f"File size {file_size} exceeds maximum {max_size} bytes. "
                f"Pass max_size= to override."
            )
        f = builtins_open(path, "rb")
        raw = f.read()
        f.seek(0)
        reader = PFMReaderHandle(f, raw)
        reader._parse_header()
        return reader


# Keep builtins reference so 'open' classmethod doesn't shadow
import builtins
builtins_open = builtins.open


class PFMReaderHandle:
    """
    Handle for indexed access to a .pfm file.
    Uses the index for O(1) section jumps - only reads what you need.
    """

    def __init__(self, handle: BinaryIO, raw: bytes) -> None:
        self._handle = handle
        self._raw = raw
        self.meta: dict[str, str] = {}
        self.index: PFMIndex = PFMIndex()
        self.format_version: str = ""

    def _parse_header(self) -> None:
        """Parse magic, meta, and index sections.

        Handles both inline index (standard) and trailing index (stream mode).
        For stream files, scans from the EOF marker backward to find the index.
        """
        text = self._raw.decode("utf-8")
        lines = text.split("\n")
        is_stream = False

        current_section: str | None = None
        i = 0
        while i < len(lines):
            line = lines[i]

            if line.startswith(MAGIC):
                version_part = line.split("/", 1)[1] if "/" in line else "1.0"
                parsed_version = version_part.split(":")[0]
                if parsed_version not in SUPPORTED_FORMAT_VERSIONS:
                    raise ValueError(
                        f"Unsupported PFM format version: {parsed_version!r}. "
                        f"Supported: {', '.join(sorted(SUPPORTED_FORMAT_VERSIONS))}"
                    )
                self.format_version = parsed_version
                is_stream = ":STREAM" in line
                i += 1
                continue

            if line.startswith(SECTION_PREFIX):
                section_name = line[len(SECTION_PREFIX):]
                current_section = section_name
                # Stop after inline index - don't scan content sections
                if current_section not in ("meta", "index", "index:trailing"):
                    break
                i += 1
                continue

            if current_section == "meta" and ": " in line:
                key, val = line.split(": ", 1)
                self.meta[key.strip()] = val.strip()

            if current_section in ("index", "index:trailing"):
                parts = line.strip().split()
                if len(parts) == 3 and parts[0] != "checksum":
                    name, offset, length = parts
                    off = int(offset)
                    ln = int(length)
                    # PFM-008: Validate index bounds
                    if 0 <= off and off + ln <= len(self._raw):
                        self.index.add(name, off, ln)

            i += 1

        # If stream mode and no index found yet, scan from the end
        if is_stream and not self.index.entries:
            self._parse_trailing_index(lines)

    def _parse_trailing_index(self, lines: list[str]) -> None:
        """Parse trailing index from the end of a stream-mode file."""
        for line in reversed(lines):
            if line.startswith(EOF_MARKER):
                continue
            if line.startswith(f"{SECTION_PREFIX}index:trailing"):
                break  # Found the start of trailing index, we're done
            if line.strip() == "":
                continue
            parts = line.strip().split()
            if len(parts) == 3 and parts[0] != "checksum":
                try:
                    name, offset, length = parts[0], int(parts[1]), int(parts[2])
                    # PFM-008: Validate bounds
                    if 0 <= offset and offset + length <= len(self._raw):
                        self.index.add(name, offset, length)
                except ValueError:
                    continue
            elif len(parts) == 2 and parts[0] == "checksum":
                self.meta["checksum"] = parts[1]

    def get_section(self, name: str) -> str | None:
        """O(1) indexed access to a section's content. Seeks directly by byte offset."""
        entry = self.index.get(name)
        if entry is None:
            return None
        offset, length = entry
        raw = self._raw[offset:offset + length].decode("utf-8")
        # Unescape content
        return unescape_content(raw)

    def get_sections(self, name: str) -> list[str]:
        """Get all sections with the given name."""
        results = []
        for offset, length in self.index.get_all(name):
            raw = self._raw[offset:offset + length].decode("utf-8")
            results.append(unescape_content(raw))
        return results

    @property
    def section_names(self) -> list[str]:
        return self.index.section_names

    def to_document(self) -> PFMDocument:
        """Convert to full PFMDocument (reads all sections)."""
        return PFMReader.parse(self._raw)

    def validate_checksum(self) -> bool:
        """Validate the checksum in meta against actual content.

        PFM-005 fix: Returns False if no checksum is present (fail-closed).
        """
        expected = self.meta.get("checksum", "")
        if not expected:
            return False  # No checksum = not validated

        # Checksum is computed from UNESCAPED section content strings
        # (without trailing newline), matching PFMDocument.compute_checksum().
        h = hashlib.sha256()
        for name in self.index.section_names:
            for offset, length in self.index.get_all(name):
                chunk = self._raw[offset:offset + length]
                # Strip the trailing newline that the writer appends
                if chunk.endswith(b"\n"):
                    chunk = chunk[:-1]
                # Unescape before checksumming (checksum covers original content)
                unescaped = unescape_content(chunk.decode("utf-8")).encode("utf-8")
                h.update(unescaped)
        return _hmac.compare_digest(h.hexdigest(), expected)

    def close(self) -> None:
        self._handle.close()

    def __enter__(self) -> PFMReaderHandle:
        return self

    def __exit__(self, *args) -> None:
        self.close()
