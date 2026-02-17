# Contributing to PFM

Thanks for your interest in PFM. Here's how you can help.

## Quick Links

- [GitHub Issues](https://github.com/jasonsutter87/P.F.M.-Pure-Fucking-Magic-/issues)
- [Web Viewer & Converter](https://jasonsutter87.github.io/P.F.M.-Pure-Fucking-Magic-/)
- [Python Package (PyPI)](https://pypi.org/project/pfm/)
- [npm Package](https://www.npmjs.com/package/pfm)

## Ways to Contribute

### 1. Framework Integrations (Highest Impact)

The single most valuable contribution is adding PFM export to an existing AI agent framework. If you use LangChain, CrewAI, AutoGen, Haystack, or any other agent framework, building a `.pfm` export integration helps the entire ecosystem.

**What an integration looks like:**
- A callback handler, plugin, or wrapper that captures agent execution
- Writes a `.pfm` file with sections: `content`, `chain`, `tools`, `metrics`
- Published as a standalone package (e.g., `langchain-pfm`)

**Integration bounty:** We're offering $100 per accepted framework integration for the first 5 frameworks. See the [Bounty Program](#bounty-program) section below.

### 2. Bug Reports & Feature Requests

Open an issue with:
- What you expected to happen
- What actually happened
- Steps to reproduce
- Your environment (Python version, OS, etc.)

### 3. Code Contributions

1. Fork the repo
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Make your changes
4. Run tests: `pytest tests/ -v` (Python) or `npm test` (JS)
5. Submit a PR

### 4. Documentation

- Improve README examples
- Write tutorials or blog posts
- Add docstrings or type hints
- Translate documentation

### 5. Spec Feedback

The .pfm format spec is v1.0 and evolving. Open a discussion issue if you think something should change.

## Development Setup

### Python

```bash
git clone https://github.com/jasonsutter87/P.F.M.-Pure-Fucking-Magic-.git
cd P.F.M.-Pure-Fucking-Magic-
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest tests/ -v
```

### JavaScript/TypeScript

```bash
cd pfm-js
npm install
npm run build
npm test
```

### VS Code Extension

```bash
cd pfm-vscode
npm install
npm run compile
```

## Code Style

- Python: Follow existing patterns, type hints encouraged
- TypeScript: Strict mode, no `any` unless necessary
- Tests: Write tests for new functionality
- Security: Never introduce OWASP Top 10 vulnerabilities

## Bounty Program

$500 total ($100 per integration) for the first 5 accepted framework integrations:

| Framework | Status | Bounty |
|-----------|--------|--------|
| LangChain / LangGraph | Open | $100 |
| CrewAI | Open | $100 |
| AutoGen | Open | $100 |
| Haystack | Open | $100 |
| OpenAI Agents SDK | Open | $100 |

**Requirements:**
- Working integration with tests
- README with usage examples
- Handles edge cases (empty output, errors)
- Published to PyPI or npm

To claim a bounty, open an issue titled "Bounty: [Framework] Integration" before starting work.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
