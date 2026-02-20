# pfm

JavaScript/TypeScript library for reading, writing, and validating **.pfm** (Pure Fucking Magic) AI agent output files.

Zero dependencies. Works in Node.js 18+ and browsers.

## Install

```bash
npm install get-pfm
```

## Quick Start

```ts
import { parse, getSection, validateChecksum } from 'get-pfm';
import fs from 'fs';

// Parse a .pfm file
const text = fs.readFileSync('report.pfm', 'utf-8');
const doc = parse(text);

// Access metadata
console.log(doc.meta.agent);   // "claude-code"
console.log(doc.meta.model);   // "claude-opus-4-6"
console.log(doc.meta.created); // "2026-02-16T..."

// Read sections
console.log(getSection(doc, 'content'));
console.log(doc.sections.map(s => s.name)); // ["content", "chain", "tools", ...]

// Validate checksum
const result = await validateChecksum(doc);
console.log(result.valid ? 'VALID' : 'INVALID');
```

## API

### Parsing

```ts
parse(text: string): PFMDocument
```
Parse .pfm text into a structured document.

```ts
isPFM(text: string): boolean
```
Quick check if text starts with the PFM magic line.

```ts
getSection(doc: PFMDocument, name: string): string | undefined
```
Get a section's content by name (first match).

```ts
getSections(doc: PFMDocument, name: string): string[]
```
Get all sections with a given name.

### Checksum

```ts
computeChecksum(sections: PFMSection[]): Promise<string>
```
Compute SHA-256 checksum of section contents (hex string).

```ts
validateChecksum(doc: PFMDocument): Promise<ChecksumResult>
```
Validate a document's checksum against its metadata. Fail-closed: returns `{ valid: false }` if no checksum present.

### Serialization

```ts
serialize(doc: PFMDocument): Promise<string>
```
Serialize a document to .pfm text format. Computes checksum and byte-offset index automatically.

### Conversion

```ts
toJSON(doc: PFMDocument, indent?: number): string
fromJSON(json: string): PFMDocument
toMarkdown(doc: PFMDocument): string
```

### Types

```ts
interface PFMDocument {
  formatVersion: string;
  isStream: boolean;
  meta: PFMMeta;
  sections: PFMSection[];
}

interface PFMSection {
  name: string;
  content: string;
}

interface PFMMeta {
  id?: string;
  agent?: string;
  model?: string;
  created?: string;
  checksum?: string;
  parent?: string;
  tags?: string;
  version?: string;
  [key: string]: string | undefined;
}

interface ChecksumResult {
  valid: boolean;
  expected: string;
  computed: string;
}
```

### Constants

```ts
META_FIELDS    // Record<string, string> — descriptions of standard meta keys
SECTION_TYPES  // Record<string, string> — descriptions of standard section types
```

## Browser Usage

Works in any modern browser via CDN or bundler:

```html
<script type="module">
  import { parse, validateChecksum } from 'https://esm.sh/get-pfm';

  const response = await fetch('report.pfm');
  const doc = parse(await response.text());
  const { valid } = await validateChecksum(doc);
</script>
```

## CommonJS

```js
const { parse, getSection } = require('get-pfm');
```

## License

MIT
