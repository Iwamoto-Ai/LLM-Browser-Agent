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
browser_playwright.py — browser.py（Selenium 版）と同じインターフェースを持つ
Playwright 実装。navigate / state / click / input_text / select_option / set_checked /
get_page_text / send_keys / scroll / screenshot / quit を同じ名前・同じ戻り値で提供するため、
agent*.py / run_template.py / mcp_server.py / tools.py は無改修で差し替えられる。

設計の要点（MCP との両立）:
  * Playwright の「同期 API」は asyncio のイベントループ上では動かせない。
    一方 MCP サーバー（FastMCP）は asyncio 上で動く。
  * そこで Playwright を「専用スレッド」で起動し、そのスレッド上だけで全操作を実行する。
    公開メソッドは呼び出しをキュー経由でそのスレッドに投げ、結果を同期的に待つ。
    これにより、CLI（同期）からも MCP（非同期）からも、同じ同期インターフェースで使える。

利点:
  * auto-waiting により、動的ページ・複雑メニューでの取りこぼしが減る。
  * channel="msedge"/"chrome" でインストール済みブラウザを使う（ダウンロード不要・社内向き）。
  * フルページのスクリーンショット。

DOM 収集 JS・SECRET 処理・state() 形式は engine_common.py で Selenium 版と共有する。

前提: pip install playwright  （ブラウザDLが要る場合のみ playwright install。channel 指定なら不要）
"""

from __future__ import annotations

import queue
import re
import threading
from concurrent.futures import Future
from datetime import datetime
from pathlib import Path

from engine_common import (
    COLLECT_JS, TEXT_JS, PAGE_TEXT_JS,
    resolve_secrets, mask_secrets, format_state, format_page_text,
)

_KEYMAP = {
    "enter": "Enter", "return": "Enter", "tab": "Tab", "escape": "Escape",
    "esc": "Escape", "backspace": "Backspace", "pagedown": "PageDown",
    "pageup": "PageUp", "arrowdown": "ArrowDown", "arrowup": "ArrowUp",
}

_ARIA_SEL_RE = re.compile(r'^aria/([^\[]+?)\s*(?:\[role="?(\w+)"?\])?$')


def _pw_locator(ctx, sel: str):
    """Chrome Recorder のセレクタ表記を Playwright のロケータに変換する。
    ctx は page でも frame でもよい（どちらも locator/get_by_text を持つ）。
    css / xpath/ / text/ / aria/ / pierce/ に対応。"""
    if sel.startswith("xpath/"):
        return ctx.locator("xpath=" + sel[len("xpath/"):])
    if sel.startswith("text/"):
        return ctx.get_by_text(sel[len("text/"):], exact=False)
    if sel.startswith("aria/"):
        # Recorder の aria/ は accessible name。role が付いていれば get_by_role が最も堅牢。
        m = _ARIA_SEL_RE.match(sel)
        name = (m.group(1) if m else sel[len("aria/"):]).strip()
        role = m.group(2) if m else None
        if role:
            try:
                return ctx.get_by_role(role, name=name)
            except Exception:
                pass
        # role が無い場合は accessible name の主な由来（テキスト / ラベル / aria-label）を or で束ねる
        return (ctx.get_by_text(name, exact=True)
                .or_(ctx.get_by_label(name))
                .or_(ctx.locator(f'[aria-label="{name}"]')))
    if sel.startswith("pierce/"):
        return ctx.locator(sel[len("pierce/"):])  # Playwright は css で shadow を貫通
    return ctx.locator(sel)


def _resolve_frame(page, frame_path):
    """録画の frame 指定を Playwright の Frame に変換する。解決不能なら None。
      * None            → メインフレーム
      * "content" 等の文字列 → フレーム名（name 属性）で特定（Codegen 由来の指定に対応）
      * [i, j, ...]     → 子フレームの順番インデックス列（Chrome Recorder 由来）"""
    if frame_path is None or frame_path == "":
        return page.main_frame
    if isinstance(frame_path, str):
        for fr in page.frames:
            if fr.name == frame_path:
                return fr
        return None
    fr = page.main_frame
    for idx in frame_path:
        kids = fr.child_frames
        if idx < len(kids):
            fr = kids[idx]
        else:
            return None
    return fr


def _all_frames(page, frame_path, target):
    """操作対象の探索順を作る。iframe（frame_path）に加え、別ウィンドウ（ポップアップ）も横断する。
    Recorder で target が URL のステップ（カレンダー等のポップアップ操作）に対応するため、
    まず target URL に一致するウィンドウ→指定フレーム、続いて全ウィンドウの全フレームを並べる。"""
    pages = list(page.context.pages)
    order = []
    if target and target != "main":
        base = target.split("?")[0]
        for pg in pages:
            try:
                if base and (base in pg.url or pg.url in target):
                    fr = _resolve_frame(pg, frame_path) or pg.main_frame
                    if fr not in order:
                        order.append(fr)
            except Exception:
                pass
    else:
        tf = _resolve_frame(page, frame_path)
        if tf is not None:
            order.append(tf)
    # フォールバック: 全ウィンドウ × 全フレーム
    for pg in pages:
        try:
            for fr in pg.frames:
                if fr not in order:
                    order.append(fr)
        except Exception:
            pass
    return order


class PlaywrightBrowser:
    def __init__(self, browser: str = "edge", headless: bool = True,
                 window: tuple[int, int] = (1280, 1600)):
        self.browser_name = (browser or "edge").lower()
        if self.browser_name not in ("edge", "chrome"):
            raise ValueError(f"未対応のブラウザ: {browser}（edge または chrome）")
        self._errors: list = []   # ページ JS エラー / console.error を蓄積（BiDi 的な失敗検知）
        self._q: queue.Queue = queue.Queue()
        self._ready: Future = Future()
        self._thread = threading.Thread(
            target=self._worker, args=(self.browser_name, headless, window), daemon=True)
        self._thread.start()
        self._ready.result()  # 起動完了を待つ（失敗時は例外を送出）

    # ---- 専用スレッド：Playwright の生成と操作はすべてここで行う ----
    def _worker(self, browser: str, headless: bool, window) -> None:
        try:
            from playwright.sync_api import sync_playwright
            pw = sync_playwright().start()
            channel = "msedge" if browser == "edge" else "chrome"
            br = pw.chromium.launch(channel=channel, headless=headless)
            ctx = br.new_context(viewport={"width": window[0], "height": window[1]},
                                 locale="ja-JP")
            page = ctx.new_page()
            page.set_default_timeout(15000)
            # ページのエラー/警告をリアルタイムに収集（BiDi 的な失敗検知の代替）
            page.on("pageerror", lambda exc: self._errors.append(f"JSエラー: {str(exc)[:160]}"))
            page.on("console", lambda m: self._errors.append(f"console.error: {m.text[:160]}")
                    if m.type == "error" else None)
        except Exception as e:  # 起動失敗を呼び出し元へ伝える
            self._ready.set_exception(e)
            return
        self._ready.set_result(True)
        while True:
            item = self._q.get()
            if item is None:
                break
            fn, fut = item
            try:
                fut.set_result(fn(page))
            except Exception as e:
                fut.set_exception(e)
        try:
            ctx.close(); br.close(); pw.stop()
        except Exception:
            pass

    def _call(self, fn):
        """専用スレッドで fn(page) を実行し、結果を同期的に返す（例外も再送出）。"""
        fut: Future = Future()
        self._q.put((fn, fut))
        return fut.result()

    # ---- 公開メソッド（browser.Browser と同一インターフェース） ----
    def navigate(self, url: str) -> str:
        if not re.match(r"^https?://", url):
            url = "https://" + url

        def op(page):
            page.goto(url, wait_until="domcontentloaded")
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass
            return f"{url} に移動しました。"
        return self._call(op)

    def state(self, max_elements: int = 120) -> str:
        def op(page):
            elems = page.evaluate(COLLECT_JS.strip()) or []
            texts = page.evaluate(TEXT_JS.strip()) or []
            errors = self._errors[-5:]
            self._errors.clear()   # 一度報告したらクリア（重複防止）
            return (page.url, page.title(), elems, texts, errors)
        url, title, elems, texts, errors = self._call(op)
        return format_state(url, title, elems, max_elements, texts, errors)

    def get_page_text(self, max_chars: int = 4000) -> str:
        """ページ本文のテキストを返す（表・照会結果などを「読む」ためのツール）。"""
        def op(page):
            body = page.evaluate(PAGE_TEXT_JS.strip()) or ""
            return (page.url, page.title(), body)
        url, title, body = self._call(op)
        return format_page_text(url, title, body, max_chars)

    # ---- Recorder（録画）リプレイ用：セレクタ候補で操作する（iframe / ポップアップ対応） ----
    def click_selector(self, selectors: list, frame: list | None = None,
                       target: str | None = None) -> str:
        def op(page):
            last = None
            for attempt in range(3):  # ポップアップ/参照パネルの遅延ロードに備え数回試す
                for fr in _all_frames(page, frame, target):
                    for sel in selectors:
                        try:
                            loc = _pw_locator(fr, sel)
                            if loc.count() == 0:
                                continue
                            loc.first.click(timeout=5000)
                            try:
                                page.wait_for_load_state("domcontentloaded", timeout=5000)
                            except Exception:
                                pass
                            return f"クリック: {sel}（frame={frame}{', popup' if target and target != 'main' else ''}）"
                        except Exception as e:
                            last = e
                page.wait_for_timeout(1000)
            raise ValueError(f"クリックできる要素がありません（候補 {selectors}, frame={frame}, target={target}）: {last}")
        return self._call(op)

    def fill_selector(self, selectors: list, text: str, frame: list | None = None,
                      target: str | None = None) -> str:
        shown = mask_secrets(text)

        def op(page):
            last = None
            for attempt in range(3):
                for fr in _all_frames(page, frame, target):
                    # SECRET はフレームごとの URL でドメイン制限を照合してから解決する
                    try:
                        resolved = resolve_secrets(text, fr.url)
                    except ValueError as e:
                        last = e
                        continue
                    for sel in selectors:
                        try:
                            loc = _pw_locator(fr, sel)
                            if loc.count() == 0:
                                continue
                            first = loc.first
                            tag = (first.evaluate("el => el.tagName") or "").lower()
                            if tag == "select":
                                first.select_option(label=resolved, timeout=5000)
                            else:
                                first.fill(resolved, timeout=5000)
                            return f"入力: {sel} ← 「{shown}」（frame={frame}）"
                        except Exception as e:
                            last = e
                page.wait_for_timeout(1000)
            raise ValueError(f"入力できる要素がありません（候補 {selectors}, frame={frame}, target={target}）: {last}")
        return self._call(op)

    def click(self, idx: int) -> str:
        def op(page):
            loc = page.locator(f"[data-claude-idx='{idx}']")
            if loc.count() == 0:
                raise ValueError(f"インデックス {idx} の要素が見つかりません。"
                                 "get_page_state でページ状態を取り直してください。")
            try:
                loc.first.click(timeout=8000)
            except Exception:
                loc.first.click(timeout=8000, force=True)
            try:
                page.wait_for_load_state("domcontentloaded", timeout=5000)
            except Exception:
                pass
            return f"要素 [{idx}] をクリックしました。"
        return self._call(op)

    def input_text(self, idx: int, text: str, submit: bool = False) -> str:
        shown = mask_secrets(text)

        def op(page):
            # SECRET は現在ページの URL でドメイン制限を照合してから解決する
            resolved = resolve_secrets(text, page.url)
            loc = page.locator(f"[data-claude-idx='{idx}']")
            if loc.count() == 0:
                raise ValueError(f"インデックス {idx} の要素が見つかりません。"
                                 "get_page_state でページ状態を取り直してください。")
            loc.first.fill(resolved)
            if submit:
                loc.first.press("Enter")
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=5000)
                except Exception:
                    pass
            return f"要素 [{idx}] に「{shown}」を入力しました{'（Enter送信）' if submit else ''}。"
        return self._call(op)

    def select_option(self, idx: int, option: str) -> str:
        """<select> 要素の選択肢を選ぶ。表示テキスト → value → 番号 の順で解決を試す。"""
        option = str(option)

        def op(page):
            loc = page.locator(f"[data-claude-idx='{idx}']")
            if loc.count() == 0:
                raise ValueError(f"インデックス {idx} の要素が見つかりません。"
                                 "get_page_state でページ状態を取り直してください。")
            first = loc.first
            try:
                first.select_option(label=option, timeout=5000)
            except Exception:
                try:
                    first.select_option(value=option, timeout=5000)
                except Exception:
                    if option.isdigit():
                        first.select_option(index=int(option), timeout=5000)
                    else:
                        raise ValueError(f"選択肢「{option}」が見つかりません。"
                                         "get_page_state の「選択肢:」から選んでください。")
            return f"要素 [{idx}] で「{option}」を選択しました。"
        return self._call(op)

    def set_checked(self, idx: int, checked: bool = True) -> str:
        """checkbox / radio のオン・オフを設定する（既に目的の状態なら何もしない）。"""
        def op(page):
            loc = page.locator(f"[data-claude-idx='{idx}']")
            if loc.count() == 0:
                raise ValueError(f"インデックス {idx} の要素が見つかりません。"
                                 "get_page_state でページ状態を取り直してください。")
            loc.first.set_checked(bool(checked), timeout=5000)
            return f"要素 [{idx}] を{'ON' if checked else 'OFF'} にしました。"
        return self._call(op)

    def send_keys(self, key: str) -> str:
        k = _KEYMAP.get(key.lower().strip())
        if k is None:
            raise ValueError(f"未対応のキー: {key}")

        def op(page):
            page.keyboard.press(k)
            try:
                page.wait_for_load_state("domcontentloaded", timeout=5000)
            except Exception:
                pass
            return f"キー {key} を送信しました。"
        return self._call(op)

    def scroll(self, direction: str = "down", amount: int = 800) -> str:
        dy = amount if direction == "down" else -amount

        def op(page):
            page.mouse.wheel(0, dy)
            return f"{direction} に {abs(dy)}px スクロールしました。"
        return self._call(op)

    def set_viewport(self, width: int, height: int) -> str:
        def op(page):
            page.set_viewport_size({"width": int(width), "height": int(height)})
            return None
        self._call(op)
        return f"ウィンドウサイズを {width}x{height} に設定しました。"

    def screenshot(self, path: str, full_page: bool = True) -> str:
        p = Path(path)
        if not p.suffix:
            p = p.with_suffix(".png")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        p = p.with_name(f"{p.stem}_{ts}{p.suffix}")
        p.parent.mkdir(parents=True, exist_ok=True)

        def op(page):
            page.screenshot(path=str(p), full_page=full_page)
            return None
        self._call(op)
        return str(p.resolve())

    def quit(self) -> None:
        try:
            self._q.put(None)
            self._thread.join(timeout=10)
        except Exception:
            pass
