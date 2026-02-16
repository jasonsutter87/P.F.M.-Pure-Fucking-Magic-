/**
 * PFM npm package tests — uses Node.js built-in test runner.
 */

import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import {
  parse,
  isPFM,
  getSection,
  getSections,
  computeChecksum,
  validateChecksum,
  toJSON,
  fromJSON,
  toMarkdown,
  serialize,
  META_FIELDS,
  SECTION_TYPES,
} from '../index.js';
import type { PFMDocument } from '../types.js';

const EXAMPLE_PFM = `#!PFM/1.0
#@meta
id: abc-123
agent: test-agent
model: test-model
created: 2026-01-01T00:00:00Z
checksum: placeholder
tags: test,demo
version: 1.0
#@index
content 200 13
chain 220 10
#@content
Hello, world!
#@chain
Some chain
#!END
`;

// ================================================================
// Parser
// ================================================================

describe('parse', () => {
  it('parses magic line and format version', () => {
    const doc = parse(EXAMPLE_PFM);
    assert.equal(doc.formatVersion, '1.0');
    assert.equal(doc.isStream, false);
  });

  it('parses metadata fields', () => {
    const doc = parse(EXAMPLE_PFM);
    assert.equal(doc.meta.id, 'abc-123');
    assert.equal(doc.meta.agent, 'test-agent');
    assert.equal(doc.meta.model, 'test-model');
    assert.equal(doc.meta.tags, 'test,demo');
  });

  it('parses sections in order', () => {
    const doc = parse(EXAMPLE_PFM);
    assert.equal(doc.sections.length, 2);
    assert.equal(doc.sections[0].name, 'content');
    assert.equal(doc.sections[0].content, 'Hello, world!');
    assert.equal(doc.sections[1].name, 'chain');
    assert.equal(doc.sections[1].content, 'Some chain');
  });

  it('handles stream mode flag', () => {
    const stream = '#!PFM/1.0:STREAM\n#@meta\nagent: x\n#@content\nhi\n#!END\n';
    const doc = parse(stream);
    assert.equal(doc.isStream, true);
    assert.equal(doc.formatVersion, '1.0');
  });

  it('unescapes content lines', () => {
    const pfm = '#!PFM/1.0\n#@meta\n#@content\nline1\n\\#@fake\n\\#!END\nline4\n#!END\n';
    const doc = parse(pfm);
    assert.equal(doc.sections[0].content, 'line1\n#@fake\n#!END\nline4');
  });

  it('handles missing EOF marker', () => {
    const noeof = '#!PFM/1.0\n#@meta\nagent: x\n#@content\nhello';
    const doc = parse(noeof);
    assert.equal(doc.sections.length, 1);
    assert.equal(doc.sections[0].content, 'hello');
  });

  it('handles empty sections', () => {
    const pfm = '#!PFM/1.0\n#@meta\n#@content\n#@chain\ndata\n#!END\n';
    const doc = parse(pfm);
    assert.equal(doc.sections.length, 2);
    assert.equal(doc.sections[0].name, 'content');
    assert.equal(doc.sections[0].content, '');
    assert.equal(doc.sections[1].content, 'data');
  });

  it('handles multiline content', () => {
    const pfm = '#!PFM/1.0\n#@meta\n#@content\nline1\nline2\nline3\n#!END\n';
    const doc = parse(pfm);
    assert.equal(doc.sections[0].content, 'line1\nline2\nline3');
  });

  it('handles custom meta fields', () => {
    const pfm = '#!PFM/1.0\n#@meta\nagent: x\ncustom_field: custom_value\n#@content\nhi\n#!END\n';
    const doc = parse(pfm);
    assert.equal(doc.meta.custom_field, 'custom_value');
  });
});

// ================================================================
// isPFM
// ================================================================

describe('isPFM', () => {
  it('returns true for PFM text', () => {
    assert.equal(isPFM('#!PFM/1.0\n'), true);
    assert.equal(isPFM('#!PFM/1.0:STREAM\n'), true);
  });

  it('returns false for non-PFM text', () => {
    assert.equal(isPFM('not a pfm file'), false);
    assert.equal(isPFM(''), false);
    assert.equal(isPFM('{"json": true}'), false);
  });
});

// ================================================================
// getSection / getSections
// ================================================================

describe('getSection', () => {
  const doc = parse(EXAMPLE_PFM);

  it('returns section content by name', () => {
    assert.equal(getSection(doc, 'content'), 'Hello, world!');
    assert.equal(getSection(doc, 'chain'), 'Some chain');
  });

  it('returns undefined for missing section', () => {
    assert.equal(getSection(doc, 'nope'), undefined);
  });
});

describe('getSections', () => {
  it('returns all sections with given name', () => {
    const pfm = '#!PFM/1.0\n#@meta\n#@content\nfirst\n#@content\nsecond\n#!END\n';
    const doc = parse(pfm);
    const contents = getSections(doc, 'content');
    assert.equal(contents.length, 2);
    assert.equal(contents[0], 'first');
    assert.equal(contents[1], 'second');
  });

  it('returns empty array for missing section', () => {
    const doc = parse(EXAMPLE_PFM);
    assert.deepEqual(getSections(doc, 'nope'), []);
  });
});

// ================================================================
// Checksum
// ================================================================

describe('computeChecksum', () => {
  it('returns hex SHA-256 digest', async () => {
    const hash = await computeChecksum([{ name: 'content', content: 'hello' }]);
    assert.equal(typeof hash, 'string');
    assert.equal(hash.length, 64);
    assert.match(hash, /^[0-9a-f]{64}$/);
  });

  it('is deterministic', async () => {
    const sections = [{ name: 'a', content: 'test' }];
    const h1 = await computeChecksum(sections);
    const h2 = await computeChecksum(sections);
    assert.equal(h1, h2);
  });

  it('changes with different content', async () => {
    const h1 = await computeChecksum([{ name: 'a', content: 'hello' }]);
    const h2 = await computeChecksum([{ name: 'a', content: 'world' }]);
    assert.notEqual(h1, h2);
  });
});

describe('validateChecksum', () => {
  it('returns valid=false when no checksum in meta', async () => {
    const doc = parse('#!PFM/1.0\n#@meta\nagent: x\n#@content\nhi\n#!END\n');
    const result = await validateChecksum(doc);
    assert.equal(result.valid, false);
  });

  it('validates a correct checksum', async () => {
    // First compute what the checksum should be
    const hash = await computeChecksum([{ name: 'content', content: 'hi' }]);
    const pfm = `#!PFM/1.0\n#@meta\nchecksum: ${hash}\n#@content\nhi\n#!END\n`;
    const doc = parse(pfm);
    const result = await validateChecksum(doc);
    assert.equal(result.valid, true);
    assert.equal(result.expected, hash);
    assert.equal(result.computed, hash);
  });

  it('rejects incorrect checksum', async () => {
    const pfm = '#!PFM/1.0\n#@meta\nchecksum: deadbeef\n#@content\nhi\n#!END\n';
    const doc = parse(pfm);
    const result = await validateChecksum(doc);
    assert.equal(result.valid, false);
    assert.equal(result.expected, 'deadbeef');
    assert.notEqual(result.computed, 'deadbeef');
  });
});

// ================================================================
// Converters
// ================================================================

describe('toJSON / fromJSON', () => {
  it('round-trips through JSON', () => {
    const doc = parse(EXAMPLE_PFM);
    const json = toJSON(doc);
    const parsed = JSON.parse(json);

    assert.equal(parsed.pfm_version, '1.0');
    assert.equal(parsed.meta.agent, 'test-agent');
    assert.equal(parsed.sections.length, 2);
    assert.equal(parsed.sections[0].name, 'content');
  });

  it('fromJSON restores document structure', () => {
    const doc = parse(EXAMPLE_PFM);
    const json = toJSON(doc);
    const restored = fromJSON(json);

    assert.equal(restored.formatVersion, '1.0');
    assert.equal(restored.meta.agent, 'test-agent');
    assert.equal(restored.sections.length, 2);
    assert.equal(restored.sections[0].content, 'Hello, world!');
  });
});

describe('toMarkdown', () => {
  it('produces markdown with frontmatter', () => {
    const doc = parse(EXAMPLE_PFM);
    const md = toMarkdown(doc);

    assert.ok(md.startsWith('---\n'));
    assert.ok(md.includes('agent: test-agent'));
    assert.ok(md.includes('## content'));
    assert.ok(md.includes('Hello, world!'));
    assert.ok(md.includes('## chain'));
  });
});

// ================================================================
// Serialize
// ================================================================

describe('serialize', () => {
  it('produces valid PFM text', async () => {
    const doc: PFMDocument = {
      formatVersion: '1.0',
      isStream: false,
      meta: { agent: 'test', model: 'test-model' },
      sections: [{ name: 'content', content: 'Hello!' }],
    };

    const text = await serialize(doc);
    assert.ok(text.startsWith('#!PFM/1.0\n'));
    assert.ok(text.includes('#@meta\n'));
    assert.ok(text.includes('agent: test\n'));
    assert.ok(text.includes('#@content\n'));
    assert.ok(text.includes('Hello!\n'));
    assert.ok(text.includes('#!END\n'));
    assert.ok(text.includes('#@index\n'));
  });

  it('round-trips parse -> serialize -> parse', async () => {
    const original: PFMDocument = {
      formatVersion: '1.0',
      isStream: false,
      meta: { agent: 'roundtrip', model: 'gpt-4' },
      sections: [
        { name: 'content', content: 'Line one\nLine two' },
        { name: 'chain', content: 'User: hello\nAgent: hi' },
      ],
    };

    const text = await serialize(original);
    const restored = parse(text);

    assert.equal(restored.meta.agent, 'roundtrip');
    assert.equal(restored.sections.length, 2);
    assert.equal(restored.sections[0].content, 'Line one\nLine two');
    assert.equal(restored.sections[1].content, 'User: hello\nAgent: hi');
  });

  it('serialized checksum validates', async () => {
    const doc: PFMDocument = {
      formatVersion: '1.0',
      isStream: false,
      meta: { agent: 'test' },
      sections: [{ name: 'content', content: 'Check me' }],
    };

    const text = await serialize(doc);
    const parsed = parse(text);
    const result = await validateChecksum(parsed);
    assert.equal(result.valid, true);
  });

  it('escapes dangerous content lines', async () => {
    const doc: PFMDocument = {
      formatVersion: '1.0',
      isStream: false,
      meta: {},
      sections: [{ name: 'content', content: '#@fake\n#!END\nnormal line' }],
    };

    const text = await serialize(doc);
    assert.ok(text.includes('\\#@fake'));
    assert.ok(text.includes('\\#!END'));

    // Verify round-trip preserves the dangerous content
    const parsed = parse(text);
    assert.equal(parsed.sections[0].content, '#@fake\n#!END\nnormal line');
  });
});

// ================================================================
// Constants
// ================================================================

describe('constants', () => {
  it('META_FIELDS has standard keys', () => {
    assert.ok('id' in META_FIELDS);
    assert.ok('agent' in META_FIELDS);
    assert.ok('checksum' in META_FIELDS);
  });

  it('SECTION_TYPES has standard sections', () => {
    assert.ok('content' in SECTION_TYPES);
    assert.ok('chain' in SECTION_TYPES);
    assert.ok('tools' in SECTION_TYPES);
    assert.ok('metrics' in SECTION_TYPES);
  });
});
