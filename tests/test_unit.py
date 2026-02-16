"""
Unit Tests - Test individual components in isolation.
"""

import hashlib
import uuid

import pytest

from pfm.spec import MAGIC, EOF_MARKER, SECTION_PREFIX, FORMAT_VERSION, SECTION_TYPES
from pfm.document import PFMDocument, PFMSection


# =============================================================================
# PFMSection
# =============================================================================

class TestPFMSection:

    def test_create_section(self):
        s = PFMSection(name="content", content="hello world")
        assert s.name == "content"
        assert s.content == "hello world"
        assert s.offset == 0
        assert s.length == 0

    def test_section_with_offset(self):
        s = PFMSection(name="chain", content="data", offset=100, length=4)
        assert s.offset == 100
        assert s.length == 4


# =============================================================================
# PFMDocument
# =============================================================================

class TestPFMDocument:

    def test_create_defaults(self):
        doc = PFMDocument.create(agent="test-agent", model="gpt-4")
        assert doc.agent == "test-agent"
        assert doc.model == "gpt-4"
        assert doc.id  # UUID should be set
        assert doc.created  # Timestamp should be set
        # Validate UUID format
        uuid.UUID(doc.id)

    def test_create_with_custom_meta(self):
        doc = PFMDocument.create(agent="a", model="m", foo="bar", baz="qux")
        assert doc.custom_meta == {"foo": "bar", "baz": "qux"}

    def test_add_section(self):
        doc = PFMDocument.create()
        section = doc.add_section("content", "hello")
        assert isinstance(section, PFMSection)
        assert len(doc.sections) == 1
        assert doc.sections[0].name == "content"
        assert doc.sections[0].content == "hello"

    def test_get_section(self):
        doc = PFMDocument.create()
        doc.add_section("content", "hello")
        doc.add_section("chain", "prompt chain")

        assert doc.get_section("content").content == "hello"
        assert doc.get_section("chain").content == "prompt chain"
        assert doc.get_section("nonexistent") is None

    def test_get_sections_multiple(self):
        doc = PFMDocument.create()
        doc.add_section("artifacts", "file1.py")
        doc.add_section("artifacts", "file2.py")

        results = doc.get_sections("artifacts")
        assert len(results) == 2

    def test_content_shortcut(self):
        doc = PFMDocument.create()
        doc.add_section("content", "the content")
        assert doc.content == "the content"

    def test_content_shortcut_none(self):
        doc = PFMDocument.create()
        assert doc.content is None

    def test_chain_shortcut(self):
        doc = PFMDocument.create()
        doc.add_section("chain", "the chain")
        assert doc.chain == "the chain"

    def test_compute_checksum(self):
        doc = PFMDocument.create()
        doc.add_section("content", "hello")
        doc.add_section("chain", "world")

        checksum = doc.compute_checksum()
        # Should be SHA-256 of "hello" + "world"
        expected = hashlib.sha256(b"helloworld").hexdigest()
        assert checksum == expected

    def test_get_meta_dict(self):
        doc = PFMDocument.create(agent="a", model="m")
        doc.custom_meta["custom_key"] = "custom_val"
        meta = doc.get_meta_dict()

        assert meta["agent"] == "a"
        assert meta["model"] == "m"
        assert meta["custom_key"] == "custom_val"
        assert "id" in meta
        assert "created" in meta

    def test_repr(self):
        doc = PFMDocument.create(agent="test")
        doc.add_section("content", "x")
        r = repr(doc)
        assert "PFMDocument" in r
        assert "test" in r
        assert "content" in r


# =============================================================================
# Spec constants
# =============================================================================

class TestSpec:

    def test_magic(self):
        assert MAGIC == "#!PFM"

    def test_eof_marker(self):
        assert EOF_MARKER == "#!END"

    def test_section_prefix(self):
        assert SECTION_PREFIX == "#@"

    def test_format_version(self):
        assert FORMAT_VERSION == "1.0"

    def test_reserved_sections_exist(self):
        assert "content" in SECTION_TYPES
        assert "chain" in SECTION_TYPES
        assert "tools" in SECTION_TYPES
        assert "meta" in SECTION_TYPES
        assert "index" in SECTION_TYPES
