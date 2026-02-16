# .pfm — Pure Fucking Magic

> A universal container format for AI agent output.

The AI ecosystem has a format problem. Agents spit out markdown, JSON, YAML, plain text, structured logs — all different, all incompatible, all missing context. `.pfm` fixes that.

One file. Every agent. All the context.

```
#!PFM/1.0
#@meta
id: 7a3f9c21-...
agent: claude-code
model: claude-opus-4-6
created: 2026-02-16T20:02:37Z
checksum: 049dcea0...
#@index
content 329 398
chain 735 330
tools 1073 188
#@content
Your actual agent output goes here.
Full multiline content, any format.
#@chain
User: Analyze this codebase
Agent: I'll examine the structure...
#@tools
search(query="authentication")
read_file("auth/handler.py")
#!END
```

That's it. Human readable. Machine parseable. Indexed for speed.

---

## Why PFM Exists

Every AI agent today outputs differently:
- ChatGPT gives you markdown blobs
- Claude gives you structured text
- AutoGPT dumps JSON logs
- LangChain has its own trace format
- CrewAI, Autogen, Semantic Kernel — all different

There's no standard way to capture **what an agent produced**, **how it got there**, **what tools it used**, and **whether the output is trustworthy**. If you want to share agent output, audit it, chain it, or verify it — you're on your own.

`.pfm` is the container that wraps it all:

| What | Where |
|------|-------|
| The actual output | `content` section |
| The conversation that produced it | `chain` section |
| Tool calls made | `tools` section |
| Agent reasoning | `reasoning` section |
| Performance data | `metrics` section |
| Anything else | Custom sections |

---

## Installation

```bash
pip install .            # From source
pip install pfm          # From PyPI (coming soon)
```

## Quick Start

### Python API

```python
from pfm import PFMDocument, PFMReader

# Create
doc = PFMDocument.create(agent="my-agent", model="claude-opus-4-6")
doc.add_section("content", "The analysis shows 3 critical findings...")
doc.add_section("chain", "User: Analyze the repo\nAgent: Starting analysis...")
doc.add_section("tools", "grep(pattern='TODO', path='src/')")
doc.write("report.pfm")

# Read (full parse)
doc = PFMReader.read("report.pfm")
print(doc.content)      # "The analysis shows..."
print(doc.agent)         # "my-agent"
print(doc.chain)         # "User: Analyze the repo..."

# Read (indexed — O(1) section access, only reads what you need)
with PFMReader.open("report.pfm") as reader:
    content = reader.get_section("content")  # Jumps directly by byte offset
    print(reader.meta["agent"])
    print(reader.section_names)
```

### CLI

```bash
# Create a .pfm file
pfm create -a "my-agent" -m "gpt-4" -c "Hello world" -o output.pfm

# Inspect metadata and sections
pfm inspect output.pfm

# Read a specific section
pfm read output.pfm content

# Validate structure and checksum
pfm validate output.pfm

# Quick file identification
pfm identify output.pfm

# Convert formats
pfm convert to json output.pfm -o output.json
pfm convert to md output.pfm -o output.md
pfm convert from json data.json -o imported.pfm
pfm convert from csv data.csv -o imported.pfm
```

### Converters

Every format goes both ways:

```python
from pfm import converters, PFMReader

doc = PFMReader.read("report.pfm")

# To other formats
json_str = converters.to_json(doc)
csv_str = converters.to_csv(doc)
txt_str = converters.to_txt(doc)
md_str = converters.to_markdown(doc)

# From other formats
doc = converters.from_json(json_str)
doc = converters.from_csv(csv_str)
doc = converters.from_txt("raw text", agent="importer")
doc = converters.from_markdown(md_str)
```

### Security

```python
from pfm.security import sign, verify, encrypt_document, decrypt_document

# Sign (HMAC-SHA256)
doc = PFMDocument.create(agent="trusted-agent")
doc.add_section("content", "verified output")
sign(doc, secret="your-signing-key")
doc.write("signed.pfm")

# Verify
loaded = PFMReader.read("signed.pfm")
assert verify(loaded, "your-signing-key")  # True if untampered

# Encrypt (AES-256-GCM, PBKDF2 key derivation)
encrypted = encrypt_document(doc, password="strong-password")
with open("secret.pfm.enc", "wb") as f:
    f.write(encrypted)

# Decrypt
data = open("secret.pfm.enc", "rb").read()
decrypted = decrypt_document(data, password="strong-password")
print(decrypted.content)
```

---

## Format Design Priorities

In this exact order:

### 1. Speed
- Magic byte check in first 64 bytes (instant file identification)
- Index with byte offsets for O(1) section jumping (no scanning)
- Two-pass writer pre-computes all offsets
- Lazy reader only loads sections you request

### 2. Indexing
- Every section has a byte offset and length in the `#@index` block
- Readers can seek directly to any section without parsing the whole file
- Multiple sections with the same name are supported and independently indexed

### 3. Human Readability
- 100% UTF-8 text (no binary blobs)
- Open it in any text editor and immediately understand the structure
- Section markers (`#@`) are visually distinct and greppable
- Magic line (`#!PFM/1.0`) is self-documenting

### 4. AI Usefulness
- Structured metadata (agent, model, timestamps)
- Prompt chain preservation (full conversation context)
- Tool call logging (reproducibility)
- Arbitrary custom sections (extend without breaking the spec)

---

## PFM vs Other Formats

| Feature | .pfm | .json | .md | .yaml | .csv |
|---------|-------|-------|-----|-------|------|
| Human readable | Yes | Somewhat | Yes | Yes | Somewhat |
| Indexed sections | **Yes (O(1))** | No | No | No | No |
| Agent metadata | **Built-in** | Manual | No | Manual | No |
| Prompt chain | **Built-in** | Manual | No | Manual | No |
| Tool call logs | **Built-in** | Manual | No | Manual | No |
| Checksum integrity | **Built-in** | No | No | No | No |
| HMAC signing | **Built-in** | No | No | No | No |
| Encryption | **AES-256-GCM** | No | No | No | No |
| Multiline content | Natural | Escaped | Natural | Indented | Escaped |
| File identification | 64 bytes | Parse whole file | No | Parse whole file | No |
| Custom sections | Unlimited | N/A | N/A | N/A | N/A |
| Bidirectional conversion | JSON, CSV, TXT, MD | — | — | — | — |

### Pros
- **Purpose-built for AI** — not a general-purpose format retrofitted for agent output
- **Self-contained** — one file has everything: output, context, metadata, provenance
- **Fast** — indexed byte offsets mean you don't parse what you don't need
- **Secure** — signing and encryption are first-class, not afterthoughts
- **Extensible** — add any section you want, the format doesn't care
- **Convertible** — round-trips cleanly to/from JSON, CSV, TXT, Markdown

### Cons
- **New format** — no existing ecosystem (yet)
- **Text-based** — not as compact as binary formats for large payloads
- **Section markers in content** — content containing `#@` or `#!PFM` on a line start is an edge case (escaping spec TBD)
- **No streaming write** — writer needs all sections in memory to compute the index
- **Young spec** — v1.0, will evolve

---

## What It Solves

1. **Agent output portability** — Share agent results between tools, platforms, and teams in one format
2. **Provenance tracking** — Know which agent, model, and prompt produced any output
3. **Output verification** — Checksums and signatures prove content hasn't been tampered with
4. **Audit trails** — Chain and tool sections preserve the full generation context
5. **Selective reading** — Index-based access means you can grab just the section you need from large files
6. **Format interop** — Convert to/from JSON, CSV, TXT, MD without losing structure

---

## Project Structure

```
pfm/
├── pyproject.toml          # Package config, CLI entry point
├── pfm/
│   ├── spec.py             # Format specification and constants
│   ├── document.py         # PFMDocument in-memory model
│   ├── writer.py           # Serializer with two-pass offset calculation
│   ├── reader.py           # Full parser + indexed lazy reader
│   ├── converters.py       # JSON, CSV, TXT, Markdown (both directions)
│   ├── security.py         # HMAC signing, AES-256-GCM encryption
│   └── cli.py              # Command-line interface
├── tests/
│   ├── test_unit.py        # 17 unit tests
│   ├── test_functional.py  # 25 functional tests
│   ├── test_e2e.py         # 15 end-to-end tests
│   └── test_security.py    # 17 security tests
└── examples/
    └── hello.pfm           # Example file
```

**74 tests. All passing.**

---

## The Name

Yes, PFM stands for **Pure Fucking Magic**.

It's a 20-year joke. Someone in 2046 will google "what does .pfm stand for," find this page, and laugh. Then they'll realize the format actually works, and they'll keep using it.

That's the plan. And honestly? The way AI agent data gets moved around today with zero standardization? The fact that it works at all *is* pure fucking magic.

---

## License

MIT

---

*Built in one session. Shipped before the hype cycle ended.*
