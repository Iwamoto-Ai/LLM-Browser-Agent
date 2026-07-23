# LLM-Browser-Agent (Standalone / MCP Server)

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://www.apache.org/licenses/LICENSE-2.0)
[![Python](https://img.shields.io/badge/Python-3.11%2B-green.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows-blue.svg)](https://github.com/Iwamoto-Ai/LLM-Browser-Agent)
[![MCP](https://img.shields.io/badge/MCP-Compatible-purple.svg)](https://modelcontextprotocol.io/)
[![LLM](https://img.shields.io/badge/LLM-Claude_%7C_Ollama-orange.svg)](https://ollama.com/)
[![CI](https://github.com/Iwamoto-Ai/LLM-Browser-Agent/actions/workflows/ci.yml/badge.svg)](https://github.com/Iwamoto-Ai/LLM-Browser-Agent/actions/workflows/ci.yml)

**日本語版 README: [README.md](README.md)**

A DOM (Document Object Model) based browser automation agent. It can record browser
operations and replay them (using Google Chrome Recorder), and it can also perform
**login, search, and screenshot capture** from natural-language instructions.
Switchable between **Microsoft Edge (default) / Google Chrome**, running on
**native Windows 11 with no WSL required**. The LLM ("brain") can be either
**cloud-based (Anthropic API)** or **local (Ollama — no API key needed)**.

> Instead of the "look at the screen as an image and operate it" approach, this tool
> **assigns an index number to every interactive element on the page and operates by
> that number** — a DOM (Document Object Model) based method. As a result, it works
> reliably even with lightweight local LLMs that have no image recognition (vision).

---

## ✨ Features (what it can do)

- **Browser automation with free software**: no Power Automate required. Works even with a local LLM that needs no API key.
- **Business workflow automation**: log in → navigate menus → fill in multiple fields → submit → screenshot of the completion screen, all from natural language.
- **Per-site template operation**: separate the procedure (template) from the values (data), so the same procedure can be repeated with different data.
- **3 run modes**: one-shot CLI / template runner / MCP server (conversational operation from Claude Desktop, OpenClaw, or Hermes Agent).
- **2 LLM backends**: cloud (Anthropic API) / local (Ollama — no API key, fully local).
- **2 browser engines**: Selenium (default) / Playwright (stable thanks to auto-waiting, full-page screenshots).
- **An escape hatch for locked-down workplaces**: drive WebDriver over HTTP from Power Automate Desktop and
  run the same batches without any browser extension ([guide](docs/PAD_WebDriver.md)).
- **Batch execution from Excel/CSV details**: process dozens of registrations/confirmations in one command (progress display, result CSV, re-run failures only).
- **Deterministic replay of Google Chrome Recorder recordings**: replays a recorded operations file (JSON) reliably without an LLM and without any browser extension (for complex sites).
- **Secrets never reach the model**: passwords are referenced as `{{SECRET:NAME}}` and the real values are filled in locally at runtime.
- **Evidence-grade screenshots**: filenames automatically get a timestamp `_YYYYMMDD_HHMMSS` (never overwritten). Selenium also supports full-page capture via CDP.
- **Select box / checkbox support**: operate them reliably with the `select_option` / `set_checked` tools. The list of select options and checkbox ON/OFF state appear in the element list.
- **Page body reading**: `get_page_text` lets the LLM read tables, query results, and line items (read-oriented tasks are supported too).
- **Domain restriction for SECRETs**: `<NAME>_ALLOWED_DOMAINS` limits which sites a secret may be typed into (a countermeasure against prompt injection by malicious pages).

---

## 🧩 The big picture (combine the 3 axes)

This tool freely combines three axes: **run mode × LLM backend × browser engine**.
Whichever you choose, the core mechanism (operating elements by index number) is the same.

### 1) Run mode (how to run it)

| Mode | File | Description |
|---|---|---|
| Template runner (recommended) | `run_template.py` | Repeatable runs with a per-site YAML + values JSON. Switch with `--backend` / `--engine` |
| Standalone (one-shot CLI) | `agent.py` (cloud) / `agent_ollama.py` (local) | Runs a natural-language task once, automatically |
| MCP server | `mcp_server.py` | Operate conversationally from Claude Desktop / OpenClaw / Hermes Agent |

### 2) LLM backend (the brain)

| Backend | Requirements | Notes |
|---|---|---|
| Anthropic API (cloud) | `ANTHROPIC_API_KEY` | Default. e.g. `claude-sonnet-4-6`. Most reliable tool use |
| Ollama (local LLM) | Local Ollama + a tool-calling capable model | **No API key, fully local**. `--backend ollama` |

### 3) Browser engine (the hands)

| Engine | Requirements | Characteristics |
|---|---|---|
| Selenium (default) | `selenium` | The proven default. `--engine selenium` |
| Playwright | `playwright` | Strong on dynamic pages and complex menus thanks to **auto-waiting**. Full-page screenshots. `--engine playwright` |

### 🧭 How to choose

- **In-house / offline use** → backend `ollama` (no API key). Doesn't conflict with your company's AI such as Copilot.
- **Maximum reliability** → backend `anthropic` (cloud). Also good as a behavioral baseline.
- **Dynamic pages / many fields / worried about missed elements** → engine `playwright` (reliable waiting).
- **Start with the minimal setup** → the defaults (Selenium + Anthropic, or Selenium + Ollama) are fine.

---

## 🛠️ Setup (native Windows 11 / no WSL)

1. **Python 3.10+** … installer from python.org (check "Add python.exe to PATH")
2. **Microsoft Edge** … standard on Windows 11 (default browser). Install Google Chrome separately if you want to use it
3. WebDrivers (msedgedriver / chromedriver) are **fetched automatically by Selenium Manager** (no manual installation)
4. **(If using a local LLM) Ollama** … install from <https://ollama.com/> and run `ollama pull qwen3:14b`
5. **(If using Playwright)** … `pip install playwright`. Because `channel=msedge` uses the already-installed Edge, `playwright install` is not needed

```powershell
cd C:\path\to\LLM-Browser-Agent
pip install -r requirements.txt
# Needed only if you want batch details read directly from Excel (.xlsx)
pip install openpyxl
# Or install as a package (adds console scripts):
#   pip install -e ".[all]"   → commands like llm-browser-agent / llm-browser-agent-mcp become available
# Only if using the cloud (Anthropic API):
copy .env.example .env   # fill in ANTHROPIC_API_KEY
# If you only use local (Ollama), no API key is needed
```

---

## ▶️ Usage

### A. Template operation (recommended)

Repeat "log in → menu → many numeric inputs → submit → completion screenshot" with a
**template written once per site**. The key idea is separating the procedure (template)
from the values (data).

- **Template** `templates/<site>.yaml` … login steps, menu navigation, input fields. One per site.
- **Data** `data/<run>.json` … the actual values to enter. Swap per run. Referenced as `{{key}}`.
- Passwords etc. stay as `{{SECRET:NAME}}` and are filled from environment variables at runtime (real values never appear in the prompt) — secure by design.

```powershell
# First, inspect the generated prompt (does not launch a browser)
python run_template.py --template templates/example_site.yaml --values data/example_values.json --dry-run

# Run with the cloud backend (default)
python run_template.py --template templates/example_site.yaml --values data/example_values.json --browser edge --no-headless

# Run with a local LLM (Ollama) — no API key. Use the stabilizing environment variables too
$env:OLLAMA_THINK="0"; $env:NO_PROXY="localhost,127.0.0.1"
python run_template.py --template templates/example_site.yaml --values data/example_values.json --backend ollama --model qwen3:14b --browser edge --no-headless

# Run with the Playwright engine (just add --engine)
python run_template.py --template templates/example_site.yaml --values data/example_values.json --engine playwright --browser edge --no-headless
```

See `templates/example_site.yaml` for how to write templates (`login` / `navigation` /
`fields` / `submit` / `verify` / `screenshot`). For sites with many fields, just add to
`fields`. For complex menus, describe them concretely in natural language under
`navigation` and the LLM will follow them.

**Reliability techniques (important)**: the current value of each input appears in
`state()`, and "key text" such as completion headings also appears in `state()` (see
"How it works" below). The generated prompt enforces the order "enter one field →
verify its current value → re-verify all fields → confirm completion and screenshot".
If any value is missing from `--values`, it stops with an error before running.
Increase `--max-steps` for sites with many fields.

| 🔧 Option | Default | Description |
|---|---|---|
| `--template` | (required) | Site template (YAML) |
| `--values` | none | Input values (JSON), substituted into `{{key}}` |
| `--backend` | `anthropic` | `anthropic` (cloud) / `ollama` (local) |
| `--engine` | `selenium` | `selenium` / `playwright` |
| `--browser` | `edge` | `edge` / `chrome` |
| `--model` | backend-dependent | If unset: anthropic `claude-sonnet-4-6` / ollama `qwen3:14b` |
| `--max-steps` | `40` | Increase with the number of fields (rule of thumb: fields × 3 + 10) |
| `--dry-run` | — | Show the generated prompt only |
| `--no-headless` | (headless) | Show the browser window |

### B. Standalone (one-shot CLI)

```powershell
# Cloud (Anthropic API)
python agent.py --task "Log in with username {{SECRET:MY_USERNAME}} and password {{SECRET:MY_PASSWORD}}, search for 'MCP server' and save the result as result.png" --start-url example.com --browser edge --no-headless

# Local LLM (Ollama) — no API key
python agent_ollama.py --task "..." --start-url example.com --model qwen3:14b --browser edge --no-headless

# Switching to Chrome / Playwright works the same way (--browser chrome / --engine playwright)
```

### C. MCP server (Claude Desktop / 🦞OpenClaw / 🟣Hermes Agent)

When you ask in conversation, "log in to XX, register YY, and take a screenshot",
the host-side LLM calls these tools:
`open_browser` / `navigate` / `get_page_state` / `get_page_text` / `click_element` / `input_text` /
`select_option` / `set_checked` / `send_keys` / `scroll` / `take_screenshot` / `close_browser`.
`take_screenshot` saves the image and also returns it to the host. No API key required.

The MCP server is configured via environment variables: `BROWSER_AGENT_ENGINE`
(selenium/playwright) / `BROWSER_AGENT_BROWSER` (edge/chrome) / `BROWSER_AGENT_HEADLESS`
(0/1) / `BROWSER_AGENT_OUTPUT` (screenshot directory). Put login credentials in `env`
and reference them as `{{SECRET:NAME}}`. Additionally, setting `<NAME>_ALLOWED_DOMAINS`
(e.g. `MY_PASSWORD_ALLOWED_DOMAINS`) restricts that secret so it can only be typed
into pages on the specified domains.

#### Claude Desktop (Windows)

Add to `%APPDATA%\Claude\claude_desktop_config.json` (see `claude_desktop_config.example.json`):

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
        "BROWSER_AGENT_OUTPUT": "C:\\Users\\<you>\\Pictures\\LLM-Browser-Agent",
        "MY_USERNAME": "your-login-id",
        "MY_PASSWORD": "your-password"
      }
    }
  }
}
```

Save and restart Claude Desktop, and the `browser-agent` tools will appear. To use
Playwright, set `BROWSER_AGENT_ENGINE` to `playwright`. If you prefer `uv`:
`"command": "uv", "args": ["run", "mcp_server.py"]` also works.

#### 🦞OpenClaw

Add a similar entry (`command` / `args` / `env`) under `mcp.servers`, or register with
`openclaw mcp set browser-agent -- python C:\path\to\mcp_server.py`.

#### 🟣 Hermes Agent (NousResearch)

Hermes is an autonomous agent that also runs on local LLMs (Ollama), with built-in MCP
client support (stdio and HTTP). If MCP support is not installed yet:
`cd ~/.hermes/hermes-agent && uv pip install -e ".[mcp]"`.
Register under `mcp_servers:` in `~/.hermes/config.yaml` (tools are auto-discovered at startup).

```yaml
mcp_servers:
  browser-agent:
    command: "python"
    args: ["/path/to/LLM-Browser-Agent/mcp_server.py"]
    env:
      BROWSER_AGENT_ENGINE: "selenium"   # selenium / playwright
      BROWSER_AGENT_BROWSER: "edge"    #  edge / chrome
      BROWSER_AGENT_HEADLESS: "0"
      BROWSER_AGENT_OUTPUT: "/path/to/output"   # screenshot directory
      MY_USERNAME: "your-login-id"
      MY_PASSWORD: "your-password"
    enabled: true
    timeout: 120
```

After registration, tools appear as `mcp_<server>_<tool>` (e.g. `mcp_browser-agent_navigate`)
to avoid name collisions. Check registration with `hermes mcp list` and tool discovery with
`hermes mcp test browser-agent`. Ask Hermes something like "log in to http://localhost:8000,
register the expenses, and save the completion screen" and it will operate the browser.

> **Driving Windows Edge from Hermes inside WSL**: set `command` to the Windows Python
> (e.g. `/mnt/c/Users/<you>/AppData/Local/Programs/Python/Python3xx/python.exe`), and pass
> the script in `args` and the paths in `env` in Windows form (`C:\\...`). Launching Hermes
> from under `/mnt/c/...` is recommended. To stay entirely inside WSL you need a Linux browser.
>
> **If the local LLM stalls on "explanations / confirmations" instead of acting**: prefix the
> request with `/no_think` and set `export OLLAMA_THINK=0` on the WSL side. Explicitly saying
> "No confirmation needed. Execute to the end with tools right now" also stabilizes it.

---

## 🦙 Local LLM (Ollama) tips

For environments where an API cannot be used (e.g. inside a company), the brain can be
swapped to a local Ollama. Behavior is the same as the cloud version.

```powershell
ollama pull qwen3:14b              # recommended (14B, stable for multi-step operations)
# ollama pull mistral-nemo         # lighter alternative (12B)

$env:OLLAMA_THINK="0"                 # disable thinking to curb wandering (effective for thinking models like qwen3)
$env:OLLAMA_NUM_CTX="16384"           # set the context length explicitly (fixes the main cause of wandering/repeats; default 16384)
$env:NO_PROXY="localhost,127.0.0.1"   # exclude localhost from the proxy (fixes connection errors)
python agent_ollama.py --task "..." --model qwen3:14b --browser edge --no-headless
```

- **⚠️ Important**
- **For multi-step form operations, choose a model with strong tool-calling capability.**
- **`OLLAMA_THINK=0`**: long thinking can cause repeated operations or drifting off to other pages. Disabling it makes the model decisive.
- **`NO_PROXY=localhost,127.0.0.1`**: the standard fix for `Failed to connect to Ollama` (prevents the client from routing localhost through a proxy).
- **`OLLAMA_NUM_CTX` (default 16384)**: sets the context length explicitly. With Ollama's own default, history gets silently truncated, causing "repeating the same operation / wandering". Use 8192 if VRAM is tight.
- **History pruning (automatic)**: only the most recent `AGENT_KEEP_STATES` page states (default 3) attached to tool results are kept; older ones are pruned automatically. Long form-filling tasks can finish even with a small context.
- **No vision needed**: elements are passed as indexed text, so models without image recognition can operate the browser.
- `OLLAMA_HOST` … default `http://localhost:11434`. Set this when using a remote Ollama.

---

## 🎭 Browser engines (Selenium / Playwright)

Switch with `--engine` (CLI) / `BROWSER_AGENT_ENGINE` (MCP). Both share the same
interface, so output and behavior are aligned.

- **Selenium (default)**: the proven default. WebDrivers are fetched automatically by Selenium Manager.
- **Playwright**: **auto-waiting** waits until elements become actionable, reducing missed
  interactions on dynamic pages and complex menus. Full-page screenshots are standard.
  With `channel="msedge"`/`"chrome"` it uses the **already-installed browser**, so no browser
  download is needed (`pip install playwright` is enough — good for corporate environments).
- **Stability over speed**: with LLM-driven automation the dominant cost is LLM inference,
  so the speed difference between engines is barely noticeable. Playwright's advantage is
  not speed but "reliable waiting".
- **Compatibility with MCP**: Playwright's sync API cannot run on asyncio, but this
  implementation drives Playwright in a **dedicated thread** wrapped in a synchronous
  interface, so it also works in the MCP server (`BROWSER_AGENT_ENGINE=playwright`).

```powershell
python run_template.py --template templates/test_site.yaml --values data/test_values.json --engine playwright --browser edge --no-headless
python test_site/selftest.py --engine playwright --browser edge --no-headless
```

---

## 🧪 Test locally

Before touching a real site, you can verify the whole flow on the bundled **local test
site**. `test_site/index.html` is a single HTML file requiring no server logic that
reproduces login → menu → expense form → completion screen
(demo credentials: `demo` / `password123`).

```powershell
# 1) Serve the test site (in another terminal)
cd test_site
python -m http.server 8000      #  → http://localhost:8000
```

```powershell
# 2-A) Plumbing test without an LLM (recommended first for isolating problems)
#      Operates the site with the browser layer only; success = a timestamped screenshot in output/
python test_site/selftest.py --browser edge --no-headless
python test_site/selftest.py --engine playwright --browser edge --no-headless   # with Playwright too
```

```powershell
# 2-B) Test via the agent (template operation)
$env:MY_USERNAME="demo"; $env:MY_PASSWORD="password123"
$env:OLLAMA_THINK="0"; $env:NO_PROXY="localhost,127.0.0.1"
python run_template.py --template templates/test_site.yaml --values data/test_values.json --backend ollama --model qwen3:14b --browser edge --no-headless
```

`selftest.py` operates the site using only the browser layer — no LLM, no network — so
**whether it passes** cleanly separates "browser-operation plumbing" issues from
"LLM judgment" issues. On success a screenshot
`output/test_selftest_YYYYMMDD_HHMMSS.png` is saved.

---

## 🎥 Record browser operations with Chrome's Recorder → deterministic replay (no extension needed)

For sites with complex menus or many fields, **replaying a procedure a human recorded
once** is more reliable than having the LLM decide every time. Chrome's DevTools has a
built-in **Recorder** that can **export recorded operations as JSON**. This tool loads
that JSON and **replays it deterministically without an LLM**.

**⚠️ Note**
> Chrome Recorder's "export as Playwright script" requires a Chrome extension (often not
> allowed inside companies). This tool replays the standard **"JSON file" export format**
> directly, so no Chrome extension is needed (Chrome 101+).
> Recording in Chrome and replaying in Edge basically works since the DOM is the same,
> but if the target site changes its content based on browser detection, replay in Chrome as well.

**🎥 Steps**
1. Open the website you want to record in Chrome. **Right-click** anywhere in the page
   and click "**Inspect**" (the bottom item) to open DevTools.
2. At the right end of the row with "Elements", click "**>>**" (to the right of "Network"),
   then click "**Recorder**" at the bottom of the menu.
3. The **Recorder** panel opens; click "**Create recording**" in the middle.
4. Set a recording name etc. (defaults are fine).
5. Click the red circle button "Start recording" near the bottom to start; click it again
   ("End recording") to stop.
6. To the right of the recording name are "↑ import" and "↓ export"; click "↓ export"
   and choose "JSON" — the "**JSON file**" format.
7. Save the exported JSON as `recordings/<name>.json`.
8. In the exported JSON, rewrite the `value` of `change` steps: `{{key}}` for variable
   values, `{{SECRET:NAME}}` for login IDs / passwords (the JSON is human-readable and re-importable).

   > **⚠️ Important (security)**: right after recording, the JSON contains the **real
   > values you typed (IDs and passwords) as-is**. Before saving, committing, or sharing,
   > always replace them with `{{SECRET:NAME}}` (secrets) / `{{key}}` (variable data).
   > Keep real values in `.env` or environment variables (`MY_USERNAME` / `MY_PASSWORD`, etc.),
   > never in the JSON.

9. Replay:

```powershell
# browser edge
$env:MY_USERNAME="demo"; $env:MY_PASSWORD="password123"
python run_recording.py --recording recordings/test_site.example.json --values data/test_values.json --browser edge --no-headless
```

```powershell
# browser chrome
$env:MY_USERNAME="demo"; $env:MY_PASSWORD="password123"
python run_recording.py --recording recordings/test_site.example.json --values data/test_values.json --browser chrome --no-headless
```

- **Deterministic**: executes the recorded steps exactly as recorded, so even complex sites don't drift (no LLM).
- **Data substitution**: `{{key}}` in `value` is filled from the `--values` JSON, so the same recording can be repeated with different data.
- **Secrets**: `{{SECRET:NAME}}` is filled from environment variables at runtime (real values appear neither in the JSON nor on screen).
- **Engine**: default is `playwright` (best compatibility with Recorder's css/xpath/text/aria/pierce selectors). `--engine selenium` also works.
- **Editing recordings (optional)**: Recorder also records the click before each input, but this tool can input with `change` alone, so you may delete redundant steps after export (`setViewport` etc. are skipped automatically during replay).
- **iframe (frame) support**: follows the recording's `frame` specification and operates elements inside that iframe.
  You can specify by **index** (`"frame": [2]` — from Chrome Recorder) or by **frame name**
  (`"frame": "content"` — from Playwright Codegen). Name-based specification survives frame
  reordering and is more robust. If the element is not found in the specified frame, it
  **searches across all frames** (resilient against missed reference panels etc.).
  For frame-heavy sites (frameset-style business systems), **`--engine playwright` is
  recommended** (Selenium has simplified support: specified frame + top-level fallback;
  name specification switches by name or id).
- **Popup (separate window) support**: handles sites where e.g. a calendar opens in another
  window (steps whose `target` is a URL). Playwright searches all windows × all frames;
  Selenium does best-effort window switching. However, **direct input is more stable than
  popup selection**, so if possible edit the recording to enter values directly
  (e.g. just `change` `{{yyyymm}}` into the year-month field and delete the steps after the reference button).
- **`--max-steps N`**: run only the first N steps. Useful to stop before a trailing Logout
  and take the screenshot at the desired screen (e.g. run from login to the query screen and stop).
- **Screenshot orientation**: reflects the recording's `setViewport` (window width × height),
  so the saved image looks close to what you saw while recording. Add `--viewport-shot` to
  capture **only the visible area (landscape)** instead of the full page.
- If any value is missing it stops with an error before running. Try it right now with the bundled `recordings/test_site.example.json`.

> **Which to use**: for routine work with fixed steps, use **recording replay (reliable)**;
> for work that needs judgment or has screen variations, use **LLM-driven (template
> operation)**. Both share the same `browser` layer.

### 🧪 Try it without a real system: local practice site (iframe + popup)

Even without access to a real business system, a **practice dummy site with iframes
(framesets) and a popup calendar window** is bundled, so you can verify frame and popup
support entirely locally (a practice-only page containing no company names, real URLs,
or real data).

The layout mimics common real-world business systems: login → frameset
(menu = frame[0] / search form = frame[2]) → year-month field (direct input, or "Browse"
opens a calendar in another window) → search → results.

```powershell
# 1) Serve the site (another terminal; serve with test_site as the root)
cd test_site
python -m http.server 8000      #  → practice site: http://localhost:8000/edi/index.html  (demo / password123)
```

```powershell
# 2) Put the demo credentials in environment variables (recordings use {{SECRET:...}}, so real values are supplied here)
$env:MY_USERNAME="demo"; $env:MY_PASSWORD="password123"
```

```powershell
# 3-A) Direct-input version (type the year-month directly → search): verifies iframe traversal
python run_recording.py --recording recordings/edi_practice_direct.json --values data/edi_practice_values.json --engine playwright --browser edge --no-headless
```

```powershell
# 3-B) Popup version (Browse → pick May in the calendar window → search): verifies iframe + separate window
python run_recording.py --recording recordings/edi_practice_popup.json --values data/edi_practice_values.json --engine playwright --browser edge --no-headless

# 3-C) Frame-name version (frames specified by name "menu"/"content"): verifies Codegen-style name specification
python run_recording.py --recording recordings/edi_practice_named.json --values data/edi_practice_values.json --engine playwright --browser edge --no-headless
```

- The **direct-input version** verifies **iframe traversal** across `frame[0]` (the menu's
  "Acceptance Inquiry") and `frame[2]` (year-month input and search).
- The **popup version** verifies **popup support**: switching to the calendar in the other
  window, picking "May", and reflecting it back into the parent frame's year-month field.
  The log shows `クリック: ...（frame=[2]）` and `（..., popup）`.
- After the run, the results screen (`検収照会 結果（練習）`) is saved as a timestamped
  screenshot (`output/recording_done_*.png`).
- For popup-heavy sites, **`--engine playwright` is recommended** (Selenium is best-effort).

> Once you've confirmed that "recording replay with frames/popups" passes on this practice
> site, you can move to production with exactly the same procedure
> (record → JSON → `run_recording.py`) when the real environment is ready.

### 🧭 Use Playwright Codegen to investigate selectors and frame names

Playwright has [Codegen](https://playwright.dev/python/docs/codegen), which records your
actions and generates **Playwright code**. It gives you **more robust selectors** than
Chrome Recorder JSON (semantic ones like `get_by_role` / `get_by_label`) and **frame
names** (`frame[name="content"]`), making it a useful **"investigation / drafting" tool
when writing recording JSON**.

```powershell
# With the practice site being served (another terminal):
python -m playwright codegen http://localhost:8000/edi/index.html
```

A browser and the Inspector open; as you operate, code is generated. Example (excerpt):

```python
page.get_by_role("button", name="Login").click()
page.locator("frame[name=\"menu\"]").content_frame.get_by_role("link", name="検収照会").click()
with page.expect_popup() as p:                    # ← the Browse button opens the calendar in another window
    page.locator("frame[name=\"content\"]").content_frame.get_by_role("button", name="参照").click()
page.locator("frame[name=\"content\"]").content_frame.locator("#yyyymm").fill("2026-05")
```

Writing this tool's recording JSON from that output gives stable results. Mapping guide:

| Codegen output | This tool's recording JSON |
|---|---|
| `page.goto("...")` | `{"type":"navigate","url":"..."}` |
| `get_by_role("button", name="Login").click()` | `{"type":"click","selectors":[["aria/Login"],["text/Login"]]}` |
| `get_by_label("年月").fill("2026-05")` | `{"type":"change","value":"{{yyyymm}}","selectors":[["aria/年月"]]}` |
| `frame[name="content"].content_frame...` | add `"frame": "content"` to the same step (**name specification**) |
| operations inside `with page.expect_popup(): ...` | add `"target": "<popup URL>"` |

- **Frames can be specified by name** (`"frame": "content"`). You can use the name Codegen
  shows as-is, which is more robust than an index (`[2]`). The bundled
  `recordings/edi_practice_named.json` is a working example of name specification.
- **Watch out for secrets**: Codegen output also contains the real IDs/passwords you typed,
  in plain text. When copying into JSON, always replace them with `{{SECRET:NAME}}` and
  variable values with `{{key}}` (same practice as with Recorder).
- The recommended unified workflow: use Codegen for "investigation / drafting", and run with
  this tool's JSON replay (which adds secret masking, value substitution, timestamped
  screenshots, and engine switching).

---

## 🔁 Batch execution (process dozens of detail rows from Excel/CSV)

In real work you rarely process one item at a time — you register or confirm **dozens of items in one go**.
`run_batch.py` treats each row of an Excel/CSV detail file as one item and **repeats the recorded replay
steps once per row** (no LLM required). Looping, progress display, error handling and re-runs are all
handled by this layer, so your templates (recordings) stay simple.

```powershell
python run_batch.py --batch recordings/edi_practice_batch.json --details data/edi_practice_batch.csv --engine playwright --browser edge --no-headless
```

### 📄 Batch definition JSON (setup / loop / recover / teardown)

Split the steps into "run once" and "repeat per item". Steps use the Chrome Recorder format as-is.
**Comments are allowed**: any line whose first non-space characters are `//` or `#` is skipped as a
comment (mid-line comments are not supported — by design, so `http://` in URLs is never broken).
The same applies to single-run recording JSON files.

```json
{
  "title":   "description",
  "setup":   [ ...login through the start screen (once at the beginning)... ],
  "loop":    [ ...steps for one item ({{column_name}} is filled from the row)... ],
  "recover": [ ...steps to get back to the start screen after a failure (optional)... ],
  "teardown":[ ...logout etc. (once at the end, optional)... ]
}
```

- **Notes / milestone display**: put a **comment step** such as
  `{"type":"comment","text":"Accepting PO {{発注番号}}"}` and it is shown in the run log as 💬
  without touching the browser (`{{column}}` substitution works too). Handy for showing
  "what is happening now" during headless runs.
- **Evidence capture**: place `{"type":"screenshot","name":"{{プロジェクト番号}}__{{発注番号}}","full_page":false}`
  inside `loop` to save the screen at that point. A timestamp is appended automatically, so files are
  named "**project__po-number__timestamp.png**" — matching a typical evidence naming rule.
- **Placeholders work inside selectors too**: e.g. `"selectors": [["aria/{{発注番号}}"]]` clicks the PO-number
  link that appeared in the search results, keyed by the row's value (no dependence on row position).
- **`loop` must start and end on the same screen**: finish each item with "return to home" style steps so the
  next item starts from the same screen (loop invariant). Put the shortest way back into `recover`.

### 📊 Detail file (--details)

- **CSV recommended** (save from Excel as "**CSV UTF-8**"). Row 1 = column names, rows 2+ = data.
  **Column names become `{{keys}}`** (Japanese column names are fine: `{{プロジェクト番号}}`).
- Reading `.xlsx` directly is also supported (requires `pip install openpyxl`; the first sheet is read).
  Numbers are converted safely (no `900000000001.0`), dates become `YYYY-MM-DD`.
- **ID column**: defaults to the first column (change with `--id-column`). Progress, results and re-runs
  are keyed by this value. In the example below the **project number** is the ID (matching an operation
  that manages items by project number). Put a **column that is unique per row** first.
- **skip column**: any row with something in the `skip` column is skipped without being executed
  (express "not this time" without deleting the row).

```csv
プロジェクト番号,発注番号,skip
PM9000000001,900000000001,
PM9000000002,900000000002,
PM9000000003,900000000003,1   ← rows with a value in skip are skipped
```

### 📈 Progress, results, re-runs

- While running, the count and ID are shown live, e.g. `[3/37] PM9000000003 開始` (visible even in
  headless mode). The full log is also saved to `output/batch_YYYYMMDD_HHMMSS.log`.
- **One failure does not stop the batch** (default). On failure a screenshot (`fail_<ID>_timestamp.png`)
  and the page state (same-name .txt) are saved automatically, `recover` returns to the start screen,
  and the next item proceeds. Use `--stop-on-error` to stop at the first failure.
- At the end a result CSV `output/batch_result_YYYYMMDD_HHMMSS.csv` (ID, result, reason, evidence) is
  written and a summary such as "37 items: 35 ok / 2 failed / 0 skipped" is printed.
- **Re-run failures only**: `--retry-from output/batch_result_….csv` (re-runs just the failed rows of a
  result CSV). For specific items use `--only PM9000000003,PM9000000005`. For a trial run use `--max-items 3`.

> **⚠️ Beware of double registration when re-running write operations**: a "failure" may actually have
> registered successfully and only the verification step failed. Check the failure screenshots
> (fail_*.png) before re-running.

### 🧪 Try it without a real system (practice-site batches)

A batch definition and details for the bundled practice site (`test_site/edi/`) are included. It processes
4 rows (1 of them skipped) in a row and saves evidence files like `K001__2026-01_timestamp.png`.

```powershell
# 1) Serve the practice sites (separate terminal)
cd test_site
python -m http.server 8000

# 2) Run the batch (4 items: 3 ok / 1 skipped means success)
$env:MY_USERNAME="demo"; $env:MY_PASSWORD="password123"
python run_batch.py --batch recordings/edi_practice_batch.json --details data/edi_practice_batch.csv --engine playwright --browser edge --no-headless
```

**An Oracle-style (tab-navigation, PO acknowledgment) practice site is also bundled** — `test_site/edi2/`
reproduces the iSupplier-Portal-style flow (login → navigator → Orders → advanced search → accept →
submit → confirmation → back to home) with **the same element IDs as the real EBS**
(`#usernameField`, `#POS_ORDERS`, `#SrchBtn`, `#Value_0`, `#ActionGoBtn`, `#PosSubmitBtn`, result link
`#N58:PosPoNumber:0`). The definition is nearly identical to the production batch except for the URL, so
you can **rehearse before access to the real system is granted**. Evidence is saved as
"project__po-number__timestamp.png", and selector placeholders (`aria/{{発注番号}}`) plus Japanese CSV
column names are exercised too.

```powershell
# EDI2 (Oracle-style) practice batch (4 items: 3 ok / 1 skipped; evidence like PM9000000001__900000000001_timestamp.png)
$env:MY_USERNAME="demo"; $env:MY_PASSWORD="password123"
python run_batch.py --batch recordings/edi2_practice_batch.json --details data/edi2_practice_batch.csv --engine playwright --browser edge --no-headless --viewport-shot
```

---

## 🏢 For locked-down workplaces (PAD + WebDriver)

If you cannot install Python on the work PC, **the same batch operation can be built with Power Automate
Desktop (PAD) alone**. PAD's web automation normally needs a browser extension, but **WebDriver has nothing
to do with that extension**: `msedgedriver.exe` itself runs as a local HTTP server, so driving it from PAD's
"Invoke web service" action lets you **control the browser with no extension at all**.

- Reading details, looping, skip handling, progress, result CSV, evidence screenshots → **native PAD actions**
- Browser operations → **HTTP to WebDriver** (element lookup and actions are unified into one
  `/execute/sync` JavaScript call)

The build guide is in **[docs/PAD_WebDriver.md](docs/PAD_WebDriver.md)** (only 5 HTTP calls are needed,
plus the shared JavaScript, flow structure and troubleshooting). The document is written in Japanese.

At home you can verify the exact same sequence with a **reference implementation that sends the same HTTP
calls in the same order** as PAD would (standard library only — no Selenium, no Playwright), and export that
sequence as the PAD guide:

```powershell
# in another terminal: msedgedriver.exe --port=9515
python pad_webdriver_ref.py --batch recordings/edi2_practice_batch.json --details data/edi2_practice_batch.csv --trace output/pad_trace.md
```

Adding `--robin` also generates **Robin code you can paste straight into PAD** (Robin is the language PAD
flows are actually written in), so you do not have to place actions one by one: `{{column}}` becomes
`%Row['column']%` and `{{SECRET:…}}` becomes a credential-variable reference. Swap the batch definition JSON
and you get the flow for that workflow. The practice site
`test_site/edi2/index.html` is a **single file, so no Python server is required** — open it via `file:///…`
and use it as a practice target for PAD.

---

## ⚙️ How it works (why it's stable)

1. **Element indexing**: interactive elements on the page get sequential numbers `[0] [1] [2] …`,
   and the list is passed to the LLM. The LLM calls `click_element` / `input_text` by number.
   No guessing of coordinates or selectors → stability.
2. **Current values of inputs**: `get_page_state` also shows each input's "current value",
   so the LLM can verify after typing that the value actually went in.
3. **Key text**: headings, `role=alert`, success messages — text that can't be operated but
   matters for judging the situation — also appear in `state()` (e.g. "登録が完了しました" /
   "Registration completed"). This makes **completion confirmation** reliable.
4. **Timestamped screenshots**: `_YYYYMMDD_HHMMSS` is appended automatically. Each run gets a
   distinct name and **nothing is overwritten** — good for audit trails.
5. **No vision required**: everything above is passed as text, so lightweight local models
   without image recognition can operate the browser.
6. **Page error detection (Playwright)**: JS errors and `console.error` are captured and
   shown in the "注意" (warnings) section of `state()`. The LLM can notice failures and
   decide to retry or abort (the practical benefit of WebDriver-BiDi-style bidirectional
   monitoring, without any extension).
7. **History pruning**: page states from old steps are pruned automatically, preventing
   context overflow (the main cause of local-LLM wandering) and reducing token cost
   (the most recent `AGENT_KEEP_STATES` states are kept; default 3).
8. **API retry**: Anthropic API rate limits (429), overload (529), and similar errors are
   retried automatically with exponential backoff.

---

## 🔒 Handling secrets

Passwords etc. are **never passed to the model**. In instructions and tool arguments you
write `{{SECRET:NAME}}`, and the real value is filled from local environment variables
(`.env` or the MCP `env`). Log output is also masked as `[SECRET:NAME]`.
Do not commit `.env` or config JSON to Git (already covered by `.gitignore`).

**Domain restriction (recommended)**: setting `<NAME>_ALLOWED_DOMAINS` makes that secret
usable only on pages of the specified domains (including subdomains). Since page content
is passed to the LLM, a malicious page could theoretically prompt-inject "type the
password into this form" — with this restriction, input on other sites is rejected at
the browser layer.

```powershell
$env:MY_PASSWORD="your-real-password"
$env:MY_PASSWORD_ALLOWED_DOMAINS="example.co.jp,localhost"   # input is rejected anywhere else
```

---

## ✅ Verified so far

- **CLI / template (Ollama / qwen3:14b)**: completed login → menu → multiple field inputs → submit → timestamped screenshot.
- **Plumbing test `selftest.py`**: **passes on both Selenium and Playwright** (verifies browser-operation health without an LLM).
- **Recorder replay**: verified import, value substitution, and candidate selector resolution with `recordings/test_site.example.json` (`run_recording.py`).
- **Page error detection (Playwright)**: JS errors / `console.error` shown in the "注意" section of `state()`.
- **Batch runner `run_batch.py`**: completed on a real browser against both practice sites
  (frameset-style `edi/` and Oracle-style `edi2/`): 3 ok / 1 skipped, evidence naming, result CSV and
  💬 comment display all confirmed. Failure isolation, recover, `--retry-from`, Japanese column names
  and .xlsx reading pass all mock tests.
- **MCP server**: verified connection from Hermes Agent (NousResearch), tool discovery (9 tools), and `navigate` execution.
- **CI (GitHub Actions)**: on every push, ubuntu runs syntax checks + unit tests, and windows-latest runs the real-Edge selftest (both Selenium and Playwright engines).
- Environment: native Windows 11 + Microsoft Edge and Google Chrome.

---

## ❓ Troubleshooting

- **Driver download fails** … in restricted environments (e.g. corporate), Selenium Manager
  may fail to fetch drivers. Use an internal mirror or manually place msedgedriver/chromedriver
  on PATH (version matching the browser). Playwright with `channel=msedge` often avoids this.
- **Corporate proxy** … set `HTTPS_PROXY` if needed. Exclude localhost with `NO_PROXY=localhost,127.0.0.1`.
- **`Failed to connect to Ollama`** … Ollama isn't running, or localhost is going through the
  proxy. Check with `ollama ps` and set `NO_PROXY`. If on a different port, also set `OLLAMA_HOST`.
- **`llama-server binary not found`** … Ollama's inference engine is missing (incomplete
  install). Reinstall and confirm inference works with `ollama run qwen3:14b "test"`.
- **Repeats the same operation / drifts to other pages / stalls on explanations or confirmations**
  … common with thinking models. Use `OLLAMA_THINK=0`, prefix the request with `/no_think`, and
  state "no confirmation needed — execute with tools now". Use a tool-calling capable model such as `qwen3:14b`.
- **Element not found** … on dynamic pages, refresh with `get_page_state` (the agent does this
  automatically). Playwright's auto-waiting mitigates this.

---

## 📄 License

Released under the [Apache License 2.0](LICENSE). Copyright 2026  Tsuyoshi Iwamoto (Iwamoto-Ai).

---

## 📚 References

- [Model Context Protocol (MCP) official](https://modelcontextprotocol.io/)
- [DOM (Document Object Model)](https://en.wikipedia.org/wiki/Document_Object_Model)
- [Claude Desktop MCP Documentation](https://docs.anthropic.com/en/docs/claude-code/overview)
- [Selenium official](https://www.selenium.dev/)
- [Playwright official](https://playwright.dev/python/)
- [Playwright Codegen (record actions and generate code)](https://playwright.dev/python/docs/codegen)
- [Chrome DevTools Recorder (official)](https://developer.chrome.com/docs/devtools/recorder/reference)
- [@puppeteer/replay (Recorder JSON spec & replay library)](https://github.com/puppeteer/replay)
- [WebDriver BiDi (W3C spec)](https://w3c.github.io/webdriver-bidi/)
- [Ollama official](https://ollama.com/)
- [OpenClaw](https://openclaw.ai/)
- [Hermes Agent (NousResearch)](https://github.com/NousResearch/hermes-agent)
- [Hermes Agent — MCP configuration reference](https://hermes-agent.nousresearch.com/docs/reference/mcp-config-reference)
