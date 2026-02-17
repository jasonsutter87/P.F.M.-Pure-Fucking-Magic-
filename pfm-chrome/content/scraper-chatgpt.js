/* ================================================================
   ChatGPT DOM Scraper
   Targets: chat.openai.com, chatgpt.com
   ================================================================ */
const ScraperChatGPT = {
  platform: 'chatgpt',

  /** CSS selector fallbacks — ordered by stability */
  selectors: {
    turnContainer: [
      '[data-testid^="conversation-turn-"]',
      'div[class*="group/conversation-turn"]',
      '.text-base'
    ],
    userMessage: [
      '[data-message-author-role="user"]',
      '[data-testid="user-message"]'
    ],
    assistantMessage: [
      '[data-message-author-role="assistant"]',
      '[data-testid="assistant-message"]',
      '.markdown.prose'
    ],
    conversationTitle: [
      'h1',
      'nav a.bg-token-sidebar-surface-secondary',
      '[data-testid="conversation-title"]'
    ],
    modelName: [
      '[data-testid="model-switcher-dropdown"]',
      'span[class*="model"]',
      'button[aria-haspopup="menu"] span'
    ]
  },

  /** Try multiple selectors, return first match(es) */
  query(parent, selectorList, all) {
    for (const sel of selectorList) {
      try {
        const result = all ? parent.querySelectorAll(sel) : parent.querySelector(sel);
        if (all ? result.length > 0 : result) return result;
      } catch (_) { /* invalid selector, skip */ }
    }
    return all ? [] : null;
  },

  /** Detect if we're on a ChatGPT conversation page */
  detect() {
    const host = location.hostname;
    return host === 'chat.openai.com' || host === 'chatgpt.com';
  },

  /** Scrape the current conversation */
  scrape() {
    const turns = this.query(document, this.selectors.turnContainer, true);
    if (!turns || turns.length === 0) {
      return null;
    }

    const messages = [];
    for (const turn of turns) {
      // Determine role
      const userEl = this.query(turn, this.selectors.userMessage, false);
      const assistantEl = this.query(turn, this.selectors.assistantMessage, false);

      if (userEl) {
        messages.push({ role: 'user', content: userEl.innerText.trim() });
      } else if (assistantEl) {
        messages.push({ role: 'assistant', content: assistantEl.innerText.trim() });
      } else {
        // Fallback: try to infer from turn structure
        const text = turn.innerText.trim();
        if (text) {
          // Check data attributes for role hints
          const role = turn.dataset?.messageAuthorRole ||
                       (turn.querySelector('[data-message-author-role]')?.dataset?.messageAuthorRole) ||
                       'unknown';
          messages.push({ role, content: text });
        }
      }
    }

    if (messages.length === 0) return null;

    // Get conversation title
    let title = 'ChatGPT Conversation';
    const titleEl = this.query(document, this.selectors.conversationTitle, false);
    if (titleEl) {
      const t = titleEl.innerText.trim();
      if (t && t.length < 200) title = t;
    }

    // Get model name
    let model = 'chatgpt';
    const modelEl = this.query(document, this.selectors.modelName, false);
    if (modelEl) {
      const m = modelEl.innerText.trim().toLowerCase();
      if (m && m.length < 50) model = m;
    }

    return { messages, title, model, platform: this.platform };
  }
};
