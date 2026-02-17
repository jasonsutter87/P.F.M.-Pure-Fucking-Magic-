/* ================================================================
   PFM Viewer — adapted from docs/index.html for Chrome extension
   Reads from chrome.storage.session or local file drop.
   ================================================================ */
(function() {
  'use strict';

  /* ================================================================
     Application State
     ================================================================ */
  let state = {
    doc: null,
    filename: '',
    activeIndex: -1,
    filteredSections: [],
    wordWrap: true,
    checksumValid: false
  };

  /* ================================================================
     DOM Refs
     ================================================================ */
  const $ = id => document.getElementById(id);
  const landing   = $('landing');
  const viewer    = $('viewer');
  const dropZone  = $('drop-zone');
  const fileInput = $('file-input');

  const MAX_FILE_SIZE = 50 * 1024 * 1024;

  /* ================================================================
     File Loading
     ================================================================ */
  function handleFile(file) {
    if (!file) return;
    if (file.size > MAX_FILE_SIZE) {
      alert('File too large. Maximum size is 50 MB.');
      return;
    }
    if (!file.name.toLowerCase().endsWith('.pfm')) {
      alert('Please select a .pfm file.');
      return;
    }
    const reader = new FileReader();
    reader.onerror = function() { alert('Error reading file.'); };
    reader.onload = e => loadPFM(e.target.result, file.name);
    reader.readAsText(file, 'utf-8');
  }

  function loadPFM(text, filename) {
    const doc = PFMParser.parse(text);
    state.doc = doc;
    state.filename = filename || 'untitled.pfm';
    state.filteredSections = [...doc.sections];
    state.activeIndex = doc.sections.length > 0 ? 0 : -1;

    PFMParser.checksum(doc.sections).then(computed => {
      state.checksumValid = (computed === (doc.meta.checksum || ''));
      renderChecksumBadge();
    });

    showViewer();
    render();
  }

  /* ================================================================
     Screen Switching
     ================================================================ */
  function showViewer() {
    landing.classList.add('hidden');
    viewer.classList.add('active');
  }

  function showLanding() {
    viewer.classList.remove('active');
    landing.classList.remove('hidden');
  }

  /* ================================================================
     Rendering
     ================================================================ */
  function render() {
    renderFilename();
    renderMeta();
    renderSectionList();
    renderContent();
    renderChecksumBadge();
  }

  function renderFilename() {
    $('v-filename').textContent = state.filename;
  }

  function renderChecksumBadge() {
    const badge = $('v-checksum-badge');
    if (state.checksumValid) {
      badge.textContent = 'VALID';
      badge.className = 'badge valid';
    } else {
      badge.textContent = 'INVALID';
      badge.className = 'badge invalid';
    }
  }

  function renderMeta() {
    const meta = state.doc.meta;
    const keys = Object.keys(meta);
    $('meta-count').textContent = keys.length + ' fields';

    const container = document.createElement('div');
    container.className = 'meta-grid';
    for (const key of keys) {
      if (key === '__proto__' || key === 'constructor' || key === 'prototype') continue;
      if (!Object.prototype.hasOwnProperty.call(meta, key)) continue;

      const val = meta[key];
      const display = (key === 'checksum' && val.length > 20) ? val.substring(0, 16) + '...' : val;

      const row = document.createElement('div');
      row.className = 'meta-row';

      const keyDiv = document.createElement('div');
      keyDiv.className = 'meta-key';
      keyDiv.textContent = key;

      const valDiv = document.createElement('div');
      valDiv.className = 'meta-val';
      valDiv.textContent = display;
      valDiv.title = val;

      row.appendChild(keyDiv);
      row.appendChild(valDiv);
      container.appendChild(row);
    }
    const metaEl = $('v-meta');
    metaEl.innerHTML = '';
    metaEl.appendChild(container);
  }

  function renderSectionList() {
    const el = $('v-section-list');
    let html = '';
    for (let i = 0; i < state.filteredSections.length; i++) {
      const s = state.filteredSections[i];
      const bytes = new TextEncoder().encode(s.content).length;
      const sizeStr = bytes >= 1024 ? (bytes / 1024).toFixed(1) + ' KB' : bytes + ' B';
      const cls = i === state.activeIndex ? ' active' : '';
      html += '<div class="section-item' + cls + '" data-idx="' + i + '">' +
              '<span class="section-item-name">' + esc(s.name) + '</span>' +
              '<span class="section-item-size">' + sizeStr + '</span></div>';
    }
    el.innerHTML = html;

    el.querySelectorAll('.section-item').forEach(item => {
      item.addEventListener('click', () => {
        selectSection(parseInt(item.dataset.idx, 10));
      });
    });
  }

  function renderContent() {
    const body = $('v-content-body');
    if (state.activeIndex < 0 || state.activeIndex >= state.filteredSections.length) {
      body.innerHTML = '<div class="content-empty">Select a section from the sidebar</div>';
      $('v-content-title').textContent = 'Select a section';
      $('v-content-meta').textContent = '';
      return;
    }

    const s = state.filteredSections[state.activeIndex];
    $('v-content-title').textContent = s.name;

    const bytes = new TextEncoder().encode(s.content).length;
    const lines = s.content.split('\n').length;
    $('v-content-meta').textContent = lines + ' lines \u00b7 ' + formatBytes(bytes);

    const contentLines = s.content.split('\n');
    const nums = contentLines.map((_, i) => i + 1).join('\n');
    const wrapClass = state.wordWrap ? ' wrap' : '';

    body.innerHTML = '<div class="code-container"><pre class="line-numbers">' + nums +
                     '</pre><pre class="content-pre' + wrapClass + '">' + esc(s.content) + '</pre></div>';
  }

  function selectSection(idx) {
    if (idx < 0 || idx >= state.filteredSections.length) return;
    state.activeIndex = idx;
    renderSectionList();
    renderContent();
  }

  function moveSection(delta) {
    const next = state.activeIndex + delta;
    if (next >= 0 && next < state.filteredSections.length) {
      selectSection(next);
      const active = document.querySelector('.section-item.active');
      if (active) active.scrollIntoView({ block: 'nearest' });
    }
  }

  /* ================================================================
     Search / Filter
     ================================================================ */
  $('v-search').addEventListener('input', function() {
    const q = this.value.toLowerCase().trim();
    if (!q) {
      state.filteredSections = [...state.doc.sections];
    } else {
      state.filteredSections = state.doc.sections.filter(s =>
        s.name.toLowerCase().includes(q) || s.content.toLowerCase().includes(q)
      );
    }
    state.activeIndex = state.filteredSections.length > 0 ? 0 : -1;
    renderSectionList();
    renderContent();
  });

  /* ================================================================
     Export
     ================================================================ */
  function exportJSON() {
    if (!state.doc) return;
    const data = {
      pfm_version: state.doc.formatVersion,
      meta: state.doc.meta,
      sections: state.doc.sections.map(s => ({ name: s.name, content: s.content }))
    };
    pfmDownload(JSON.stringify(data, null, 2), state.filename.replace('.pfm', '.json'), 'application/json');
  }

  function exportMarkdown() {
    if (!state.doc) return;
    let md = '---\n';
    for (const [k, v] of Object.entries(state.doc.meta)) md += k + ': ' + v + '\n';
    md += '---\n\n';
    for (const s of state.doc.sections) md += '## ' + s.name + '\n\n' + s.content + '\n\n';
    pfmDownload(md, state.filename.replace('.pfm', '.md'), 'text/markdown');
  }

  function exportCSV() {
    if (!state.doc) return;
    let csv = 'section_name,content\n';
    for (const s of state.doc.sections) {
      csv += '"' + s.name.replace(/"/g, '""') + '","' + s.content.replace(/"/g, '""') + '"\n';
    }
    pfmDownload(csv, state.filename.replace('.pfm', '.csv'), 'text/csv');
  }

  function exportTXT() {
    if (!state.doc) return;
    let txt = '';
    for (const s of state.doc.sections) {
      txt += '=== ' + s.name + ' ===\n\n' + s.content + '\n\n';
    }
    pfmDownload(txt.trim(), state.filename.replace('.pfm', '.txt'), 'text/plain');
  }

  /* ================================================================
     Theme
     ================================================================ */
  function toggleTheme() {
    document.body.classList.toggle('light');
    // Use chrome.storage.local for persistence
    chrome.storage.local.set({
      'pfm-theme': document.body.classList.contains('light') ? 'light' : 'dark'
    });
  }

  // Restore theme preference
  chrome.storage.local.get('pfm-theme', (result) => {
    if (result['pfm-theme'] === 'light') {
      document.body.classList.add('light');
    }
  });

  /* ================================================================
     Word Wrap
     ================================================================ */
  function toggleWrap() {
    state.wordWrap = !state.wordWrap;
    $('btn-wrap').classList.toggle('active', state.wordWrap);
    const pre = document.querySelector('.content-pre');
    if (pre) pre.classList.toggle('wrap', state.wordWrap);
  }

  /* ================================================================
     Shortcuts Modal
     ================================================================ */
  function openShortcuts() {
    $('shortcuts-modal').style.display = 'flex';
  }
  function closeShortcuts() {
    $('shortcuts-modal').style.display = 'none';
  }

  /* ================================================================
     Meta Section Toggle
     ================================================================ */
  let metaOpen = true;
  $('meta-toggle').addEventListener('click', () => {
    metaOpen = !metaOpen;
    $('v-meta').style.display = metaOpen ? '' : 'none';
  });

  /* ================================================================
     Event Listeners
     ================================================================ */
  // Drag & drop on landing
  ['dragenter', 'dragover'].forEach(evt => {
    dropZone.addEventListener(evt, e => { e.preventDefault(); dropZone.classList.add('dragover'); });
  });
  ['dragleave', 'drop'].forEach(evt => {
    dropZone.addEventListener(evt, e => { e.preventDefault(); dropZone.classList.remove('dragover'); });
  });
  dropZone.addEventListener('drop', e => {
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  });

  fileInput.addEventListener('change', e => handleFile(e.target.files[0]));

  // Topbar buttons
  $('btn-export-json').addEventListener('click', exportJSON);
  $('btn-export-md').addEventListener('click', exportMarkdown);
  $('btn-export-csv').addEventListener('click', exportCSV);
  $('btn-export-txt').addEventListener('click', exportTXT);
  $('btn-theme').addEventListener('click', toggleTheme);
  $('btn-wrap').addEventListener('click', toggleWrap);
  $('btn-shortcuts').addEventListener('click', openShortcuts);
  $('btn-close-shortcuts').addEventListener('click', closeShortcuts);
  $('btn-open-new').addEventListener('click', () => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.pfm';
    input.onchange = e => handleFile(e.target.files[0]);
    input.click();
  });

  // Keyboard shortcuts
  document.addEventListener('keydown', e => {
    const target = e.target;
    const isInput = target.tagName === 'INPUT' || target.tagName === 'TEXTAREA';

    if (e.key === 'Escape') {
      closeShortcuts();
      if (isInput) {
        target.blur();
        if (target.id === 'v-search') {
          target.value = '';
          target.dispatchEvent(new Event('input'));
        }
      }
      return;
    }

    if (isInput) return;
    if (!viewer.classList.contains('active')) return;

    switch (e.key) {
      case 'j':
      case 'ArrowDown':
        e.preventDefault();
        moveSection(1);
        break;
      case 'k':
      case 'ArrowUp':
        e.preventDefault();
        moveSection(-1);
        break;
      case '/':
        e.preventDefault();
        $('v-search').focus();
        break;
      case 'w':
        toggleWrap();
        break;
      case 't':
        toggleTheme();
        break;
      case 'o':
        $('btn-open-new').click();
        break;
      case '?':
        openShortcuts();
        break;
    }
  });

  // Drag onto viewer
  viewer.addEventListener('dragover', e => e.preventDefault());
  viewer.addEventListener('drop', e => {
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  });

  /* ================================================================
     Load from chrome.storage.session (popup handoff)
     ================================================================ */
  chrome.storage.session.get(['pfm_pending', 'pfm_filename'], (result) => {
    if (result.pfm_pending) {
      const text = result.pfm_pending;
      const filename = result.pfm_filename || 'untitled.pfm';
      // Clear the pending data
      chrome.storage.session.remove(['pfm_pending', 'pfm_filename']);
      loadPFM(text, filename);
    }
  });
})();
