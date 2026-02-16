/**
 * PFM Checksum — SHA-256 validation for PFM documents.
 *
 * Works in both Node.js (crypto module) and browsers (Web Crypto API).
 * Mirrors the Python PFMDocument.compute_checksum() logic exactly:
 *   - Iterate sections in order
 *   - Hash each section's unescaped content as UTF-8 bytes
 *   - Compare hex digest to meta.checksum
 */

import type { PFMDocument, PFMSection, ChecksumResult } from './types.js';

/**
 * Compute the SHA-256 checksum of a document's section contents.
 *
 * @param sections - Array of PFM sections.
 * @returns Hex-encoded SHA-256 hash string.
 *
 * @example
 * ```ts
 * import { parse, computeChecksum } from 'pfm';
 *
 * const doc = parse(text);
 * const hash = await computeChecksum(doc.sections);
 * console.log(hash === doc.meta.checksum); // true if valid
 * ```
 */
export async function computeChecksum(sections: PFMSection[]): Promise<string> {
  // Detect environment and use the appropriate crypto API
  if (typeof globalThis !== 'undefined' && (globalThis as any).crypto?.subtle) {
    return checksumWebCrypto(sections);
  }
  return checksumNode(sections);
}

/**
 * Validate a document's checksum against its metadata.
 *
 * Fail-closed: returns `{ valid: false }` if no checksum is present in meta.
 *
 * @param doc - A parsed PFMDocument.
 * @returns ChecksumResult with valid, expected, and computed fields.
 */
export async function validateChecksum(doc: PFMDocument): Promise<ChecksumResult> {
  const expected = doc.meta.checksum || '';
  const computed = await computeChecksum(doc.sections);

  return {
    valid: expected !== '' && computed === expected,
    expected,
    computed,
  };
}

/** Web Crypto API implementation (browsers + Node 18+). */
async function checksumWebCrypto(sections: PFMSection[]): Promise<string> {
  const encoder = new TextEncoder();
  const chunks: Uint8Array[] = [];
  let totalLen = 0;

  for (const section of sections) {
    const encoded = encoder.encode(section.content);
    chunks.push(encoded);
    totalLen += encoded.length;
  }

  // Concatenate all chunks
  const merged = new Uint8Array(totalLen);
  let offset = 0;
  for (const chunk of chunks) {
    merged.set(chunk, offset);
    offset += chunk.length;
  }

  const hashBuffer = await crypto.subtle.digest('SHA-256', merged);
  return hexEncode(new Uint8Array(hashBuffer));
}

/** Node.js crypto module implementation. */
async function checksumNode(sections: PFMSection[]): Promise<string> {
  const { createHash } = await import('crypto');
  const hash = createHash('sha256');
  for (const section of sections) {
    hash.update(section.content, 'utf8');
  }
  return hash.digest('hex');
}

/** Convert Uint8Array to hex string. */
function hexEncode(bytes: Uint8Array): string {
  let hex = '';
  for (let i = 0; i < bytes.length; i++) {
    hex += bytes[i].toString(16).padStart(2, '0');
  }
  return hex;
}
