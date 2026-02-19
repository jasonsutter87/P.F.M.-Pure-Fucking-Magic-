/**
 * PFM Serializer — Write PFM documents back to text.
 *
 * Mirrors the Python PFMWriter logic:
 *   - Magic line with format version
 *   - Meta section with key: value pairs
 *   - Index section with byte offsets
 *   - Content sections with escape of #@ and #! prefixes
 *   - EOF marker
 */

import type { PFMDocument, PFMSection } from './types.js';
import { computeChecksum } from './checksum.js';

/**
 * Serialize a PFMDocument to .pfm text format.
 *
 * Computes checksum and byte-offset index automatically.
 *
 * @param doc - The document to serialize.
 * @returns The complete .pfm file content as a string.
 *
 * @example
 * ```ts
 * import { serialize } from 'pfm';
 *
 * const text = await serialize({
 *   formatVersion: '1.0',
 *   isStream: false,
 *   meta: { id: 'abc', agent: 'my-agent', model: 'gpt-4' },
 *   sections: [{ name: 'content', content: 'Hello, world!' }],
 * });
 * fs.writeFileSync('output.pfm', text);
 * ```
 */
export async function serialize(doc: PFMDocument): Promise<string> {
  const encoder = new TextEncoder();

  // Validate section names
  const VALID_NAME = /^[a-z0-9_-]+$/;
  const RESERVED = new Set(['meta', 'index', 'index-trailing']);
  for (const s of doc.sections) {
    if (!s.name || s.name.length > 64 || !VALID_NAME.test(s.name)) {
      throw new Error(`Invalid section name: '${s.name}'. Only lowercase alphanumeric, hyphens, and underscores allowed (max 64 chars).`);
    }
    if (RESERVED.has(s.name)) {
      throw new Error(`Reserved section name: '${s.name}'`);
    }
  }

  // Compute checksum
  const checksum = await computeChecksum(doc.sections);

  // Escape section contents
  const escaped = doc.sections.map((s) => ({
    name: s.name,
    content: escapeContent(s.content),
  }));

  // Build header (magic + meta)
  const magic = `#!PFM/${doc.formatVersion}${doc.isStream ? ':STREAM' : ''}\n`;
  const meta = buildMeta({ ...doc.meta, checksum });

  // Final assembly with correct offsets
  const headerWithoutIndex = magic + meta;
  const headerBytes = encoder.encode(headerWithoutIndex).length;

  // Calculate final index with correct offsets
  const indexHeader = '#@index\n';
  // We need to iteratively find stable offsets
  let prevIndex = '';
  let finalIndex = '';
  for (let pass = 0; pass < 5; pass++) {
    const indexSize = encoder.encode(indexHeader + prevIndex).length;
    const sectionStart = headerBytes + indexSize;
    finalIndex = '';
    let offset = sectionStart;
    for (const s of escaped) {
      const sectionHeader = `#@${s.name}\n`;
      const sectionContent = s.content + '\n';
      const contentOffset = offset + encoder.encode(sectionHeader).length;
      const contentLen = encoder.encode(sectionContent).length;
      finalIndex += `${s.name} ${contentOffset} ${contentLen}\n`;
      offset = contentOffset + contentLen;
    }
    if (finalIndex === prevIndex) break;
    prevIndex = finalIndex;
  }

  // Assemble
  let result = headerWithoutIndex + indexHeader + finalIndex;
  for (const s of escaped) {
    result += `#@${s.name}\n${s.content}\n`;
  }
  result += '#!END\n';

  return result;
}

/**
 * Sanitize a meta value: strip control characters to prevent format injection.
 * A newline in a meta value would break PFM format parsing.
 */
function sanitizeMeta(value: string): string {
  // eslint-disable-next-line no-control-regex
  return value.replace(/[\x00-\x1f\x7f]/g, '');
}

/** Build the #@meta section text. */
function buildMeta(meta: Record<string, string | undefined>): string {
  let text = '#@meta\n';
  // Standard fields first, in canonical order
  const order = ['id', 'agent', 'model', 'created', 'checksum', 'parent', 'tags', 'version'];
  for (const key of order) {
    if (meta[key]) {
      text += `${sanitizeMeta(key)}: ${sanitizeMeta(meta[key]!)}\n`;
    }
  }
  // Custom fields
  for (const [key, val] of Object.entries(meta)) {
    if (!order.includes(key) && val) {
      text += `${sanitizeMeta(key)}: ${sanitizeMeta(val)}\n`;
    }
  }
  return text;
}

/**
 * Check if a line starts with zero or more backslashes followed by a PFM marker.
 * Used by both escape and unescape to handle arbitrary nesting depth.
 */
function hasMarkerAfterBackslashes(line: string): boolean {
  let i = 0;
  while (i < line.length && line[i] === '\\') i++;
  const rest = line.substring(i);
  return rest.startsWith('#@') || rest.startsWith('#!PFM') || rest.startsWith('#!END');
}

/**
 * Escape content lines that could be confused with PFM markers.
 *
 * Matches the Python spec.escape_content_line() logic exactly.
 * Handles arbitrary backslash nesting: \#@, \\#@, etc.
 */
function escapeContent(content: string): string {
  return content
    .split('\n')
    .map((line) => {
      if (hasMarkerAfterBackslashes(line)) {
        return '\\' + line;
      }
      return line;
    })
    .join('\n');
}
