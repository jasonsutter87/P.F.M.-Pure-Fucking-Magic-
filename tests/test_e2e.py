"""
End-to-End Tests - Full workflows from creation through conversion.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from pfm.document import PFMDocument
from pfm.reader import PFMReader
from pfm.writer import PFMWriter
from pfm import converters


class TestFullWorkflow:
    """Test complete user workflows end-to-end."""

    def test_create_write_read_cycle(self):
        """Create a doc, write it, read it back, verify everything matches."""
        # Create
        doc = PFMDocument.create(
            agent="e2e-agent",
            model="claude-opus-4-6",
            tags="test,e2e",
        )
        doc.add_section("content", "This is the primary output from the agent.")
        doc.add_section("chain", "User: Write a poem\nAgent: Here's a poem about code...")
        doc.add_section("tools", "search(query='python file formats')\nread_file('spec.py')")
        doc.add_section("reasoning", "I need to write a poem. Let me think about code metaphors.")
        doc.add_section("metrics", "tokens_in=150 tokens_out=89 latency_ms=1234 cost=0.003")

        original_id = doc.id
        original_checksum = doc.compute_checksum()

        # Write
        with tempfile.NamedTemporaryFile(suffix=".pfm", delete=False) as f:
            path = f.name
        doc.write(path)

        # Read back (full parse)
        loaded = PFMReader.read(path)
        assert loaded.id == original_id
        assert loaded.agent == "e2e-agent"
        assert loaded.model == "claude-opus-4-6"
        assert loaded.tags == "test,e2e"
        assert loaded.content == "This is the primary output from the agent."
        assert loaded.chain == "User: Write a poem\nAgent: Here's a poem about code..."
        assert loaded.get_section("tools").content == "search(query='python file formats')\nread_file('spec.py')"
        assert loaded.get_section("reasoning") is not None
        assert loaded.get_section("metrics") is not None
        assert len(loaded.sections) == 5

        # Read back (indexed access)
        with PFMReader.open(path) as reader:
            assert reader.meta["id"] == original_id
            assert reader.meta["agent"] == "e2e-agent"
            content = reader.get_section("content")
            assert "primary output" in content
            assert reader.validate_checksum()

        Path(path).unlink()

    def test_pfm_to_json_to_pfm_roundtrip(self):
        """PFM -> JSON -> PFM should preserve all data."""
        doc = PFMDocument.create(agent="roundtrip", model="test")
        doc.add_section("content", "roundtrip content")
        doc.add_section("chain", "roundtrip chain")

        # PFM -> JSON
        json_str = converters.to_json(doc)

        # JSON -> PFM
        loaded = converters.from_json(json_str)
        assert loaded.agent == "roundtrip"
        assert loaded.content == "roundtrip content"
        assert loaded.chain == "roundtrip chain"

        # Write back to PFM and verify
        with tempfile.NamedTemporaryFile(suffix=".pfm", delete=False) as f:
            path = f.name
        loaded.write(path)

        final = PFMReader.read(path)
        assert final.content == "roundtrip content"
        Path(path).unlink()

    def test_pfm_to_markdown_to_pfm_roundtrip(self):
        """PFM -> Markdown -> PFM should preserve sections."""
        doc = PFMDocument.create(agent="md-rt", model="test")
        doc.add_section("content", "markdown roundtrip")
        doc.add_section("chain", "the chain")

        md = converters.to_markdown(doc)
        loaded = converters.from_markdown(md)

        assert loaded.agent == "md-rt"
        assert loaded.get_section("content").content == "markdown roundtrip"
        assert loaded.get_section("chain").content == "the chain"

    def test_pfm_to_all_formats(self):
        """Convert a single PFM doc to all supported formats."""
        doc = PFMDocument.create(agent="multi", model="test")
        doc.add_section("content", "multi-format test")

        formats = ["json", "csv", "txt", "md"]
        for fmt in formats:
            result = converters.convert_to(doc, fmt)
            assert isinstance(result, str)
            assert len(result) > 0
            assert "multi-format test" in result

    def test_large_content(self):
        """Handle large content sections without issues."""
        large_content = "x" * 1_000_000  # 1MB of content
        doc = PFMDocument.create(agent="large")
        doc.add_section("content", large_content)

        data = PFMWriter.serialize(doc)
        loaded = PFMReader.parse(data)

        assert loaded.content == large_content
        assert len(loaded.content) == 1_000_000

    def test_unicode_content(self):
        """Handle unicode content correctly."""
        unicode_content = "Hello 🌍! Привет мир! 你好世界! مرحبا بالعالم"
        doc = PFMDocument.create(agent="unicode")
        doc.add_section("content", unicode_content)

        data = PFMWriter.serialize(doc)
        loaded = PFMReader.parse(data)

        assert loaded.content == unicode_content

    def test_empty_sections(self):
        """Handle empty section content."""
        doc = PFMDocument.create(agent="empty")
        doc.add_section("content", "")
        doc.add_section("chain", "")

        data = PFMWriter.serialize(doc)
        loaded = PFMReader.parse(data)

        assert loaded.content == ""
        assert loaded.chain == ""

    def test_special_characters_in_content(self):
        """Content with characters that look like PFM markers.

        PFM-001 fix verification: Content escaping ensures round-trip fidelity
        for content containing #@ and #! marker sequences.
        """
        tricky = "#!PFM/1.0\n#@content\nfake section\n#!END"
        doc = PFMDocument.create(agent="tricky")
        doc.add_section("content", tricky)

        data = PFMWriter.serialize(doc)
        loaded = PFMReader.parse(data)

        # Content MUST be preserved exactly (escaping/unescaping round-trips)
        assert loaded.content == tricky

    def test_file_to_multiple_formats_and_back(self):
        """Write PFM, convert to JSON and MD, convert back, compare."""
        original = PFMDocument.create(agent="full-cycle", model="opus")
        original.add_section("content", "the answer is 42")
        original.add_section("chain", "user: what is the meaning?\nagent: 42")

        with tempfile.NamedTemporaryFile(suffix=".pfm", delete=False) as f:
            pfm_path = f.name
        original.write(pfm_path)

        # Read from file
        doc = PFMReader.read(pfm_path)

        # Convert to JSON, write, read back
        json_str = converters.to_json(doc)
        json_doc = converters.from_json(json_str)
        assert json_doc.content == "the answer is 42"

        # Convert to CSV, write, read back
        csv_str = converters.to_csv(doc)
        csv_doc = converters.from_csv(csv_str)
        assert csv_doc.content == "the answer is 42"

        Path(pfm_path).unlink()


class TestCLI:
    """Test the CLI commands via subprocess."""

    def test_cli_help(self):
        result = subprocess.run(
            [sys.executable, "-m", "pfm.cli", "--help"],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        assert result.returncode == 0
        assert "Pure Fucking Magic" in result.stdout

    def test_cli_version(self):
        result = subprocess.run(
            [sys.executable, "-m", "pfm.cli", "--version"],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        assert result.returncode == 0
        assert "0.1.0" in result.stdout

    def test_cli_create_and_inspect(self):
        with tempfile.NamedTemporaryFile(suffix=".pfm", delete=False) as f:
            path = f.name

        project_root = str(Path(__file__).parent.parent)

        # Create
        result = subprocess.run(
            [sys.executable, "-m", "pfm.cli", "create",
             "-o", path,
             "-a", "cli-test",
             "-m", "test-model",
             "-c", "CLI created content"],
            capture_output=True,
            text=True,
            cwd=project_root,
        )
        assert result.returncode == 0
        assert "Created" in result.stdout

        # Inspect
        result = subprocess.run(
            [sys.executable, "-m", "pfm.cli", "inspect", path],
            capture_output=True,
            text=True,
            cwd=project_root,
        )
        assert result.returncode == 0
        assert "cli-test" in result.stdout
        assert "content" in result.stdout
        assert "VALID" in result.stdout

        # Read section
        result = subprocess.run(
            [sys.executable, "-m", "pfm.cli", "read", path, "content"],
            capture_output=True,
            text=True,
            cwd=project_root,
        )
        assert result.returncode == 0
        assert "CLI created content" in result.stdout

        # Validate
        result = subprocess.run(
            [sys.executable, "-m", "pfm.cli", "validate", path],
            capture_output=True,
            text=True,
            cwd=project_root,
        )
        assert result.returncode == 0
        assert "OK" in result.stdout

        # Identify
        result = subprocess.run(
            [sys.executable, "-m", "pfm.cli", "identify", path],
            capture_output=True,
            text=True,
            cwd=project_root,
        )
        assert result.returncode == 0
        assert "PFM file" in result.stdout

        Path(path).unlink()

    def test_cli_convert_to_json(self):
        # Create a PFM file first
        with tempfile.NamedTemporaryFile(suffix=".pfm", delete=False) as f:
            pfm_path = f.name
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            json_path = f.name

        project_root = str(Path(__file__).parent.parent)

        doc = PFMDocument.create(agent="convert-cli")
        doc.add_section("content", "convert me")
        doc.write(pfm_path)

        result = subprocess.run(
            [sys.executable, "-m", "pfm.cli", "convert", "to", "json", pfm_path, "-o", json_path],
            capture_output=True,
            text=True,
            cwd=project_root,
        )
        assert result.returncode == 0

        json_content = Path(json_path).read_text()
        assert "convert me" in json_content

        Path(pfm_path).unlink()
        Path(json_path).unlink()
