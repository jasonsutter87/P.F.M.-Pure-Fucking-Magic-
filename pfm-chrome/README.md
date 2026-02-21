# PFM Chrome Extension

Capture AI conversations directly from your browser as `.pfm` files.

## Supported Platforms

- **ChatGPT** (chat.openai.com, chatgpt.com)
- **Claude** (claude.ai)
- **Gemini** (gemini.google.com)
- **Grok** (grok.com, grok.x.ai, x.com/i/grok)
- **OpenClaw** (openclaw.ai)

## Features

- One-click capture of any AI conversation as a `.pfm` file
- Popup with **Capture** tab (save current conversation) and **View/Convert** tab (drop files)
- Full-tab `.pfm` viewer with sidebar, search, keyboard shortcuts, and export
- Stores conversation chain (`User: ... / Assistant: ...`) for downstream use
- Zero dependencies — pure browser APIs only (Manifest V3)

## Install

Available on the [Chrome Web Store](https://chromewebstore.google.com/) (in review).

### Manual / Development

1. Clone this repo
2. Open `chrome://extensions/` in Chrome
3. Enable **Developer mode**
4. Click **Load unpacked** and select the `pfm-chrome/` directory

## How It Works

Each supported AI site has a dedicated content script scraper (`content/scraper-*.js`) that extracts:

- **Conversation turns** — the full `User: ... / Assistant: ...` chain
- **Metadata** — model name, platform, page title, source URL
- **Content** — the final assistant response

The captured data is serialized into `.pfm` format using the shared PFM core (`shared/pfm-core.js`) and downloaded as a file.

## Export to Fine-Tuning Data

Captured `.pfm` files can be exported to fine-tuning JSONL using the CLI:

```bash
pfm export ./captured/ -o training.jsonl --format openai
pfm export ./captured/ -o training.jsonl --format alpaca
pfm export ./captured/ -o training.jsonl --format sharegpt

# Or use the spell alias
pfm pensieve ./captured/ -o training.jsonl
```

Install the CLI via `pip install get-pfm` or `npm install -g get-pfm`.

## Structure

```
pfm-chrome/
├── manifest.json              # MV3 manifest
├── background/
│   └── service-worker.js      # Background service worker
├── content/
│   ├── content-main.js        # Shared content script entry point
│   ├── scraper-chatgpt.js     # ChatGPT conversation extractor
│   ├── scraper-claude.js      # Claude conversation extractor
│   ├── scraper-gemini.js      # Gemini conversation extractor
│   ├── scraper-grok.js        # Grok conversation extractor
│   └── scraper-moltbot.js     # OpenClaw conversation extractor
├── popup/
│   ├── popup.html             # Extension popup UI
│   ├── popup.css              # Popup styles
│   └── popup.js               # Popup logic (capture + view/convert tabs)
├── shared/
│   └── pfm-core.js            # PFM parser, serializer, converters
├── viewer/
│   ├── viewer.html            # Full-tab .pfm viewer
│   └── viewer.js              # Viewer logic (sidebar, search, export)
└── icons/
    ├── icon16.png
    ├── icon48.png
    └── icon128.png
```

## License

MIT
