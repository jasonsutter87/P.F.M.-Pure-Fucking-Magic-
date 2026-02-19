/* ================================================================
   PFM Core — shared library for the PFM Chrome extension.
   Extracted verbatim from docs/index.html (the PFM SPA).
   Zero dependencies — uses only Web APIs available in Chrome extensions.
   ================================================================ */

/* ================================================================
   PFM Parser — Pure client-side .pfm parser
   Mirrors the Python PFMReader logic exactly.
   ================================================================ */
const PFMParser = {
  MAGIC: '#!PFM',
  EOF: '#!END',
  SEC: '#@',
  MAX_SECTIONS: 10000,
  MAX_META_FIELDS: 100,
  MAX_SECTION_NAME_LEN: 64,

  parse(text) {
    const lines = text.split('\n');
    const doc = {
      formatVersion: '1.0',
      isStream: false,
      meta: {},
      sections: [],
      raw: text
    };

    let currentSection = null;
    let sectionLines = [];
    let inMeta = false;
    let inIndex = false;
    let metaFieldCount = 0;

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];

      // Magic line
      if (line.startsWith(this.MAGIC)) {
        const slash = line.indexOf('/');
        if (slash !== -1) {
          const rest = line.substring(slash + 1);
          const colon = rest.indexOf(':');
          doc.formatVersion = colon !== -1 ? rest.substring(0, colon) : rest;
          doc.isStream = rest.includes(':STREAM');
        }
        // Reject unknown format versions (matches Python reader behavior)
        if (doc.formatVersion !== '1.0') {
          throw new Error(`Unsupported PFM format version: '${doc.formatVersion}'`);
        }
        continue;
      }

      // EOF
      if (line.startsWith(this.EOF)) {
        flush();
        break;
      }

      // Section header (not escaped)
      if (line.startsWith(this.SEC) && !line.startsWith('\\#')) {
        flush();
        const name = line.substring(this.SEC.length);
        // Validate section name length
        if (name.length > this.MAX_SECTION_NAME_LEN) {
          currentSection = null;
          continue;
        }
        inMeta = (name === 'meta');
        inIndex = (name === 'index' || name === 'index-trailing');
        if (!inMeta && !inIndex) {
          // Enforce section count limit
          if (doc.sections.length >= this.MAX_SECTIONS) {
            currentSection = null;
            continue;
          }
          currentSection = name;
          sectionLines = [];
        } else {
          currentSection = null;
        }
        continue;
      }

      // Meta
      if (inMeta) {
        const sep = line.indexOf(': ');
        if (sep !== -1 && metaFieldCount < this.MAX_META_FIELDS) {
          const key = line.substring(0, sep).trim();
          const val = line.substring(sep + 2).trim();
          // Prevent prototype pollution
          if (key === '__proto__' || key === 'constructor' || key === 'prototype') {
            continue;
          }
          // First-wins: prevent duplicate meta key override
          if (!(key in doc.meta)) {
            doc.meta[key] = val;
            metaFieldCount++;
          }
        }
        continue;
      }

      // Index (skip)
      if (inIndex) continue;

      // Content
      if (currentSection !== null) {
        sectionLines.push(this.unescape(line));
      }
    }
    flush();
    return doc;

    function flush() {
      if (currentSection === null) return;
      let content = sectionLines.join('\n');
      if (content.endsWith('\n')) content = content.slice(0, -1);
      doc.sections.push({ name: currentSection, content });
      currentSection = null;
      sectionLines = [];
    }
  },

  unescape(line) {
    if (line.startsWith('\\') && this._hasMarkerAfterBackslashes(line.substring(1))) {
      return line.substring(1);
    }
    return line;
  },

  _hasMarkerAfterBackslashes(line) {
    let i = 0;
    while (i < line.length && line[i] === '\\') i++;
    const rest = line.substring(i);
    return rest.startsWith('#@') || rest.startsWith('#!PFM') || rest.startsWith('#!END');
  },

};


/* ================================================================
   PFM Serializer — builds .pfm file content from structured data
   ================================================================ */
const PFMSerializer = {
  /** Escape a content line that starts with a PFM marker prefix */
  escapeLine(line) {
    if (this._hasMarkerAfterBackslashes(line)) {
      return '\\' + line;
    }
    return line;
  },

  _hasMarkerAfterBackslashes(line) {
    let i = 0;
    while (i < line.length && line[i] === '\\') i++;
    const rest = line.substring(i);
    return rest.startsWith('#@') || rest.startsWith('#!PFM') || rest.startsWith('#!END');
  },

  /** Escape all lines in content */
  escapeContent(content) {
    return content.split('\n').map(line => this.escapeLine(line)).join('\n');
  },

  /** Generate a UUID v4 using cryptographically secure random values */
  uuid() {
    // Use crypto.getRandomValues for secure randomness (not Math.random)
    const bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    // Set version (4) and variant (RFC 4122) bits
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = Array.from(bytes).map(b => b.toString(16).padStart(2, '0')).join('');
    return hex.substring(0, 8) + '-' + hex.substring(8, 12) + '-' +
           hex.substring(12, 16) + '-' + hex.substring(16, 20) + '-' + hex.substring(20, 32);
  },

  /** Compute SHA-256 checksum of section contents (O(N) allocation) */
  async checksum(sections) {
    const encoder = new TextEncoder();
    const chunks = [];
    let totalLen = 0;
    for (const s of sections) {
      const encoded = encoder.encode(s.content);
      chunks.push(encoded);
      totalLen += encoded.length;
    }
    const merged = new Uint8Array(totalLen);
    let offset = 0;
    for (const chunk of chunks) {
      merged.set(chunk, offset);
      offset += chunk.length;
    }
    const hashBuffer = await crypto.subtle.digest('SHA-256', merged);
    return Array.from(new Uint8Array(hashBuffer)).map(b => b.toString(16).padStart(2, '0')).join('');
  },

  /** Serialize sections and meta into a .pfm string */
  async serialize(sections, meta) {
    meta = meta || {};
    // Auto-fill required meta fields
    if (!meta.id) meta.id = this.uuid();
    if (!meta.created) meta.created = new Date().toISOString();
    if (!meta.agent) meta.agent = 'pfm-chrome-extension';

    // Compute checksum
    const hash = await this.checksum(sections);
    meta.checksum = hash;

    // Build content sections first (to calculate offsets for index)
    // Validate and normalize section names before serialization
    const VALID_NAME_RE = /^[a-z0-9_-]+$/;
    const sectionBlocks = [];
    for (const s of sections) {
      let name = String(s.name || 'content').substring(0, 64);
      if (!VALID_NAME_RE.test(name)) {
        // Normalize: lowercase, replace invalid chars
        name = name.toLowerCase().replace(/\s/g, '-').replace(/[^a-z0-9_-]/g, '');
        if (!name) name = 'content';
      }
      const escaped = this.escapeContent(s.content);
      sectionBlocks.push({ name, escaped, content: s.content });
    }

    // Build the file
    let pfm = '#!PFM/1.0\n';

    // Meta block
    pfm += '#@meta\n';
    for (const [k, v] of Object.entries(meta)) {
      if (k === '__proto__' || k === 'constructor' || k === 'prototype') continue;
      // Sanitize meta values: strip newlines and control characters to prevent format injection
      const safeVal = String(v).replace(/[\x00-\x1f\x7f]/g, '');
      const safeKey = String(k).replace(/[\x00-\x1f\x7f]/g, '');
      pfm += safeKey + ': ' + safeVal + '\n';
    }

    // Index block — calculate byte offsets with convergence loop
    // (offset digits can change index size, shifting all offsets)
    const encoder = new TextEncoder();
    const headerWithoutIndex = pfm;
    const headerBytes = encoder.encode(headerWithoutIndex).length;
    const indexHeader = '#@index\n';

    let prevIndex = '';
    let finalIndex = '';
    for (let pass = 0; pass < 5; pass++) {
      const indexSize = encoder.encode(indexHeader + prevIndex).length;
      const sectionStart = headerBytes + indexSize;
      finalIndex = '';
      let off = sectionStart;
      for (const sb of sectionBlocks) {
        const sectionHdr = '#@' + sb.name + '\n';
        const body = sb.escaped + '\n';
        const contentOffset = off + encoder.encode(sectionHdr).length;
        const contentLen = encoder.encode(body).length;
        finalIndex += sb.name + ' ' + contentOffset + ' ' + contentLen + '\n';
        off = contentOffset + contentLen;
      }
      if (finalIndex === prevIndex) break;
      prevIndex = finalIndex;
    }

    pfm = headerWithoutIndex + indexHeader + finalIndex;

    // Section blocks
    for (const sb of sectionBlocks) {
      pfm += '#@' + sb.name + '\n';
      pfm += sb.escaped + '\n';
    }

    pfm += '#!END\n';
    return pfm;
  }
};


/* ================================================================
   Converters — transform various formats into PFM sections + meta
   ================================================================ */
const Converters = {
  /** Detect format from filename extension */
  detectFormat(filename) {
    const ext = filename.split('.').pop().toLowerCase();
    if (ext === 'json') return 'json';
    if (ext === 'csv') return 'csv';
    if (ext === 'md' || ext === 'markdown') return 'markdown';
    return 'txt';
  },

  /** Convert JSON to PFM sections + meta */
  fromJSON(text, filename) {
    let data;
    try {
      data = JSON.parse(text);
    } catch (e) {
      throw new Error('Invalid JSON: ' + e.message);
    }

    if (typeof data !== 'object' || data === null || Array.isArray(data)) {
      throw new Error('JSON must be an object with sections array or key-value pairs');
    }

    const meta = { source_file: filename, source_format: 'json' };
    const sections = [];

    // Format 1: PFM-like structure { meta: {...}, sections: [{name, content}] }
    if (data.sections && Array.isArray(data.sections)) {
      if (data.meta && typeof data.meta === 'object' && !Array.isArray(data.meta)) {
        for (const [k, v] of Object.entries(data.meta)) {
          if (k === '__proto__' || k === 'constructor' || k === 'prototype') continue;
          if (typeof v === 'string') meta[k] = v;
        }
      }
      for (const s of data.sections) {
        if (!s || typeof s.name !== 'string') continue;
        const content = typeof s.content === 'string' ? s.content : JSON.stringify(s.content, null, 2);
        // Normalize section name for PFM compatibility
        let name = s.name.toLowerCase().replace(/\s/g, '-').replace(/[^a-z0-9_-]/g, '').substring(0, 64);
        if (!name) name = 'content';
        sections.push({ name, content });
      }
    }
    // Format 2: Flat key-value — each key becomes a section
    else {
      for (const [k, v] of Object.entries(data)) {
        if (k === '__proto__' || k === 'constructor' || k === 'prototype') continue;
        const content = typeof v === 'string' ? v : JSON.stringify(v, null, 2);
        // Normalize key as section name
        let name = k.toLowerCase().replace(/\s/g, '-').replace(/[^a-z0-9_-]/g, '').substring(0, 64);
        if (!name) name = 'content';
        sections.push({ name, content });
      }
    }

    if (sections.length === 0) {
      sections.push({ name: 'content', content: JSON.stringify(data, null, 2) });
    }

    return { sections, meta };
  },

  /** Convert CSV to PFM sections + meta */
  fromCSV(text, filename) {
    const meta = { source_file: filename, source_format: 'csv' };
    const sections = [];
    const lines = text.split('\n').filter(l => l.trim());

    if (lines.length === 0) {
      throw new Error('CSV file is empty');
    }

    // Try to detect if first row is headers
    const firstRow = this.parseCSVLine(lines[0]);

    // Check for section_name/content format
    const nameIdx = firstRow.findIndex(h => /^(section[_\s]?name|name|section)$/i.test(h.trim()));
    const contentIdx = firstRow.findIndex(h => /^(content|body|text|value)$/i.test(h.trim()));

    if (nameIdx !== -1 && contentIdx !== -1 && lines.length > 1) {
      // Structured CSV with section name + content columns
      for (let i = 1; i < lines.length; i++) {
        const cols = this.parseCSVLine(lines[i]);
        // Normalize section name for PFM compatibility
        let name = (cols[nameIdx] || '').trim().toLowerCase().replace(/\s/g, '-').replace(/[^a-z0-9_-]/g, '').substring(0, 64);
        if (!name) name = 'content';
        const content = (cols[contentIdx] || '').trim();
        if (name) sections.push({ name, content });
      }
    } else {
      // Treat entire CSV as a single data section
      sections.push({ name: 'data', content: text });

      // Also try to provide a structured view
      if (firstRow.length > 1 && lines.length > 1) {
        const headers = firstRow.map(h => h.trim());
        let structured = '';
        for (let i = 1; i < lines.length; i++) {
          const cols = this.parseCSVLine(lines[i]);
          structured += '--- Row ' + i + ' ---\n';
          for (let j = 0; j < headers.length; j++) {
            structured += headers[j] + ': ' + (cols[j] || '').trim() + '\n';
          }
          structured += '\n';
        }
        sections.push({ name: 'structured', content: structured.trim() });
      }
    }

    meta.rows = String(lines.length - 1);
    meta.columns = String(firstRow.length);
    return { sections, meta };
  },

  /** Basic CSV line parser (handles quoted fields) */
  parseCSVLine(line) {
    const result = [];
    let current = '';
    let inQuotes = false;
    for (let i = 0; i < line.length; i++) {
      const ch = line[i];
      if (inQuotes) {
        if (ch === '"' && line[i + 1] === '"') {
          current += '"';
          i++;
        } else if (ch === '"') {
          inQuotes = false;
        } else {
          current += ch;
        }
      } else {
        if (ch === '"') {
          inQuotes = true;
        } else if (ch === ',') {
          result.push(current);
          current = '';
        } else {
          current += ch;
        }
      }
    }
    result.push(current);
    return result;
  },

  /** Convert plain text to PFM (single content section) */
  fromTXT(text, filename) {
    const meta = { source_file: filename, source_format: 'text' };
    const sections = [{ name: 'content', content: text.trim() }];
    return { sections, meta };
  },

  /** Convert Markdown to PFM (H2 headings become sections) */
  fromMarkdown(text, filename) {
    const meta = { source_file: filename, source_format: 'markdown' };
    const sections = [];

    // Extract YAML front matter if present
    const fmMatch = text.match(/^---\n([\s\S]*?)\n---\n/);
    let body = text;
    if (fmMatch) {
      body = text.substring(fmMatch[0].length);
      const fmLines = fmMatch[1].split('\n');
      for (const line of fmLines) {
        const sep = line.indexOf(': ');
        if (sep !== -1) {
          const key = line.substring(0, sep).trim();
          const val = line.substring(sep + 2).trim();
          if (key && val && key !== '__proto__' && key !== 'constructor' && key !== 'prototype') {
            meta[key] = val;
          }
        }
      }
    }

    // Split by ## headings
    const parts = body.split(/^## /m);

    // Content before first H2
    const preamble = parts[0].trim();
    if (preamble) {
      sections.push({ name: 'content', content: preamble });
    }

    // Each H2 becomes a section
    for (let i = 1; i < parts.length; i++) {
      const lines = parts[i].split('\n');
      const rawName = lines[0].trim().substring(0, 64);
      // Normalize section name: lowercase, replace spaces with hyphens,
      // strip non-alphanumeric chars for PFM section name compatibility
      let name = rawName.toLowerCase().replace(/\s/g, '-');
      name = name.replace(/[^a-z0-9_-]/g, '');
      if (!name) name = 'content';
      const content = lines.slice(1).join('\n').trim();
      if (name) {
        sections.push({ name, content });
      }
    }

    if (sections.length === 0) {
      sections.push({ name: 'content', content: text.trim() });
    }

    return { sections, meta };
  }
};


/* ================================================================
   Utilities
   ================================================================ */
function esc(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

function formatBytes(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

function sanitizeFilename(name) {
  return name.replace(/[\/\\:*?"<>|]/g, '_').replace(/\.\./g, '_');
}

/** Constant-time string comparison to prevent timing side-channels on checksum validation. */
function timingSafeEqual(a, b) {
  const len = Math.max(a.length, b.length);
  let result = a.length === b.length ? 0 : 1;
  for (let i = 0; i < len; i++) {
    result |= (a.charCodeAt(i) || 0) ^ (b.charCodeAt(i) || 0);
  }
  return result === 0;
}

function pfmDownload(content, filename, mime) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = sanitizeFilename(filename);
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}


/* ================================================================
   PFM Crypto — AES-256-GCM encryption compatible with Python pfm.security
   Uses Web Crypto API (available in Chrome extensions).
   Format: "#!PFM-ENC/1.0\n" + salt(16) + nonce(12) + ciphertext + tag(16)
   ================================================================ */
const PFMCrypto = {
  HEADER: '#!PFM-ENC/1.0\n',
  AAD: new TextEncoder().encode('PFM-ENC/1.0'),
  PBKDF2_ITERATIONS: 600000,

  /** Derive an AES-256-GCM CryptoKey from a password and salt */
  async deriveKey(password, salt) {
    const enc = new TextEncoder();
    const keyMaterial = await crypto.subtle.importKey(
      'raw', enc.encode(password), 'PBKDF2', false, ['deriveKey']
    );
    return crypto.subtle.deriveKey(
      { name: 'PBKDF2', salt, iterations: this.PBKDF2_ITERATIONS, hash: 'SHA-256' },
      keyMaterial,
      { name: 'AES-GCM', length: 256 },
      false,
      ['encrypt', 'decrypt']
    );
  },

  /** Encrypt a PFM string with a password. Returns Uint8Array. */
  async encrypt(pfmText, password) {
    const enc = new TextEncoder();
    const plaintext = enc.encode(pfmText);
    const salt = crypto.getRandomValues(new Uint8Array(16));
    const nonce = crypto.getRandomValues(new Uint8Array(12));
    const key = await this.deriveKey(password, salt);

    const ciphertext = await crypto.subtle.encrypt(
      { name: 'AES-GCM', iv: nonce, additionalData: this.AAD },
      key, plaintext
    );

    // Assemble: header + salt + nonce + ciphertext (includes GCM tag)
    const header = enc.encode(this.HEADER);
    const result = new Uint8Array(header.length + 16 + 12 + ciphertext.byteLength);
    result.set(header, 0);
    result.set(salt, header.length);
    result.set(nonce, header.length + 16);
    result.set(new Uint8Array(ciphertext), header.length + 28);
    return result;
  },

  /** Decrypt an encrypted PFM file. Returns plaintext string. */
  async decrypt(data, password) {
    // data is Uint8Array
    const enc = new TextEncoder();
    const header = enc.encode(this.HEADER);

    // Validate header
    for (let i = 0; i < header.length; i++) {
      if (data[i] !== header[i]) throw new Error('Not an encrypted PFM file');
    }

    const payload = data.slice(header.length);
    if (payload.length < 44) throw new Error('Encrypted payload too short');

    const salt = payload.slice(0, 16);
    const nonce = payload.slice(16, 28);
    const ciphertext = payload.slice(28);

    const key = await this.deriveKey(password, salt);
    const plaintext = await crypto.subtle.decrypt(
      { name: 'AES-GCM', iv: nonce, additionalData: this.AAD },
      key, ciphertext
    );

    return new TextDecoder().decode(plaintext);
  }
};
