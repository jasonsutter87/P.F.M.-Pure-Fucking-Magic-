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

  // Iteratively calculate offsets (converges in <=3 passes)
  let index = '';
  let headerLen = encoder.encode(magic + meta).length;

  for (let pass = 0; pass < 4; pass++) {
    index = buildIndex(escaped, headerLen + encoder.encode(`#@index\n${index}`).length);
    const fullHeader = magic + meta + `#@index\n${index}`;
    const newHeaderLen = encoder.encode(fullHeader).length;
    if (newHeaderLen === headerLen + encoder.encode(`#@index\n${index}`).length - encoder.encode(`#@index\n${index}`).length + encoder.encode(`#@index\n${index}`).length) {
      // Already stable
    }
    headerLen = encoder.encode(magic + meta).length;
  }

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

/** Build the #@meta section text. */
function buildMeta(meta: Record<string, string | undefined>): string {
  let text = '#@meta\n';
  // Standard fields first, in canonical order
  const order = ['id', 'agent', 'model', 'created', 'checksum', 'parent', 'tags', 'version'];
  for (const key of order) {
    if (meta[key]) {
      text += `${key}: ${meta[key]}\n`;
    }
  }
  // Custom fields
  for (const [key, val] of Object.entries(meta)) {
    if (!order.includes(key) && val) {
      text += `${key}: ${val}\n`;
    }
  }
  return text;
}

/** Build the index entries. */
function buildIndex(
  sections: Array<{ name: string; content: string }>,
  startOffset: number
): string {
  const encoder = new TextEncoder();
  let index = '';
  let offset = startOffset;

  for (const s of sections) {
    const headerLine = `#@${s.name}\n`;
    const contentLine = s.content + '\n';
    const contentOffset = offset + encoder.encode(headerLine).length;
    const contentLen = encoder.encode(contentLine).length;
    index += `${s.name} ${contentOffset} ${contentLen}\n`;
    offset = contentOffset + contentLen;
  }

  return index;
}

/**
 * Escape content lines that could be confused with PFM markers.
 *
 * Matches the Python spec.escape_content_line() logic exactly:
 *   - Lines starting with #@ (section prefix)
 *   - Lines starting with \# (already-escaped prefix, must double-escape)
 *   - Lines starting with #!PFM (magic marker)
 *   - Lines starting with #!END (EOF marker)
 */
function escapeContent(content: string): string {
  return content
    .split('\n')
    .map((line) => {
      if (line.startsWith('#@') || line.startsWith('\\#')) {
        return '\\' + line;
      }
      if (line.startsWith('#!PFM') || line.startsWith('#!END')) {
        return '\\' + line;
      }
      return line;
    })
    .join('\n');
}
