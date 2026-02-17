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
        inIndex = (name === 'index' || name === 'index:trailing');
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
          doc.meta[key] = val;
          metaFieldCount++;
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
    return line.startsWith('\\#') ? line.substring(1) : line;
  },

  async checksum(sections) {
    const encoder = new TextEncoder();
    let allBytes = new Uint8Array(0);
    for (const s of sections) {
      const encoded = encoder.encode(s.content);
      const merged = new Uint8Array(allBytes.length + encoded.length);
      merged.set(allBytes);
      merged.set(encoded, allBytes.length);
      allBytes = merged;
    }
    const hashBuffer = await crypto.subtle.digest('SHA-256', allBytes);
    return Array.from(new Uint8Array(hashBuffer)).map(b => b.toString(16).padStart(2, '0')).join('');
  }
};


/* ================================================================
   PFM Serializer — builds .pfm file content from structured data
   ================================================================ */
const PFMSerializer = {
  /** Escape a content line that starts with #@ or #! */
  escapeLine(line) {
    if (line.startsWith('#@') || line.startsWith('#!') || line.startsWith('\\#')) {
      return '\\' + line;
    }
    return line;
  },

  /** Escape all lines in content */
  escapeContent(content) {
    return content.split('\n').map(line => this.escapeLine(line)).join('\n');
  },

  /** Generate a UUID v4 */
  uuid() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
      const r = (Math.random() * 16) | 0;
      return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
    });
  },

  /** Compute SHA-256 checksum of section contents */
  async checksum(sections) {
    const encoder = new TextEncoder();
    let allBytes = new Uint8Array(0);
    for (const s of sections) {
      const encoded = encoder.encode(s.content);
      const merged = new Uint8Array(allBytes.length + encoded.length);
      merged.set(allBytes);
      merged.set(encoded, allBytes.length);
      allBytes = merged;
    }
    const hashBuffer = await crypto.subtle.digest('SHA-256', allBytes);
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
    const sectionBlocks = [];
    for (const s of sections) {
      const escaped = this.escapeContent(s.content);
      sectionBlocks.push({ name: s.name, escaped, content: s.content });
    }

    // Build the file
    let pfm = '#!PFM/1.0\n';

    // Meta block
    pfm += '#@meta\n';
    for (const [k, v] of Object.entries(meta)) {
      if (k === '__proto__' || k === 'constructor' || k === 'prototype') continue;
      pfm += k + ': ' + v + '\n';
    }

    // Index block — calculate byte offsets
    pfm += '#@index\n';
    let offset = new TextEncoder().encode(pfm).length;
    // First pass: compute index lines to know their size
    let indexLines = '';
    for (const sb of sectionBlocks) {
      indexLines += sb.name + ' 0 0\n'; // placeholder
    }
    offset += new TextEncoder().encode(indexLines).length;

    // Now calculate real offsets
    let indexContent = '';
    for (const sb of sectionBlocks) {
      const header = '#@' + sb.name + '\n';
      const body = sb.escaped + '\n';
      const headerBytes = new TextEncoder().encode(header).length;
      const bodyBytes = new TextEncoder().encode(body).length;
      const sectionSize = headerBytes + bodyBytes;

      indexContent += sb.name + ' ' + offset + ' ' + bodyBytes + '\n';
      offset += sectionSize;
    }

    // Rebuild with real index
    pfm = '#!PFM/1.0\n';
    pfm += '#@meta\n';
    for (const [k, v] of Object.entries(meta)) {
      if (k === '__proto__' || k === 'constructor' || k === 'prototype') continue;
      pfm += k + ': ' + v + '\n';
    }
    pfm += '#@index\n';
    pfm += indexContent;

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
        sections.push({ name: s.name.substring(0, 64), content });
      }
    }
    // Format 2: Flat key-value — each key becomes a section
    else {
      for (const [k, v] of Object.entries(data)) {
        if (k === '__proto__' || k === 'constructor' || k === 'prototype') continue;
        const content = typeof v === 'string' ? v : JSON.stringify(v, null, 2);
        sections.push({ name: k.substring(0, 64), content });
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
        const name = (cols[nameIdx] || '').trim().substring(0, 64);
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
        const sep = line.indexOf(':');
        if (sep !== -1) {
          const key = line.substring(0, sep).trim();
          const val = line.substring(sep + 1).trim();
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
      const name = lines[0].trim().substring(0, 64);
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
