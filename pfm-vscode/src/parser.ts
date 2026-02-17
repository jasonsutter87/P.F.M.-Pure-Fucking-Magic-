/**
 * Lightweight PFM parser for VS Code extension.
 * Parses .pfm text into structured data for use by providers.
 */

export interface PFMSection {
  name: string;
  content: string;
  /** Line number (0-indexed) of the #@ header */
  headerLine: number;
  /** Line number (0-indexed) of first content line */
  contentStartLine: number;
  /** Line number (0-indexed) of last content line */
  contentEndLine: number;
}

export interface PFMMeta {
  [key: string]: string;
}

export interface PFMDocument {
  formatVersion: string;
  isStream: boolean;
  meta: PFMMeta;
  sections: PFMSection[];
  /** Line number of #!PFM magic line */
  magicLine: number;
  /** Line number of #!END marker (-1 if not found) */
  eofLine: number;
}

const MAGIC = '#!PFM';
const EOF_MARKER = '#!END';
const SECTION_PREFIX = '#@';

/** Safety limits. */
const MAX_SECTIONS = 10_000;
const MAX_META_FIELDS = 100;
const MAX_SECTION_NAME_LENGTH = 64;

/** Keys that must never be set on objects from untrusted input. */
const FORBIDDEN_KEYS = new Set(['__proto__', 'constructor', 'prototype']);

/** Known meta field descriptions for hover tooltips. */
export const META_FIELD_DESCRIPTIONS: Record<string, string> = {
  id: 'Unique document identifier (UUID v4)',
  agent: 'Name/identifier of the generating agent',
  model: 'Model ID used for generation',
  created: 'ISO-8601 creation timestamp',
  checksum: 'SHA-256 hash of all content sections',
  parent: 'ID of parent .pfm document (for chains)',
  tags: 'Comma-separated tags',
  version: 'Document version (user-defined)',
};

/** Known section type descriptions for hover tooltips. */
export const SECTION_DESCRIPTIONS: Record<string, string> = {
  content: 'Primary output content from the agent',
  chain: 'Prompt chain / conversation that produced this output',
  tools: 'Tool calls made during generation',
  artifacts: 'Generated code, files, or structured data',
  reasoning: 'Agent reasoning / chain-of-thought',
  context: 'Context window snapshot at generation time',
  errors: 'Errors encountered during generation',
  metrics: 'Performance metrics (tokens, latency, cost)',
};

/**
 * Parse PFM text into a structured document.
 */
export function parsePFM(text: string): PFMDocument {
  const lines = text.split('\n');
  const doc: PFMDocument = {
    formatVersion: '1.0',
    isStream: false,
    meta: {},
    sections: [],
    magicLine: 0,
    eofLine: -1,
  };

  let currentSection: string | null = null;
  let sectionLines: string[] = [];
  let sectionHeaderLine = -1;
  let sectionContentStart = -1;
  let inMeta = false;
  let inIndex = false;
  let metaFieldCount = 0;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    // Magic line
    if (line.startsWith(MAGIC)) {
      doc.magicLine = i;
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

    // EOF marker
    if (line.startsWith(EOF_MARKER)) {
      doc.eofLine = i;
      // Flush last section
      flushSection();
      break;
    }

    // Section header (not escaped)
    if (line.startsWith(SECTION_PREFIX) && !line.startsWith('\\#')) {
      flushSection();
      const name = line.substring(SECTION_PREFIX.length);

      // Validate section name length
      if (name.length > MAX_SECTION_NAME_LENGTH) {
        currentSection = null;
        continue;
      }

      inMeta = name === 'meta';
      inIndex = name === 'index' || name === 'index-trailing';

      if (!inMeta && !inIndex) {
        // Enforce section count limit
        if (doc.sections.length >= MAX_SECTIONS) {
          currentSection = null;
          continue;
        }
        currentSection = name;
        sectionHeaderLine = i;
        sectionContentStart = i + 1;
        sectionLines = [];
      } else {
        currentSection = null;
      }
      continue;
    }

    // Meta parsing
    if (inMeta) {
      const sepIdx = line.indexOf(': ');
      if (sepIdx !== -1) {
        const key = line.substring(0, sepIdx).trim();
        const val = line.substring(sepIdx + 2).trim();
        // Prevent prototype pollution and enforce field count limit (O(1) check)
        if (!FORBIDDEN_KEYS.has(key) && metaFieldCount < MAX_META_FIELDS) {
          doc.meta[key] = val;
          metaFieldCount++;
        }
      }
      continue;
    }

    // Index parsing (skip)
    if (inIndex) {
      continue;
    }

    // Section content
    if (currentSection !== null) {
      sectionLines.push(unescapeLine(line));
    }
  }

  // Flush any remaining section (if no EOF marker)
  flushSection();

  return doc;

  function flushSection(): void {
    if (currentSection === null) return;
    let content = sectionLines.join('\n');
    // Strip trailing newline (matches writer behavior)
    if (content.endsWith('\n')) {
      content = content.slice(0, -1);
    }
    doc.sections.push({
      name: currentSection,
      content,
      headerLine: sectionHeaderLine,
      contentStartLine: sectionContentStart,
      contentEndLine: sectionContentStart + sectionLines.length - 1,
    });
    currentSection = null;
    sectionLines = [];
  }
}

/** Check if line has a PFM marker after any leading backslashes. */
function hasMarkerAfterBackslashes(line: string): boolean {
  let i = 0;
  while (i < line.length && line[i] === '\\') i++;
  const rest = line.substring(i);
  return rest.startsWith('#@') || rest.startsWith('#!PFM') || rest.startsWith('#!END');
}

function unescapeLine(line: string): string {
  if (line.startsWith('\\') && hasMarkerAfterBackslashes(line.substring(1))) {
    return line.substring(1);
  }
  return line;
}

/**
 * Compute SHA-256 checksum of section contents (matches Python implementation).
 */
export async function computeChecksum(sections: PFMSection[]): Promise<string> {
  // Use Web Crypto API (available in VS Code's Node.js)
  const crypto = await import('crypto');
  const hash = crypto.createHash('sha256');
  for (const section of sections) {
    hash.update(section.content, 'utf8');
  }
  return hash.digest('hex');
}
