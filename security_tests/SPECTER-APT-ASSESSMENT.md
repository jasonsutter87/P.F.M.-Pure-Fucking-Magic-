# APT Simulation Report - Specter
**Date:** 2026-02-16
**Project:** PFM (Pure Fucking Magic) -- AI Agent Output Container Format
**Scope:** /Users/jasonsutter/Documents/Companies/pfm (local code only -- STRICT)
**Threat Model:** Nation-State Actor (Simulated Analysis)
**Analyst:** Specter APT Simulator (Opus 4.6)

## Scope Verification
- [x] Within allowed project boundary
- [x] Simulation only -- no actual attacks executed
- [x] No files modified except this report
- [x] No network connections attempted
- [x] No elevated privileges used

---

## Executive Summary

PFM is a text-based file format library with **zero runtime dependencies** (only stdlib), which dramatically reduces supply-chain attack surface. However, the format's design -- text-based sections with inline markers, indexed byte offsets, streaming append mode, and a parser that trusts offset values -- creates several exploitable vectors that a nation-state actor would target for **persistence**, **data exfiltration**, and **integrity subversion**.

The most dangerous findings center on:
1. **Section marker injection** enabling steganographic data hiding and parser confusion
2. **Index offset poisoning** enabling arbitrary read-beyond-bounds
3. **Stream append mode** enabling persistent backdoor sections that survive "crash recovery"
4. **Crypto gaps** that allow signature bypass, downgrade, and timing-based oracle attacks
5. **setattr-based meta parsing** enabling attribute injection on the document model

**Overall APT Exploitability Rating: HIGH**

---

## Kill Chain Analysis

### 1. Initial Access Vectors

#### 1.1 CRITICAL -- Section Marker Injection (Content Confusion Attack)
**Severity:** CRITICAL
**File:** `/Users/jasonsutter/Documents/Companies/pfm/pfm/reader.py`, lines 106-175
**MITRE ATT&CK:** T1059 (Command and Scripting Interpreter), T1027 (Obfuscated Files)

The parser in `PFMReader.parse()` processes lines sequentially and checks for section markers (`#@`) and structural markers (`#!PFM`, `#!END`) on each line. **There is no escaping mechanism.** Content that begins with `#@` on a new line will be interpreted as a new section header.

```python
# reader.py line 121-137
if line.startswith(SECTION_PREFIX):
    # Flush previous section
    ...
    section_name = line[len(SECTION_PREFIX):]  # Attacker controls this
    current_section = section_name
```

**Attack Chain:**
1. Attacker crafts a .pfm file where a "content" section contains a line starting with `#@malicious_section`
2. Parser splits the content section prematurely and creates a phantom section
3. The phantom section's name and content are fully attacker-controlled
4. Applications consuming the PFM document may process the injected section as legitimate
5. If the consuming application acts on section names (e.g., "tools", "chain", "reasoning"), the attacker can inject false tool calls, fake reasoning chains, or spoofed metadata

**The project's own test suite acknowledges this:**
```python
# test_e2e.py line 150-161
def test_special_characters_in_content(self):
    """Content with characters that look like PFM markers."""
    tricky = "#!PFM/1.0\n#@content\nfake section\n#!END"
    doc = PFMDocument.create(agent="tricky")
    doc.add_section("content", tricky)
    # The content should be preserved as-is
    # (This is a known edge case - section markers in content)
    assert loaded.content is not None  # NOTE: does NOT assert content == tricky
```

The test intentionally avoids asserting exact content preservation -- confirming the vulnerability exists and is unresolved.

**README.md also acknowledges:**
```
Section markers in content -- content containing #@ or #!PFM on a line start is an edge case (escaping spec TBD)
```

**APT Exploitation:** An APT29-style actor would use this to inject invisible "reasoning" or "tools" sections into .pfm files that pass through AI agent pipelines, poisoning downstream agents' context without detection.

---

#### 1.2 HIGH -- Attribute Injection via setattr in Meta Parsing
**Severity:** HIGH
**File:** `/Users/jasonsutter/Documents/Companies/pfm/pfm/reader.py`, lines 140-148

```python
# reader.py lines 140-148
if in_meta:
    if ": " in line:
        key, val = line.split(": ", 1)
        key = key.strip()
        val = val.strip()
        if hasattr(doc, key) and key != "custom_meta":
            setattr(doc, key, val)   # <--- DANGEROUS
        else:
            doc.custom_meta[key] = val
```

The parser uses `setattr(doc, key, val)` where `key` comes from untrusted file content. The only guard is `hasattr(doc, key) and key != "custom_meta"`. This means a crafted .pfm file can overwrite:
- `doc.format_version` -- enabling downgrade attacks (see Section 4)
- `doc.sections` -- replacing the sections list with a string (crashes or confuses consumers)
- `doc.checksum` -- pre-setting a checksum to bypass integrity validation
- Any dataclass field including `id`, `agent`, `model`, `created`

**Attack Chain:**
1. Craft a .pfm file with meta line: `sections: []` or `format_version: 0.1`
2. `hasattr(doc, "sections")` returns True (it is a dataclass field)
3. `setattr(doc, "sections", "[]")` replaces the list with the string "[]"
4. Any code calling `doc.sections` or iterating over it breaks unpredictably

More insidiously:
1. Craft meta line: `checksum: <attacker_computed_hash>`
2. This sets doc.checksum before sections are parsed
3. After parsing, `verify_integrity()` compares doc.checksum (attacker value) against computed
4. Attacker can pre-compute the hash of their modified content so integrity check passes

---

#### 1.3 HIGH -- CLI Path Traversal via --file Flag
**Severity:** HIGH
**File:** `/Users/jasonsutter/Documents/Companies/pfm/pfm/cli.py`, line 33

```python
if args.file:
    content = Path(args.file).read_text(encoding="utf-8")
```

The `--file` argument is passed directly to `Path.read_text()` with no sanitization, path canonicalization, or access control. A user (or automated pipeline) running `pfm create --file /etc/shadow` or `pfm create --file ../../../.ssh/id_rsa` would embed sensitive file contents into a .pfm file.

**APT Exploitation:** If the PFM CLI is integrated into an AI agent pipeline or CI/CD system, an attacker who can influence the `--file` parameter can exfiltrate arbitrary system files by embedding them into PFM output that gets stored, transmitted, or logged.

---

### 2. Persistence Opportunities

#### 2.1 CRITICAL -- Stream Append Mode Persistent Backdoor Sections
**Severity:** CRITICAL
**File:** `/Users/jasonsutter/Documents/Companies/pfm/pfm/stream.py`, lines 169-238

The `_recover()` function in the streaming writer is designed to recover from crashes by scanning for section markers and rebuilding the index. It then **truncates** the file at the trailing index/EOF and opens it for appending.

```python
# stream.py lines 222-236
truncate_at = len(raw)
for line in reversed(lines):
    if line.startswith(f"{SECTION_PREFIX}index:trailing") or line.startswith(EOF_MARKER):
        truncate_at = text.index(line)
        truncate_at = len(text[:truncate_at].encode("utf-8"))
        break
    elif line.strip() == "":
        continue
    else:
        break

handle = open(path, "r+b")
handle.seek(truncate_at)
handle.truncate()
```

**Attack Chain (APT41 Long-Term Persistence):**
1. Attacker modifies a stream .pfm file to inject a section between existing sections
2. The injected section survives crash recovery because `_recover()` scans forward through ALL `#@` markers
3. When the application resumes with `append=True`, the injected section is preserved in the rebuilt section list
4. The attacker's section persists across multiple crash-recovery cycles
5. If the section name is something innocuous like "context" or "metrics", it will not be noticed

**Additional `_recover()` vulnerability:**
```python
# stream.py line 225
truncate_at = text.index(line)
```

`text.index(line)` finds the **first** occurrence of the line content. If the attacker injects a fake `#@index:trailing` earlier in the file, `text.index()` will match that instead of the real trailing index, causing truncation at the wrong point and potentially corrupting the file or preserving attacker-injected content.

---

#### 2.2 HIGH -- Checksum Bypass Enables Undetectable Modification
**Severity:** HIGH
**File:** `/Users/jasonsutter/Documents/Companies/pfm/pfm/reader.py`, lines 297-313
**File:** `/Users/jasonsutter/Documents/Companies/pfm/pfm/security.py`, lines 196-203

```python
# reader.py line 301
if not expected:
    return True  # No checksum to validate

# security.py line 201
if not doc.checksum:
    return True  # No checksum stored
```

Both `validate_checksum()` and `verify_integrity()` return `True` when no checksum is present. This means:
1. An attacker who strips the checksum from the meta section creates a file that passes all validation
2. The consuming application has no way to distinguish "file was never checksummed" from "file was modified"
3. Combined with attribute injection (2.1.2), an attacker can replace the checksum with their own computed hash

**This is the cryptographic equivalent of "the door has a lock, but if you remove the lock the guard waves you through."**

---

### 3. Stealth Data Exfiltration Vectors

#### 3.1 CRITICAL -- Steganographic Data Hiding via Index Offset Manipulation
**Severity:** CRITICAL
**Files:** `/Users/jasonsutter/Documents/Companies/pfm/pfm/reader.py`, lines 274-280

```python
def get_section(self, name: str) -> str | None:
    entry = self.index.get(name)
    if entry is None:
        return None
    offset, length = entry
    return self._raw[offset:offset + length].decode("utf-8")
```

The indexed reader trusts the offset and length values from the index section **without any bounds checking or validation against actual section marker positions**. This creates a powerful steganographic channel:

**Attack Chain (APT29 Data Exfiltration):**
1. Create a .pfm file with normal-looking content sections
2. Append hidden data AFTER the `#!END` marker (the parser stops at `#!END`, but the bytes exist in the file)
3. Craft the index to contain an entry with an offset pointing beyond `#!END` to the hidden payload
4. Alternatively: manipulate offsets so sections overlap, with the "visible" section appearing normal while the index points to a different byte range containing exfiltrated data
5. `pfm inspect` shows normal section names and sizes
6. `pfm validate` passes (checksum covers only indexed sections, and the checksum is computed from the same manipulated offsets)
7. The hidden data is only accessible to someone who knows to look at the raw bytes or uses the secret index entry name

**No bounds validation exists anywhere in the codebase.** The reader will happily read bytes from anywhere in the file buffer as long as `offset + length <= len(self._raw)`.

---

#### 3.2 HIGH -- Custom Section Steganography
**Severity:** HIGH
**File:** `/Users/jasonsutter/Documents/Companies/pfm/pfm/spec.py`, lines 43-54

The format explicitly allows arbitrary custom section names:
```python
SECTION_TYPES = {
    "meta": "...", "index": "...", "content": "...",
    "chain": "...", "tools": "...", "artifacts": "...",
    ...
}
```

But these are merely documentation -- the code never validates section names against this list. An attacker can create sections with names like:
- `x` (single character -- easily overlooked)
- `metrics_cache` (looks like an internal caching artifact)
- A name containing Unicode zero-width characters that appears blank in terminal output

The content of these sections passes through all validation (checksum covers them, signature covers them), making them legitimate-looking containers for exfiltrated data.

---

#### 3.3 MEDIUM -- Custom Meta Field Exfiltration Channel
**Severity:** MEDIUM
**File:** `/Users/jasonsutter/Documents/Companies/pfm/pfm/document.py`, lines 44-46, 106

```python
custom_meta: dict[str, str] = field(default_factory=dict)
...
meta.update(self.custom_meta)
```

Custom meta fields are unlimited in number and size. An attacker can embed encoded data in custom meta fields with innocuous-sounding names like `cache_id`, `trace_id`, `correlation_token`, etc. These survive serialization/deserialization and are included in JSON/CSV/MD conversions.

---

### 4. Version Downgrade / Upgrade Attacks

#### 4.1 HIGH -- Format Version is Cosmetic Only
**Severity:** HIGH
**File:** `/Users/jasonsutter/Documents/Companies/pfm/pfm/reader.py`, lines 110-113

```python
if line.startswith(MAGIC):
    version_part = line.split("/", 1)[1] if "/" in line else "1.0"
    doc.format_version = version_part.split(":")[0]
```

The format version is parsed but **never validated or acted upon**. There is:
- No minimum version enforcement
- No maximum version check
- No version-specific parsing behavior
- No rejection of unknown versions

**Attack Chain:**
1. Set `#!PFM/0.0` and the file still parses normally
2. Set `#!PFM/99.0` and the file still parses normally
3. If a future PFM version adds security features (e.g., mandatory signatures), an attacker can simply set version `1.0` to bypass them
4. Combined with attribute injection (Section 1.2), `format_version` can be overwritten via meta field injection

---

#### 4.2 MEDIUM -- Stream Flag Has No Security Implications
**Severity:** MEDIUM
**File:** `/Users/jasonsutter/Documents/Companies/pfm/pfm/reader.py`, line 224

```python
is_stream = ":STREAM" in line
```

The `:STREAM` flag only affects whether the reader looks for a trailing index. A non-stream file with a trailing index appended would be parsed differently depending on how the reader handles it. Conversely, a stream file without the flag would fail to find its index. This inconsistency could be exploited to hide sections from readers that only check inline indexes.

---

### 5. Crash Recovery / Append Mode Abuse

#### 5.1 CRITICAL -- Race Condition in Stream Recovery
**Severity:** CRITICAL
**File:** `/Users/jasonsutter/Documents/Companies/pfm/pfm/stream.py`, lines 169-238

The `_recover()` function reads the file, processes it, then opens the same file with `r+b` and truncates. **There is no file locking.** Between the `read_bytes()` and the `open(path, "r+b")`, the file could be modified by another process.

```python
raw = path.read_bytes()          # <-- Read
text = raw.decode("utf-8")
lines = text.split("\n")
...
handle = open(path, "r+b")       # <-- Gap: file could change between read and open
handle.seek(truncate_at)
handle.truncate()                 # <-- Truncate based on stale data
```

**APT Exploitation:**
1. Monitor for .pfm stream files being recovered (file access patterns)
2. Between the read and the truncate, modify the file to inject persistent sections
3. The truncation offset was calculated from the old file, so it may land in the middle of the injected content, partially preserving the attacker's payload
4. Alternatively, if the attacker increases the file size, `truncate_at` (calculated from old data) will leave the new content intact

---

#### 5.2 HIGH -- text.index() First-Match Bug in Recovery
**Severity:** HIGH
**File:** `/Users/jasonsutter/Documents/Companies/pfm/pfm/stream.py`, line 225

```python
truncate_at = text.index(line)
```

This finds the **first** occurrence of the line in the entire file text. If an attacker injects a fake trailing index marker earlier in the file (e.g., inside a content section using the marker injection vulnerability from 1.1), `text.index()` will match the fake marker, causing truncation at the wrong position. This can:
1. Preserve attacker-injected sections that should have been removed
2. Corrupt the file by truncating in the middle of legitimate content
3. Cause the actual trailing index to be silently dropped

---

#### 5.3 HIGH -- Checksum Recomputation from Manipulated Offsets
**Severity:** HIGH
**File:** `/Users/jasonsutter/Documents/Companies/pfm/pfm/stream.py`, lines 76-79

```python
# Recompute running checksum from existing sections
self._checksum = hashlib.sha256()
raw = self.path.read_bytes()
for name, offset, length in self._sections:
    self._checksum.update(raw[offset:offset + length])
```

During append recovery, the checksum is recomputed from the section list returned by `_recover()`. If `_recover()` returns manipulated offsets (due to injected section markers), the checksum will cover the wrong data. The final checksum written on `close()` will then validate against the manipulated content, making the tampered file appear legitimate.

---

### 6. Cryptographic Weakness Analysis

#### 6.1 HIGH -- HMAC Signing Does Not Cover Format Version or Structure
**Severity:** HIGH
**File:** `/Users/jasonsutter/Documents/Companies/pfm/pfm/security.py`, lines 73-87

```python
def _build_signing_message(doc: PFMDocument) -> bytes:
    parts = []
    for key in sorted(doc.get_meta_dict().keys()):
        val = doc.get_meta_dict()[key]
        parts.append(f"{key}={val}".encode("utf-8"))
    for section in doc.sections:
        parts.append(f"[{section.name}]".encode("utf-8"))
        parts.append(section.content.encode("utf-8"))
    return b"\x00".join(parts)
```

The signing message includes meta fields and section name/content pairs but does NOT include:
- The format version (`doc.format_version`)
- Section ordering (sorted meta keys destroy original order)
- Section byte offsets/lengths (index entries)
- The `#!PFM` magic line
- The number of sections (delimiters could be ambiguous)

**Attack:** An attacker could modify the format version, reorder sections, or manipulate index offsets without breaking the signature. The signature only proves that the meta values and section content bytes are unchanged -- not that the file structure is intact.

---

#### 6.2 HIGH -- Null Byte Delimiter Ambiguity in Signing Message
**Severity:** HIGH
**File:** `/Users/jasonsutter/Documents/Companies/pfm/pfm/security.py`, line 87

```python
return b"\x00".join(parts)
```

The signing message concatenates parts with a `\x00` delimiter. However, if a section name or content contains `\x00` bytes (which is valid in Python strings, even if unusual in UTF-8 text), the delimiter becomes ambiguous. An attacker could construct content that, when joined with `\x00`, produces the same byte sequence as a different set of sections.

**Example:** Section "a" with content "b\x00[c]" produces the same signing bytes as section "a" with content "b" followed by section "c" with empty content (simplified -- actual attack requires careful construction).

---

#### 6.3 HIGH -- No Authenticated Associated Data (AAD) in AES-GCM
**Severity:** HIGH
**File:** `/Users/jasonsutter/Documents/Companies/pfm/pfm/security.py`, lines 125-126

```python
aesgcm = AESGCM(key)
ciphertext = aesgcm.encrypt(nonce, data, None)  # <-- None = no AAD
```

AES-GCM supports Associated Authenticated Data (AAD) which authenticates plaintext metadata alongside the encrypted payload. The PFM implementation passes `None` for AAD, meaning:
1. The `#!PFM-ENC/1.0` header is not authenticated
2. An attacker can modify the header (e.g., change version) without detection
3. If additional plaintext metadata is ever added to the encrypted format, it will not be integrity-protected

---

#### 6.4 MEDIUM -- PBKDF2 Key Derivation Lacks Algorithm Agility
**Severity:** MEDIUM
**File:** `/Users/jasonsutter/Documents/Companies/pfm/pfm/security.py`, lines 94-102

```python
def _derive_key(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations=600_000,
        dklen=32,
    )
```

While 600,000 iterations meets current OWASP recommendations, there is no algorithm identifier stored in the encrypted output. If the iteration count or algorithm is changed in a future version, old encrypted files become indistinguishable from new ones. An attacker could craft a file with fewer iterations (e.g., 1) that looks identical in format, making brute-force trivial.

---

#### 6.5 MEDIUM -- Fingerprint Truncation to 16 Hex Characters
**Severity:** MEDIUM
**File:** `/Users/jasonsutter/Documents/Companies/pfm/pfm/security.py`, lines 206-213

```python
def fingerprint(doc: PFMDocument) -> str:
    material = f"{doc.id}:{doc.checksum}:{doc.created}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
```

Truncating SHA-256 to 16 hex characters (64 bits) reduces collision resistance from 128 bits to 32 bits (birthday attack). A nation-state actor with moderate compute resources could find collisions, enabling fingerprint spoofing for document deduplication evasion or tracking confusion.

---

#### 6.6 LOW -- Timing Side-Channel in Checksum Validation
**Severity:** LOW
**File:** `/Users/jasonsutter/Documents/Companies/pfm/pfm/reader.py`, line 313

```python
return h.hexdigest() == expected
```

Standard string comparison (`==`) is used instead of `hmac.compare_digest()`. This leaks timing information about how many characters match. While the HMAC verification in `security.py` correctly uses `hmac.compare_digest()`, the checksum validation in the reader does not.

Note: exploiting this requires an oracle (repeated submission + timing measurement), which limits practical exploitation. However, in a server-side context where .pfm files are validated via API, this becomes more relevant.

---

### 7. Supply Chain Analysis

#### 7.1 LOW -- Zero Runtime Dependencies (Positive Finding)
**Severity:** LOW (this is good)
**File:** `/Users/jasonsutter/Documents/Companies/pfm/pyproject.toml`

```toml
[project]
# No dependencies listed
```

The PFM library has zero runtime dependencies -- only stdlib. The `cryptography` library is optional (imported only when encryption is used). This dramatically reduces the supply chain attack surface compared to typical Python packages.

**However:** The optional `cryptography` dependency is imported at runtime without version pinning:
```python
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
```

If an attacker can compromise the `cryptography` package installation (e.g., via dependency confusion or pip cache poisoning), the encryption functions become compromised.

---

#### 7.2 MEDIUM -- No Lockfile or Hash Pinning for Dev Dependencies
**Severity:** MEDIUM
**File:** `/Users/jasonsutter/Documents/Companies/pfm/pyproject.toml`, lines 27-28

```toml
[project.optional-dependencies]
dev = ["pytest>=7.0", "pytest-cov>=4.0"]
```

Dev dependencies use minimum-version pins with no lockfile. An attacker performing a supply chain attack on `pytest` or `pytest-cov` could inject malicious code that executes during test runs, potentially:
1. Modifying source files before tests run
2. Injecting backdoors into the build output
3. Exfiltrating test data (which may include crypto keys from security tests)

---

#### 7.3 LOW -- Build Backend Uses Legacy Setuptools Path
**Severity:** LOW
**File:** `/Users/jasonsutter/Documents/Companies/pfm/pyproject.toml`, line 3

```toml
build-backend = "setuptools.backends._legacy:_Backend"
```

Using the `_legacy` backend path is unusual and may have different security properties than the standard `setuptools.build_meta` backend. This could be a deliberate choice or a misconfiguration.

---

## Attack Scenarios

### Scenario 1: "Ghost Section" -- APT29 Steganographic Exfiltration Pipeline
**Threat Actor:** APT29 (Cozy Bear)
**Objective:** Establish a covert data exfiltration channel using .pfm files as carriers
**Likelihood:** HIGH
**Impact:** Sensitive data exfiltration through legitimate file transfers

**Kill Chain:**
1. **Initial Access:** Compromise an AI agent that produces .pfm output (supply chain or credential theft)
2. **Weaponize:** Modify the agent to inject hidden data into .pfm files using either:
   - Index offset manipulation pointing to data after `#!END`
   - Custom section with innocuous name ("metrics_cache", "trace")
   - Section marker injection inside content sections
3. **Deliver:** The .pfm files flow through normal channels (APIs, shared storage, agent pipelines)
4. **Exploit:** No exploit needed -- the data is embedded in files that pass all validation
5. **Persist:** The exfil channel persists as long as the compromised agent runs
6. **Collect:** Exfiltrated data accumulates in .pfm files stored by the target organization
7. **Exfiltrate:** Attacker retrieves .pfm files from storage/logs and extracts hidden data using known offsets

**Detection Difficulty:** VERY HIGH -- files pass checksum validation, signature verification, and visual inspection. Only raw hex dump or byte-level analysis would reveal hidden content.

---

### Scenario 2: "The Forged Oracle" -- APT41 AI Agent Poisoning
**Threat Actor:** APT41 (Double Dragon)
**Objective:** Poison AI agent reasoning chains to influence downstream decisions
**Likelihood:** MEDIUM
**Impact:** Decision manipulation in AI-assisted workflows

**Kill Chain:**
1. **Initial Access:** Intercept .pfm files in transit or at rest (shared storage, API proxy)
2. **Modify:** Use section marker injection to split a "content" section and inject a fake "reasoning" section containing adversarial instructions
3. **Bypass Integrity:** Strip the checksum (validation returns True for missing checksums) or recompute it for the modified content
4. **Impact:** Downstream agents consuming the .pfm file see the injected reasoning as legitimate, altering their behavior
5. **Persist:** Modify the "chain" section to include a poisoned conversation history that biases future agent interactions

---

### Scenario 3: "The Immortal Stream" -- Lazarus Group Persistent Access
**Threat Actor:** Lazarus Group
**Objective:** Maintain persistent code execution context through stream file manipulation
**Likelihood:** MEDIUM
**Impact:** Long-term access to agent execution environments

**Kill Chain:**
1. **Initial Access:** Compromise a system running PFM stream writers for long-running agent tasks
2. **Exploit:** During the TOCTOU gap in `_recover()`, inject sections into the stream file
3. **Persist:** Injected sections survive crash recovery and become part of the legitimate section index
4. **Maintain:** Each crash-recovery cycle preserves the attacker's sections while rebuilding the index
5. **Escalate:** If the agent pipeline processes "tools" sections as executable instructions, the attacker achieves code execution context injection

---

## Defense Gaps

### Logging and Monitoring
1. **No audit logging** -- File reads, writes, validation results, and signature checks produce no log output
2. **No anomaly detection** -- No mechanisms to detect unusual section counts, names, sizes, or offset patterns
3. **Silent validation pass on missing checksums** -- Applications cannot distinguish "never signed" from "signature stripped"

### Input Validation
1. **No section name validation** against known types
2. **No offset bounds checking** in indexed reader
3. **No content sanitization** for section marker sequences
4. **No path sanitization** in CLI file operations
5. **No maximum file size enforcement**
6. **No maximum section count limit** (memory exhaustion DoS)

### Structural Integrity
1. **Index is not cross-validated** against actual section markers
2. **Section boundaries are not verified** after indexed read
3. **EOF marker position is not validated** against file size
4. **Stream recovery does not validate recovered sections** against original meta

---

## Prioritized Recommendations for Red Team

### P0 -- Critical (Fix Before Any Production Use)

1. **Implement section marker escaping.** Define an escape sequence (e.g., `\#@` or doubling) for content that starts with `#@` or `#!`. Apply on write, unescape on read. This closes the marker injection vector entirely.

2. **Bounds-check all index offsets.** In `PFMReaderHandle.get_section()`, validate that `offset >= header_end` and `offset + length <= eof_marker_position`. Reject entries that fall outside the section content region.

3. **Cross-validate index against section markers.** After parsing the index, verify that each offset actually follows a `#@section_name\n` header in the raw bytes. This prevents phantom section injection via offset manipulation.

4. **Reject files with missing checksums when validation is requested.** Change `validate_checksum()` and `verify_integrity()` to return `False` (or raise) when no checksum is present, or add a `strict=True` parameter.

5. **Add file locking to stream recovery.** Use `fcntl.flock()` (Unix) or platform-appropriate locking in `_recover()` to prevent TOCTOU attacks.

### P1 -- High (Fix Before Public Release)

6. **Replace setattr-based meta parsing** with an explicit allowlist:
   ```python
   ALLOWED_META_FIELDS = {"id", "agent", "model", "created", "checksum", "parent", "tags", "version"}
   if key in ALLOWED_META_FIELDS:
       setattr(doc, key, val)
   ```

7. **Include format_version in HMAC signing message.** Add `format_version` and section ordering to `_build_signing_message()`.

8. **Use length-prefixed encoding in signing message** instead of null-byte delimiters to prevent ambiguity attacks.

9. **Pass the encrypted header as AAD** to AES-GCM: `aesgcm.encrypt(nonce, data, header)`.

10. **Store KDF parameters** (algorithm, iterations) in the encrypted file header so they are version-independent.

11. **Fix text.index() in _recover()** to use `rfind()` or search from the expected position, not from the beginning of the file.

12. **Sanitize --file path in CLI** using `Path.resolve()` and optionally restricting to the current directory.

### P2 -- Medium (Hardening)

13. **Use hmac.compare_digest() for checksum validation** in `reader.py` instead of `==`.

14. **Add a lockfile** (`requirements.txt` or `pip-compile` output) for dev dependencies with hash pinning.

15. **Increase fingerprint length** from 16 to 32 hex characters (128-bit collision resistance).

16. **Add maximum section count and file size limits** to prevent resource exhaustion.

17. **Validate format_version** against a known set of supported versions and reject unknown versions.

### P3 -- Low (Defense in Depth)

18. **Add structured logging** for all file operations, validation results, and security operations.

19. **Add a `--strict` mode to the CLI** that rejects files with missing checksums, unknown section names, or other anomalies.

20. **Consider canonical serialization** for the signing message (e.g., CBOR or bencode) to eliminate ambiguity entirely.

---

## Files Analyzed

| File | Lines | Purpose | Findings |
|------|-------|---------|----------|
| `/Users/jasonsutter/Documents/Companies/pfm/pfm/spec.py` | 73 | Format constants | Version not enforced |
| `/Users/jasonsutter/Documents/Companies/pfm/pfm/document.py` | 134 | In-memory model | setattr target |
| `/Users/jasonsutter/Documents/Companies/pfm/pfm/writer.py` | 135 | Serializer | No content escaping |
| `/Users/jasonsutter/Documents/Companies/pfm/pfm/reader.py` | 323 | Parser + indexed reader | Marker injection, offset trust, timing leak, setattr injection |
| `/Users/jasonsutter/Documents/Companies/pfm/pfm/security.py` | 214 | Crypto operations | No AAD, delimiter ambiguity, missing coverage |
| `/Users/jasonsutter/Documents/Companies/pfm/pfm/stream.py` | 239 | Streaming writer | TOCTOU, first-match bug, persistent injection |
| `/Users/jasonsutter/Documents/Companies/pfm/pfm/converters.py` | 289 | Format converters | Inherits parser vulnerabilities |
| `/Users/jasonsutter/Documents/Companies/pfm/pfm/cli.py` | 213 | CLI interface | Path traversal |
| `/Users/jasonsutter/Documents/Companies/pfm/pfm/spells.py` | 160 | Aliased API | Passthrough (inherits all) |
| `/Users/jasonsutter/Documents/Companies/pfm/pfm/__init__.py` | 16 | Package init | Clean |
| `/Users/jasonsutter/Documents/Companies/pfm/pyproject.toml` | 33 | Build config | Legacy backend, no pins |

---

## Summary Threat Matrix

| Finding | Severity | MITRE ATT&CK | Exploitable By |
|---------|----------|---------------|----------------|
| Section marker injection | CRITICAL | T1027, T1059 | Any attacker with file write |
| Index offset steganography | CRITICAL | T1048 (Exfil) | APT with file access |
| Stream TOCTOU race | CRITICAL | T1068 (Priv Esc) | APT with local access |
| Stream append persistence | CRITICAL | T1137 (Persistence) | APT with file access |
| setattr attribute injection | HIGH | T1055 (Process Injection) | Any attacker with file write |
| Checksum bypass (missing = valid) | HIGH | T1070 (Defense Evasion) | Any attacker |
| HMAC scope gap (version, order) | HIGH | T1565 (Data Manipulation) | Attacker with signed file |
| Null-byte delimiter ambiguity | HIGH | T1565 | Sophisticated attacker |
| No AAD in AES-GCM | HIGH | T1565 | Attacker with encrypted file |
| CLI path traversal | HIGH | T1005 (Data from Local System) | Pipeline attacker |
| text.index() first-match | HIGH | T1565 | Attacker with stream file |
| Stream checksum recomputation | HIGH | T1070 | Attacker with stream file |
| Format version not enforced | HIGH | T1562 (Impair Defenses) | Any attacker |
| No KDF params stored | MEDIUM | T1110 (Brute Force) | Offline attacker |
| Custom section steganography | MEDIUM | T1048 | APT with file access |
| Custom meta field exfil | MEDIUM | T1048 | APT with file access |
| Dev dependency pinning | MEDIUM | T1195 (Supply Chain) | Supply chain attacker |
| Fingerprint truncation | MEDIUM | T1036 (Masquerading) | Moderate compute |
| Stream flag inconsistency | MEDIUM | T1027 | Parser confusion |
| Timing leak in checksum | LOW | T1212 (Exploitation for Cred) | Network oracle |
| Legacy build backend | LOW | T1195 | Supply chain attacker |

---

**End of Specter APT Assessment**
*Analysis performed on code as of 2026-02-16. No actual attacks were executed. All findings are based on static code analysis within the defined scope.*
