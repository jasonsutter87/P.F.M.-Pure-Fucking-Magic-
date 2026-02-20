/**
 * PFM Converters — Convert PFM documents to JSON and Markdown.
 */

import type { PFMDocument } from './types.js';

/**
 * Convert a PFM document to a JSON string.
 *
 * @param doc - A parsed PFMDocument.
 * @param indent - JSON indentation (default: 2).
 * @returns Pretty-printed JSON string.
 */
export function toJSON(doc: PFMDocument, indent = 2): string {
  return JSON.stringify(
    {
      pfm_version: doc.formatVersion,
      meta: doc.meta,
      sections: doc.sections.map((s) => ({
        name: s.name,
        content: s.content,
      })),
    },
    null,
    indent
  );
}

/** Keys that must never be set on objects from untrusted input. */
const FORBIDDEN_KEYS = new Set(['__proto__', 'constructor', 'prototype']);

/**
 * Parse a PFM JSON export back into a PFMDocument.
 *
 * Validates input structure and rejects prototype pollution attempts.
 *
 * @param json - JSON string (as produced by `toJSON`).
 * @returns A PFMDocument.
 * @throws {Error} If the JSON structure is invalid.
 */
export function fromJSON(json: string): PFMDocument {
  const data = JSON.parse(json);

  // If it's not a PFM-structured export, wrap raw JSON as content
  if (data === null || typeof data !== 'object' || Array.isArray(data) || !('sections' in data)) {
    return {
      formatVersion: '1.0',
      isStream: false,
      meta: { agent: 'json-import', created: new Date().toISOString().replace(/\.\d{3}Z$/, 'Z') },
      sections: [{ name: 'content', content: JSON.stringify(data, null, 2) }],
    };
  }

  // Validate and sanitize meta (prevent prototype pollution)
  const rawMeta = data.meta;
  const safeMeta: Record<string, string> = {};
  if (rawMeta && typeof rawMeta === 'object' && !Array.isArray(rawMeta)) {
    for (const [key, val] of Object.entries(rawMeta)) {
      if (FORBIDDEN_KEYS.has(key)) continue;
      if (typeof val === 'string') {
        safeMeta[key] = val;
      }
    }
  }

  // Validate and sanitize sections
  const rawSections = Array.isArray(data.sections) ? data.sections : [];
  const VALID_NAME = /^[a-z0-9_-]+$/;
  const RESERVED_NAMES = new Set(['meta', 'index', 'index-trailing']);
  const safeSections = rawSections
    .filter((s: unknown): s is { name: string; content: string } =>
      s !== null &&
      typeof s === 'object' &&
      typeof (s as Record<string, unknown>).name === 'string' &&
      typeof (s as Record<string, unknown>).content === 'string'
    )
    .filter((s: { name: string }) =>
      s.name.length > 0 &&
      s.name.length <= 64 &&
      VALID_NAME.test(s.name) &&
      !RESERVED_NAMES.has(s.name)
    )
    .map((s: { name: string; content: string }) => ({
      name: String(s.name),
      content: String(s.content),
    }));

  const version = typeof data.pfm_version === 'string' ? data.pfm_version : '1.0';
  if (version !== '1.0') {
    throw new Error(`Unsupported PFM format version: '${version}'`);
  }

  return {
    formatVersion: version,
    isStream: false,
    meta: safeMeta,
    sections: safeSections,
  };
}

/**
 * Convert a PFM document to Markdown.
 *
 * Meta becomes YAML-style frontmatter, sections become ## headers.
 *
 * @param doc - A parsed PFMDocument.
 * @returns Markdown string.
 */
export function toMarkdown(doc: PFMDocument): string {
  const parts: string[] = [];

  // Frontmatter
  const meta = doc.meta;
  const keys = Object.keys(meta);
  if (keys.length > 0) {
    parts.push('---');
    for (const key of keys) {
      if (meta[key]) {
        // Sanitize key: only allow alphanumeric, hyphens, underscores
        const safeKey = key.replace(/[^a-zA-Z0-9_-]/g, '_');
        // Sanitize value: replace newlines, escape frontmatter delimiters
        const safeVal = meta[key]!.replace(/\n/g, ' ').replace(/---/g, '\\---');
        parts.push(`${safeKey}: ${safeVal}`);
      }
    }
    parts.push('---');
    parts.push('');
  }

  // Sections (sanitize names to prevent injection via markdown headings)
  for (const section of doc.sections) {
    const safeName = section.name.replace(/[^a-z0-9_-]/g, '_');
    parts.push(`## ${safeName}`);
    parts.push('');
    parts.push(section.content);
    parts.push('');
  }

  return parts.join('\n');
}
