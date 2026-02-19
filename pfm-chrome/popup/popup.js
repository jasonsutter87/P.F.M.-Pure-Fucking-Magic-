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

  // ===== Supported hosts =====
  const KNOWN_HOSTS = [
    'chat.openai.com', 'chatgpt.com',
    'claude.ai',
    'gemini.google.com',
    'grok.com', 'grok.x.ai',
    'openclaw.ai'
  ];

  /** Check if a URL is on a known supported host */
  function isKnownHost(url) {
    try {
      const hostname = new URL(url).hostname;
      return KNOWN_HOSTS.some(h => hostname === h || hostname.endsWith('.' + h));
    } catch (_) {
      return false;
    }
  }

  /** Check if URL is x.com/i/grok (special case: host match + path) */
  function isGrokOnX(url) {
    try {
      const u = new URL(url);
      return u.hostname === 'x.com' && u.pathname.startsWith('/i/grok');
    } catch (_) {
      return false;
    }
  }

  /**
   * Programmatically inject content scripts into the active tab.
   * Used when the tab's URL isn't in the manifest's content_scripts
   * matches (e.g., self-hosted Moltbot/OpenClaw instances).
   */
  async function injectContentScripts(tabId) {
    await chrome.scripting.executeScript({
      target: { tabId },
      files: [
        'shared/pfm-core.js',
        'content/scraper-chatgpt.js',
        'content/scraper-claude.js',
        'content/scraper-gemini.js',
        'content/scraper-grok.js',
        'content/scraper-moltbot.js',
        'content/content-main.js'
      ]
    });
    // Give the content script a moment to initialize
    await new Promise(r => setTimeout(r, 300));
  }

  /**
   * Try to send a capture message to the content script.
   * If it fails (content script not injected), inject and retry.
   */
  async function captureFromTab(tab) {
    try {
      const response = await chrome.tabs.sendMessage(tab.id, { action: 'capture_conversation' });
      return response;
    } catch (_) {
      // Content script not present — inject programmatically and retry
      await injectContentScripts(tab.id);
      return await chrome.tabs.sendMessage(tab.id, { action: 'capture_conversation' });
    }
  }

  // ===== Encryption toggle =====
  const chkEncrypt = $('chk-encrypt');
  const passwordRow = $('password-row');
  const encPassword = $('encrypt-password');
  const encConfirm = $('encrypt-confirm');

  chkEncrypt.addEventListener('change', () => {
    passwordRow.classList.toggle('hidden', !chkEncrypt.checked);
    if (!chkEncrypt.checked) {
      encPassword.value = '';
      encConfirm.value = '';
      encPassword.classList.remove('error');
      encConfirm.classList.remove('error');
    }
  });

  // ===== Capture =====
  $('btn-capture').addEventListener('click', async () => {
    const btn = $('btn-capture');
    const status = $('capture-status');
    status.textContent = '';
    status.className = 'status';

    // Validate encryption passwords before capture
    const wantEncrypt = chkEncrypt.checked;
    if (wantEncrypt) {
      const pw = encPassword.value;
      const pw2 = encConfirm.value;
      encPassword.classList.remove('error');
      encConfirm.classList.remove('error');

      if (!pw) {
        encPassword.classList.add('error');
        status.textContent = 'Enter an encryption password';
        status.className = 'status error';
        encPassword.focus();
        return;
      }
      if (pw.length < 8) {
        encPassword.classList.add('error');
        status.textContent = 'Password must be at least 8 characters';
        status.className = 'status error';
        encPassword.focus();
        return;
      }
      if (pw !== pw2) {
        encConfirm.classList.add('error');
        status.textContent = 'Passwords do not match';
        status.className = 'status error';
        encConfirm.focus();
        return;
      }
    }

    btn.disabled = true;
    btn.textContent = wantEncrypt ? 'Encrypting...' : 'Capturing...';

    try {
      // Get the active tab
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      if (!tab) throw new Error('No active tab');

      const url = tab.url || '';
      const supported = isKnownHost(url) || isGrokOnX(url);

      // For unknown hosts, we'll still try via programmatic injection
      // (handles self-hosted Moltbot/OpenClaw)
      if (!supported && !url.startsWith('https://') && !url.startsWith('http://')) {
        throw new Error('Navigate to an AI chat page first');
      }

      // Send message to content script (with fallback injection)
      const response = await captureFromTab(tab);

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

      // Sanitize URL and title to prevent format injection (matching content-main.js)
      const safeUrl = url.replace(/[\x00-\x1f]/g, '');
      const safeTitle = (result.title || '').replace(/[\x00-\x1f]/g, '').substring(0, 200);
      const meta = {
        agent: result.model || result.platform,
        model: result.model,
        source_platform: result.platform,
        source_url: safeUrl,
        title: safeTitle,
        tags: 'ai-conversation,' + result.platform
      };

      const pfmContent = await PFMSerializer.serialize(sections, meta);
      let filename = sanitizeFilename(result.title.substring(0, 60)) + '.pfm';

      if (wantEncrypt) {
        // Encrypt the PFM content before download
        const encrypted = await PFMCrypto.encrypt(pfmContent, encPassword.value);
        filename += '.enc';
        pfmDownload(encrypted, filename, 'application/octet-stream');
        status.textContent = 'Encrypted and saved ' + filename;
      } else {
        pfmDownload(pfmContent, filename, 'text/plain');
        status.textContent = 'Saved ' + filename;
      }

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
          // chrome.storage.session has a ~10MB quota; reject files that exceed it
          const MAX_SESSION_BYTES = 8 * 1024 * 1024; // 8MB safely under quota
          if (new TextEncoder().encode(text).length > MAX_SESSION_BYTES) {
            fileStatus.textContent = 'File too large for viewer tab (max 8 MB)';
            fileStatus.className = 'status error';
            return;
          }
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
