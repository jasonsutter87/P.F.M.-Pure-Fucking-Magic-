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

  // Validate top-level structure
  if (data === null || typeof data !== 'object' || Array.isArray(data)) {
    throw new Error('Invalid PFM JSON: expected an object at top level');
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
  const safeSections = rawSections
    .filter((s: unknown): s is { name: string; content: string } =>
      s !== null &&
      typeof s === 'object' &&
      typeof (s as Record<string, unknown>).name === 'string' &&
      typeof (s as Record<string, unknown>).content === 'string'
    )
    .map((s: { name: string; content: string }) => ({
      name: String(s.name),
      content: String(s.content),
    }));

  return {
    formatVersion: typeof data.pfm_version === 'string' ? data.pfm_version : '1.0',
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
      if (meta[key]) parts.push(`${key}: ${meta[key]}`);
    }
    parts.push('---');
    parts.push('');
  }

  // Sections
  for (const section of doc.sections) {
    parts.push(`## ${section.name}`);
    parts.push('');
    parts.push(section.content);
    parts.push('');
  }

  return parts.join('\n');
}
