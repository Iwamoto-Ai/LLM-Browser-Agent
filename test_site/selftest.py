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
selftest.py — LLM を使わず、browser.py だけでローカルテストサイトを操作し、
配管（ログイン → メニュー → 数値入力 → 登録 → 日時付きスクショ保存）が
正しく動くかを確認する。LLM やネットワーク接続の問題と切り分けるための土台テスト。

手順:
  1) 別ターミナルで:  cd test_site && python -m http.server 8000
  2) このスクリプトを実行:  python test_site/selftest.py --browser edge --no-headless
     （または上の階層から:  python -m test_site.selftest ... ではなく直接パス指定で実行）

成功すると output/ に test_selftest_YYYYMMDD_HHMMSS.png が保存される。
"""

from __future__ import annotations

import argparse
import os
import re
import sys

# 親ディレクトリ（リポジトリ直下）を import パスに追加して browser.py を読む
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from browser_factory import make_browser  # noqa: E402

_LINE_RE = re.compile(r"^\[(\d+)\]\s+<[^>]*>\s+(.*)$")


def find_index(browser, predicate) -> int:
    """公開 state() の出力をパースし、ラベルに predicate が一致する最初の番号を返す。
    Selenium / Playwright どちらのエンジンでも同じ state() 形式なので共通で動く。"""
    for line in browser.state().splitlines():
        m = _LINE_RE.match(line)
        if not m:
            continue
        idx = int(m.group(1))
        label = re.split(r"\s+= 現在値:|\s+選択肢:", m.group(2))[0].strip()
        if predicate({"idx": idx, "label": label}):
            return idx
    raise RuntimeError("要素が見つかりません: " + repr(predicate))


def main() -> None:
    p = argparse.ArgumentParser(description="ローカルテストサイトの自己テスト（LLM 不要）")
    p.add_argument("--url", default="http://localhost:8000")
    p.add_argument("--browser", choices=["edge", "chrome"], default="edge")
    p.add_argument("--engine", choices=["selenium", "playwright"], default="selenium",
                   help="ブラウザ駆動エンジン（既定: selenium）")
    p.add_argument("--user", default=os.environ.get("MY_USERNAME", "demo"))
    p.add_argument("--password", default=os.environ.get("MY_PASSWORD", "password123"))
    p.add_argument("--out-dir", default="output")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--headless", dest="headless", action="store_true")
    g.add_argument("--no-headless", dest="headless", action="store_false")
    p.set_defaults(headless=False)
    args = p.parse_args()

    b = make_browser(args.engine, args.browser, args.headless)
    try:
        print("1) ページを開く"); print(b.navigate(args.url))
        # ログイン
        print("2) ログイン")
        b.input_text(find_index(b, lambda e: "ユーザーID" in e["label"]), args.user)
        b.input_text(find_index(b, lambda e: "パスワード" in e["label"]), args.password)
        b.click(find_index(b, lambda e: e["label"] == "ログイン"))
        # メニュー → 経費登録
        print("3) メニューから経費登録")
        b.click(find_index(b, lambda e: e["label"] == "経費登録"))
        # 数値入力（select / checkbox も含む）
        print("4) 各項目を入力")
        b.select_option(find_index(b, lambda e: "経費区分" in e["label"]), "会議")
        b.input_text(find_index(b, lambda e: "交通費" in e["label"]), "12300")
        b.input_text(find_index(b, lambda e: "宿泊費" in e["label"]), "8000")
        b.input_text(find_index(b, lambda e: "日当" in e["label"]), "3000")
        b.input_text(find_index(b, lambda e: "備考" in e["label"]), "自己テスト")
        b.set_checked(find_index(b, lambda e: "立替払い" in e["label"]), True)
        # 登録
        print("5) 登録")
        b.click(find_index(b, lambda e: e["label"] == "登録"))
        # 検証: 完了メッセージ
        state = b.state()
        # state() の「主なテキスト」に完了見出しが出る。保険で操作可能要素もマーカーに使う。
        ok = "登録が完了しました" in state or "続けて登録" in state
        print("6) 完了メッセージ検出:", "OK" if ok else "NG")
        # 検証: get_page_text で結果テーブルの内容（select/checkbox の反映）を読めるか
        body = b.get_page_text()
        ok_text = ("会議" in body) and ("立替払い" in body)
        print("6b) get_page_text（select/checkbox 反映）:", "OK" if ok_text else "NG")
        ok = ok and ok_text
        # スクショ（日時が自動付与される）
        saved = b.screenshot(os.path.join(args.out_dir, "test_selftest.png"))
        print("7) スクリーンショット保存:", saved)
        exists = os.path.exists(saved)
        print("   ファイル存在:", "OK" if exists else "NG")
        print("\n=== 結果:", "成功 ✅" if (ok and exists) else "失敗 ❌", "===")
        sys.exit(0 if (ok and exists) else 1)
    finally:
        b.quit()


if __name__ == "__main__":
    main()
