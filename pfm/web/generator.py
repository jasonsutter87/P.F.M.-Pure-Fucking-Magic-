"""PFM Web Generator - Produces self-contained HTML viewers for .pfm files.

Zero dependencies. The generated HTML embeds all data, CSS, and JS inline.
"""

from __future__ import annotations

import json
from pathlib import Path

from pfm.reader import PFMReader


def generate_html(pfm_path: str | Path) -> str:
    """Generate a self-contained HTML viewer for a .pfm file.

    The output is a single HTML file with embedded CSS/JS and the PFM
    data serialized as JSON inside a <script> tag.
    """
    pfm_path = Path(pfm_path)

    with PFMReader.open(pfm_path) as reader:
        meta = dict(reader.meta)
        section_names = list(reader.section_names)
        sections = []
        for name in section_names:
            content = reader.get_section(name) or ""
            sections.append({"name": name, "content": content})
        checksum_valid = reader.validate_checksum()
        format_version = reader.format_version

    pfm_data = {
        "filename": pfm_path.name,
        "format_version": format_version,
        "meta": meta,
        "sections": sections,
        "checksum_valid": checksum_valid,
    }

    # JSON-encode with ensure_ascii=True for safe embedding.
    # Then escape sequences that could break out of <script> context:
    #   - "</script>" -> "<\/script>" prevents premature script tag closure
    #   - "<!--" -> "<\!--" prevents HTML comment injection
    data_json = json.dumps(pfm_data, ensure_ascii=True)
    data_json = data_json.replace("</", "<\\/")
    data_json = data_json.replace("<!--", "<\\!--")

    return _HTML_TEMPLATE.replace("__PFM_DATA_PLACEHOLDER__", data_json)


def write_html(pfm_path: str | Path, output_path: str | Path) -> int:
    """Generate HTML and write to file. Returns bytes written.

    Security: Rejects output paths containing '..' to prevent path traversal.
    """
    output_path = Path(output_path)
    # Reject path traversal attempts
    if ".." in output_path.parts:
        raise ValueError("Output path must not contain '..' (path traversal)")
    content = generate_html(pfm_path)
    output_path.write_text(content, encoding="utf-8")
    return len(content.encode("utf-8"))


# ---------------------------------------------------------------------------
# HTML Template (self-contained)
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:;">
<title>PFM Viewer</title>
<style>
:root {
  --bg: #1e1e1e;
  --bg-sidebar: #252526;
  --bg-card: #2d2d2d;
  --bg-hover: #3e3e3e;
  --text: #d4d4d4;
  --text-muted: #808080;
  --accent: #569cd6;
  --accent-dim: #264f78;
  --green: #4ec9b0;
  --red: #f44747;
  --orange: #ce9178;
  --border: #404040;
  --font: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, monospace;
  --mono: 'Cascadia Code', 'Fira Code', 'JetBrains Mono', Consolas, monospace;
}
.light {
  --bg: #ffffff;
  --bg-sidebar: #f3f3f3;
  --bg-card: #ffffff;
  --bg-hover: #e8e8e8;
  --text: #1e1e1e;
  --text-muted: #6a6a6a;
  --accent: #0066b8;
  --accent-dim: #cce0f5;
  --green: #16825d;
  --red: #cd3131;
  --orange: #a31515;
  --border: #d4d4d4;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: var(--font);
  font-size: 14px;
  display: flex;
  height: 100vh;
  overflow: hidden;
}
/* Sidebar */
.sidebar {
  width: 280px;
  min-width: 280px;
  background: var(--bg-sidebar);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.sidebar-header {
  padding: 16px;
  border-bottom: 1px solid var(--border);
}
.sidebar-header h1 {
  font-size: 16px;
  color: var(--accent);
  margin-bottom: 4px;
}
.sidebar-header .version {
  font-size: 12px;
  color: var(--text-muted);
}
.sidebar-header .checksum {
  margin-top: 8px;
  font-size: 12px;
  font-weight: bold;
  padding: 4px 8px;
  border-radius: 4px;
}
.checksum.valid { color: var(--green); background: rgba(78,201,176,0.1); }
.checksum.invalid { color: var(--red); background: rgba(244,71,71,0.1); }
/* Meta section */
.meta-section {
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
  overflow-y: auto;
  max-height: 40%;
}
.meta-row {
  margin-bottom: 6px;
}
.meta-key {
  font-size: 11px;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.meta-val {
  font-size: 13px;
  color: var(--text);
  word-break: break-all;
}
/* Search */
.search-box {
  padding: 8px 16px;
  border-bottom: 1px solid var(--border);
}
.search-box input {
  width: 100%;
  padding: 6px 10px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--text);
  font-size: 13px;
  outline: none;
}
.search-box input:focus {
  border-color: var(--accent);
}
/* Section list */
.section-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px 0;
}
.section-item {
  padding: 8px 16px;
  cursor: pointer;
  border-left: 3px solid transparent;
  transition: all 0.1s;
}
.section-item:hover {
  background: var(--bg-hover);
}
.section-item.active {
  background: var(--accent-dim);
  border-left-color: var(--accent);
  color: var(--accent);
}
.section-item .section-name {
  font-size: 13px;
  font-weight: 500;
}
.section-item .section-size {
  font-size: 11px;
  color: var(--text-muted);
}
/* Toolbar */
.toolbar {
  padding: 8px 16px;
  border-top: 1px solid var(--border);
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.toolbar button {
  padding: 4px 10px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--text);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.1s;
}
.toolbar button:hover {
  background: var(--bg-hover);
  border-color: var(--accent);
}
/* Main content */
.main {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.content-header {
  padding: 12px 20px;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.content-header h2 {
  font-size: 15px;
  color: var(--accent);
}
.content-body {
  flex: 1;
  overflow: auto;
  padding: 20px;
}
.content-body pre {
  font-family: var(--mono);
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-wrap: break-word;
  color: var(--text);
}
/* Collapsible */
.collapsible-toggle {
  cursor: pointer;
  user-select: none;
  padding: 4px 0;
  color: var(--text-muted);
  font-size: 12px;
}
.collapsible-toggle:hover { color: var(--accent); }
</style>
</head>
<body>
<div class="sidebar">
  <div class="sidebar-header">
    <h1 id="filename"></h1>
    <div class="version" id="version"></div>
    <div class="checksum" id="checksum"></div>
  </div>
  <div class="meta-section" id="meta"></div>
  <div class="search-box">
    <input type="text" id="search" placeholder="Filter sections..." />
  </div>
  <div class="section-list" id="section-list"></div>
  <div class="toolbar">
    <button onclick="exportJSON()">Export JSON</button>
    <button onclick="exportMarkdown()">Export Markdown</button>
    <button onclick="toggleTheme()">Toggle Theme</button>
  </div>
</div>
<div class="main">
  <div class="content-header">
    <h2 id="content-title">Select a section</h2>
  </div>
  <div class="content-body">
    <pre id="content-pre"></pre>
  </div>
</div>

<script>
const PFM = __PFM_DATA_PLACEHOLDER__;

// --- Render ---
function init() {
  document.getElementById('filename').textContent = PFM.filename;
  document.getElementById('version').textContent = 'PFM v' + PFM.format_version;

  const cs = document.getElementById('checksum');
  cs.textContent = PFM.checksum_valid ? 'Checksum: VALID' : 'Checksum: INVALID';
  cs.className = 'checksum ' + (PFM.checksum_valid ? 'valid' : 'invalid');

  renderMeta();
  renderSections(PFM.sections);

  // Auto-select first section
  if (PFM.sections.length > 0) selectSection(0);

  // Search
  document.getElementById('search').addEventListener('input', function() {
    const q = this.value.toLowerCase();
    const filtered = PFM.sections.filter(function(s) {
      return s.name.toLowerCase().indexOf(q) !== -1 ||
             s.content.toLowerCase().indexOf(q) !== -1;
    });
    renderSections(filtered);
  });

  // Keyboard shortcuts
  document.addEventListener('keydown', function(e) {
    if (e.target.tagName === 'INPUT') return;
    if (e.key === '/') { e.preventDefault(); document.getElementById('search').focus(); }
    if (e.key === 'j') moveSelection(1);
    if (e.key === 'k') moveSelection(-1);
  });
}

function renderMeta() {
  const el = document.getElementById('meta');
  let html = '';
  const meta = PFM.meta;
  for (const key in meta) {
    if (!Object.prototype.hasOwnProperty.call(meta, key)) continue;
    const val = meta[key];
    const display = val.length > 36 ? val.substring(0, 33) + '...' : val;
    html += '<div class="meta-row"><div class="meta-key">' + esc(key) +
            '</div><div class="meta-val">' + esc(display) + '</div></div>';
  }
  el.innerHTML = html;
}

let currentSections = PFM.sections;
let activeIndex = -1;

function renderSections(sections) {
  currentSections = sections;
  const el = document.getElementById('section-list');
  let html = '';
  for (let i = 0; i < sections.length; i++) {
    const s = sections[i];
    const bytes = new TextEncoder().encode(s.content).length;
    const sizeStr = bytes > 1024 ? (bytes / 1024).toFixed(1) + ' KB' : bytes + ' B';
    const cls = i === activeIndex ? ' active' : '';
    html += '<div class="section-item' + cls + '" onclick="selectSection(' + i + ')">' +
            '<div class="section-name">' + esc(s.name) + '</div>' +
            '<div class="section-size">' + sizeStr + '</div></div>';
  }
  el.innerHTML = html;
}

function selectSection(idx) {
  if (idx < 0 || idx >= currentSections.length) return;
  activeIndex = idx;
  const s = currentSections[idx];
  document.getElementById('content-title').textContent = s.name;
  document.getElementById('content-pre').textContent = s.content;
  // Update active class
  const items = document.querySelectorAll('.section-item');
  items.forEach(function(el, i) {
    el.className = 'section-item' + (i === idx ? ' active' : '');
  });
}

function moveSelection(delta) {
  const next = activeIndex + delta;
  if (next >= 0 && next < currentSections.length) selectSection(next);
}

// --- Export ---
function exportJSON() {
  const data = {
    pfm_version: PFM.format_version,
    meta: PFM.meta,
    sections: PFM.sections
  };
  download(JSON.stringify(data, null, 2), PFM.filename.replace('.pfm', '.json'), 'application/json');
}

function exportMarkdown() {
  let md = '---\n';
  for (const k in PFM.meta) {
    if (!Object.prototype.hasOwnProperty.call(PFM.meta, k)) continue;
    md += k + ': ' + PFM.meta[k] + '\n';
  }
  md += '---\n\n';
  PFM.sections.forEach(function(s) {
    md += '## ' + s.name + '\n\n' + s.content + '\n\n';
  });
  download(md, PFM.filename.replace('.pfm', '.md'), 'text/markdown');
}

function sanitizeFilename(name) {
  return name.replace(/[\/\\:*?"<>|]/g, '_').replace(/\.\./g, '_');
}

function download(content, filename, mime) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = sanitizeFilename(filename);
  document.body.appendChild(a); a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// --- Theme ---
function toggleTheme() {
  document.body.classList.toggle('light');
}

// --- Utils ---
function esc(s) {
  const div = document.createElement('div');
  div.textContent = s;
  return div.innerHTML;
}

init();
</script>
</body>
</html>"""
