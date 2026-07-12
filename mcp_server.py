# Copyright 2026 Iwamoto-Ai
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
mcp_server.py — ブラウザ操作を MCP ツールとして公開するサーバー。

Claude Desktop や OpenClaw から、navigate / click / input_text / take_screenshot
などを直接呼んでブラウザを操作できる（API キー不要。ホスト側の Claude が頭脳になる）。

ブラウザは 1 プロセス内で 1 セッションを保持し、ツール呼び出しをまたいで維持する。

環境変数（claude_desktop_config.json の env で指定可能）:
  BROWSER_AGENT_ENGINE   selenium | playwright （既定: selenium）
  BROWSER_AGENT_BROWSER  edge | chrome   （既定: edge）
  BROWSER_AGENT_HEADLESS 1 で非表示       （既定: 表示）
  BROWSER_AGENT_OUTPUT   スクショ保存先   （既定: ~/claude_browser_agent_output）
  ログイン用シークレット（MY_PASSWORD など）も env に置けば {{SECRET:NAME}} で参照可。
  <NAME>_ALLOWED_DOMAINS（例 MY_PASSWORD_ALLOWED_DOMAINS=example.co.jp）を設定すると、
  そのシークレットは指定ドメインのページにしか入力できなくなる（インジェクション対策）。
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

from mcp.server.fastmcp import FastMCP, Image

from browser_factory import make_browser

mcp = FastMCP("browser-agent")

_browser = None
_lock = threading.Lock()   # FastMCP はツールをスレッドプールで実行し得るため直列化する


def _env_bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _output_dir() -> Path:
    p = Path(os.environ.get("BROWSER_AGENT_OUTPUT")
             or (Path.home() / "claude_browser_agent_output"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def _get(create: bool = True):
    global _browser
    if _browser is None and create:
        _browser = make_browser(
            os.environ.get("BROWSER_AGENT_ENGINE", "selenium"),
            os.environ.get("BROWSER_AGENT_BROWSER", "edge"),
            _env_bool("BROWSER_AGENT_HEADLESS", False),
        )
    if _browser is None:
        raise RuntimeError("ブラウザが開かれていません。open_browser を呼んでください。")
    return _browser


@mcp.tool()
def open_browser(browser: str = "edge", headless: bool = False,
                 engine: str = "") -> str:
    """ブラウザを起動する。browser は 'edge'（既定）か 'chrome'。
    engine は 'selenium'（既定）か 'playwright'（未指定なら環境変数 BROWSER_AGENT_ENGINE）。
    すでに開いている場合は一度閉じてから開き直す。headless=True で画面非表示。"""
    global _browser
    with _lock:
        if _browser is not None:
            _browser.quit()
            _browser = None
        eng = engine or os.environ.get("BROWSER_AGENT_ENGINE", "selenium")
        _browser = make_browser(eng, browser, headless)
        return f"{browser} を起動しました（engine={eng}, headless={headless}）。"


@mcp.tool()
def navigate(url: str) -> str:
    """指定 URL に移動し、移動後のページ状態（操作可能要素の一覧）を返す。"""
    with _lock:
        b = _get()
        msg = b.navigate(url)
        return f"{msg}\n\n{b.state()}"


@mcp.tool()
def get_page_state() -> str:
    """現在の URL・タイトルと、操作可能な要素のインデックス一覧を返す。"""
    with _lock:
        return _get().state()


@mcp.tool()
def get_page_text(max_chars: int = 4000) -> str:
    """現在のページの本文テキストを返す。表・照会結果・明細など、
    操作ではなく「内容を読む」必要があるときに使う。"""
    with _lock:
        return _get().get_page_text(max_chars)


@mcp.tool()
def click_element(index: int) -> str:
    """指定インデックスの要素（リンク/ボタン等）をクリックし、最新のページ状態を返す。"""
    with _lock:
        b = _get()
        msg = b.click(index)
        return f"{msg}\n\n{b.state()}"


@mcp.tool()
def input_text(index: int, text: str, submit: bool = False) -> str:
    """入力欄にテキストを入力する。パスワード等の秘密情報は値を直接書かず
    {{SECRET:NAME}} 形式で指定する（例: {{SECRET:MY_PASSWORD}}）。実際の値はサーバー側の
    環境変数から補完され、モデルには渡らない。submit=True で入力後 Enter を送る。
    セレクトボックスには select_option、チェックボックスには set_checked を使うこと。"""
    with _lock:
        b = _get()
        msg = b.input_text(index, text, submit)
        return f"{msg}\n\n{b.state()}"


@mcp.tool()
def select_option(index: int, option: str) -> str:
    """セレクトボックス（<select>）の選択肢を選ぶ。option には要素一覧の「選択肢:」に
    表示されている表示テキストをそのまま指定する（value・番号でも可）。"""
    with _lock:
        b = _get()
        msg = b.select_option(index, option)
        return f"{msg}\n\n{b.state()}"


@mcp.tool()
def set_checked(index: int, checked: bool = True) -> str:
    """チェックボックスやラジオボタンのオン・オフを設定する。
    現在値は要素一覧に ON/OFF で表示される。"""
    with _lock:
        b = _get()
        msg = b.set_checked(index, checked)
        return f"{msg}\n\n{b.state()}"


@mcp.tool()
def send_keys(key: str) -> str:
    """特殊キーを送る（enter, tab, escape, pagedown, pageup, arrowdown, arrowup など）。"""
    with _lock:
        b = _get()
        msg = b.send_keys(key)
        return f"{msg}\n\n{b.state()}"


@mcp.tool()
def scroll(direction: str = "down", amount: int = 800) -> str:
    """ページを上下にスクロールする（direction は 'up' か 'down'）。"""
    with _lock:
        b = _get()
        msg = b.scroll(direction, amount)
        return f"{msg}\n\n{b.state()}"


@mcp.tool()
def take_screenshot(filename: str = "screenshot.png") -> Image:
    """現在のページのスクリーンショットを保存し、画像をホスト（Claude）にも返す。
    ファイル名の末尾には自動で日時 (_YYYYMMDD_HHMMSS) が付く。
    保存先は BROWSER_AGENT_OUTPUT（既定: ~/claude_browser_agent_output）。"""
    with _lock:
        b = _get()
        saved = b.screenshot(str(_output_dir() / filename))
        return Image(path=saved)


@mcp.tool()
def close_browser() -> str:
    """ブラウザを閉じてセッションを破棄する。"""
    global _browser
    with _lock:
        if _browser is not None:
            _browser.quit()
            _browser = None
            return "ブラウザを閉じました。"
        return "ブラウザは開かれていません。"


def main() -> None:
    """console script（llm-browser-agent-mcp）からの起動用エントリポイント。"""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
