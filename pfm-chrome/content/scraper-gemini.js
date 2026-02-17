/* ================================================================
   Gemini DOM Scraper
   Targets: gemini.google.com
   ================================================================ */
const ScraperGemini = {
  platform: 'gemini',

  /** CSS selector fallbacks — ordered by stability */
  selectors: {
    turnContainer: [
      'message-content',
      '.conversation-container message-content',
      '[class*="message-content"]'
    ],
    userMessage: [
      '.user-query',
      'message-content.user-message',
      '[data-message-type="user"]',
      '.query-text'
    ],
    assistantMessage: [
      '.model-response-text',
      'message-content.model-response',
      '[data-message-type="model"]',
      '.response-text',
      '.markdown-main-panel'
    ],
    conversationTitle: [
      '.conversation-title',
      'h1.title',
      '[data-conversation-title]'
    ],
    modelName: [
      '.model-selector',
      '[data-model-name]',
      'button[aria-label*="model"]'
    ]
  },

  query(parent, selectorList, all) {
    for (const sel of selectorList) {
      try {
        const result = all ? parent.querySelectorAll(sel) : parent.querySelector(sel);
        if (all ? result.length > 0 : result) return result;
      } catch (_) { /* skip */ }
    }
    return all ? [] : null;
  },

  detect() {
    return location.hostname === 'gemini.google.com';
  },

  scrape() {
    const messages = [];

    // Strategy 1: Explicit user/model messages
    const userEls = this.query(document, this.selectors.userMessage, true);
    const assistantEls = this.query(document, this.selectors.assistantMessage, true);

    if (userEls.length > 0 || assistantEls.length > 0) {
      const allTurns = [];

      for (const el of userEls) {
        const text = el.innerText.trim();
        if (text) allTurns.push({ el, role: 'user', content: text });
      }

      for (const el of assistantEls) {
        const text = el.innerText.trim();
        if (text) allTurns.push({ el, role: 'assistant', content: text });
      }

      // Sort by DOM order
      allTurns.sort((a, b) => {
        const pos = a.el.compareDocumentPosition(b.el);
        return pos & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1;
      });

      for (const turn of allTurns) {
        messages.push({ role: turn.role, content: turn.content });
      }
    }

    // Strategy 2: Fallback — generic turn containers
    if (messages.length === 0) {
      const turns = this.query(document, this.selectors.turnContainer, true);
      let isUser = true;
      for (const turn of turns) {
        const text = turn.innerText.trim();
        if (text) {
          messages.push({ role: isUser ? 'user' : 'assistant', content: text });
          isUser = !isUser;
        }
      }
    }

    if (messages.length === 0) return null;

    // Title
    let title = 'Gemini Conversation';
    const titleEl = this.query(document, this.selectors.conversationTitle, false);
    if (titleEl) {
      const t = titleEl.innerText.trim();
      if (t && t.length < 200) title = t;
    }

    // Model
    let model = 'gemini';
    const modelEl = this.query(document, this.selectors.modelName, false);
    if (modelEl) {
      const m = modelEl.innerText.trim().toLowerCase();
      if (m && m.length < 50) model = m;
    }

    return { messages, title, model, platform: this.platform };
  }
};
