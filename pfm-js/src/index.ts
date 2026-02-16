/**
 * PFM — Pure Fucking Magic
 *
 * JavaScript/TypeScript library for reading, writing, and validating
 * .pfm AI agent output files.
 *
 * @example
 * ```ts
 * import { parse, getSection, validateChecksum } from 'pfm';
 *
 * const doc = parse(pfmText);
 * console.log(doc.meta.agent);
 * console.log(getSection(doc, 'content'));
 *
 * const result = await validateChecksum(doc);
 * console.log(result.valid ? 'VALID' : 'INVALID');
 * ```
 *
 * @packageDocumentation
 */

// Types
export type {
  PFMDocument,
  PFMSection,
  PFMMeta,
  ChecksumResult,
} from './types.js';

export { META_FIELDS, SECTION_TYPES } from './types.js';

// Parser
export { parse, isPFM, getSection, getSections } from './parser.js';

// Checksum
export { computeChecksum, validateChecksum } from './checksum.js';

// Serializer
export { serialize } from './serialize.js';

// Converters
export { toJSON, fromJSON, toMarkdown } from './convert.js';
