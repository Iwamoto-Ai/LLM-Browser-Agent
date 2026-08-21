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

"""Power Automate Desktop（PAD）版バッチの**参照実装**。

PAD には Web 自動化用のブラウザ拡張機能が必要だが、**WebDriver は拡張とは無関係**で、
`msedgedriver.exe` 自体がローカルの HTTP サーバーとして動く。したがって
「HTTP リクエストを送れるツール」があれば拡張なしでブラウザを操作できる。
PAD の「Web サービスの呼び出し」がまさにそれに当たる。

このスクリプトは **PAD が送るのと同じ HTTP 呼び出しを、同じ順序で送る**ことだけを行う
（Selenium も Playwright も使わず、Python 標準ライブラリの urllib のみ）。自宅で本スクリプトを
練習サイトに対して流して成功を確認し、`--trace` で出力される「HTTP 呼び出しの実物」を
そのまま PAD のフローに書き写す、という使い方を想定している。

設計上の要点:
  * 要素の特定と操作は **`/execute/sync`（JavaScript 実行）に一本化**する。
    W3C 標準の「要素を検索して要素 ID を得る → その ID を操作する」方式は往復が増え、
    `element-6066-11e4-a52e-4f735466cecf` という長いキーの取り回しが PAD では煩雑なため。
    結果として PAD 側は**同じ形の HTTP 呼び出し 1 種類**を用意し、送る引数を変えるだけで済む。
  * セレクタは既存の録画 JSON の候補リストをそのまま使える（css / xpath/ / text/ / aria/ / pierce/）。
    候補は JS 側で順に試し、最初に見つかったものを操作する。

使い方（例）:
  # 1) 別ターミナルで WebDriver を起動しておく
  #    msedgedriver.exe --port=9515
  # 2) 練習サイトに対してバッチを流し、PAD 用の手順書を出力する
  python pad_webdriver_ref.py --batch recordings/edi2_practice_batch.json \
      --details data/edi2_practice_batch.csv --trace output/pad_trace.md
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime

# 変換器の版。ブラウザ版（tools/pad_converter.html）と必ず同じ値にすること。
# 生成物の先頭に「# 変換器：…」として出るので、持ち込まれた Robin を見たときに
# どちらで、どの版で作られたものかが分かる。tools/verify_parity.mjs は
# この行だけ比較から外している（種類が違うので必ず食い違うため）。
CONVERTER_VERSION = "1.0.0"
CONVERTER_KIND = "Python版"

from engine_common import mask_secrets, resolve_secrets
from recorder_import import fill_value, load_recording
from details_io import load_details

# ---------------------------------------------------------------------------
# 要素の特定と操作をまとめて行う JavaScript。
# 引数: arguments[0]=セレクタ候補の配列, arguments[1]=操作, arguments[2]=値
# 戻り値: {"ok": true/false, "used": 実際に一致したセレクタ}
# PAD へはこの文字列を 1 行にして貼り付ける（--trace の出力にそのまま含まれる）。
# ---------------------------------------------------------------------------
JS_ACT = r"""
var cands = arguments[0], action = arguments[1], value = arguments[2];
var Q = String.fromCharCode(39), DQ = String.fromCharCode(34);
function lit(s) { if (s.indexOf(Q) < 0) { return Q + s + Q; } return DQ + s + DQ; }
function byXPath(xp) {
  try { return document.evaluate(xp, document, null, 9, null).singleNodeValue; }
  catch (e) { return null; }
}
function find(sel) {
  try {
    if (sel.indexOf(`id/`) === 0) { return document.getElementById(sel.slice(3)); }
    if (sel.indexOf(`xpath/`) === 0) { return byXPath(sel.slice(6)); }
    if (sel.indexOf(`text/`) === 0) {
      var t = sel.slice(5).trim();
      return byXPath(`//*[not(self::script) and normalize-space(text())=` + lit(t) + `]`);
    }
    if (sel.indexOf(`aria/`) === 0) {
      var n = sel.slice(5).split(`[`)[0].trim();
      var el = document.querySelector(`[aria-label=` + lit(n) + `]`);
      if (el) { return el; }
      return byXPath(`//*[not(self::script) and (@aria-label=` + lit(n)
                     + ` or @title=` + lit(n) + ` or normalize-space(text())=` + lit(n) + `)]`);
    }
    if (sel.indexOf(`pierce/`) === 0) { sel = sel.slice(7); }
    return document.querySelector(sel);
  } catch (e) { return null; }
}
if (action === `exists`) {
  var body = document.body || document.documentElement;
  var txt = (body && (body.innerText || body.textContent)) || ``;
  return { ok: txt.indexOf(value) >= 0, used: null };
}
for (var i = 0; i < cands.length; i++) {
  var el = find(cands[i]);
  if (!el) { continue; }
  if (action === `click`) {
    try { el.scrollIntoView({ block: `center` }); } catch (e) {}
    el.click();
  } else if (action === `fill`) {
    el.focus();
    el.value = value;
    el.dispatchEvent(new Event(`input`, { bubbles: true }));
    el.dispatchEvent(new Event(`change`, { bubbles: true }));
  }
  return { ok: true, used: cands[i] };
}
return { ok: false, used: null };
"""


def js_act_oneline() -> str:
    """JS_ACT を 1 行にする（Robin の文字列リテラルや JSON へ安全に埋め込むため）。
    JS_ACT は二重引用符とバックスラッシュを含まない書き方に統一してあるので、
    JSON へ入れてもエスケープが発生せず、PAD 側でも壊れない。"""
    return " ".join(line.strip() for line in JS_ACT.strip().splitlines() if line.strip())


class WebDriverHTTP:
    """W3C WebDriver を HTTP で直接叩く最小クライアント（標準ライブラリのみ）。"""

    def __init__(self, base_url: str = "http://127.0.0.1:9515",
                 browser_name: str = "MicrosoftEdge", trace: list | None = None):
        self.base = base_url.rstrip("/")
        self.browser_name = browser_name
        self.session_id: str | None = None
        self.trace = trace if trace is not None else []

    # ---- 低レベル ---------------------------------------------------------
    def _call(self, method: str, path: str, body: dict | None = None,
              note: str = "", trace_body: dict | None = None):
        """trace_body を渡した場合は、記録にはそちら（秘密情報を含まない版）を残す。
        実際に送信するのは常に body。"""
        url = self.base + path
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json; charset=utf-8")
        # PAD に書き写すための記録（秘密情報は解決前＝プレースホルダのまま残す）
        shown = trace_body if trace_body is not None else body
        if shown is not None:
            shown = json.loads(mask_secrets(json.dumps(shown, ensure_ascii=False)))
        self.trace.append({"method": method, "path": path, "body": shown, "note": note})
        try:
            # localhost へはプロキシを経由させない（PAD でも同じ配慮が要る）
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(req, timeout=60) as res:
                payload = json.loads(res.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            try:
                v = json.loads(detail).get("value", {})
                msg = f'{v.get("error", "")}: {v.get("message", "")[:200]}'
            except Exception:
                msg = detail[:200]
            raise RuntimeError(f"WebDriver エラー [{method} {path}] {msg}") from None
        except urllib.error.URLError as e:
            raise RuntimeError(
                f"WebDriver に接続できません（{self.base}）: {e.reason}. "
                "msedgedriver.exe が起動しているか、プロキシ除外設定を確認してください。"
            ) from None
        return payload.get("value")

    # ---- セッション -------------------------------------------------------
    def start(self) -> str:
        body = {"capabilities": {"alwaysMatch": {"browserName": self.browser_name}}}
        value = self._call("POST", "/session", body, note="セッション開始（ブラウザ起動）")
        self.session_id = (value or {}).get("sessionId")
        if not self.session_id:
            raise RuntimeError("セッション ID を取得できませんでした")
        return self.session_id

    def _s(self, tail: str) -> str:
        return f"/session/{self.session_id}{tail}"

    def quit(self) -> None:
        if self.session_id:
            try:
                self._call("DELETE", self._s(""), note="セッション終了（ブラウザを閉じる）")
            except Exception:
                pass
            self.session_id = None

    # ---- 操作 -------------------------------------------------------------
    def navigate(self, url: str) -> None:
        self._call("POST", self._s("/url"), {"url": url}, note=f"ページを開く: {url}")

    def set_window(self, width: int, height: int) -> None:
        self._call("POST", self._s("/window/rect"),
                   {"width": int(width), "height": int(height)},
                   note=f"ウィンドウサイズ {width}x{height}")

    def execute(self, script: str, args: list, note: str = "",
                trace_args: list | None = None):
        trace_body = None
        if trace_args is not None:
            trace_body = {"script": script, "args": trace_args}
        return self._call("POST", self._s("/execute/sync"),
                          {"script": script, "args": args},
                          note=note, trace_body=trace_body)

    def screenshot(self, path: str) -> str:
        """スクリーンショットを保存する。ファイル名末尾に _YYYYMMDD_HHMMSS を付ける。
        （PAD では base64 を扱う代わりに、PAD 標準の「スクリーンショットを取得」でもよい）"""
        b64 = self._call("GET", self._s("/screenshot"), note="スクリーンショット取得（base64）")
        root, ext = os.path.splitext(path)
        ext = ext or ".png"
        out = f"{root}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext}"
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        with open(out, "wb") as f:
            f.write(base64.b64decode(b64))
        return os.path.abspath(out)

    # ---- 高レベル（JS 一本化） -------------------------------------------
    def act(self, candidates: list, action: str, value: str = "", note: str = "") -> dict:
        resolved = resolve_secrets(value) if action == "fill" else value
        res = self.execute(JS_ACT, [list(candidates), action, resolved],
                           note=note,
                           trace_args=[list(candidates), action, value]) or {}
        if not res.get("ok"):
            raise RuntimeError(
                f"要素が見つからないか操作できません（action={action}, 候補={candidates}）")
        return res


# ---------------------------------------------------------------- ステップ実行
def _candidates(step: dict) -> list:
    """録画 JSON の selectors（[[sel], [sel], ...]）を平坦な候補リストにする。"""
    out = []
    for group in step.get("selectors", []):
        if isinstance(group, list):
            out.extend([s for s in group if isinstance(s, str)])
        elif isinstance(group, str):
            out.append(group)
    return out


def exec_step(drv: WebDriverHTTP, step: dict, values: dict, out_dir: str,
              log=print, tag: str = "") -> None:
    t = step.get("type")
    if t == "comment":
        log(f"  {tag}💬 {fill_value(step.get('text', ''), values)}")
        return
    if t == "setViewport":
        w, h = step.get("width"), step.get("height")
        if w and h:
            drv.set_window(w, h)
            log(f"  {tag}ウィンドウサイズ → {w}x{h}")
        return
    if t == "navigate":
        url = fill_value(step.get("url", ""), values)
        drv.navigate(url)
        log(f"  {tag}navigate {url}")
        return
    if t in ("click", "doubleClick"):
        cands = [fill_value(s, values) for s in _candidates(step)]
        res = drv.act(cands, "click", note=f"クリック {cands[:1]}")
        log(f"  {tag}クリック: {res.get('used')}")
        return
    if t == "change":
        cands = [fill_value(s, values) for s in _candidates(step)]
        val = fill_value(step.get("value", ""), values)
        res = drv.act(cands, "fill", val, note=f"入力 {cands[:1]}")
        log(f"  {tag}入力: {res.get('used')} ← 「{mask_secrets(val)}」")
        return
    if t == "screenshot":
        name = fill_value(step.get("name", "screenshot"), values)
        saved = drv.screenshot(os.path.join(out_dir, name + ".png"))
        log(f"  {tag}📸 {saved}")
        return
    if t == "assertText":                      # 完了メッセージの確認（任意）
        text = fill_value(step.get("text", ""), values)
        res = drv.act([], "exists", text, note=f"完了確認: {text}")
        log(f"  {tag}✔ 画面に「{text}」を確認")
        return
    log(f"  {tag}{t} … 未対応のためスキップ")


# ---------------------------------------------------------------- バッチ本体
def run(batch: dict, rows: list, common: dict, drv: WebDriverHTTP, out_dir: str,
        id_col: str, log=print, stop_on_error: bool = False) -> list:
    setup = batch.get("setup", [])
    loop = batch.get("loop", [])
    recover = batch.get("recover", [])
    teardown = batch.get("teardown", [])
    results = []

    log(f"── セットアップ（{len(setup)} ステップ）──")
    for i, st in enumerate(setup, 1):
        exec_step(drv, st, common, out_dir, log=log, tag=f"[setup {i}/{len(setup)}] ")

    total = len(rows)
    for n, row in enumerate(rows, 1):
        rid = str(row.get(id_col, "")).strip()
        if str(row.get("skip", "")).strip():
            log(f"[{n}/{total}] {rid} … スキップ（skip 列指定）")
            results.append({"ID": rid, "結果": "スキップ", "理由": "", "エビデンス": ""})
            continue
        values = dict(common)
        values.update(row)
        log(f"── [{n}/{total}] {rid} 開始 ──")
        shot = ""
        try:
            for i, st in enumerate(loop, 1):
                exec_step(drv, st, values, out_dir, log=log,
                          tag=f"[{n}/{total} step {i}/{len(loop)}] ")
                if st.get("type") == "screenshot":
                    shot = fill_value(st.get("name", ""), values)
            results.append({"ID": rid, "結果": "成功", "理由": "", "エビデンス": shot})
            log(f"── [{n}/{total}] {rid} ✅ 成功 ──")
        except Exception as e:
            reason = str(e)[:300]
            log(f"── [{n}/{total}] {rid} ❌ 失敗: {reason} ──")
            try:
                drv.screenshot(os.path.join(out_dir, f"fail_{rid}.png"))
            except Exception:
                pass
            results.append({"ID": rid, "結果": "失敗", "理由": reason, "エビデンス": ""})
            if stop_on_error:
                break
            for i, st in enumerate(recover, 1):
                try:
                    exec_step(drv, st, values, out_dir, log=log,
                              tag=f"[recover {i}/{len(recover)}] ")
                except Exception:
                    pass

    for i, st in enumerate(teardown, 1):
        try:
            exec_step(drv, st, common, out_dir, log=log,
                      tag=f"[teardown {i}/{len(teardown)}] ")
        except Exception:
            pass
    return results


# ---------------------------------------------------------------- trace 出力
def write_trace(trace: list, path: str, batch_title: str) -> str:
    """PAD に書き写すための「HTTP 呼び出しの実物」を Markdown で出力する。"""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    lines = [
        f"# PAD 手順書（自動生成）: {batch_title}",
        "",
        "各行が PAD の「Web サービスの呼び出し」1 アクションに対応する。",
        "URL の `{session}` は、最初の POST /session の応答から取り出した `value.sessionId` を入れる。",
        "秘密情報は `{{SECRET:...}}` のまま記載しているので、PAD 側で資格情報の変数に置き換えること。",
        "",
        "| # | メソッド | URL | 本文（JSON） | 意味 |",
        "|---|---|---|---|---|",
    ]
    import re
    for i, c in enumerate(trace, 1):
        # 実セッション ID を {session} に伏せる（毎回変わる値なので手順書には残さない）
        path_disp = re.sub(r"^/session/[^/]+", "/session/{session}", c["path"])
        body = c["body"]
        if body is None:
            body_disp = "（なし）"
        elif isinstance(body, dict) and "script" in body:
            # JS 本文は全ステップ共通なので、変わる部分（args）だけを載せる
            s = json.dumps(body.get("args", []), ensure_ascii=False)
            body_disp = "`script`=共通JS, `args`=" + "`" + s.replace("|", "\\|") + "`"
        else:
            s = json.dumps(body, ensure_ascii=False)
            body_disp = "`" + s.replace("|", "\\|") + "`"
        lines.append(f"| {i} | {c['method']} | `{path_disp}` | {body_disp} | {c['note']} |")
    lines += [
        "",
        "## 共通で使う JavaScript（`/execute/sync` の `script` に入れる）",
        "",
        "```javascript",
        JS_ACT.strip(),
        "```",
        "",
        "PAD では上記を 1 つのテキスト変数に入れておき、`args` だけを差し替える。",
        "`args` は `[[セレクタ候補の配列], \"click\" か \"fill\", 入力値]` の形。",
    ]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return os.path.abspath(path)


def _robin_js_chunks(js: str, width: int = 100) -> list:
    """長い 1 行は PAD への貼り付けで無視されるため、JS を短い行に分割して連結する。

      SET JsAct TO $'''<1つ目>'''
      SET JsAct TO $'''%JsAct%<2つ目>'''   ← %JsAct% で前の内容に継ぎ足す

    分割位置が単引用符に隣接すると `''''` のような紛らわしい並びになるため、
    境界が `'` に当たらないよう 1 文字ずつずらす。"""
    chunks, i = [], 0
    while i < len(js):
        end = min(i + width, len(js))
        while end < len(js) and (js[end - 1] == "'" or js[end] == "'"):
            end += 1
        chunks.append(js[i:end])
        i = end
    lines = []
    for n, c in enumerate(chunks):
        head = "" if n == 0 else "%JsAct%"
        lines.append(f"SET JsAct TO $'''{head}{c}'''")
    return lines


def _robin_safe_selector(sel: str) -> str:
    """Robin の $'''…''' リテラルには**単引用符を入れられない**（PAD が黙って無視する）。
    そこで `xpath///*[@id="X"]` のような形は、引用符の要らない `id/X` に変換する。
    それでも引用符が残る候補は Robin 生成時に落とす（_robin_filter_candidates）。"""
    m = re.match(r'^xpath//\*\[@id=[\'"]([^\'"]+)[\'"]\]$', sel)
    if m:
        return "id/" + m.group(1)
    m = re.match(r'^xpath///\*\[@id=[\'"]([^\'"]+)[\'"]\]$', sel)
    if m:
        return "id/" + m.group(1)
    # aria/名前[role="link"] のような属性の付いた形は、名前の部分しか使わない
    # （共通 JavaScript が [ 以降を切り落とす）。ここで先に切っておけば、
    # 二重引用符が理由で候補ごと落ちるのを避けられる。
    if sel.startswith("aria/") and "[" in sel:
        return "aria/" + sel[5:].split("[")[0].strip()
    return sel


def _is_unique_id(sel: str) -> bool:
    """id 1 つだけで要素を指す候補か。#foo や id/foo を指す。

    #foo .bar のように他の条件が付くもの、xpath/… や pierce/… は対象外。
    xpath///*[@id="foo"] は _robin_safe_selector が id/foo に直している。"""
    if sel.startswith("id/"):
        return len(sel) > 3
    if not sel.startswith("#"):
        return False
    body = sel[1:]
    return bool(body) and not any(ch in body for ch in " >+~,.:[")


def _robin_filter_candidates(cands: list) -> list:
    """Robin リテラルや JSON 本文に入れられない候補を落とす。

    * 単引用符 … Robin の $'''…''' に入れると PAD が黙って無視する
    * 二重引用符 … 本文は {"script": "…", "args": […]} という JSON なので、
      候補の中に生の " があるとそこで文字列が閉じ、WebDriver が
      「invalid argument: missing command parameters」を返す

    そのうえで、**id で指す候補を先頭に寄せる**。録画は aria/名前 を先に出すが、
    同じ名前が画面に複数あると別の要素に当たる。押しても何も起きない要素でも
    クリックは成功するので、そのまま先へ進んで後のステップで落ちる。
    id はページ内で一意なので、こちらを先に試すほうが確実。
    id が動的に変わるサイトでも、当たらなければ次の候補へ落ちるだけ。

    すべて落ちてしまう場合は、CSS の id セレクタなど代替を残せないか呼び出し側で確認する。"""
    out = []
    for x in cands:
        c = _robin_safe_selector(x)
        if "'" in c or '"' in c:
            continue
        out.append(c)
    out.sort(key=lambda c: 0 if _is_unique_id(c) else 1)
    return out


def _robin_col_var(col: str, cols: list) -> str:
    """列名 → Robin の変数名（ASCII）。%Row['列名']% はリテラル内に単引用符が入り
    PAD が貼り付けを無視するため、ループ先頭で変数に取り出して %Col1% の形で使う。

    Col 番号は「ID 列を必ず Col1」にそろえる（write_robin が cols を id_col で
    事前に埋める）。以降は録画での出現順。"""
    if col not in cols:
        cols.append(col)
    return f"%Col{cols.index(col) + 1}%"


def _to_robin_var(text: str, cols: list) -> str:
    """{{列名}} を Robin の変数参照 %Col1% 等に変換する（{{SECRET:…}} は対象外）。"""
    return re.sub(r"\{\{(?!SECRET:)(\w+)\}\}",
                  lambda m: _robin_col_var(m.group(1), cols), str(text))


def _robin_str(s: str) -> str:
    """Robin の文字列リテラル。実機で確認した規則:
      * バックスラッシュは `\\\\` に二重化する（`\\%` は「エスケープされた %」と解釈され、
        変数展開の `%` が対応しなくなって貼り付けが無視される）
      * 単引用符は `\\'` にエスケープする（生のままだと貼り付けが無視される）
    なお `%…%` は変数展開なので、そのまま埋め込みたい値に `%` を含めないこと。"""
    return "$'''" + s.replace("\\", "\\\\").replace("'", "\\'") + "'''"


def _robin_under_base(path_str: str, out_dir: str) -> str:
    """out_dir 配下のパスは %BaseDir% 相対のリテラルにする。

    配布時に直すのが BaseDir の 1 行だけで済むようにするため。
    out_dir の外にあるパスは絶対パスのまま出す。"""
    base = out_dir.rstrip("\\/")
    sep = "\\"
    if path_str.lower().startswith((base + sep).lower()):
        rest = path_str[len(base) + 1:]
        esc = rest.replace("\\", "\\\\").replace("'", "\\'")
        return "$'''%BaseDir%" + "\\\\" + esc + "'''"
    return _robin_str(path_str)


def _safe_comment(text: str, cols: list) -> str:
    """Robin のコメント行に出す文字列。

    {{列名}} は変数参照に変換されるが、{{SECRET:…}} は変換対象外なので
    そのまま書くと生成物に未解決のプレースホルダが残る。
    コメントに秘密情報の名前を出す必要はないため、角かっこ表記に置き換える。"""
    t = _to_robin_var(text, cols)
    t = re.sub(r"\{\{SECRET:([^}]*)\}\}", r"[SECRET:\1]", t)
    t = t.replace("{{", "[").replace("}}", "]")
    return t


# ---------------------------------------------------------------- Robin 部品
# 実機で確認した必須引数。EncodeRequestBody: False が無いと本文が URL エンコードされ、
# WebDriver が invalid argument: missing command parameters を返して何も動かない。
_WEB_FLAGS = "EncodeRequestBody: False FailOnErrorStatus: False"


def _web(url: str, method: str, body: str, resp: str, status: str,
         indent: str = "") -> str:
    """Web サービス呼び出し 1 行。body が None なら RequestBody を省く（GET/DELETE 用）。"""
    b = f"RequestBody: {body} " if body else ""
    return (f"{indent}Web.InvokeWebService.InvokeWebService Url: {url} "
            f"Method: Web.Method.{method} Accept: AppJson ContentType: AppJson "
            f"{b}{_WEB_FLAGS} Response=> {resp} StatusCode=> {status}")


def _robin_shot(indent: str, file_var: str) -> list:
    """エビデンス取得。WebDriver の /screenshot はページの表示領域だけを返すので、
    デスクトップや他ウィンドウが写り込まず、フォーカスにも依存しない。
    変数名を ActObj / ActResp と分けるのは、直前の ok 判定を壊さないため。"""
    return [
        _web("ShotUrl", "Get", None, "ShotResp", "ShotStatus", indent),
        f"{indent}Variables.ConvertJsonToCustomObject Json: ShotResp CustomObject=> ShotObj",
        f"{indent}SET ShotB64 TO ShotObj['value']",
        f"{indent}File.ConvertFromBase64 Base64Text: ShotB64 File: {file_var} "
        f"IfFileExists: File.IfExists.DoNothing",
    ]


def _robin_fail(indent: str) -> list:
    """RowError が立っていたら、エビデンスと結果を記録して次の件へ。
    PrevFailed は件の先頭で True に置いてあるので、ここで触る必要はない。"""
    ind2 = indent + "    "
    return [
        f"{indent}IF RowError <> $'''''' THEN",
        f"{ind2}SET NgCount TO NgCount + 1",
        *_robin_shot(ind2, "FailShot"),
        f"{ind2}File.WriteText File: ResultFile "
        f"TextToWrite: $'''%RowId%,%RowKey%,失敗,\"%RowError%\",\"%FailShot%\",%RecStamp%''' "
        f"AppendNewLine: True IfFileExists: File.IfFileExists.Append",
        f"{ind2}File.WriteText File: LogFile "
        f"TextToWrite: $'''[%RecStamp%] %RowId% / %RowKey% 失敗 %RowError%''' "
        f"AppendNewLine: True IfFileExists: File.IfFileExists.Append",
        # WebDriver の生の応答も残す。error と message に理由がそのまま入るので、
        # 「要素が見つかりません」だけでは分からないときの手がかりになる。
        f"{ind2}File.WriteText File: LogFile "
        f"TextToWrite: $'''[%RecStamp%] 応答 %ActResp%''' "
        f"AppendNewLine: True IfFileExists: File.IfFileExists.Append",
        f"{ind2}NEXT LOOP",
        f"{indent}END",
    ]


def _robin_act(cands: list, action: str, value: str, indent: str, note: str,
               step_no: int, cols: list) -> list:
    """要素操作 1 ステップ分の Robin（本文組み立て → Web サービス呼び出し → 成否判定）。"""
    cands = [_to_robin_var(c, cols) for c in _robin_filter_candidates(cands)]
    value = _to_robin_var(value, cols)
    # 注記はリテラルに入るため、単引用符を含めない形に整える
    note = _to_robin_var(note, cols).replace("'", "").replace("[", "").replace("]", "")
    body_args = json.dumps([cands, action, value], ensure_ascii=False)
    # %JsAct% は Robin 側で展開させたいので、文字列のまま残す
    # exists は「文字列が見つからない」、click/fill は「要素が見つからない」
    why = "画面に文字列がありません" if action == "exists" else "で要素が見つかりません"
    reason = (f"ステップ{step_no}（{note}）{why}" if action == "exists"
              else f"ステップ{step_no}（{note}）{why}")
    return [
        f"{indent}# [{step_no}] {note}",
        f"{indent}SET ActBody TO $'''{{\"script\": \"%JsAct%\", \"args\": {body_args}}}'''",
        _web("ExecUrl", "Post", "ActBody", "ActResp", "ActStatus", indent),
        # 応答コードを先に見る。WebDriver がエラーを返すと value の中身が
        # error/message に入れ替わり、ok が無くなる。そのまま読みに行くと
        #「プロパティがありません」という、原因の分からないエラーになる。
        f"{indent}IF ActStatus <> 200 THEN",
        f"{indent}    SET RowError TO $'''ステップ{step_no}（{note}）で WebDriver が"
        f"エラーを返しました（HTTP %ActStatus%）'''",
        f"{indent}END",
        f"{indent}IF ActStatus = 200 THEN",
        f"{indent}    Variables.ConvertJsonToCustomObject Json: ActResp CustomObject=> ActObj",
        f"{indent}    IF ActObj['value']['ok'] <> True THEN",
        f"{indent}        SET RowError TO $'''{reason}'''",
        f"{indent}    END",
        f"{indent}END",
    ]


def _robin_act_best_effort(cands: list, action: str, value: str, indent: str,
                           note: str, cols: list) -> list:
    """復帰処理や後片付け用。成否を判定せず、通るところまで進める。"""
    cands = [_to_robin_var(c, cols) for c in _robin_filter_candidates(cands)]
    value = _to_robin_var(value, cols)
    note = _to_robin_var(note, cols).replace("'", "").replace("[", "").replace("]", "")
    body_args = json.dumps([cands, action, value], ensure_ascii=False)
    return [
        f"{indent}# {note}",
        f"{indent}SET ActBody TO $'''{{\"script\": \"%JsAct%\", \"args\": {body_args}}}'''",
        _web("ExecUrl", "Post", "ActBody", "ActResp", "ActStatus", indent),
        f"{indent}WAIT 1",
    ]


def _prescan_cols(steps: list, cols: list) -> None:
    """{{列名}} の参照を先に全部拾って cols を確定させる。

    結果 CSV のヘッダーを書く時点で列名が分かっていないと、業務キーの列名が
    プレースホルダのまま出力されてしまうため、emit の前に 1 周する。
    登録順は emit 時と同じなので Col 番号はずれない。"""
    for st in steps:
        for sel in _candidates(st):
            _to_robin_var(sel, cols)
        for key in ("value", "text", "name", "url"):
            v = st.get(key)
            if v is not None:
                _to_robin_var(v, cols)


def _lint_robin(lines: list, log=print) -> list:
    """生成した Robin を貼り付ける前に、実機で判明している落とし穴を機械的に洗う。

    PAD は解釈できない行をエラーも出さずに無視するため、生成時に気づけないと
    「貼り付けたのに一部のアクションが無い」という形で後から発覚する。
    検出するもの:
      * 長すぎる 1 行（黙って無視される）
      * `SET x TO %y%` — 変数を変数に代入するとき % で囲んではいけない
      * Web サービス呼び出しに EncodeRequestBody: False が無い
      * $'''…''' の中のエスケープされていない単引用符
      * 実機で貼り付けを確認していない列挙値（Display.Icon.Error で貼り付けが落ちた）
    """
    # 実機で貼り付けを確認済みの列挙値だけを許す。PAD は解釈できない値の行を
    # 黙って捨てるため、UI に選択肢があっても Robin の綴りが同じとは限らない。
    known_enums = {
        "Display.Icon": {"None", "Information", "Warning", "Question"},
        "Display.Buttons": {"OK", "OKCancel"},
        "Display.DefaultButton": {"Button1", "Button2"},
        "Web.Method": {"Get", "Post", "Delete"},
        "File.IfFileExists": {"Append", "Overwrite"},
        "File.IfExists": {"DoNothing"},
    }
    warns = []
    for i, ln in enumerate(lines, 1):
        s = ln.strip()
        # 未解決のプレースホルダはコメント行に残っていても不可。
        # 列名やSECRETの変換漏れをここで捕まえる。閉じかっこ側は見ない
        # （WebDriver の JSON 本文が正当に }}} で終わるため）。
        if "{{" in s:
            warns.append(f"{i}行: 未解決のプレースホルダが残っています: {s[:80]}")
        if s.startswith("#"):
            continue
        if len(ln) > 700:
            warns.append(f"{i}行: 1行が長すぎます（{len(ln)}文字）。分割してください")
        m = re.match(r"^SET\s+\w+\s+TO\s+%(\w+)%\s*$", s)
        if m:
            warns.append(
                f"{i}行: SET の右辺で % を使っています。"
                f"変数の代入は `TO {m.group(1)}` と裸で書きます: {s}")
        if "InvokeWebService" in s and "EncodeRequestBody: False" not in s:
            warns.append(f"{i}行: EncodeRequestBody: False がありません（本文がURLエンコードされます）")
        for ns, ok in known_enums.items():
            for val in re.findall(re.escape(ns) + r"\.(\w+)", s):
                if val not in ok:
                    warns.append(
                        f"{i}行: {ns}.{val} は実機で未確認の列挙値です。"
                        f"確認済み: {'/'.join(sorted(ok))}")
        for lit in re.findall(r"\$'''(.*?)'''", s):
            body = lit.replace("\\'", "")
            if "'" in body:
                warns.append(f"{i}行: リテラル内の単引用符が未エスケープです（\\' にする）: {s[:80]}")
        # JSON 本文に生の二重引用符が混ざっていないか。
        # {"script": "…", "args": […]} の中で " が閉じてしまうと、WebDriver は
        # 「invalid argument: missing command parameters」を返す。
        # 例: aria/検収照会[role="link"] のようなセレクタをそのまま埋めた場合。
        key = 'args\\": ['
        if key in s:
            args_part = s.split(key, 1)[1]
            if '"' in args_part.replace('\\"', ""):
                warns.append(
                    f"{i}行: JSON 本文の args に生の二重引用符が入っています。"
                    f"そのままだと WebDriver がエラーを返します: {s[:80]}")
    for w in warns:
        log(f"  ⚠ {w}")
    return warns


Q_ = "'''"   # Robin のリテラル区切り

def write_robin(batch: dict, details_path: str, id_col: str, path: str,
                shot_name: str = "%RowId%__%RowKey%__%Stamp%",
                driver_exe: str = r"C:\temp\msedgedriver.exe",
                out_dir: str = r"C:\temp", proxy: str = "",
                auto_driver: bool = False,
                browser: str = "edge") -> str:
    """PAD に貼り付けられる Robin コードを生成する。

    PAD のフローデザイナーはアクションのコピー＆ペーストにテキスト（Robin）を使うため、
    生成したコードをキャンバスに貼り付ければフローが組み上がる。

    生成されるフローの構造（docs/PAD_WebDriver.md と対応）:
      setup   … ドライバ起動 → セッション → ログイン → 起点へ移動 → 失敗検知(Halt)
      loop    … skip 判定 / 再実行絞り込み / 件数上限 / 復帰 / 1 件分の操作 / エビデンス
      recover … 失敗した件のあと、次の件の前に起点へ戻す（batch の recover を使う）
    """
    js_one = js_act_oneline()
    # ID 列を必ず Col1 にそろえる（明細 CSV の先頭列 = ID という運用に合わせる）
    cols: list = [id_col]
    L: list = []
    A = L.append

    setup = batch.get("setup", [])
    loop_steps = batch.get("loop", [])
    # 起点画面の判定に使う「ループ最初の操作対象」。手動ログインの案内でも
    # 「何が見える画面まで進むのか」を出したいので、ここで先に求めておく。
    # 明細の値を含む候補は、1 件目の値が分からないので判定に使えない。
    first_target = None
    for _st in loop_steps:
        if _st.get("type") in ("click", "doubleClick", "change"):
            _cands = _robin_filter_candidates(_candidates(_st))
            if _cands and not any("{{" in c for c in _cands):
                first_target = _cands
            break
    origin_hint = _origin_hint(batch, first_target or [])
    recover = batch.get("recover", [])
    teardown = batch.get("teardown", [])

    # 列名を先に確定させる（結果 CSV のヘッダーで業務キーの列名が必要）
    for _sec in (setup, loop_steps, recover, teardown):
        _prescan_cols(_sec, cols)

    # 起点へ戻る URL（recover が空のときのフォールバックに使う）
    start_url = ""
    for st in setup:
        if st.get("type") == "navigate":
            start_url = st.get("url", "")
            break

    A("# ============================================================")
    A("# 自動生成 PADコード(Robin)")
    A("# ============================================================")
    A("# 【メモ欄】自動で分かる範囲を初期値として入れてある。適宜書き換えて使う。")
    _mtitle = _safe_comment(str(batch.get("title", "")).strip(), cols)
    _mloop = len([s for s in loop_steps if s.get("type") != "comment"])
    _mkeys = " ／ ".join(cols[1:]) if len(cols) > 1 else "なし"
    A(f"# タイトル: {_mtitle}")
    A(f"# 処理内容：明細 1 件につき {_mloop} 操作を繰り返す"
      f"（ID列: {id_col} ／ 業務キー: {_mkeys}）")
    if start_url:
        A(f"#           開始URL: {start_url}")
    # 変換環境が Linux/macOS でも Windows パスの末尾を取り出せるようにする
    _mcsv = details_path.replace("\\", "/").rstrip("/").split("/")[-1]
    A(f"#           明細CSV: {_mcsv}")
    A(f"# 備考：{datetime.now():%Y/%m/%d} 生成 ／ ブラウザー={browser}"
      f" ／ ドライバー自動取得={'有効' if auto_driver else '無効'}"
      f" ／ プロキシ={proxy or '未使用'}")
    A("# ============================================================")
    A("# LLM-Browser-Agent　PAD版　https://github.com/Iwamoto-Ai")
    A("# Apache License 2.0　Copyright 2026 岩本 剛 (Iwamoto-Ai).")
    A(f"# 変換器：{CONVERTER_KIND} v{CONVERTER_VERSION}")
    A("# ============================================================")
    A("")
    A("# --- 接続先：環境を切り替えるときはここを直す ---")
    A("# 練習サイト  : file:///C:/temp/index.html")
    A("# 本番サイト  : https://… （実環境の URL）")
    A(f"SET TargetUrl TO {_robin_str(start_url)}")
    A("")
    A("# --- プロキシ：社外へ出るときに指定する ---")
    A("# WebDriver が起動するブラウザーは素のプロファイルで、Windows のプロキシ設定を")
    A("# 引き継がない。社内プロキシ経由でしか外部に出られない環境では下を有効にする。")
    A("# ※ 対象サイトだけでなく、**WebDriver の自動取得もここを通る**。")
    A("#   練習サイトのようにローカルのファイルを開く場合でも、ドライバーは外から")
    A("#   取ってくるので True が要る。とくに Chrome は版の問い合わせに")
    A("#   googlechromelabs.github.io へ出るため、Edge が動いても Chrome だけ")
    A("#   失敗することがある。")
    A("# 対象サイトへの通信は localhost と file:// なら直結だが、それとは別に")
    A("# ドライバーの取得で外へ出る。練習サイトでも設定が要る点に注意。")
    if proxy:
        A("# UseProxy を False にすると直結（練習サイト用）に戻る。")
        A("SET UseProxy TO True")
        A(f"SET ProxyAddr TO {_robin_str(proxy)}")
    else:
        A("# 使う場合: UseProxy を True にし、ProxyAddr にプロキシの host:port を書く。")
        A("SET UseProxy TO False")
        A("SET ProxyAddr TO $'''proxy.example.com:8080'''")
    A("")
    A("# --- ブラウザー：edge か chrome。ここ 1 行だけ直せば切り替わる ---")
    A("# 対象サイトがブラウザー判定で表示を変える場合や、片方で不具合が出たときに使う。")
    A("# 下の BrowserName（WebDriver への指定）とドライバーのプロセス名も自動で追従する。")
    A(f"SET Browser TO {_robin_str(browser)}")
    A("SET BrowserName TO $'''MicrosoftEdge'''")
    A("SET DriverProc TO $'''msedgedriver'''")
    A("IF Browser = $'''chrome''' THEN")
    A("    SET BrowserName TO $'''chrome'''")
    A("    SET DriverProc TO $'''chromedriver'''")
    A("END")
    A("")
    A("# --- フォルダ・ファイル：配布時に触るのはこの BaseDir だけにする ---")
    A(f"SET BaseDir TO {_robin_str(out_dir)}")
    A("# ※ BaseDir の末尾に \\ を付けないこと（%BaseDir%\\file.png が二重になる）")
    A("")
    A("# --- ドライバーの入手方法 ---")
    A("# AutoDriver = True なら、入っているブラウザーに合わせて自動で取ってくる。")
    A("# ブラウザーが更新されても入れ替えが要らない。")
    A("#")
    A("# DriverSource = direct  … ベンダーのサイトから直接取る（推奨）。")
    A("#   使うのは curl.exe / tar.exe / powershell.exe だけで、どれも Windows に")
    A("#   最初から入っている Microsoft 署名済みの実行ファイル。持ち込みの exe を")
    A("#   実行できない環境でも動く。落ちてくるドライバーもベンダー署名付き。")
    A("# DriverSource = manager … Selenium Manager に任せる。")
    A("#   selenium-manager-windows.exe を BaseDir に置いておく必要がある。取得元:")
    A("#   https://github.com/SeleniumHQ/selenium_manager_artifacts/releases")
    A("#   ※ 署名の無い実行ファイルを止める環境では、これ自体が起動できない。")
    A("#")
    A("# AutoDriver = False … 下の固定パスを使う。ブラウザー更新時は手で入れ替える。")
    A(f"SET AutoDriver TO {'True' if auto_driver else 'False'}")
    A(f"SET DriverSource TO {_robin_str('direct')}")
    A("SET SmExe TO $'''selenium-manager-windows.exe'''")
    A("")
    A("# AutoDriver = False のときに使う固定パス。Browser に追従させるため、")
    A("# edge / chrome それぞれの既定を持ち、下の IF で切り替える。")
    A("# BaseDir 以外に置く場合は、次の 2 行を直接書き換えること。")
    _arg = _robin_under_base(driver_exe, out_dir)
    _edge = _arg if browser == "edge" else "$" + Q_ + "%BaseDir%\\\\msedgedriver.exe" + Q_
    _chrome = _arg if browser == "chrome" else "$" + Q_ + "%BaseDir%\\\\chromedriver.exe" + Q_
    A(f"SET EdgeDriverExe TO {_edge}")
    A(f"SET ChromeDriverExe TO {_chrome}")
    A("SET DriverExe TO EdgeDriverExe")
    A(f"IF Browser = {_robin_str('chrome')} THEN")
    A("    SET DriverExe TO ChromeDriverExe")
    A("END")
    A("SET DriverUrl TO $'''http://127.0.0.1:9515'''")
    A(f"SET DetailsFile TO {_robin_under_base(details_path, out_dir)}")
    A("SET ResultFile TO $'''%BaseDir%\\\\pad_result.csv'''")
    A("SET LogFile TO $'''%BaseDir%\\\\pad_progress.log'''")
    A("SET ShotDir TO $'''%BaseDir%'''")
    A("")
    A("# --- 運用スイッチ ---")
    A("# まず 1 にして 1 件だけ流し、画面と結果を目で確認してから増やす")
    A("SET MaxItems TO 1")
    A("# 起動したブラウザーとドライバーの種類・バージョンをダイアログで出す")
    A("# False にしてもログ（pad_progress.log）には必ず 1 行残る")
    A("SET ShowDriverInfo TO True")
    A("# 失敗分だけを再実行するとき True（読み込み元と出力先が自動で切り替わる）")
    A("SET RetryMode TO False")
    A("IF RetryMode THEN")
    A("    SET DetailsFile TO $'''%BaseDir%\\\\pad_result.csv'''")
    A("    SET ResultFile TO $'''%BaseDir%\\\\pad_result_retry.csv'''")
    A("END")
    A("")
    A("# --- 要素操作の共通 JavaScript ---")
    A("# PAD は長すぎる 1 行を貼り付けても黙って無視するため、短い行に分けて継ぎ足す。")
    A("# （%JsAct% は直前までの内容。順番どおりに貼ること）")
    for line in _robin_js_chunks(js_one):
        A(line)
    A("# ※ 継ぎ足しがうまくいかない場合は、共通 JavaScript（変換器のコピー機能、または")
    A("#   Python 版が同時に出力する .jsact ファイル）の中身を「変数の設定」アクション")
    A("#   （変数名 JsAct）の値の欄に手で貼り付けてもよい。")
    A("")
    A("")
    A("# --- バージョン比較用の JavaScript ---")
    A("# ブラウザーとドライバーのメジャーバージョン（最初のドット手前）を取り出して比べる。")
    A("# Chrome/Edge はビルド番号まで一致するとは限らず、合わせるのはメジャーだけでよい。")
    A("# 文字列リテラルはバッククォートを使う（JSON にも Robin にもそのまま置ける）。")
    _jsver = ("var b = String(arguments[0]).split(`.`)[0]; "
              "var d = String(arguments[1]).split(`.`)[0]; "
              "return { ok: true, bMajor: b, dMajor: d, match: (b === d) };")
    A(f"SET JsVer TO {_robin_str(_jsver)}")
    A("# 途中で中止するかどうかの目印（ドライバー取得やログインの失敗で True になる）")
    A("SET Halt TO False")
    A("# 中止した理由。最後のダイアログとログにそのまま出すので、")
    A("# Halt を立てる箇所では必ずこれも設定すること。")
    A(f"SET HaltReason TO {_robin_str('')}")
    A("# セッションを張れたか。後片付けで DELETE を投げてよいかの判定に使う。")
    A("SET SessionOk TO False")
    A("")
    A("# --- 実行開始をログに残す ---")
    A("# ここは中止しても必ず通る。ループの中だけで書くと、起点に着けずに")
    A("# 中止したとき「ログを確認してください」と案内しながらログが空になる。")
    _hdr = _robin_str("===== 実行開始 上限%MaxItems%件 RetryMode=%RetryMode% "
                      "Browser=%Browser% =====")
    A(f"File.WriteText File: LogFile TextToWrite: {_hdr} "
      f"AppendNewLine: True IfFileExists: File.IfFileExists.Append")
    A("")
    A("# ドライバーをどう用意したか。ログとダイアログに出す。")
    _fx = _robin_str("固定パス（AutoDriver=False のためブラウザー更新時は手動で入れ替え）")
    A(f"SET DriverSrc TO {_fx}")
    A(f"SET SmMsg TO {_robin_str('')}")
    A("")
    A("# ---------- ベンダーから直接取ってくる（DriverSource = direct）----------")
    A("# 版ごとのフォルダに入れる。ブラウザーが更新されると版が変わり、")
    A("# フォルダ名も変わるので自動的に取り直しになる。中身を比べる必要がない。")
    A("IF AutoDriver THEN")
    A(f"IF DriverSource = {_robin_str('direct')} THEN")
    A("    # 入っているブラウザーの版をレジストリから読む。")
    A("    # [Console]::Write は改行を付けないので、そのまま URL に埋め込める。")
    A("    # [char]46 は「.」。引用符を書かずに済ませるための書き方。")
    A(f"    SET VerCmd TO {_robin_str(_EDGE_VER_CMD)}")
    A(f"    IF Browser = {_robin_str('chrome')} THEN")
    A(f"        SET VerCmd TO {_robin_str(_CHROME_VER_CMD)}")
    A("    END")
    A(_dos("VerCmd", "BrowserKey", "VerErr", "VerExit", 120, "    "))
    A(f"    IF BrowserKey = {_robin_str('')} THEN")
    A("        SET Halt TO True")
    A(f"        SET HaltReason TO {_robin_str('レジストリからブラウザーの版を読めませんでした')}")
    A("    END")
    A("")
    A("    # Edge は入っている版の zip がそのまま用意されている。Chrome は版ぴったりの")
    A("    # ドライバーが無いことが多いので、メジャー番号でその世代の最新版を問い合わせる。")
    A("    SET DrvVer TO BrowserKey")
    A("    IF Halt = False THEN")
    A(f"        IF Browser = {_robin_str('chrome')} THEN")
    A("            SET RelUrl TO $'''https://googlechromelabs.github.io/chrome-for-testing/LATEST_RELEASE_%BrowserKey%'''")
    A("            SET VerFile TO $'''%BaseDir%\\\\drvver.txt'''")
    A("            SET RelCmd TO $'''curl.exe -f -L -sS -o \"%VerFile%\" %RelUrl%'''")
    A("            IF UseProxy THEN")
    A("                SET RelCmd TO $'''curl.exe -f -L -sS -x %ProxyAddr% -o \"%VerFile%\" %RelUrl%'''")
    A("            END")
    A(_dos("RelCmd", "RelOut", "RelErr", "RelExit", 300, "            "))
    A("            SET ReadCmd TO $'''powershell -NoProfile -Command [Console]::Write((Get-Content -Raw %VerFile%).Trim())'''")
    A(_dos("ReadCmd", "DrvVer", "ReadErr", "ReadExit", 120, "            "))
    A(f"            IF DrvVer = {_robin_str('')} THEN")
    A("                SET Halt TO True")
    _rmsg = _robin_str(
        "ドライバーの版を問い合わせられませんでした"
        "（curl=%RelExit% / %RelErr%）。UseProxy の設定を確認してください")
    A(f"                SET HaltReason TO {_rmsg}")
    A("            END")
    A("        END")
    A("    END")
    A("")
    A("    IF Halt = False THEN")
    A("        Folder.Create FolderPath: BaseDir FolderName: $'''driver''' Folder=> DrvRoot")
    A("        Folder.Create FolderPath: $'''%BaseDir%\\\\driver''' FolderName: DrvVer Folder=> DrvDirObj")
    A("        SET DrvDir TO $'''%BaseDir%\\\\driver\\\\%DrvVer%'''")
    A("        # Edge の zip は exe が直下、Chrome は chromedriver-win64 の下に入る")
    A("        SET DrvHome TO DrvDir")
    A("        SET DrvExeName TO $'''msedgedriver.exe'''")
    A("        SET ZipUrl TO $'''https://msedgedriver.microsoft.com/%DrvVer%/edgedriver_win64.zip'''")
    A(f"        IF Browser = {_robin_str('chrome')} THEN")
    A("            SET DrvHome TO $'''%DrvDir%\\\\chromedriver-win64'''")
    A("            SET DrvExeName TO $'''chromedriver.exe'''")
    A("            SET ZipUrl TO $'''https://storage.googleapis.com/chrome-for-testing-public/%DrvVer%/win64/chromedriver-win64.zip'''")
    A("        END")
    A("        SET ZipPath TO $'''%DrvDir%\\\\driver.zip'''")
    A("        " + _folder_get("DrvHome", "DrvExeName", "HaveDrv"))
    A("        IF HaveDrv.Count = 0 THEN")
    A("            # -f を付けないと 404 でも curl は成功を返し、エラーページを zip として")
    A("            # 保存してしまう。その先の tar が失敗して原因が読めなくなる。")
    A("            SET DlCmd TO $'''curl.exe -f -L -sS -o \"%ZipPath%\" %ZipUrl%'''")
    A("            IF UseProxy THEN")
    A("                SET DlCmd TO $'''curl.exe -f -L -sS -x %ProxyAddr% -o \"%ZipPath%\" %ZipUrl%'''")
    A("            END")
    A(_dos("DlCmd", "DlOut", "DlErr", "DlExit", 600, "            "))
    A("            IF DlExit <> 0 THEN")
    A("                SET Halt TO True")
    A("                SET HaltReason TO $'''ドライバーを取得できませんでした（curl の終了コード %DlExit%）'''")
    A("            END")
    A("            IF Halt = False THEN")
    A("                SET UnzipCmd TO $'''tar.exe -xf \"%ZipPath%\" -C \"%DrvDir%\"'''")
    A(_dos("UnzipCmd", "UzOut", "UzErr", "UzExit", 300, "                "))
    A("            END")
    A("        END")
    A("    END")
    A("")
    A("    IF Halt = False THEN")
    A("        " + _folder_get("DrvHome", "DrvExeName", "HaveDrv2"))
    A("        IF HaveDrv2.Count = 0 THEN")
    A("            SET Halt TO True")
    A("            SET HaltReason TO $'''ドライバーを展開できませんでした（tar の終了コード %UzExit%）'''")
    A("        END")
    A("    END")
    A("    IF Halt = False THEN")
    A("        SET DriverExe TO $'''%DrvHome%\\\\%DrvExeName%'''")
    A(f"        SET DriverSrc TO {_robin_str('ベンダーから直接取得（%DrvVer% / 版ごとのフォルダに保管）')}")
    A("    END")
    A("END")
    A("END")
    A("")
    A("# ---------- Selenium Manager に任せる（DriverSource = manager）----------")
    A("# 設定は冒頭の AutoDriver / SmExe。取得できたらそのパスで DriverExe を上書きする。")
    A("IF AutoDriver THEN")
    A(f"IF DriverSource = {_robin_str('manager')} THEN")
    A("    SET SmArgs TO $'''%SmExe% --browser %Browser% --browser-version stable "
      "--output json'''")
    A("    IF UseProxy THEN")
    A("        SET SmArgs TO $'''%SmArgs% --proxy %ProxyAddr%'''")
    A("    END")
    A("    Scripting.RunDOSCommand.RunDOSCommandAndFailOnTimeout "
      "DOSCommandOrApplication: SmArgs WorkingDirectory: BaseDir Timeout: 300 "
      "StandardOutput=> SmOutput StandardError=> SmError ExitCode=> SmExit")
    A("    # 終了コードを先に見る。exe が起動できないと出力が空になり、そのまま")
    A("    # JSON に変換しようとして「CustomObject が取れません」という、原因の")
    A("    # 分からないエラーになる。")
    A("    IF SmExit <> 0 THEN")
    A("        SET Halt TO True")
    A(f"        SET HaltReason TO {_robin_str('Selenium Manager を実行できませんでした')}")
    A("        Display.ShowMessageDialog.ShowMessage Title: "
      + _robin_str("Selenium Manager を実行できません")
      + " Message: SmError Icon: Display.Icon.Warning Buttons: Display.Buttons.OK "
        "DefaultButton: Display.DefaultButton.Button1 IsTopMost: True "
        "ButtonPressed=> SmBtn2")
    A("    END")
    A("    IF Halt = False THEN")
    A("    Variables.ConvertJsonToCustomObject Json: SmOutput CustomObject=> SmObj")
    A("    IF SmObj['result']['code'] = 0 THEN")
    A("        SET DriverExe TO SmObj['result']['driver_path']")
    _sm = _robin_str("Selenium Manager（ブラウザーのバージョンに合わせて自動取得）")
    A(f"        SET DriverSrc TO {_sm}")
    A("        SET SmMsg TO SmObj['result']['message']")
    A("    END")
    A("    IF SmObj['result']['code'] <> 0 THEN")
    A("        SET Halt TO True")
    A(f"        SET HaltReason TO "
      f"{_robin_str('ドライバーの取得に失敗しました（Selenium Manager）')}")
    A("        Display.ShowMessageDialog.ShowMessage Title: $'''ドライバー取得に失敗''' "
      "Message: SmOutput Icon: Display.Icon.Information Buttons: Display.Buttons.OK "
      "DefaultButton: Display.DefaultButton.Button1 IsTopMost: True "
      "ButtonPressed=> SmBtn")
    A("    END")
    A("    END")
    A("END")
    A("END")
    A("")
    A("# ここから先はドライバーが要る。取得に失敗していたら入らない。")
    A("# 入ってしまうと更新前の古いドライバーで起動し、")
    A("#「sessionId がありません」という無関係なエラーに化ける。")
    A("IF Halt = False THEN")
    A("# --- 古いドライバーが残っていたら終了する ---")
    A("# 前回の実行が異常終了すると、ドライバーがポート 9515 を掴んだまま残り、")
    A("# 新しいドライバーが起動できない（古い方が応答してしまう）。")
    A("# 別のブラウザーのフローを続けて動かす場合もポートを奪い合うため、両方を終了させる。")
    A("System.TerminateProcess.TerminateProcessByName ProcessName: $'''msedgedriver'''")
    A("System.TerminateProcess.TerminateProcessByName ProcessName: $'''chromedriver'''")
    A("WAIT 1")
    A("")
    A("# --- WebDriver を起動 ---")
    A("System.RunApplication.RunApplication ApplicationPath: DriverExe "
      "CommandLineArguments: $'''--port=9515''' WindowStyle: System.ProcessWindowStyle.Hidden "
      "ProcessId=> DriverPid")
    A("WAIT 3")
    A("")
    A("# --- セッション開始（ブラウザ起動）---")
    A("# ブラウザーは冒頭の Browser、プロキシの有無は UseProxy で切り替わる。")
    A("# 組み合わせが増えるので、本文は前から継ぎ足して組み立てる。")
    A("SET SessionBody TO $'''{\"capabilities\": {\"alwaysMatch\": "
      "{\"browserName\": \"%BrowserName%\"'''")
    A("IF UseProxy THEN")
    A("    SET SessionBody TO $'''%SessionBody%, \"proxy\": {\"proxyType\": \"manual\", "
      "\"httpProxy\": \"%ProxyAddr%\", \"sslProxy\": \"%ProxyAddr%\"}'''")
    A("END")
    A("SET SessionBody TO $'''%SessionBody%}}}'''")
    A("SET AppJson TO $'''application/json'''")
    A("SET NewUrl TO $'''%DriverUrl%/session'''")
    A(_web("NewUrl", "Post", "SessionBody", "SessionResp", "SessionStatus"))
    A("# ↓ 「sessionId がありません」と出たらこの行を有効にして生の応答を確認する")
    A("# Display.ShowMessageDialog.ShowMessage Title: $\'\'\'WebDriver 応答\'\'\' "
      "Message: SessionResp Icon: Display.Icon.Information Buttons: Display.Buttons.OK "
      "DefaultButton: Display.DefaultButton.Button1 IsTopMost: True ButtonPressed=> BtnDbg")
    A("# セッションが作れたかを応答コードで判定する。ここを見ないと、失敗応答")
    A("#（value の中身が error/message に入れ替わる）をそのまま読みに行って")
    A("#「sessionId がありません」という、原因の分からないエラーになる。")
    A("IF SessionStatus <> 200 THEN")
    A("    SET Halt TO True")
    _sr = _robin_str("WebDriver のセッションを作成できませんでした"
                     "（ブラウザーとドライバーの不一致など）")
    A(f"    SET HaltReason TO {_sr}")
    A(f"    Display.ShowMessageDialog.ShowMessage Title: {_robin_str('セッション作成に失敗')} "
      "Message: SessionResp Icon: Display.Icon.Warning Buttons: Display.Buttons.OK "
      "DefaultButton: Display.DefaultButton.Button1 IsTopMost: True ButtonPressed=> SessBtn")
    A("END")
    A("END")
    A("")
    A("IF Halt = False THEN")
    A("Variables.ConvertJsonToCustomObject Json: SessionResp CustomObject=> SessionObj")
    A("# カスタムオブジェクトはブラケット記法で参照する。ドット記法は使えない。")
    A("SET SessionId TO SessionObj['value']['sessionId']")
    A("SET SessionOk TO True")
    A("# 以降で使い回す URL を組み立てておく（1 行を短く保つため）")
    A("SET ExecUrl TO $'''%DriverUrl%/session/%SessionId%/execute/sync'''")
    A("SET GoUrl TO $'''%DriverUrl%/session/%SessionId%/url'''")
    A("SET RectUrl TO $'''%DriverUrl%/session/%SessionId%/window/rect'''")
    A("SET ShotUrl TO $'''%DriverUrl%/session/%SessionId%/screenshot'''")
    A("SET QuitUrl TO $'''%DriverUrl%/session/%SessionId%'''")
    A("")
    A("# --- 起動したブラウザーとドライバーを確認する ---")
    A("# 値はセッションの応答（capabilities）から取る。実際に動いているものが出る。")
    A("SET BrowserVer TO SessionObj['value']['capabilities']['browserVersion']")
    A("# 起動したのが要求どおりのブラウザーかを先に確かめる。ドライバーは取り違えても")
    A("# セッションを張ってしまうことがあり、そのときは空白のウィンドウが出るだけで")
    A("# 気づけない。ここで止めないと、続く capabilities の参照キーも食い違う。")
    A("SET RealBrowser TO SessionObj['value']['capabilities']['browserName']")
    A("IF RealBrowser <> BrowserName THEN")
    A("    SET Halt TO True")
    _bm = _robin_str("要求したブラウザー(%BrowserName%)と実際に起動したブラウザー"
                     "(%RealBrowser%)が違います。ドライバーの取り違えです")
    A(f"    SET HaltReason TO {_bm}")
    A(f"    Display.ShowMessageDialog.ShowMessage Title: "
      f"{_robin_str('ブラウザーの取り違え')} Message: HaltReason "
      "Icon: Display.Icon.Warning Buttons: Display.Buttons.OK "
      "DefaultButton: Display.DefaultButton.Button1 IsTopMost: True ButtonPressed=> MixBtn")
    A("END")
    A("")
    A("IF Halt = False THEN")
    A(f"SET DriverVer TO {_robin_str('(不明)')}")
    A(f"IF Browser = {_robin_str('chrome')} THEN")
    A("    SET DriverVer TO "
      "SessionObj['value']['capabilities']['chrome']['chromedriverVersion']")
    A("END")
    A(f"IF Browser = {_robin_str('edge')} THEN")
    A("    SET DriverVer TO "
      "SessionObj['value']['capabilities']['msedge']['msedgedriverVersion']")
    A("END")
    A("# メジャーバージョンの比較はページ側の JavaScript にやらせる。")
    A("# PAD のテキスト分割アクションを増やさずに済み、貼り付け事故の余地が減る。")
    A("SET VerBody TO $'''{\"script\": \"%JsVer%\", "
      "\"args\": [\"%BrowserVer%\", \"%DriverVer%\"]}'''")
    A(_web("ExecUrl", "Post", "VerBody", "VerResp", "VerStatus"))
    A("Variables.ConvertJsonToCustomObject Json: VerResp CustomObject=> VerObj")
    A(f"SET VerJudge TO {_robin_str('不一致（ブラウザー更新の可能性あり）')}")
    A("IF VerObj['value']['match'] = True THEN")
    A(f"    SET VerJudge TO {_robin_str('一致')}")
    A("END")
    _di = _robin_str("ブラウザー=%Browser% %BrowserVer% / WebDriver=%DriverProc% "
                     "%DriverVer% / メジャー判定=%VerJudge% / 取得方法=%DriverSrc% / "
                     "パス=%DriverExe%")
    A(f"SET DriverInfo TO {_di}")
    A(f"File.WriteText File: LogFile "
      f"TextToWrite: {_robin_str('[ドライバー] %DriverInfo%')} "
      f"AppendNewLine: True IfFileExists: File.IfFileExists.Append")
    A("# ダイアログにだけ補足を足す。ここはページを開く前なのでブラウザーは白紙で、")
    A("# 初めて見た人が異常だと思いやすい。ログ側は 1 行を短く保つため足さない。")
    _note = _robin_str("%DriverInfo%  ※この時点ではまだページを開いていません"
                       "（白紙で正常）。OK を押すとページを開きます。")
    A(f"SET DriverInfoMsg TO {_note}")
    A("IF ShowDriverInfo THEN")
    A(f"    Display.ShowMessageDialog.ShowMessage Title: {_robin_str('ドライバー確認')} "
      "Message: DriverInfoMsg Icon: Display.Icon.Information Buttons: Display.Buttons.OK "
      "DefaultButton: Display.DefaultButton.Button1 IsTopMost: True ButtonPressed=> DrvBtn")
    A("END")
    A("END")
    A("")

    A("END")
    # ---- setup ----
    A("# ================= セットアップ（最初に 1 回）=================")
    A("# セッションが張れていなければ、以降の URL 変数が存在しないので入らない。")
    A("IF Halt = False THEN")
    A("SET RowError TO $''''''")
    # 手動ログイン方式。パスワードは PAD が一度も受け取らない。
    # ただし「起点画面まで進む」のは機械にやらせる。ログイン直後から録画を
    # 始めてもらえば、録画にはメニュー移動だけが入り、資格情報は現れない。
    # 起点が分かりにくいサイトでは、人に「起点まで進んでください」と言うより
    # 機械が辿るほうが確実で、説明も要らない。
    n = 0
    for st in setup:
        t_ = st.get("type")
        if t_ == "setViewport":
            n += 1
            w = int(st.get("width", 1920) or 1920)
            h = int(st.get("height", 1080) or 1080)
            A(f"# [{n}] ウィンドウサイズ {w}x{h}")
            A("# エビデンスに写る範囲はこのサイズで決まる。複数の PC に配布する場合は")
            A("# 一番小さい画面に収まる値にそろえること。")
            A(f"SET RectBody TO $'''{{\"width\": {w}, \"height\": {h}}}'''")
            A(_web("RectUrl", "Post", "RectBody", "RectResp", "RectStatus"))
            continue
        if t_ == "navigate":
            n += 1
            A(f"# [{n}] ページを開く（URL は冒頭の TargetUrl で設定）")
            A("SET UrlBody TO $'''{\"url\": \"%TargetUrl%\"}'''")
            A(_web("GoUrl", "Post", "UrlBody", "UrlResp", "UrlStatus"))
            A("WAIT 2")
            continue
    A("")
    A("# ---------- 手動ログイン ----------")
    A("# フローを止めて人がログインする。ここで止めるのはログインだけで、")
    A("# 起点画面までの移動は[OK]のあと機械が行う。")
    A("# PAD はパスワードを一度も受け取らないので、変数ペイン・実行ログ・")
    A("# エラーメッセージのどこにも残らない。生成物にも入らない。")
    A("# WebDriver は自分が起動したブラウザーしか操作できない。別に開いてある")
    A("# 普段のブラウザーでログインしても、フローはそのタブを見られない。")
    _lmsg = _robin_str(
        "ログインしたら[OK]。そのあと自動で起点画面まで進みます。"
        "ブラウザーは閉じないでください。")
    A("Display.ShowMessageDialog.ShowMessage Title: $\'\'\'手動ログイン\'\'\' "
      f"Message: {_lmsg} "
      "Icon: Display.Icon.Information Buttons: Display.Buttons.OKCancel "
      "DefaultButton: Display.DefaultButton.Button1 IsTopMost: True "
      "ButtonPressed=> LoginBtn")
    A(f"IF LoginBtn = {_robin_str('Cancel')} THEN")
    A("    SET Halt TO True")
    A(f"    SET HaltReason TO {_robin_str('手動ログインがキャンセルされました')}")
    A("END")
    A("")

    # ---- ログイン後、起点画面まで進む ----
    # 録画に残っているメニュー移動をそのまま再生する。失敗しても止めない。
    # 起点に着いたかどうかは、このあとの確認で見るので、ここで判定する必要はない。
    # 画面がすでに進んでいる場合に「見つかりません」で止めるほうが困る。
    # クリックだけを再生する。入力（change）は扱わない。
    # SECRET に置き換えていない録画では、入力値にパスワードがそのまま
    # 残っている。値を読まなければ、生成物に出る余地がない。
    # 起点までの移動は普通メニューのクリックだけで足りる。
    move = [st for st in setup if st.get("type") in ("click", "doubleClick")]
    if move:
        A("IF Halt = False THEN")
        A("# ---------- 起点画面まで進む ----------")
        A("# ログイン直後の画面から、繰り返しの起点までメニューを辿る。")
        A("# ここは通らなくても構わない（すでに起点にいる場合など）。")
        A("# 起点に着いたかどうかは次の確認で見る。")
        for st in move:
            cands = _candidates(st)
            if not _robin_filter_candidates(cands):
                continue
            for ln in _robin_act_best_effort(cands, "click", "", "    ",
                                             f"click {cands[0]}", cols):
                A(ln)
        A("END")
        A("")
    A("")
    # ---- 起点画面の確認 ----
    # 手動ログイン運用では、人がどこまで進めて[OK]を押したかで結果が変わる。
    if first_target:
        A("# ---------- 起点画面かどうかを確認する ----------")
        A("# ループ最初の操作対象がこの画面にあるかを、クリックせずに調べる。")
        A("# 見つからなければ、その場で進めてもらって何度でも試せるようにする。")
        A("# 1 度きりで中止すると、画面を直してから実行し直すことになって手間が増える。")
        body_args = json.dumps([first_target, "find", ""], ensure_ascii=False)
        hint = origin_hint
        A(f"SET ActBody TO $'''{{\"script\": \"%JsAct%\", \"args\": {body_args}}}'''")
        A("SET StartOk TO False")
        A("SET StartTry TO 0")
        A("LOOP WHILE StartOk = False")
        A("    " + _web("ExecUrl", "Post", "ActBody", "ActResp", "ActStatus"))
        A("    # 応答コードを先に見る。エラー応答には ok が無いので、そのまま")
        A("    # 読みに行くと「プロパティがありません」で止まる。")
        A("    IF ActStatus = 200 THEN")
        A("        Variables.ConvertJsonToCustomObject Json: ActResp CustomObject=> ActObj")
        A("        IF ActObj['value']['ok'] = True THEN")
        A("            SET StartOk TO True")
        A("        END")
        A("    END")
        A("    IF StartOk = False THEN")
        A("        SET StartTry TO StartTry + 1")
        _msg = _robin_str(
            "起点画面が出ていません。" + hint +
            "まで進めて[OK]。（%StartTry% 回目）")
        A("        Display.ShowMessageDialog.ShowMessage Title: "
          + _robin_str("起点画面ではありません")
          + f" Message: {_msg} Icon: Display.Icon.Warning "
            "Buttons: Display.Buttons.OKCancel "
            "DefaultButton: Display.DefaultButton.Button1 IsTopMost: True "
            "ButtonPressed=> StartBtn")
        A(f"        IF StartBtn = {_robin_str('Cancel')} THEN")
        A("            SET Halt TO True")
        A(f"            SET HaltReason TO "
          f"{_robin_str('繰り返しの起点画面に到達できませんでした')}")
        A("            SET StartOk TO True")
        A("        END")
        A("    END")
        A("END")
        A("")

    A("# ---------- セットアップ失敗を検知して止める ----------")
    A("# ここで止めないと、ループ先頭で RowError がリセットされるため、")
    A("# 全件が「ステップ1で要素が見つかりません」という偽の失敗として記録される。")
    A("IF RowError <> $'''''' THEN")
    A("    SET Halt TO True")
    A("    SET HaltReason TO RowError")
    A("END")
    A("END")
    A("")

    # ---- 明細読み込み ----
    # SET の右辺で変数を参照するときは % で囲まない（%Col2% と書くと貼り付けが弾かれる）
    key_ref = "Col2" if len(cols) > 1 else "$''''''"
    A("# ================= 明細（CSV）を読み込む =================")
    A("IF Halt = False THEN")
    A("    File.ReadFromCSVFile.ReadCSV CSVFile: DetailsFile "
      "Encoding: File.CSVEncoding.UTF8 TrimFields: True "
      "FirstLineContainsColumnNames: True "
      "ColumnsSeparator: File.CSVColumnsSeparator.Comma CSVTable=> Rows")
    A("    # 結果 CSV は、そのまま明細として読み直せる列構成にする。")
    A("    # ID だけでなく業務キーも入れないと、再実行で対象を特定できない。")
    key_head = cols[1] if len(cols) > 1 else "業務キー"
    A(f"    File.WriteText File: ResultFile "
      f"TextToWrite: $'''{id_col},{key_head},結果,理由,エビデンス,実行日時''' "
      f"AppendNewLine: True IfFileExists: File.IfFileExists.Overwrite")
    A("    SET OkCount TO 0")
    A("    SET NgCount TO 0")
    A("    SET SkipCount TO 0")
    A("    SET Attempted TO 0")
    A("    SET PrevFailed TO False")
    A("")

    # ---- ループ ----
    ind = "    "
    inner = "        "
    A(f"{ind}# ================= 明細ごとの繰り返し =================")
    A(f"{ind}LOOP FOREACH Row IN Rows")
    A(f"{inner}# 明細の列を変数に取り出す（リテラル内に単引用符を入れないため）")
    A("@@COLVARS@@")
    A(f"{inner}SET RowId TO Col1")
    A(f"{inner}SET RowKey TO {key_ref}")
    A(f"{inner}SET RowError TO $''''''")
    A("")
    A(f"{inner}# 再実行モードでは「失敗」行だけを対象にする")
    A(f"{inner}IF RetryMode THEN")
    A(f"{inner}    # 対象は「失敗」と「未実行」。未実行は件数上限で打ち切った行で、")
    A(f"{inner}    # これを外すと上限を刻んで回したとき続きが流せない。")
    A(f"{inner}    SET DoRow TO False")
    A(f"{inner}    IF Row['結果'] = {_robin_str('失敗')} THEN")
    A(f"{inner}        SET DoRow TO True")
    A(f"{inner}    END")
    A(f"{inner}    IF Row['結果'] = {_robin_str('未実行')} THEN")
    A(f"{inner}        SET DoRow TO True")
    A(f"{inner}    END")
    A(f"{inner}    IF DoRow = False THEN")
    A(f"{inner}        NEXT LOOP")
    A(f"{inner}    END")
    A(f"{inner}END")
    A("")
    A(f"{inner}# skip 列に値がある行は飛ばす（再実行 CSV には skip 列が無いので除外）")
    A(f"{inner}IF RetryMode = False THEN")
    A(f"{inner}    IF Row['skip'] <> $'''''' THEN")
    A(f"{inner}        SET SkipCount TO SkipCount + 1")
    A(f"{inner}        File.WriteText File: ResultFile "
      "TextToWrite: $'''%RowId%,%RowKey%,スキップ,,,''' AppendNewLine: True "
      "IfFileExists: File.IfFileExists.Append")
    A(f"{inner}        NEXT LOOP")
    A(f"{inner}    END")
    A(f"{inner}END")
    A("")
    A(f"{inner}# 件数上限。打ち切った行も記録に残す（どこから再開するか分かる）")
    A(f"{inner}IF Attempted >= MaxItems THEN")
    A(f"{inner}    File.WriteText File: ResultFile "
      "TextToWrite: $'''%RowId%,%RowKey%,未実行,\"件数上限 %MaxItems% 件に達したため\",,''' "
      "AppendNewLine: True IfFileExists: File.IfFileExists.Append")
    A(f"{inner}    NEXT LOOP")
    A(f"{inner}END")
    A(f"{inner}SET Attempted TO Attempted + 1")
    A("")
    A(f"{inner}# 直前の件が失敗していたら、起点に復帰してから始める。")
    A(f"{inner}# 失敗した画面のまま次の件を始めると 1 件の失敗が全件に連鎖する。")
    A(f"{inner}IF PrevFailed THEN")
    if recover:
        for st in recover:
            t = st.get("type")
            if t == "comment":
                A(f"{inner}    # 💬 {_safe_comment(st.get('text', ''), cols)}")
            elif t in ("click", "doubleClick", "change"):
                cands = _candidates(st)
                act = "fill" if t == "change" else "click"
                L.extend(_robin_act_best_effort(
                    cands, act, st.get("value", ""), inner + "    ",
                    f"復帰: {act} {cands[0] if cands else ''}", cols))
            elif t == "navigate":
                A(f"{inner}    SET UrlBody TO $'''{{\"url\": \"%TargetUrl%\"}}'''")
                A(_web("GoUrl", "Post", "UrlBody", "UrlResp", "UrlStatus", inner + "    "))
                A(f"{inner}    WAIT 2")
    elif start_url:
        A(f"{inner}    # batch に recover が無いので、開始 URL を開き直して復帰する。")
        A(f"{inner}    # ログインが必要なサイトではセッションが切れる可能性があるため、")
        A(f"{inner}    # 録画に recover セクションを用意するほうが確実。")
        A(f"{inner}    SET UrlBody TO $'''{{\"url\": \"%TargetUrl%\"}}'''")
        A(_web("GoUrl", "Post", "UrlBody", "UrlResp", "UrlStatus", inner + "    "))
        A(f"{inner}    WAIT 2")
    else:
        A(f"{inner}    # ★ 復帰手順が定義されていない。batch に recover を追加すること。")
        A(f"{inner}    #   このままでは 1 件失敗すると以降が連鎖して失敗する。")
    A(f"{inner}    SET PrevFailed TO False")
    A(f"{inner}END")
    A(f"{inner}# 悲観的に置く。最後まで通れば False に戻る（フラグを立てる箇所が 1 行で済む）")
    A(f"{inner}SET PrevFailed TO True")
    A("")
    A(f"{inner}# 日時つきのファイル名を作る。MM は月、mm は分。")
    A(f"{inner}DateTime.GetCurrentDateTime.Local "
      "DateTimeFormat: DateTime.DateTimeFormat.DateAndTime CurrentDateTime=> NowDt")
    A(f"{inner}Text.ConvertDateTimeToText.FromCustomDateTime DateTime: NowDt "
      "CustomFormat: $'''yyyyMMdd_HHmmss''' Result=> Stamp")
    A(f"{inner}Text.ConvertDateTimeToText.FromCustomDateTime DateTime: NowDt "
      "CustomFormat: $'''yyyy/MM/dd HH:mm:ss''' Result=> RecStamp")
    A(f"{inner}# エビデンスのファイル名。ここ 1 行を直せば命名が変わる。")
    A(f"{inner}# 使える差し込み: %RowId%（ID列）/ %RowKey%（業務キー）/ %Stamp%（日時）")
    A(f"{inner}SET ShotName TO {_robin_str(shot_name)}")
    A(f"{inner}SET ShotPath TO $'''%ShotDir%\\\\%ShotName%.png'''")
    A(f"{inner}SET FailShot TO $'''%ShotDir%\\\\fail_%ShotName%.png'''")
    A(f"{inner}File.WriteText File: LogFile "
      "TextToWrite: $'''[%RecStamp%] %RowId% / %RowKey% 開始''' AppendNewLine: True "
      "IfFileExists: File.IfFileExists.Append")
    A("")

    m = 0
    for st in loop_steps:
        t = st.get("type")
        if t == "comment":
            A(f"{inner}# 💬 {_safe_comment(st.get('text', ''), cols)}")
            continue
        if t == "screenshot":
            A(f"{inner}# エビデンス保存（%RowId%__%RowKey%__日時）")
            A(f"{inner}# WebDriver に撮らせるとページの表示領域だけが写る。")
            A(f"{inner}# デスクトップや他ウィンドウは写らず、フォーカスにも依存しない。")
            A(f"{inner}# 逆にスクロールしないと見えない範囲は写らない点に注意。")
            L.extend(_robin_shot(inner, "ShotPath"))
            A("")
            continue
        if t == "assertText":
            m += 1
            text = st.get("text", "")
            A(f"{inner}# 完了確認。「ボタンは押せたが実際には処理されていない」を検知する。")
            L.extend(_robin_act([], "exists", text, inner,
                                f"完了確認: {text}", m, cols))
            L.extend(_robin_fail(inner))
            A("")
            continue
        if t in ("click", "doubleClick", "change"):
            m += 1
            cands = _candidates(st)
            action = "fill" if t == "change" else "click"
            L.extend(_robin_act(cands, action, st.get("value", ""), inner,
                                f"{action} {cands[0] if cands else ''}", m, cols))
            L.extend(_robin_fail(inner))
            A(f"{inner}WAIT 1")
            A("")
            continue

    A(f"{inner}# ここまで来たら成功")
    A(f"{inner}SET PrevFailed TO False")
    A(f"{inner}SET OkCount TO OkCount + 1")
    A(f"{inner}File.WriteText File: ResultFile "
      "TextToWrite: $'''%RowId%,%RowKey%,成功,,\"%ShotPath%\",%RecStamp%''' "
      "AppendNewLine: True IfFileExists: File.IfFileExists.Append")
    A(f"{inner}File.WriteText File: LogFile "
      "TextToWrite: $'''[%RecStamp%] %RowId% / %RowKey% 成功''' AppendNewLine: True "
      "IfFileExists: File.IfFileExists.Append")
    A(f"{ind}END")
    A("END")
    A("")

    # ---- teardown / 後片付け ----
    if teardown:
        A("# ================= 後処理（batch の teardown）=================")
        for st in teardown:
            t = st.get("type")
            if t == "comment":
                A(f"# 💬 {_safe_comment(st.get('text', ''), cols)}")
            elif t in ("click", "doubleClick", "change"):
                cands = _candidates(st)
                act = "fill" if t == "change" else "click"
                L.extend(_robin_act_best_effort(
                    cands, act, st.get("value", ""), "",
                    f"後処理: {act} {cands[0] if cands else ''}", cols))
        A("")

    A("# ================= 後片付け =================")
    A("# セッションを張れなかったときは QuitUrl が無いので投げない。")
    A("IF SessionOk THEN")
    A(_web("QuitUrl", "Delete", None, "QuitResp", "QuitStatus"))
    A("END")
    A("System.TerminateProcess.TerminateProcessByName ProcessName: DriverProc")
    A("IF Halt = False THEN")
    A("    Display.ShowMessageDialog.ShowMessage Title: $'''完了''' "
      "Message: $'''成功 %OkCount% / 失敗 %NgCount% / スキップ %SkipCount%"
      "（上限 %MaxItems% 件）  結果CSV: %ResultFile%''' "
      "Icon: Display.Icon.Information Buttons: Display.Buttons.OK "
      "DefaultButton: Display.DefaultButton.Button1 IsTopMost: True ButtonPressed=> Btn")
    A("END")
    A("IF Halt THEN")
    A("    DateTime.GetCurrentDateTime.Local "
      "DateTimeFormat: DateTime.DateTimeFormat.DateAndTime CurrentDateTime=> HaltDt")
    A(f"    Text.ConvertDateTimeToText.FromCustomDateTime DateTime: HaltDt "
      f"CustomFormat: {_robin_str('yyyy/MM/dd HH:mm:ss')} Result=> HaltStamp")
    A(f"    File.WriteText File: LogFile "
      f"TextToWrite: {_robin_str('[%HaltStamp%] 中止 %HaltReason%')} "
      f"AppendNewLine: True IfFileExists: File.IfFileExists.Append")
    A("    Display.ShowMessageDialog.ShowMessage Title: $'''中止''' "
      "Message: $'''%HaltReason%のため、明細を1件も処理せず中止しました。"
      "詳細は pad_progress.log を確認してください。''' "
      "Icon: Display.Icon.Warning Buttons: Display.Buttons.OK "
      "DefaultButton: Display.DefaultButton.Button1 IsTopMost: True ButtonPressed=> Btn")
    A("END")

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    # 収集した参照列を、ループ先頭の変数取り出しに展開する（Col1 = ID 列）
    colvars = "\n".join(
        f"        SET Col{i + 1} TO Row['{c}']" for i, c in enumerate(cols)
    )
    body = "\n".join(L).replace("@@COLVARS@@", colvars)
    warns = _lint_robin(body.split("\n"))
    if warns:
        print(f"  ⚠ 上記 {len(warns)} 件は貼り付けが無視される可能性があります")
    with open(path, "w", encoding="utf-8") as f:
        f.write(body + "\n")
    # 共通 JavaScript は別ファイルにも出す（長い 1 行が貼れないときの逃げ道）
    js_path = os.path.splitext(path)[0]
    if js_path.endswith(".robin"):
        js_path = js_path[: -len(".robin")]
    js_path += ".jsact.js"
    with open(js_path, "w", encoding="utf-8") as f:
        f.write(js_one + "\n")
    return os.path.abspath(path)


# ドライバーをベンダーから直接取るときに使うコマンド。引用符を書かずに済むよう、
# レジストリのキーは空白の無いものを直接指定し、区切り文字は [char]46 で表す。
# [Console]::Write は改行を付けないので、結果をそのまま URL に埋め込める。
_EDGE_VER_CMD = ("powershell -NoProfile -Command [Console]::Write("
                 "(Get-ItemProperty HKCU:\\Software\\Microsoft\\Edge\\BLBeacon).version)")
_CHROME_VER_CMD = ("powershell -NoProfile -Command [Console]::Write("
                   "(Get-ItemProperty HKCU:\\Software\\Google\\Chrome\\BLBeacon)"
                   ".version.Split([char]46)[0])")


def _dos(cmd_var: str, out_var: str, err_var: str, exit_var: str,
         timeout: int, indent: str = "") -> str:
    """DOS コマンドの実行（実機で確認済みの書式）。"""
    return (f"{indent}Scripting.RunDOSCommand.RunDOSCommandAndFailOnTimeout "
            f"DOSCommandOrApplication: {cmd_var} WorkingDirectory: BaseDir "
            f"Timeout: {timeout} StandardOutput=> {out_var} "
            f"StandardError=> {err_var} ExitCode=> {exit_var}")


def _folder_get(folder_var: str, filter_var: str, out_var: str) -> str:
    """フォルダー内のファイル取得。並べ替えの列挙は Folder.SortBy.○○（実機確認済み）。"""
    return (f"Folder.GetFiles Folder: {folder_var} FileFilter: {filter_var} "
            "IncludeSubfolders: False FailOnAccessDenied: True "
            "SortBy1: Folder.SortBy.Name SortDescending1: False "
            "SortBy2: Folder.SortBy.LastModified SortDescending2: False "
            "SortBy3: Folder.SortBy.LastAccessed SortDescending3: False "
            f"Files=> {out_var}")


def _origin_hint(batch: dict, cands: list) -> str:
    """起点画面の案内文を、人が読める形で作る。

    「#POS_SHIPMENTS が見える画面まで進めて」では、その ID が画面のどこを
    指すのか利用者には分からない。次の順で探す。

      1. バッチ定義の originHint（例: "納入"）。人が書いたものが一番確実
      2. 候補の aria/ や text/ の名前。画面に出ている文字なので目で探せる
      3. どちらも無ければ、ID は出さずに文言だけで案内する
    """
    named = str(batch.get("originHint", "")).strip()
    if named:
        return "「" + named + "」が見える画面"
    for c in cands:
        for pre in ("aria/", "text/"):
            if c.startswith(pre):
                name = c[len(pre):].split("[")[0].strip()
                if name:
                    return "「" + name + "」が見える画面"
    return "繰り返しの最初の操作ができる画面"


def _warn_exec_paths(args) -> None:
    """実行環境のパスを渡すべき引数に、変換環境のパスが来ていないか警告する。

    --details / --driver-exe / --pad-out-dir は生成物に文字列として埋め込まれ、
    PAD を動かす PC 側で解決される。ここにリポジトリ相対のパスを渡すと生成は
    成功してしまい、実行時に「CSVファイルから読み取る」などが失敗する。
    生成時点で気づけるように、Windows の絶対パスに見えないものを指摘する。"""
    def looks_windows_abs(s: str) -> bool:
        return len(s) > 2 and s[1] == ":" and s[2] in "\\/" or s.startswith("\\\\")

    checks = [("--details", args.details),
              ("--driver-exe", args.driver_exe),
              ("--pad-out-dir", args.pad_out_dir)]
    bad = [(name, val) for name, val in checks if val and not looks_windows_abs(val)]
    if not bad:
        return
    print("  ⚠ 実行環境（PAD を動かす PC）のパスに見えない引数があります。")
    print("    生成物にそのまま埋め込まれるため、実行時に読み取りが失敗します。")
    for name, val in bad:
        print(f"      {name} = {val}")
    print('    例: --details "C:\\temp\\sample_batch.csv"')


def _use_utf8_stdout() -> None:
    """標準出力を UTF-8 にする。

    完了メッセージに 📄 や ⚠ を使っているため、コンソールのコードページが
    cp1252（英語版 Windows など）だと UnicodeEncodeError で落ちる。日本語版の
    Windows では起きないので気づきにくいが、EXE を配ったときに相手側の
    ロケール次第で壊れる。errors="replace" も付けて、万一表示できない文字が
    あっても処理そのものは止めない。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


# セクションごとに生成器が扱えるステップ種別。ここに無い種別を書いても
# 黙って捨てられるため、生成時に警告する。たとえば setup に assertText を
# 置いても何も出力されない（起点の確認はループ先頭の要素から自動生成する）。
SECTION_STEPS = {
    "setup": {"comment", "setViewport", "navigate", "click", "doubleClick", "change"},
    "loop": {"comment", "screenshot", "assertText", "click", "doubleClick", "change"},
    "recover": {"comment", "navigate", "click", "doubleClick", "change"},
    "teardown": {"comment", "click", "doubleClick", "change"},
}


def _warn_unsupported_steps(batch: dict) -> list:
    """バッチ定義の中で、そのセクションでは無視される種別を拾う。"""
    warns = []
    # 手動ログイン専用なので、ログイン操作は変換に含めない。録画に混ざって
    # いたら知らせる。生成物には入らないが、録画ファイル自体に平文が残る。
    if any(st.get("type") == "change" for st in batch.get("setup") or []):
        warns.append(
            "setup の入力操作は変換に含めません（PAD 版は手動ログイン専用）。"
            "起点までの移動はクリックだけを再生します。"
            "録画はログイン直後から始めてください。"
            "録画 JSON にパスワードが残っている場合は削除を")
    for sec, allowed in SECTION_STEPS.items():
        for i, st in enumerate(batch.get(sec) or [], 1):
            t = st.get("type", "")
            if t and t not in allowed:
                warns.append(
                    f"{sec} の {i} 番目: 種別 '{t}' は {sec} では無視されます"
                    f"（使えるのは {' / '.join(sorted(allowed))}）")
    return warns


def main() -> None:
    _use_utf8_stdout()
    p = argparse.ArgumentParser(
        description="PAD 版バッチの参照実装（WebDriver を HTTP 直叩き・拡張機能不要）")
    p.add_argument("--batch", required=True, help="バッチ定義 JSON")
    p.add_argument("--details", required=True, help="明細 CSV / xlsx")
    p.add_argument("--values", help="共通値 JSON（任意）")
    p.add_argument("--id-column", help="ID 列（既定: 先頭列）")
    p.add_argument("--driver-url", default="http://127.0.0.1:9515",
                   help="WebDriver の URL（既定: http://127.0.0.1:9515）")
    p.add_argument("--browser-name", default="MicrosoftEdge",
                   help="MicrosoftEdge / chrome")
    p.add_argument("--out-dir", default="output")
    p.add_argument("--trace", help="PAD 用手順書（Markdown）の出力先")
    p.add_argument("--robin", help="PAD に貼り付ける Robin コードの出力先（ブラウザ操作は不要）")
    p.add_argument("--driver-exe", default=r"C:\WebDriver\msedgedriver.exe",
                   help="Robin 生成時に埋め込む msedgedriver のパス")
    p.add_argument("--pad-out-dir", default=r"C:\PAD\output",
                   help="Robin 生成時に埋め込む出力フォルダ")
    p.add_argument("--pad-browser", choices=["edge", "chrome"], default="edge",
                   help="生成する Robin が使うブラウザー（既定 edge）。"
                        "生成後も Robin 冒頭の Browser を書き換えれば切り替えられる")
    p.add_argument("--shot-name", default="%RowId%__%RowKey%__%Stamp%",
                   help="エビデンスのファイル名（拡張子なし）。"
                        "%RowId% / %RowKey% / %Stamp% を差し込める。"
                        "例: 【注文受諾】%RowId%_〇〇株式会社")
    p.add_argument("--auto-driver", action="store_true",
                   help="Selenium Manager でドライバーを自動取得する行を入れる"
                        "（selenium-manager-windows.exe を実行環境の BaseDir に置くこと）")
    p.add_argument("--proxy", default="",
                   help="外部サイト用プロキシ host:port（例 proxy.example.com:8080）。"
                        "localhost/file:// は通さない。省略時はプロキシなし")
    p.add_argument("--max-items", type=int, default=0)
    p.add_argument("--stop-on-error", action="store_true")
    args = p.parse_args()

    batch = load_recording(args.batch)
    common = load_recording(args.values) if args.values else {}
    # Robin 生成のみの場合、--details は「会社 PC 側のパス」でよく、手元に実体が無くてよい
    if args.robin and not os.path.exists(args.details):
        headers, rows = [args.id_column or "ID"], []
    else:
        headers, rows = load_details(args.details)
        if not rows and not args.robin:
            sys.exit("明細が 0 件です: " + args.details)
    id_col = args.id_column or headers[0]
    if id_col not in headers:
        sys.exit(f"ID 列 '{id_col}' が明細の列名にありません: {headers}")
    if args.max_items:
        rows = rows[:args.max_items]

    if args.robin:
        out = write_robin(batch, args.details, id_col, args.robin,
                          args.shot_name,
                          args.driver_exe, args.pad_out_dir, args.proxy,
                          args.auto_driver, args.pad_browser)
        js_out = out[:-len(".robin.txt")] + ".jsact.js" if out.endswith(".robin.txt") \
            else os.path.splitext(out)[0] + ".jsact.js"
        print(f"📄 PAD 用 Robin コード: {out}")
        print(f"📄 共通 JavaScript   : {js_out}")
        _warn_exec_paths(args)
        for w in _warn_unsupported_steps(batch):
            print("  ⚠ " + w)
        print(f"   → .js は PAD 実行 PC の {args.pad_out_dir} に置くこと")
        if not args.trace:
            return

    os.makedirs(args.out_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    logf = open(os.path.join(args.out_dir, f"pad_{stamp}.log"), "w", encoding="utf-8")

    def log(msg: str = "") -> None:
        print(msg)
        logf.write(str(msg) + "\n")
        logf.flush()

    log(f"バッチ: {batch.get('title', '')}")
    log(f"明細: {args.details}（{len(rows)} 件 / ID列: {id_col}）")
    log(f"WebDriver: {args.driver_url}")

    trace: list = []
    drv = WebDriverHTTP(args.driver_url, args.browser_name, trace)
    results = None
    try:
        drv.start()
        results = run(batch, rows, common, drv, args.out_dir, id_col,
                      log=log, stop_on_error=args.stop_on_error)
    except Exception as e:
        log(f"\n❌ 続行できないエラーで中断しました: {str(e)[:300]}")
        log("   よくある原因: (1) msedgedriver.exe が未起動 "
            "(2) Edge とドライバのバージョン不一致 "
            "(3) {{SECRET:...}} の環境変数が未設定 (4) 開始 URL に到達できない")
    finally:
        drv.quit()

    if args.trace:
        log(f"\n📄 PAD 用手順書: {write_trace(trace, args.trace, batch.get('title', ''))}")

    if results is None:
        logf.close()
        sys.exit(2)

    import csv as _csv
    rp = os.path.join(args.out_dir, f"pad_result_{stamp}.csv")
    with open(rp, "w", newline="", encoding="utf-8-sig") as f:
        w = _csv.DictWriter(f, fieldnames=["ID", "結果", "理由", "エビデンス"])
        w.writeheader()
        w.writerows(results)
    ok = sum(1 for r in results if r["結果"] == "成功")
    ng = sum(1 for r in results if r["結果"] == "失敗")
    sk = sum(1 for r in results if r["結果"] == "スキップ")
    log(f"\n===== 結果: {len(results)} 件中  成功 {ok} / 失敗 {ng} / スキップ {sk} =====")
    log(f"結果 CSV: {rp}")
    logf.close()
    if ng:
        sys.exit(1)


if __name__ == "__main__":
    main()
