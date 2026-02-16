/**
 * PFM Parser — Parses .pfm text into structured documents.
 *
 * Mirrors the Python PFMReader logic exactly:
 *   - Magic line detection (#!PFM/1.0 or #!PFM/1.0:STREAM)
 *   - Meta section parsing (key: value pairs)
 *   - Index section parsing (skipped — JS parser reads linearly)
 *   - Content section parsing with unescape of \#@ and \#! prefixes
 *   - EOF marker detection (#!END, with optional :offset for stream mode)
 */

import type { PFMDocument, PFMSection, PFMMeta } from './types.js';

const MAGIC = '#!PFM';
const EOF_MARKER = '#!END';
const SECTION_PREFIX = '#@';

/** Safety limits matching the Python implementation. */
const MAX_SECTIONS = 10_000;
const MAX_META_FIELDS = 100;
const MAX_SECTION_NAME_LENGTH = 64;

/** Keys that must never be set on objects from untrusted input. */
const FORBIDDEN_KEYS = new Set(['__proto__', 'constructor', 'prototype']);

/**
 * Parse a PFM file from its text content.
 *
 * @param text - The full text content of a .pfm file.
 * @returns A parsed PFMDocument.
 *
 * @example
 * ```ts
 * import { parse } from 'pfm';
 *
 * const text = fs.readFileSync('report.pfm', 'utf-8');
 * const doc = parse(text);
 *
 * console.log(doc.meta.agent);
 * for (const section of doc.sections) {
 *   console.log(section.name, section.content.length);
 * }
 * ```
 */
export function parse(text: string): PFMDocument {
  const lines = text.split('\n');
  const doc: PFMDocument = {
    formatVersion: '1.0',
    isStream: false,
    meta: {},
    sections: [],
  };

  let currentSection: string | null = null;
  let sectionLines: string[] = [];
  let inMeta = false;
  let inIndex = false;
  let metaFieldCount = 0;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    // Magic line
    if (line.startsWith(MAGIC)) {
      const slash = line.indexOf('/');
      if (slash !== -1) {
        const rest = line.substring(slash + 1);
        const colon = rest.indexOf(':');
        doc.formatVersion = colon !== -1 ? rest.substring(0, colon) : rest;
        doc.isStream = rest.includes(':STREAM');
      }
      continue;
    }

    // EOF marker
    if (line.startsWith(EOF_MARKER)) {
      flush();
      break;
    }

    // Section header (only unescaped lines -- escaped start with \#)
    if (line.startsWith(SECTION_PREFIX) && !line.startsWith('\\#')) {
      flush();
      const name = line.substring(SECTION_PREFIX.length);

      // Validate section name length
      if (name.length > MAX_SECTION_NAME_LENGTH) {
        currentSection = null;
        continue;
      }

      inMeta = name === 'meta';
      inIndex = name === 'index' || name === 'index:trailing';

      if (!inMeta && !inIndex) {
        // Enforce section count limit
        if (doc.sections.length >= MAX_SECTIONS) {
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

    // Meta key: value
    if (inMeta) {
      const sep = line.indexOf(': ');
      if (sep !== -1 && metaFieldCount < MAX_META_FIELDS) {
        const key = line.substring(0, sep).trim();
        const val = line.substring(sep + 2).trim();
        // Prevent prototype pollution: reject dangerous keys
        if (!FORBIDDEN_KEYS.has(key)) {
          (doc.meta as Record<string, string>)[key] = val;
          metaFieldCount++;
        }
      }
      continue;
    }

    // Index entries (skip)
    if (inIndex) {
      continue;
    }

    // Section content
    if (currentSection !== null) {
      sectionLines.push(unescapeLine(line));
    }
  }

  // Flush any remaining section (no EOF marker)
  flush();

  return doc;

  function flush(): void {
    if (currentSection === null) return;
    let content = sectionLines.join('\n');
    // Strip trailing newline (matches writer behavior)
    if (content.endsWith('\n')) {
      content = content.slice(0, -1);
    }
    doc.sections.push({ name: currentSection!, content });
    currentSection = null;
    sectionLines = [];
  }
}

/**
 * Quick check if text looks like a PFM file.
 *
 * @param text - First few bytes/lines of a file.
 * @returns `true` if the text starts with the PFM magic line.
 */
export function isPFM(text: string): boolean {
  return text.startsWith(MAGIC);
}

/**
 * Get a specific section by name from a parsed document.
 * Returns the first matching section, or `undefined` if not found.
 *
 * @param doc - A parsed PFMDocument.
 * @param name - Section name to find.
 * @returns The section content, or `undefined`.
 */
export function getSection(doc: PFMDocument, name: string): string | undefined {
  const section = doc.sections.find((s) => s.name === name);
  return section?.content;
}

/**
 * Get all sections with a given name.
 *
 * @param doc - A parsed PFMDocument.
 * @param name - Section name to find.
 * @returns Array of content strings.
 */
export function getSections(doc: PFMDocument, name: string): string[] {
  return doc.sections.filter((s) => s.name === name).map((s) => s.content);
}

/** Unescape a single content line (reverses writer escaping). */
function unescapeLine(line: string): string {
  if (line.startsWith('\\#')) {
    return line.substring(1);
  }
  return line;
}
