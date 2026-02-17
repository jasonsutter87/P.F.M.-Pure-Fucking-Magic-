/* ================================================================
   Content Script Orchestrator
   Detects platform, injects floating "Save as .pfm" button,
   scrapes conversation on click, serializes, and downloads.
   ================================================================ */
(function() {
  'use strict';

  // Guard against double-injection
  if (window.__pfmContentInjected) return;
  window.__pfmContentInjected = true;

  const BUTTON_ID = 'pfm-save-btn';
  const Z_INDEX = 2147483647;

  /** Detect which scraper to use */
  function getScraper() {
    if (typeof ScraperChatGPT !== 'undefined' && ScraperChatGPT.detect()) return ScraperChatGPT;
    if (typeof ScraperClaude !== 'undefined' && ScraperClaude.detect()) return ScraperClaude;
    if (typeof ScraperGemini !== 'undefined' && ScraperGemini.detect()) return ScraperGemini;
    return null;
  }

  /** Create the floating save button */
  function createButton() {
    if (document.getElementById(BUTTON_ID)) return;

    const btn = document.createElement('button');
    btn.id = BUTTON_ID;
    btn.textContent = 'Save as .pfm';
    btn.title = 'Capture this AI conversation as a .pfm file';

    Object.assign(btn.style, {
      position: 'fixed',
      bottom: '20px',
      right: '20px',
      zIndex: Z_INDEX,
      padding: '10px 18px',
      background: 'linear-gradient(135deg, #58a6ff, #bc8cff)',
      color: '#fff',
      border: 'none',
      borderRadius: '8px',
      fontSize: '14px',
      fontWeight: '600',
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif',
      cursor: 'pointer',
      boxShadow: '0 4px 16px rgba(88, 166, 255, 0.3)',
      transition: 'transform 150ms ease, box-shadow 150ms ease',
      opacity: '0',
      transform: 'translateY(10px)'
    });

    btn.addEventListener('mouseenter', () => {
      btn.style.transform = 'translateY(-2px)';
      btn.style.boxShadow = '0 6px 20px rgba(88, 166, 255, 0.4)';
    });
    btn.addEventListener('mouseleave', () => {
      btn.style.transform = 'translateY(0)';
      btn.style.boxShadow = '0 4px 16px rgba(88, 166, 255, 0.3)';
    });

    btn.addEventListener('click', handleCapture);

    document.body.appendChild(btn);

    // Animate in
    requestAnimationFrame(() => {
      btn.style.opacity = '1';
      btn.style.transform = 'translateY(0)';
    });
  }

  /** Remove the button (e.g., when navigating away from conversation) */
  function removeButton() {
    const existing = document.getElementById(BUTTON_ID);
    if (existing) existing.remove();
  }

  /** Handle the capture click */
  async function handleCapture() {
    const btn = document.getElementById(BUTTON_ID);
    const scraper = getScraper();
    if (!scraper) {
      showStatus(btn, 'Platform not detected', true);
      return;
    }

    // Visual feedback
    const origText = btn.textContent;
    btn.textContent = 'Capturing...';
    btn.style.pointerEvents = 'none';

    try {
      const result = scraper.scrape();
      if (!result || result.messages.length === 0) {
        showStatus(btn, 'No conversation found', true);
        return;
      }

      // Build PFM sections from conversation
      const sections = [];
      const chain = result.messages
        .map(m => `${m.role === 'user' ? 'User' : 'Assistant'}: ${m.content}`)
        .join('\n\n');

      sections.push({ name: 'chain', content: chain });

      // Add individual messages as sections if many
      if (result.messages.length > 2) {
        // Summary section
        const userCount = result.messages.filter(m => m.role === 'user').length;
        const assistantCount = result.messages.filter(m => m.role === 'assistant').length;
        const summary = `Conversation with ${result.messages.length} messages (${userCount} user, ${assistantCount} assistant)\nPlatform: ${result.platform}\nModel: ${result.model}`;
        sections.push({ name: 'summary', content: summary });
      }

      // Meta
      const meta = {
        agent: result.model || result.platform,
        model: result.model,
        source_platform: result.platform,
        source_url: location.href,
        title: result.title,
        tags: 'ai-conversation,' + result.platform
      };

      const pfmContent = await PFMSerializer.serialize(sections, meta);
      const filename = sanitizeFilename(result.title.substring(0, 60)) + '.pfm';
      pfmDownload(pfmContent, filename, 'text/plain');

      showStatus(btn, 'Saved!', false);
    } catch (err) {
      console.error('[PFM] Capture error:', err);
      showStatus(btn, 'Error: ' + err.message, true);
    }

    function showStatus(btn, msg, isError) {
      btn.textContent = msg;
      btn.style.background = isError
        ? 'linear-gradient(135deg, #f85149, #d29922)'
        : 'linear-gradient(135deg, #3fb950, #58a6ff)';
      setTimeout(() => {
        btn.textContent = origText;
        btn.style.background = 'linear-gradient(135deg, #58a6ff, #bc8cff)';
        btn.style.pointerEvents = '';
      }, 2000);
    }
  }

  /** Wait for a matching element to appear in the DOM */
  function waitForElement(selectors, timeout) {
    timeout = timeout || 10000;
    return new Promise((resolve) => {
      // Check immediately
      for (const sel of selectors) {
        try {
          const el = document.querySelector(sel);
          if (el) { resolve(el); return; }
        } catch (_) { /* skip */ }
      }

      const observer = new MutationObserver(() => {
        for (const sel of selectors) {
          try {
            const el = document.querySelector(sel);
            if (el) {
              observer.disconnect();
              resolve(el);
              return;
            }
          } catch (_) { /* skip */ }
        }
      });

      observer.observe(document.body, { childList: true, subtree: true });

      // Timeout fallback
      setTimeout(() => {
        observer.disconnect();
        resolve(null);
      }, timeout);
    });
  }

  /** Initialize: wait for conversation to load, then inject button */
  async function init() {
    const scraper = getScraper();
    if (!scraper) return;

    // Wait for conversation content to appear
    const conversationSelectors = {
      chatgpt: [
        '[data-testid^="conversation-turn-"]',
        'div[class*="group/conversation-turn"]',
        '.text-base'
      ],
      claude: [
        '[data-testid="conversation-turn"]',
        '[data-testid="human-turn"]',
        '.font-claude-message'
      ],
      gemini: [
        'message-content',
        '.user-query',
        '.model-response-text'
      ]
    };

    const selectors = conversationSelectors[scraper.platform] || [];
    const el = await waitForElement(selectors, 15000);
    if (el) {
      createButton();
    }
  }

  /** Watch for SPA navigation (URL changes without page reload) */
  function watchNavigation() {
    let lastUrl = location.href;

    const check = () => {
      if (location.href !== lastUrl) {
        lastUrl = location.href;
        removeButton();
        // Re-init after a short delay for SPA to render
        setTimeout(init, 1500);
      }
    };

    // Observe URL changes via multiple strategies
    const navObserver = new MutationObserver(check);
    navObserver.observe(document.body, { childList: true, subtree: true });

    // Also poll (some SPAs don't trigger mutations on navigation)
    setInterval(check, 2000);

    // Listen for popstate (back/forward)
    window.addEventListener('popstate', () => setTimeout(init, 1000));
  }

  /** Listen for messages from popup requesting capture */
  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg.action === 'capture_conversation') {
      const scraper = getScraper();
      if (!scraper) {
        sendResponse({ error: 'Platform not detected' });
        return;
      }
      const result = scraper.scrape();
      if (!result || result.messages.length === 0) {
        sendResponse({ error: 'No conversation found on this page' });
        return;
      }
      sendResponse({ data: result });
    }
    return true; // keep channel open for async
  });

  // Start
  init();
  watchNavigation();
})();
