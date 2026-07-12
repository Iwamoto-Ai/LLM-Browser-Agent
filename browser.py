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
browser.py — Selenium WebDriver の薄いラッパー。

設計の要点:
  * ページ上の「操作可能な要素」に連番インデックス (data-claude-idx) を振り、
    Claude にはその一覧をテキストで渡す。Claude はインデックスを指定して操作する
    （座標やセレクタを推測させない = 安定する）。
  * パスワード等のシークレットはモデルに渡さない。テキスト中の {{SECRET:NAME}} を
    このレイヤーで環境変数の値に置換してから入力する。
    <NAME>_ALLOWED_DOMAINS で入力先ドメインを制限できる（engine_common 参照）。
  * DOM 収集 JS・SECRET 処理・state() 形式は engine_common.py で
    Playwright 版（browser_playwright.py）と共有する。
"""

from __future__ import annotations

import base64
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import Select
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    ElementNotInteractableException,
    NoSuchElementException,
    WebDriverException,
)

from engine_common import (
    COLLECT_JS, TEXT_JS, PAGE_TEXT_JS,
    resolve_secrets, mask_secrets, format_state, format_page_text, xpath_literal,
)

# Recorder の aria/ セレクタで role → 具体的な XPath に落とすための対応表
_ARIA_ROLE_XPATH = {
    "button": ("//button[normalize-space(.)={lit}]",
               "//input[(@type='submit' or @type='button') and @value={lit}]"),
    "link": ("//a[normalize-space(.)={lit}]",),
    "textbox": ("//input[@aria-label={lit} or @placeholder={lit} or @name={lit}]",
                "//textarea[@aria-label={lit} or @placeholder={lit} or @name={lit}]"),
}


class Browser:
    def __init__(self, browser: str = "edge", headless: bool = True,
                 window: tuple[int, int] = (1280, 1600)):
        browser = (browser or "edge").lower()
        if browser not in ("edge", "chrome"):
            raise ValueError(f"未対応のブラウザ: {browser}（edge または chrome）")
        self.browser_name = browser

        opts = EdgeOptions() if browser == "edge" else ChromeOptions()
        if headless:
            opts.add_argument("--headless=new")
        opts.add_argument(f"--window-size={window[0]},{window[1]}")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--lang=ja-JP")
        # Linux / WSL でのみ必要なフラグ（Windows ネイティブでは付けない）
        if sys.platform != "win32":
            opts.add_argument("--no-sandbox")
            opts.add_argument("--disable-dev-shm-usage")

        # Selenium 4.6+ の Selenium Manager がドライバ（msedgedriver/chromedriver）を自動取得
        if browser == "edge":
            self.driver = webdriver.Edge(options=opts)
        else:
            self.driver = webdriver.Chrome(options=opts)
        self.driver.set_page_load_timeout(45)

    # ---- 基本操作 -----------------------------------------------------------
    def navigate(self, url: str) -> str:
        if not re.match(r"^https?://", url):
            url = "https://" + url
        self.driver.get(url)
        self._wait_ready()
        return f"{url} に移動しました。"

    def _wait_ready(self, timeout: float = 10.0) -> None:
        end = time.time() + timeout
        while time.time() < end:
            try:
                if self.driver.execute_script("return document.readyState") == "complete":
                    return
            except WebDriverException:
                pass
            time.sleep(0.2)

    def _resolve_secrets(self, text: str) -> str:
        """{{SECRET:NAME}} を解決する。<NAME>_ALLOWED_DOMAINS があれば現在 URL と照合。"""
        try:
            url = self.driver.current_url
        except WebDriverException:
            url = None
        return resolve_secrets(text, url)

    def _find(self, idx: int):
        try:
            return self.driver.find_element(By.CSS_SELECTOR, f"[data-claude-idx='{idx}']")
        except NoSuchElementException:
            raise ValueError(f"インデックス {idx} の要素が見つかりません。"
                             "get_page_state でページ状態を取り直してください。")

    def click(self, idx: int) -> str:
        el = self._find(idx)
        label = el.get_attribute("aria-label") or el.text or f"#{idx}"
        try:
            el.click()
        except (ElementClickInterceptedException, ElementNotInteractableException):
            self.driver.execute_script("arguments[0].click();", el)
        self._wait_ready()
        return f"要素 [{idx}] ({label[:40]}) をクリックしました。"

    def input_text(self, idx: int, text: str, submit: bool = False) -> str:
        el = self._find(idx)
        resolved = self._resolve_secrets(text)
        try:
            el.clear()
        except WebDriverException:
            pass
        el.send_keys(resolved)
        if submit:
            el.send_keys(Keys.RETURN)
            self._wait_ready()
        # ログに残すテキストはシークレットを伏せる（モデルに値は渡らない）
        shown = mask_secrets(text)
        return f"要素 [{idx}] に「{shown}」を入力しました{'（Enter送信）' if submit else ''}。"

    def select_option(self, idx: int, option: str) -> str:
        """<select> 要素の選択肢を選ぶ。表示テキスト → value → 番号 の順で解決を試す。"""
        el = self._find(idx)
        if el.tag_name.lower() != "select":
            raise ValueError(f"インデックス {idx} は <select> ではありません（{el.tag_name}）。")
        sel = Select(el)
        option = str(option)
        try:
            sel.select_by_visible_text(option)
        except Exception:
            try:
                sel.select_by_value(option)
            except Exception:
                if option.isdigit():
                    sel.select_by_index(int(option))
                else:
                    raise ValueError(f"選択肢「{option}」が見つかりません。"
                                     "get_page_state の「選択肢:」から選んでください。")
        self._wait_ready()
        return f"要素 [{idx}] で「{option}」を選択しました。"

    def set_checked(self, idx: int, checked: bool = True) -> str:
        """checkbox / radio のオン・オフを設定する（既に目的の状態なら何もしない）。"""
        el = self._find(idx)
        if el.is_selected() != bool(checked):
            try:
                el.click()
            except (ElementClickInterceptedException, ElementNotInteractableException):
                self.driver.execute_script("arguments[0].click();", el)
        self._wait_ready()
        return f"要素 [{idx}] を{'ON' if checked else 'OFF'} にしました。"

    # ---- Recorder（録画）リプレイ用：セレクタ候補で操作する ----
    def _selector_candidates(self, sel: str) -> list:
        """Chrome Recorder のセレクタ表記を Selenium の (By, value) 候補リストに変換する。"""
        if sel.startswith("xpath/"):
            return [(By.XPATH, sel[len("xpath/"):])]
        if sel.startswith("pierce/"):
            return [(By.CSS_SELECTOR, sel[len("pierce/"):])]  # 注: shadow DOM 貫通は不可（best-effort）
        if sel.startswith("text/"):
            # 最深ノードに限定する（従来の contains(.) は <html> 等の祖先が先にマッチしてしまう）
            lit = xpath_literal(sel[len("text/"):])
            return [(By.XPATH,
                     f"//*[contains(normalize-space(.), {lit})"
                     f" and not(.//*[contains(normalize-space(.), {lit})])]")]
        if sel.startswith("aria/"):
            # aria/名前[role="button"] 形式。accessible name は aria-label とは限らないため、
            # aria-label → role 固有 XPath → 最深テキスト一致 の順で候補を並べる。
            body = sel[len("aria/"):]
            name = body.split("[")[0].strip()
            m = re.search(r'role="?(\w+)', body)
            role = m.group(1) if m else None
            lit = xpath_literal(name)
            cands = [(By.XPATH, f"//*[@aria-label={lit}]")]
            for xp in _ARIA_ROLE_XPATH.get(role or "", ()):
                cands.append((By.XPATH, xp.format(lit=lit)))
            cands.append((By.XPATH,
                          f"//*[normalize-space(.)={lit}"
                          f" and not(.//*[normalize-space(.)={lit}])]"))
            return cands
        return [(By.CSS_SELECTOR, sel)]

    def _try_in_frame(self, frame_path, selectors, action):
        """frame 指定に降りて、候補セレクタで action を試す。成功したセレクタ文字列を返す。
        frame_path は None（最上位）／"content" 等の名前（name か id）／[i, j, ...]（インデックス列）。"""
        try:
            self.driver.switch_to.default_content()
            if frame_path:
                if isinstance(frame_path, str):
                    self.driver.switch_to.frame(frame_path)  # name か id で切替
                else:
                    for idx in frame_path:
                        self.driver.switch_to.frame(idx)
        except Exception:
            self.driver.switch_to.default_content()
            return None
        for sel in selectors:
            for by, val in self._selector_candidates(sel):
                try:
                    el = self.driver.find_element(by, val)
                    action(el)
                    return sel
                except Exception:
                    continue
        return None

    def _windows_for(self, target):
        """target が URL のとき、一致するウィンドウハンドルを優先的に返す（なければ全ハンドル）。"""
        handles = self.driver.window_handles
        if not target or target == "main":
            return [self.driver.current_window_handle]
        base = target.split("?")[0]
        cur = self.driver.current_window_handle
        matched, others = [], []
        for h in handles:
            try:
                self.driver.switch_to.window(h)
                u = self.driver.current_url
                (matched if base and (base in u or u in target) else others).append(h)
            except Exception:
                others.append(h)
        try:
            self.driver.switch_to.window(cur)
        except Exception:
            pass
        return matched + others if matched else handles

    def _try_targets(self, selectors, frame, target, action):
        """別ウィンドウ（ポップアップ）と iframe を横断して action を試す。"""
        orig = self.driver.current_window_handle
        for h in self._windows_for(target):
            try:
                self.driver.switch_to.window(h)
            except Exception:
                continue
            sel = self._try_in_frame(frame, selectors, action)
            if sel is None and frame:
                sel = self._try_in_frame(None, selectors, action)
            if sel is not None:
                self._wait_ready()
                try:  # 元ウィンドウが残っていれば戻す（ポップアップが閉じた場合はそのまま）
                    if orig in self.driver.window_handles:
                        self.driver.switch_to.window(orig)
                        self.driver.switch_to.default_content()
                except Exception:
                    pass
                return sel
        try:
            if orig in self.driver.window_handles:
                self.driver.switch_to.window(orig)
            self.driver.switch_to.default_content()
        except Exception:
            pass
        return None

    def click_selector(self, selectors: list, frame: list | None = None,
                       target: str | None = None) -> str:
        def act(el):
            try:
                el.click()
            except (ElementClickInterceptedException, ElementNotInteractableException):
                self.driver.execute_script("arguments[0].click();", el)
        sel = self._try_targets(selectors, frame, target, act)
        if sel is None:
            raise ValueError(f"クリックできる要素がありません（候補 {selectors}, frame={frame}, target={target}）")
        return f"クリック: {sel}（frame={frame}{', popup' if target and target != 'main' else ''}）"

    def fill_selector(self, selectors: list, text: str, frame: list | None = None,
                      target: str | None = None) -> str:
        resolved = self._resolve_secrets(text)
        shown = mask_secrets(text)

        def act(el):
            if el.tag_name.lower() == "select":
                Select(el).select_by_visible_text(resolved)
                return
            try:
                el.clear()
            except WebDriverException:
                pass
            el.send_keys(resolved)
        sel = self._try_targets(selectors, frame, target, act)
        if sel is None:
            raise ValueError(f"入力できる要素がありません（候補 {selectors}, frame={frame}, target={target}）")
        return f"入力: {sel} ← 「{shown}」（frame={frame}）"

    def send_keys(self, key: str) -> str:
        mapping = {
            "enter": Keys.RETURN, "return": Keys.RETURN, "tab": Keys.TAB,
            "escape": Keys.ESCAPE, "esc": Keys.ESCAPE, "backspace": Keys.BACKSPACE,
            "pagedown": Keys.PAGE_DOWN, "pageup": Keys.PAGE_UP,
            "arrowdown": Keys.ARROW_DOWN, "arrowup": Keys.ARROW_UP,
        }
        k = mapping.get(key.lower().strip())
        if k is None:
            raise ValueError(f"未対応のキー: {key}")
        webdriver.ActionChains(self.driver).send_keys(k).perform()
        self._wait_ready()
        return f"キー {key} を送信しました。"

    def scroll(self, direction: str = "down", amount: int = 800) -> str:
        dy = amount if direction == "down" else -amount
        self.driver.execute_script(f"window.scrollBy(0, {dy});")
        time.sleep(0.3)
        return f"{direction} に {abs(dy)}px スクロールしました。"

    def set_viewport(self, width: int, height: int) -> str:
        try:
            self.driver.set_window_size(int(width), int(height))
        except Exception:
            pass
        return f"ウィンドウサイズを {width}x{height} に設定しました。"

    def screenshot(self, path: str, full_page: bool = True) -> str:
        """ファイル名の末尾（拡張子の前）に _YYYYMMDD_HHMMSS を付けて保存し、
        実際に保存した絶対パスを返す。例: result.png -> result_20260621_153012.png
        full_page=True では CDP (Page.captureScreenshot + captureBeyondViewport) で
        ページ全体を撮影する（Chromium 系のみ）。失敗時はビューポート撮影にフォールバック。"""
        p = Path(path)
        if not p.suffix:
            p = p.with_suffix(".png")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        p = p.with_name(f"{p.stem}_{ts}{p.suffix}")
        p.parent.mkdir(parents=True, exist_ok=True)
        if full_page:
            try:
                data = self.driver.execute_cdp_cmd(
                    "Page.captureScreenshot",
                    {"format": "png", "captureBeyondViewport": True})["data"]
                p.write_bytes(base64.b64decode(data))
                return str(p.resolve())
            except Exception:
                pass  # CDP 不可の場合はビューポート撮影へ
        self.driver.save_screenshot(str(p))
        return str(p.resolve())

    # ---- 状態取得 -----------------------------------------------------------
    def state(self, max_elements: int = 120) -> str:
        elems = self.driver.execute_script("return " + COLLECT_JS.strip()) or []
        texts = self.driver.execute_script("return " + TEXT_JS.strip()) or []
        return format_state(self.driver.current_url, self.driver.title,
                            elems, max_elements, texts)

    def get_page_text(self, max_chars: int = 4000) -> str:
        """ページ本文のテキストを返す（表・照会結果などを「読む」ためのツール）。"""
        body = self.driver.execute_script("return " + PAGE_TEXT_JS.strip()) or ""
        return format_page_text(self.driver.current_url, self.driver.title,
                                body, max_chars)

    def quit(self) -> None:
        try:
            self.driver.quit()
        except WebDriverException:
            pass
