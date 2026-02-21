/**
 * PFM Export — Turn parser and training data exporters.
 *
 * Converts .pfm conversation files into fine-tuning JSONL formats:
 *   - OpenAI  (messages array with system/user/assistant roles)
 *   - Alpaca  (instruction/input/output per turn pair)
 *   - ShareGPT (conversations array with human/gpt roles)
 */

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, extname } from 'node:path';
import { parse } from './parser.js';
import type { PFMDocument } from './types.js';

// ---------------------------------------------------------------------------
// Turn parser
// ---------------------------------------------------------------------------

export interface Turn {
  role: 'user' | 'assistant';
  content: string;
}

export function parseTurns(text: string): Turn[] {
  const turns: Turn[] = [];
  if (!text || !text.trim()) return turns;

  const blocks = text.split('\n\n');
  let currentRole: 'user' | 'assistant' | null = null;
  let currentLines: string[] = [];

  for (const block of blocks) {
    const stripped = block.trim();
    if (!stripped) continue;

    if (stripped.startsWith('User:')) {
      if (currentRole !== null) {
        turns.push({ role: currentRole, content: currentLines.join('\n\n').trim() });
      }
      currentRole = 'user';
      currentLines = [stripped.slice('User:'.length).trim()];
    } else if (stripped.startsWith('Assistant:')) {
      if (currentRole !== null) {
        turns.push({ role: currentRole, content: currentLines.join('\n\n').trim() });
      }
      currentRole = 'assistant';
      currentLines = [stripped.slice('Assistant:'.length).trim()];
    } else if (stripped.startsWith('Agent:')) {
      if (currentRole !== null) {
        turns.push({ role: currentRole, content: currentLines.join('\n\n').trim() });
      }
      currentRole = 'assistant';
      currentLines = [stripped.slice('Agent:'.length).trim()];
    } else {
      if (currentRole !== null) {
        currentLines.push(stripped);
      } else {
        currentRole = 'assistant';
        currentLines = [stripped];
      }
    }
  }

  if (currentRole !== null) {
    turns.push({ role: currentRole, content: currentLines.join('\n\n').trim() });
  }

  return turns;
}

// ---------------------------------------------------------------------------
// Metadata extractor
// ---------------------------------------------------------------------------

interface ExportMeta {
  model?: string;
  platform?: string;
  source_url?: string;
  title?: string;
}

function extractMetadata(doc: PFMDocument): ExportMeta {
  const meta: ExportMeta = {};
  if (doc.meta.model) meta.model = doc.meta.model;
  if (doc.meta.agent) meta.platform = doc.meta.agent;
  if (doc.meta.source_url) meta.source_url = doc.meta.source_url;
  if (doc.meta.title) meta.title = doc.meta.title;
  // Also check for platform key directly
  if (doc.meta.platform) meta.platform = doc.meta.platform;
  return meta;
}

function getSection(doc: PFMDocument, name: string): string | undefined {
  const section = doc.sections.find((s) => s.name === name);
  return section?.content;
}

// ---------------------------------------------------------------------------
// Format exporters
// ---------------------------------------------------------------------------

function exportOpenAI(
  turns: Turn[],
  meta: ExportMeta,
): { line: string; turnCount: number } {
  const platform = meta.platform || 'unknown';
  const model = meta.model || 'unknown';
  const systemMsg = `Conversation from ${platform} using ${model}`;

  const messages: Array<{ role: string; content: string }> = [
    { role: 'system', content: systemMsg },
  ];
  for (const turn of turns) {
    messages.push({ role: turn.role, content: turn.content });
  }

  return { line: JSON.stringify({ messages }), turnCount: turns.length };
}

function exportAlpaca(
  turns: Turn[],
  meta: ExportMeta,
): { lines: string[]; turnCount: number } {
  const lines: string[] = [];
  let i = 0;
  while (i < turns.length) {
    if (
      turns[i].role === 'user' &&
      i + 1 < turns.length &&
      turns[i + 1].role === 'assistant'
    ) {
      const entry: Record<string, unknown> = {
        instruction: turns[i].content,
        input: '',
        output: turns[i + 1].content,
      };
      const metaObj: Record<string, string> = {};
      if (meta.model) metaObj.model = meta.model;
      if (meta.platform) metaObj.platform = meta.platform;
      if (Object.keys(metaObj).length > 0) entry.metadata = metaObj;
      lines.push(JSON.stringify(entry));
      i += 2;
    } else {
      i += 1;
    }
  }
  return { lines, turnCount: lines.length };
}

function exportShareGPT(
  turns: Turn[],
): { line: string; turnCount: number } {
  const conversations: Array<{ from: string; value: string }> = [];
  for (const turn of turns) {
    conversations.push({
      from: turn.role === 'user' ? 'human' : 'gpt',
      value: turn.content,
    });
  }
  return { line: JSON.stringify({ conversations }), turnCount: turns.length };
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export type ExportFormat = 'openai' | 'alpaca' | 'sharegpt';

export function exportDocument(
  doc: PFMDocument,
  format: ExportFormat = 'openai',
): { lines: string[]; turnCount: number } {
  // Prefer chain section; fall back to content
  const chain = getSection(doc, 'chain');
  let turns: Turn[];

  if (chain) {
    turns = parseTurns(chain);
  } else {
    const content = getSection(doc, 'content') || '';
    if (content) {
      turns = [{ role: 'assistant', content }];
    } else {
      return { lines: [], turnCount: 0 };
    }
  }

  if (turns.length === 0) return { lines: [], turnCount: 0 };

  const meta = extractMetadata(doc);

  switch (format) {
    case 'openai': {
      const r = exportOpenAI(turns, meta);
      return { lines: [r.line], turnCount: r.turnCount };
    }
    case 'alpaca': {
      const r = exportAlpaca(turns, meta);
      return { lines: r.lines, turnCount: r.turnCount };
    }
    case 'sharegpt': {
      const r = exportShareGPT(turns);
      return { lines: [r.line], turnCount: r.turnCount };
    }
    default:
      throw new Error(`Unknown export format: ${format}. Use: openai, alpaca, sharegpt`);
  }
}

export function exportDocuments(
  docs: PFMDocument[],
  format: ExportFormat = 'openai',
): { lines: string[]; totalTurns: number } {
  const allLines: string[] = [];
  let totalTurns = 0;
  for (const doc of docs) {
    const { lines, turnCount } = exportDocument(doc, format);
    allLines.push(...lines);
    totalTurns += turnCount;
  }
  return { lines: allLines, totalTurns };
}

export function loadPfmPaths(pathArg: string): string[] {
  const stat = statSync(pathArg);
  if (stat.isFile()) {
    return [pathArg];
  } else if (stat.isDirectory()) {
    return readdirSync(pathArg)
      .filter((f) => extname(f).toLowerCase() === '.pfm')
      .sort()
      .map((f) => join(pathArg, f));
  } else {
    throw new Error(`Path not found: ${pathArg}`);
  }
}

export function loadAndExport(
  pathArg: string,
  format: ExportFormat = 'openai',
): { lines: string[]; totalTurns: number; fileCount: number } {
  const paths = loadPfmPaths(pathArg);
  const docs: PFMDocument[] = paths.map((p) => {
    const text = readFileSync(p, 'utf-8');
    return parse(text);
  });
  const { lines, totalTurns } = exportDocuments(docs, format);
  return { lines, totalTurns, fileCount: paths.length };
}
