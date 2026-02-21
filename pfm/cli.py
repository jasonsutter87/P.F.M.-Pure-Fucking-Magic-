"""
PFM CLI - Command-line interface for Pure Fucking Magic files.

Commands:
  pfm create   - Create a new .pfm file
  pfm inspect  - Show metadata and sections of a .pfm file
  pfm read     - Read a specific section from a .pfm file
  pfm validate - Validate a .pfm file (checksum, structure)
  pfm convert  - Convert to/from JSON, CSV, TXT, Markdown
  pfm export   - Export .pfm conversations to fine-tuning JSONL
  pfm encrypt  - Encrypt a .pfm file with AES-256-GCM
  pfm decrypt  - Decrypt an encrypted .pfm file
  pfm sign     - Sign a .pfm file with HMAC-SHA256
  pfm verify   - Verify HMAC-SHA256 signature of a .pfm file
  pfm identify - Quick check if a file is PFM format
  pfm view     - View a .pfm file (TUI, web, or HTML export)
"""

from __future__ import annotations

import argparse
import os
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
        cwd = Path.cwd().resolve()
        if ".." in Path(args.file).parts:
            print("Error: Path traversal (..) not allowed in --file", file=sys.stderr)
            sys.exit(1)
        # Ensure resolved path is under the current working directory
        try:
            file_path.relative_to(cwd)
        except ValueError:
            print("Error: --file must reference a path under the current directory", file=sys.stderr)
            sys.exit(1)
        if not file_path.is_file():
            print(f"Error: File not found: {args.file}", file=sys.stderr)
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

    # Optional signing (--sign or PFM_ALWAYS_SIGN env var)
    sign_secret = getattr(args, 'sign', None) or os.environ.get('PFM_SIGN_SECRET', '')
    if sign_secret:
        from pfm.security import sign_document
        from pfm.reader import PFMReader
        doc = PFMReader.read(output)
        sign_document(doc, sign_secret)
        doc.write(output)
        print(f"  Signed with HMAC-SHA256")

    # Optional encryption (--encrypt or PFM_ALWAYS_ENCRYPT env var)
    encrypt_pw = getattr(args, 'encrypt', None) or os.environ.get('PFM_ENCRYPT_PASSWORD', '')
    if encrypt_pw:
        from pfm.security import encrypt_document
        from pfm.reader import PFMReader
        doc = PFMReader.read(output)
        encrypted = encrypt_document(doc, encrypt_pw)
        enc_output = output + ".enc"
        Path(enc_output).write_bytes(encrypted)
        Path(output).unlink()
        print(f"  Encrypted -> {enc_output}")


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


def _infer_format(filename: str) -> str | None:
    """Infer format from file extension."""
    ext_map = {".json": "json", ".csv": "csv", ".txt": "txt", ".md": "md", ".markdown": "md", ".pfm": "pfm"}
    return ext_map.get(Path(filename).suffix.lower())


def cmd_convert(args: argparse.Namespace) -> None:
    """Convert to/from PFM."""
    from pfm.reader import PFMReader
    from pfm.converters import convert_to, convert_from
    from pfm.spec import MAX_FILE_SIZE

    known_formats = {"json", "csv", "txt", "md"}

    # Resolve format and input: either explicit (pfm convert from json file) or inferred (pfm convert from file)
    if args.format_or_input in known_formats and args.input:
        fmt = args.format_or_input
        input_file = args.input
    else:
        input_file = args.format_or_input
        inferred = _infer_format(input_file)
        inferred_from_output = _infer_format(args.output) if args.output else None
        # For "to": infer from -o flag since input is .pfm
        # For "from": infer from input file extension
        resolved = (inferred_from_output if args.direction == "to" and inferred_from_output and inferred_from_output != "pfm" else inferred)
        if not resolved or resolved == "pfm":
            print(f"Error: Cannot infer format. Specify explicitly:", file=sys.stderr)
            print(f"  pfm convert {args.direction} <json|csv|txt|md> {input_file}", file=sys.stderr)
            sys.exit(1)
        fmt = resolved

    if args.direction == "from":
        # Convert other format -> PFM
        input_path = Path(input_file)
        if not input_path.is_file():
            print(f"Error: File not found: {input_file}", file=sys.stderr)
            sys.exit(1)
        file_size = input_path.stat().st_size
        if file_size > MAX_FILE_SIZE:
            print(
                f"Error: File size {file_size} exceeds maximum {MAX_FILE_SIZE} bytes",
                file=sys.stderr,
            )
            sys.exit(1)
        data = input_path.read_text(encoding="utf-8")
        doc = convert_from(data, fmt)
        output = args.output or Path(input_file).stem + ".pfm"
        # Reject path traversal in output path
        if ".." in Path(output).parts:
            print("Error: Output path must not contain '..' (path traversal)", file=sys.stderr)
            sys.exit(1)
        nbytes = doc.write(output)
        print(f"Converted {input_file} -> {output} ({nbytes} bytes)")

    elif args.direction == "to":
        # Convert PFM -> other format
        doc = PFMReader.read(input_file)
        result = convert_to(doc, fmt)
        if args.output:
            # Reject path traversal in output path
            if ".." in Path(args.output).parts:
                print("Error: Output path must not contain '..' (path traversal)", file=sys.stderr)
                sys.exit(1)
            Path(args.output).write_text(result, encoding="utf-8")
            print(f"Converted {input_file} -> {args.output}")
        else:
            print(result, end="")


def cmd_view(args: argparse.Namespace) -> None:
    """View a .pfm file in TUI, web browser, or as static HTML."""
    path = args.path

    if args.html:
        # Generate standalone HTML file
        from pfm.web.generator import write_html

        output = args.output or Path(path).stem + ".html"
        nbytes = write_html(path, output)
        print(f"Generated {output} ({nbytes} bytes)")
        return

    if args.web:
        # Launch local web server + open browser
        from pfm.web.server import serve

        serve(path, open_browser=True)
        return

    # Default: TUI viewer
    try:
        from pfm.tui.viewer import run_viewer
    except ImportError:
        print(
            "TUI viewer requires the 'textual' package.\n"
            "Install it with: pip install \"pfm[tui]\"",
            file=sys.stderr,
        )
        sys.exit(1)
    run_viewer(path)


def cmd_export(args: argparse.Namespace) -> None:
    """Export .pfm conversations to fine-tuning JSONL."""
    from pfm.export import load_pfm_paths, export_documents
    from pfm.reader import PFMReader

    path = args.path
    fmt = args.format
    output = args.output or "training.jsonl"

    # Reject path traversal in output
    if ".." in Path(output).parts:
        print("Error: Output path must not contain '..' (path traversal)", file=sys.stderr)
        sys.exit(1)

    try:
        pfm_paths = load_pfm_paths(path)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if not pfm_paths:
        print(f"Error: No .pfm files found in {path}", file=sys.stderr)
        sys.exit(1)

    docs = []
    for p in pfm_paths:
        try:
            docs.append(PFMReader.read(str(p)))
        except Exception as e:
            print(f"Warning: Skipping {p}: {e}", file=sys.stderr)

    if not docs:
        print("Error: No valid .pfm files to export", file=sys.stderr)
        sys.exit(1)

    lines, total_turns = export_documents(docs, fmt)
    Path(output).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Exported {len(docs)} conversations ({total_turns} turns) -> {output}")


def cmd_encrypt(args: argparse.Namespace) -> None:
    """Encrypt a .pfm file with AES-256-GCM."""
    from pfm.reader import PFMReader
    from pfm.security import encrypt_document

    doc = PFMReader.read(args.path)
    password = args.password
    if not password:
        import getpass
        password = getpass.getpass("Password: ")
        confirm = getpass.getpass("Confirm: ")
        if password != confirm:
            print("Error: Passwords do not match", file=sys.stderr)
            sys.exit(1)
    if not password:
        print("Error: Password cannot be empty", file=sys.stderr)
        sys.exit(1)

    output = args.output or args.path + ".enc"
    if ".." in Path(output).parts:
        print("Error: Output path must not contain '..' (path traversal)", file=sys.stderr)
        sys.exit(1)
    encrypted = encrypt_document(doc, password)
    Path(output).write_bytes(encrypted)
    print(f"Encrypted {args.path} -> {output} ({len(encrypted)} bytes)")


def cmd_decrypt(args: argparse.Namespace) -> None:
    """Decrypt an encrypted .pfm file."""
    from pfm.security import decrypt_document

    from pfm.spec import MAX_FILE_SIZE
    enc_path = Path(args.path)
    file_size = enc_path.stat().st_size
    if file_size > MAX_FILE_SIZE:
        print(f"Error: File size {file_size} exceeds maximum {MAX_FILE_SIZE} bytes", file=sys.stderr)
        sys.exit(1)
    data = enc_path.read_bytes()
    password = args.password
    if not password:
        import getpass
        password = getpass.getpass("Password: ")
    if not password:
        print("Error: Password cannot be empty", file=sys.stderr)
        sys.exit(1)

    try:
        doc = decrypt_document(data, password)
    except Exception:
        print("Error: Decryption failed (wrong password or corrupted file)", file=sys.stderr)
        sys.exit(1)

    output = args.output
    if not output:
        # Strip .enc suffix if present
        output = args.path.removesuffix(".enc") if args.path.endswith(".enc") else args.path + ".dec.pfm"
    if ".." in Path(output).parts:
        print("Error: Output path must not contain '..' (path traversal)", file=sys.stderr)
        sys.exit(1)
    nbytes = doc.write(output)
    print(f"Decrypted {args.path} -> {output} ({nbytes} bytes)")


def cmd_sign(args: argparse.Namespace) -> None:
    """Sign a .pfm file with HMAC-SHA256."""
    from pfm.reader import PFMReader
    from pfm.security import sign

    doc = PFMReader.read(args.path)
    secret = args.secret
    if not secret:
        import getpass
        secret = getpass.getpass("Secret: ")
    if not secret:
        print("Error: Secret cannot be empty", file=sys.stderr)
        sys.exit(1)

    sig = sign(doc, secret)
    output = args.output or args.path
    # Reject path traversal in output path
    if ".." in Path(output).parts:
        print("Error: Output path must not contain '..' (path traversal)", file=sys.stderr)
        sys.exit(1)
    doc.write(output)
    print(f"Signed {output} (sig={sig[:16]}...)")


def cmd_verify(args: argparse.Namespace) -> None:
    """Verify the HMAC-SHA256 signature of a .pfm file."""
    from pfm.reader import PFMReader
    from pfm.security import verify

    doc = PFMReader.read(args.path)
    secret = args.secret
    if not secret:
        import getpass
        secret = getpass.getpass("Secret: ")
    if not secret:
        print("Error: Secret cannot be empty", file=sys.stderr)
        sys.exit(1)

    if not doc.custom_meta.get("signature"):
        print(f"FAIL: {args.path} has no signature")
        sys.exit(1)

    valid = verify(doc, secret)
    if valid:
        print(f"OK: {args.path} signature is valid")
    else:
        print(f"FAIL: {args.path} signature mismatch (tampered or wrong secret)")
        sys.exit(1)


def cmd_spells(args: argparse.Namespace) -> None:
    """List all available PFM spells."""
    print("PFM Spells")
    print("Aliased API with Harry Potter spell names.\n")
    print("  accio <file> <section>           Summon a section from a .pfm file")
    print("                                   (alias for: pfm read)")
    print()
    print("  polyjuice <file> <format>        Transform to another format (json, csv, txt, md)")
    print("                                   (alias for: pfm convert to <format>)")
    print()
    print("  fidelius <file> [-p password]     Cast the Fidelius Charm — encrypt a document")
    print("                                   (alias for: pfm encrypt)")
    print()
    print("  revelio <file> [-p password]      Reveal hidden contents — decrypt a document")
    print("                                   (alias for: pfm decrypt)")
    print()
    print("  unbreakable-vow <file> [-s key]   Make an Unbreakable Vow — sign a document")
    print("                                   (alias for: pfm sign)")
    print()
    print("  vow-kept <file> [-s key]          Check if the Vow holds — verify signature")
    print("                                   (alias for: pfm verify)")
    print()
    print("  prior-incantato <file>            Reveal history and integrity of a document")
    print("                                   (alias for: pfm validate)")
    print()
    print("  pensieve <path> [-o out] [--fmt]  Extract memories for training data")
    print("                                   (alias for: pfm export)")
    print()
    print("Usage:")
    print("  pfm accio report.pfm content")
    print("  pfm polyjuice report.pfm json -o report.json")
    print("  pfm fidelius report.pfm -p mypassword")
    print("  pfm revelio report.pfm.enc -p mypassword")
    print("  pfm unbreakable-vow report.pfm -s mysecret")
    print("  pfm vow-kept report.pfm -s mysecret")
    print("  pfm prior-incantato report.pfm")
    print()
    print("Python API:")
    print("  from pfm.spells import accio, polyjuice, fidelius, revelio")
    print("  content = accio('report.pfm', 'content')")


def cmd_accio(args: argparse.Namespace) -> None:
    """Summon a section from a .pfm file."""
    cmd_read(args)


def cmd_polyjuice(args: argparse.Namespace) -> None:
    """Transform a .pfm file to another format."""
    from pfm.reader import PFMReader
    from pfm.converters import convert_to

    doc = PFMReader.read(args.path)
    result = convert_to(doc, args.format)
    if args.output:
        if ".." in Path(args.output).parts:
            print("Error: Output path must not contain '..' (path traversal)", file=sys.stderr)
            sys.exit(1)
        Path(args.output).write_text(result, encoding="utf-8")
        print(f"Converted {args.path} -> {args.output}")
    else:
        print(result, end="")


def cmd_prior_incantato(args: argparse.Namespace) -> None:
    """Reveal the history and integrity of a document."""
    from pfm.reader import PFMReader
    from pfm.spells import prior_incantato

    doc = PFMReader.read(args.path)
    result = prior_incantato(doc)

    print(f"Prior Incantato: {args.path}\n")
    print(f"  ID:         {result['id'] or '(none)'}")
    print(f"  Agent:      {result['agent'] or '(none)'}")
    print(f"  Model:      {result['model'] or '(none)'}")
    print(f"  Created:    {result['created'] or '(none)'}")
    print(f"  Integrity:  {'VALID' if result['integrity'] else 'INVALID'}")
    print(f"  Signed:     {'Yes (' + result['sig_algo'] + ')' if result['signed'] else 'No'}")
    print(f"  Fingerprint: {result['fingerprint']}")


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
    from pfm import __version__
    parser.add_argument("--version", action="version", version=f"pfm {__version__}")
    sub = parser.add_subparsers(dest="command")

    # create
    p_create = sub.add_parser("create", help="Create a new .pfm file")
    p_create.add_argument("-o", "--output", help="Output file path")
    p_create.add_argument("-a", "--agent", help="Agent name")
    p_create.add_argument("-m", "--model", help="Model ID")
    p_create.add_argument("-c", "--content", help="Content string")
    p_create.add_argument("-f", "--file", help="Read content from file")
    p_create.add_argument("--chain", help="Prompt chain")
    p_create.add_argument("--sign", help="Sign with HMAC-SHA256 secret (or set PFM_SIGN_SECRET env var)")
    p_create.add_argument("--encrypt", help="Encrypt with password (or set PFM_ENCRYPT_PASSWORD env var)")

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
    p_convert.add_argument("format_or_input", help="Format (json, csv, txt, md) or input file")
    p_convert.add_argument("input", nargs="?", default=None, help="Input file path")
    p_convert.add_argument("-o", "--output", help="Output file path")

    # view
    p_view = sub.add_parser("view", help="View a .pfm file (TUI, web, or HTML)")
    p_view.add_argument("path", help="Path to .pfm file")
    p_view.add_argument("--web", action="store_true", help="Open in web browser (local server)")
    p_view.add_argument("--html", action="store_true", help="Generate standalone HTML file")
    p_view.add_argument("-o", "--output", help="Output path for --html mode")

    # encrypt
    p_encrypt = sub.add_parser("encrypt", help="Encrypt a .pfm file with AES-256-GCM")
    p_encrypt.add_argument("path", help="Path to .pfm file")
    p_encrypt.add_argument("-p", "--password", help="Encryption password (prompted if omitted)")
    p_encrypt.add_argument("-o", "--output", help="Output path (default: <path>.enc)")

    # decrypt
    p_decrypt = sub.add_parser("decrypt", help="Decrypt an encrypted .pfm file")
    p_decrypt.add_argument("path", help="Path to encrypted file")
    p_decrypt.add_argument("-p", "--password", help="Decryption password (prompted if omitted)")
    p_decrypt.add_argument("-o", "--output", help="Output path")

    # sign
    p_sign = sub.add_parser("sign", help="Sign a .pfm file with HMAC-SHA256")
    p_sign.add_argument("path", help="Path to .pfm file")
    p_sign.add_argument("-s", "--secret", help="Signing secret (prompted if omitted)")
    p_sign.add_argument("-o", "--output", help="Output path (default: overwrite input)")

    # verify
    p_verify = sub.add_parser("verify", help="Verify HMAC-SHA256 signature")
    p_verify.add_argument("path", help="Path to .pfm file")
    p_verify.add_argument("-s", "--secret", help="Signing secret (prompted if omitted)")

    # identify
    p_identify = sub.add_parser("identify", help="Quick check if a file is PFM")
    p_identify.add_argument("path", help="Path to file")

    # spells
    sub.add_parser("spells", help="List all PFM spells (aliased commands)")

    # accio (alias for read)
    p_accio = sub.add_parser("accio", help="Summon a section from a .pfm file")
    p_accio.add_argument("path", help="Path to .pfm file")
    p_accio.add_argument("section", help="Section name to summon")

    # polyjuice (alias for convert to)
    p_polyjuice = sub.add_parser("polyjuice", help="Transform a .pfm file to another format")
    p_polyjuice.add_argument("path", help="Path to .pfm file")
    p_polyjuice.add_argument("format", choices=["json", "csv", "txt", "md"], help="Target format")
    p_polyjuice.add_argument("-o", "--output", help="Output file path")

    # fidelius (alias for encrypt)
    p_fidelius = sub.add_parser("fidelius", help="Encrypt a .pfm file (Fidelius Charm)")
    p_fidelius.add_argument("path", help="Path to .pfm file")
    p_fidelius.add_argument("-p", "--password", help="Encryption password (prompted if omitted)")
    p_fidelius.add_argument("-o", "--output", help="Output path (default: <path>.enc)")

    # revelio (alias for decrypt)
    p_revelio = sub.add_parser("revelio", help="Decrypt an encrypted .pfm file")
    p_revelio.add_argument("path", help="Path to encrypted file")
    p_revelio.add_argument("-p", "--password", help="Decryption password (prompted if omitted)")
    p_revelio.add_argument("-o", "--output", help="Output path")

    # unbreakable-vow (alias for sign)
    p_vow = sub.add_parser("unbreakable-vow", help="Sign a .pfm file (Unbreakable Vow)")
    p_vow.add_argument("path", help="Path to .pfm file")
    p_vow.add_argument("-s", "--secret", help="Signing secret (prompted if omitted)")
    p_vow.add_argument("-o", "--output", help="Output path (default: overwrite input)")

    # vow-kept (alias for verify)
    p_vow_kept = sub.add_parser("vow-kept", help="Verify signature (check the Vow)")
    p_vow_kept.add_argument("path", help="Path to .pfm file")
    p_vow_kept.add_argument("-s", "--secret", help="Signing secret (prompted if omitted)")

    # prior-incantato (alias for validate, with provenance)
    p_prior = sub.add_parser("prior-incantato", help="Reveal history and integrity")
    p_prior.add_argument("path", help="Path to .pfm file")

    # export
    p_export = sub.add_parser("export", help="Export .pfm conversations to fine-tuning JSONL")
    p_export.add_argument("path", help="Path to .pfm file or directory")
    p_export.add_argument("-o", "--output", help="Output JSONL file (default: training.jsonl)")
    p_export.add_argument("--format", choices=["openai", "alpaca", "sharegpt"], default="openai", help="Export format (default: openai)")

    # pensieve (alias for export)
    p_pensieve = sub.add_parser("pensieve", help="Extract memories for training (Pensieve)")
    p_pensieve.add_argument("path", help="Path to .pfm file or directory")
    p_pensieve.add_argument("-o", "--output", help="Output JSONL file (default: training.jsonl)")
    p_pensieve.add_argument("--format", choices=["openai", "alpaca", "sharegpt"], default="openai", help="Export format (default: openai)")

    args = parser.parse_args()

    if not args.command:
        print("PFM - Pure Fucking Magic")
        print("AI agent output container format.\n")
        print("Usage:")
        print("  pfm create -a \"my-agent\" -m \"gpt-4\" -c \"Hello world\" -o output.pfm")
        print("  pfm inspect output.pfm")
        print("  pfm read output.pfm content")
        print("  pfm validate output.pfm")
        print("  pfm convert to json output.pfm -o output.json")
        print("  pfm convert from json data.json -o imported.pfm")
        print("  pfm view output.pfm")
        print("  pfm encrypt output.pfm -p mypassword")
        print("  pfm decrypt output.pfm.enc -p mypassword")
        print("  pfm sign output.pfm -s mysecret")
        print("  pfm verify output.pfm -s mysecret")
        print("  pfm export ./conversations/ -o training.jsonl --format openai")
        print("  pfm identify output.pfm")
        print()
        print("Pipe from stdin:")
        print("  echo \"Hello\" | pfm create -a cli -o hello.pfm")
        print("  cat report.txt | pfm create -a importer -m gpt-4 -o report.pfm")
        print()
        print("Spells (aliased commands):")
        print("  pfm accio report.pfm content         Summon a section")
        print("  pfm polyjuice report.pfm json         Transform format")
        print("  pfm fidelius report.pfm               Encrypt (Fidelius Charm)")
        print("  pfm revelio report.pfm.enc            Decrypt (Revelio)")
        print("  pfm unbreakable-vow report.pfm        Sign (Unbreakable Vow)")
        print("  pfm prior-incantato report.pfm        Integrity + provenance")
        print("  pfm pensieve ./conversations/         Extract training data")
        print()
        print("Run 'pfm spells' for the full spellbook.")
        print("Run 'pfm <command> --help' for details on any command.")
        print("Run 'pfm --version' for version info.")
        sys.exit(0)

    commands = {
        "create": cmd_create,
        "inspect": cmd_inspect,
        "read": cmd_read,
        "validate": cmd_validate,
        "convert": cmd_convert,
        "view": cmd_view,
        "encrypt": cmd_encrypt,
        "decrypt": cmd_decrypt,
        "sign": cmd_sign,
        "verify": cmd_verify,
        "identify": cmd_identify,
        "spells": cmd_spells,
        "accio": cmd_accio,
        "polyjuice": cmd_polyjuice,
        "fidelius": cmd_encrypt,
        "revelio": cmd_decrypt,
        "unbreakable-vow": cmd_sign,
        "vow-kept": cmd_verify,
        "prior-incantato": cmd_prior_incantato,
        "export": cmd_export,
        "pensieve": cmd_export,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
