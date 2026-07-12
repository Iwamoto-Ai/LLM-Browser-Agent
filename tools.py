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
tools.py — Claude に渡すツール定義と、ツール呼び出しを Browser につなぐ
ディスパッチャ。各操作の後にページ状態を付けて返すことで Claude が結果を把握できる。
"""

from __future__ import annotations

from browser_factory import make_browser  # noqa: F401  （型的な依存を明示）

TOOLS = [
    {
        "name": "navigate",
        "description": "指定した URL にブラウザを移動する。最初に対象サイトを開くときに使う。",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "移動先 URL"}},
            "required": ["url"],
        },
    },
    {
        "name": "get_page_state",
        "description": "現在のページの URL・タイトルと、操作可能な要素のインデックス一覧を取得する。操作前後で状態が分からなくなったら呼ぶ。",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_page_text",
        "description": "現在のページの本文テキストを取得する。表・照会結果・明細など、操作ではなく「内容を読む」必要があるときに使う。",
        "input_schema": {
            "type": "object",
            "properties": {
                "max_chars": {"type": "integer", "description": "取得する最大文字数（既定 4000）"},
            },
        },
    },
    {
        "name": "click_element",
        "description": "指定したインデックスの要素をクリックする。リンク・ボタン・送信ボタンなど。",
        "input_schema": {
            "type": "object",
            "properties": {"index": {"type": "integer", "description": "要素のインデックス"}},
            "required": ["index"],
        },
    },
    {
        "name": "input_text",
        "description": (
            "入力欄（input/textarea）にテキストを入力する。ユーザー名・検索語など。"
            "パスワード等の秘密情報は値を直接書かず {{SECRET:NAME}} の形式で指定すること"
            "（例: {{SECRET:MY_PASSWORD}}）。実際の値はローカルの環境変数から補完され、"
            "あなた（モデル）には渡らない。submit=true で入力後に Enter を送る。"
            "セレクトボックスには select_option、チェックボックスには set_checked を使うこと。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "index": {"type": "integer", "description": "入力欄のインデックス"},
                "text": {"type": "string", "description": "入力する文字列。秘密情報は {{SECRET:NAME}}"},
                "submit": {"type": "boolean", "description": "入力後に Enter を送るか（既定 false）"},
            },
            "required": ["index", "text"],
        },
    },
    {
        "name": "select_option",
        "description": (
            "セレクトボックス（<select>）の選択肢を選ぶ。option には要素一覧の「選択肢:」に"
            "表示されている表示テキストをそのまま指定する（value・番号でも可）。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "index": {"type": "integer", "description": "select 要素のインデックス"},
                "option": {"type": "string", "description": "選ぶ選択肢（表示テキスト推奨）"},
            },
            "required": ["index", "option"],
        },
    },
    {
        "name": "set_checked",
        "description": "チェックボックスやラジオボタンのオン・オフを設定する。現在値は要素一覧に ON/OFF で表示される。",
        "input_schema": {
            "type": "object",
            "properties": {
                "index": {"type": "integer", "description": "checkbox/radio のインデックス"},
                "checked": {"type": "boolean", "description": "true でオン、false でオフ（既定 true）"},
            },
            "required": ["index"],
        },
    },
    {
        "name": "send_keys",
        "description": "特殊キーを送る（enter, tab, escape, pagedown, pageup, arrowdown, arrowup など）。",
        "input_schema": {
            "type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"],
        },
    },
    {
        "name": "scroll",
        "description": "ページを上下にスクロールする。画面外の要素を表示したいときに使う。",
        "input_schema": {
            "type": "object",
            "properties": {
                "direction": {"type": "string", "enum": ["up", "down"]},
                "amount": {"type": "integer", "description": "ピクセル（既定 800）"},
            },
            "required": ["direction"],
        },
    },
    {
        "name": "take_screenshot",
        "description": "現在のページのスクリーンショットを PNG で保存する。ファイル名の末尾には自動で日時 (_YYYYMMDD_HHMMSS) が付く。",
        "input_schema": {
            "type": "object",
            "properties": {"filename": {"type": "string", "description": "保存ファイル名（例: result.png）"}},
            "required": ["filename"],
        },
    },
    {
        "name": "finish",
        "description": "タスク完了時に呼ぶ。実行結果の要約を summary に書く。",
        "input_schema": {
            "type": "object",
            "properties": {"summary": {"type": "string", "description": "実施内容の要約"}},
            "required": ["summary"],
        },
    },
]


def dispatch(name: str, args: dict, browser, out_dir: str) -> str:
    """ツール呼び出しを実行し、結果テキスト（多くは末尾に最新ページ状態）を返す。"""
    try:
        if name == "navigate":
            msg = browser.navigate(args["url"])
            return f"{msg}\n\n{browser.state()}"
        if name == "get_page_state":
            return browser.state()
        if name == "get_page_text":
            return browser.get_page_text(int(args.get("max_chars", 4000)))
        if name == "click_element":
            msg = browser.click(args["index"])
            return f"{msg}\n\n{browser.state()}"
        if name == "input_text":
            msg = browser.input_text(args["index"], args["text"], args.get("submit", False))
            return f"{msg}\n\n{browser.state()}"
        if name == "select_option":
            msg = browser.select_option(args["index"], args["option"])
            return f"{msg}\n\n{browser.state()}"
        if name == "set_checked":
            msg = browser.set_checked(args["index"], args.get("checked", True))
            return f"{msg}\n\n{browser.state()}"
        if name == "send_keys":
            msg = browser.send_keys(args["key"])
            return f"{msg}\n\n{browser.state()}"
        if name == "scroll":
            msg = browser.scroll(args["direction"], args.get("amount", 800))
            return f"{msg}\n\n{browser.state()}"
        if name == "take_screenshot":
            import os
            saved = browser.screenshot(os.path.join(out_dir, args["filename"]))
            return f"スクリーンショットを保存しました: {saved}"
        if name == "finish":
            return "FINISH"
        return f"未知のツール: {name}"
    except Exception as e:  # ツール失敗もモデルに返して自己修復させる
        return f"エラー: {e}"
