# LLM-Browser-Agent (Stand Alone/MCP-Server)

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://www.apache.org/licenses/LICENSE-2.0)
[![Python](https://img.shields.io/badge/Python-3.11%2B-green.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows-blue.svg)](https://github.com/Iwamoto-Ai/LLM-Browser-Agent)
[![MCP](https://img.shields.io/badge/MCP-Compatible-purple.svg)](https://modelcontextprotocol.io/)
[![LLM](https://img.shields.io/badge/LLM-Claude_%7C_Ollama-orange.svg)](https://ollama.com/)

ブラウザを操作する DOM（Document Object Model）ベースの自動化エージェント。ブラウザ操作を録画し再生可能（Google Chrome Recorder使用)　**ログイン・検索・スクショ保存**を
自然言語の指示もできる。**Microsoft Edge（既定）/ Google Chrome 切替**、**WSL 不要のネイティブ Windows 11** 対応。
LLM（頭脳）は **クラウド（Anthropic API）** でも **ローカル（Ollama・API キー不要）** でも動く。

> このツールは「画面を画像で見て操作する」方式ではなく、ページ内の**操作可能な要素に番号を振り、その番号で操作する**
> DOM（Document Object Model）ベースの方式で実現したことにより、画像認識を持たないローカルの軽量 LLM でも安定して動作可能。

---

## ✨ 特徴（できること）
- **無料ソフトウェアでブラウザ操作自動化**: PowerAutomate不要。API キー不要のローカル LLM でも使える。
- **業務フローの自動化**: ログイン → メニュー操作 → 複数項目の入力 → 登録 → 完了画面のスクショ、を自然言語で。
- **サイトごとのテンプレート運用**: 手順（テンプレート）と数値（データ）を分離し、同じ手順を別データで繰り返し実行可能。
- **3 つの実行形態**: 単発 CLI / テンプレート実行 / MCP サーバー（Claude Desktop・OpenClaw・Hermes Agent から会話操作）。
- **2 つの LLM バックエンド**: クラウド（Anthropic API）/ ローカル（Ollama・API キー不要・完全ローカル）。
- **2 つのブラウザエンジン**: Selenium（既定）/ Playwright（auto-waiting で安定、フルページスクショ）。
- **開発ツールが使えない職場向けの逃げ道**: Power Automate Desktop から WebDriver を HTTP で操作し、
  ブラウザ拡張機能なしで同じバッチ運用ができる（[手順書](docs/PAD_WebDriver.md)）。
- **Excel/CSV の明細をバッチ実行**: 数十件の登録・確認を 1 コマンドで繰り返す（進捗表示・結果 CSV・失敗分だけ再実行）。
- **Google Chrome Recorder の録画を決定論リプレイ**: ブラウザ拡張機能不要でブラウザの操作を記録したファイル（JSON）を LLM なしで確実に再生（複雑サイト向け）。
- **秘密情報をモデルに渡さない**: パスワードは `{{SECRET:NAME}}` で参照し、実値は実行時にローカルで補完。
- **証跡に強いスクショ**: 保存名に自動で日時 `_YYYYMMDD_HHMMSS` を付与（上書きされない）。

---

## 🧩 全体像（3 つの軸を組み合わせて使う）

このツールは「**実行形態 × LLM バックエンド × ブラウザエンジン**」の 3 軸を自由に組み合わせます。
どれを選んでも操作の中身（要素番号で操作する仕組み）は同じです。

### 1) 実行形態（どう動かすか）

| 形態 | ファイル | 説明 |
|---|---|---|
| テンプレート実行（推奨） | `run_template.py` | サイトごとの YAML ＋数値 JSON で繰り返し実行。`--backend` / `--engine` で切替 |
| スタンドアロン（単発 CLI） | `agent.py`（クラウド）/ `agent_ollama.py`（ローカル） | 自然言語タスクを 1 回だけ自動実行 |
| MCP サーバー | `mcp_server.py` | Claude Desktop / OpenClaw / Hermes Agent から会話しながら操作 |

### 2) LLM バックエンド（頭脳）

| バックエンド | 必要なもの | 備考 |
|---|---|---|
| Anthropic API（クラウド） | `ANTHROPIC_API_KEY` | 既定。`claude-sonnet-4-6` など。tool 使用が最も確実 |
| Ollama（ローカル LLM） | ローカルの Ollama ＋ tool calling 対応モデル | **API キー不要・完全ローカル**。`--backend ollama` |

### 3) ブラウザエンジン（手足）

| エンジン | 必要なもの | 特徴 |
|---|---|---|
| Selenium（既定） | `selenium` | 実績の既定。`--engine selenium` |
| Playwright | `playwright` | **auto-waiting** で動的ページ・複雑メニューに強い。フルページスクショ。`--engine playwright` |

### 🧭 選び方の目安

- **社内・オフラインで使いたい** → バックエンドは `ollama`（API キー不要）。会社の AI が Copilot 等でも干渉しない。
- **とにかく確実に動かしたい** → バックエンドは `anthropic`（クラウド）。動作基準の確認にも向く。
- **動的ページ・項目が多い・取りこぼしが不安** → エンジンは `playwright`（待機が確実）。
- **まず最小構成で試す** → 既定（Selenium ＋ Anthropic、または Selenium ＋ Ollama）でOK。

---

## 🛠️ セットアップ（ネイティブ Windows 11 / WSL 不要）

1. **Python 3.10+** … python.org のインストーラ（"Add python.exe to PATH" にチェック）
2. **Microsoft Edge** … Windows 11 標準（既定ブラウザ）。Google Chrome を使う場合は別途インストール
3. WebDriver（msedgedriver / chromedriver）は **Selenium Manager が自動取得**（手動導入不要）
4. **（ローカル LLM を使う場合）Ollama** … <https://ollama.com/> から導入し `ollama pull qwen3:14b`
5. **（Playwright を使う場合）** … `pip install playwright`。`channel=msedge` で導入済み Edge を使うため `playwright install` は不要

```powershell
cd C:\path\to\LLM-Browser-Agent
pip install -r requirements.txt
# Excel ファイル（.xlsx）をバッチの明細として直読みしたい場合に必要
pip install openpyxl
# クラウド（Anthropic API）を使う場合のみ:
copy .env.example .env   # ANTHROPIC_API_KEY を記入
# ローカル（Ollama）だけで使うなら API キーは不要
```

---

## ▶️ 使い方

### A. テンプレート運用（推奨）

「ログイン → メニュー → 多数の数値入力 → 登録 → 完了画面スクショ」を、サイトごとに **1 度書いたテンプレートで繰り返す**。
手順（テンプレート）と数値（データ）を分けるのがポイント。

- **テンプレート** `templates/<site>.yaml` … ログイン手順・メニュー操作・入力項目。サイトごとに 1 つ。
- **データ** `data/<run>.json` … 実際に入れる数値。実行ごとに差し替え。値は `{{key}}` で参照。
- パスワード等は `{{SECRET:NAME}}` のまま残り、実行時に環境変数から補完される（プロンプトに実値は載らない）ので安心セキュリティ。

```powershell
# まず生成プロンプトの確認（ブラウザを起動しない）
python run_template.py --template templates/example_site.yaml --values data/example_values.json --dry-run

# クラウド（既定）で実行
python run_template.py --template templates/example_site.yaml --values data/example_values.json --browser edge --no-headless

# ローカル LLM（Ollama）で実行 — API キー不要。安定化の環境変数を併用
$env:OLLAMA_THINK="0"; $env:NO_PROXY="localhost,127.0.0.1"
python run_template.py --template templates/example_site.yaml --values data/example_values.json --backend ollama --model qwen3:14b --browser edge --no-headless

# Playwright エンジンで実行（--engine を足すだけ）
python run_template.py --template templates/example_site.yaml --values data/example_values.json --engine playwright --browser edge --no-headless
```

テンプレートの書き方は `templates/example_site.yaml` を参照（`login` / `navigation` / `fields` / `submit` / `verify` / `screenshot`）。
項目が多いサイトは `fields` に足すだけ。複雑なメニューは `navigation` に自然言語で具体的に書けば LLM が辿る。

**信頼性の工夫（重要）**: 入力欄の現在値が `state()` に出る／完了見出し等の「主なテキスト」も `state()` に出る（後述「仕組み」）。
生成プロンプトは「1 項目ごとに入力 → 現在値を確認 → 全項目を再検証 → 完了を確認してスクショ」という順序を強制する。
`--values` に値の指定漏れがあれば実行前にエラーで止まる。項目が多い場合は `--max-steps` を増やす。

| 🔧 オプション | 既定 | 説明 |
|---|---|---|
| `--template` | （必須） | サイトテンプレート (YAML) |
| `--values` | なし | 入力値 (JSON)。`{{key}}` に埋め込む |
| `--backend` | `anthropic` | `anthropic`（クラウド）/ `ollama`（ローカル） |
| `--engine` | `selenium` | `selenium` / `playwright` |
| `--browser` | `edge` | `edge` / `chrome` |
| `--model` | backend 依存 | 未指定なら anthropic:`claude-sonnet-4-6` / ollama:`qwen3:14b` |
| `--max-steps` | `40` | 項目数に応じて増やす（目安: 項目数 × 3 + 10） |
| `--dry-run` | — | 生成プロンプトの確認のみ |
| `--no-headless` | （headless） | ブラウザを表示 |

### B. スタンドアロン（単発 CLI）

```powershell
# クラウド（Anthropic API）
python agent.py --task "ユーザー名 {{SECRET:MY_USERNAME}} とパスワード {{SECRET:MY_PASSWORD}} でログインし、'MCP server' を検索して result.png に保存して" --start-url example.com --browser edge --no-headless

# ローカル LLM（Ollama）— API キー不要
python agent_ollama.py --task "..." --start-url example.com --model qwen3:14b --browser edge --no-headless

# Chrome / Playwright への切替も同様（--browser chrome / --engine playwright）
```

### C. MCP サーバー（Claude Desktop / 🦞OpenClaw / 🟣Hermes Agent）

会話の中で「○○にログインして△△を登録しスクショを取って」と頼むと、ホスト側 LLM が下記ツールを呼ぶ:
`open_browser` / `navigate` / `get_page_state` / `click_element` / `input_text` / `send_keys` / `scroll` /
`take_screenshot` / `close_browser`。`take_screenshot` は保存に加え画像をホストにも返す。API キーは不要。

MCP サーバーは環境変数で挙動を切り替える: `BROWSER_AGENT_ENGINE`(selenium/playwright) / `BROWSER_AGENT_BROWSER`(edge/chrome) /
`BROWSER_AGENT_HEADLESS`(0/1) / `BROWSER_AGENT_OUTPUT`(スクショ保存先)。ログイン情報は `env` に置き `{{SECRET:NAME}}` で参照。

#### Claude Desktop（Windows）

`%APPDATA%\Claude\claude_desktop_config.json` に追記（`claude_desktop_config.example.json` 参照）:

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

保存して Claude Desktop を再起動すると `browser-agent` のツールが現れる。Playwright を使うなら
`BROWSER_AGENT_ENGINE` を `playwright` に。`uv` 派なら `"command": "uv", "args": ["run", "mcp_server.py"]` でも可。

#### 🦞OpenClaw

`mcp.servers` に同様のエントリ（`command` / `args` / `env`）を追加するか
`openclaw mcp set browser-agent -- python C:\path\to\mcp_server.py` で登録する。

#### 🟣 Hermes Agent（NousResearch）

Hermes はローカル LLM（Ollama）でも動く自律エージェントで、MCP クライアント機能を内蔵（stdio・HTTP 対応）。
MCP 対応が未導入なら `cd ~/.hermes/hermes-agent && uv pip install -e ".[mcp]"`。
`~/.hermes/config.yaml` の `mcp_servers:` に登録（起動時に自動でツール検出）。

```yaml
mcp_servers:
  browser-agent:
    command: "python"
    args: ["/path/to/LLM-Browser-Agent/mcp_server.py"]
    env:
      BROWSER_AGENT_ENGINE: "selenium"   # selenium / playwright
      BROWSER_AGENT_BROWSER: "edge"    #  edge / chrome 
      BROWSER_AGENT_HEADLESS: "0"
      BROWSER_AGENT_OUTPUT: "/path/to/output"   # スクショ保存場所
      MY_USERNAME: "your-login-id"
      MY_PASSWORD: "your-password"
    enabled: true
    timeout: 120
```

登録後、ツールは衝突回避のため `mcp_<サーバー名>_<ツール名>`（例 `mcp_browser-agent_navigate`）として見える。
`hermes mcp list` で登録確認、`hermes mcp test browser-agent` でツール検出を確認できる。Hermes に
「http://localhost:8000 にログインして経費を登録し完了画面を保存して」のように依頼すると操作する。

> **WSL の Hermes から Windows の Edge を操作する場合**: `command` を Windows の Python
> （例 `/mnt/c/Users/<you>/AppData/Local/Programs/Python/Python3xx/python.exe`）にし、`args` のスクリプトと
> `env` のパスも Windows 形式（`C:\\...`）で渡す。Hermes は `/mnt/c/...` 配下から起動するのが推奨。
> WSL 内で完結させるなら Linux 版ブラウザが必要。
>
> **ローカル LLM が「説明・確認」で止まり操作しない場合**: 依頼文の冒頭に `/no_think` を付け、WSL 側で
> `export OLLAMA_THINK=0` を設定する。さらに「確認は不要。今すぐツールで最後まで実行」と明示すると安定する。

---

## 🦙 ローカル LLM (Ollama) のコツ

API を使えない環境（社内など）向けに、頭脳をローカルの Ollama に差し替えられる。挙動はクラウド版と同じ。

```powershell
ollama pull qwen3:14b              # 推奨（14B・マルチステップ操作で安定）
# ollama pull qwen3.5:9b           # 軽量代替（9B）

$env:OLLAMA_THINK="0"                 # 思考オフで徘徊を抑制（qwen3 等の思考型に有効）
$env:NO_PROXY="localhost,127.0.0.1"   # localhost をプロキシ除外（接続エラー対策）
python agent_ollama.py --task "..." --model qwen3:14b --browser edge --no-headless
```

**⚠️ 重要**
- **マルチステップのフォーム操作では tool calling 機能が優れたモデルを選ぶこと。** 
- **`OLLAMA_THINK=0`**: 思考が長いと同じ操作を繰り返したり別ページを探しに行くことがある。思考オフで決断的になる。
- **`NO_PROXY=localhost,127.0.0.1`**: `Failed to connect to Ollama` の定番対策（クライアントが localhost をプロキシ経由にするのを防ぐ）。
- **vision 不要**: 要素はインデックス（テキスト）で渡すため、画像認識のないモデルでも操作できる。
- `OLLAMA_HOST` … 既定 `http://localhost:11434`。リモートの Ollama を使う場合に指定。

---

## 🎭 ブラウザエンジン（Selenium / Playwright）

`--engine`（CLI）/ `BROWSER_AGENT_ENGINE`（MCP）で切替。両者は同一インターフェースなので出力・挙動は揃う。

- **Selenium（既定）**: 実績の既定。WebDriver は Selenium Manager が自動取得。
- **Playwright**: **auto-waiting** で要素が操作可能になるまで自動待機するため、動的ページ・複雑メニューでの
  取りこぼしが減る。フルページのスクショが標準。
- **速度より安定性**: LLM 駆動では全体時間の支配項は LLM 推論なので、エンジン間の速度差は体感しにくい。
  Playwright の利点は速さより「待機の確実さ」。
- **MCP との両立**: Playwright の同期 API は asyncio（非同期） 上で動かせないが、本実装は Playwright を**専用スレッド**で
  駆動し同期インターフェースで包むため、MCP サーバー（`BROWSER_AGENT_ENGINE=playwright`）でも動く。

```powershell
python run_template.py --template templates/test_site.yaml --values data/test_values.json --engine playwright --browser edge --no-headless
python test_site/selftest.py --engine playwright --browser edge --no-headless
```

---

## 🧪 ローカルでテストする

実サイトに触れる前に、付属の**ローカルテストサイト**で一連の流れを確認できる。`test_site/index.html` は
サーバー不要の単体 HTML で、ログイン・メニュー・経費登録フォーム・登録完了画面を再現する
（デモ資格情報: `demo` / `password123`）。


```powershell
# 1) テストサイトを配信（別ターミナルで）
cd test_site
python -m http.server 8000      #  → http://localhost:8000
```

```powershell
# 2-A) LLM なしの配管テスト（最初の切り分け用・推奨）
#      browser だけでサイトを操作し、日時付きスクショが output/ に出れば成功
python test_site/selftest.py --browser edge --no-headless
python test_site/selftest.py --engine playwright --browser edge --no-headless   # Playwright でも
```

```powershell
# 2-B) エージェント経由のテスト（テンプレート運用）
$env:MY_USERNAME="demo"; $env:MY_PASSWORD="password123"
$env:OLLAMA_THINK="0"; $env:NO_PROXY="localhost,127.0.0.1"
python run_template.py --template templates/test_site.yaml --values data/test_values.json --backend ollama --model qwen3:14b --browser edge --no-headless
```

`selftest.py` は LLM もネットワークも使わず browser 層だけでサイトを操作するので、**まずこれが通るか**で
「ブラウザ操作の配管」と「LLM の判断」を切り分けられる。成功するとスクショ`output/test_selftest_YYYYMMDD_HHMMSS.png` が保存される。

---

## 🎥 Google Chrome の Recorder でブラウザ操作を録画 → 決定論リプレイ（拡張機能不要）

複雑なメニュー・項目数が多いサイトでは、LLM に毎回判断させるより、**人が一度操作して録画した手順を
そのまま再生する**ほうが確実。Chrome 内の DevTools には **Recorder** が標準で内蔵されており、
記録した操作を **JSON でエクスポート**できる。このツールはその JSON を読み込み、**LLM なしで決定論的に再生**する。

**⚠️ 注意**
> Chrome Recorder の「Playwright 形式エクスポート」を使う場合は Chrome 拡張機能が必要となる（社内では使えないことが多い）
> 本ツールは標準エクスポート形式の**「JSON file」形式**を直接再生するので Chrome 拡張機能不要。（Chrome 101 以降）
> 録画を Chrome で行い再生を Edge で行う場合でも基本は同じDOMなので動きますが、もし対象サイトがブラウザ判定で表示内容を変えるようなら、再生も Chrome ですること。

**🎥 手順**
1. Chrome ブラウザで録画したい Web サイトを開く。ページ内で**右クリック**するとメニューが表示されるので、
   1番下の「**検証**」をクリックして DevTools を開く。
2. 上部の「Elements」がある行の右端、「Network」の右の「**>>**」をクリックし、表示されたメニューの
   1番下の「**Recorder**」をクリック。
3. **Recorder** パネルが開くので、右に表示された「**Create a new recording**」をクリック。
4. 録画名などを指定する（デフォルトのままでも良い）。
5. 下のほうに赤い〇ボタン「Start recording」をクリックすると録画が始まり、もう一度〇ボタンをクリックすると「End recording」となり録画が停止する。
6. 録画ファイル名の右に「↑インポート」と「↓エクスポート」があるので「↓エクスポート」をクリック。表示されたメニューの「JSON」を選択し「**JSON file**形式」でエクスポートする。　
7. エクスポートしたJSONファイルを`recordings/<name>.json` に保存。
8. エクスポートした JSON の `change` ステップの `value` を、可変の数値は `{{key}}`、ログインID・パスワードは
   `{{SECRET:NAME}}` に書き換える（JSON は人間可読・再インポート可）。
   
   > **⚠️ 重要（セキュリティ）**: 録画直後の JSON には、録画中に入力した**実値（IDやパスワード）がそのまま残る**。
   > 保存・コミット・共有の前に、必ず `{{SECRET:NAME}}`（秘密）/ `{{key}}`（可変データ）へ置き換えること。
   > 実値は `.env` や環境変数（`MY_USERNAME` / `MY_PASSWORD` など）に置き、JSON には残さない。

9. 再生する:

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

- **決定論的**: 記録した手順をそのまま実行するので、複雑サイトでもブレない（LLM 不要）。
- **データ差し替え**: `value` の `{{key}}` を `--values` の JSON で埋め込み、同じ録画を別データで繰り返せる。
- **秘密情報**: `{{SECRET:NAME}}` は実行時に環境変数から補完（JSON にも画面にも実値は出ない）。
- **エンジン**: 既定は `playwright`（Recorder の css/xpath/text/aria/pierce セレクタと相性が良い）。`--engine selenium` も可。
- **録画の手直し（任意）**: Recorder は入力前のクリックも記録するが、本ツールは `change` だけで入力できるため、
  エクスポート後に不要な重複ステップは消してよい（`setViewport` などは再生時に自動スキップ）。
- **iframe（フレーム）対応**: 録画の `frame` 指定に追従して、その iframe 内の要素を操作する。
  指定は **インデックス**（`"frame": [2]`＝Chrome Recorder 由来）でも、**フレーム名**（`"frame": "content"`＝
  Playwright Codegen 由来）でも可。名前指定はフレームの並び順が変わっても壊れにくく、より堅牢。
  指定フレームで見つからない場合は**全フレームを横断**して探す（参照パネル等の取りこぼしに強い）。
  フレームを多用するサイト（フレームセット型の業務システム等）は **`--engine playwright` を推奨**
  （Selenium は指定フレーム＋最上位フォールバックのみの簡易対応。名前指定は name か id で切替）。
- **ポップアップ（別ウィンドウ）対応**: カレンダー等が別ウィンドウで開くサイトにも対応（`target` が URL のステップ）。
  Playwright は全ウィンドウ×全フレームを横断、Selenium はウィンドウ切替で best-effort 対応する。
  ただし**ポップアップ選択より「直接入力」のほうが安定**するため、可能なら入力欄に直接値を入れる録画に手直しすると確実
  （例: 年月欄に `{{yyyymm}}` を `change` するだけにして、参照ボタン以降のステップを削除）。
- **`--max-steps N`**: 先頭から N ステップだけ実行する。録画末尾の Logout などを止めて、目的の画面で
  スクショを撮りたいときに使う（例: ログイン〜照会まで実行して止める）。
- **スクショの向き**: 録画の `setViewport`（ウィンドウ幅×高さ）を反映するので、録画時の見た目に近い形で保存される。
  さらに `--viewport-shot` を付けると、ページ全体ではなく**表示領域だけ（横長）**を撮る。
- 値の指定漏れがあれば実行前にエラーで止まる。付属の `recordings/test_site.example.json` で今すぐ試せる。

> **使い分け**: 毎回手順が決まっている定型業務は **録画リプレイ（確実）**、画面差異や判断が要る作業は
> **LLM 駆動（テンプレート運用）** が向く。両者は同じ `browser` 層を共有する。

### 🧪 実環境がなくても試せる：ローカル練習サイト（iframe＋ポップアップ）

実際の業務システムにアクセスできなくても、**iframe（フレームセット）と別ウィンドウのカレンダーを備えた
練習用ダミーサイト**を同梱しているので、frame 対応・ポップアップ対応の動作確認がローカルだけで完結する
（社名・実 URL・実データは一切含まない練習専用ページ）。

構成は実在の業務システムによくある形を模した、ログイン → フレームセット（メニュー＝frame[0] ／ 検索フォーム＝frame[2]）
→ 年月欄（直接入力または「参照」で別ウィンドウのカレンダー）→ 検索 → 結果、という流れ。

```powershell
# 1) サイトを配信（別ターミナル。test_site をルートに配信）
cd test_site
python -m http.server 8000      #  → 練習サイト: http://localhost:8000/edi/index.html （demo / password123）
```

```powershell
# 2) デモ資格情報を環境変数に（録画は {{SECRET:...}} を使うため実値はここで補完）
$env:MY_USERNAME="demo"; $env:MY_PASSWORD="password123"
```

```powershell
# 3-A) 直接入力版（年月を直接入力 → 検索）: iframe 横断の確認
python run_recording.py --recording recordings/edi_practice_direct.json --values data/edi_practice_values.json --engine playwright --browser edge --no-headless
```

```powershell
# 3-B) ポップアップ版（参照 → 別ウィンドウのカレンダーで 05月 → 検索）: iframe＋別ウィンドウの確認
python run_recording.py --recording recordings/edi_practice_popup.json --values data/edi_practice_values.json --engine playwright --browser edge --no-headless
```

```powershell
# 3-C) フレーム名指定版（frame を "menu"/"content" の名前で指定）: Codegen 由来の名前指定の確認
python run_recording.py --recording recordings/edi_practice_named.json --values data/edi_practice_values.json --engine playwright --browser edge --no-headless
```

- **直接入力版**で `frame[0]`（メニューの検収照会）と `frame[2]`（年月入力・検索）の **iframe 横断**を確認できる。
- **ポップアップ版**で、別ウィンドウのカレンダーへ切り替えて「05月」を選び、親フレームの年月欄へ反映される
  **ポップアップ対応**を確認できる。`ログ`に `クリック: ...（frame=[2]）` や `（..., popup）` が出る。
- 実行後、結果画面（`検収照会 結果（練習）`）が日時付きスクショ（`output/recording_done_*.png`）に保存される。
- ポップアップを多用するサイトは **`--engine playwright` を推奨**（Selenium は best-effort）。

> この練習サイトで「frame／popup を含む録画リプレイ」が通ることを確認しておけば、実環境が用意できたときに
> 同じ手順（録画 → JSON → `run_recording.py`）でそのまま本番へ移行できる。

### 🧭 Playwright Codegen をセレクタ・フレーム名の調査に使う

Playwright には操作を記録して**Playwright コード**を生成する [Codegen](https://playwright.dev/python/docs/codegen) がある。
Chrome Recorder（JSON）より**壊れにくいセレクタ**（`get_by_role`／`get_by_label` など意味ベース）と、
**フレーム名**（`frame[name="content"]`）を教えてくれるので、**録画 JSON を書くときの「調査・下書き」ツール**として有用。

```powershell
# 練習サイトを配信した状態で（別ターミナル）:
python -m playwright codegen http://localhost:8000/edi/index.html
```

ブラウザと Inspector が開き、操作するとコードが生成される。例（抜粋）:

```python
page.get_by_role("button", name="Login").click()
page.locator("frame[name=\"menu\"]").content_frame.get_by_role("link", name="検収照会").click()
with page.expect_popup() as p:                    # ← 参照ボタンでカレンダーが別ウィンドウで開く
    page.locator("frame[name=\"content\"]").content_frame.get_by_role("button", name="参照").click()
page.locator("frame[name=\"content\"]").content_frame.locator("#yyyymm").fill("2026-05")
```

この出力から、本ツールの録画 JSON を書くと安定する。対応づけの目安:

| Codegen の出力 | 本ツールの録画 JSON |
|---|---|
| `page.goto("...")` | `{"type":"navigate","url":"..."}` |
| `get_by_role("button", name="Login").click()` | `{"type":"click","selectors":[["aria/Login"],["text/Login"]]}` |
| `get_by_label("年月").fill("2026-05")` | `{"type":"change","value":"{{yyyymm}}","selectors":[["aria/年月"]]}` |
| `frame[name="content"].content_frame...` | 同ステップに `"frame": "content"` を付ける（**名前指定**） |
| `with page.expect_popup(): ...` の中の別ウィンドウ操作 | `"target": "<ポップアップURL>"` を付ける |

- **フレームは名前で指定できる**（`"frame": "content"`）。Codegen が示す name をそのまま使えるので、
  インデックス（`[2]`）より堅牢。付属の `recordings/edi_practice_named.json` が名前指定の実例。
- **秘密情報に注意**: Codegen 出力にも入力した実 ID・パスワードが平文で載る。JSON へ写す際は必ず
  `{{SECRET:NAME}}` に置き換え、可変値は `{{key}}` にする（Recorder と同じ運用）。
- Codegen は「調査・下書き」に使い、実行は本ツールの JSON リプレイ（秘密情報マスク・値の差し替え・
  日時スクショ・エンジン切替つき）で行うのが、統一運用としておすすめ。





---

## 🔁 バッチ実行（Excel/CSV の明細を数十件まとめて処理）

実務では 1 件ずつではなく「**数十件をまとめて登録・確認**」が普通。`run_batch.py` は、Excel/CSV の明細を
1 行 = 1 件として、録画リプレイの手順を**件数分だけ確実に繰り返す**実行層（LLM 不要）。
ループ・進捗表示・エラー処理・再実行はこの層が引き受けるため、テンプレート（録画）はシンプルなまま保てる。

```powershell
python run_batch.py --batch recordings/edi_practice_batch.json --details data/edi_practice_batch.csv --engine playwright --browser edge --no-headless
```

### 📄 バッチ定義 JSON（setup / loop / recover / teardown）

手順を「1 回だけ」と「明細ごとに繰り返す」に分けて書く。ステップは Chrome Recorder 形式そのまま。
**コメントも書ける**: 行の先頭（空白可）が `//` か `#` の行はコメントとして読み飛ばされる
（行の途中のコメントは不可 — URL の `http://` を壊さないための仕様）。単発リプレイ用の録画 JSON でも同様に使える。

```json
{
  "title":   "説明",
  "setup":   [ …ログイン〜開始画面まで（最初に 1 回）… ],
  "loop":    [ …明細 1 件分の手順（{{列名}} が行の値で埋まる）… ],
  "recover": [ …失敗時に開始画面へ戻る手順（任意）… ],
  "teardown":[ …ログアウト等（最後に 1 回。任意）… ]
}
```

- **手順メモ／節目の表示**: `{"type":"comment","text":"発注 {{発注番号}} の受諾を開始"}` という
  **comment ステップ**を置くと、ブラウザ操作なしで実行ログに 💬 として表示される（`{{列名}}` も使える）。
  headless 実行時に「いま何をしているか」を見せる進捗の節目としても便利。
- **エビデンス保存**: `loop` の中に `{"type":"screenshot","name":"{{プロジェクト番号}}__{{発注番号}}","full_page":false}`
  を置くと、その時点の画面を保存する。日時は自動付与されるので、保存名は
  「**プロジェクト番号__発注番号__日時.png**」の形式になる（証跡の命名規則にそのまま合う）。
- **セレクタにも {{列名}} が使える**: 例 `"selectors": [["aria/{{発注番号}}"]]` で、検索結果に出た
  発注番号リンクを行の値で特定できる（行位置に依存しない）。
- **`loop` の始点と終点は同じ画面に**: 1 件処理の最後に「ホームへ戻る」等を入れて、次の件が同じ画面から
  始まるようにする（ループ不変条件）。`recover` には失敗時にその画面へ戻る最短手順を書く。

### 📊 明細ファイル（--details）

- **CSV 推奨**（Excel で「**CSV UTF-8**」として保存 → そのまま読める）。1 行目 = 列名、2 行目以降 = データ。
  **列名がそのまま `{{キー}}`** になる（日本語列名も可: `{{プロジェクト番号}}`）。
- `.xlsx` の直読みも可（`pip install openpyxl` が必要。先頭シートを読む）。
  数値は `900000000001.0` にならないよう整数化、日付は `YYYY-MM-DD` に整形される。
- **ID 列**: 既定は先頭列（`--id-column` で変更可）。進捗・結果・再実行はこの値で扱う。
  上の例では**プロジェクト番号**が ID になる（案件をプロジェクト番号で管理している運用に合わせた並び）。
  **行ごとに一意な列**を先頭に置くこと。
- **skip 列**: `skip` 列に何か入っている行は実行せずスキップ（行を消さずに「今回は流さない」を表現できる）。

```csv
プロジェクト番号,発注番号,skip
PM9000000001,900000000001,
PM9000000002,900000000002,
PM9000000003,900000000003,1   ← skip に値がある行は飛ばす
```

### 📈 進捗・結果・再実行

- 実行中は `[3/37] PM9000000003 開始` のように**件数と ID を逐次表示**（headless でも見える）。
  全ログは `output/batch_YYYYMMDD_HHMMSS.log` にも保存される。
- **1 件の失敗では止まらない**（既定）。失敗時はその場のスクショ（`fail_<ID>_日時.png`）と
  画面状態（同名 .txt）を自動保存し、`recover` で開始画面へ戻って次の件へ進む。
  最初の失敗で止めたい場合は `--stop-on-error`。
- 終了時に `output/batch_result_YYYYMMDD_HHMMSS.csv`（ID・結果・理由・エビデンス）を出力し、
  「37 件中 成功 35 / 失敗 2 / スキップ 0」のように要約する。
- **失敗分だけ再実行**: `--retry-from output/batch_result_….csv`（結果 CSV の失敗行だけを流し直す）。
  特定の件だけなら `--only PM9000000003,PM9000000005`。お試しは `--max-items 3`。

> **⚠️ 登録系の再実行は二重登録に注意**: 「実は登録は成功していたが確認段階で失敗扱いになった」ケースが
> 混ざり得る。再実行の前に、失敗時スクショ（fail_*.png）で実際の画面を確認してから流すこと。

### 🧪 実環境がなくても試せる（練習サイトでバッチ体験）

付属の練習サイト（`test_site/edi/`）に対するバッチ定義と明細を同梱している。明細 4 行
（うち 1 行は skip）を連続処理し、`K001__2026-01_日時.png` のようなエビデンスが件数分保存される。

```powershell
# 1) 練習サイトを配信（別ターミナル）
cd test_site
python -m http.server 8000    #  → 練習サイト: http://localhost:8000/edi2/index.html （demo / password123）
```

```powershell
# 2) バッチ実行（4 件: 成功 3 / スキップ 1 になれば OK）
$env:MY_USERNAME="demo"; $env:MY_PASSWORD="password123"
python run_batch.py --batch recordings/edi_practice_batch.json --details data/edi_practice_batch.csv --engine playwright --browser edge --no-headless
```

**Oracle 型（タブ遷移・発注確認）の練習サイトも同梱** — `test_site/edi2/` は iSupplier Portal 風の
画面遷移（ログイン → ナビゲータ → 発注 → 拡張検索 → 受理 → 発行 → 確認完了 → ホームへ戻る）を、
**実 EBS と同じ要素 ID**（`#usernameField`・`#POS_ORDERS`・`#SrchBtn`・`#Value_0`・`#ActionGoBtn`・
`#PosSubmitBtn`・検索結果リンク `#N58:PosPoNumber:0`）で再現している。本番バッチと URL 以外ほぼ同一の
定義で検証できるため、実環境の許可が下りる前の**予行演習**に使える。エビデンスは
「プロジェクト番号__発注番号__日時.png」で保存され、セレクタ内プレースホルダ（`aria/{{発注番号}}`）や
日本語列名の CSV もこの練習で確認できる。

```powershell
# EDI2（Oracle 型）練習バッチ（4 件: 成功 3 / スキップ 1。エビデンス例 PM9000000001__900000000001_日時.png）
$env:MY_USERNAME="demo"; $env:MY_PASSWORD="password123"
python run_batch.py --batch recordings/edi2_practice_batch.json --details data/edi2_practice_batch.csv --engine playwright --browser edge --no-headless --viewport-shot
```

---

## 🏢 開発ツールが使えない環境向け（PAD ＋ WebDriver）

会社の PC に Python を入れられない場合でも、**Power Automate Desktop（PAD）だけで同じバッチ運用ができる**。
PAD の Web 自動化は専用のブラウザ拡張機能を必要とするが、**WebDriver は拡張機能とは無関係**で、
`msedgedriver.exe` 自体がローカルの HTTP サーバーとして動くため、PAD の「Web サービスの呼び出し」から
HTTP で指示すれば**拡張機能なしでブラウザを操作できる**。

- 明細の読み込み・ループ・skip 判定・進捗・結果 CSV・エビデンスのスクショ → **PAD の標準アクション**
- ブラウザ操作 → **WebDriver へ HTTP**（要素の特定と操作は `/execute/sync` の JavaScript に一本化）

組み立て手順は **[docs/PAD_WebDriver.md](docs/PAD_WebDriver.md)** にまとめてある
（使う HTTP 呼び出しは 5 種類だけ・共通 JavaScript・フロー構成・トラブルシュート）。

自宅では、**PAD が送るのと同じ HTTP 呼び出しを同じ順序で送る参照実装**で動作を確認し、
その呼び出し列を PAD 用の手順書として書き出せる（Selenium も Playwright も使わない標準ライブラリのみ）。

```powershell
# 別ターミナルで: msedgedriver.exe --port=9515
python pad_webdriver_ref.py --batch recordings/edi2_practice_batch.json --details data/edi2_practice_batch.csv --trace output/pad_trace.md
```

さらに `--robin` を付けると、**PAD にそのまま貼り付けられる Robin コード**（PAD のフローの実体）を生成する。
アクションを 1 つずつ手で置く必要はなく、`{{列名}}` は `%Row['列名']%` へ、`{{SECRET:…}}` は資格情報変数の参照へ
自動変換される。バッチ定義 JSON を差し替えれば、その業務のフローがそのまま生成される。
練習サイト `test_site/edi2/index.html` は**単一ファイルなので Python のサーバー不要**で、
`file:///…` で開いて PAD の練習台にできる。

---

## ⚙️ 仕組み（なぜ安定するか）

1. **DOM（Document Object Model）ベースで要素インデックス方式**: ページ上の操作可能な要素に連番 `[0] [1] [2] …` を振り、その一覧を LLM に渡す。
   LLM は番号で `click_element` / `input_text` を呼ぶ。座標やセレクタを推測させないので安定する。
2. **入力欄の現在値**: `get_page_state` には各入力欄の「現在値」も出る。入力後に値が入ったかを LLM が検証できる。
3. **主なテキスト**: 見出し・`role=alert`・成功メッセージ等の「操作はできないが状況判断に重要なテキスト」も
   `state()` に出る（例:「登録が完了しました」）。これにより**完了確認**が確実になる。
4. **日時付きスクショ**: 保存名の末尾に `_YYYYMMDD_HHMMSS` を自動付与。毎回別名で**上書きされない**ため証跡に向く。
5. **vision 不要**: 上記はすべてテキストで渡るため、画像認識のないローカル軽量モデルでも操作できる。
6. **ページエラー検知（Playwright）**: JS エラーや `console.error` を捕捉し、`state()` の「注意」欄に出す。
   LLM が失敗に気づいてリトライ・中断を判断できる（WebDriver BiDi 的な双方向監視の実利を拡張機能なしで実現）。

---

## 🔒 秘密情報の扱い

- パスワード等は **モデルに渡さない**。指示やツール引数では `{{SECRET:NAME}}` と書き、実際の値は
ローカル（`.env` または MCP の `env`）の環境変数から補完される。ログ表示も `[SECRET:NAME]` にマスクされる安全設計。
- `.env` と設定 JSON は Git にコミットしないこと（`.gitignore` 済み）。

---

## ✅ 動作確認状況

- **CLI / テンプレート（Ollama / qwen3:14b）**: ログイン → メニュー → 複数項目入力 → 登録 → 日時付きスクショまで完走。
- **配管テスト `selftest.py`**: **Selenium / Playwright とも完走**（LLM なしでブラウザ操作の健全性を確認）。
- **Recorder リプレイ**: `recordings/test_site.example.json` で取り込み・値の埋め込み・候補セレクタ解決を確認（`run_recording.py`）。
- **ページエラー検知（Playwright）**: JS エラー / `console.error` を `state()` の「注意」欄に表示。
- **バッチ実行 `run_batch.py`**: 練習サイト 2 種（フレームセット型 `edi/`・Oracle 型 `edi2/`）で
  **実ブラウザ完走**（成功 3 / スキップ 1、エビデンス命名・結果 CSV・💬 コメント表示まで確認）。
  失敗隔離・recover・`--retry-from`・日本語列名・.xlsx 読込はモックで全テスト合格。
- **MCP サーバー**: Hermes Agent（NousResearch）から接続・ツール検出（9 個）・`navigate` 実行までを確認。
- **CI（GitHub Actions）**: push のたびに ubuntu で構文チェック＋ユニットテスト、windows-latest で実 Edge の
  selftest（Selenium / Playwright 両エンジン）を実行。
- 環境: ネイティブ Windows 11 ＋ Microsoft Edge および Google Chrome。

---

## ❓ トラブルシュート

- **ドライバ取得に失敗** … 社内など制限環境では Selenium Manager がドライバ取得に失敗することがある。
  社内ミラー or 手動で msedgedriver/chromedriver を PATH に置く（バージョンはブラウザに合わせる）。Playwright なら `channel=msedge` で回避しやすい。
- **会社プロキシ** … 必要なら `HTTPS_PROXY` を設定。localhost 接続は `NO_PROXY=localhost,127.0.0.1` で除外。
- **`Failed to connect to Ollama`** … Ollama 本体が未起動か localhost がプロキシ経由。`ollama ps` で確認し
  `NO_PROXY` を設定。別ポートなら `OLLAMA_HOST` も指定。
- **`llama-server binary not found`** … Ollama 本体の推論エンジンが欠落（インストール不完全）。再インストールし
  `ollama run qwen3:14b "test"` で推論できることを確認。
- **同じ操作を繰り返す / 別ページを探しに行く / 説明や確認で止まる** … 思考型モデルにありがち。`OLLAMA_THINK=0`、
  依頼文に `/no_think`、「確認不要・今すぐツールで実行」を明示。`qwen3:14b` 等の tool calling 対応モデルを使う。
- **要素が見つからない** … 動的ページでは `get_page_state` を取り直す（エージェントは自動で行う）。Playwright は auto-waiting で緩和。

---

## 📄 ライセンス

[Apache License 2.0](LICENSE) のもとで公開しています。　Copyright 2026 岩本 剛 (Iwamoto-Ai).

---

## 📚 参考資料

- [Model Context Protocol (MCP) 公式](https://modelcontextprotocol.io/)
- [DOM（Document Object Model）](https://ja.wikipedia.org/wiki/Document_Object_Model)
- [Claude Desktop MCP Documentation](https://docs.anthropic.com/en/docs/claude-code/overview)
- [Selenium 公式](https://www.selenium.dev/)
- [Playwright 公式](https://playwright.dev/python/)
- [Playwright Codegen（操作を記録してコード生成）](https://playwright.dev/python/docs/codegen)
- [Chrome DevTools Recorder（公式）](https://developer.chrome.com/docs/devtools/recorder/reference)
- [@puppeteer/replay（Recorder JSON 仕様・再生ライブラリ）](https://github.com/puppeteer/replay)
- [WebDriver BiDi（W3C 仕様）](https://w3c.github.io/webdriver-bidi/)
- [Ollama 公式](https://ollama.com/)
- [OpenClaw](https://openclaw.ai/)
- [Hermes Agent (NousResearch)](https://github.com/NousResearch/hermes-agent)
- [Hermes Agent — MCP 設定リファレンス](https://hermes-agent.nousresearch.com/docs/reference/mcp-config-reference)
