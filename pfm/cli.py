"""
PFM CLI - Command-line interface for Pure Fucking Magic files.

Commands:
  pfm create   - Create a new .pfm file
  pfm inspect  - Show metadata and sections of a .pfm file
  pfm read     - Read a specific section from a .pfm file
  pfm validate - Validate a .pfm file (checksum, structure)
  pfm convert  - Convert to/from JSON, CSV, TXT, Markdown
  pfm identify - Quick check if a file is PFM format
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def cmd_create(args: argparse.Namespace) -> None:
    """Create a new .pfm file."""
    from pfm.document import PFMDocument

    doc = PFMDocument.create(
        agent=args.agent or "cli",
        model=args.model or "",
    )

    # Read content from stdin or --content flag
    if args.content:
        content = args.content
    elif args.file:
        # PFM-005/CLI: Resolve path and reject traversal attempts
        file_path = Path(args.file).resolve()
        if ".." in Path(args.file).parts:
            print("Error: Path traversal (..) not allowed in --file", file=sys.stderr)
            sys.exit(1)
        content = file_path.read_text(encoding="utf-8")
    elif not sys.stdin.isatty():
        content = sys.stdin.read()
    else:
        print("Error: Provide content via --content, --file, or stdin", file=sys.stderr)
        sys.exit(1)

    doc.add_section("content", content)

    if args.chain:
        doc.add_section("chain", args.chain)

    output = args.output or "output.pfm"
    nbytes = doc.write(output)
    print(f"Created {output} ({nbytes} bytes)")


def cmd_inspect(args: argparse.Namespace) -> None:
    """Inspect a .pfm file - show metadata and section listing."""
    from pfm.reader import PFMReader

    with PFMReader.open(args.path) as reader:
        print(f"PFM v{reader.format_version}")
        print()

        print("META:")
        for key, val in reader.meta.items():
            # Truncate long values
            display = val if len(val) <= 72 else val[:69] + "..."
            print(f"  {key}: {display}")
        print()

        print("SECTIONS:")
        for name in reader.section_names:
            entries = reader.index.get_all(name)
            for offset, length in entries:
                print(f"  {name:16s}  offset={offset:>8d}  length={length:>8d}")
        print()

        # Checksum validation
        valid = reader.validate_checksum()
        status = "VALID" if valid else "INVALID"
        print(f"CHECKSUM: {status}")


def cmd_read(args: argparse.Namespace) -> None:
    """Read a specific section from a .pfm file."""
    from pfm.reader import PFMReader

    with PFMReader.open(args.path) as reader:
        content = reader.get_section(args.section)
        if content is None:
            print(f"Section '{args.section}' not found.", file=sys.stderr)
            print(f"Available: {', '.join(reader.section_names)}", file=sys.stderr)
            sys.exit(1)
        print(content, end="")


def cmd_validate(args: argparse.Namespace) -> None:
    """Validate a .pfm file."""
    from pfm.reader import PFMReader

    path = args.path

    # Quick magic byte check
    if not PFMReader.is_pfm(path):
        print(f"FAIL: {path} is not a valid PFM file (bad magic bytes)")
        sys.exit(1)

    try:
        with PFMReader.open(path) as reader:
            valid = reader.validate_checksum()
            if valid:
                print(f"OK: {path} is valid PFM v{reader.format_version}")
                print(f"    Sections: {', '.join(reader.section_names)}")
            else:
                print(f"FAIL: {path} checksum mismatch")
                sys.exit(1)
    except ValueError as e:
        # ValueError from parser (version, format, bounds) -- safe to show
        print(f"FAIL: parse error: {e}")
        sys.exit(1)
    except Exception:
        # PFM-018 fix: Generic errors do not leak internal paths or stack details
        print(f"FAIL: unable to parse file (corrupted or invalid format)")
        sys.exit(1)


def cmd_convert(args: argparse.Namespace) -> None:
    """Convert to/from PFM."""
    from pfm.reader import PFMReader
    from pfm.converters import convert_to, convert_from

    if args.direction == "from":
        # Convert other format -> PFM
        data = Path(args.input).read_text(encoding="utf-8")
        doc = convert_from(data, args.format)
        output = args.output or Path(args.input).stem + ".pfm"
        nbytes = doc.write(output)
        print(f"Converted {args.input} -> {output} ({nbytes} bytes)")

    elif args.direction == "to":
        # Convert PFM -> other format
        doc = PFMReader.read(args.input)
        result = convert_to(doc, args.format)
        if args.output:
            Path(args.output).write_text(result, encoding="utf-8")
            print(f"Converted {args.input} -> {args.output}")
        else:
            print(result, end="")


def cmd_identify(args: argparse.Namespace) -> None:
    """Quick check if a file is PFM format."""
    from pfm.reader import PFMReader

    is_pfm = PFMReader.is_pfm(args.path)
    if is_pfm:
        print(f"{args.path}: PFM file")
    else:
        print(f"{args.path}: not PFM")
    sys.exit(0 if is_pfm else 1)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="pfm",
        description="PFM - Pure Fucking Magic. AI agent output container format.",
    )
    parser.add_argument("--version", action="version", version="pfm 0.1.0")
    sub = parser.add_subparsers(dest="command")

    # create
    p_create = sub.add_parser("create", help="Create a new .pfm file")
    p_create.add_argument("-o", "--output", help="Output file path")
    p_create.add_argument("-a", "--agent", help="Agent name")
    p_create.add_argument("-m", "--model", help="Model ID")
    p_create.add_argument("-c", "--content", help="Content string")
    p_create.add_argument("-f", "--file", help="Read content from file")
    p_create.add_argument("--chain", help="Prompt chain")

    # inspect
    p_inspect = sub.add_parser("inspect", help="Inspect a .pfm file")
    p_inspect.add_argument("path", help="Path to .pfm file")

    # read
    p_read = sub.add_parser("read", help="Read a section from a .pfm file")
    p_read.add_argument("path", help="Path to .pfm file")
    p_read.add_argument("section", help="Section name to read")

    # validate
    p_validate = sub.add_parser("validate", help="Validate a .pfm file")
    p_validate.add_argument("path", help="Path to .pfm file")

    # convert
    p_convert = sub.add_parser("convert", help="Convert to/from PFM")
    p_convert.add_argument("direction", choices=["to", "from"], help="Conversion direction")
    p_convert.add_argument("format", choices=["json", "csv", "txt", "md"], help="Target/source format")
    p_convert.add_argument("input", help="Input file path")
    p_convert.add_argument("-o", "--output", help="Output file path")

    # identify
    p_identify = sub.add_parser("identify", help="Quick check if a file is PFM")
    p_identify.add_argument("path", help="Path to file")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    commands = {
        "create": cmd_create,
        "inspect": cmd_inspect,
        "read": cmd_read,
        "validate": cmd_validate,
        "convert": cmd_convert,
        "identify": cmd_identify,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
