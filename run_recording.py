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
run_recording.py — Chrome Recorder の JSON を「決定論的に」再生する（LLM 不要）。

複雑なメニューや項目が多いサイトでも、人が一度操作して録画した手順をそのまま再生するため、
LLM の判断ゆらぎが無く確実。入力値は {{key}} を --values で差し替えられるので、
同じ録画を別データで何度でも回せる（パスワードは {{SECRET:NAME}} のまま安全に補完）。

追加ステップ型（録画 JSON に手で書ける）:
  {"type": "screenshot", "name": "{{project_no}}__{{po_number}}", "full_page": false}
    … 手順の途中でスクリーンショットを保存する（名前に {{key}} を使える。日時は自動付与）。
      エビデンス取得（完了画面の証跡）を、後続の「ホームへ戻る」等の前に置けるようにするための拡張。

使い方:
  python run_recording.py --recording recordings/test_site.example.json --values data/test_values.json --browser edge --no-headless
  # 既定エンジンは playwright（Recorder セレクタとの相性が良い）。--engine selenium も可。

run_batch.py（バッチ実行）もこのモジュールの exec_step() を共用する。
"""

from __future__ import annotations

import argparse
import os
import sys

from browser_factory import make_browser
from recorder_import import load_recording, fill_value, candidates, missing_placeholders

# Recorder の keyDown で扱う特殊キー（send_keys に渡す）
_SPECIAL_KEYS = {"Enter", "Tab", "Escape", "Backspace",
                 "ArrowDown", "ArrowUp", "PageDown", "PageUp"}

# 再生では無視するステップ型
_SKIP_TYPES = ("waitForElement", "waitForExpression", "customStep", "close")


def exec_step(browser, step: dict, values: dict, out_dir: str,
              full_page: bool = True, log=print, tag: str = "") -> str | None:
    """録画の 1 ステップを実行する。screenshot ステップは保存パスを返す（それ以外は None）。
    run_recording.py（単発リプレイ）と run_batch.py（バッチ）の両方から使う共通実行部。"""
    t = step.get("type")
    fr = step.get("frame")
    if t == "setViewport":
        w, h = step.get("width"), step.get("height")
        if w and h and hasattr(browser, "set_viewport"):
            log(f"  {tag}setViewport → {w}x{h}")
            try:
                browser.set_viewport(w, h)
            except Exception:
                pass
        else:
            log(f"  {tag}setViewport … スキップ")
        return None
    if t in _SKIP_TYPES:
        log(f"  {tag}{t} … スキップ")
        return None
    if t == "navigate":
        log(f"  {tag}navigate {step.get('url')}")
        browser.navigate(step["url"])
        return None
    if t in ("click", "doubleClick"):
        # セレクタ内の {{キー}} も明細の値で埋める（例: "aria/{{発注番号}}" で
        # 検索結果のリンクを行の値で特定できる）
        sels = [fill_value(s, values) for s in candidates(step)]
        msg = browser.click_selector(sels, frame=fr, target=step.get("target"))
        log(f"  {tag}{msg}")
        return None
    if t == "change":
        val = fill_value(step.get("value", ""), values)
        sels = [fill_value(s, values) for s in candidates(step)]
        msg = browser.fill_selector(sels, val, frame=fr,
                                    target=step.get("target"))
        log(f"  {tag}{msg}")
        return None
    if t == "keyDown":
        k = step.get("key")
        if k in _SPECIAL_KEYS:
            log(f"  {tag}キー送信 {k}")
            browser.send_keys(k)
        else:
            log(f"  {tag}keyDown {k} … スキップ（修飾キー/通常キー）")
        return None
    if t == "keyUp":
        return None  # keyDown 側で処理済み
    if t == "scroll":
        log(f"  {tag}scroll")
        browser.scroll("down", int(step.get("y") or 600))
        return None
    if t == "screenshot":
        name = fill_value(step.get("name", "screenshot"), values)
        fp = step.get("full_page", full_page)
        saved = browser.screenshot(os.path.join(out_dir, str(name)), full_page=fp)
        log(f"  {tag}📸 スクリーンショット保存: {saved}")
        return saved
    log(f"  {tag}{t} … 未対応のためスキップ")
    return None


def replay(recording: dict, values: dict, browser, out_dir: str,
           screenshot: str = "recording_done.png", max_steps: int = 0,
           full_page: bool = True) -> str:
    steps = recording.get("steps", [])
    if max_steps and max_steps > 0:
        steps = steps[:max_steps]
    total = len(steps)
    for i, step in enumerate(steps, 1):
        fr = step.get("frame")
        tag = f"[{i}/{total}] " + (f"(frame={fr}) " if fr else "")
        exec_step(browser, step, values, out_dir, full_page=full_page, tag=tag)
    saved = browser.screenshot(os.path.join(out_dir, screenshot), full_page=full_page)
    print(f"\n📸 スクリーンショット保存: {saved}")
    return saved


def main() -> None:
    p = argparse.ArgumentParser(description="Chrome Recorder JSON の決定論リプレイ（LLM 不要）")
    p.add_argument("--recording", required=True, help="Recorder からエクスポートした JSON")
    p.add_argument("--values", default=None, help="入力値 JSON（{{key}} に埋め込む）")
    p.add_argument("--engine", choices=["selenium", "playwright"], default="playwright",
                   help="ブラウザ駆動エンジン（既定: playwright。Recorder セレクタと相性が良い）")
    p.add_argument("--browser", choices=["edge", "chrome"], default="edge")
    p.add_argument("--out-dir", default="output")
    p.add_argument("--screenshot", default="recording_done.png", help="保存名（日時が自動付与される）")
    p.add_argument("--max-steps", type=int, default=0,
                   help="先頭から指定ステップ数だけ実行（0=全部）。Logout 等の末尾を止めたいときに使う")
    p.add_argument("--viewport-shot", dest="full_page", action="store_false",
                   help="スクショを表示領域（横長）だけにする。既定はページ全体（縦長）")
    p.set_defaults(full_page=True)
    g = p.add_mutually_exclusive_group()
    g.add_argument("--headless", dest="headless", action="store_true")
    g.add_argument("--no-headless", dest="headless", action="store_false")
    p.set_defaults(headless=False)
    args = p.parse_args()

    recording = load_recording(args.recording)
    values = {}
    if args.values:
        import json
        with open(args.values, encoding="utf-8") as f:
            values = json.load(f)

    miss_target = recording
    if args.max_steps and args.max_steps > 0:
        miss_target = {"steps": recording.get("steps", [])[:args.max_steps]}
    miss = missing_placeholders(miss_target, values)
    if miss:
        sys.exit("値が未指定のプレースホルダがあります: " + ", ".join(miss)
                 + "\n--values の JSON に追加してください。")

    os.makedirs(args.out_dir, exist_ok=True)
    browser = make_browser(args.engine, args.browser, args.headless)
    try:
        replay(recording, values, browser, args.out_dir, args.screenshot,
               args.max_steps, args.full_page)
        print("\n✅ リプレイ完了")
    finally:
        browser.quit()


if __name__ == "__main__":
    main()
