"""
Functional Tests - Test writer, reader, and converters working together.
"""

import hashlib
import tempfile
from pathlib import Path

import pytest

from pfm.document import PFMDocument
from pfm.writer import PFMWriter
from pfm.reader import PFMReader, PFMReaderHandle
from pfm.spec import MAGIC, EOF_MARKER, SECTION_PREFIX
from pfm import converters


# =============================================================================
# Writer
# =============================================================================

class TestWriter:

    def test_serialize_basic(self):
        doc = PFMDocument.create(agent="test", model="test-model")
        doc.add_section("content", "Hello PFM!")

        data = PFMWriter.serialize(doc)
        text = data.decode("utf-8")

        assert text.startswith("#!PFM/1.0\n")
        assert text.endswith("#!END\n")
        assert "#@meta\n" in text
        assert "#@index\n" in text
        assert "#@content\n" in text
        assert "Hello PFM!" in text
        assert "agent: test\n" in text
        assert "model: test-model\n" in text

    def test_serialize_multiple_sections(self):
        doc = PFMDocument.create(agent="test")
        doc.add_section("content", "main output")
        doc.add_section("chain", "User: hello\nAgent: hi")
        doc.add_section("tools", "tool_call: search")

        data = PFMWriter.serialize(doc)
        text = data.decode("utf-8")

        assert "#@content\n" in text
        assert "#@chain\n" in text
        assert "#@tools\n" in text
        assert "main output" in text
        assert "User: hello" in text

    def test_serialize_sets_checksum(self):
        doc = PFMDocument.create(agent="test")
        doc.add_section("content", "data")

        PFMWriter.serialize(doc)
        assert doc.checksum == doc.compute_checksum()

    def test_write_to_file(self):
        doc = PFMDocument.create(agent="test")
        doc.add_section("content", "file content")

        with tempfile.NamedTemporaryFile(suffix=".pfm", delete=False) as f:
            path = f.name

        nbytes = PFMWriter.write(doc, path)
        assert nbytes > 0
        assert Path(path).exists()
        assert Path(path).stat().st_size == nbytes
        Path(path).unlink()

    def test_index_byte_offsets_are_correct(self):
        """Critical: verify that index byte offsets actually point to the right content."""
        doc = PFMDocument.create(agent="test")
        doc.add_section("content", "CONTENT_MARKER_12345")
        doc.add_section("chain", "CHAIN_MARKER_67890")

        data = PFMWriter.serialize(doc)

        # Find index entries
        text = data.decode("utf-8")
        for line in text.split("\n"):
            parts = line.strip().split()
            if len(parts) == 3 and parts[0] == "content":
                offset = int(parts[1])
                length = int(parts[2])
                chunk = data[offset:offset + length].decode("utf-8")
                assert "CONTENT_MARKER_12345" in chunk

            if len(parts) == 3 and parts[0] == "chain":
                offset = int(parts[1])
                length = int(parts[2])
                chunk = data[offset:offset + length].decode("utf-8")
                assert "CHAIN_MARKER_67890" in chunk


# =============================================================================
# Reader
# =============================================================================

class TestReader:

    def _make_pfm(self, **kwargs) -> bytes:
        doc = PFMDocument.create(agent="test", model="test-model")
        doc.add_section("content", kwargs.get("content", "hello"))
        if "chain" in kwargs:
            doc.add_section("chain", kwargs["chain"])
        return PFMWriter.serialize(doc)

    def test_is_pfm_bytes(self):
        data = self._make_pfm()
        assert PFMReader.is_pfm_bytes(data)
        assert not PFMReader.is_pfm_bytes(b"not a pfm file")
        assert not PFMReader.is_pfm_bytes(b"")

    def test_parse_basic(self):
        data = self._make_pfm(content="hello world")
        doc = PFMReader.parse(data)

        assert doc.agent == "test"
        assert doc.model == "test-model"
        assert doc.content == "hello world"
        assert doc.id  # Should have UUID

    def test_parse_multiple_sections(self):
        data = self._make_pfm(content="output", chain="prompt history")
        doc = PFMReader.parse(data)

        assert doc.content == "output"
        assert doc.chain == "prompt history"
        assert len(doc.sections) == 2

    def test_parse_multiline_content(self):
        multiline = "line 1\nline 2\nline 3"
        data = self._make_pfm(content=multiline)
        doc = PFMReader.parse(data)

        assert doc.content == multiline

    def test_is_pfm_file(self):
        data = self._make_pfm()
        with tempfile.NamedTemporaryFile(suffix=".pfm", delete=False) as f:
            f.write(data)
            path = f.name

        assert PFMReader.is_pfm(path)
        Path(path).unlink()

    def test_read_file(self):
        doc = PFMDocument.create(agent="file-test")
        doc.add_section("content", "from file")

        with tempfile.NamedTemporaryFile(suffix=".pfm", delete=False) as f:
            path = f.name

        doc.write(path)
        loaded = PFMReader.read(path)

        assert loaded.agent == "file-test"
        assert loaded.content == "from file"
        Path(path).unlink()


# =============================================================================
# Reader Handle (indexed access)
# =============================================================================

class TestReaderHandle:

    def test_open_and_read_section(self):
        doc = PFMDocument.create(agent="handle-test")
        doc.add_section("content", "indexed content")
        doc.add_section("chain", "indexed chain")

        with tempfile.NamedTemporaryFile(suffix=".pfm", delete=False) as f:
            path = f.name

        doc.write(path)

        with PFMReader.open(path) as reader:
            assert reader.meta["agent"] == "handle-test"
            assert "content" in reader.section_names
            assert "chain" in reader.section_names

            content = reader.get_section("content")
            assert "indexed content" in content

            chain = reader.get_section("chain")
            assert "indexed chain" in chain

        Path(path).unlink()

    def test_get_nonexistent_section(self):
        doc = PFMDocument.create()
        doc.add_section("content", "x")

        with tempfile.NamedTemporaryFile(suffix=".pfm", delete=False) as f:
            path = f.name

        doc.write(path)

        with PFMReader.open(path) as reader:
            assert reader.get_section("nonexistent") is None

        Path(path).unlink()

    def test_validate_checksum(self):
        doc = PFMDocument.create()
        doc.add_section("content", "checksum test")

        with tempfile.NamedTemporaryFile(suffix=".pfm", delete=False) as f:
            path = f.name

        doc.write(path)

        with PFMReader.open(path) as reader:
            assert reader.validate_checksum()

        Path(path).unlink()

    def test_to_document(self):
        doc = PFMDocument.create(agent="convert-test")
        doc.add_section("content", "convert me")

        with tempfile.NamedTemporaryFile(suffix=".pfm", delete=False) as f:
            path = f.name

        doc.write(path)

        with PFMReader.open(path) as reader:
            full_doc = reader.to_document()
            assert full_doc.agent == "convert-test"
            assert full_doc.content == "convert me"

        Path(path).unlink()


# =============================================================================
# Converters
# =============================================================================

class TestConverters:

    def _make_doc(self) -> PFMDocument:
        doc = PFMDocument.create(agent="conv-test", model="test-model")
        doc.add_section("content", "converter test content")
        doc.add_section("chain", "user: hello\nagent: hi")
        return doc

    # --- JSON ---

    def test_json_roundtrip(self):
        doc = self._make_doc()
        json_str = converters.to_json(doc)
        loaded = converters.from_json(json_str)

        assert loaded.agent == "conv-test"
        assert loaded.model == "test-model"
        assert loaded.content == "converter test content"
        assert loaded.chain == "user: hello\nagent: hi"

    def test_json_structure(self):
        import json
        doc = self._make_doc()
        json_str = converters.to_json(doc)
        data = json.loads(json_str)

        assert "pfm_version" in data
        assert "meta" in data
        assert "sections" in data
        assert len(data["sections"]) == 2

    # --- CSV ---

    def test_csv_roundtrip(self):
        doc = self._make_doc()
        csv_str = converters.to_csv(doc)
        loaded = converters.from_csv(csv_str)

        assert loaded.agent == "conv-test"
        assert loaded.content == "converter test content"

    def test_csv_has_header(self):
        doc = self._make_doc()
        csv_str = converters.to_csv(doc)
        first_line = csv_str.split("\n")[0]
        assert "type" in first_line
        assert "key" in first_line
        assert "value" in first_line

    # --- TXT ---

    def test_txt_output(self):
        doc = self._make_doc()
        txt = converters.to_txt(doc)

        assert "=== CONTENT ===" in txt
        assert "=== CHAIN ===" in txt
        assert "converter test content" in txt

    def test_txt_from(self):
        doc = converters.from_txt("just some text", agent="txt-agent")
        assert doc.agent == "txt-agent"
        assert doc.content == "just some text"

    # --- Markdown ---

    def test_markdown_roundtrip(self):
        doc = self._make_doc()
        md = converters.to_markdown(doc)
        loaded = converters.from_markdown(md)

        assert loaded.agent == "conv-test"
        assert loaded.get_section("content").content == "converter test content"

    def test_markdown_has_frontmatter(self):
        doc = self._make_doc()
        md = converters.to_markdown(doc)
        assert md.startswith("---\n")
        assert "agent: conv-test" in md

    def test_markdown_from_plain(self):
        doc = converters.from_markdown("# Hello\nJust some markdown without headers")
        assert doc.content is not None

    # --- convert_to / convert_from ---

    def test_convert_to_unknown_format(self):
        doc = self._make_doc()
        with pytest.raises(ValueError, match="Unknown format"):
            converters.convert_to(doc, "xml")

    def test_convert_from_unknown_format(self):
        with pytest.raises(ValueError, match="Unknown format"):
            converters.convert_from("data", "xml")
