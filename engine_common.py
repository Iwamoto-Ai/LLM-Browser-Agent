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
engine_common.py — Selenium / Playwright 両エンジンで共有するロジック。

* COLLECT_JS / TEXT_JS / PAGE_TEXT_JS … DOM から情報を集める JavaScript（両エンジン同一仕様）
* resolve_secrets / mask_secrets      … {{SECRET:NAME}} の解決とログ用マスク
* SECRET のドメイン許可リスト          … <NAME>_ALLOWED_DOMAINS でサイトを限定
* format_state                        … state() の出力フォーマット
"""

from __future__ import annotations

import os
import re
from urllib.parse import urlparse

# 可視で操作可能な要素を収集し data-claude-idx を付与して一覧を返す JS。
# disabled / aria-disabled / tabindex="-1"（本来対話的でない要素）は除外する。
COLLECT_JS = r"""
(function () {
  document.querySelectorAll('[data-claude-idx]')
          .forEach(e => e.removeAttribute('data-claude-idx'));
  const nativeSel = 'a, button, input, textarea, select, [role=button], [role=link],' +
              '[role=textbox], [role=checkbox], [role=search], [role=menuitem],' +
              '[contenteditable=true], [onclick]';
  const sel = nativeSel + ', [tabindex]';
  const out = [];
  let i = 0;
  for (const el of document.querySelectorAll(sel)) {
    if (el.type === 'hidden') continue;
    if (el.disabled === true || el.getAttribute('aria-disabled') === 'true') continue;
    // tabindex="-1" だけが理由で拾われた要素（本来フォーカス不能）は除外
    if (el.getAttribute('tabindex') === '-1' && !el.matches(nativeSel)) continue;
    const r = el.getBoundingClientRect();
    const s = window.getComputedStyle(el);
    const visible = r.width > 0 && r.height > 0 &&
                    s.visibility !== 'hidden' && s.display !== 'none' &&
                    s.opacity !== '0';
    if (!visible) continue;
    el.setAttribute('data-claude-idx', i);
    const tag = el.tagName.toLowerCase();
    const isField = tag === 'input' || tag === 'textarea' || tag === 'select' ||
                    el.getAttribute('contenteditable') === 'true';
    let label = (el.getAttribute('aria-label') || el.getAttribute('placeholder') ||
                 el.getAttribute('title') || el.getAttribute('alt') ||
                 el.getAttribute('name') || (isField ? '' : el.innerText) || '').trim();
    label = label.replace(/\s+/g, ' ').slice(0, 100);
    let value = '';
    if (isField) {
      if (tag === 'select') {
        const opt = el.selectedOptions && el.selectedOptions[0];
        value = (opt ? opt.text : el.value || '').trim().replace(/\s+/g, ' ').slice(0, 80);
      } else if (el.type === 'checkbox' || el.type === 'radio') {
        value = el.checked ? 'ON' : 'OFF';
      } else {
        value = (el.value || el.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 80);
      }
    }
    // select は選択肢の一覧も渡す（LLM が select_option の値を選べるように）
    let options = '';
    if (tag === 'select') {
      options = Array.from(el.options).slice(0, 20)
        .map(o => o.text.trim().replace(/\s+/g, ' ')).join(' / ').slice(0, 200);
    }
    out.push({ idx: i, tag: tag, type: el.getAttribute('type') || '',
               label: label, value: value, options: options });
    i++;
  }
  return out;
})()
"""

# ページ内の「主なテキスト」を集める JS。見出しや成功/エラー通知など、操作はできないが
# 状況判断に重要なテキストを LLM に渡すためのもの（例:「登録が完了しました」）。
TEXT_JS = r"""
(function () {
  const out = [];
  const seen = new Set();
  const push = (t) => {
    t = (t || '').trim().replace(/\s+/g, ' ');
    if (t && t.length <= 120 && !seen.has(t)) { seen.add(t); out.push(t); }
  };
  const sel = 'h1, h2, h3, [role=alert], [role=status], [aria-live],' +
              '.alert, .message, .toast, .notification, .success, .badge';
  for (const el of document.querySelectorAll(sel)) {
    const r = el.getBoundingClientRect();
    const s = window.getComputedStyle(el);
    const visible = r.width > 0 && r.height > 0 &&
                    s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0';
    if (visible) push(el.innerText);
  }
  return out.slice(0, 12);
})()
"""

# ページ本文のテキストを取り出す JS（get_page_text 用）。
# 表の中身・照会結果など「読む」用途に使う。
PAGE_TEXT_JS = r"""
(function () {
  const t = (document.body && document.body.innerText) || '';
  return t.replace(/[ \t]+\n/g, '\n').replace(/\n{3,}/g, '\n\n').trim();
})()
"""

SECRET_RE = re.compile(r"\{\{SECRET:([A-Z0-9_]+)\}\}")


def _host_of(url: str | None) -> str:
    try:
        return (urlparse(url or "").hostname or "").lower()
    except Exception:
        return ""


def _domain_allowed(host: str, domains: str) -> bool:
    for d in domains.split(","):
        d = d.strip().lower().lstrip("*").lstrip(".")
        if not d:
            continue
        if host == d or host.endswith("." + d):
            return True
    return False


def resolve_secrets(text: str, current_url: str | None = None) -> str:
    """{{SECRET:NAME}} を環境変数 NAME の値に置換する。

    セキュリティ: 環境変数 <NAME>_ALLOWED_DOMAINS（カンマ区切り）が設定されている場合、
    現在の URL のホストがそのドメイン（またはサブドメイン）に一致しないと拒否する。
    悪意あるページのプロンプトインジェクションで秘密情報を別サイトに入力させられる
    リスクを防ぐ（例: MY_PASSWORD_ALLOWED_DOMAINS=example.co.jp,localhost）。
    """
    def repl(m: re.Match) -> str:
        name = m.group(1)
        val = os.environ.get(name)
        if val is None:
            raise ValueError(f"環境変数 {name} が設定されていません")
        domains = os.environ.get(f"{name}_ALLOWED_DOMAINS")
        if domains:
            host = _host_of(current_url)
            if not _domain_allowed(host, domains):
                raise ValueError(
                    f"SECRET:{name} は現在のサイト（{host or '不明'}）への入力が許可されていません"
                    f"（{name}_ALLOWED_DOMAINS={domains}）。プロンプトインジェクションの"
                    f"可能性があるため入力を拒否しました。")
        return val
    return SECRET_RE.sub(repl, text)


def mask_secrets(text: str) -> str:
    """ログ・モデルへの返答用に {{SECRET:NAME}} → [SECRET:NAME] へ伏せる。"""
    return SECRET_RE.sub(r"[SECRET:\1]", text)


def format_state(url: str, title: str, elems: list, max_elements: int = 120,
                 texts: list | None = None, errors: list | None = None) -> str:
    """state() の共通フォーマット（Selenium / Playwright で同一出力にする）。"""
    lines = []
    for e in elems[:max_elements]:
        t = e["tag"] + (f":{e['type']}" if e.get("type") else "")
        label = e.get("label") or "(ラベルなし)"
        val = e.get("value") or ""
        suffix = f'  = 現在値:"{val}"' if val else ""
        opts = e.get("options") or ""
        opt_suffix = f"  選択肢: {opts}" if opts else ""
        lines.append(f"[{e['idx']}] <{t}> {label}{suffix}{opt_suffix}")
    more = "" if len(elems) <= max_elements else f"\n…他 {len(elems) - max_elements} 要素"
    elist = "\n".join(lines) if lines else "(操作可能な要素なし)"
    text_block = ""
    if texts:
        text_block = "\n--- 主なテキスト ---\n" + "\n".join(texts)
    err_block = ""
    if errors:
        err_block = "\n--- 注意（ページのエラー/警告）---\n" + "\n".join(errors)
    return (f"URL: {url}\nタイトル: {title}\n--- 操作可能な要素 ---"
            f"\n{elist}{more}{text_block}{err_block}")


def format_page_text(url: str, title: str, body: str, max_chars: int = 4000) -> str:
    """get_page_text の共通フォーマット。"""
    body = (body or "").strip()
    trunc = ""
    if len(body) > max_chars:
        body = body[:max_chars]
        trunc = f"\n…（{max_chars} 文字で打ち切り）"
    return f"URL: {url}\nタイトル: {title}\n--- ページ本文 ---\n{body}{trunc}"


def xpath_literal(s: str) -> str:
    """任意の文字列を XPath 1.0 のリテラルにする（' と \" が混在しても安全）。"""
    if "'" not in s:
        return f"'{s}'"
    if '"' not in s:
        return f'"{s}"'
    parts = s.split("'")
    return "concat(" + ", \"'\", ".join(f"'{p}'" for p in parts) + ")"
