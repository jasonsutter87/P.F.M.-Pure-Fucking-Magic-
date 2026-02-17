"""
PFM Conformance Tests

Cross-implementation test suite using shared test vectors.
Covers: escape round-trips, write/read round-trips, checksum computation,
adversarial inputs, and edge cases.

These tests ensure Python implementation matches the spec and agrees with
the JS implementations (pfm-js, pfm-chrome, docs/index.html).
"""

import hashlib
import json
import os
import tempfile
from pathlib import Path

import pytest

from pfm.document import PFMDocument
from pfm.reader import PFMReader
from pfm.writer import PFMWriter
from pfm.spec import (
    escape_content_line,
    unescape_content_line,
    escape_content,
    unescape_content,
    MAGIC,
    EOF_MARKER,
    SECTION_PREFIX,
)


VECTORS_PATH = Path(__file__).parent / "conformance" / "vectors.json"

@pytest.fixture(scope="module")
def vectors():
    with open(VECTORS_PATH) as f:
        return json.load(f)


# ================================================================
# Escape Round-Trip Tests
# ================================================================

class TestEscapeRoundTrip:
    """Every escape case must perfectly round-trip: unescape(escape(x)) == x."""

    def test_conformance_vectors(self, vectors):
        for case in vectors["escape_roundtrip"]["cases"]:
            inp = case["input"]
            expected_escaped = case["escaped"]
            desc = case["desc"]

            escaped = escape_content_line(inp)
            assert escaped == expected_escaped, (
                f"[{desc}] escape({inp!r}) = {escaped!r}, expected {expected_escaped!r}"
            )

            unescaped = unescape_content_line(escaped)
            assert unescaped == inp, (
                f"[{desc}] unescape({escaped!r}) = {unescaped!r}, expected {inp!r}"
            )

    def test_multi_roundtrip_stability(self):
        """Escape N times, unescape N times — must return to original."""
        test_cases = ["#@section", "#!PFM/1.0", "#!END", "\\#@marker", "\\\\#@deep"]
        for original in test_cases:
            current = original
            for _ in range(10):
                current = escape_content_line(current)
            for _ in range(10):
                current = unescape_content_line(current)
            assert current == original, f"Multi-roundtrip failed for {original!r}"

    def test_multiline_escape_roundtrip(self):
        """escape_content/unescape_content on multiline strings."""
        content = "normal\n#@section\n\\#@escaped\n#!PFM/1.0\nfinal"
        escaped = escape_content(content)
        unescaped = unescape_content(escaped)
        assert unescaped == content

    def test_no_false_positives(self):
        """Lines that should NOT be escaped remain untouched."""
        safe_lines = [
            "normal line",
            "#hello",           # hash but not #@ or #!PFM/#!END
            "#!other",          # hash-bang but not a PFM marker
            "\\#hello",         # backslash-hash but no marker after
            "\\normal",         # backslash but no hash
            "",                 # empty
            "   #@indented",    # indented — not at line start
        ]
        for line in safe_lines:
            assert escape_content_line(line) == line, f"False positive escape on {line!r}"


# ================================================================
# Write → Read Round-Trip Tests
# ================================================================

class TestWriteReadRoundTrip:
    """Write a document, read it back — content must be byte-for-byte identical."""

    def test_conformance_vectors(self, vectors):
        for case in vectors["parse_serialize_roundtrip"]["cases"]:
            desc = case["desc"]
            doc = PFMDocument.create(agent=case["meta"].get("agent", "test"))
            if "model" in case["meta"]:
                doc.model = case["meta"]["model"]

            for sec in case["sections"]:
                doc.add_section(sec["name"], sec["content"])

            # Serialize and parse back
            data = PFMWriter.serialize(doc)
            restored = PFMReader.parse(data)

            assert len(restored.sections) == len(doc.sections), (
                f"[{desc}] Section count mismatch: {len(restored.sections)} vs {len(doc.sections)}"
            )
            for orig, rest in zip(doc.sections, restored.sections):
                assert rest.name == orig.name, f"[{desc}] Name mismatch: {rest.name!r} vs {orig.name!r}"
                assert rest.content == orig.content, (
                    f"[{desc}] Content mismatch in '{orig.name}': {rest.content!r} vs {orig.content!r}"
                )

    def test_roundtrip_via_file(self):
        """Write to disk, read back — full file I/O round-trip."""
        doc = PFMDocument.create(agent="roundtrip-test", model="test-v1")
        doc.add_section("content", "Hello world\nLine 2")
        doc.add_section("chain", "User: test\nAgent: response")

        with tempfile.NamedTemporaryFile(suffix=".pfm", delete=False) as f:
            path = f.name

        try:
            PFMWriter.write(doc, path)

            # Full parse
            restored = PFMReader.read(path)
            assert restored.content == doc.content
            assert restored.chain == doc.chain
            assert restored.agent == doc.agent

            # Indexed/lazy read
            with PFMReader.open(path) as reader:
                assert reader.get_section("content") == doc.sections[0].content
                assert reader.get_section("chain") == doc.sections[1].content
                assert reader.validate_checksum()
                assert reader.meta["agent"] == "roundtrip-test"
        finally:
            os.unlink(path)

    def test_roundtrip_with_dangerous_content(self):
        """Content containing PFM markers survives write/read."""
        dangerous_content = (
            "Line before markers\n"
            "#@fake-section\n"
            "#!PFM/1.0\n"
            "#!END\n"
            "\\#@already-escaped\n"
            "\\\\#@double-escaped\n"
            "Line after markers"
        )
        doc = PFMDocument.create(agent="test")
        doc.add_section("content", dangerous_content)

        data = PFMWriter.serialize(doc)
        restored = PFMReader.parse(data)
        assert restored.sections[0].content == dangerous_content

    def test_roundtrip_checksum_valid(self):
        """Checksum computed by writer matches on read."""
        doc = PFMDocument.create(agent="test")
        doc.add_section("content", "checksum test data")
        doc.add_section("chain", "more data for checksum")

        with tempfile.NamedTemporaryFile(suffix=".pfm", delete=False) as f:
            path = f.name

        try:
            PFMWriter.write(doc, path)
            with PFMReader.open(path) as reader:
                assert reader.validate_checksum(), "Checksum should be valid after fresh write"
        finally:
            os.unlink(path)


# ================================================================
# Checksum Tests
# ================================================================

class TestChecksum:
    """Verify checksum computation matches expected SHA-256 values."""

    def test_conformance_vectors(self, vectors):
        for case in vectors["checksum"]["cases"]:
            desc = case["desc"]
            doc = PFMDocument.create(agent="test")
            for sec in case["sections"]:
                doc.add_section(sec["name"], sec["content"])
            computed = doc.compute_checksum()
            assert computed == case["expected_checksum"], (
                f"[{desc}] Checksum mismatch: {computed} vs {case['expected_checksum']}"
            )

    def test_checksum_order_dependent(self):
        """Checksum changes if section order changes."""
        doc1 = PFMDocument.create(agent="test")
        doc1.add_section("content", "a")
        doc1.add_section("chain", "b")

        doc2 = PFMDocument.create(agent="test")
        doc2.add_section("chain", "b")
        doc2.add_section("content", "a")

        # Same content, different order → different checksum
        assert doc1.compute_checksum() != doc2.compute_checksum()


# ================================================================
# Lazy Reader Tests
# ================================================================

class TestLazyReader:
    """Verify the indexed reader truly does lazy reads via file seek."""

    def test_indexed_read_matches_full_parse(self):
        """Indexed reader returns same content as full parser."""
        doc = PFMDocument.create(agent="lazy-test", model="v1")
        doc.add_section("content", "Main content here")
        doc.add_section("chain", "User: hello\nAgent: hi")
        doc.add_section("tools", "grep(pattern='test')")

        with tempfile.NamedTemporaryFile(suffix=".pfm", delete=False) as f:
            path = f.name

        try:
            PFMWriter.write(doc, path)

            full = PFMReader.read(path)
            with PFMReader.open(path) as lazy:
                for section in full.sections:
                    lazy_content = lazy.get_section(section.name)
                    assert lazy_content == section.content, (
                        f"Mismatch in '{section.name}': lazy={lazy_content!r} vs full={section.content!r}"
                    )
        finally:
            os.unlink(path)

    def test_section_names_available(self):
        """Index provides section names without reading content."""
        doc = PFMDocument.create(agent="test")
        doc.add_section("content", "x")
        doc.add_section("chain", "y")
        doc.add_section("metrics", "z")

        with tempfile.NamedTemporaryFile(suffix=".pfm", delete=False) as f:
            path = f.name

        try:
            PFMWriter.write(doc, path)
            with PFMReader.open(path) as reader:
                assert set(reader.section_names) == {"content", "chain", "metrics"}
        finally:
            os.unlink(path)

    def test_nonexistent_section_returns_none(self):
        """Requesting a section that doesn't exist returns None."""
        doc = PFMDocument.create(agent="test")
        doc.add_section("content", "exists")

        with tempfile.NamedTemporaryFile(suffix=".pfm", delete=False) as f:
            path = f.name

        try:
            PFMWriter.write(doc, path)
            with PFMReader.open(path) as reader:
                assert reader.get_section("nonexistent") is None
        finally:
            os.unlink(path)

    def test_to_document_reads_all(self):
        """to_document() produces a full PFMDocument from lazy reader."""
        doc = PFMDocument.create(agent="test")
        doc.add_section("content", "hello")
        doc.add_section("chain", "world")

        with tempfile.NamedTemporaryFile(suffix=".pfm", delete=False) as f:
            path = f.name

        try:
            PFMWriter.write(doc, path)
            with PFMReader.open(path) as reader:
                full_doc = reader.to_document()
                assert full_doc.content == "hello"
                assert full_doc.chain == "world"
        finally:
            os.unlink(path)


# ================================================================
# Adversarial Input Tests
# ================================================================

class TestAdversarial:
    """Edge cases and potentially malicious inputs."""

    def test_max_section_name_length(self):
        """Section name at exactly 64 chars is accepted."""
        doc = PFMDocument.create(agent="test")
        name = "a" * 64
        doc.add_section(name, "content")
        data = PFMWriter.serialize(doc)
        restored = PFMReader.parse(data)
        assert restored.sections[0].name == name

    def test_section_name_too_long_rejected(self):
        """Section name over 64 chars is rejected."""
        doc = PFMDocument.create(agent="test")
        with pytest.raises(ValueError, match="too long"):
            doc.add_section("a" * 65, "content")

    def test_empty_document(self):
        """Document with no sections serializes and parses."""
        doc = PFMDocument.create(agent="empty-test")
        data = PFMWriter.serialize(doc)
        restored = PFMReader.parse(data)
        assert len(restored.sections) == 0
        assert restored.agent == "empty-test"

    def test_unicode_in_all_positions(self):
        """Unicode in section content, meta values."""
        doc = PFMDocument.create(agent="テスト", model="模型")
        doc.add_section("content", "日本語テスト 🎌")
        doc.add_section("chain", "Ñoño → résumé")

        data = PFMWriter.serialize(doc)
        restored = PFMReader.parse(data)
        assert restored.sections[0].content == "日本語テスト 🎌"
        assert restored.sections[1].content == "Ñoño → résumé"

    def test_large_content(self):
        """Large section content survives round-trip."""
        big = "x" * 100_000 + "\n" + "y" * 100_000
        doc = PFMDocument.create(agent="test")
        doc.add_section("content", big)

        data = PFMWriter.serialize(doc)
        restored = PFMReader.parse(data)
        assert restored.sections[0].content == big

    def test_many_sections(self):
        """Document with many sections round-trips correctly."""
        doc = PFMDocument.create(agent="test")
        for i in range(100):
            doc.add_section(f"section{i:03d}", f"content-{i}")

        data = PFMWriter.serialize(doc)
        restored = PFMReader.parse(data)
        assert len(restored.sections) == 100
        for i in range(100):
            assert restored.sections[i].content == f"content-{i}"

    def test_content_only_newlines(self):
        """Content that is only newlines — trailing newline consumed by writer/reader protocol."""
        doc = PFMDocument.create(agent="test")
        doc.add_section("content", "\n\n\n")

        data = PFMWriter.serialize(doc)
        restored = PFMReader.parse(data)
        # Writer ensures trailing \n, reader strips one — net loss of one trailing newline
        assert restored.sections[0].content == "\n"

    def test_content_with_trailing_newline(self):
        """Trailing newline consumed by writer/reader protocol."""
        doc = PFMDocument.create(agent="test")
        doc.add_section("content", "hello\n")

        data = PFMWriter.serialize(doc)
        restored = PFMReader.parse(data)
        # Writer sees content already ends with \n (no extra added),
        # reader strips trailing \n → original trailing newline is consumed
        assert restored.sections[0].content == "hello"
