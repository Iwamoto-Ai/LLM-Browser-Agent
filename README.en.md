# LLM-Browser-Agent (Standalone / MCP Server)

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://www.apache.org/licenses/LICENSE-2.0)
[![Python](https://img.shields.io/badge/Python-3.10%2B-green.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows-blue.svg)](https://github.com/Iwamoto-Ai/LLM-Browser-Agent)
[![MCP](https://img.shields.io/badge/MCP-Compatible-purple.svg)](https://modelcontextprotocol.io/)
[![CI](https://github.com/Iwamoto-Ai/LLM-Browser-Agent/actions/workflows/ci.yml/badge.svg)](https://github.com/Iwamoto-Ai/LLM-Browser-Agent/actions/workflows/ci.yml)

**日本語版 README: [README.md](README.md)** (more detailed)

A DOM-based browser automation agent driven by LLMs. Instead of "looking at pixels",
it assigns an index number to every interactive element on the page and lets the LLM
operate by number — so it works reliably even with small **local models without vision**
(Ollama), as well as with the Anthropic API. Runs on native Windows 11 (no WSL),
driving **Microsoft Edge (default) or Google Chrome**.

## Highlights

- **3 run modes**: one-shot CLI, YAML template runner (procedure/data separation), and an
  **MCP server** usable from Claude Desktop, OpenClaw, or Hermes Agent.
- **2 LLM backends**: Anthropic API (cloud) or **Ollama (local, no API key, fully offline)**.
- **2 browser engines** behind one interface: Selenium (default) or Playwright
  (auto-waiting; runs in a dedicated thread so it also works under the asyncio-based MCP server).
- **Deterministic replay of Chrome DevTools Recorder JSON** — no extension required, no LLM
  needed for fixed routine flows. Supports `{{key}}` value substitution, iframes
  (by index or by frame *name*) and popup windows.
- **Secrets never reach the model**: write `{{SECRET:NAME}}` and the browser layer fills in
  the value from local environment variables. Optional
  **`<NAME>_ALLOWED_DOMAINS` allow-list** blocks a prompt-injected page from luring the
  agent into typing your password on another site.
- **Rich page state for the LLM**: element list with current input values, `<select>`
  options, checkbox ON/OFF, page headings/alerts, and (Playwright) captured JS/console
  errors. `get_page_text` returns the page body for read-only tasks.
- **Robust local-LLM loop**: history pruning of old page states (avoids context overflow —
  the main cause of "agent keeps repeating itself"), explicit `OLLAMA_NUM_CTX`,
  tool-call salvage from plain-text JSON, `<think>` stripping.
- **Evidence-grade screenshots**: timestamped filenames, full-page capture on both engines
  (Selenium uses CDP `captureBeyondViewport`).
- **Exponential-backoff retry** for Anthropic API rate limits / overload (429 / 529).

## Install

```powershell
cd C:\path\to\LLM-Browser-Agent
pip install -r requirements.txt          # or: pip install -e ".[all]"
copy .env.example .env                   # only if using the Anthropic API
```

Optional: `pip install -e ".[all]"` installs console commands
`llm-browser-agent`, `llm-browser-agent-ollama`, `llm-browser-agent-mcp`,
`llm-browser-agent-template`, `llm-browser-agent-recording`.

## Quick start

```powershell
# One-shot task (cloud)
python agent.py --task "log in with {{SECRET:MY_USERNAME}} / {{SECRET:MY_PASSWORD}}, search 'MCP server', save result.png" --start-url example.com --no-headless

# One-shot task (local Ollama, no API key)
$env:OLLAMA_THINK="0"; $env:OLLAMA_NUM_CTX="16384"; $env:NO_PROXY="localhost,127.0.0.1"
python agent_ollama.py --task "..." --model qwen3:14b --browser edge --no-headless

# Template runner (procedure YAML + values JSON)
python run_template.py --template templates/example_site.yaml --values data/example_values.json --backend ollama --no-headless

# Deterministic replay of a Chrome Recorder export
python run_recording.py --recording recordings/test_site.example.json --values data/test_values.json --no-headless
```

## MCP server (Claude Desktop)

Add to `%APPDATA%\Claude\claude_desktop_config.json` (see
`claude_desktop_config.example.json`):

```json
{
  "mcpServers": {
    "browser-agent": {
      "command": "python",
      "args": ["C:\\path\\to\\LLM-Browser-Agent\\mcp_server.py"],
      "env": {
        "BROWSER_AGENT_ENGINE": "selenium",
        "BROWSER_AGENT_BROWSER": "edge",
        "BROWSER_AGENT_HEADLESS": "0",
        "MY_USERNAME": "your-login-id",
        "MY_PASSWORD": "your-password",
        "MY_PASSWORD_ALLOWED_DOMAINS": "example.co.jp"
      }
    }
  }
}
```

Exposed tools: `open_browser`, `navigate`, `get_page_state`, `get_page_text`,
`click_element`, `input_text`, `select_option`, `set_checked`, `send_keys`, `scroll`,
`take_screenshot` (returns the image to the host), `close_browser`.

## Test locally without a real site

```powershell
cd test_site && python -m http.server 8000    # demo credentials: demo / password123
python test_site/selftest.py --browser edge --no-headless          # plumbing test, no LLM
python test_site/selftest.py --engine playwright --browser edge --no-headless
```

A practice site with framesets and popup calendars (`test_site/edi/`) is included for
testing iframe/popup replay. Unit tests: `pytest -q`. CI runs lint + unit tests on
Ubuntu and real-Edge selftests (both engines) on Windows.

## License

[Apache License 2.0](LICENSE). Copyright 2026 Iwamoto-Ai.
