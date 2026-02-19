"""
PFM Writer - Serializes PFMDocument to .pfm format.

Two-pass strategy for speed:
  1. Serialize all sections to bytes (calculate sizes)
  2. Build index with real byte offsets
  3. Assemble final output: magic + meta + index + sections + EOF
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

from pfm.spec import MAGIC, EOF_MARKER, SECTION_PREFIX, FORMAT_VERSION, escape_content

if TYPE_CHECKING:
    from pfm.document import PFMDocument


class PFMWriter:

    @staticmethod
    def serialize(doc: PFMDocument) -> bytes:
        """Serialize a PFMDocument to bytes. Pure — does not mutate the input document."""

        # Compute checksum without mutating doc
        checksum = doc.compute_checksum()

        # --- Pass 1: Pre-serialize sections (with content escaping) ---
        section_blobs: list[tuple[str, bytes]] = []
        for section in doc.sections:
            header_line = f"{SECTION_PREFIX}{section.name}\n".encode("utf-8")
            # Escape content lines that look like PFM markers
            escaped = escape_content(section.content)
            content_bytes = escaped.encode("utf-8")
            # ALWAYS append exactly one newline as a format separator.
            # The reader ALWAYS strips exactly one trailing newline.
            # This preserves content that naturally ends with \n:
            #   "hello"   -> on disk "hello\n"   -> reader strips -> "hello"
            #   "hello\n" -> on disk "hello\n\n" -> reader strips -> "hello\n"
            content_bytes += b"\n"
            section_blobs.append((section.name, header_line + content_bytes))

        # --- Build header (magic + meta) ---
        header = io.BytesIO()

        # Magic line
        header.write(f"{MAGIC}/{doc.format_version}\n".encode("utf-8"))

        # Meta section
        header.write(f"{SECTION_PREFIX}meta\n".encode("utf-8"))
        meta = doc.get_meta_dict()
        # Override checksum with freshly computed value
        meta["checksum"] = checksum
        for key, val in meta.items():
            # Sanitize meta values: strip newlines and control characters
            # to prevent format injection (a newline in a value could create
            # fake section headers or EOF markers)
            safe_key = "".join(c for c in key if c >= " " and c != "\x7f")
            safe_val = "".join(c for c in val if c >= " " and c != "\x7f")
            header.write(f"{safe_key}: {safe_val}\n".encode("utf-8"))

        # --- Pass 2: Calculate offsets and build index ---
        # Index section header
        index_header = f"{SECTION_PREFIX}index\n".encode("utf-8")

        # We need to know the total size of header + index to calculate section offsets.
        # Index entries are: "name offset length\n"
        # Problem: offset depends on index size, index size depends on offset digits.
        # Solution: Iteratively build the index, feeding the previous iteration's
        # index size forward until the size stabilises (digit counts converge).

        header_bytes = header.getvalue()

        # Pre-compute per-section sizes (invariant across iterations)
        entry_info: list[tuple[str, int, int]] = []  # (name, content_len, blob_len)
        for name, blob in section_blobs:
            section_header_len = len(f"{SECTION_PREFIX}{name}\n".encode("utf-8"))
            content_len = len(blob) - section_header_len
            entry_info.append((name, content_len, len(blob)))

        # Seed: start with just the index header (minimum possible index)
        prev_index_bytes = index_header

        for _attempt in range(5):  # Converges in 2-3 iterations
            base_offset = len(header_bytes) + len(prev_index_bytes)
            index_buf = io.BytesIO()
            index_buf.write(index_header)
            running = base_offset
            for name, content_len, blob_len in entry_info:
                section_header_len = len(f"{SECTION_PREFIX}{name}\n".encode("utf-8"))
                content_offset = running + section_header_len
                index_buf.write(f"{name} {content_offset} {content_len}\n".encode("utf-8"))
                running += blob_len

            index_bytes = index_buf.getvalue()

            if len(index_bytes) == len(prev_index_bytes):
                break  # Converged — digit counts are stable
            prev_index_bytes = index_bytes

        # --- Assemble final output ---
        out = io.BytesIO()
        out.write(header_bytes)
        out.write(index_bytes)
        for _, blob in section_blobs:
            out.write(blob)
        out.write(f"{EOF_MARKER}\n".encode("utf-8"))

        return out.getvalue()

    @staticmethod
    def write(doc: PFMDocument, path: str, mode: int = 0o644) -> int:
        """Write a PFMDocument to a file atomically. Returns bytes written.

        Uses write-to-temp-then-rename to prevent corruption if the process
        crashes mid-write. For long-running agent tasks that write sections
        incrementally, use PFMStreamWriter instead — it flushes each section
        to disk with fsync and supports crash recovery.

        PFM-019 fix: Uses explicit file permissions (default 0644).
        For sensitive files, pass mode=0o600.
        """
        import os
        import tempfile
        data = PFMWriter.serialize(doc)
        # Atomic write: write to temp file, then rename over target.
        # This ensures the target file is never partially written.
        dir_name = os.path.dirname(os.path.abspath(path)) or "."
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".pfm.tmp")
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            # On Windows, target must not exist for os.rename
            if os.path.exists(path):
                os.replace(tmp_path, path)
            else:
                os.rename(tmp_path, path)
        except Exception:
            # Clean up temp file on failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        return len(data)
