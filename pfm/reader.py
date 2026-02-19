"""
PFM Reader - Fast parser for .pfm files.

Speed features:
  - Magic byte check in first 64 bytes (instant file identification)
  - Index-based O(1) section access via file seek (true lazy reading)
  - Only the header (magic + meta + index) is read on open
  - Section content is read on demand — never loads the full file into memory

Security features:
  - Content unescaping (reverses writer escaping of #@/#! markers)
  - Strict allowlist for meta field parsing (no arbitrary setattr)
  - File size limits (prevents OOM from crafted files)
  - Index bounds validation (prevents out-of-bounds reads)
"""

from __future__ import annotations

import builtins
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
        # Full parse (loads entire file)
        doc = PFMReader.read("file.pfm")

        # Indexed access (lazy — only reads header on open, seeks for sections)
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
    def parse(cls, data: bytes, max_size: int = MAX_FILE_SIZE) -> PFMDocument:
        """Parse bytes into a PFMDocument."""
        if len(data) > max_size:
            raise ValueError(
                f"Input size {len(data)} exceeds maximum {max_size} bytes. "
                f"Pass max_size= to override."
            )
        text = data.decode("utf-8")
        # Normalize CRLF/CR to LF to handle Windows line endings
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        lines = text.split("\n")

        doc = PFMDocument()
        current_section: str | None = None
        section_lines: list[str] = []
        in_meta = False
        in_index = False
        hit_eof = False

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
                hit_eof = True
                break

            # Section header (only match unescaped — escaped lines start with \#)
            if line.startswith(SECTION_PREFIX):
                # Flush previous section
                skip_sections = ("meta", "index", "index-trailing")
                if current_section and current_section not in skip_sections:
                    content = "\n".join(section_lines)
                    # Unescape content lines
                    content = unescape_content(content)
                    doc.add_section(current_section, content)

                section_name = line[len(SECTION_PREFIX):]
                current_section = section_name
                section_lines = []
                in_meta = section_name == "meta"
                in_index = section_name in ("index", "index-trailing")
                i += 1
                continue

            # Meta key-value pairs (strict allowlist — PFM-002 fix)
            if in_meta:
                if ": " in line:
                    key, val = line.split(": ", 1)
                    key = key.strip()
                    val = val.strip()
                    if key in META_ALLOWLIST:
                        # First-wins: prevent duplicate meta key override
                        # Use explicit dict-style access to avoid setattr risks
                        if not getattr(doc, key, ""):
                            doc.__dict__[key] = val
                    else:
                        # First-wins: only set if key not already present
                        if key not in doc.custom_meta:
                            # PFM-014: Enforce custom meta field count limit
                            if len(doc.custom_meta) >= MAX_META_FIELDS:
                                raise ValueError(
                                    f"Maximum custom meta fields exceeded: {MAX_META_FIELDS}"
                                )
                            doc.custom_meta[key] = val
                i += 1
                continue

            # Index entries (skipped in full parse — index is only used for lazy access)
            if in_index:
                i += 1
                continue

            # Section content (raw — unescaping happens on flush)
            if current_section:
                section_lines.append(line)

            i += 1

        # Flush last section
        if current_section and current_section not in ("meta", "index", "index-trailing"):
            content = "\n".join(section_lines)
            # Strip trailing newline only for unfinalized stream files (no EOF marker).
            # The writer adds \n after content for format correctness. In finalized
            # files, the EOF marker stops accumulation before this padding, so
            # content trailing newlines are preserved. In unfinalized files (crash
            # recovery), the padding \n leaks into the last section's content.
            if not hit_eof and content.endswith("\n"):
                content = content[:-1]
            content = unescape_content(content)
            doc.add_section(current_section, content)

        return doc

    @classmethod
    def open(cls, path: str | Path, max_size: int = MAX_FILE_SIZE) -> PFMReaderHandle:
        """Open a .pfm file for indexed, lazy reading.

        Only reads the header (magic + meta + index) on open.
        Section content is read on demand via file seek — the full file
        is never loaded into memory.

        CRLF safety: If the file contains ``\\r\\n`` line endings (e.g. from
        Git autocrlf on Windows), the reader transparently normalizes the
        data to LF-only so that index byte offsets remain correct.
        """
        path = Path(path)
        file_size = path.stat().st_size
        if file_size > max_size:
            raise ValueError(
                f"File size {file_size} exceeds maximum {max_size} bytes. "
                f"Pass max_size= to override."
            )

        f = builtins_open(path, "rb")
        # Detect CRLF: peek at first 4 KB to check for \r\n
        head = f.read(min(file_size, 4096))
        has_crlf = b"\r\n" in head

        if has_crlf:
            # Normalize entire file to LF in memory so index offsets work
            f.seek(0)
            raw = f.read()
            f.close()
            normalized = raw.replace(b"\r\n", b"\n")
            import io as _io
            f = _io.BytesIO(normalized)
            file_size = len(normalized)

        else:
            f.seek(0)

        reader = PFMReaderHandle(f, file_size)
        reader._parse_header()
        return reader


# Keep builtins reference so 'open' classmethod doesn't shadow
builtins_open = builtins.open


class PFMReaderHandle:
    """
    Handle for indexed, lazy access to a .pfm file.

    Only the header (magic, meta, index) is parsed on open.
    Section content is read on demand via file seek — O(1) per section,
    with no upfront cost proportional to file size.
    """

    def __init__(self, handle: BinaryIO, file_size: int) -> None:
        self._handle = handle
        self._file_size = file_size
        self.meta: dict[str, str] = {}
        self.index: PFMIndex = PFMIndex()
        self.format_version: str = ""

    def _parse_header(self) -> None:
        """Parse only magic, meta, and index by reading line-by-line.

        Stops as soon as the first content section header is encountered.
        Handles both inline index (standard) and trailing index (stream mode).
        """
        self._handle.seek(0)
        current_section: str | None = None
        is_stream = False

        while True:
            line_bytes = self._handle.readline()
            if not line_bytes:
                break
            line = line_bytes.decode("utf-8").rstrip("\n").rstrip("\r")

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
                continue

            if line.startswith(SECTION_PREFIX):
                section_name = line[len(SECTION_PREFIX):]
                current_section = section_name
                # Stop at the first content section — header is fully parsed
                if current_section not in ("meta", "index", "index-trailing"):
                    break
                continue

            if current_section == "meta" and ": " in line:
                key, val = line.split(": ", 1)
                key = key.strip()
                # First-wins: prevent duplicate meta key override (e.g., checksum)
                if key in self.meta:
                    continue
                # Enforce meta field count limit (PFM-014: prevents DoS from crafted files)
                if len(self.meta) >= MAX_META_FIELDS:
                    continue
                self.meta[key] = val.strip()

            if current_section in ("index", "index-trailing"):
                parts = line.strip().split()
                if len(parts) == 3 and parts[0] != "checksum":
                    try:
                        name, offset, length = parts
                        off = int(offset)
                        ln = int(length)
                    except ValueError:
                        continue
                    # PFM-008: Validate index bounds
                    if 0 <= off and off + ln <= self._file_size:
                        self.index.add(name, off, ln)

        # If stream mode and no index found yet, scan from the end
        if is_stream and not self.index.entries:
            self._parse_trailing_index()

    def _parse_trailing_index(self) -> None:
        """Parse trailing index from the end of a stream-mode file.

        Reads backward from EOF to find the index-trailing section.
        """
        # Read the tail of the file (trailing index is typically < 4KB)
        tail_size = min(self._file_size, 64 * 1024)
        self._handle.seek(self._file_size - tail_size)
        tail = self._handle.read(tail_size).decode("utf-8")
        lines = tail.split("\n")

        for line in reversed(lines):
            if line.startswith(EOF_MARKER):
                continue
            if line.startswith(f"{SECTION_PREFIX}index-trailing"):
                break  # Found the start of trailing index, we're done
            if line.strip() == "":
                continue
            parts = line.strip().split()
            if len(parts) == 3 and parts[0] != "checksum":
                try:
                    name, offset, length = parts[0], int(parts[1]), int(parts[2])
                    # PFM-008: Validate bounds
                    if 0 <= offset and offset + length <= self._file_size:
                        self.index.add(name, offset, length)
                except ValueError:
                    continue
            elif len(parts) == 2 and parts[0] == "checksum":
                self.meta["checksum"] = parts[1]

    def _read_raw(self, offset: int, length: int) -> bytes:
        """Seek to offset and read exactly length bytes."""
        self._handle.seek(offset)
        return self._handle.read(length)

    def get_section(self, name: str) -> str | None:
        """O(1) indexed access to a section's content.

        Seeks directly to the byte offset in the file and reads only the
        requested section — no other data is loaded.
        """
        entry = self.index.get(name)
        if entry is None:
            return None
        offset, length = entry
        raw = self._read_raw(offset, length).decode("utf-8")
        # Strip trailing newline that writer adds for format correctness
        if raw.endswith("\n"):
            raw = raw[:-1]
        return unescape_content(raw)

    def get_sections(self, name: str) -> list[str]:
        """Get all sections with the given name."""
        results = []
        for offset, length in self.index.get_all(name):
            raw = self._read_raw(offset, length).decode("utf-8")
            # Strip trailing newline that writer adds for format correctness
            if raw.endswith("\n"):
                raw = raw[:-1]
            results.append(unescape_content(raw))
        return results

    @property
    def section_names(self) -> list[str]:
        return self.index.section_names

    def to_document(self) -> PFMDocument:
        """Convert to full PFMDocument (reads all sections from disk)."""
        self._handle.seek(0)
        data = self._handle.read()
        return PFMReader.parse(data)

    def validate_checksum(self) -> bool:
        """Validate the checksum in meta against actual content.

        PFM-005 fix: Returns False if no checksum is present (fail-closed).
        Reads each section via seek — does not load the full file.
        """
        expected = self.meta.get("checksum", "")
        if not expected:
            return False  # No checksum = not validated

        # Checksum is computed from UNESCAPED section content strings
        # (without trailing newline), matching PFMDocument.compute_checksum().
        # Sort by offset to ensure consistent order regardless of how
        # the index was parsed (trailing index reads in reverse).
        all_entries = []
        for name in self.index.section_names:
            for offset, length in self.index.get_all(name):
                all_entries.append((offset, length))
        all_entries.sort()

        h = hashlib.sha256()
        for offset, length in all_entries:
            chunk = self._read_raw(offset, length)
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
