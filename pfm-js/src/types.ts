/**
 * PFM Types — TypeScript definitions for the PFM file format.
 */

/** A single section in a PFM document. */
export interface PFMSection {
  /** Section name (e.g. "content", "chain", "tools"). */
  name: string;
  /** Section content (unescaped). */
  content: string;
}

/** Parsed metadata from a PFM document. */
export interface PFMMeta {
  /** Unique document identifier (UUID v4). */
  id?: string;
  /** Name/identifier of the generating agent. */
  agent?: string;
  /** Model ID used for generation. */
  model?: string;
  /** ISO-8601 creation timestamp. */
  created?: string;
  /** SHA-256 hash of all content sections. */
  checksum?: string;
  /** ID of parent .pfm document (for chains). */
  parent?: string;
  /** Comma-separated tags. */
  tags?: string;
  /** Document version (user-defined). */
  version?: string;
  /** Any additional custom metadata fields. */
  [key: string]: string | undefined;
}

/** A fully parsed PFM document. */
export interface PFMDocument {
  /** Format version (e.g. "1.0"). */
  formatVersion: string;
  /** Whether this is a streaming-mode document. */
  isStream: boolean;
  /** Document metadata. */
  meta: PFMMeta;
  /** Content sections (in order). */
  sections: PFMSection[];
}

/** Result of checksum validation. */
export interface ChecksumResult {
  /** Whether the checksum is valid. */
  valid: boolean;
  /** Expected checksum from metadata (empty string if missing). */
  expected: string;
  /** Computed checksum from section contents. */
  computed: string;
}

/** Known standard metadata field descriptions. */
export const META_FIELDS: Record<string, string> = {
  id: 'Unique document identifier (UUID v4)',
  agent: 'Name/identifier of the generating agent',
  model: 'Model ID used for generation',
  created: 'ISO-8601 creation timestamp',
  checksum: 'SHA-256 hash of all content sections',
  parent: 'ID of parent .pfm document (for chains)',
  tags: 'Comma-separated tags',
  version: 'Document version (user-defined)',
};

/** Known standard section type descriptions. */
export const SECTION_TYPES: Record<string, string> = {
  content: 'Primary output content from the agent',
  chain: 'Prompt chain / conversation that produced this output',
  tools: 'Tool calls made during generation',
  artifacts: 'Generated code, files, or structured data',
  reasoning: 'Agent reasoning / chain-of-thought',
  context: 'Context window snapshot at generation time',
  errors: 'Errors encountered during generation',
  metrics: 'Performance metrics (tokens, latency, cost)',
};
