"""
PFM CLI - Command-line interface for Pure Fucking Magic files.

Commands:
  pfm create   - Create a new .pfm file
  pfm inspect  - Show metadata and sections of a .pfm file
  pfm read     - Read a specific section from a .pfm file
  pfm validate - Validate a .pfm file (checksum, structure)
  pfm convert  - Convert to/from JSON, CSV, TXT, Markdown
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


def cmd_convert(args: argparse.Namespace) -> None:
    """Convert to/from PFM."""
    from pfm.reader import PFMReader
    from pfm.converters import convert_to, convert_from
    from pfm.spec import MAX_FILE_SIZE

    if args.direction == "from":
        # Convert other format -> PFM
        input_path = Path(args.input)
        if not input_path.is_file():
            print(f"Error: File not found: {args.input}", file=sys.stderr)
            sys.exit(1)
        file_size = input_path.stat().st_size
        if file_size > MAX_FILE_SIZE:
            print(
                f"Error: File size {file_size} exceeds maximum {MAX_FILE_SIZE} bytes",
                file=sys.stderr,
            )
            sys.exit(1)
        data = input_path.read_text(encoding="utf-8")
        doc = convert_from(data, args.format)
        output = args.output or Path(args.input).stem + ".pfm"
        # Reject path traversal in output path
        if ".." in Path(output).parts:
            print("Error: Output path must not contain '..' (path traversal)", file=sys.stderr)
            sys.exit(1)
        nbytes = doc.write(output)
        print(f"Converted {args.input} -> {output} ({nbytes} bytes)")

    elif args.direction == "to":
        # Convert PFM -> other format
        doc = PFMReader.read(args.input)
        result = convert_to(doc, args.format)
        if args.output:
            # Reject path traversal in output path
            if ".." in Path(args.output).parts:
                print("Error: Output path must not contain '..' (path traversal)", file=sys.stderr)
                sys.exit(1)
            Path(args.output).write_text(result, encoding="utf-8")
            print(f"Converted {args.input} -> {args.output}")
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
    p_convert.add_argument("format", choices=["json", "csv", "txt", "md"], help="Target/source format")
    p_convert.add_argument("input", help="Input file path")
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
        "view": cmd_view,
        "encrypt": cmd_encrypt,
        "decrypt": cmd_decrypt,
        "sign": cmd_sign,
        "verify": cmd_verify,
        "identify": cmd_identify,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
