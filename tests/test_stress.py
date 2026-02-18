"""
PFM Stress Tests
================
Battle-test the format with real files, large payloads, format conversions,
edge cases, and benchmarks.

Run:
    python -m pytest tests/test_stress.py -v --tb=short
    python tests/test_stress.py          # standalone mode with benchmarks
"""

from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import time
from pathlib import Path

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

from pfm.document import PFMDocument, PFMSection
from pfm.writer import PFMWriter
from pfm.reader import PFMReader, PFMReaderHandle
from pfm.spec import (
    MAGIC, EOF_MARKER, SECTION_PREFIX, MAX_SECTIONS,
    escape_content, unescape_content,
)
from pfm import converters


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
DOWNLOADS = Path.home() / "Downloads"
EXAMPLES = Path(__file__).parent.parent / "examples"

ILIAD_TXT = DOWNLOADS / "The Iliad.txt"
ILIAD_PFM = DOWNLOADS / "The Iliad.pfm"
CHATGPT_PFM = DOWNLOADS / "ChatGPT Conversation on pfm.pfm"
GEMINI_PFM = DOWNLOADS / "Gemini Conversation.pfm"
HELLO_PFM = EXAMPLES / "hello.pfm"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _timer():
    """Simple context-manager stopwatch."""
    class Timer:
        def __init__(self):
            self.elapsed = 0.0
        def __enter__(self):
            self._start = time.perf_counter()
            return self
        def __exit__(self, *_):
            self.elapsed = time.perf_counter() - self._start
    return Timer()


def _write_temp(doc: PFMDocument) -> tuple[Path, int]:
    """Write doc to a temp file, return (path, nbytes)."""
    with tempfile.NamedTemporaryFile(suffix=".pfm", delete=False) as f:
        path = Path(f.name)
    nbytes = PFMWriter.write(doc, str(path))
    return path, nbytes


def _report(label: str, elapsed: float, size: int = 0):
    mb = size / (1024 * 1024) if size else 0
    rate = f" ({mb / elapsed:.1f} MB/s)" if size and elapsed > 0 else ""
    print(f"  {label}: {elapsed*1000:.1f} ms{rate}")


# ===================================================================
# 1. REAL FILE TESTS
# ===================================================================

class TestRealFiles:
    """Parse and validate every real .pfm file we have."""

    def _validate_pfm(self, path: Path):
        """Full validation of a .pfm file."""
        assert path.exists(), f"File not found: {path}"
        size = path.stat().st_size

        # Full parse
        doc = PFMReader.read(str(path))
        assert doc.id, "Missing document ID"
        assert len(doc.sections) > 0, "No sections"

        # Checksum validation
        assert doc.validate_checksum(), f"Checksum mismatch in {path.name}"

        # Indexed access
        with PFMReader.open(str(path)) as reader:
            assert len(reader.section_names) > 0
            for name in reader.section_names:
                content = reader.get_section(name)
                assert content is not None, f"Index lookup failed for {name}"
            assert reader.validate_checksum()

        # Round-trip: serialize and re-parse
        data = PFMWriter.serialize(doc)
        doc2 = PFMReader.parse(data)
        assert len(doc2.sections) == len(doc.sections)
        for s1, s2 in zip(doc.sections, doc2.sections):
            assert s1.name == s2.name
            assert s1.content == s2.content, (
                f"Content mismatch in section '{s1.name}': "
                f"{len(s1.content)} vs {len(s2.content)} chars"
            )

        return doc, size

    def test_hello_pfm(self):
        if not HELLO_PFM.exists():
            return
        doc, size = self._validate_pfm(HELLO_PFM)
        assert doc.agent == "claude-code"
        assert len(doc.sections) == 4
        print(f"  hello.pfm: {size} bytes, {len(doc.sections)} sections OK")

    def test_chatgpt_conversation(self):
        if not CHATGPT_PFM.exists():
            return
        doc, size = self._validate_pfm(CHATGPT_PFM)
        print(f"  ChatGPT conversation: {size:,} bytes, {len(doc.sections)} sections OK")

    def test_gemini_conversation(self):
        if not GEMINI_PFM.exists():
            return
        doc, size = self._validate_pfm(GEMINI_PFM)
        print(f"  Gemini conversation: {size:,} bytes, {len(doc.sections)} sections OK")

    def test_iliad_pfm(self):
        if not ILIAD_PFM.exists():
            return
        doc, size = self._validate_pfm(ILIAD_PFM)
        total_content = sum(len(s.content) for s in doc.sections)
        print(f"  The Iliad.pfm: {size:,} bytes, {len(doc.sections)} sections, "
              f"{total_content:,} chars content OK")


# ===================================================================
# 2. LARGE FILE STRESS TESTS
# ===================================================================

class TestLargeFiles:
    """Stress-test with The Iliad and synthetic large payloads."""

    def test_iliad_txt_to_pfm_roundtrip(self):
        """Ingest The Iliad as text, serialize, re-parse, verify content."""
        if not ILIAD_TXT.exists():
            return

        text = ILIAD_TXT.read_text(encoding="utf-8", errors="replace")
        assert len(text) > 1_000_000, "Iliad should be 1MB+"

        doc = PFMDocument.create(agent="stress-test", model="iliad-test")
        doc.add_section("content", text)

        # Serialize
        with _timer() as t:
            data = PFMWriter.serialize(doc)
        _report("Serialize Iliad", t.elapsed, len(data))

        # Parse
        with _timer() as t:
            doc2 = PFMReader.parse(data)
        _report("Parse Iliad", t.elapsed, len(data))

        assert doc2.content == text, "Content mismatch after round-trip!"
        assert doc2.validate_checksum(), "Checksum mismatch!"
        print(f"  Round-trip OK: {len(text):,} chars, {len(data):,} bytes")

    def test_iliad_indexed_access(self):
        """Verify O(1) indexed access on a large file."""
        if not ILIAD_TXT.exists():
            return

        text = ILIAD_TXT.read_text(encoding="utf-8", errors="replace")
        doc = PFMDocument.create(agent="stress-test")
        doc.add_section("content", text)
        doc.add_section("metadata", "This is the metadata section")

        path, nbytes = _write_temp(doc)
        try:
            with PFMReader.open(str(path)) as reader:
                # Indexed read of small section should be fast
                with _timer() as t:
                    meta = reader.get_section("metadata")
                _report("Index seek (small section)", t.elapsed)
                assert meta == "This is the metadata section"

                # Indexed read of large section
                with _timer() as t:
                    content = reader.get_section("content")
                _report("Index seek (Iliad)", t.elapsed, len(content.encode()))
                assert content == text

                assert reader.validate_checksum()
        finally:
            path.unlink()

    def test_synthetic_5mb(self):
        """Generate a 5MB payload and round-trip it."""
        payload = "The quick brown fox jumps over the lazy dog.\n" * 120_000  # ~5.4MB
        doc = PFMDocument.create(agent="stress-test")
        doc.add_section("content", payload)

        with _timer() as t:
            data = PFMWriter.serialize(doc)
        _report("Serialize 5MB", t.elapsed, len(data))

        with _timer() as t:
            doc2 = PFMReader.parse(data)
        _report("Parse 5MB", t.elapsed, len(data))

        assert doc2.content == payload
        assert doc2.validate_checksum()
        print(f"  5MB synthetic: {len(data):,} bytes OK")

    def test_synthetic_50mb(self):
        """Push toward the 100MB limit with a 50MB file."""
        payload = "ABCDEFGHIJ" * 5_000_000  # 50MB
        doc = PFMDocument.create(agent="stress-test")
        doc.add_section("content", payload)

        with _timer() as t:
            data = PFMWriter.serialize(doc)
        _report("Serialize 50MB", t.elapsed, len(data))

        with _timer() as t:
            doc2 = PFMReader.parse(data)
        _report("Parse 50MB", t.elapsed, len(data))

        assert doc2.content == payload
        assert doc2.validate_checksum()
        print(f"  50MB synthetic: {len(data):,} bytes OK")


# ===================================================================
# 3. MANY SECTIONS STRESS
# ===================================================================

class TestManySections:
    """Test with large numbers of sections."""

    def test_100_sections(self):
        doc = PFMDocument.create(agent="stress-test")
        for i in range(100):
            doc.add_section(f"section-{i:04d}", f"Content for section {i}\n" * 10)

        data = PFMWriter.serialize(doc)
        doc2 = PFMReader.parse(data)
        assert len(doc2.sections) == 100
        assert doc2.validate_checksum()

        # Indexed access
        path, _ = _write_temp(doc)
        try:
            with PFMReader.open(str(path)) as reader:
                assert len(reader.section_names) == 100
                # Spot check
                s50 = reader.get_section("section-0050")
                assert "Content for section 50" in s50
                assert reader.validate_checksum()
        finally:
            path.unlink()
        print(f"  100 sections: {len(data):,} bytes OK")

    def test_1000_sections(self):
        doc = PFMDocument.create(agent="stress-test")
        for i in range(1000):
            doc.add_section(f"s-{i:04d}", f"Data {i}")

        with _timer() as t:
            data = PFMWriter.serialize(doc)
        _report("Serialize 1000 sections", t.elapsed, len(data))

        with _timer() as t:
            doc2 = PFMReader.parse(data)
        _report("Parse 1000 sections", t.elapsed, len(data))

        assert len(doc2.sections) == 1000
        assert doc2.validate_checksum()
        print(f"  1000 sections: {len(data):,} bytes OK")

    def test_iliad_split_into_books(self):
        """Split The Iliad into ~24 'book' sections by paragraph breaks."""
        if not ILIAD_TXT.exists():
            return

        text = ILIAD_TXT.read_text(encoding="utf-8", errors="replace")
        # Split into chunks of ~50KB
        chunk_size = 50_000
        chunks = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]

        doc = PFMDocument.create(agent="stress-test", model="iliad-split")
        for i, chunk in enumerate(chunks):
            doc.add_section(f"book-{i+1:02d}", chunk)

        with _timer() as t:
            data = PFMWriter.serialize(doc)
        _report(f"Serialize Iliad in {len(chunks)} books", t.elapsed, len(data))

        doc2 = PFMReader.parse(data)
        assert len(doc2.sections) == len(chunks)
        assert doc2.validate_checksum()

        # Verify each chunk survived
        for i, chunk in enumerate(chunks):
            section = doc2.sections[i]
            assert section.content == chunk, f"Book {i+1} content mismatch"

        print(f"  Iliad split: {len(chunks)} books, {len(data):,} bytes OK")


# ===================================================================
# 4. FORMAT CONVERSION BATTLE
# ===================================================================

class TestFormatBattle:
    """Round-trip through every format. PFM vs TXT vs MD vs JSON vs CSV."""

    def _make_doc(self, content: str = "") -> PFMDocument:
        doc = PFMDocument.create(agent="format-battle", model="stress-v1")
        doc.add_section("content", content or "Default test content")
        doc.add_section("chain", "User: test\nAgent: response")
        return doc

    def test_json_roundtrip(self):
        doc = self._make_doc("JSON battle content")
        json_str = converters.to_json(doc)
        doc2 = converters.from_json(json_str)
        assert doc2.content == "JSON battle content"
        assert doc2.chain == "User: test\nAgent: response"
        print(f"  JSON round-trip: {len(json_str):,} chars OK")

    def test_csv_roundtrip(self):
        doc = self._make_doc("CSV battle content")
        csv_str = converters.to_csv(doc)
        doc2 = converters.from_csv(csv_str)
        assert doc2.content == "CSV battle content"
        print(f"  CSV round-trip: {len(csv_str):,} chars OK")

    def test_markdown_roundtrip(self):
        doc = self._make_doc("Markdown battle content")
        md_str = converters.to_markdown(doc)
        doc2 = converters.from_markdown(md_str)
        s = doc2.get_section("content")
        assert s and s.content == "Markdown battle content"
        print(f"  Markdown round-trip: {len(md_str):,} chars OK")

    def test_txt_roundtrip(self):
        doc = self._make_doc("TXT battle content")
        txt = converters.to_txt(doc)
        # TXT is lossy (no structured round-trip), just verify content present
        assert "TXT battle content" in txt
        print(f"  TXT output: {len(txt):,} chars OK")

    def test_iliad_through_all_formats(self):
        """The Iliad through PFM -> JSON -> PFM -> CSV -> PFM -> MD -> PFM."""
        if not ILIAD_TXT.exists():
            return

        text = ILIAD_TXT.read_text(encoding="utf-8", errors="replace")
        original = PFMDocument.create(agent="format-battle", model="iliad")
        original.add_section("content", text)

        # PFM -> JSON -> PFM
        with _timer() as t:
            json_str = converters.to_json(original)
        _report("Iliad to JSON", t.elapsed, len(json_str.encode()))
        with _timer() as t:
            from_json = converters.from_json(json_str)
        _report("Iliad from JSON", t.elapsed)
        assert from_json.content == text, "JSON round-trip corrupted content!"

        # PFM -> CSV -> PFM
        with _timer() as t:
            csv_str = converters.to_csv(original)
        _report("Iliad to CSV", t.elapsed, len(csv_str.encode()))
        with _timer() as t:
            from_csv = converters.from_csv(csv_str)
        _report("Iliad from CSV", t.elapsed)
        assert from_csv.content == text, "CSV round-trip corrupted content!"

        # PFM -> Markdown -> PFM
        with _timer() as t:
            md_str = converters.to_markdown(original)
        _report("Iliad to Markdown", t.elapsed, len(md_str.encode()))
        with _timer() as t:
            from_md = converters.from_markdown(md_str)
        _report("Iliad from Markdown", t.elapsed)
        s = from_md.get_section("content")
        assert s and s.content == text, "Markdown round-trip corrupted content!"

        print(f"  Iliad format battle: all 3 formats survived {len(text):,} chars!")

    def test_chain_format_gauntlet(self):
        """Chain: PFM -> JSON -> PFM -> MD -> PFM -> CSV -> PFM -> bytes -> PFM."""
        doc = self._make_doc("Gauntlet starter content\nWith multiple\nlines!")

        # JSON
        j = converters.to_json(doc)
        doc = converters.from_json(j)
        assert "Gauntlet starter" in doc.content

        # Markdown
        m = converters.to_markdown(doc)
        doc = converters.from_markdown(m)
        s = doc.get_section("content")
        assert s and "Gauntlet starter" in s.content

        # CSV
        c = converters.to_csv(doc)
        doc = converters.from_csv(c)
        assert "Gauntlet starter" in doc.content

        # Binary round-trip
        data = PFMWriter.serialize(doc)
        doc = PFMReader.parse(data)
        assert "Gauntlet starter" in doc.content
        assert doc.validate_checksum()

        print(f"  Format gauntlet: survived 4 conversions OK")


# ===================================================================
# 5. CONTENT ESCAPING EDGE CASES
# ===================================================================

class TestEscapingStress:
    """Hammer the content escaping with adversarial content."""

    def test_pfm_markers_in_content(self):
        """Content that looks like PFM markers."""
        evil_content = (
            "Normal line\n"
            "#!PFM/1.0\n"
            "#@meta\n"
            "#@content\n"
            "#!END\n"
            "Normal again\n"
            "#!PFM/2.0\n"
            "\\#@fake\n"
            "\\\\#!END"
        )
        doc = PFMDocument.create(agent="escape-test")
        doc.add_section("content", evil_content)

        data = PFMWriter.serialize(doc)
        doc2 = PFMReader.parse(data)
        assert doc2.content == evil_content, (
            f"Escaping failed!\nExpected:\n{evil_content!r}\nGot:\n{doc2.content!r}"
        )
        assert doc2.validate_checksum()
        print(f"  PFM markers in content: survived OK")

    def test_nested_backslashes(self):
        """Multiple levels of backslash nesting before markers."""
        lines = []
        for depth in range(10):
            prefix = "\\" * depth
            lines.append(f"{prefix}#@section")
            lines.append(f"{prefix}#!PFM/1.0")
            lines.append(f"{prefix}#!END")
        content = "\n".join(lines)

        doc = PFMDocument.create(agent="escape-test")
        doc.add_section("content", content)

        data = PFMWriter.serialize(doc)
        doc2 = PFMReader.parse(data)
        assert doc2.content == content
        assert doc2.validate_checksum()
        print(f"  Nested backslash escaping: {len(lines)} lines survived OK")

    def test_unicode_stress(self):
        """Unicode edge cases: emoji, CJK, RTL, zero-width chars."""
        content = (
            "English text\n"
            "Emoji: \U0001F525\U0001F4A5\U0001F680\U0001F47E\n"
            "CJK: \u4f60\u597d\u4e16\u754c\n"
            "Arabic: \u0645\u0631\u062d\u0628\u0627\n"
            "Russian: \u041f\u0440\u0438\u0432\u0435\u0442\n"
            "Math: \u222b\u2202\u2207\u221e\n"
            "Zero-width: a\u200bb\u200cc\u200dd\ufeffe\n"
            "Combining: e\u0301 n\u0303 o\u0308\n"
        )
        doc = PFMDocument.create(agent="unicode-test")
        doc.add_section("content", content)

        data = PFMWriter.serialize(doc)
        doc2 = PFMReader.parse(data)
        assert doc2.content == content
        assert doc2.validate_checksum()
        print(f"  Unicode stress: {len(content)} chars survived OK")

    def test_very_long_lines(self):
        """Single lines that are extremely long (no newlines)."""
        long_line = "X" * 1_000_000  # 1M chars, no newline
        doc = PFMDocument.create(agent="long-line-test")
        doc.add_section("content", long_line)

        data = PFMWriter.serialize(doc)
        doc2 = PFMReader.parse(data)
        assert doc2.content == long_line
        assert doc2.validate_checksum()
        print(f"  1M char single line: OK")

    def test_empty_content(self):
        """Empty section content."""
        doc = PFMDocument.create(agent="empty-test")
        doc.add_section("content", "")

        data = PFMWriter.serialize(doc)
        doc2 = PFMReader.parse(data)
        assert doc2.content == ""
        assert doc2.validate_checksum()
        print(f"  Empty content: OK")

    def test_only_newlines(self):
        """Content that is nothing but newlines."""
        content = "\n" * 1000
        doc = PFMDocument.create(agent="newline-test")
        doc.add_section("content", content)

        data = PFMWriter.serialize(doc)
        doc2 = PFMReader.parse(data)
        assert doc2.content == content
        assert doc2.validate_checksum()
        print(f"  1000 newlines: OK")


# ===================================================================
# 6. INDEX ACCURACY STRESS
# ===================================================================

class TestIndexAccuracy:
    """Verify byte offsets are correct under various conditions."""

    def test_index_with_multibyte_utf8(self):
        """Index offsets must account for multi-byte UTF-8 characters."""
        doc = PFMDocument.create(agent="index-test")
        # 3-byte UTF-8 chars
        doc.add_section("cjk", "\u4f60\u597d" * 500)
        # 4-byte UTF-8 chars (emoji)
        doc.add_section("emoji", "\U0001F525" * 500)
        # ASCII
        doc.add_section("ascii", "hello" * 500)

        path, nbytes = _write_temp(doc)
        try:
            with PFMReader.open(str(path)) as reader:
                cjk = reader.get_section("cjk")
                assert cjk == "\u4f60\u597d" * 500
                emoji = reader.get_section("emoji")
                assert emoji == "\U0001F525" * 500
                ascii_ = reader.get_section("ascii")
                assert ascii_ == "hello" * 500
                assert reader.validate_checksum()
        finally:
            path.unlink()
        print(f"  Multi-byte UTF-8 index: OK")

    def test_index_with_escaped_content(self):
        """Index offsets must account for escape characters added by writer."""
        doc = PFMDocument.create(agent="index-test")
        # Content with lines that need escaping (adds backslash prefix)
        evil = "#@fake-section\n#!PFM/1.0\n#!END\nnormal line"
        doc.add_section("evil", evil)
        doc.add_section("after", "This section comes after the escaped one")

        path, nbytes = _write_temp(doc)
        try:
            with PFMReader.open(str(path)) as reader:
                evil_back = reader.get_section("evil")
                assert evil_back == evil, f"Expected:\n{evil!r}\nGot:\n{evil_back!r}"
                after = reader.get_section("after")
                assert after == "This section comes after the escaped one"
                assert reader.validate_checksum()
        finally:
            path.unlink()
        print(f"  Escaped content index: OK")

    def test_index_with_many_sections(self):
        """Index with 500 sections, verify random access."""
        doc = PFMDocument.create(agent="index-test")
        expected = {}
        for i in range(500):
            content = f"Section {i} content: {'x' * (i * 10)}"
            name = f"sec-{i:04d}"
            doc.add_section(name, content)
            expected[name] = content

        path, nbytes = _write_temp(doc)
        try:
            with PFMReader.open(str(path)) as reader:
                # Random access
                for name in ["sec-0000", "sec-0250", "sec-0499", "sec-0100", "sec-0375"]:
                    content = reader.get_section(name)
                    assert content == expected[name], f"Index mismatch for {name}"
                assert reader.validate_checksum()
        finally:
            path.unlink()
        print(f"  500-section random access: OK")


# ===================================================================
# 7. BENCHMARKS
# ===================================================================

def run_benchmarks():
    """Run all benchmarks and print a summary table."""
    print("\n" + "=" * 70)
    print("PFM STRESS TEST & BENCHMARK SUITE")
    print("=" * 70)

    results = []

    # --- hello.pfm ---
    if HELLO_PFM.exists():
        print(f"\n--- hello.pfm ({HELLO_PFM.stat().st_size:,} bytes) ---")
        data = HELLO_PFM.read_bytes()
        with _timer() as t:
            doc = PFMReader.parse(data)
        _report("Parse", t.elapsed, len(data))
        with _timer() as t:
            out = PFMWriter.serialize(doc)
        _report("Serialize", t.elapsed, len(out))
        results.append(("hello.pfm", len(data), t.elapsed))

    # --- ChatGPT conversation ---
    if CHATGPT_PFM.exists():
        print(f"\n--- ChatGPT conversation ({CHATGPT_PFM.stat().st_size:,} bytes) ---")
        data = CHATGPT_PFM.read_bytes()
        with _timer() as t:
            doc = PFMReader.parse(data)
        _report("Parse", t.elapsed, len(data))
        with _timer() as t:
            out = PFMWriter.serialize(doc)
        _report("Serialize", t.elapsed, len(out))
        results.append(("ChatGPT.pfm", len(data), t.elapsed))

    # --- The Iliad ---
    if ILIAD_TXT.exists():
        print(f"\n--- The Iliad ({ILIAD_TXT.stat().st_size:,} bytes) ---")
        text = ILIAD_TXT.read_text(encoding="utf-8", errors="replace")

        doc = PFMDocument.create(agent="benchmark")
        doc.add_section("content", text)

        with _timer() as t:
            data = PFMWriter.serialize(doc)
        _report("Serialize", t.elapsed, len(data))

        with _timer() as t:
            doc2 = PFMReader.parse(data)
        _report("Parse", t.elapsed, len(data))

        # Write to temp file for indexed access benchmark
        path, _ = _write_temp(doc)
        with PFMReader.open(str(path)) as reader:
            with _timer() as t:
                content = reader.get_section("content")
            _report("Indexed seek+read", t.elapsed, len(content.encode()))
        path.unlink()

        # Format conversions
        with _timer() as t:
            j = converters.to_json(doc)
        _report("To JSON", t.elapsed, len(j.encode()))
        with _timer() as t:
            converters.from_json(j)
        _report("From JSON", t.elapsed)

        with _timer() as t:
            c = converters.to_csv(doc)
        _report("To CSV", t.elapsed, len(c.encode()))

        with _timer() as t:
            m = converters.to_markdown(doc)
        _report("To Markdown", t.elapsed, len(m.encode()))

        results.append(("Iliad", len(data), t.elapsed))

    # --- Synthetic 10MB ---
    print(f"\n--- Synthetic 10MB ---")
    payload = "The quick brown fox jumps over the lazy dog.\n" * 230_000
    doc = PFMDocument.create(agent="benchmark")
    doc.add_section("content", payload)

    with _timer() as t:
        data = PFMWriter.serialize(doc)
    _report("Serialize", t.elapsed, len(data))

    with _timer() as t:
        PFMReader.parse(data)
    _report("Parse", t.elapsed, len(data))
    results.append(("10MB synthetic", len(data), t.elapsed))

    # --- Summary ---
    print(f"\n{'='*70}")
    print(f"{'Test':<25} {'Size':>12} {'Serialize':>12} {'Parse':>12}")
    print(f"{'-'*25} {'-'*12} {'-'*12} {'-'*12}")

    for label, size, elapsed in results:
        size_str = f"{size:,}"
        ms = f"{elapsed*1000:.1f} ms"
        print(f"{label:<25} {size_str:>12} {'':>12} {ms:>12}")

    print(f"{'='*70}")


# ===================================================================
# Standalone runner
# ===================================================================

if __name__ == "__main__":
    import traceback

    test_classes = [
        TestRealFiles,
        TestLargeFiles,
        TestManySections,
        TestFormatBattle,
        TestEscapingStress,
        TestIndexAccuracy,
    ]

    passed = 0
    failed = 0
    skipped = 0

    for cls in test_classes:
        print(f"\n{'='*60}")
        print(f"  {cls.__name__}")
        print(f"{'='*60}")

        instance = cls()
        for name in sorted(dir(instance)):
            if not name.startswith("test_"):
                continue
            try:
                getattr(instance, name)()
                passed += 1
            except AssertionError as e:
                print(f"  FAIL {name}: {e}")
                traceback.print_exc()
                failed += 1
            except Exception as e:
                print(f"  ERROR {name}: {e}")
                traceback.print_exc()
                failed += 1

    # Benchmarks
    run_benchmarks()

    # Final score
    print(f"\n{'='*60}")
    total = passed + failed
    print(f"  RESULTS: {passed}/{total} passed, {failed} failed")
    if failed == 0:
        print(f"  ALL TESTS PASSED")
    print(f"{'='*60}")

    sys.exit(1 if failed else 0)
