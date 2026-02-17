/* ================================================================
   PFM Popup — Capture, View, and Convert
   ================================================================ */
(function() {
  'use strict';

  const $ = id => document.getElementById(id);

  // ===== Tab switching =====
  document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
      tab.classList.add('active');
      $('panel-' + tab.dataset.tab).classList.add('active');
    });
  });

  // ===== Capture =====
  $('btn-capture').addEventListener('click', async () => {
    const btn = $('btn-capture');
    const status = $('capture-status');
    status.textContent = '';
    status.className = 'status';
    btn.disabled = true;
    btn.textContent = 'Capturing...';

    try {
      // Get the active tab
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      if (!tab) throw new Error('No active tab');

      // Check if we're on a supported site
      const url = tab.url || '';
      const supported = [
        'chat.openai.com', 'chatgpt.com',
        'claude.ai',
        'gemini.google.com'
      ];
      const isSupported = supported.some(host => url.includes(host));

      if (!isSupported) {
        throw new Error('Navigate to ChatGPT, Claude, or Gemini first');
      }

      // Send message to content script
      const response = await chrome.tabs.sendMessage(tab.id, { action: 'capture_conversation' });

      if (response.error) {
        throw new Error(response.error);
      }

      const result = response.data;

      // Build PFM
      const sections = [];
      const chain = result.messages
        .map(m => `${m.role === 'user' ? 'User' : 'Assistant'}: ${m.content}`)
        .join('\n\n');
      sections.push({ name: 'chain', content: chain });

      if (result.messages.length > 2) {
        const userCount = result.messages.filter(m => m.role === 'user').length;
        const assistantCount = result.messages.filter(m => m.role === 'assistant').length;
        const summary = `Conversation with ${result.messages.length} messages (${userCount} user, ${assistantCount} assistant)\nPlatform: ${result.platform}\nModel: ${result.model}`;
        sections.push({ name: 'summary', content: summary });
      }

      const meta = {
        agent: result.model || result.platform,
        model: result.model,
        source_platform: result.platform,
        source_url: url,
        title: result.title,
        tags: 'ai-conversation,' + result.platform
      };

      const pfmContent = await PFMSerializer.serialize(sections, meta);
      const filename = sanitizeFilename(result.title.substring(0, 60)) + '.pfm';
      pfmDownload(pfmContent, filename, 'text/plain');

      status.textContent = 'Saved ' + filename;
      status.className = 'status success';
    } catch (err) {
      status.textContent = err.message;
      status.className = 'status error';
    }

    btn.disabled = false;
    btn.textContent = 'Save Conversation as .pfm';
  });

  // ===== Drop zone =====
  const dropZone = $('drop-zone');
  const fileInput = $('file-input');
  const fileStatus = $('file-status');

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

  fileInput.addEventListener('change', e => {
    const file = e.target.files[0];
    if (file) handleFile(file);
  });

  async function handleFile(file) {
    fileStatus.textContent = '';
    fileStatus.className = 'status';

    const MAX_FILE_SIZE = 50 * 1024 * 1024;
    if (file.size > MAX_FILE_SIZE) {
      fileStatus.textContent = 'File too large (max 50 MB)';
      fileStatus.className = 'status error';
      return;
    }

    const ext = file.name.split('.').pop().toLowerCase();
    const reader = new FileReader();

    reader.onerror = () => {
      fileStatus.textContent = 'Error reading file';
      fileStatus.className = 'status error';
    };

    reader.onload = async (e) => {
      const text = e.target.result;

      if (ext === 'pfm') {
        // View .pfm — hand off to viewer tab
        try {
          await chrome.storage.session.set({ pfm_pending: text, pfm_filename: file.name });
          chrome.runtime.sendMessage({ action: 'open_viewer' });
          fileStatus.textContent = 'Opening viewer...';
          fileStatus.className = 'status success';
        } catch (err) {
          fileStatus.textContent = 'Error: ' + err.message;
          fileStatus.className = 'status error';
        }
      } else {
        // Convert to .pfm
        try {
          const format = Converters.detectFormat(file.name);
          let result;
          switch (format) {
            case 'json':     result = Converters.fromJSON(text, file.name); break;
            case 'csv':      result = Converters.fromCSV(text, file.name); break;
            case 'markdown': result = Converters.fromMarkdown(text, file.name); break;
            default:         result = Converters.fromTXT(text, file.name); break;
          }

          const pfmContent = await PFMSerializer.serialize(result.sections, result.meta);
          const filename = file.name.replace(/\.[^.]+$/, '.pfm');
          pfmDownload(pfmContent, filename, 'text/plain');

          fileStatus.textContent = 'Converted and saved ' + filename;
          fileStatus.className = 'status success';
        } catch (err) {
          fileStatus.textContent = 'Conversion error: ' + err.message;
          fileStatus.className = 'status error';
        }
      }
    };

    reader.readAsText(file, 'utf-8');
  }
})();
