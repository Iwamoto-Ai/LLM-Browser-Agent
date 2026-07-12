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

"""ブラウザも LLM も不要の単体テスト（pytest）。CI の ubuntu ジョブで実行する。"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import engine_common as ec  # noqa: E402
import agent_core as ac     # noqa: E402


# ---- engine_common -----------------------------------------------------------

def test_xpath_literal():
    assert ec.xpath_literal("abc") == "'abc'"
    assert ec.xpath_literal('a"b') == "'a\"b'"   # 二重引用符のみ → 単引用符で包む
    assert "concat(" in ec.xpath_literal("a'b\"c")


def test_mask_secrets():
    assert ec.mask_secrets("pw={{SECRET:MY_PASSWORD}}") == "pw=[SECRET:MY_PASSWORD]"


def test_resolve_secrets_basic(monkeypatch):
    monkeypatch.setenv("MY_TOKEN", "s3cr3t")
    monkeypatch.delenv("MY_TOKEN_ALLOWED_DOMAINS", raising=False)
    assert ec.resolve_secrets("v={{SECRET:MY_TOKEN}}") == "v=s3cr3t"


def test_resolve_secrets_missing_env(monkeypatch):
    monkeypatch.delenv("NO_SUCH_SECRET", raising=False)
    with pytest.raises(ValueError):
        ec.resolve_secrets("{{SECRET:NO_SUCH_SECRET}}")


def test_resolve_secrets_domain_allowed(monkeypatch):
    monkeypatch.setenv("MY_TOKEN", "s3cr3t")
    monkeypatch.setenv("MY_TOKEN_ALLOWED_DOMAINS", "example.co.jp, localhost")
    assert ec.resolve_secrets("{{SECRET:MY_TOKEN}}",
                              "https://app.example.co.jp/login") == "s3cr3t"
    assert ec.resolve_secrets("{{SECRET:MY_TOKEN}}",
                              "http://localhost:8000/") == "s3cr3t"


def test_resolve_secrets_domain_denied(monkeypatch):
    monkeypatch.setenv("MY_TOKEN", "s3cr3t")
    monkeypatch.setenv("MY_TOKEN_ALLOWED_DOMAINS", "example.co.jp")
    with pytest.raises(ValueError, match="許可されていません"):
        ec.resolve_secrets("{{SECRET:MY_TOKEN}}", "https://evil.example.com/")
    # 部分文字列では騙せない（notexample.co.jp は不一致）
    with pytest.raises(ValueError):
        ec.resolve_secrets("{{SECRET:MY_TOKEN}}", "https://notexample.co.jp/")


def test_format_state_select_options():
    elems = [{"idx": 0, "tag": "select", "type": "", "label": "経費区分",
              "value": "出張", "options": "出張 / 会議"}]
    out = ec.format_state("http://x/", "t", elems)
    assert "選択肢: 出張 / 会議" in out and '現在値:"出張"' in out


def test_format_page_text_truncates():
    out = ec.format_page_text("http://x/", "t", "あ" * 100, max_chars=10)
    assert "打ち切り" in out


# ---- agent_core: 履歴プルーニング ---------------------------------------------

_STATE = "クリックしました。\n\nURL: http://x/\nタイトル: t\n--- 操作可能な要素 ---\n[0] <a> Home"


def test_prune_state_text():
    pruned = ac.prune_state_text(_STATE)
    assert "--- 操作可能な要素 ---" not in pruned
    assert "クリックしました" in pruned          # 操作メッセージは残る
    assert ac.prune_state_text("エラー: x") == "エラー: x"  # state 無しはそのまま


def test_prune_anthropic_history():
    msgs = []
    for i in range(5):
        msgs.append({"role": "assistant", "content": []})
        msgs.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": str(i), "content": _STATE}]})
    ac.prune_anthropic_history(msgs, keep=2)
    states = [m["content"][0]["content"] for m in msgs if m["role"] == "user"]
    assert sum("--- 操作可能な要素 ---" in s for s in states) == 2
    assert "--- 操作可能な要素 ---" in states[-1]   # 直近は残る


def test_prune_ollama_history():
    msgs = [{"role": "system", "content": "sys"}]
    for i in range(4):
        msgs.append({"role": "tool", "tool_name": "click_element", "content": _STATE})
    ac.prune_ollama_history(msgs, keep=1)
    kept = [m for m in msgs if m.get("role") == "tool"
            and "--- 操作可能な要素 ---" in m["content"]]
    assert len(kept) == 1


# ---- agent_core: 本文 JSON の救済パース ----------------------------------------

def test_parse_text_toolcall():
    text = 'まず入力します {"name": "input_text", "arguments": {"index": 3, "text": "demo"}}'
    assert ac.parse_text_toolcall(text) == ("input_text", {"index": 3, "text": "demo"})
    assert ac.parse_text_toolcall("説明だけの本文") is None
    # 新ツールも認識される
    t2 = '{"name": "select_option", "arguments": {"index": 1, "option": "会議"}}'
    assert ac.parse_text_toolcall(t2) == ("select_option", {"index": 1, "option": "会議"})


# ---- browser（Selenium）: セレクタ変換のみ（ドライバ不要） ----------------------

def test_selenium_text_selector_targets_deepest_node():
    browser_mod = pytest.importorskip("browser")
    b = object.__new__(browser_mod.Browser)   # __init__ を通さずメソッドだけ使う
    cands = b._selector_candidates("text/ログイン")
    xpath = cands[0][1]
    assert "not(.//*[contains" in xpath       # 祖先(<html>)マッチ防止


def test_selenium_aria_selector_role_candidates():
    browser_mod = pytest.importorskip("browser")
    b = object.__new__(browser_mod.Browser)
    cands = b._selector_candidates('aria/Login[role="button"]')
    joined = " | ".join(v for _, v in cands)
    assert "@aria-label" in joined and "//button" in joined
