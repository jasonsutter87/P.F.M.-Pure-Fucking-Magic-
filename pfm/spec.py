"""
PFM Format Specification v1.0
==============================

Layout:
    #!PFM/1.0                    <- Magic line (file identification, instant)
    #@meta                       <- Metadata section header
    id: <uuid>                   <- Unique document ID
    agent: <name>                <- Agent that generated this
    model: <model-id>            <- Model used
    created: <iso-8601>          <- Timestamp
    checksum: <sha256>           <- SHA-256 of all content sections combined
    #@index                      <- Index section (byte offsets for O(1) jumps)
    <name> <offset> <length>     <- Section name, byte offset from file start, byte length
    <name> <offset> <length>
    ...
    #@<section_name>             <- Content sections
    <content>
    #@<section_name>
    <content>
    #!END                        <- EOF marker

Design Decisions:
    - #! prefix for file boundaries (like shebang - instant identification)
    - #@ prefix for section markers (fast single-char scan after #)
    - Index uses fixed-width-friendly format: name<space>offset<space>length
    - All UTF-8, no binary blobs (human readable)
    - Sections are arbitrary - format doesn't dictate what you store
    - Byte offsets in index point to first byte AFTER the section header line

Content Escaping:
    - Lines starting with #@ or #! inside section content are escaped on write
    - Escape prefix: \\# (backslash-hash) replaces the leading #
    - Writer: "#@fake" → "\\#@fake",  "#!END" → "\\#!END"
    - Reader: "\\#@fake" → "#@fake",  "\\#!END" → "#!END"
    - Only affects lines starting with #@ or #! (minimal overhead)
    - Human-readable: the backslash is visually obvious

Priority: Speed > Indexing > Human Readability > AI Usefulness
"""

# Magic bytes - first line of every .pfm file
MAGIC = "#!PFM"
EOF_MARKER = "#!END"
SECTION_PREFIX = "#@"
ESCAPE_PREFIX = "\\#"  # Escape for content lines that look like markers

# Format version
FORMAT_VERSION = "1.0"

# Supported format versions (reject unknown versions to prevent downgrade attacks)
SUPPORTED_FORMAT_VERSIONS = frozenset({"1.0"})

# Strict allowlist for meta fields settable via parser
META_ALLOWLIST = frozenset({"id", "agent", "model", "created", "checksum", "parent", "tags", "version"})

# Safety limits
MAX_FILE_SIZE = 500 * 1024 * 1024  # 500MB max file size for reader
MAX_SECTIONS = 10_000              # Max sections per document (prevents resource exhaustion)
MAX_META_FIELDS = 100              # Max custom meta fields
MAX_SECTION_NAME_LENGTH = 64       # Max length for section names
ALLOWED_SECTION_NAME_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_-")

# Reserved section names (users can define custom ones too)
SECTION_TYPES = {
    "meta": "File metadata (id, agent, model, timestamps)",
    "index": "Byte offset index for O(1) section access",
    "content": "Primary output content from the agent",
    "chain": "Prompt chain / conversation that produced this output",
    "tools": "Tool calls made during generation",
    "artifacts": "Generated code, files, or structured data",
    "reasoning": "Agent reasoning / chain-of-thought",
    "context": "Context window snapshot at generation time",
    "errors": "Errors encountered during generation",
    "metrics": "Performance metrics (tokens, latency, cost)",
}

# Meta field names
META_FIELDS = {
    "id": "Unique document identifier (UUID v4)",
    "agent": "Name/identifier of the generating agent",
    "model": "Model ID used for generation",
    "created": "ISO-8601 creation timestamp",
    "checksum": "SHA-256 hash of all content sections",
    "parent": "ID of parent .pfm document (for chains)",
    "tags": "Comma-separated tags",
    "version": "Document version (user-defined)",
}

# File extension
EXTENSION = ".pfm"

# Max magic line scan (for fast identification - don't read more than this)
MAX_MAGIC_SCAN_BYTES = 64


def escape_content_line(line: str) -> str:
    """Escape a content line that starts with a PFM marker prefix."""
    if line.startswith(SECTION_PREFIX) or line.startswith("\\#") or (line.startswith("#!") and (line.startswith(MAGIC) or line.startswith(EOF_MARKER))):
        return "\\" + line
    return line


def unescape_content_line(line: str) -> str:
    """Unescape a previously escaped content line."""
    if line.startswith("\\#"):
        return line[1:]
    return line


def escape_content(content: str) -> str:
    """Escape all lines in a content string."""
    return "\n".join(escape_content_line(line) for line in content.split("\n"))


def unescape_content(content: str) -> str:
    """Unescape all lines in a content string."""
    return "\n".join(unescape_content_line(line) for line in content.split("\n"))


def validate_section_name(name: str) -> bool:
    """Validate a section name is safe."""
    if not name or len(name) > MAX_SECTION_NAME_LENGTH:
        return False
    return all(c in ALLOWED_SECTION_NAME_CHARS for c in name)
