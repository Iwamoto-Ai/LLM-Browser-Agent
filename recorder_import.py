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
recorder_import.py — Chrome DevTools Recorder の「JSON エクスポート」を読み込み、
このツールで決定論的に再生（リプレイ）できる形に整える。

Recorder JSON の各ステップは type（navigate / click / change / keyDown / scroll …）と、
複数の selectors 候補（css / xpath/ / text/ / aria/ / pierce/）を持つ。これを
browser 層の click_selector / fill_selector / navigate / send_keys / scroll に橋渡しする。

値のパラメータ化:
  * change ステップの value に {{key}} と書くと、--values の JSON から埋め込まれる。
  * パスワード等は {{SECRET:NAME}} と書けば、実値は実行時に環境変数から補完される
    （JSON にもプロンプトにも実値は載らない）。

Recorder（拡張機能不要・Chrome 内蔵）の使い方:
  1. Chrome DevTools → Recorder パネルで操作を記録
  2. 「JSON file」形式でエクスポート（Playwright 形式は拡張機能が要るため JSON を使う）
  3. change の value を {{key}} / {{SECRET:NAME}} に編集
  4. run_recording.py で再生
"""

from __future__ import annotations

import json
import re

# {{key}} を data から埋め込む。{{SECRET:NAME}} はコロンを含むため一致せず温存される。
# {{キー}} を values から埋め込む。\w は日本語も含むため、Excel の日本語列名
# （例 {{プロジェクト番号}}）もそのまま使える。{{SECRET:NAME}} はコロンを含むため
# 一致せず温存される（実行時に環境変数から補完）。
_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


def load_recording(path: str) -> dict:
    """録画/バッチ定義 JSON を読み込む。**行頭コメント対応**:
    行の先頭（空白を除く）が ``//`` または ``#`` で始まる行はコメントとして読み飛ばす。
    行の途中のコメントは非対応（URL の ``http://`` を誤って壊さないための安全設計）。"""
    with open(path, encoding="utf-8-sig") as f:
        lines = [ln for ln in f
                 if not ln.lstrip().startswith(("//", "#"))]
    return json.loads("".join(lines))


def fill_value(text, values: dict):
    """value 内の {{key}} を values で置換。未知キーや {{SECRET:..}} はそのまま残す。"""
    if text is None:
        return text
    return _PLACEHOLDER.sub(
        lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0),
        str(text),
    )


def candidates(step: dict) -> list:
    """step.selectors（[[sel], [sel], ...] 形式）から候補セレクタの一覧を取り出す。"""
    out = []
    for group in step.get("selectors", []):
        if isinstance(group, list) and group:
            out.append(group[0])
        elif isinstance(group, str):
            out.append(group)
    return out


def missing_placeholders(recording: dict, values: dict) -> list:
    """change の value に残る未解決の {{key}}（SECRET 以外）を洗い出す。"""
    miss = set()
    for step in recording.get("steps", []):
        if step.get("type") == "change":
            for m in _PLACEHOLDER.finditer(str(step.get("value", ""))):
                if m.group(1) not in values:
                    miss.add(m.group(1))
    return sorted(miss)
