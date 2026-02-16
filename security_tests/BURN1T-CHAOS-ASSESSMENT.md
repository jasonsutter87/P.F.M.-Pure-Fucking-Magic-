# Chaos Assessment - Burn1t

**Date:** 2026-02-16
**Project:** PFM (Pure Fucking Magic) - AI agent output container format
**Scope:** /Users/jasonsutter/Documents/Companies/pfm (local code only - STRICT)
**Analyst:** Burn1t Chaos Agent

## Scope Verification

- [x] Within allowed project boundary
- [x] Analysis only - NO destructive actions taken
- [x] All file paths reference /Users/jasonsutter/Documents/Companies/pfm only

---

## Executive Summary

PFM is a text-based file format library with streaming write, crash recovery, encryption, signing, and format conversion capabilities. The codebase has **7 CRITICAL**, **4 HIGH**, and **3 MEDIUM** destruction vectors. The worst-case scenario involves a crafted .pfm file that causes unbounded memory allocation (OOM kill), combined with abuse of the crash recovery system to corrupt or destroy existing data. The format's text-based nature and lack of size limits create a broad attack surface for resource exhaustion.

---

## NIGHTMARE SCENARIOS

### Scenario 1: "Memory Bomb" - Crafted .pfm Causes OOM Kill (CRITICAL)

**Trigger:** An attacker crafts a .pfm file with a forged index containing massive offset+length values, or simply a multi-gigabyte content section.

**The Code:**
```python
# reader.py line 89-91 (PFMReader.read)
@classmethod
def read(cls, path: str | Path) -> PFMDocument:
    with open(path, "rb") as f:
        data = f.read()       # <-- READS ENTIRE FILE INTO MEMORY, NO SIZE LIMIT
    return cls.parse(data)
```

```python
# reader.py line 180-183 (PFMReader.open)
@classmethod
def open(cls, path: str | Path) -> PFMReaderHandle:
    f = builtins_open(path, "rb")
    raw = f.read()            # <-- ALSO READS ENTIRE FILE, NO SIZE LIMIT
    f.seek(0)
    reader = PFMReaderHandle(f, raw)
```

**Cascade:** Both `read()` and `open()` load the ENTIRE file into memory unconditionally. There is zero size validation. A 10GB .pfm file will attempt to allocate 10GB of RAM. On systems with limited memory (containers, CI/CD workers, serverless functions), this is an instant OOM kill.

**Blast Radius:**
- Any process that calls `PFMReader.read()`, `PFMReader.open()`, or any CLI command (`pfm inspect`, `pfm validate`, `pfm read`, `pfm convert`)
- Any automated pipeline that processes .pfm files from untrusted sources
- If PFM is used in a web service, a single uploaded file kills the worker

**Recovery Time:** Seconds (process restart), but can be used for repeated DoS

**Public Impact:** "AI file format library crashes servers with a single file upload"

**PoC Scenario:**
```
Craft a file:
  #!PFM/1.0
  #@meta
  id: bomb
  #@index
  content 100 999999999
  #@content
  [minimal data]
  #!END

The reader loads this fine, but PFMReaderHandle.get_section() at line 280:
  return self._raw[offset:offset + length].decode("utf-8")
will attempt to slice with fabricated offset/length values.

Even simpler: just make a file that is 10GB of repeated content.
```

---

### Scenario 2: "Recovery Weapon" - Crash Recovery Destroys Data (CRITICAL)

**Trigger:** An attacker provides a malicious file to a system using `PFMStreamWriter(path, append=True)`, or triggers append mode on a file that has been tampered with.

**The Code:**
```python
# stream.py line 169-238 (_recover function)
def _recover(path: Path) -> tuple:
    raw = path.read_bytes()           # Reads entire file
    text = raw.decode("utf-8")
    lines = text.split("\n")
    ...
    # Line 234-236: OPENS THE FILE AND TRUNCATES IT
    handle = open(path, "r+b")
    handle.seek(truncate_at)
    handle.truncate()                 # <-- DESTROYS DATA IN THE EXISTING FILE
    return handle, sections
```

**Cascade:** The `_recover()` function opens the existing file in `r+b` mode and TRUNCATES it. If the truncation point is calculated incorrectly (due to a crafted file with ambiguous markers), the function can destroy legitimate data. The `text.index(line)` call on line 226 finds the FIRST occurrence of the marker string, which may not be the correct one if the content sections contain text that looks like PFM markers.

**Critical Detail - `text.index()` Confusion Attack:**
```python
# stream.py line 225-226
if line.startswith(f"{SECTION_PREFIX}index:trailing") or line.startswith(EOF_MARKER):
    truncate_at = text.index(line)    # <-- FINDS FIRST OCCURRENCE, NOT THE CORRECT ONE
```

If a content section contains the literal text `#@index:trailing` or `#!END`, the `text.index(line)` call will find that embedded text FIRST (since it appears earlier in the file than the real trailing markers). The truncation point will be set INSIDE the content, destroying all data after that point.

**Blast Radius:**
- Any .pfm file opened with `append=True`
- Long-running agent tasks that use crash recovery
- The "4-hour agent task crashes at hour 3" scenario this feature was built to solve -- recovery itself could destroy the first 3 hours of work

**Recovery Time:** Permanent data loss -- the file is truncated on disk. No backup is made.

**Public Impact:** "PFM crash recovery feature destroys the data it was supposed to save"

**PoC Scenario:**
```
Create a .pfm file where content contains:
  #@index:trailing
  fake_section 0 0
  #!END:0

Then open with PFMStreamWriter(path, append=True).
_recover() will find the embedded markers first, set truncate_at to inside the content,
and destroy everything after that point.
```

---

### Scenario 3: "Section Injection" - Format Confusion Breaks Parser Integrity (CRITICAL)

**Trigger:** Content that contains PFM section markers (`#@`, `#!PFM`, `#!END`) causes the parser to misinterpret file structure.

**The Code:**
```python
# reader.py line 106-167 (PFMReader.parse)
while i < len(lines):
    line = lines[i]
    if line.startswith(MAGIC):     # No escaping, no quoting
        ...
    if line.startswith(EOF_MARKER): # Content that starts with #!END terminates parsing
        break
    if line.startswith(SECTION_PREFIX):  # Content that starts with #@ creates phantom sections
        ...
```

**Cascade:** The parser has NO escaping mechanism. Any content line that begins with `#@` will be interpreted as a new section boundary. Any line beginning with `#!END` will terminate parsing early, silently discarding all subsequent sections. Any line beginning with `#!PFM` will be treated as a magic line.

The existing test `test_special_characters_in_content` (test_e2e.py line 150-162) acknowledges this:
```python
tricky = "#!PFM/1.0\n#@content\nfake section\n#!END"
doc = PFMDocument.create(agent="tricky")
doc.add_section("content", tricky)
# The assertion only checks content "is not None" -- it does NOT verify the content survived intact
```

**This test actually documents the vulnerability without testing for correctness.**

**Blast Radius:**
- Any .pfm file containing code snippets, shell scripts, or documentation that references PFM format markers
- Agent output that discusses PFM itself (meta/self-referential content)
- Conversion from formats that naturally contain `#` prefixed lines (Markdown headers, Python comments, shell scripts)

**Impact:** Silent data corruption. Sections are split, merged, or lost without any error.

**PoC Scenario:**
```
An agent writes a .pfm file containing Python code as content:
  # Check if file is PFM
  #!PFM/1.0  <-- parser thinks this is a new file magic
  #@meta      <-- parser thinks this is a meta section start
  ...

Reading this back silently destroys the content structure.
```

---

### Scenario 4: "Encryption Denial" - Corrupt Encrypted Files Beyond Recovery (CRITICAL)

**Trigger:** Flip a single bit in an encrypted .pfm.enc file.

**The Code:**
```python
# security.py line 131-151 (decrypt_bytes)
def decrypt_bytes(encrypted: bytes, password: str) -> bytes:
    salt = encrypted[:16]
    nonce = encrypted[16:28]
    ciphertext = encrypted[28:]
    key = _derive_key(password, salt)
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, None)  # Raises InvalidTag on ANY corruption
```

**Cascade:** AES-256-GCM is an authenticated encryption mode. ANY modification to the salt, nonce, or ciphertext -- even a single flipped bit -- will cause decryption to fail with an `InvalidTag` exception. There is no error correction, no redundancy, and no partial recovery capability.

Furthermore, the header parsing is fragile:
```python
# security.py line 180
header_end = data.index(b"\n") + 1  # If the newline is corrupted, this crashes with ValueError
```

**Blast Radius:**
- All encrypted .pfm.enc files
- No mechanism for key backup, key rotation, or recovery
- If the password is lost, data is gone forever (by design, but there is no warning in the API)
- Bit rot on storage media (SSDs, HDDs) will eventually corrupt encrypted files

**Recovery Time:** Never. The data is unrecoverable.

**Public Impact:** "Encrypted PFM files are one bit-flip away from permanent data loss"

---

### Scenario 5: "PBKDF2 CPU Bomb" - Encryption as DoS Vector (HIGH)

**Trigger:** Force the system to call `encrypt_bytes` or `decrypt_bytes` repeatedly.

**The Code:**
```python
# security.py line 94-102
def _derive_key(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations=600_000,  # 600K iterations -- intentionally slow
        dklen=32,
    )
```

**Cascade:** Each encryption/decryption call runs 600,000 PBKDF2 iterations. This is CPU-intensive by design (to resist brute force), but if an attacker can trigger decrypt attempts on a service (e.g., uploading encrypted .pfm files that force decryption attempts with wrong passwords), they can burn significant CPU. There is no rate limiting in the library.

**Blast Radius:** Any service that auto-decrypts uploaded .pfm.enc files

**Recovery Time:** Ongoing -- each attempt burns ~0.5-2 seconds of CPU

---

### Scenario 6: "Checksum Bypass" - Integrity Verification is Optional and Flawed (CRITICAL)

**Trigger:** Tamper with file content while leaving the checksum field empty or removing it.

**The Code:**
```python
# security.py line 196-203
def verify_integrity(doc: PFMDocument) -> bool:
    if not doc.checksum:
        return True  # <-- NO CHECKSUM = AUTOMATICALLY "VALID"
    return doc.checksum == doc.compute_checksum()
```

```python
# reader.py line 297-313 (validate_checksum)
def validate_checksum(self) -> bool:
    expected = self.meta.get("checksum", "")
    if not expected:
        return True  # <-- SAME: NO CHECKSUM = "VALID"
```

**Cascade:** Both integrity verification functions return `True` when no checksum is present. An attacker can tamper with ANY .pfm file and simply remove the `checksum:` line from the meta section. The file will pass all validation checks.

The CLI `pfm validate` command will print `OK` for tampered files with no checksum.

**Blast Radius:** Every .pfm file. The integrity system provides a false sense of security.

**Recovery Time:** N/A -- this is a design flaw

**PoC Scenario:**
```
1. Take any signed/checksummed .pfm file
2. Remove the "checksum: <hash>" line from the #@meta section
3. Modify any content you want
4. pfm validate <file> --> "OK: file is valid PFM"
```

---

### Scenario 7: "Signature Stripping" - HMAC Verification Fails Open (CRITICAL)

**Trigger:** Remove the signature fields from a signed document.

**The Code:**
```python
# security.py line 47-70
def verify(doc: PFMDocument, secret: str | bytes) -> bool:
    stored_sig = doc.custom_meta.get("signature", "")
    if not stored_sig:
        return False          # Returns False, but...
```

**Cascade:** While `verify()` correctly returns False for unsigned documents, the problem is that **there is no mechanism to require signatures**. No field in the format says "this document MUST be signed." An attacker can:

1. Strip the `signature` and `sig_algo` custom_meta fields
2. Modify content freely
3. Re-sign with their own key
4. The receiving system has no way to know the original signing key was different

Furthermore, the signing message construction includes the checksum in meta:
```python
# security.py line 73-87
def _build_signing_message(doc: PFMDocument) -> bytes:
    for key in sorted(doc.get_meta_dict().keys()):
        val = doc.get_meta_dict()[key]
        parts.append(f"{key}={val}".encode("utf-8"))
```

But `PFMWriter.serialize()` recomputes the checksum on every write (line 28: `doc.checksum = doc.compute_checksum()`), which changes the signing message and invalidates previously computed signatures. The test at line 66-91 of test_security.py has to work around this by pre-computing the checksum before signing. This is a footgun: the natural workflow of `sign then write` breaks signatures silently.

**Blast Radius:** Any workflow relying on HMAC signatures for document authenticity

---

### Scenario 8: "Index Poisoning" - Fabricated Index Points to Arbitrary Data (CRITICAL)

**Trigger:** Craft a .pfm file where the index entries contain offset/length values that point to the wrong data.

**The Code:**
```python
# reader.py line 274-280 (PFMReaderHandle.get_section)
def get_section(self, name: str) -> str | None:
    entry = self.index.get(name)
    if entry is None:
        return None
    offset, length = entry
    return self._raw[offset:offset + length].decode("utf-8")  # Trusts index blindly
```

**Cascade:** The indexed reader (`PFMReader.open()`) trusts the index entries completely. There is NO validation that:
- Offsets are within file bounds
- Offsets actually point to the correct section
- Lengths are accurate
- Offsets don't overlap with meta or index sections

An attacker can craft index entries that:
1. Point `content` to the `meta` section (leaking metadata like signatures)
2. Point to offsets beyond the file (causing IndexError or returning empty/garbage)
3. Point multiple section names to the same data (confusion)
4. Use negative offsets (Python slicing handles these, creating surprising results -- `self._raw[-100:-100+50]` is valid)

**Blast Radius:** Any system using indexed access (`PFMReader.open()`, `accio()`, CLI commands)

**PoC Scenario:**
```
#!PFM/1.0
#@meta
id: evil
agent: attacker
signature: real_hmac_signature_here
#@index
content 15 40
#@content
innocent looking text
#!END

The index says "content starts at byte 15 with length 40" -- but byte 15 is
actually inside the meta section, so reading "content" returns metadata
including the signature value.
```

---

### Scenario 9: "Stream Writer Race Condition" - Concurrent Access Corrupts Files (HIGH)

**Trigger:** Two processes/threads open the same file with `PFMStreamWriter`.

**The Code:**
```python
# stream.py line 83
self._handle = open(self.path, "wb")  # No file locking
```

```python
# stream.py line 73-81 (append mode)
if append and self.path.exists():
    self._handle, self._sections = _recover(self.path)
    raw = self.path.read_bytes()      # Read
    ...
    # Between read_bytes() and the file handle operations, another process can modify the file
```

**Cascade:** There is no file locking mechanism (no `fcntl.flock`, no advisory locks, no `.lock` files). The append/recovery path has a classic TOCTOU (time-of-check-time-of-use) race:
1. Process A reads the file and computes truncation point
2. Process B writes new data to the file
3. Process A truncates, destroying Process B's data

**Blast Radius:** Any multi-process or multi-agent system sharing .pfm files

**Recovery Time:** Permanent data loss for the corrupted sections

---

### Scenario 10: "setattr Injection" - Metadata Overwrites Object Attributes (HIGH)

**Trigger:** Craft a .pfm file with meta keys that match Python object attribute names.

**The Code:**
```python
# reader.py line 145-148 (parse meta)
if hasattr(doc, key) and key != "custom_meta":
    setattr(doc, key, val)           # <-- SETS ARBITRARY ATTRIBUTES
else:
    doc.custom_meta[key] = val
```

```python
# converters.py line 108-109 (from_csv)
if key in reserved and hasattr(doc, key):
    setattr(doc, key, value)         # <-- ALSO HERE
```

```python
# converters.py line 203-208 (from_markdown)
if key in reserved and hasattr(doc, key):
    setattr(doc, key, val)           # <-- AND HERE
```

**Cascade:** The `reader.py` parser calls `setattr(doc, key, val)` for ANY key that matches a `hasattr` check. While PFMDocument is a dataclass with specific fields, `hasattr` also returns True for inherited attributes and methods. The check `key != "custom_meta"` prevents one specific case but not others.

Specifically, crafted meta keys could set:
- `sections` -> overwrite the sections list with a string
- `format_version` -> set to garbage
- `__class__`, `__dict__` -> depends on Python version behavior

The `from_csv` and `from_markdown` converters have the same pattern but with a `reserved` set that limits the attack to the 8 known field names. The reader.py parser has a broader `hasattr` check.

**Blast Radius:** Any system that processes untrusted .pfm files or untrusted CSV/Markdown conversions

**PoC Scenario:**
```
#!PFM/1.0
#@meta
id: normal
sections: overwritten
format_version: 99.99
```

---

### Scenario 11: "Disk Filler" - Streaming Writer Has No Size Limits (HIGH)

**Trigger:** A compromised or misbehaving agent writes indefinitely to a stream.

**The Code:**
```python
# stream.py line 103-127
def write_section(self, name: str, content: str) -> None:
    # No size check on content
    # No total file size check
    # No section count limit
    content_bytes = content.encode("utf-8")
    self._handle.write(content_bytes)
    self._handle.flush()
    os.fsync(self._handle.fileno())   # Forces to disk immediately
```

**Cascade:** The streaming writer:
- Has no maximum file size
- Has no maximum section size
- Has no maximum section count
- Calls `os.fsync()` after every write, ensuring data hits disk immediately
- Cannot be rate-limited from within the library

An agent that writes in a loop will fill the disk. The fsync ensures no kernel buffer tricks can delay the impact.

**Blast Radius:** The entire filesystem where the .pfm file resides

**Recovery Time:** Hours (disk cleanup, potentially lost data from other applications)

---

### Scenario 12: "Unicode Decoder Bomb" - Malformed UTF-8 Crashes Parser (MEDIUM)

**Trigger:** Provide a file with invalid UTF-8 byte sequences.

**The Code:**
```python
# reader.py line 96
text = data.decode("utf-8")           # Raises UnicodeDecodeError on invalid UTF-8

# reader.py line 212
text = raw.decode("utf-8")            # Same

# stream.py line 176
text = raw.decode("utf-8")            # Same in recovery
```

**Cascade:** Every decode call uses strict mode (the default). A single invalid byte anywhere in the file causes an unhandled `UnicodeDecodeError`. The CLI catches this generically in `cmd_validate` but NOT in `cmd_inspect`, `cmd_read`, or `cmd_convert`.

**Blast Radius:** Any .pfm file with byte-level corruption or intentionally crafted invalid UTF-8

---

### Scenario 13: "Newline Accumulation" - Round-trip Write/Read Corrupts Content (MEDIUM)

**Trigger:** Repeatedly write and read a .pfm file.

**The Code:**
```python
# writer.py line 36-37
if not content_bytes.endswith(b"\n"):
    content_bytes += b"\n"            # Adds newline if missing

# reader.py line 127-128
if content.endswith("\n"):
    content = content[:-1]            # Strips ONE trailing newline
```

**Cascade:** The writer ensures content ends with `\n`. The reader strips one trailing `\n`. This is balanced for a single round-trip. But if content ALREADY ends with `\n`, the writer does NOT add another one, and the reader strips the existing one, REMOVING a legitimate trailing newline from the content. After multiple round-trips, trailing newlines accumulate or disappear depending on the original content.

**Blast Radius:** Any pipeline that reads, modifies, and re-writes .pfm files repeatedly

---

### Scenario 14: "CLI Path Traversal" - Read Arbitrary Files via --file Flag (MEDIUM)

**Trigger:** Use the CLI `create` command with a crafted `--file` path.

**The Code:**
```python
# cli.py line 33
content = Path(args.file).read_text(encoding="utf-8")   # No path validation
```

**Cascade:** The `--file` flag reads any file the process has access to. While this is "by design" for a CLI tool, if PFM is wrapped in a web service or API that exposes the create functionality, this becomes a file read vulnerability. No path sanitization, no allowlist, no chroot.

**Blast Radius:** Depends on deployment context

---

## Single Points of Failure

| Component | Failure Impact | Backup Exists? | Recovery Plan? |
|-----------|---------------|----------------|----------------|
| File read (reader.py:89-91) | OOM on large files | No | None - process dies |
| Crash recovery (stream.py:234-236) | Truncates existing data | No backup before truncation | None - data destroyed |
| Index entries (reader.py:274-280) | Returns wrong data for sections | No validation | None - silent corruption |
| UTF-8 decode (reader.py:96) | Unhandled exception crashes parse | No fallback encoding | None |
| Checksum field (security.py:201) | Missing checksum = auto-valid | No mandatory checksum | None |
| Encryption (security.py:131) | Single bit-flip = total data loss | No error correction | None |
| File handle (stream.py:83) | No file locking | No lock mechanism | None |
| Writer checksum recompute (writer.py:28) | Invalidates pre-computed signatures | No signature preservation | Manual workaround (pre-compute checksum) |

---

## Destruction Vectors (Ranked by Impact)

| # | Vector | Method | Impact | Difficulty |
|---|--------|--------|--------|------------|
| 1 | Memory Bomb | Craft large .pfm or fabricated index lengths | OOM kill, DoS | TRIVIAL |
| 2 | Recovery Data Destruction | Embed markers in content, trigger append mode | Permanent data loss | LOW |
| 3 | Section Injection | Content containing #@ or #!END markers | Silent data corruption | TRIVIAL |
| 4 | Index Poisoning | Fabricate offset/length values in index | Data leakage, corruption | LOW |
| 5 | Checksum Bypass | Remove checksum line from meta | Undetected tampering | TRIVIAL |
| 6 | Signature Stripping | Remove signature fields, re-sign with new key | Authentication bypass | LOW |
| 7 | Encryption Denial | Flip single bit in .pfm.enc file | Permanent data loss | TRIVIAL |
| 8 | Disk Fill | Continuous stream writes with no limits | Filesystem exhaustion | LOW |
| 9 | Race Condition | Concurrent writers on same file | Data corruption | MEDIUM |
| 10 | setattr Injection | Crafted meta keys matching object attributes | Object state corruption | LOW |
| 11 | PBKDF2 CPU Burn | Trigger repeated decrypt attempts | CPU exhaustion | LOW |
| 12 | UTF-8 Bomb | Invalid byte sequences in file | Parser crash | TRIVIAL |
| 13 | Newline Corruption | Round-trip files with trailing newlines | Silent content mutation | TRIVIAL |
| 14 | CLI Path Traversal | Crafted --file argument | Arbitrary file read | Context-dependent |

---

## Resilience Gaps

### No Input Validation
- **No maximum file size** on read or write
- **No maximum section size** or section count
- **No maximum meta field count** or meta value length
- **No validation of index offset/length** against actual file boundaries
- **No validation of UTF-8** before attempting full decode
- **No escaping mechanism** for content containing format markers

### No Data Protection
- **No backup before recovery truncation** -- _recover() destroys data in-place
- **No file locking** -- concurrent access silently corrupts
- **No write-ahead log** -- partial writes are unrecoverable
- **No error correction** on encrypted files -- single bit-flip = total loss

### No Security Enforcement
- **Checksums are optional** -- missing checksum = valid
- **Signatures have no binding** -- can be stripped without detection
- **No key management** -- passwords are passed as strings
- **Signing order footgun** -- write() recomputes checksum, invalidating signatures

### No Monitoring / Observability
- **No logging** anywhere in the library
- **No metrics** for file sizes, parse times, error rates
- **No warnings** for suspicious inputs (huge files, missing checksums, marker-like content)

---

## Recommendations for Red Team

### P0 - Critical (Fix Before Any Untrusted Input)

1. **Add maximum file size enforcement in reader** -- both `read()` and `open()` must check file size before loading. Default to a sane limit (e.g., 100MB) with an explicit opt-in for larger files.

2. **Fix crash recovery to backup before truncation** -- `_recover()` must copy the original file before truncating. Consider writing to a new temp file and atomic-renaming.

3. **Implement content escaping** -- any content line starting with `#!` or `#@` must be escaped on write and unescaped on read. Without this, the format is fundamentally unsafe for arbitrary content.

4. **Validate index entries against file boundaries** -- `get_section()` must verify that `offset >= 0`, `offset + length <= len(self._raw)`, and that the referenced data is within a content section.

5. **Make checksum validation mandatory or clearly advisory** -- either require checksums and fail on missing/invalid, or rename the function to `checksum_matches_if_present()` so the API does not create a false sense of security.

### P1 - High (Fix Before Production Use)

6. **Add file locking to stream writer** -- use `fcntl.flock()` or equivalent to prevent concurrent access corruption.

7. **Fix the sign-then-write footgun** -- either `serialize()` should not recompute checksum if a signature exists, or provide a `sign_and_serialize()` atomic operation.

8. **Add streaming/chunked reader** -- for indexed access, only mmap or read the requested byte range, not the entire file.

9. **Add size limits to stream writer** -- configurable max file size, max section size, max section count.

### P2 - Medium (Fix Before Wider Adoption)

10. **Handle UTF-8 errors gracefully** -- use `errors="replace"` or `errors="surrogateescape"` with explicit warnings.

11. **Fix newline round-trip behavior** -- preserve trailing newlines exactly as provided.

12. **Add structured logging** -- emit warnings for large files, missing checksums, marker-like content.

13. **Document the `setattr` behavior** -- restrict the `hasattr/setattr` pattern to an explicit allowlist matching `META_FIELDS` from spec.py.

---

## Maximum Blast Radius Scenario

**Title:** "The Perfect Storm"

A single crafted .pfm file simultaneously exploits vectors 2, 3, and 4:

1. It contains content with embedded `#@index:trailing` and `#!END` markers (section injection)
2. It has a fabricated index pointing content to the signature metadata (index poisoning)
3. When a crash recovery system opens it with `append=True`, the embedded markers cause `_recover()` to truncate the file at the wrong point, destroying all legitimate data

The result: a file that **reads as valid**, **returns wrong data for sections**, **passes checksum validation** (because checksum was removed), and **destroys itself when recovery is attempted**.

This is the worst case for PFM: silent corruption followed by catastrophic data loss on recovery.
