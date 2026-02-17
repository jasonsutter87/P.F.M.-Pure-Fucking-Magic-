/* ================================================================
   Claude DOM Scraper
   Targets: claude.ai
   ================================================================ */
const ScraperClaude = {
  platform: 'claude',

  /** CSS selector fallbacks — ordered by stability */
  selectors: {
    messageGroup: [
      '[data-testid="conversation-turn"]',
      '.font-claude-message',
      '[class*="ConversationItem"]',
      '.prose'
    ],
    humanMessage: [
      '[data-testid="human-turn"]',
      '[class*="human-turn"]',
      '.font-user-message'
    ],
    assistantMessage: [
      '[data-testid="assistant-turn"]',
      '[class*="assistant-turn"]',
      '.font-claude-message'
    ],
    humanContent: [
      '[data-testid="human-turn"] .whitespace-pre-wrap',
      '[data-testid="human-turn"] p',
      '.font-user-message p'
    ],
    assistantContent: [
      '[data-testid="assistant-turn"] .grid-cols-1',
      '[data-testid="assistant-turn"] .prose',
      '.font-claude-message .prose',
      '[class*="markdown"]'
    ],
    conversationTitle: [
      'button[data-testid="chat-title"]',
      'h2',
      '[class*="ConversationTitle"]'
    ],
    modelBadge: [
      '[data-testid="model-selector"]',
      'button[class*="model"]',
      '[class*="ModelBadge"]'
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
    return location.hostname === 'claude.ai';
  },

  scrape() {
    const messages = [];

    // Strategy 1: Look for explicit human/assistant turns
    const humanTurns = this.query(document, this.selectors.humanMessage, true);
    const assistantTurns = this.query(document, this.selectors.assistantMessage, true);

    if (humanTurns.length > 0 || assistantTurns.length > 0) {
      // Collect all turns with position info for ordering
      const allTurns = [];

      for (const el of humanTurns) {
        const content = this.query(el, this.selectors.humanContent, false);
        const text = (content || el).innerText.trim();
        if (text) allTurns.push({ el, role: 'user', content: text });
      }

      for (const el of assistantTurns) {
        const content = this.query(el, this.selectors.assistantContent, false);
        const text = (content || el).innerText.trim();
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

    // Strategy 2: Fallback — look for alternating message blocks
    if (messages.length === 0) {
      const groups = this.query(document, this.selectors.messageGroup, true);
      let isUser = true;
      for (const group of groups) {
        const text = group.innerText.trim();
        if (text) {
          messages.push({ role: isUser ? 'user' : 'assistant', content: text });
          isUser = !isUser;
        }
      }
    }

    if (messages.length === 0) return null;

    // Title
    let title = 'Claude Conversation';
    const titleEl = this.query(document, this.selectors.conversationTitle, false);
    if (titleEl) {
      const t = titleEl.innerText.trim();
      if (t && t.length < 200) title = t;
    }

    // Model
    let model = 'claude';
    const modelEl = this.query(document, this.selectors.modelBadge, false);
    if (modelEl) {
      const m = modelEl.innerText.trim().toLowerCase();
      if (m && m.length < 50) model = m;
    }

    return { messages, title, model, platform: this.platform };
  }
};
