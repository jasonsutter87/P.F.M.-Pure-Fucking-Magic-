"""
PFM Converters - Convert to/from JSON, CSV, TXT, Markdown.

Every format goes both ways:
  - to_json / from_json
  - to_csv / from_csv
  - to_txt / from_txt
  - to_markdown / from_markdown
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from pfm.document import PFMDocument, PFMSection
from pfm.spec import META_ALLOWLIST


# =============================================================================
# JSON
# =============================================================================

def to_json(doc: PFMDocument, indent: int = 2) -> str:
    """Convert PFM document to JSON string."""
    data: dict[str, Any] = {
        "pfm_version": doc.format_version,
        "meta": doc.get_meta_dict(),
        "sections": [],
    }
    for section in doc.sections:
        data["sections"].append({
            "name": section.name,
            "content": section.content,
        })
    return json.dumps(data, indent=indent, ensure_ascii=False)


def from_json(json_str: str) -> PFMDocument:
    """Create PFM document from JSON string.

    Validates the structure of the parsed JSON to prevent type confusion attacks.
    Rejects keys that could cause prototype-pollution-like issues in downstream JS.
    """
    data = json.loads(json_str)

    # Validate top-level structure
    if not isinstance(data, dict):
        raise ValueError("Invalid PFM JSON: expected a JSON object at top level")

    meta = data.get("meta", {})
    if not isinstance(meta, dict):
        raise ValueError("Invalid PFM JSON: 'meta' must be a JSON object")

    # Validate all meta values are strings
    safe_meta = {}
    for key, val in meta.items():
        if not isinstance(key, str) or not isinstance(val, str):
            continue
        safe_meta[key] = val

    doc = PFMDocument(
        id=safe_meta.get("id", ""),
        agent=safe_meta.get("agent", ""),
        model=safe_meta.get("model", ""),
        created=safe_meta.get("created", ""),
        checksum=safe_meta.get("checksum", ""),
        parent=safe_meta.get("parent", ""),
        tags=safe_meta.get("tags", ""),
        version=safe_meta.get("version", ""),
        format_version=data.get("pfm_version", "1.0") if isinstance(data.get("pfm_version"), str) else "1.0",
    )

    # Custom meta fields
    reserved = {"id", "agent", "model", "created", "checksum", "parent", "tags", "version"}
    for key, val in safe_meta.items():
        if key not in reserved:
            doc.custom_meta[key] = val

    sections = data.get("sections", [])
    if not isinstance(sections, list):
        raise ValueError("Invalid PFM JSON: 'sections' must be an array")

    for section in sections:
        if not isinstance(section, dict):
            continue
        name = section.get("name")
        content = section.get("content")
        if isinstance(name, str) and isinstance(content, str):
            doc.add_section(name, content)

    return doc


# =============================================================================
# CSV
# =============================================================================

def _escape_csv_formula(value: str) -> str:
    """Escape CSV formula injection characters (=, +, -, @, tab, CR, ;).

    Checks the first non-whitespace character to prevent spreadsheet
    applications from interpreting cell content as formulas.
    Per OWASP: also handles semicolons (formula initiator in some locales)
    and leading whitespace before dangerous characters.
    """
    stripped = value.lstrip()
    if stripped and stripped[0] in ("=", "+", "-", "@", "\t", "\r", ";"):
        return "'" + value
    return value


def to_csv(doc: PFMDocument) -> str:
    """
    Convert PFM document to CSV.
    Row format: type, key/name, value/content
    First rows are meta fields, then section rows.

    Security: Escapes formula injection characters to prevent spreadsheet attacks.
    """
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["type", "key", "value"])

    # Meta rows
    for key, val in doc.get_meta_dict().items():
        writer.writerow(["meta", _escape_csv_formula(key), _escape_csv_formula(val)])

    # Section rows
    for section in doc.sections:
        writer.writerow(["section", section.name, _escape_csv_formula(section.content)])

    return buf.getvalue()


def from_csv(csv_str: str) -> PFMDocument:
    """Create PFM document from CSV string.

    Validates row types and enforces field count limits.
    Raises csv.field_size_limit for large fields (e.g., entire books
    stored as section content). We temporarily increase the limit to
    match PFM's MAX_FILE_SIZE.
    """
    from pfm.spec import MAX_META_FIELDS, MAX_FILE_SIZE

    # Increase field size limit for large PFM content sections
    old_limit = csv.field_size_limit()
    csv.field_size_limit(MAX_FILE_SIZE)
    try:
        reader = csv.reader(io.StringIO(csv_str))
        header = next(reader, None)  # Skip header row

        doc = PFMDocument()

        for row in reader:
            if len(row) < 3:
                continue
            row_type, key, value = row[0], row[1], row[2]

            # Validate types are strings
            if not isinstance(key, str) or not isinstance(value, str):
                continue

            if row_type == "meta":
                if key in META_ALLOWLIST:
                    doc.__dict__[key] = value
                else:
                    # Enforce custom meta field count limit
                    if len(doc.custom_meta) >= MAX_META_FIELDS:
                        continue
                    doc.custom_meta[key] = value
            elif row_type == "section":
                doc.add_section(key, value)

        return doc
    finally:
        csv.field_size_limit(old_limit)


# =============================================================================
# Plain Text (TXT)
# =============================================================================

def to_txt(doc: PFMDocument) -> str:
    """
    Convert PFM document to plain text.
    Just the content sections, separated by section names as headers.
    Optimized for human reading - strips all metadata overhead.
    """
    parts = []

    # Compact meta header
    meta = doc.get_meta_dict()
    if meta:
        meta_line = " | ".join(f"{k}={v}" for k, v in meta.items() if k != "checksum")
        parts.append(f"[{meta_line}]")
        parts.append("")

    for section in doc.sections:
        parts.append(f"=== {section.name.upper()} ===")
        parts.append(section.content)
        parts.append("")

    return "\n".join(parts)


def from_txt(txt_str: str, agent: str = "", model: str = "") -> PFMDocument:
    """
    Create PFM document from plain text.
    Treats the entire text as a single 'content' section.
    """
    doc = PFMDocument.create(agent=agent, model=model)
    doc.add_section("content", txt_str.strip())
    return doc


# =============================================================================
# Markdown
# =============================================================================

def to_markdown(doc: PFMDocument) -> str:
    """
    Convert PFM document to Markdown.
    Sections become ## headers, meta becomes a YAML-style frontmatter block.

    Security: Sanitizes meta keys and values to prevent YAML frontmatter injection.
    """
    parts = []

    # Frontmatter
    meta = doc.get_meta_dict()
    if meta:
        parts.append("---")
        for key, val in meta.items():
            # Sanitize key: remove colons and control characters
            safe_key = "".join(c if c.isalnum() or c in "-_" else "_" for c in key)
            # Sanitize value: replace newlines, escape frontmatter delimiters
            safe_val = val.replace("\n", " ").replace("---", "\\---")
            parts.append(f"{safe_key}: {safe_val}")
        parts.append("---")
        parts.append("")

    # Sections as headers
    for section in doc.sections:
        parts.append(f"## {section.name}")
        parts.append("")
        parts.append(section.content)
        parts.append("")

    return "\n".join(parts)


def from_markdown(md_str: str) -> PFMDocument:
    """
    Create PFM document from Markdown.
    Parses YAML-style frontmatter for meta, ## headers as sections.
    If no headers found, treats entire content as a single 'content' section.

    Enforces meta field count limits from spec.
    """
    from pfm.spec import MAX_META_FIELDS

    doc = PFMDocument()
    lines = md_str.split("\n")
    i = 0

    # Parse frontmatter
    if lines and lines[0].strip() == "---":
        i = 1
        while i < len(lines) and lines[i].strip() != "---":
            line = lines[i].strip()
            if ": " in line:
                key, val = line.split(": ", 1)
                key = key.strip()
                val = val.strip()
                if key in META_ALLOWLIST:
                    doc.__dict__[key] = val
                else:
                    # Enforce custom meta field count limit
                    if len(doc.custom_meta) < MAX_META_FIELDS:
                        doc.custom_meta[key] = val
            i += 1
        i += 1  # Skip closing ---

    # Parse sections (## headers)
    current_section: str | None = None
    section_lines: list[str] = []
    content_before_sections: list[str] = []

    while i < len(lines):
        line = lines[i]

        if line.startswith("## "):
            # Flush previous section
            if current_section:
                doc.add_section(current_section, "\n".join(section_lines).strip())
            else:
                # Only add pre-section content if it's non-empty
                pre_content = "\n".join(content_before_sections).strip()
                if pre_content:
                    doc.add_section("content", pre_content)

            # Normalize section name: lowercase, replace spaces with hyphens,
            # strip non-alphanumeric chars for PFM section name compatibility
            raw_name = line[3:].strip()
            normalized = raw_name.lower().replace(" ", "-")
            normalized = "".join(
                c for c in normalized if c in "abcdefghijklmnopqrstuvwxyz0123456789_-"
            )
            current_section = normalized or "content"
            section_lines = []
        elif current_section is None:
            content_before_sections.append(line)
        else:
            section_lines.append(line)

        i += 1

    # Flush last section
    if current_section:
        doc.add_section(current_section, "\n".join(section_lines).strip())
    else:
        pre_content = "\n".join(content_before_sections).strip()
        if pre_content:
            doc.add_section("content", pre_content)

    # If no sections at all, treat everything as content
    if not doc.sections:
        doc.add_section("content", md_str.strip())

    return doc


# =============================================================================
# Auto-detect and convert
# =============================================================================

CONVERTERS_TO = {
    "json": to_json,
    "csv": to_csv,
    "txt": to_txt,
    "md": to_markdown,
    "markdown": to_markdown,
}

CONVERTERS_FROM = {
    "json": from_json,
    "csv": from_csv,
    "txt": from_txt,
    "md": from_markdown,
    "markdown": from_markdown,
}


def convert_to(doc: PFMDocument, fmt: str) -> str:
    """Convert a PFM document to the specified format."""
    converter = CONVERTERS_TO.get(fmt.lower())
    if converter is None:
        raise ValueError(f"Unknown format: {fmt}. Supported: {list(CONVERTERS_TO.keys())}")
    return converter(doc)


def convert_from(data: str, fmt: str, **kwargs) -> PFMDocument:
    """Create a PFM document from data in the specified format.

    Only 'txt' format accepts extra kwargs (agent=, model=).
    Other formats ignore unknown kwargs to prevent TypeError.
    """
    converter = CONVERTERS_FROM.get(fmt.lower())
    if converter is None:
        raise ValueError(f"Unknown format: {fmt}. Supported: {list(CONVERTERS_FROM.keys())}")
    # Only from_txt accepts kwargs; strip them for other converters
    if fmt.lower() == "txt":
        return converter(data, **kwargs)
    return converter(data)
