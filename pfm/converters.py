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
    """Create PFM document from JSON string."""
    data = json.loads(json_str)
    meta = data.get("meta", {})

    doc = PFMDocument(
        id=meta.get("id", ""),
        agent=meta.get("agent", ""),
        model=meta.get("model", ""),
        created=meta.get("created", ""),
        checksum=meta.get("checksum", ""),
        parent=meta.get("parent", ""),
        tags=meta.get("tags", ""),
        version=meta.get("version", ""),
        format_version=data.get("pfm_version", "1.0"),
    )

    # Custom meta fields
    reserved = {"id", "agent", "model", "created", "checksum", "parent", "tags", "version"}
    for key, val in meta.items():
        if key not in reserved:
            doc.custom_meta[key] = val

    for section in data.get("sections", []):
        doc.add_section(section["name"], section["content"])

    return doc


# =============================================================================
# CSV
# =============================================================================

def to_csv(doc: PFMDocument) -> str:
    """
    Convert PFM document to CSV.
    Row format: type, key/name, value/content
    First rows are meta fields, then section rows.
    """
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["type", "key", "value"])

    # Meta rows
    for key, val in doc.get_meta_dict().items():
        writer.writerow(["meta", key, val])

    # Section rows
    for section in doc.sections:
        writer.writerow(["section", section.name, section.content])

    return buf.getvalue()


def from_csv(csv_str: str) -> PFMDocument:
    """Create PFM document from CSV string."""
    reader = csv.reader(io.StringIO(csv_str))
    header = next(reader, None)  # Skip header row

    doc = PFMDocument()
    reserved = {"id", "agent", "model", "created", "checksum", "parent", "tags", "version"}

    for row in reader:
        if len(row) < 3:
            continue
        row_type, key, value = row[0], row[1], row[2]

        if row_type == "meta":
            if key in reserved and hasattr(doc, key):
                setattr(doc, key, value)
            else:
                doc.custom_meta[key] = value
        elif row_type == "section":
            doc.add_section(key, value)

    return doc


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
    """
    parts = []

    # Frontmatter
    meta = doc.get_meta_dict()
    if meta:
        parts.append("---")
        for key, val in meta.items():
            parts.append(f"{key}: {val}")
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
    """
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
                reserved = {"id", "agent", "model", "created", "checksum", "parent", "tags", "version"}
                if key in reserved and hasattr(doc, key):
                    setattr(doc, key, val)
                else:
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

            current_section = line[3:].strip()
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
    """Create a PFM document from data in the specified format."""
    converter = CONVERTERS_FROM.get(fmt.lower())
    if converter is None:
        raise ValueError(f"Unknown format: {fmt}. Supported: {list(CONVERTERS_FROM.keys())}")
    return converter(data, **kwargs)
