/**
 * PFM Preview Panel - Rich webview preview like Markdown preview.
 */

import * as vscode from 'vscode';
import { parsePFM, PFMDocument } from '../parser';

export class PFMPreviewPanel {
  public static readonly viewType = 'pfm.preview';
  private static panels = new Map<string, PFMPreviewPanel>();

  private static readonly DEBOUNCE_MS = 300;

  private readonly panel: vscode.WebviewPanel;
  private readonly uri: vscode.Uri;
  private disposables: vscode.Disposable[] = [];
  private debounceTimer: ReturnType<typeof setTimeout> | undefined;

  private constructor(panel: vscode.WebviewPanel, uri: vscode.Uri) {
    this.panel = panel;
    this.uri = uri;

    this.panel.onDidDispose(() => this.dispose(), null, this.disposables);

    // Update on document changes (debounced to avoid excessive re-renders)
    const watcher = vscode.workspace.onDidChangeTextDocument((e) => {
      if (e.document.uri.toString() === uri.toString()) {
        if (this.debounceTimer) {
          clearTimeout(this.debounceTimer);
        }
        this.debounceTimer = setTimeout(() => {
          this.update(e.document.getText());
        }, PFMPreviewPanel.DEBOUNCE_MS);
      }
    });
    this.disposables.push(watcher);
  }

  public static show(uri: vscode.Uri, text: string): void {
    const key = uri.toString();
    const existing = PFMPreviewPanel.panels.get(key);
    if (existing) {
      existing.panel.reveal(vscode.ViewColumn.Beside);
      existing.update(text);
      return;
    }

    const panel = vscode.window.createWebviewPanel(
      PFMPreviewPanel.viewType,
      `Preview: ${uri.path.split('/').pop()}`,
      vscode.ViewColumn.Beside,
      {
        enableScripts: true,
        retainContextWhenHidden: true,
        // Security: restrict webview to no local resources and no remote resources
        localResourceRoots: [],
      }
    );

    const instance = new PFMPreviewPanel(panel, uri);
    PFMPreviewPanel.panels.set(key, instance);
    instance.update(text);
  }

  private update(text: string): void {
    const doc = parsePFM(text);
    this.panel.webview.html = this.getHtml(doc);
  }

  private dispose(): void {
    if (this.debounceTimer) {
      clearTimeout(this.debounceTimer);
    }
    PFMPreviewPanel.panels.delete(this.uri.toString());
    this.panel.dispose();
    for (const d of this.disposables) {
      d.dispose();
    }
    this.disposables = [];
  }

  private getHtml(doc: PFMDocument): string {
    const meta = doc.meta;
    const sections = doc.sections;
    const checksumStatus = meta.checksum ? 'present' : 'missing';

    let metaHtml = '';
    for (const [key, val] of Object.entries(meta)) {
      const display = val.length > 40 ? val.substring(0, 37) + '...' : val;
      metaHtml += `<div class="meta-row"><span class="meta-key">${esc(key)}</span>: <span class="meta-val">${esc(display)}</span></div>`;
    }

    let sectionsHtml = '';
    for (const section of sections) {
      sectionsHtml += `
        <div class="section">
          <div class="section-header">
            <span class="toggle-icon">&#9660;</span>
            <span class="section-name">${esc(section.name)}</span>
            <span class="section-size">${section.content.length} chars</span>
          </div>
          <pre class="section-content">${esc(section.content)}</pre>
        </div>`;
    }

    // Generate a nonce for CSP
    const nonce = getNonce();

    return `<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'nonce-${nonce}'; script-src 'nonce-${nonce}';">
<style nonce="${nonce}">
  body {
    font-family: var(--vscode-font-family);
    color: var(--vscode-foreground);
    background: var(--vscode-editor-background);
    padding: 16px;
    line-height: 1.5;
  }
  h1 { font-size: 18px; color: var(--vscode-textLink-foreground); margin-bottom: 12px; }
  h2 { font-size: 14px; color: var(--vscode-descriptionForeground); margin-bottom: 8px; }
  .meta-section {
    background: var(--vscode-editor-inactiveSelectionBackground);
    padding: 12px;
    border-radius: 4px;
    margin-bottom: 16px;
  }
  .meta-row { margin: 2px 0; font-size: 13px; }
  .meta-key { color: var(--vscode-symbolIcon-variableForeground, #9cdcfe); }
  .meta-val { color: var(--vscode-foreground); }
  .section {
    border: 1px solid var(--vscode-panel-border);
    border-radius: 4px;
    margin-bottom: 8px;
    overflow: hidden;
  }
  .section-header {
    padding: 8px 12px;
    background: var(--vscode-editor-inactiveSelectionBackground);
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 8px;
    user-select: none;
  }
  .section-header:hover { background: var(--vscode-list-hoverBackground); }
  .toggle-icon { font-size: 10px; transition: transform 0.2s; }
  .collapsed .toggle-icon { transform: rotate(-90deg); }
  .collapsed .section-content { display: none; }
  .section-name { font-weight: bold; color: var(--vscode-textLink-foreground); }
  .section-size { margin-left: auto; font-size: 11px; color: var(--vscode-descriptionForeground); }
  .section-content {
    padding: 12px;
    margin: 0;
    font-family: var(--vscode-editor-font-family);
    font-size: var(--vscode-editor-font-size, 13px);
    white-space: pre-wrap;
    word-wrap: break-word;
    overflow-x: auto;
  }
</style>
</head>
<body>
  <h1>PFM v${esc(doc.formatVersion)} ${doc.isStream ? '<span style="color:var(--vscode-charts-orange)">[STREAM]</span>' : ''}</h1>
  <div class="meta-section">
    <h2>Metadata</h2>
    ${metaHtml}
  </div>
  <h2>Sections (${sections.length})</h2>
  ${sectionsHtml}
  <script nonce="${nonce}">
    document.querySelectorAll('.section-header').forEach(function(header) {
      header.addEventListener('click', function() {
        this.parentElement.classList.toggle('collapsed');
      });
    });
  </script>
</body>
</html>`;
  }
}

function esc(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/** Generate a random nonce for Content-Security-Policy. */
function getNonce(): string {
  const crypto = require('crypto');
  return crypto.randomBytes(16).toString('base64');
}
