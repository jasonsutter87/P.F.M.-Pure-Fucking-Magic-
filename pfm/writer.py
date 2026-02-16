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
        """Serialize a PFMDocument to bytes. Fast two-pass assembly."""

        # Compute checksum before serialization
        doc.checksum = doc.compute_checksum()

        # --- Pass 1: Pre-serialize sections (with content escaping) ---
        section_blobs: list[tuple[str, bytes]] = []
        for section in doc.sections:
            header_line = f"{SECTION_PREFIX}{section.name}\n".encode("utf-8")
            # Escape content lines that look like PFM markers
            escaped = escape_content(section.content)
            content_bytes = escaped.encode("utf-8")
            # Ensure content ends with newline
            if not content_bytes.endswith(b"\n"):
                content_bytes += b"\n"
            section_blobs.append((section.name, header_line + content_bytes))

        # --- Build header (magic + meta) ---
        header = io.BytesIO()

        # Magic line
        header.write(f"{MAGIC}/{doc.format_version}\n".encode("utf-8"))

        # Meta section
        header.write(f"{SECTION_PREFIX}meta\n".encode("utf-8"))
        meta = doc.get_meta_dict()
        for key, val in meta.items():
            header.write(f"{key}: {val}\n".encode("utf-8"))

        # --- Pass 2: Calculate offsets and build index ---
        # Index section header
        index_header = f"{SECTION_PREFIX}index\n".encode("utf-8")

        # We need to know the total size of header + index to calculate section offsets.
        # Index entries are: "name offset length\n"
        # Problem: offset depends on index size, index size depends on offset digits.
        # Solution: Calculate with estimated offsets, then recalculate if digit count changes.

        header_bytes = header.getvalue()

        # First estimate: calculate index entries with placeholder offsets
        for _attempt in range(3):  # Max 3 iterations (converges fast)
            index_buf = io.BytesIO()
            index_buf.write(index_header)

            # Current position after header + index
            # We need to figure out index size first
            estimated_entries = []
            cursor = 0  # Will be set after we know index size
            for name, blob in section_blobs:
                content_start = len(f"{SECTION_PREFIX}{name}\n".encode("utf-8"))
                content_len = len(blob) - content_start
                estimated_entries.append((name, cursor, content_len, len(blob)))
                cursor += len(blob)

            # Build index string to measure it
            test_index = io.BytesIO()
            test_index.write(index_header)
            base_offset = len(header_bytes) + 0  # placeholder
            running = base_offset
            for name, _, content_len, blob_len in estimated_entries:
                # Offset points to content start (after section header line)
                section_header_len = len(f"{SECTION_PREFIX}{name}\n".encode("utf-8"))
                content_offset = running + section_header_len
                test_index.write(f"{name} {content_offset} {content_len}\n".encode("utf-8"))
                running += blob_len

            test_index_bytes = test_index.getvalue()
            actual_base = len(header_bytes) + len(test_index_bytes)

            # Recalculate with actual base
            index_buf = io.BytesIO()
            index_buf.write(index_header)
            running = actual_base
            final_entries = []
            for name, _, content_len, blob_len in estimated_entries:
                section_header_len = len(f"{SECTION_PREFIX}{name}\n".encode("utf-8"))
                content_offset = running + section_header_len
                entry_line = f"{name} {content_offset} {content_len}\n"
                index_buf.write(entry_line.encode("utf-8"))
                final_entries.append((name, content_offset, content_len))
                running += blob_len

            index_bytes = index_buf.getvalue()

            # Check if our size estimate was right
            if len(index_bytes) == len(test_index_bytes):
                break  # Converged
            # Otherwise loop with corrected sizes

        # Update section objects with computed offsets
        for i, (name, offset, length) in enumerate(final_entries):
            doc.sections[i].offset = offset
            doc.sections[i].length = length

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
        """Write a PFMDocument to a file. Returns bytes written.

        PFM-019 fix: Uses explicit file permissions (default 0644).
        For sensitive files, pass mode=0o600.
        """
        import os
        data = PFMWriter.serialize(doc)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(data)
        except Exception:
            # fd is consumed by fdopen even on error
            raise
        return len(data)
