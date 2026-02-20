#!/usr/bin/env node
/**
 * PFM CLI (Node.js) — Command-line interface for .pfm files.
 *
 * Commands:
 *   pfm create    - Create a new .pfm file
 *   pfm inspect   - Show metadata and sections of a .pfm file
 *   pfm read      - Read a specific section from a .pfm file
 *   pfm validate  - Validate structure and checksum
 *   pfm convert   - Convert to/from JSON, Markdown
 *   pfm identify  - Quick check if a file is PFM format
 *   pfm spells    - List all PFM spells
 *
 * Spells (aliased commands):
 *   pfm accio            - Summon a section (alias for read)
 *   pfm polyjuice        - Transform format (alias for convert to)
 *   pfm prior-incantato  - Integrity + provenance (alias for validate)
 */

import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { resolve, basename, extname } from 'node:path';
import { parse, isPFM, getSection } from './parser.js';
import { serialize } from './serialize.js';
import { validateChecksum } from './checksum.js';
import { toJSON, fromJSON, toMarkdown, fromText, fromMarkdown, fromCSV, toCSV, toText } from './convert.js';
import type { PFMDocument } from './types.js';

const VERSION = '0.1.7';

function printUsage(): void {
  console.log('PFM - Pure Fucking Magic');
  console.log('AI agent output container format.\n');
  console.log('Usage:');
  console.log('  pfm create -a "my-agent" -m "gpt-4" -c "Hello world" -o output.pfm');
  console.log('  pfm inspect output.pfm');
  console.log('  pfm read output.pfm content');
  console.log('  pfm validate output.pfm');
  console.log('  pfm convert to json output.pfm -o output.json');
  console.log('  pfm convert from json data.json -o imported.pfm');
  console.log('  pfm identify output.pfm');
  console.log();
  console.log('Pipe from stdin:');
  console.log('  echo "Hello" | pfm create -a cli -o hello.pfm');
  console.log();
  console.log('Spells (aliased commands):');
  console.log('  pfm accio report.pfm content         Summon a section');
  console.log('  pfm polyjuice report.pfm json         Transform format');
  console.log('  pfm prior-incantato report.pfm        Integrity + provenance');
  console.log();
  console.log("Run 'pfm spells' for the full spellbook.");
  console.log("Run 'pfm <command> --help' for details on any command.");
  console.log("Run 'pfm --version' for version info.");
}

function readStdin(): Promise<string> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', (chunk: Buffer) => chunks.push(chunk));
    process.stdin.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
    process.stdin.on('error', reject);
    // If stdin is a TTY, resolve immediately with empty string
    if (process.stdin.isTTY) resolve('');
  });
}

function getFlag(args: string[], flag: string, shortFlag?: string): string | undefined {
  for (let i = 0; i < args.length; i++) {
    if (args[i] === flag || (shortFlag && args[i] === shortFlag)) {
      return args[i + 1];
    }
  }
  return undefined;
}

function hasFlag(args: string[], flag: string, shortFlag?: string): boolean {
  return args.includes(flag) || (shortFlag ? args.includes(shortFlag) : false);
}

function getPositional(args: string[]): string[] {
  const positional: string[] = [];
  const flags = new Set(['-a', '--agent', '-m', '--model', '-c', '--content', '-o', '--output', '-f', '--file', '-s', '--secret', '-p', '--password']);
  for (let i = 0; i < args.length; i++) {
    if (flags.has(args[i])) {
      i++; // skip value
      continue;
    }
    if (!args[i].startsWith('-')) {
      positional.push(args[i]);
    }
  }
  return positional;
}

async function cmdCreate(args: string[]): Promise<void> {
  if (hasFlag(args, '--help', '-h')) {
    console.log('Usage: pfm create [options]');
    console.log();
    console.log('Options:');
    console.log('  -a, --agent <name>    Agent name (default: "cli")');
    console.log('  -m, --model <id>      Model ID');
    console.log('  -c, --content <text>  Content string');
    console.log('  -f, --file <path>     Read content from file');
    console.log('  -o, --output <path>   Output file (default: output.pfm)');
    return;
  }

  const agent = getFlag(args, '--agent', '-a') || 'cli';
  const model = getFlag(args, '--model', '-m') || '';
  const contentFlag = getFlag(args, '--content', '-c');
  const fileFlag = getFlag(args, '--file', '-f');
  const output = getFlag(args, '--output', '-o') || 'output.pfm';

  let content: string;
  if (contentFlag) {
    content = contentFlag;
  } else if (fileFlag) {
    const filePath = resolve(fileFlag);
    if (!existsSync(filePath)) {
      console.error(`Error: File not found: ${fileFlag}`);
      process.exit(1);
    }
    content = readFileSync(filePath, 'utf-8');
  } else {
    content = await readStdin();
    if (!content) {
      console.error('Error: Provide content via --content, --file, or stdin');
      process.exit(1);
    }
  }

  const now = new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
  const id = crypto.randomUUID();

  const doc: PFMDocument = {
    formatVersion: '1.0',
    isStream: false,
    meta: { id, agent, model: model || undefined, created: now },
    sections: [{ name: 'content', content }],
  };

  const text = await serialize(doc);
  writeFileSync(output, text, 'utf-8');
  const bytes = Buffer.byteLength(text, 'utf-8');
  console.log(`Created ${output} (${bytes} bytes)`);
}

function cmdInspect(args: string[]): void {
  if (hasFlag(args, '--help', '-h')) {
    console.log('Usage: pfm inspect <path>');
    return;
  }
  const pos = getPositional(args);
  if (pos.length === 0) {
    console.error('Usage: pfm inspect <path>');
    process.exit(1);
  }
  const path = pos[0];
  const text = readFileSync(path, 'utf-8');
  const doc = parse(text);

  console.log(`PFM v${doc.formatVersion}`);
  console.log();
  console.log('META:');
  for (const [key, val] of Object.entries(doc.meta)) {
    if (val) {
      const display = val.length <= 72 ? val : val.slice(0, 69) + '...';
      console.log(`  ${key}: ${display}`);
    }
  }
  console.log();
  console.log('SECTIONS:');
  for (const section of doc.sections) {
    const bytes = Buffer.byteLength(section.content, 'utf-8');
    console.log(`  ${section.name.padEnd(16)}  ${bytes} bytes`);
  }
}

function cmdRead(args: string[]): void {
  if (hasFlag(args, '--help', '-h')) {
    console.log('Usage: pfm read <path> <section>');
    return;
  }
  const pos = getPositional(args);
  if (pos.length < 2) {
    console.error('Usage: pfm read <path> <section>');
    process.exit(1);
  }
  const [path, sectionName] = pos;
  const text = readFileSync(path, 'utf-8');
  const doc = parse(text);
  const content = getSection(doc, sectionName);
  if (content === undefined) {
    const available = doc.sections.map((s) => s.name).join(', ');
    console.error(`Section '${sectionName}' not found. Available: ${available}`);
    process.exit(1);
  }
  process.stdout.write(content);
}

async function cmdValidate(args: string[]): Promise<void> {
  if (hasFlag(args, '--help', '-h')) {
    console.log('Usage: pfm validate <path>');
    return;
  }
  const pos = getPositional(args);
  if (pos.length === 0) {
    console.error('Usage: pfm validate <path>');
    process.exit(1);
  }
  const path = pos[0];
  const text = readFileSync(path, 'utf-8');

  if (!isPFM(text)) {
    console.log(`FAIL: ${path} is not a valid PFM file (bad magic bytes)`);
    process.exit(1);
  }

  const doc = parse(text);
  const result = await validateChecksum(doc);
  if (result.valid) {
    const sections = doc.sections.map((s) => s.name).join(', ');
    console.log(`OK: ${path} is valid PFM v${doc.formatVersion}`);
    console.log(`    Sections: ${sections}`);
  } else {
    console.log(`FAIL: ${path} checksum mismatch`);
    process.exit(1);
  }
}

function inferFormat(filename: string): string | undefined {
  const ext = extname(filename).toLowerCase();
  const map: Record<string, string> = { '.json': 'json', '.md': 'md', '.markdown': 'md', '.txt': 'txt', '.csv': 'csv', '.pfm': 'pfm' };
  return map[ext];
}

async function cmdConvert(args: string[]): Promise<void> {
  if (hasFlag(args, '--help', '-h')) {
    console.log('Usage: pfm convert <to|from> [format] <input> [-o output]');
    console.log();
    console.log('Format is auto-detected from file extension if omitted.');
    console.log('  pfm convert from test.json           # infers json');
    console.log('  pfm convert to json report.pfm       # explicit');
    return;
  }
  const pos = getPositional(args);
  if (pos.length < 2) {
    console.error('Usage: pfm convert <to|from> [format] <input> [-o output]');
    console.error('Format is auto-detected from file extension if omitted.');
    process.exit(1);
  }

  let direction: string, format: string, input: string;
  const formats = new Set(['json', 'md', 'txt', 'csv']);

  if (pos.length >= 3 && formats.has(pos[1])) {
    // Explicit: pfm convert from json test.json
    [direction, format, input] = pos;
  } else {
    // Inferred: pfm convert from test.json  OR  pfm convert to report.pfm -o out.json
    direction = pos[0];
    input = pos[1];
    const output = getFlag(args, '--output', '-o');
    const inferred = inferFormat(input);
    const inferredFromOutput = output ? inferFormat(output) : undefined;
    // For "to": infer from -o flag since input is .pfm
    // For "from": infer from input file extension
    const resolved = (direction === 'to' && inferredFromOutput && inferredFromOutput !== 'pfm')
      ? inferredFromOutput
      : inferred;
    if (!resolved || resolved === 'pfm') {
      console.error(`Cannot infer format. Specify explicitly: pfm convert ${direction} <json|md> ${input}`);
      process.exit(1);
    }
    format = resolved;
  }

  const output = getFlag(args, '--output', '-o');

  if (direction === 'to') {
    const text = readFileSync(input, 'utf-8');
    const doc = parse(text);
    let result: string;
    if (format === 'json') {
      result = toJSON(doc);
    } else if (format === 'md') {
      result = toMarkdown(doc);
    } else if (format === 'csv') {
      result = toCSV(doc);
    } else if (format === 'txt') {
      result = toText(doc);
    } else {
      console.error(`Unsupported format: ${format}. Use: json, md, csv, txt`);
      process.exit(1);
      return;
    }
    if (output) {
      writeFileSync(output, result, 'utf-8');
      console.log(`Converted ${input} -> ${output}`);
    } else {
      process.stdout.write(result);
    }
  } else if (direction === 'from') {
    const data = readFileSync(input, 'utf-8');
    let doc: PFMDocument;
    if (format === 'json') {
      doc = fromJSON(data);
    } else if (format === 'md') {
      doc = fromMarkdown(data);
    } else if (format === 'csv') {
      doc = fromCSV(data);
    } else if (format === 'txt') {
      doc = fromText(data);
    } else {
      console.error(`Unsupported format for import: ${format}. Use: json, md, csv, txt`);
      process.exit(1);
      return;
    }
    const pfmText = await serialize(doc);
    const out = output || basename(input, extname(input)) + '.pfm';
    writeFileSync(out, pfmText, 'utf-8');
    const bytes = Buffer.byteLength(pfmText, 'utf-8');
    console.log(`Converted ${input} -> ${out} (${bytes} bytes)`);
  } else {
    console.error('Direction must be "to" or "from"');
    process.exit(1);
  }
}

function cmdIdentify(args: string[]): void {
  if (hasFlag(args, '--help', '-h')) {
    console.log('Usage: pfm identify <path>');
    return;
  }
  const pos = getPositional(args);
  if (pos.length === 0) {
    console.error('Usage: pfm identify <path>');
    process.exit(1);
  }
  const path = pos[0];
  const text = readFileSync(path, { encoding: 'utf-8', flag: 'r' });
  const first64 = text.slice(0, 64);
  if (isPFM(first64)) {
    console.log(`${path}: PFM file`);
  } else {
    console.log(`${path}: not PFM`);
    process.exit(1);
  }
}

function cmdSpells(): void {
  console.log('PFM Spells');
  console.log('Aliased API with Harry Potter spell names.\n');
  console.log('  accio <file> <section>           Summon a section from a .pfm file');
  console.log('                                   (alias for: pfm read)');
  console.log();
  console.log('  polyjuice <file> <format>        Transform to another format (json, md, csv, txt)');
  console.log('                                   (alias for: pfm convert to <format>)');
  console.log();
  console.log('  prior-incantato <file>            Reveal history and integrity of a document');
  console.log('                                   (alias for: pfm validate + provenance)');
  console.log();
  console.log('Note: fidelius (encrypt), revelio (decrypt), unbreakable-vow (sign),');
  console.log('and vow-kept (verify) are available in the Python CLI.');
  console.log('Install with: pip install get-pfm');
  console.log();
  console.log('Usage:');
  console.log('  pfm accio report.pfm content');
  console.log('  pfm polyjuice report.pfm json -o report.json');
  console.log('  pfm prior-incantato report.pfm');
  console.log();
  console.log('Python API:');
  console.log("  from pfm.spells import accio, polyjuice, fidelius, revelio");
  console.log("  content = accio('report.pfm', 'content')");
}

function cmdPolyjuice(args: string[]): void {
  if (hasFlag(args, '--help', '-h')) {
    console.log('Usage: pfm polyjuice <path> <format> [-o output]');
    console.log();
    console.log('Transform a .pfm file to another format.');
    console.log('Formats: json, md, csv, txt');
    return;
  }
  const pos = getPositional(args);
  if (pos.length < 2) {
    console.error('Usage: pfm polyjuice <path> <format> [-o output]');
    process.exit(1);
  }
  const [path, format] = pos;
  const output = getFlag(args, '--output', '-o');
  const text = readFileSync(path, 'utf-8');
  const doc = parse(text);

  let result: string;
  if (format === 'json') {
    result = toJSON(doc);
  } else if (format === 'md') {
    result = toMarkdown(doc);
  } else if (format === 'csv') {
    result = toCSV(doc);
  } else if (format === 'txt') {
    result = toText(doc);
  } else {
    console.error(`Unsupported format: ${format}. Use: json, md, csv, txt`);
    process.exit(1);
    return;
  }

  if (output) {
    writeFileSync(output, result, 'utf-8');
    console.log(`Converted ${path} -> ${output}`);
  } else {
    process.stdout.write(result);
  }
}

async function cmdPriorIncantato(args: string[]): Promise<void> {
  if (hasFlag(args, '--help', '-h')) {
    console.log('Usage: pfm prior-incantato <path>');
    console.log();
    console.log('Reveal the history and integrity of a .pfm document.');
    return;
  }
  const pos = getPositional(args);
  if (pos.length === 0) {
    console.error('Usage: pfm prior-incantato <path>');
    process.exit(1);
  }
  const path = pos[0];
  const text = readFileSync(path, 'utf-8');
  const doc = parse(text);
  const result = await validateChecksum(doc);

  console.log(`Prior Incantato: ${path}\n`);
  console.log(`  ID:         ${doc.meta.id || '(none)'}`);
  console.log(`  Agent:      ${doc.meta.agent || '(none)'}`);
  console.log(`  Model:      ${doc.meta.model || '(none)'}`);
  console.log(`  Created:    ${doc.meta.created || '(none)'}`);
  console.log(`  Integrity:  ${result.valid ? 'VALID' : 'INVALID'}`);
  console.log(`  Checksum:   ${result.computed}`);
  console.log(`  Signed:     ${doc.meta.signature ? 'Yes' : 'No'}`);
  console.log(`  Sections:   ${doc.sections.map((s) => s.name).join(', ')}`);
}

async function main(): Promise<void> {
  const args = process.argv.slice(2);

  if (args.length === 0) {
    printUsage();
    process.exit(0);
  }

  // Top-level flags
  if (args[0] === '--version' || args[0] === '-v' || args[0] === '-V') {
    console.log(`pfm ${VERSION}`);
    return;
  }
  if (args[0] === '--help' || args[0] === '-h' || args[0] === '-help') {
    printUsage();
    return;
  }

  const command = args[0];
  const rest = args.slice(1);

  switch (command) {
    case 'create':
      await cmdCreate(rest);
      break;
    case 'inspect':
      cmdInspect(rest);
      break;
    case 'read':
    case 'accio':
      cmdRead(rest);
      break;
    case 'validate':
      await cmdValidate(rest);
      break;
    case 'convert':
      await cmdConvert(rest);
      break;
    case 'identify':
      cmdIdentify(rest);
      break;
    case 'spells':
      cmdSpells();
      break;
    case 'polyjuice':
      cmdPolyjuice(rest);
      break;
    case 'prior-incantato':
      await cmdPriorIncantato(rest);
      break;
    default:
      console.error(`Unknown command: ${command}`);
      console.error("Run 'pfm --help' for usage.");
      process.exit(1);
  }
}

main().catch((err) => {
  console.error(`Error: ${err instanceof Error ? err.message : String(err)}`);
  process.exit(1);
});
